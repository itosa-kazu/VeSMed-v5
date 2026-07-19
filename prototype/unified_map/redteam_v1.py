"""Post-selection red-team for the sealed F18 Unified Clinical Map candidate."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .benchmark_v1_contract import (
    PublicTrainingRecord,
    RolloutTarget,
    build_public_training_record,
    classify_state_pair,
    oracle_signature,
    rollout_scores,
    treatment_regret,
)
from .benchmark_v1_runner import _flatten_probe_result, _oracle_rows, verify_run_bundle
from .candidate_families import make_candidate
from .candidate_seal import verify_candidate_seal
from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes, digest_json
from .extensions import _open_custody
from .schema import EventKind, PlanKind
from .world_registry import WORLD_REGISTRY
from .worlds.base import MicroWorld, PrivateEpisode, WorldSplit
from .worlds.w16 import W16World, make_w16_extension_custody
from .worlds.w17 import W17World, make_w17_extension_custody


REDTEAM_PROTOCOL = "ucm-post-selection-redteam/1"
TRAIN_SEED = 910_001
TEST_SEED = 920_003
MODEL_SEED = 104_729


def _standard_records(
    world: MicroWorld,
    *,
    count: int = 64,
    seed: int = TRAIN_SEED,
    include: Callable[[PrivateEpisode], bool] | None = None,
) -> tuple[PublicTrainingRecord, ...]:
    rows: list[PublicTrainingRecord] = []
    index = 0
    while len(rows) < count:
        episode = world.generate_episode(WorldSplit.TRAIN, seed, index)
        index += 1
        if include is not None and not include(episode):
            continue
        rows.append(
            build_public_training_record(
                world, episode, oracle_seed=seed + 100_000 + index
            )
        )
    return tuple(rows)


def _fit_standard(
    world: MicroWorld,
    *,
    count: int = 64,
    include: Callable[[PrivateEpisode], bool] | None = None,
) -> Any:
    candidate = make_candidate("F18")
    candidate.fit(
        (world.catalog,),
        _standard_records(world, count=count, include=include),
        model_seed=MODEL_SEED,
    )
    return candidate


def _extension_record(world: Any, episode: PrivateEpisode, oracle_seed: int) -> PublicTrainingRecord:
    rows: list[RolloutTarget] = []
    for horizon in world.extension_catalog.horizons:
        for index, policy in enumerate(world.extension_policy_set(horizon)):
            oracle = world.counterfactual(
                episode, policy, horizon, oracle_seed + horizon * 1009 + index
            )
            rows.append(
                RolloutTarget(
                    horizon,
                    policy,
                    oracle_signature(oracle),
                    oracle.expected_utility,
                )
            )
    return PublicTrainingRecord(
        episode.public_history, dict(episode.diagnostic_target), tuple(rows)
    )


def _fit_extension(world: Any, *, count: int = 64) -> Any:
    records = tuple(
        _extension_record(
            world,
            world.generate_extension_episode(WorldSplit.TRAIN, TRAIN_SEED, index),
            TRAIN_SEED + 200_000 + index,
        )
        for index in range(count)
    )
    candidate = make_candidate("F18")
    candidate.fit(
        (world.extension_catalog,), records, model_seed=MODEL_SEED
    )
    return candidate


def _distance(left: Any, right: Any) -> float:
    a = np.asarray(left.distance_vector, dtype=np.float64)
    b = np.asarray(right.distance_vector, dtype=np.float64)
    if a.shape != b.shape:
        return math.inf
    return float(np.linalg.norm(a - b))


def _extension_redteam() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for slot, world_type, custody_factory in (
        ("W16", W16World, make_w16_extension_custody),
        ("W17", W17World, make_w17_extension_custody),
    ):
        custody = custody_factory()
        primary_world = world_type(extension_commitment=custody.public.commitment)
        primary_candidate = _fit_standard(primary_world, count=64)
        primary_episode = primary_world.generate_episode(
            WorldSplit.SEALED_TEST, TEST_SEED, 7
        )
        primary_state = primary_candidate.initialize(
            primary_episode.public_history, inference_seed=1
        )
        reveal = _open_custody(custody)
        world = primary_world.activate_extension(reveal)
        new_policy = world.extension_policy_set(4)[-1]
        old_state_first_query = primary_candidate.rollout(
            primary_state, new_policy, 4, query_seed=2
        )
        migrated = _fit_extension(world, count=64)
        extension_episode = world.generate_extension_episode(
            WorldSplit.SEALED_TEST, TEST_SEED, 11
        )
        initialization_refusal = None
        try:
            primary_candidate.initialize(extension_episode.public_history, inference_seed=3)
        except ProtocolViolation as exc:
            initialization_refusal = str(exc)
        migrated_state = migrated.initialize(
            extension_episode.public_history, inference_seed=4
        )
        migrated_rollout = migrated.rollout(migrated_state, new_policy, 4, query_seed=5)

        if slot == "W16":
            pair = world.extension_result_pair(TEST_SEED + 16)
        else:
            pair = tuple(
                world.as_extension_episode(episode)
                for episode in world.extension_split_pair(TEST_SEED + 17)
            )
        pair_states = tuple(
            migrated.initialize(episode.public_history, inference_seed=10 + index)
            for index, episode in enumerate(pair)
        )
        left_oracles: list[Any] = []
        right_oracles: list[Any] = []
        for horizon in world.extension_catalog.horizons:
            for policy_index, policy in enumerate(world.extension_policy_set(horizon)):
                left_oracles.append(
                    world.counterfactual(
                        pair[0], policy, horizon, TEST_SEED + 1000 + horizon * 10 + policy_index
                    )
                )
                right_oracles.append(
                    world.counterfactual(
                        pair[1], policy, horizon, TEST_SEED + 1000 + horizon * 10 + policy_index
                    )
                )
        classification = classify_state_pair(
            pair_states[0], pair_states[1], left_oracles, right_oracles
        )
        rows[slot] = {
            "commitment_preceded_reveal": True,
            "primary_catalog_digest": primary_world.catalog.digest,
            "extension_catalog_digest": world.extension_catalog.digest,
            "old_state_hash": primary_state.state_hash,
            "old_state_new_query_abstained": old_state_first_query.abstained,
            "old_encoder_extension_initialization_refusal": initialization_refusal,
            "migrated_state_hash": migrated_state.state_hash,
            "migrated_rollout_abstained": migrated_rollout.abstained,
            "pair_state_distance": _distance(pair_states[0], pair_states[1]),
            "pair_classification": classification,
            "migration_cost": {
                "candidate_core_changed_bytes": 0,
                "training_examples": 64,
                "history_replay_required": True,
                "new_catalog_model_required": True,
                "local_in_place_refinement": False,
            },
        }
    return rows


def _fresh_collision_redteam() -> dict[str, Any]:
    results: dict[str, Any] = {}
    for slot in ("W04", "W08", "W19", "W20"):
        declaration = WORLD_REGISTRY[slot]
        panel = declaration.panels[0]
        world = panel.instantiate()
        candidate = _fit_standard(world, count=64)
        rows: list[dict[str, Any]] = []
        for probe in panel.probes:
            method = getattr(world, probe.method_name)
            count = min(16, probe.indexed_count)
            for index in range(count):
                seed = TEST_SEED + int(slot[1:]) * 10_000 + index
                result = method(seed, probe_index=index) if probe.indexed_count > 1 else method(seed)
                for group_index, episodes in enumerate(
                    _flatten_probe_result(result, probe.mapping_result)
                ):
                    if len(episodes) < 2:
                        continue
                    states = tuple(
                        candidate.initialize(
                            episode.public_history, inference_seed=seed + side
                        )
                        for side, episode in enumerate(episodes[:2])
                    )
                    left_oracles: list[Any] = []
                    right_oracles: list[Any] = []
                    for horizon in world.catalog.horizons:
                        left_oracles.extend(_oracle_rows(world, episodes[0], horizon, seed + 100))
                        right_oracles.extend(_oracle_rows(world, episodes[1], horizon, seed + 100))
                    classification = classify_state_pair(
                        states[0], states[1], left_oracles, right_oracles
                    )
                    rows.append(
                        {
                            "probe_id": probe.probe_id,
                            "probe_index": index,
                            "group_index": group_index,
                            **classification,
                        }
                    )
        collisions = [row for row in rows if row["dangerous_collision"]]
        false_splits = [row for row in rows if row["false_split"]]
        results[slot] = {
            "pair_count": len(rows),
            "dangerous_collision_count": len(collisions),
            "false_split_count": len(false_splits),
            "worst_collision": max(
                collisions, key=lambda item: item["oracle_distance"], default=None
            ),
        }
    return results


def _ood_redteam() -> dict[str, Any]:
    world = WORLD_REGISTRY["W18"].panels[0].instantiate()
    candidate = _fit_standard(world, count=64)
    rows = []
    for index in range(128):
        episode = world.generate_episode(WorldSplit.SEALED_TEST, TEST_SEED + 18_000, index)
        state = candidate.initialize(episode.public_history, inference_seed=index)
        prediction = candidate.diagnose(
            state, world.catalog.diagnostic_labels, query_seed=index + 1000
        )
        target = float(episode.diagnostic_target["unknown"])
        predicted = float(prediction.probabilities["unknown"])
        rows.append(
            {
                "index": index,
                "target_unknown": target,
                "predicted_unknown": predicted,
                "unsafe_forced_known": target >= 0.5 and predicted < 0.5,
                "false_unknown": target < 0.5 and predicted >= 0.5,
                "brier": (target - predicted) ** 2,
            }
        )
    return {
        "episode_count": len(rows),
        "unsafe_forced_known_count": sum(row["unsafe_forced_known"] for row in rows),
        "false_unknown_count": sum(row["false_unknown"] for row in rows),
        "unknown_brier_mean": float(np.mean([row["brier"] for row in rows])),
        "worst_rows": sorted(rows, key=lambda item: item["brier"], reverse=True)[:8],
    }


def _new_combination_redteam() -> dict[str, Any]:
    world = WORLD_REGISTRY["W13"].panels[0].instantiate()
    candidate = _fit_standard(
        world,
        count=64,
        include=lambda episode: int(episode.invariant_parameters["interaction_class"]) != 2,
    )
    rows = []
    index = 2
    while len(rows) < 64:
        episode = world.generate_episode(WorldSplit.SEALED_TEST, TEST_SEED + 13_000, index)
        index += 3
        state = candidate.initialize(episode.public_history, inference_seed=index)
        diagnosis = candidate.diagnose(
            state, world.catalog.diagnostic_labels, query_seed=index + 100
        )
        policies = world.policy_set(4)
        predictions = [
            candidate.rollout(state, policy, 4, query_seed=index + 200 + p_index)
            for p_index, policy in enumerate(policies)
        ]
        oracles = [
            world.counterfactual(
                episode, policy, 4, TEST_SEED + 300_000 + index * 100 + p_index
            )
            for p_index, policy in enumerate(policies)
        ]
        rows.append(
            {
                "c2_probability": float(diagnosis.probabilities["C2"]),
                "c2_top1": max(diagnosis.probabilities, key=diagnosis.probabilities.get)
                == "C2",
                "regret": treatment_regret(predictions, oracles)["regret"],
                "mean_rollout_rmse": float(
                    np.mean(
                        [
                            rollout_scores(prediction, oracle)["signature_rmse"]
                            for prediction, oracle in zip(predictions, oracles, strict=True)
                        ]
                    )
                ),
            }
        )
    return {
        "train_classes": [0, 1],
        "held_out_test_class": 2,
        "episode_count": len(rows),
        "diagnosis_top1_accuracy": float(np.mean([row["c2_top1"] for row in rows])),
        "mean_c2_probability": float(np.mean([row["c2_probability"] for row in rows])),
        "mean_treatment_regret": float(np.mean([row["regret"] for row in rows])),
        "mean_rollout_rmse": float(np.mean([row["mean_rollout_rmse"] for row in rows])),
    }


def _new_task_redteam() -> dict[str, Any]:
    world = WORLD_REGISTRY["W01"].panels[0].instantiate()
    candidate = _fit_standard(world, count=64)

    def rows(split: WorldSplit, seed: int, count: int) -> tuple[np.ndarray, np.ndarray]:
        features = []
        targets = []
        for index in range(count):
            episode = world.generate_episode(split, seed, index)
            state = candidate.initialize(episode.public_history, inference_seed=index)
            features.append(state.distance_vector)
            targets.append(float(episode.factual_utility))
        return np.asarray(features, dtype=np.float64), np.asarray(targets, dtype=np.float64)

    train_x, train_y = rows(WorldSplit.TRAIN, TRAIN_SEED + 1, 64)
    test_x, test_y = rows(WorldSplit.VALIDATION, TEST_SEED + 1, 64)
    design = np.concatenate((np.ones((len(train_x), 1)), train_x), axis=1)
    penalty = np.eye(design.shape[1]) * 1e-3
    penalty[0, 0] = 0.0
    weights = np.linalg.pinv(design.T @ design + penalty) @ design.T @ train_y
    prediction = np.concatenate((np.ones((len(test_x), 1)), test_x), axis=1) @ weights
    baseline = np.full_like(test_y, train_y.mean())
    return {
        "task": "realized_factual_utility_readout_not_used_by_candidate_fit",
        "encoder_frozen": True,
        "query_reads_state_only": True,
        "train_examples": len(train_y),
        "test_examples": len(test_y),
        "state_dimension": train_x.shape[1],
        "state_only_probe_rmse": float(np.sqrt(np.mean((prediction - test_y) ** 2))),
        "constant_baseline_rmse": float(np.sqrt(np.mean((baseline - test_y) ** 2))),
    }


def _history_deletion_redteam() -> dict[str, Any]:
    world = WORLD_REGISTRY["W20"].panels[0].instantiate()
    candidate = _fit_standard(world, count=64)
    episode = next(
        world.generate_episode(WorldSplit.SEALED_TEST, TEST_SEED + 20_000, index)
        for index in range(64)
        if any(event.kind is EventKind.PERFORMED_TREATMENT for event in world.generate_episode(WorldSplit.SEALED_TEST, TEST_SEED + 20_000, index).public_history.events)
    )
    history = episode.public_history
    treatment_index = next(
        index
        for index, event in enumerate(history.events)
        if event.kind is EventKind.PERFORMED_TREATMENT
    )
    observation_index = next(
        index
        for index, event in enumerate(history.events)
        if event.kind is EventKind.OBSERVATION_AVAILABLE
    )

    def without(index: int) -> Any:
        return type(history)(
            events=history.events[:index] + history.events[index + 1 :],
            as_of_available_at=history.as_of_available_at,
            catalog_digest=history.catalog_digest,
        )

    full = candidate.initialize(history, inference_seed=1)
    no_treatment = candidate.initialize(without(treatment_index), inference_seed=2)
    no_old_observation = candidate.initialize(without(observation_index), inference_seed=3)
    no_op = world.policy_set(8)[0]
    full_rollout = candidate.rollout(full, no_op, 8, query_seed=10)
    treatment_rollout = candidate.rollout(no_treatment, no_op, 8, query_seed=10)
    observation_rollout = candidate.rollout(no_old_observation, no_op, 8, query_seed=10)
    return {
        "full_state_hash": full.state_hash,
        "delete_treatment": {
            "state_changed": no_treatment.state_hash != full.state_hash,
            "state_distance": _distance(full, no_treatment),
            "utility_prediction_change": abs(
                full_rollout.expected_utility - treatment_rollout.expected_utility
            ),
        },
        "delete_oldest_observation": {
            "state_changed": no_old_observation.state_hash != full.state_hash,
            "state_distance": _distance(full, no_old_observation),
            "utility_prediction_change": abs(
                full_rollout.expected_utility - observation_rollout.expected_utility
            ),
            "causal_relevance_not_asserted": True,
        },
    }


def _time_scale_from_complete(reference_run: Path) -> dict[str, Any]:
    summary = verify_run_bundle(reference_run)
    buckets: dict[tuple[str, int], list[float]] = {}
    for line in (reference_run / summary["raw_episode_file"]).read_text(
        encoding="utf-8"
    ).splitlines():
        row = json.loads(line)
        for policy in row["policy_rows"]:
            key = (policy["task"], int(policy["horizon"]))
            buckets.setdefault(key, []).append(float(policy["scores"]["signature_rmse"]))
    result = {
        f"{task}_h{horizon}": float(np.mean(values))
        for (task, horizon), values in sorted(buckets.items())
    }
    result["natural_h8_to_h1_ratio"] = result["natural_forecast_h8"] / max(
        result["natural_forecast_h1"], 1e-12
    )
    result["intervention_h8_to_h1_ratio"] = result["intervention_h8"] / max(
        result["intervention_h1"], 1e-12
    )
    return result


def run_redteam(*, seal_path: Path, output_root: Path) -> Path:
    started = time.perf_counter()
    seal = verify_candidate_seal(seal_path)
    repo_root = Path(__file__).resolve().parents[2]
    complete_run = repo_root / seal["complete_run"]["relative_path"]
    report = {
        "protocol": REDTEAM_PROTOCOL,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "candidate_seal_digest": digest_bytes(seal_path.read_bytes()),
        "candidate_source_digest": seal["candidate_source_binding"]["source_digest"],
        "complete_run_id": seal["complete_run"]["run_id"],
        "post_selection_candidate_mutation": False,
        "public_redteam_seeds": {
            "train": TRAIN_SEED,
            "test": TEST_SEED,
            "model": MODEL_SEED,
        },
        "extension_new_check_and_treatment": _extension_redteam(),
        "fresh_collision_probes": _fresh_collision_redteam(),
        "fresh_ood": _ood_redteam(),
        "held_out_nonlinear_combination": _new_combination_redteam(),
        "new_state_only_task": _new_task_redteam(),
        "history_deletion": _history_deletion_redteam(),
        "time_scale": _time_scale_from_complete(complete_run),
        "claim_boundary": {
            "synthetic_only": True,
            "clinical_validity_claimed": False,
            "post_selection_redteam": True,
        },
    }
    report["wall_seconds"] = time.perf_counter() - started
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-F18-redteam-{uuid.uuid4().hex[:10]}"
    output = output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    result_path = output / "redteam.json"
    result_path.write_bytes(canonical_json_bytes(report))
    source_raw = Path(__file__).read_bytes()
    manifest = {
        "protocol": "ucm-post-selection-redteam-manifest/1",
        "run_id": run_id,
        "files": [
            {
                "name": result_path.name,
                "byte_length": result_path.stat().st_size,
                "sha256": digest_bytes(result_path.read_bytes()),
            }
        ],
        "source": {
            "relative_path": "prototype/unified_map/redteam_v1.py",
            "byte_length": len(source_raw),
            "sha256": digest_bytes(source_raw),
        },
    }
    manifest["bundle_root"] = digest_json(manifest)
    (output / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Run sealed F18 post-selection redteam")
    parser.add_argument(
        "--seal", type=Path, default=Path("research/unified_map/CANDIDATE_SEAL.json")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("results/unified_map/redteam")
    )
    args = parser.parse_args()
    print(run_redteam(seal_path=args.seal, output_root=args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

