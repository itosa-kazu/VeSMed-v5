"""Unified training/evaluation runner for frozen UCM benchmark v1.

The runner owns judge-side world/oracle access.  Candidate methods receive only
public training projections or one shared state plus a non-patient query.  Every
run is published to a new directory by atomic rename and binds the benchmark
freeze, candidate/runner source hashes, configuration and raw per-query rows.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import math
import multiprocessing
import os
import shutil
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .benchmark_v1_contract import (
    DiagnosisPrediction,
    PublicTrainingRecord,
    RolloutPrediction,
    SharedPatientState,
    build_public_training_record,
    classify_state_pair,
    diagnosis_scores,
    oracle_signature,
    rollout_scores,
    treatment_regret,
)
from .benchmark_v1_freeze import (
    FREEZE_FILENAME,
    MODEL_SEEDS,
    REPLICATE_IDS,
    SEED_SECRET_SCHEMA,
    SPLIT_EPISODES_PER_PANEL,
    build_seed_reveal,
    verify_freeze_manifest_bytes,
)
from .candidate_families import make_candidate
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .schema import PlanKind, VisibleDelta
from .world_registry import EXTENSION_WORLD_REGISTRY, WORLD_REGISTRY
from .worlds.base import CounterfactualOracle, MicroWorld, PrivateEpisode, WorldSplit


RUN_PROTOCOL = "ucm-benchmark-v1-run/1"
RUN_MANIFEST_PROTOCOL = "ucm-benchmark-v1-run-manifest/1"
SEED_DERIVATION_DOMAIN = b"UCM_BENCHMARK_V1_DERIVED_SEED\0"
DEFAULT_RESULTS_ROOT = Path("results/unified_map/runs")


@dataclass(frozen=True, slots=True)
class RunConfig:
    experiment_id: str
    family_code: str
    parameters: dict[str, Any]
    world_slots: tuple[str, ...]
    replicate_ids: tuple[str, ...]
    train_episodes_per_panel: int
    validation_episodes_per_panel: int
    test_episodes_per_panel: int
    pair_probe_limit_per_declaration: int = 1

    def __post_init__(self) -> None:
        for value, label in (
            (self.experiment_id, "experiment_id"),
            (self.family_code, "family_code"),
        ):
            if type(value) is not str or not value or value.strip() != value:
                raise ProtocolViolation(f"{label} must be a canonical string")
        validate_json_like(self.parameters, path="run parameters")
        if (
            type(self.world_slots) is not tuple
            or not self.world_slots
            or any(slot not in WORLD_REGISTRY for slot in self.world_slots)
            or len(set(self.world_slots)) != len(self.world_slots)
        ):
            raise ProtocolViolation("run world_slots are invalid")
        if (
            type(self.replicate_ids) is not tuple
            or not self.replicate_ids
            or any(value not in REPLICATE_IDS for value in self.replicate_ids)
            or len(set(self.replicate_ids)) != len(self.replicate_ids)
        ):
            raise ProtocolViolation("run replicate_ids are invalid")
        limits = {
            "train": self.train_episodes_per_panel,
            "validation": self.validation_episodes_per_panel,
            "sealed_test": self.test_episodes_per_panel,
        }
        if any(type(value) is not int or value <= 0 for value in limits.values()):
            raise ProtocolViolation("episode counts must be positive integers")
        if any(limits[key] > SPLIT_EPISODES_PER_PANEL[key] for key in limits):
            raise ProtocolViolation("run episode count exceeds frozen allocation")
        if (
            type(self.pair_probe_limit_per_declaration) is not int
            or self.pair_probe_limit_per_declaration < 0
        ):
            raise ProtocolViolation("pair probe limit must be nonnegative")

    @property
    def complete_benchmark(self) -> bool:
        return (
            self.world_slots == tuple(WORLD_REGISTRY)
            and self.replicate_ids == REPLICATE_IDS
            and self.train_episodes_per_panel == SPLIT_EPISODES_PER_PANEL["train"]
            and self.validation_episodes_per_panel
            == SPLIT_EPISODES_PER_PANEL["validation"]
            and self.test_episodes_per_panel
            == SPLIT_EPISODES_PER_PANEL["sealed_test"]
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "family_code": self.family_code,
            "parameters": self.parameters,
            "world_slots": list(self.world_slots),
            "replicate_ids": list(self.replicate_ids),
            "train_episodes_per_panel": self.train_episodes_per_panel,
            "validation_episodes_per_panel": self.validation_episodes_per_panel,
            "test_episodes_per_panel": self.test_episodes_per_panel,
            "pair_probe_limit_per_declaration": self.pair_probe_limit_per_declaration,
            "complete_benchmark": self.complete_benchmark,
        }


def screening_config(
    experiment_id: str,
    family_code: str,
    *,
    parameters: dict[str, Any] | None = None,
    world_slots: tuple[str, ...] = ("W01", "W04", "W08", "W15", "W18", "W19", "W20"),
) -> RunConfig:
    return RunConfig(
        experiment_id,
        family_code,
        parameters or {},
        world_slots,
        (REPLICATE_IDS[0],),
        12,
        4,
        6,
        1,
    )


def complete_config(
    experiment_id: str,
    family_code: str,
    *,
    parameters: dict[str, Any] | None = None,
    pair_probe_limit_per_declaration: int = 2,
) -> RunConfig:
    return RunConfig(
        experiment_id,
        family_code,
        parameters or {},
        tuple(WORLD_REGISTRY),
        REPLICATE_IDS,
        SPLIT_EPISODES_PER_PANEL["train"],
        SPLIT_EPISODES_PER_PANEL["validation"],
        SPLIT_EPISODES_PER_PANEL["sealed_test"],
        pair_probe_limit_per_declaration,
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _decode_canonical(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} is unavailable or invalid") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    return value


def _load_authority(freeze_path: Path, secret_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = verify_freeze_manifest_bytes(freeze_path.read_bytes())
    secret = _decode_canonical(secret_path, "benchmark seed secret")
    if secret.get("schema_version") != SEED_SECRET_SCHEMA:
        raise ProtocolViolation("benchmark seed secret schema mismatch")
    # Building the reveal verifies every commitment without publishing it.
    build_seed_reveal(secret, freeze)
    return freeze, secret


def _derived_seed(root_seed: int, *parts: str | int) -> int:
    payload = canonical_json_bytes([root_seed, *parts])
    return int.from_bytes(
        hashlib.sha256(SEED_DERIVATION_DOMAIN + payload).digest()[:8], "big"
    ) & ((1 << 63) - 1)


def _replicate_secret(secret: dict[str, Any], replicate_id: str) -> dict[str, Any]:
    return next(row for row in secret["replicates"] if row["replicate_id"] == replicate_id)


def _panels(world_slots: Iterable[str]) -> list[tuple[str, Any, MicroWorld]]:
    rows: list[tuple[str, Any, MicroWorld]] = []
    for slot in world_slots:
        for panel in WORLD_REGISTRY[slot].panels:
            rows.append((slot, panel, panel.instantiate()))
    return rows


def _instantiate_panel(slot: str, panel_id: str) -> MicroWorld:
    for panel in WORLD_REGISTRY[slot].panels:
        if panel.panel_id == panel_id:
            return panel.instantiate()
    raise ProtocolViolation(f"unknown panel {slot}/{panel_id}")


def _oracle_worker_count(task_count: int) -> int:
    configured = int(os.environ.get("UCM_ORACLE_WORKERS", "0"))
    available = os.cpu_count() or 1
    requested = configured if configured > 0 else min(10, available)
    return max(1, min(requested, task_count))


def _build_training_record_worker(
    task: tuple[str, str, int, int, int],
) -> PublicTrainingRecord:
    slot, panel_id, generator_seed, oracle_root, index = task
    world = _instantiate_panel(slot, panel_id)
    episode = world.generate_episode(WorldSplit.TRAIN, generator_seed, index)
    return build_public_training_record(
        world,
        episode,
        oracle_seed=_derived_seed(oracle_root, index),
    )


_PUBLIC_TRAINING_CACHE: dict[
    tuple[tuple[tuple[str, str], ...], int, int],
    tuple[tuple[Any, ...], tuple[PublicTrainingRecord, ...]],
] = {}


def _training_records(
    panel_rows: list[tuple[str, Any, MicroWorld]],
    seed_row: dict[str, Any],
    count: int,
) -> tuple[tuple[Any, ...], tuple[PublicTrainingRecord, ...]]:
    # A multi-candidate suite must use byte-identical public training records.
    # Reuse them in-process; private episodes/oracles from the sealed test split
    # are intentionally never cached here or exposed to candidate code.
    cache_key = (
        tuple((slot, panel.panel_id) for slot, panel, _ in panel_rows),
        int(seed_row["train_root_seed"]),
        count,
    )
    cached = _PUBLIC_TRAINING_CACHE.get(cache_key)
    if cached is not None:
        return cached
    catalogs: list[Any] = []
    tasks: list[tuple[str, str, int, int, int]] = []
    for slot, panel, world in panel_rows:
        catalogs.append(world.catalog)
        generator_seed = _derived_seed(
            seed_row["train_root_seed"], slot, panel.panel_id, "population"
        )
        oracle_root = _derived_seed(
            seed_row["train_root_seed"], slot, panel.panel_id, "oracle"
        )
        tasks.extend(
            (slot, panel.panel_id, generator_seed, oracle_root, index)
            for index in range(count)
        )
    if count >= SPLIT_EPISODES_PER_PANEL["train"] and len(tasks) > 1:
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=_oracle_worker_count(len(tasks)), mp_context=context
        ) as executor:
            records = list(executor.map(_build_training_record_worker, tasks, chunksize=1))
    else:
        records = [_build_training_record_worker(task) for task in tasks]
    result = (tuple(catalogs), tuple(records))
    _PUBLIC_TRAINING_CACHE[cache_key] = result
    return result


def _oracle_rows(
    world: MicroWorld,
    episode: PrivateEpisode,
    horizon: int,
    oracle_root: int,
) -> tuple[CounterfactualOracle, ...]:
    return tuple(
        world.counterfactual(
            episode,
            plan,
            horizon,
            _derived_seed(oracle_root, horizon, index),
        )
        for index, plan in enumerate(world.policy_set(horizon))
    )


def _sealed_episode_worker(
    task: tuple[str, str, int, int, int],
) -> tuple[PrivateEpisode, dict[int, tuple[CounterfactualOracle, ...]]]:
    slot, panel_id, generator_seed, oracle_root, episode_index = task
    world = _instantiate_panel(slot, panel_id)
    episode = world.generate_episode(
        WorldSplit.SEALED_TEST, generator_seed, episode_index
    )
    episode_oracle_root = _derived_seed(oracle_root, episode_index)
    rows = {
        horizon: _oracle_rows(world, episode, horizon, episode_oracle_root)
        for horizon in world.catalog.horizons
    }
    return episode, rows


_SEALED_JUDGE_CACHE: dict[
    tuple[tuple[tuple[str, str], ...], int, int],
    dict[
        tuple[str, str, int],
        tuple[PrivateEpisode, dict[int, tuple[CounterfactualOracle, ...]]],
    ],
] = {}


def _sealed_evaluation_rows(
    panel_rows: list[tuple[str, Any, MicroWorld]],
    seed_row: dict[str, Any],
    count: int,
) -> dict[
    tuple[str, str, int],
    tuple[PrivateEpisode, dict[int, tuple[CounterfactualOracle, ...]]],
]:
    cache_key = (
        tuple((slot, panel.panel_id) for slot, panel, _ in panel_rows),
        int(seed_row["sealed_test_root_seed"]),
        count,
    )
    cached = _SEALED_JUDGE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    tasks: list[tuple[str, str, int, int, int]] = []
    keys: list[tuple[str, str, int]] = []
    for slot, panel, _ in panel_rows:
        generator_seed = _derived_seed(
            seed_row["sealed_test_root_seed"], slot, panel.panel_id, "population"
        )
        oracle_root = _derived_seed(
            seed_row["sealed_test_root_seed"], slot, panel.panel_id, "oracle"
        )
        for episode_index in range(count):
            tasks.append(
                (slot, panel.panel_id, generator_seed, oracle_root, episode_index)
            )
            keys.append((slot, panel.panel_id, episode_index))
    if count >= SPLIT_EPISODES_PER_PANEL["sealed_test"] and len(tasks) > 1:
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=_oracle_worker_count(len(tasks)), mp_context=context
        ) as executor:
            values = list(executor.map(_sealed_episode_worker, tasks, chunksize=1))
    else:
        values = [_sealed_episode_worker(task) for task in tasks]
    result = dict(zip(keys, values, strict=True))
    # Judge-side only: this object is never passed to fit/initialize/heads.  It
    # makes a multi-candidate suite reuse the exact sealed oracles instead of
    # recomputing them with candidate-dependent timing.
    _SEALED_JUDGE_CACHE[cache_key] = result
    return result


def _mean(rows: list[float]) -> float | None:
    return math.fsum(rows) / len(rows) if rows else None


def _aggregate_scalar_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if type(value) in {int, float} and type(value) is not bool and math.isfinite(float(value)):
                buckets.setdefault(key, []).append(float(value))
    return {
        key: {"mean": _mean(values), "min": min(values), "max": max(values), "exposure": len(values)}
        for key, values in sorted(buckets.items())
    }


def _evaluate_episode(
    *,
    candidate: Any,
    slot: str,
    panel: Any,
    world: MicroWorld,
    episode: PrivateEpisode,
    replicate_id: str,
    episode_index: int,
    oracle_root: int,
    raw_writer: Any,
    precomputed_oracles: dict[int, tuple[CounterfactualOracle, ...]] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    state = candidate.initialize(
        episode.public_history,
        inference_seed=_derived_seed(oracle_root, "initialize", episode_index),
    )
    initialize_ms = (time.perf_counter_ns() - started) / 1e6
    if type(state) is not SharedPatientState:
        raise ProtocolViolation("candidate initialize returned a non-shared state")
    state_hash = state.state_hash

    head_started = time.perf_counter_ns()
    diagnosis = candidate.diagnose(
        state,
        world.catalog.diagnostic_labels,
        query_seed=_derived_seed(oracle_root, "diagnosis", episode_index),
    )
    if type(diagnosis) is not DiagnosisPrediction:
        raise ProtocolViolation("candidate diagnose returned wrong type")
    diagnosis.validate_for(world.catalog)
    diagnosis_metric = diagnosis_scores(diagnosis, episode.diagnostic_target)
    head_ms = (time.perf_counter_ns() - head_started) / 1e6

    # Empty-delta replay is a frozen update identity probe.
    replay_state = candidate.update(
        state,
        VisibleDelta(episode.public_history.as_of_available_at, ()),
        inference_seed=_derived_seed(oracle_root, "update", episode_index),
    )
    update_replay_match = replay_state.state_hash == state_hash

    natural_scores: list[dict[str, float]] = []
    intervention_scores: list[dict[str, float]] = []
    regret_rows: list[dict[str, Any]] = []
    policy_raw_rows: list[dict[str, Any]] = []
    first_rollout: RolloutPrediction | None = None
    for horizon in world.catalog.horizons:
        policies = world.policy_set(horizon)
        oracles = (
            precomputed_oracles[horizon]
            if precomputed_oracles is not None
            else _oracle_rows(world, episode, horizon, oracle_root)
        )
        predictions: list[RolloutPrediction] = []
        for policy_index, (policy, oracle) in enumerate(zip(policies, oracles)):
            began = time.perf_counter_ns()
            prediction = candidate.rollout(
                state,
                policy,
                horizon,
                query_seed=_derived_seed(
                    oracle_root, "rollout", episode_index, horizon, policy_index
                ),
            )
            head_ms += (time.perf_counter_ns() - began) / 1e6
            if type(prediction) is not RolloutPrediction:
                raise ProtocolViolation("candidate rollout returned wrong type")
            if first_rollout is None:
                first_rollout = prediction
            scores = rollout_scores(prediction, oracle)
            if policy.kind in {PlanKind.NO_NEW_ACTION, PlanKind.CONTINUE_CURRENT}:
                natural_scores.append(scores)
                task = "natural_forecast"
            else:
                intervention_scores.append(scores)
                task = "intervention"
            predictions.append(prediction)
            policy_raw_rows.append(
                {
                    "task": task,
                    "horizon": horizon,
                    "policy_index": policy_index,
                    "policy": policy.to_wire(),
                    "state_hash": state_hash,
                    "prediction": {
                        "signature": list(prediction.signature),
                        "expected_utility": prediction.expected_utility,
                        "abstained": prediction.abstained,
                    },
                    "oracle": {
                        "signature": list(oracle_signature(oracle)),
                        "expected_utility": oracle.expected_utility,
                    },
                    "scores": scores,
                }
            )
        regret_rows.append({"horizon": horizon, **treatment_regret(predictions, oracles)})

    # Query-order purity: same state/query/seed after all other heads must match.
    diagnosis_again = candidate.diagnose(
        state,
        world.catalog.diagnostic_labels,
        query_seed=_derived_seed(oracle_root, "diagnosis", episode_index),
    )
    query_order_pure = diagnosis_again.probabilities == diagnosis.probabilities
    if first_rollout is None:
        raise ProtocolViolation("world exposed no rollout query")

    unknown_metrics: dict[str, float] = {}
    if "unknown" in world.catalog.diagnostic_labels:
        target_unknown = float(episode.diagnostic_target["unknown"])
        predicted_unknown = float(diagnosis.probabilities["unknown"])
        unknown_metrics = {
            "unknown_brier": (predicted_unknown - target_unknown) ** 2,
            "known_coverage": float(predicted_unknown < 0.5),
            "unsafe_non_abstain": float(target_unknown >= 0.5 and predicted_unknown < 0.5),
        }

    summary = {
        "world_slot": slot,
        "panel_id": panel.panel_id,
        "replicate_id": replicate_id,
        "episode_index": episode_index,
        "state_hash": state_hash,
        "state_bytes": state.canonical_size_bytes,
        "state_dimension": len(state.distance_vector),
        "compactness_class": state.compactness_class,
        "initialize_ms": initialize_ms,
        "head_ms": head_ms,
        "diagnosis": diagnosis_metric,
        "natural": _aggregate_scalar_rows(natural_scores),
        "intervention": _aggregate_scalar_rows(intervention_scores),
        "regret": _aggregate_scalar_rows(regret_rows),
        "ood": unknown_metrics,
        "update_replay_match": update_replay_match,
        "query_order_pure": query_order_pure,
    }
    raw_writer.write(
        canonical_json_bytes(
            {
                "protocol": "ucm-benchmark-v1-episode-raw/1",
                "episode_summary": summary,
                "diagnosis_prediction": diagnosis.probabilities,
                "diagnosis_target": episode.diagnostic_target,
                "policy_rows": policy_raw_rows,
            }
        )
    )
    return summary


def _flatten_probe_result(result: object, mapping: bool) -> list[tuple[PrivateEpisode, ...]]:
    if mapping:
        if type(result) is not dict:
            raise ProtocolViolation("mapping probe did not return a dict")
        rows = []
        for key in sorted(result):
            value = result[key]
            if type(value) is not tuple or not value or any(type(item) is not PrivateEpisode for item in value):
                raise ProtocolViolation("mapping probe contains invalid episodes")
            rows.append(value)
        return rows
    if type(result) is PrivateEpisode:
        return [(result,)]
    if type(result) is tuple and result and all(type(item) is PrivateEpisode for item in result):
        return [result]
    raise ProtocolViolation("probe result is invalid")


def _pair_probe_oracle_worker(
    task: tuple[str, str, str, str, int, bool, int, int],
) -> list[dict[str, Any]]:
    (
        slot,
        panel_id,
        probe_id,
        method_name,
        indexed_count,
        mapping_result,
        probe_index,
        seed,
    ) = task
    world = _instantiate_panel(slot, panel_id)
    method = getattr(world, method_name)
    result = (
        method(seed, probe_index=probe_index)
        if indexed_count > 1
        else method(seed)
    )
    rows: list[dict[str, Any]] = []
    for group_index, episodes in enumerate(
        _flatten_probe_result(result, mapping_result)
    ):
        if len(episodes) < 2:
            continue
        left, right = episodes[0], episodes[1]
        left_oracles: list[CounterfactualOracle] = []
        right_oracles: list[CounterfactualOracle] = []
        for horizon in world.catalog.horizons:
            left_oracles.extend(_oracle_rows(world, left, horizon, seed + 11))
            right_oracles.extend(_oracle_rows(world, right, horizon, seed + 11))
        rows.append(
            {
                "world_slot": slot,
                "panel_id": panel_id,
                "probe_id": probe_id,
                "probe_index": probe_index,
                "group_index": group_index,
                "seed": seed,
                "left": left,
                "right": right,
                "left_oracles": tuple(left_oracles),
                "right_oracles": tuple(right_oracles),
            }
        )
    return rows


_PAIR_JUDGE_CACHE: dict[
    tuple[tuple[tuple[str, str], ...], int, int],
    dict[tuple[str, str], list[dict[str, Any]]],
] = {}


def _precompute_pair_oracles(
    panel_rows: list[tuple[str, Any, MicroWorld]], seed_root: int, limit: int
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    cache_key = (
        tuple((slot, panel.panel_id) for slot, panel, _ in panel_rows),
        int(seed_root),
        limit,
    )
    cached = _PAIR_JUDGE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    tasks: list[tuple[str, str, str, str, int, bool, int, int]] = []
    for slot, panel, _ in panel_rows:
        if limit == 0 or slot in EXTENSION_WORLD_REGISTRY:
            continue
        for declaration in panel.probes:
            for probe_index in range(min(limit, declaration.indexed_count)):
                seed = _derived_seed(
                    seed_root,
                    slot,
                    panel.panel_id,
                    declaration.probe_id,
                    probe_index,
                )
                tasks.append(
                    (
                        slot,
                        panel.panel_id,
                        declaration.probe_id,
                        declaration.method_name,
                        declaration.indexed_count,
                        declaration.mapping_result,
                        probe_index,
                        seed,
                    )
                )
    if limit >= 2 and len(tasks) > 1:
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=_oracle_worker_count(len(tasks)), mp_context=context
        ) as executor:
            task_rows = list(executor.map(_pair_probe_oracle_worker, tasks, chunksize=1))
    else:
        task_rows = [_pair_probe_oracle_worker(task) for task in tasks]
    result: dict[tuple[str, str], list[dict[str, Any]]] = {
        (slot, panel.panel_id): [] for slot, panel, _ in panel_rows
    }
    for rows in task_rows:
        for row in rows:
            result[(row["world_slot"], row["panel_id"])].append(row)
    _PAIR_JUDGE_CACHE[cache_key] = result
    return result


def _pair_probes(
    *,
    candidate: Any,
    slot: str,
    panel: Any,
    world: MicroWorld,
    seed_root: int,
    limit: int,
    precomputed: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if precomputed is not None:
        rows = []
        for item in precomputed:
            seed = int(item["seed"])
            states = (
                candidate.initialize(item["left"].public_history, inference_seed=seed + 1),
                candidate.initialize(item["right"].public_history, inference_seed=seed + 2),
            )
            classification = classify_state_pair(
                states[0], states[1], item["left_oracles"], item["right_oracles"]
            )
            rows.append(
                {
                    "world_slot": item["world_slot"],
                    "panel_id": item["panel_id"],
                    "probe_id": item["probe_id"],
                    "probe_index": item["probe_index"],
                    "group_index": item["group_index"],
                    "left_state_hash": states[0].state_hash,
                    "right_state_hash": states[1].state_hash,
                    **classification,
                }
            )
        return rows
    if limit == 0 or slot in EXTENSION_WORLD_REGISTRY:
        return []
    rows: list[dict[str, Any]] = []
    for declaration in panel.probes:
        method = getattr(world, declaration.method_name)
        count = min(limit, declaration.indexed_count)
        for probe_index in range(count):
            seed = _derived_seed(seed_root, slot, panel.panel_id, declaration.probe_id, probe_index)
            result = (
                method(seed, probe_index=probe_index)
                if declaration.indexed_count > 1
                else method(seed)
            )
            for group_index, episodes in enumerate(
                _flatten_probe_result(result, declaration.mapping_result)
            ):
                if len(episodes) < 2:
                    continue
                left, right = episodes[0], episodes[1]
                states = (
                    candidate.initialize(left.public_history, inference_seed=seed + 1),
                    candidate.initialize(right.public_history, inference_seed=seed + 2),
                )
                left_oracles: list[CounterfactualOracle] = []
                right_oracles: list[CounterfactualOracle] = []
                for horizon in world.catalog.horizons:
                    left_oracles.extend(_oracle_rows(world, left, horizon, seed + 11))
                    right_oracles.extend(_oracle_rows(world, right, horizon, seed + 11))
                classification = classify_state_pair(
                    states[0], states[1], left_oracles, right_oracles
                )
                rows.append(
                    {
                        "world_slot": slot,
                        "panel_id": panel.panel_id,
                        "probe_id": declaration.probe_id,
                        "probe_index": probe_index,
                        "group_index": group_index,
                        "left_state_hash": states[0].state_hash,
                        "right_state_hash": states[1].state_hash,
                        **classification,
                    }
                )
    return rows


def _world_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    diagnosis = [row["diagnosis"] for row in rows]
    natural = [
        {key: value["mean"] for key, value in row["natural"].items()}
        for row in rows
    ]
    intervention = [
        {key: value["mean"] for key, value in row["intervention"].items()}
        for row in rows
    ]
    regret = [
        {key: value["mean"] for key, value in row["regret"].items()}
        for row in rows
    ]
    ood = [row["ood"] for row in rows if row["ood"]]
    return {
        "episode_count": len(rows),
        "diagnosis": _aggregate_scalar_rows(diagnosis),
        "natural": _aggregate_scalar_rows(natural),
        "intervention": _aggregate_scalar_rows(intervention),
        "regret": _aggregate_scalar_rows(regret),
        "ood": _aggregate_scalar_rows(ood),
        "state_bytes": _aggregate_scalar_rows([{"value": row["state_bytes"]} for row in rows]),
        "state_dimension": _aggregate_scalar_rows([{"value": row["state_dimension"]} for row in rows]),
        "initialize_ms": _aggregate_scalar_rows([{"value": row["initialize_ms"]} for row in rows]),
        "head_ms": _aggregate_scalar_rows([{"value": row["head_ms"]} for row in rows]),
        "update_replay_failure_count": sum(not row["update_replay_match"] for row in rows),
        "query_order_failure_count": sum(not row["query_order_pure"] for row in rows),
    }


def _macro(summary_by_world: dict[str, dict[str, Any]], path: tuple[str, ...]) -> float | None:
    values: list[float] = []
    for summary in summary_by_world.values():
        value: Any = summary
        try:
            for key in path:
                value = value[key]
        except KeyError:
            continue
        if type(value) in {int, float} and type(value) is not bool:
            values.append(float(value))
    return _mean(values)


def _replicate_summary(
    episode_rows: list[dict[str, Any]], pair_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    by_world: dict[str, list[dict[str, Any]]] = {}
    for row in episode_rows:
        by_world.setdefault(row["world_slot"], []).append(row)
    world_summaries = {slot: _world_summary(rows) for slot, rows in sorted(by_world.items())}
    headline = {
        "diagnosis_top1_accuracy": _macro(world_summaries, ("diagnosis", "top1_accuracy", "mean")),
        "diagnosis_nll": _macro(world_summaries, ("diagnosis", "cross_entropy_nll", "mean")),
        "natural_signature_rmse": _macro(world_summaries, ("natural", "signature_rmse", "mean")),
        "intervention_signature_rmse": _macro(world_summaries, ("intervention", "signature_rmse", "mean")),
        "treatment_regret": _macro(world_summaries, ("regret", "regret", "mean")),
        "state_bytes": _macro(world_summaries, ("state_bytes", "value", "mean")),
        "initialize_ms": _macro(world_summaries, ("initialize_ms", "value", "mean")),
        "head_ms": _macro(world_summaries, ("head_ms", "value", "mean")),
        "ood_unknown_brier": _macro(world_summaries, ("ood", "unknown_brier", "mean")),
    }
    return {
        "worlds": world_summaries,
        "headline": headline,
        "dangerous_collision_count": sum(row["dangerous_collision"] for row in pair_rows),
        "false_split_count": sum(row["false_split"] for row in pair_rows),
        "pair_probe_count": len(pair_rows),
        "update_replay_failure_count": sum(
            world["update_replay_failure_count"] for world in world_summaries.values()
        ),
        "query_order_failure_count": sum(
            world["query_order_failure_count"] for world in world_summaries.values()
        ),
        "unsafe_non_abstain_count": sum(
            row["ood"].get("unsafe_non_abstain", 0.0) > 0.0
            for row in episode_rows
        ),
    }


def _cross_seed_summary(replicates: list[dict[str, Any]]) -> dict[str, Any]:
    keys = sorted(
        {
            key
            for row in replicates
            for key, value in row["summary"]["headline"].items()
            if value is not None
        }
    )
    metrics: dict[str, Any] = {}
    for key in keys:
        values = [
            float(row["summary"]["headline"][key])
            for row in replicates
            if row["summary"]["headline"][key] is not None
        ]
        mean = statistics.fmean(values)
        sd = statistics.stdev(values) if len(values) > 1 else 0.0
        half_width = 2.7764451051977987 * sd / math.sqrt(5) if len(values) == 5 else None
        metrics[key] = {
            "mean": mean,
            "sd": sd,
            "min": min(values),
            "max": max(values),
            "t95_low": None if half_width is None else mean - half_width,
            "t95_high": None if half_width is None else mean + half_width,
            "seed_count": len(values),
        }
    return metrics


def _source_binding() -> dict[str, Any]:
    root = _repo_root()
    paths = (
        "prototype/unified_map/benchmark_v1_runner.py",
        "prototype/unified_map/benchmark_v1_full_suite.py",
        "prototype/unified_map/candidate_families.py",
    )
    rows = []
    for relative in paths:
        raw = (root / relative).read_bytes()
        rows.append({"relative_path": relative, "byte_length": len(raw), "sha256": digest_bytes(raw)})
    return {"files": rows, "source_digest": digest_json(rows)}


def _run_id(config: RunConfig) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{config.experiment_id}-{uuid.uuid4().hex[:10]}"


def run_benchmark(
    config: RunConfig,
    *,
    freeze_path: Path | None = None,
    secret_path: Path,
    results_root: Path | None = None,
) -> Path:
    root = _repo_root()
    freeze_path = freeze_path or root / FREEZE_FILENAME
    results_root = results_root or root / DEFAULT_RESULTS_ROOT
    freeze, secret = _load_authority(freeze_path, secret_path)
    run_id = _run_id(config)
    final = results_root / run_id
    temporary = results_root / f".{run_id}.tmp"
    if final.exists() or temporary.exists():
        raise ProtocolViolation("run_id collision; append-only publication refused")
    temporary.mkdir(parents=True, exist_ok=False)
    raw_path = temporary / "raw-episodes.jsonl"
    pair_path = temporary / "raw-pairs.jsonl"
    started = time.perf_counter()
    replicate_results: list[dict[str, Any]] = []
    try:
        with raw_path.open("wb") as raw_writer, pair_path.open("wb") as pair_writer:
            for replicate_id in config.replicate_ids:
                seed_row = _replicate_secret(secret, replicate_id)
                panel_rows = _panels(config.world_slots)
                catalogs, training = _training_records(
                    panel_rows,
                    seed_row,
                    config.train_episodes_per_panel,
                )
                candidate = make_candidate(config.family_code, **config.parameters)
                model_seed = MODEL_SEEDS[REPLICATE_IDS.index(replicate_id)]
                fit_started = time.perf_counter()
                candidate.fit(catalogs, training, model_seed=model_seed)
                fit_seconds = time.perf_counter() - fit_started
                sealed_rows = _sealed_evaluation_rows(
                    panel_rows, seed_row, config.test_episodes_per_panel
                )
                pair_oracle_rows = _precompute_pair_oracles(
                    panel_rows,
                    seed_row["sealed_test_root_seed"],
                    config.pair_probe_limit_per_declaration,
                )
                episode_rows: list[dict[str, Any]] = []
                pair_rows: list[dict[str, Any]] = []
                for slot, panel, world in panel_rows:
                    oracle_root = _derived_seed(
                        seed_row["sealed_test_root_seed"], slot, panel.panel_id, "oracle"
                    )
                    for episode_index in range(config.test_episodes_per_panel):
                        episode, precomputed_oracles = sealed_rows[
                            (slot, panel.panel_id, episode_index)
                        ]
                        episode_rows.append(
                            _evaluate_episode(
                                candidate=candidate,
                                slot=slot,
                                panel=panel,
                                world=world,
                                episode=episode,
                                replicate_id=replicate_id,
                                episode_index=episode_index,
                                oracle_root=_derived_seed(oracle_root, episode_index),
                                raw_writer=raw_writer,
                                precomputed_oracles=precomputed_oracles,
                            )
                        )
                    panel_pairs = _pair_probes(
                        candidate=candidate,
                        slot=slot,
                        panel=panel,
                        world=world,
                        seed_root=seed_row["sealed_test_root_seed"],
                        limit=config.pair_probe_limit_per_declaration,
                        precomputed=pair_oracle_rows[(slot, panel.panel_id)],
                    )
                    pair_rows.extend(panel_pairs)
                    for row in panel_pairs:
                        pair_writer.write(canonical_json_bytes(row))
                replicate_results.append(
                    {
                        "replicate_id": replicate_id,
                        "model_seed": model_seed,
                        "seed_commitment": next(
                            row["commitment"]
                            for row in freeze["seed_commitments"]
                            if row["replicate_id"] == replicate_id
                        ),
                        "fit_seconds": fit_seconds,
                        "training_record_count": len(training),
                        "model_summary": candidate.model_summary(),
                        "summary": _replicate_summary(episode_rows, pair_rows),
                    }
                )
        hard_failures = {
            "dangerous_collision": sum(
                row["summary"]["dangerous_collision_count"] for row in replicate_results
            ),
            "update_inconsistency": sum(
                row["summary"]["update_replay_failure_count"] for row in replicate_results
            ),
            "query_order_impurity": sum(
                row["summary"]["query_order_failure_count"] for row in replicate_results
            ),
            "unsafe_forced_known_ood": sum(
                row["summary"]["unsafe_non_abstain_count"] for row in replicate_results
            ),
        }
        baseline_only = config.family_code in {"B02", "B03", "B04"}
        report = {
            "protocol": RUN_PROTOCOL,
            "run_id": run_id,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "freeze_root": freeze["freeze_root"],
            "benchmark_status": freeze["status"],
            "config": config.to_wire(),
            "candidate_eligibility": "baseline_only" if baseline_only else "ucm_candidate",
            "shared_state_compliant_by_design": config.family_code != "B03",
            "source_binding": _source_binding(),
            "replicates": replicate_results,
            "cross_seed_summary": _cross_seed_summary(replicate_results),
            "hard_failures": hard_failures,
            "hard_gate_pass": not any(hard_failures.values()) and config.family_code != "B03",
            "wall_seconds": time.perf_counter() - started,
            "raw_episode_file": raw_path.name,
            "raw_pair_file": pair_path.name,
            "seed_preimages_published": False,
            "claim_boundary": {
                "synthetic_only": True,
                "clinical_validity_claimed": False,
                "complete_benchmark": config.complete_benchmark,
                "screening_run": not config.complete_benchmark,
            },
        }
        summary_raw = canonical_json_bytes(report)
        (temporary / "summary.json").write_bytes(summary_raw)
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
                for path in (raw_path, pair_path, temporary / "summary.json")
            ],
        }
        manifest["bundle_root"] = digest_json(manifest)
        (temporary / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        results_root.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def verify_run_bundle(path: Path) -> dict[str, Any]:
    manifest = _decode_canonical(path / "manifest.json", "run manifest")
    if manifest.get("protocol") != RUN_MANIFEST_PROTOCOL:
        raise ProtocolViolation("run manifest protocol mismatch")
    expected_root = digest_json(
        {key: value for key, value in manifest.items() if key != "bundle_root"}
    )
    if manifest.get("bundle_root") != expected_root:
        raise ProtocolViolation("run bundle root mismatch")
    for row in manifest["files"]:
        member = path / row["name"]
        if member.is_file():
            raw = member.read_bytes()
        else:
            compressed = member.with_name(member.name + ".gz")
            if not compressed.is_file():
                raise ProtocolViolation("run bundle member is missing")
            try:
                with gzip.open(compressed, "rb") as handle:
                    raw = handle.read(int(row["byte_length"]) + 1)
            except (OSError, EOFError) as exc:
                raise ProtocolViolation("run bundle gzip sidecar is invalid") from exc
        if len(raw) != row["byte_length"] or digest_bytes(raw) != row["sha256"]:
            raise ProtocolViolation("run bundle member drifted")
    summary = _decode_canonical(path / "summary.json", "run summary")
    if summary.get("run_id") != manifest.get("run_id"):
        raise ProtocolViolation("run summary/manifest id mismatch")
    return summary


def _main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen UCM benchmark v1")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--secret", type=Path, required=True)
    parser.add_argument("--parameters", default="{}")
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--worlds", default="")
    parser.add_argument("--results-root", type=Path)
    args = parser.parse_args()
    parameters = json.loads(args.parameters)
    if type(parameters) is not dict:
        raise ProtocolViolation("--parameters must encode an object")
    if args.complete:
        config = complete_config(args.experiment_id, args.family, parameters=parameters)
    else:
        worlds = (
            tuple(item for item in args.worlds.split(",") if item)
            if args.worlds
            else ("W01", "W04", "W08", "W15", "W18", "W19", "W20")
        )
        config = screening_config(
            args.experiment_id, args.family, parameters=parameters, world_slots=worlds
        )
    path = run_benchmark(
        config,
        secret_path=args.secret,
        results_root=args.results_root,
    )
    summary = verify_run_bundle(path)
    print(
        json.dumps(
            {
                "run_id": summary["run_id"],
                "path": str(path.resolve()),
                "complete_benchmark": summary["config"]["complete_benchmark"],
                "hard_gate_pass": summary["hard_gate_pass"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "RUN_MANIFEST_PROTOCOL",
    "RUN_PROTOCOL",
    "RunConfig",
    "complete_config",
    "run_benchmark",
    "screening_config",
    "verify_run_bundle",
]
