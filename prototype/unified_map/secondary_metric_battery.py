"""Exploratory secondary-metric battery for executable UCM candidates.

This module closes a practical evidence gap in the benchmark-v1 runner without
changing the sealed candidate source or the primary runner.  It executes five
small, explicitly secondary probes:

* M09-like public sample-efficiency curves;
* M10-like W13 nonlinear-combination transfer;
* M11-like W16/W17 check/treatment extension cost;
* M13-like Python peak-memory measurements; and
* M16-like transfer to a genuinely new conditional-expectation readout.

The names are deliberately ``Mxx-like``.  This battery is executable evidence,
not a replacement for the frozen metric denominator/applicability authority.
Candidates receive only public training records, visible history/deltas and
their own ``SharedPatientState``.  Judge true state and future expectations are
used only after the candidate API boundary to construct scores and controls.

Execution is serial.  On Windows the process is moved to BelowNormal priority
by default so a broad all-family run does not monopolise an interactive host.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import shutil
import tempfile
import time
import tracemalloc
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from .baselines_v2 import exact_history_feature_vector
from .benchmark_v1_contract import (
    PublicTrainingRecord,
    SharedPatientState,
    build_public_training_record,
    oracle_signature,
)
from .candidate_families import make_candidate
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from .extensions import ExtensionRunner
from .f22_switching_particle import make_f22_candidate
from .schema import ActionPlan, PlanKind, VisibleDelta
from .state import StateClass, StatePayload, seal_state
from .worlds.base import CounterfactualOracle, MicroWorld, PrivateEpisode, PublicCatalog, WorldSplit
from .worlds.w01 import World as World01
from .worlds.w04 import World as World04
from .worlds.w13 import World as World13
from .worlds.w16 import W16World, make_w16_extension_custody
from .worlds.w17 import W17World, make_w17_extension_custody


PROTOCOL = "ucm-secondary-metric-battery/1"
RAW_PROTOCOL = "ucm-secondary-metric-row/1"
MANIFEST_PROTOCOL = "ucm-secondary-metric-bundle/1"

# Every executable UCM research family currently present in the repository.
# F09S/F09L are genuine ablation families and therefore have their own rows.
ORDINARY_FAMILY_CODES: tuple[str, ...] = (
    "F01",
    "F02",
    "F03",
    "F04",
    "F05",
    "F06",
    "F07",
    "F08",
    "F09",
    "F09S",
    "F09L",
    "F10",
    "F11",
    "F12",
    "F13",
    "F14",
    "F15",
    "F16",
    "F17",
    "F18",
    "F19",
    "F20",
    "F21",
    "F22",
)
METRIC_IDS = ("M09", "M10", "M11", "M13", "M16")


def make_battery_candidate(family_code: str, **parameters: Any) -> Any:
    """Create one ordinary candidate without routing through the primary runner."""

    if family_code not in ORDINARY_FAMILY_CODES:
        raise ProtocolViolation(f"unsupported secondary-battery family {family_code!r}")
    if family_code == "F22":
        return make_f22_candidate(family_code, **parameters)
    return make_candidate(family_code, **parameters)


def _positive_tuple(values: tuple[int, ...], label: str) -> None:
    if (
        type(values) is not tuple
        or not values
        or any(type(value) is not int or value <= 0 for value in values)
        or tuple(sorted(set(values))) != values
    ):
        raise ProtocolViolation(f"{label} must be sorted unique positive integers")


@dataclass(frozen=True, slots=True)
class SecondaryBatteryConfig:
    """Small default workload; callers may scale counts without changing semantics."""

    families: tuple[str, ...] = ORDINARY_FAMILY_CODES
    metrics: tuple[str, ...] = METRIC_IDS
    model_seed: int = 20260719
    generator_seed: int = 9173
    oracle_seed: int = 11939
    worker_count: int = 1
    below_normal_priority: bool = True
    m09_train_sizes: tuple[int, ...] = (2, 4, 8)
    m09_validation_examples: int = 4
    m10_train_examples: int = 8
    m10_pair_count: int = 4
    m11_primary_train_examples: int = 4
    m11_extension_train_examples: int = 4
    m13_train_examples: int = 4
    m16_candidate_train_examples: int = 8
    m16_readout_train_examples: int = 16
    m16_readout_validation_examples: int = 8
    m16_readout_test_examples: int = 8
    m16_max_capacity: int = 64
    ridge_regularization: float = 1e-3

    def __post_init__(self) -> None:
        if (
            type(self.families) is not tuple
            or not self.families
            or len(set(self.families)) != len(self.families)
            or any(code not in ORDINARY_FAMILY_CODES for code in self.families)
        ):
            raise ProtocolViolation("families must be a unique ordinary-family tuple")
        if (
            type(self.metrics) is not tuple
            or not self.metrics
            or len(set(self.metrics)) != len(self.metrics)
            or any(metric not in METRIC_IDS for metric in self.metrics)
        ):
            raise ProtocolViolation("metrics must be a unique supported-metric tuple")
        if self.worker_count != 1:
            raise ProtocolViolation("secondary battery is intentionally single-worker")
        if type(self.below_normal_priority) is not bool:
            raise ProtocolViolation("below_normal_priority must be bool")
        for value, label in (
            (self.model_seed, "model_seed"),
            (self.generator_seed, "generator_seed"),
            (self.oracle_seed, "oracle_seed"),
        ):
            if type(value) is not int or value < 0:
                raise ProtocolViolation(f"{label} must be a non-negative integer")
        _positive_tuple(self.m09_train_sizes, "m09_train_sizes")
        for name in (
            "m09_validation_examples",
            "m10_train_examples",
            "m10_pair_count",
            "m11_primary_train_examples",
            "m11_extension_train_examples",
            "m13_train_examples",
            "m16_candidate_train_examples",
            "m16_readout_train_examples",
            "m16_readout_validation_examples",
            "m16_readout_test_examples",
            "m16_max_capacity",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ProtocolViolation(f"{name} must be a positive integer")
        if (
            type(self.ridge_regularization) not in {int, float}
            or not math.isfinite(float(self.ridge_regularization))
            or self.ridge_regularization <= 0
        ):
            raise ProtocolViolation("ridge_regularization must be positive finite")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL,
            "families": list(self.families),
            "metrics": list(self.metrics),
            "model_seed": self.model_seed,
            "generator_seed": self.generator_seed,
            "oracle_seed": self.oracle_seed,
            "worker_count": self.worker_count,
            "below_normal_priority": self.below_normal_priority,
            "m09_train_sizes": list(self.m09_train_sizes),
            "m09_validation_examples": self.m09_validation_examples,
            "m10_train_examples": self.m10_train_examples,
            "m10_pair_count": self.m10_pair_count,
            "m11_primary_train_examples": self.m11_primary_train_examples,
            "m11_extension_train_examples": self.m11_extension_train_examples,
            "m13_train_examples": self.m13_train_examples,
            "m16_candidate_train_examples": self.m16_candidate_train_examples,
            "m16_readout_train_examples": self.m16_readout_train_examples,
            "m16_readout_validation_examples": self.m16_readout_validation_examples,
            "m16_readout_test_examples": self.m16_readout_test_examples,
            "m16_max_capacity": self.m16_max_capacity,
            "ridge_regularization": float(self.ridge_regularization),
        }


def _set_below_normal_priority(requested: bool) -> dict[str, Any]:
    if not requested:
        return {"requested": False, "applied": False, "method": "not_requested"}
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetCurrentProcess()
            applied = bool(kernel32.SetPriorityClass(handle, 0x00004000))
            return {
                "requested": True,
                "applied": applied,
                "method": "SetPriorityClass(BELOW_NORMAL_PRIORITY_CLASS)",
            }
        except (AttributeError, OSError):
            return {"requested": True, "applied": False, "method": "windows_failed"}
    try:
        os.nice(5)
        return {"requested": True, "applied": True, "method": "os.nice(+5)"}
    except OSError:
        return {"requested": True, "applied": False, "method": "posix_failed"}


def _seed(root: int, *parts: Any) -> int:
    return int(digest_json([root, *parts])[7:23], 16) & ((1 << 63) - 1)


def _training_record(
    world: MicroWorld, episode: PrivateEpisode, *, oracle_seed: int
) -> PublicTrainingRecord:
    return build_public_training_record(world, episode, oracle_seed=oracle_seed)


def _records(
    world: MicroWorld,
    split: WorldSplit,
    count: int,
    *,
    generator_seed: int,
    oracle_seed: int,
    start_index: int = 0,
) -> tuple[PublicTrainingRecord, ...]:
    return tuple(
        _training_record(
            world,
            world.generate_episode(split, generator_seed, start_index + index),
            oracle_seed=_seed(oracle_seed, split.value, start_index + index),
        )
        for index in range(count)
    )


def _no_action(world: MicroWorld, horizon: int) -> ActionPlan:
    rows = [plan for plan in world.policy_set(horizon) if plan.kind is PlanKind.NO_NEW_ACTION]
    if len(rows) != 1:
        raise ProtocolViolation("world must expose exactly one no-new-action policy")
    return rows[0]


def _intervention(world: MicroWorld, horizon: int) -> ActionPlan:
    rows = [plan for plan in world.policy_set(horizon) if plan.kind is PlanKind.ACTION_SEQUENCE]
    if not rows:
        raise ProtocolViolation("world has no intervention policy")
    return rows[-1]


def _proper_components(
    candidate: Any,
    world: MicroWorld,
    episode: PrivateEpisode,
    *,
    seed: int,
) -> dict[str, float | bool]:
    state = candidate.initialize(episode.public_history, inference_seed=_seed(seed, "init"))
    diagnosis = candidate.diagnose(
        state, world.catalog.diagnostic_labels, query_seed=_seed(seed, "diagnose")
    ).validate_for(world.catalog)
    target_label = max(episode.diagnostic_target, key=episode.diagnostic_target.get)
    probability = max(float(diagnosis.probabilities[target_label]), 1e-12)
    nll = -math.log(probability)
    horizon = world.catalog.horizons[min(1, len(world.catalog.horizons) - 1)]
    plan = _no_action(world, horizon)
    prediction = candidate.rollout(
        state, plan, horizon, query_seed=_seed(seed, "rollout")
    )
    oracle = world.counterfactual(episode, plan, horizon, _seed(seed, "oracle"))
    signature = np.asarray(oracle_signature(oracle), dtype=np.float64)
    predicted = np.asarray(prediction.signature, dtype=np.float64)
    signature_rmse = float(np.sqrt(np.mean((predicted - signature) ** 2)))
    utility_abs_error = abs(float(prediction.expected_utility) - oracle.expected_utility)
    # This transparent composite is battery-local; primary metrics remain separate.
    proper_error = nll + signature_rmse + utility_abs_error
    return {
        "diagnosis_nll": float(nll),
        "natural_signature_rmse": signature_rmse,
        "natural_utility_abs_error": float(utility_abs_error),
        "proper_error": float(proper_error),
        "rollout_abstained": bool(prediction.abstained),
        "state_size_bytes": state.canonical_size_bytes,
    }


def _m09_rows(family: str, config: SecondaryBatteryConfig) -> list[dict[str, Any]]:
    worlds: tuple[tuple[str, MicroWorld], ...] = (
        ("W01", World01()),
        ("W04", World04()),
        ("W13", World13()),
    )
    maximum = max(config.m09_train_sizes)
    pools = {
        slot: _records(
            world,
            WorldSplit.TRAIN,
            maximum,
            generator_seed=_seed(config.generator_seed, "M09", slot, "train"),
            oracle_seed=_seed(config.oracle_seed, "M09", slot, "train"),
        )
        for slot, world in worlds
    }
    validation = {
        slot: tuple(
            world.generate_episode(
                WorldSplit.VALIDATION,
                _seed(config.generator_seed, "M09", slot, "validation"),
                index,
            )
            for index in range(config.m09_validation_examples)
        )
        for slot, world in worlds
    }
    rows: list[dict[str, Any]] = []
    means: list[tuple[int, float]] = []
    for size in config.m09_train_sizes:
        candidate = make_battery_candidate(family)
        training = tuple(record for slot, _ in worlds for record in pools[slot][:size])
        candidate.fit(
            tuple(world.catalog for _, world in worlds),
            training,
            model_seed=_seed(config.model_seed, family, "M09", size),
        )
        scores: list[float] = []
        for slot, world in worlds:
            for index, episode in enumerate(validation[slot]):
                components = _proper_components(
                    candidate,
                    world,
                    episode,
                    seed=_seed(config.model_seed, family, "M09", size, slot, index),
                )
                scores.append(float(components["proper_error"]))
                rows.append(
                    {
                        "protocol": RAW_PROTOCOL,
                        "metric": "M09",
                        "family": family,
                        "row_kind": "sample_efficiency_case",
                        "world": slot,
                        "train_examples_per_world": size,
                        "total_train_examples": len(training),
                        "validation_index": index,
                        "candidate_inputs": ["public_training_record", "visible_history", "shared_state"],
                        "judge_only_inputs": ["diagnostic_target", "counterfactual_oracle"],
                        **components,
                    }
                )
        means.append((len(training), float(np.mean(scores))))
    if len(means) == 1:
        auc = means[0][1]
    else:
        xs = np.log2(np.asarray([item[0] for item in means], dtype=np.float64))
        ys = np.asarray([item[1] for item in means], dtype=np.float64)
        auc = float(np.trapz(ys, xs) / (xs[-1] - xs[0]))
    rows.append(
        {
            "protocol": RAW_PROTOCOL,
            "metric": "M09",
            "family": family,
            "row_kind": "sample_efficiency_summary",
            "curve": [
                {"train_examples": count, "mean_proper_error": score}
                for count, score in means
            ],
            "normalized_error_auc": float(auc),
            "normalized_error_auc_direction": "minimize",
            "efficiency_score": float(-auc),
            "efficiency_score_direction": "maximize",
            "formal_metric_claim": False,
        }
    )
    return rows


def _public_match_vector(episode: PrivateEpisode) -> np.ndarray:
    return exact_history_feature_vector(episode.public_history.to_wire())


def _score_blind_matches(
    heldout: Sequence[PrivateEpisode], seen: Sequence[PrivateEpisode]
) -> list[tuple[int, int, float]]:
    """Greedy public-feature matching fixed before any candidate score exists."""

    available = set(range(len(seen)))
    matches: list[tuple[int, int, float]] = []
    for left_index, left in enumerate(heldout):
        left_vector = _public_match_vector(left)
        choices = [
            (
                float(np.linalg.norm(left_vector - _public_match_vector(seen[index]))),
                index,
            )
            for index in available
        ]
        distance, right_index = min(choices)
        available.remove(right_index)
        matches.append((left_index, right_index, distance))
    return matches


def _m10_rows(family: str, config: SecondaryBatteryConfig) -> list[dict[str, Any]]:
    world = World13()
    training = _records(
        world,
        WorldSplit.TRAIN,
        config.m10_train_examples,
        generator_seed=_seed(config.generator_seed, "M10", "train"),
        oracle_seed=_seed(config.oracle_seed, "M10", "train"),
    )
    candidate = make_battery_candidate(family)
    candidate.fit(
        (world.catalog,),
        training,
        model_seed=_seed(config.model_seed, family, "M10"),
    )
    heldout = tuple(
        world.generate_episode(
            WorldSplit.SEALED_TEST,
            _seed(config.generator_seed, "M10", "heldout"),
            5 * index,
        )
        for index in range(config.m10_pair_count)
    )
    # These rows come from the training distribution but were not used to fit.
    seen = tuple(
        world.generate_episode(
            WorldSplit.TRAIN,
            _seed(config.generator_seed, "M10", "seen"),
            config.m10_train_examples + index,
        )
        for index in range(config.m10_pair_count)
    )
    matches = _score_blind_matches(heldout, seen)
    rows: list[dict[str, Any]] = []
    gaps: list[float] = []
    for pair_number, (left, right, distance) in enumerate(matches):
        heldout_score = _proper_components(
            candidate,
            world,
            heldout[left],
            seed=_seed(config.model_seed, family, "M10", "heldout", pair_number),
        )
        seen_score = _proper_components(
            candidate,
            world,
            seen[right],
            seed=_seed(config.model_seed, family, "M10", "seen", pair_number),
        )
        gap = float(heldout_score["proper_error"]) - float(seen_score["proper_error"])
        gaps.append(gap)
        rows.append(
            {
                "protocol": RAW_PROTOCOL,
                "metric": "M10",
                "family": family,
                "row_kind": "nonlinear_combination_pair",
                "world": "W13",
                "pair_id": f"{family}-w13-{pair_number:03d}",
                "heldout_generator_cell": "threshold_shell_compositional_holdout",
                "matched_seen_generator_cell": "unseen_row_from_train_distribution",
                "matching_basis": "greedy_euclidean_exact_public_history_feature_before_scoring",
                "public_match_distance": distance,
                "heldout": heldout_score,
                "matched_seen": seen_score,
                "proper_error_gap": gap,
                "candidate_received_true_or_future": False,
            }
        )
    rows.append(
        {
            "protocol": RAW_PROTOCOL,
            "metric": "M10",
            "family": family,
            "row_kind": "nonlinear_combination_summary",
            "pair_count": len(matches),
            "mean_proper_error_gap": float(np.mean(gaps)),
            "formal_metric_claim": False,
        }
    )
    return rows


class _ExtensionWorldAdapter(MicroWorld):
    """Expose an already revealed S1 scope through the ordinary trainer API."""

    def __init__(self, world: W16World | W17World) -> None:
        self.world = world

    @property
    def environment_key(self) -> str:
        return self.world.environment_key + "-secondary-extension-adapter"

    @property
    def catalog(self) -> PublicCatalog:
        return self.world.extension_catalog

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        return self.world.generate_extension_episode(split, generator_seed, episode_index)

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        return self.world.extension_policy_set(horizon)

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        return self.world.counterfactual(episode, policy, horizon, oracle_seed)


def _candidate_source_paths(family: str) -> tuple[Path, ...]:
    root = Path(__file__).resolve().parent
    paths = [root / "candidate_families.py"]
    if family == "F22":
        paths.append(root / "f22_switching_particle.py")
    return tuple(paths)


def _seal_and_reveal_extension(
    family: str,
    candidate: Any,
    old_state: SharedPatientState,
    history: Any,
    world: W16World | W17World,
    custody: Any,
) -> tuple[Any, dict[str, Any]]:
    """Use the repository extension state machine with a minimal source bundle."""

    model_bytes = canonical_json_bytes(candidate.model_summary())
    with tempfile.TemporaryDirectory(prefix="ucm-secondary-extension-seal-") as raw:
        root = Path(raw)
        for source in _candidate_source_paths(family):
            (root / source.name).write_bytes(source.read_bytes())
        runner = ExtensionRunner(custody, primary_catalog_digest=world.catalog.digest)
        # Compute the exact digest using the same helper as ExtensionRunner.
        from .extensions import candidate_tree_digest

        candidate_digest = candidate_tree_digest(root)
        model_digest = digest_bytes(model_bytes)
        scope_digest = digest_json(
            {"protocol": "ucm-secondary-extension-s0-scope/1", "catalog": world.catalog.digest}
        )
        state_payload = StatePayload(
            old_state.payload,
            "canonical-json-v1",
            old_state.schema_version,
            StateClass.COMPRESSED_SHARED,
        )
        sealed = seal_state(
            state_payload,
            candidate_bundle_digest=candidate_digest,
            model_digest=model_digest,
            scope_digest=scope_digest,
            catalog_digest=world.catalog.digest,
            as_of_available_at=history.as_of_available_at,
            operation="initialize",
            state_instance_id=f"secondary-{family}-{world.environment_key}",
        )
        primary = runner.seal_primary(
            candidate_root=root,
            model_artifact=model_bytes,
            states=(sealed,),
            histories={sealed.record.state_hash: history},
        )
        reveal = runner.reveal()
        evidence = {
            "primary_seal_digest": primary.seal_digest,
            "candidate_source_subset_digest": primary.candidate_bundle_digest,
            "model_summary_digest": primary.model_digest,
            "old_state_hash": old_state.state_hash,
            "harness_state_hash": sealed.record.state_hash,
            "extension_commitment": reveal.commitment,
            "extension_pack_digest": reveal.pack_digest,
            "seal_strength": "secondary_source_subset_and_model_summary_not_full_import_inventory",
        }
        return reveal, evidence


def _extension_only_plan(adapter: _ExtensionWorldAdapter, horizon: int) -> ActionPlan:
    primary_ids = {
        action.action_id for action in adapter.world.catalog.actions
    } | {check.check_id for check in adapter.world.catalog.checks}
    for plan in adapter.policy_set(horizon):
        if any(action.action_id not in primary_ids for action in plan.actions):
            return plan
    raise ProtocolViolation("revealed extension exposes no extension-only plan")


def _m11_world_row(
    family: str,
    config: SecondaryBatteryConfig,
    *,
    world: W16World | W17World,
    custody: Any,
    slot: str,
    kind: str,
) -> dict[str, Any]:
    primary_records = _records(
        world,
        WorldSplit.TRAIN,
        config.m11_primary_train_examples,
        generator_seed=_seed(config.generator_seed, "M11", slot, "S0"),
        oracle_seed=_seed(config.oracle_seed, "M11", slot, "S0"),
    )
    candidate = make_battery_candidate(family)
    primary_start = time.perf_counter_ns()
    candidate.fit(
        (world.catalog,),
        primary_records,
        model_seed=_seed(config.model_seed, family, "M11", slot, "S0"),
    )
    primary_train_ns = time.perf_counter_ns() - primary_start
    old_episode = world.generate_episode(
        WorldSplit.VALIDATION, _seed(config.generator_seed, "M11", slot, "old"), 0
    )
    old_state = candidate.initialize(
        old_episode.public_history,
        inference_seed=_seed(config.model_seed, family, "M11", slot, "old-state"),
    )
    old_payload_before = bytes(old_state.payload)
    reveal, seal_evidence = _seal_and_reveal_extension(
        family, candidate, old_state, old_episode.public_history, world, custody
    )
    extended_world = world.activate_extension(reveal)
    adapter = _ExtensionWorldAdapter(extended_world)
    horizon = adapter.catalog.horizons[min(1, len(adapter.catalog.horizons) - 1)]
    plan = _extension_only_plan(adapter, horizon)
    direct_error: str | None = None
    direct_abstained = True
    try:
        prediction = candidate.rollout(
            old_state,
            plan,
            horizon,
            query_seed=_seed(config.model_seed, family, "M11", slot, "direct"),
        )
        direct_abstained = bool(prediction.abstained)
    except Exception as exc:  # an explicit inability is scope insufficiency here
        direct_error = f"{type(exc).__name__}:{exc}"
    scope_insufficient = direct_error is not None or direct_abstained

    extension_records = _records(
        adapter,
        WorldSplit.TRAIN,
        config.m11_extension_train_examples,
        generator_seed=_seed(config.generator_seed, "M11", slot, "S1"),
        oracle_seed=_seed(config.oracle_seed, "M11", slot, "S1"),
    )
    extension_candidate = make_battery_candidate(family)
    extension_start = time.perf_counter_ns()
    extension_candidate.fit(
        (adapter.catalog,),
        extension_records,
        model_seed=_seed(config.model_seed, family, "M11", slot, "S1"),
    )
    extension_train_ns = time.perf_counter_ns() - extension_start
    migrated_episode = adapter.generate_episode(
        WorldSplit.VALIDATION, _seed(config.generator_seed, "M11", slot, "migrate"), 0
    )
    replay_start = time.perf_counter_ns()
    migrated_state = extension_candidate.initialize(
        migrated_episode.public_history,
        inference_seed=_seed(config.model_seed, family, "M11", slot, "migrated-state"),
    )
    replay_ns = time.perf_counter_ns() - replay_start
    migrated_prediction = extension_candidate.rollout(
        migrated_state,
        plan,
        horizon,
        query_seed=_seed(config.model_seed, family, "M11", slot, "migrated-query"),
    )
    training_bytes = sum(len(canonical_json_bytes(record.to_wire())) for record in extension_records)
    history_replay_bytes = len(canonical_json_bytes(migrated_episode.public_history.to_wire()))
    return {
        "protocol": RAW_PROTOCOL,
        "metric": "M11",
        "family": family,
        "row_kind": "extension_cost",
        "world": slot,
        "extension_kind": kind,
        "chronology": [
            "fit_s0_public_records",
            "initialize_and_seal_s0_state",
            "reveal_extension",
            "state_only_first_query",
            "explicit_full_retrain_and_history_replay",
        ],
        "scope_insufficient": scope_insufficient,
        "state_only_first_query_abstained": direct_abstained,
        "state_only_first_query_error": direct_error,
        "local_state_migration_supported": False,
        "local_state_migration_bytes": 0,
        "migration_disposition": "explicit_full_retrain_and_offline_history_replay",
        "retrain_examples": len(extension_records),
        "retrain_public_record_bytes": training_bytes,
        "history_replay_bytes": history_replay_bytes,
        "primary_train_wall_ns": primary_train_ns,
        "extension_train_wall_ns": extension_train_ns,
        "history_replay_wall_ns": replay_ns,
        "old_state_size_bytes": old_state.canonical_size_bytes,
        "extended_state_size_bytes": migrated_state.canonical_size_bytes,
        "old_state_unchanged_after_query": old_state.payload == old_payload_before,
        "source_change_bytes": 0,
        "source_change_loc": 0,
        "stable_exported_model_artifact_available": False,
        "extended_query_abstained_after_retrain": bool(migrated_prediction.abstained),
        "candidate_received_true_or_future": False,
        "formal_metric_claim": False,
        **seal_evidence,
    }


def _m11_rows(family: str, config: SecondaryBatteryConfig) -> list[dict[str, Any]]:
    return [
        _m11_world_row(
            family,
            config,
            world=W16World(),
            custody=make_w16_extension_custody(),
            slot="W16",
            kind="new_check",
        ),
        _m11_world_row(
            family,
            config,
            world=W17World(),
            custody=make_w17_extension_custody(),
            slot="W17",
            kind="new_treatment",
        ),
    ]


def _measure_peak(call: Callable[[], Any]) -> tuple[Any, int, int]:
    tracemalloc.reset_peak()
    before = tracemalloc.get_traced_memory()[0]
    result = call()
    current, peak = tracemalloc.get_traced_memory()
    return result, max(0, peak - before), max(0, current - before)


def _m13_rows(family: str, config: SecondaryBatteryConfig) -> list[dict[str, Any]]:
    world = World01()
    training = _records(
        world,
        WorldSplit.TRAIN,
        config.m13_train_examples,
        generator_seed=_seed(config.generator_seed, "M13", "train"),
        oracle_seed=_seed(config.oracle_seed, "M13", "train"),
    )
    candidate = make_battery_candidate(family)
    episode = world.generate_episode(
        WorldSplit.VALIDATION, _seed(config.generator_seed, "M13", "validation"), 0
    )
    plan = _no_action(world, 4)
    tracemalloc.start()
    try:
        _, fit_peak, fit_retained = _measure_peak(
            lambda: candidate.fit(
                (world.catalog,),
                training,
                model_seed=_seed(config.model_seed, family, "M13"),
            )
        )
        state, initialize_peak, initialize_retained = _measure_peak(
            lambda: candidate.initialize(
                episode.public_history,
                inference_seed=_seed(config.model_seed, family, "M13", "init"),
            )
        )
        empty_delta = VisibleDelta(episode.public_history.as_of_available_at, ())
        updated, update_peak, update_retained = _measure_peak(
            lambda: candidate.update(
                state,
                empty_delta,
                inference_seed=_seed(config.model_seed, family, "M13", "update"),
            )
        )
        _, diagnosis_peak, diagnosis_retained = _measure_peak(
            lambda: candidate.diagnose(
                updated,
                world.catalog.diagnostic_labels,
                query_seed=_seed(config.model_seed, family, "M13", "diagnose"),
            )
        )
        _, rollout_peak, rollout_retained = _measure_peak(
            lambda: candidate.rollout(
                updated,
                plan,
                4,
                query_seed=_seed(config.model_seed, family, "M13", "rollout"),
            )
        )
    finally:
        tracemalloc.stop()
    summary_bytes = len(canonical_json_bytes(candidate.model_summary()))
    rows = []
    for operation, peak, retained in (
        ("fit", fit_peak, fit_retained),
        ("initialize", initialize_peak, initialize_retained),
        ("update_empty_delta", update_peak, update_retained),
        ("diagnose", diagnosis_peak, diagnosis_retained),
        ("rollout", rollout_peak, rollout_retained),
    ):
        rows.append(
            {
                "protocol": RAW_PROTOCOL,
                "metric": "M13",
                "family": family,
                "row_kind": "peak_memory",
                "operation": operation,
                "collector": "python_tracemalloc",
                "peak_increment_bytes": int(peak),
                "retained_increment_bytes": int(retained),
                "native_allocator_coverage": "not_guaranteed",
                "worker_count": 1,
                "state_size_bytes": updated.canonical_size_bytes,
                "model_summary_canonical_bytes": summary_bytes,
                "model_summary_is_not_exported_artifact": True,
                "formal_metric_claim": False,
            }
        )
    return rows


def conditional_expected_future_statistic(
    world: World01, episode: PrivateEpisode, *, horizon: int = 4
) -> float:
    """Judge target E[||X_H||^2 | X_cut, theta, do(no-new-action)].

    The target integrates future process noise analytically.  It is not a
    single realised factual utility and is not part of ``PublicTrainingRecord``
    because that projection excludes ``latent_distribution``.
    """

    plan = _no_action(world, horizon)
    oracle = world.judge_true_state_counterfactual(
        episode.hidden_state_at_cut,
        episode.invariant_parameters,
        plan,
        horizon,
    )
    step = oracle.latent_distribution["steps"][-1]
    mean = np.asarray(step["mean"], dtype=np.float64)
    covariance = np.asarray(step["covariance"], dtype=np.float64)
    return float(mean @ mean + np.trace(covariance))


def _numeric_leaves(value: Any) -> list[float]:
    if type(value) is bool:
        return [float(value)]
    if type(value) in {int, float}:
        return [float(value)]
    if type(value) is list:
        return [number for item in value for number in _numeric_leaves(item)]
    if type(value) is dict:
        return [number for key in sorted(value) for number in _numeric_leaves(value[key])]
    return []


def _true_state_library(episode: PrivateEpisode, capacity: int) -> np.ndarray:
    raw = np.asarray(
        _numeric_leaves(episode.hidden_state_at_cut)
        + _numeric_leaves(episode.invariant_parameters),
        dtype=np.float64,
    )
    if not len(raw):
        raise ProtocolViolation("true-state control has no numeric leaves")
    values = list(raw)
    values.extend(float(value * value) for value in raw)
    values.extend(
        float(raw[left] * raw[right])
        for left in range(len(raw))
        for right in range(left + 1, len(raw))
    )
    base = np.asarray(values, dtype=np.float64)
    if len(base) >= capacity:
        return base[:capacity]
    output = list(base)
    index = 1
    while len(output) < capacity:
        source = base[(index - 1) % len(base)]
        output.append(float(math.sin(index * source) if index % 2 else math.cos(index * source)))
        index += 1
    return np.asarray(output, dtype=np.float64)


def _project_rows(rows: Sequence[np.ndarray], capacity: int, seed: int) -> np.ndarray:
    matrix = np.vstack(rows).astype(np.float64, copy=False)
    if matrix.shape[1] == capacity:
        return matrix
    rng = np.random.default_rng(seed)
    projection = rng.normal(0.0, 1.0 / math.sqrt(max(1, matrix.shape[1])), (matrix.shape[1], capacity))
    return matrix @ projection


def _standardize(train: np.ndarray, *others: np.ndarray) -> tuple[np.ndarray, ...]:
    mean = train.mean(axis=0)
    scale = train.std(axis=0)
    scale[scale < 1e-12] = 1.0
    return tuple((matrix - mean) / scale for matrix in (train, *others))


def _ridge_fit(x: np.ndarray, y: np.ndarray, regularization: float) -> np.ndarray:
    design = np.concatenate((np.ones((len(x), 1)), x), axis=1)
    penalty = np.eye(design.shape[1], dtype=np.float64) * regularization
    penalty[0, 0] = 0.0
    return np.linalg.pinv(design.T @ design + penalty, rcond=1e-12) @ design.T @ y


def _ridge_mse(
    train_x: np.ndarray,
    train_y: np.ndarray,
    test_x: np.ndarray,
    test_y: np.ndarray,
    regularization: float,
) -> float:
    weights = _ridge_fit(train_x, train_y, regularization)
    prediction = np.concatenate((np.ones((len(test_x), 1)), test_x), axis=1) @ weights
    return float(np.mean((prediction - test_y) ** 2))


def _capacity_ladder(maximum: int) -> tuple[int, ...]:
    values = []
    current = 1
    while current < maximum:
        values.append(current)
        current *= 2
    values.append(maximum)
    return tuple(sorted(set(values)))


def _m16_rows(family: str, config: SecondaryBatteryConfig) -> list[dict[str, Any]]:
    world = World01()
    fit_records = _records(
        world,
        WorldSplit.TRAIN,
        config.m16_candidate_train_examples,
        generator_seed=_seed(config.generator_seed, "M16", "candidate-fit"),
        oracle_seed=_seed(config.oracle_seed, "M16", "candidate-fit"),
    )
    candidate = make_battery_candidate(family)
    fit_finished_ns: int
    candidate.fit(
        (world.catalog,),
        fit_records,
        model_seed=_seed(config.model_seed, family, "M16", "candidate-fit"),
    )
    fit_finished_ns = time.perf_counter_ns()

    split_rows: dict[str, list[tuple[PrivateEpisode, SharedPatientState, float]]] = {}
    specifications = (
        (
            "readout_train",
            WorldSplit.TRAIN,
            config.m16_readout_train_examples,
            config.m16_candidate_train_examples + 100,
        ),
        ("validation", WorldSplit.VALIDATION, config.m16_readout_validation_examples, 100),
        ("sealed_test", WorldSplit.SEALED_TEST, config.m16_readout_test_examples, 100),
    )
    target_materialized_ns: int | None = None
    for name, split, count, offset in specifications:
        materialized = []
        for index in range(count):
            episode = world.generate_episode(
                split,
                _seed(config.generator_seed, "M16", name),
                offset + index,
            )
            state = candidate.initialize(
                episode.public_history,
                inference_seed=_seed(config.model_seed, family, "M16", name, index),
            )
            target = conditional_expected_future_statistic(world, episode)
            if target_materialized_ns is None:
                target_materialized_ns = time.perf_counter_ns()
            materialized.append((episode, state, target))
        split_rows[name] = materialized
    assert target_materialized_ns is not None

    state_dimension = len(split_rows["readout_train"][0][1].distance_vector)
    capacity = min(state_dimension, config.m16_max_capacity)
    ladder = _capacity_ladder(capacity)

    def state_matrix(name: str) -> np.ndarray:
        rows = [np.asarray(state.distance_vector, dtype=np.float64) for _, state, _ in split_rows[name]]
        return _project_rows(rows, capacity, _seed(config.model_seed, family, "M16", "state"))

    def history_matrix(name: str) -> np.ndarray:
        rows = [exact_history_feature_vector(episode.public_history.to_wire()) for episode, _, _ in split_rows[name]]
        return _project_rows(rows, capacity, _seed(config.model_seed, family, "M16", "history"))

    def true_matrix(name: str) -> np.ndarray:
        return np.vstack([_true_state_library(episode, capacity) for episode, _, _ in split_rows[name]])

    targets = {
        name: np.asarray([target for _, _, target in rows], dtype=np.float64)
        for name, rows in split_rows.items()
    }
    state_train, state_validation, state_test = _standardize(
        state_matrix("readout_train"), state_matrix("validation"), state_matrix("sealed_test")
    )
    history_train, history_validation, history_test = _standardize(
        history_matrix("readout_train"), history_matrix("validation"), history_matrix("sealed_test")
    )
    true_train, true_validation, true_test = _standardize(
        true_matrix("readout_train"), true_matrix("validation"), true_matrix("sealed_test")
    )
    rows: list[dict[str, Any]] = []
    for width in ladder:
        state_validation_mse = _ridge_mse(
            state_train[:, :width],
            targets["readout_train"],
            state_validation[:, :width],
            targets["validation"],
            config.ridge_regularization,
        )
        history_validation_mse = _ridge_mse(
            history_train[:, :width],
            targets["readout_train"],
            history_validation[:, :width],
            targets["validation"],
            config.ridge_regularization,
        )
        true_validation_mse = _ridge_mse(
            true_train[:, :width],
            targets["readout_train"],
            true_validation[:, :width],
            targets["validation"],
            config.ridge_regularization,
        )
        state_test_mse = _ridge_mse(
            state_train[:, :width],
            targets["readout_train"],
            state_test[:, :width],
            targets["sealed_test"],
            config.ridge_regularization,
        )
        history_test_mse = _ridge_mse(
            history_train[:, :width],
            targets["readout_train"],
            history_test[:, :width],
            targets["sealed_test"],
            config.ridge_regularization,
        )
        true_test_mse = _ridge_mse(
            true_train[:, :width],
            targets["readout_train"],
            true_test[:, :width],
            targets["sealed_test"],
            config.ridge_regularization,
        )
        rows.append(
            {
                "protocol": RAW_PROTOCOL,
                "metric": "M16",
                "family": family,
                "row_kind": "novel_readout_capacity_point",
                "capacity": width,
                "candidate_state_native_dimension": state_dimension,
                "state_only_validation_mse": state_validation_mse,
                "same_capacity_full_history_validation_mse": history_validation_mse,
                "judge_true_state_validation_mse": true_validation_mse,
                "state_only_sealed_test_mse": state_test_mse,
                "same_capacity_full_history_sealed_test_mse": history_test_mse,
                "judge_true_state_sealed_test_mse": true_test_mse,
                "oracle_target_identity_upper_mse": 0.0,
                "same_readout": "ridge_with_intercept",
                "same_regularization": float(config.ridge_regularization),
                "same_capacity_for_state_and_history": True,
                "target": "E[||X_H||^2 | judge_true_state, no_new_action, H=4]",
                "target_is_conditional_expectation_not_realized_noise": True,
                "target_excluded_from_public_training_record": True,
                "candidate_received_true_or_future": False,
                "candidate_fit_finished_before_target_materialization": fit_finished_ns < target_materialized_ns,
                "formal_metric_claim": False,
            }
        )
    return rows


_RUNNERS: dict[str, Callable[[str, SecondaryBatteryConfig], list[dict[str, Any]]]] = {
    "M09": _m09_rows,
    "M10": _m10_rows,
    "M11": _m11_rows,
    "M13": _m13_rows,
    "M16": _m16_rows,
}


def execute_secondary_battery(config: SecondaryBatteryConfig) -> dict[str, Any]:
    """Execute in memory and return canonical-JSON-compatible raw evidence."""

    if type(config) is not SecondaryBatteryConfig:
        raise ProtocolViolation("config must be SecondaryBatteryConfig")
    priority = _set_below_normal_priority(config.below_normal_priority)
    started = time.perf_counter_ns()
    rows: list[dict[str, Any]] = []
    for family in config.families:
        for metric in config.metrics:
            rows.extend(_RUNNERS[metric](family, config))
    elapsed = time.perf_counter_ns() - started
    return {
        "protocol": PROTOCOL,
        "status": "SECONDARY_EXPLORATORY_EVIDENCE",
        "formal_frozen_metric_claim": False,
        "candidate_input_boundary": [
            "public_catalog",
            "public_training_record",
            "visible_history_or_delta",
            "shared_patient_state",
        ],
        "judge_only_material_never_passed_to_candidate": [
            "hidden_state_at_cut",
            "invariant_parameters",
            "counterfactual_oracle",
            "future_statistic_target",
        ],
        "priority": priority,
        "worker_count": 1,
        "elapsed_ns": elapsed,
        "configuration": config.to_wire(),
        "rows": rows,
    }


def _source_binding() -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parent
    paths = (
        Path(__file__).resolve(),
        root / "candidate_families.py",
        root / "f22_switching_particle.py",
        root / "baselines_v2.py",
        root / "benchmark_v1_contract.py",
        root / "worlds" / "w01.py",
        root / "worlds" / "w04.py",
        root / "worlds" / "w13.py",
        root / "worlds" / "w16.py",
        root / "worlds" / "w17.py",
    )
    repository = root.parents[1]
    return [
        {
            "path": path.relative_to(repository).as_posix(),
            "byte_length": len(path.read_bytes()),
            "sha256": digest_bytes(path.read_bytes()),
        }
        for path in paths
    ]


def write_secondary_bundle(result: dict[str, Any], output_root: Path) -> Path:
    """Publish canonical raw JSONL + summary + self-digested manifest atomically."""

    if type(result) is not dict or result.get("protocol") != PROTOCOL:
        raise ProtocolViolation("result is not a secondary battery report")
    root = output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    config_digest = digest_json(result["configuration"])
    run_id = f"{timestamp}-SECONDARY-{config_digest[7:17]}"
    final = root / run_id
    if final.exists():
        raise ProtocolViolation("secondary run id already exists")
    temporary = root / f".{run_id}.tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir()
    try:
        raw = b"".join(canonical_json_bytes(row) for row in result["rows"])
        (temporary / "raw.jsonl").write_bytes(raw)
        summary = {key: value for key, value in result.items() if key != "rows"}
        summary["run_id"] = run_id
        summary["row_count"] = len(result["rows"])
        summary["metric_row_counts"] = {
            metric: sum(row["metric"] == metric for row in result["rows"])
            for metric in METRIC_IDS
            if metric in result["configuration"]["metrics"]
        }
        (temporary / "summary.json").write_bytes(canonical_json_bytes(summary))
        files = []
        for name in ("raw.jsonl", "summary.json"):
            content = (temporary / name).read_bytes()
            files.append(
                {"path": name, "byte_length": len(content), "sha256": digest_bytes(content)}
            )
        unsigned = {
            "protocol": MANIFEST_PROTOCOL,
            "run_id": run_id,
            "configuration_digest": config_digest,
            "source_binding": _source_binding(),
            "files": files,
        }
        manifest = {**unsigned, "bundle_root": digest_json(unsigned)}
        (temporary / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        os.replace(temporary, final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    verify_secondary_bundle(final)
    return final


def _decode_canonical(path: Path) -> Any:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{path.name} is invalid JSON") from exc
    if canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{path.name} is not canonical JSON")
    return value


def verify_secondary_bundle(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ProtocolViolation("secondary bundle must be a directory")
    names = {item.name for item in resolved.iterdir() if item.is_file()}
    if names != {"manifest.json", "raw.jsonl", "summary.json"}:
        raise ProtocolViolation("secondary bundle file closure mismatch")
    manifest = _decode_canonical(resolved / "manifest.json")
    if type(manifest) is not dict or manifest.get("protocol") != MANIFEST_PROTOCOL:
        raise ProtocolViolation("secondary manifest protocol mismatch")
    unsigned = {key: value for key, value in manifest.items() if key != "bundle_root"}
    if manifest.get("bundle_root") != digest_json(unsigned):
        raise ProtocolViolation("secondary manifest bundle_root mismatch")
    for row in manifest["files"]:
        raw = (resolved / row["path"]).read_bytes()
        if len(raw) != row["byte_length"] or digest_bytes(raw) != row["sha256"]:
            raise ProtocolViolation(f"secondary file binding mismatch: {row['path']}")
    summary = _decode_canonical(resolved / "summary.json")
    if summary.get("run_id") != manifest.get("run_id"):
        raise ProtocolViolation("secondary summary/manifest run id mismatch")
    raw_rows = []
    raw_payload = (resolved / "raw.jsonl").read_bytes()
    for line in raw_payload.splitlines(keepends=True):
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("secondary raw row is invalid JSON") from exc
        if canonical_json_bytes(value) != line or value.get("protocol") != RAW_PROTOCOL:
            raise ProtocolViolation("secondary raw row is not canonical/protocol-bound")
        raw_rows.append(value)
    if len(raw_rows) != summary.get("row_count"):
        raise ProtocolViolation("secondary raw row count mismatch")
    return {
        "status": "verified",
        "run_id": manifest["run_id"],
        "bundle_root": manifest["bundle_root"],
        "row_count": len(raw_rows),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--output-root", type=Path, default=Path("results/unified_map/secondary"))
    run.add_argument("--families", nargs="+", choices=ORDINARY_FAMILY_CODES, default=list(ORDINARY_FAMILY_CODES))
    run.add_argument("--metrics", nargs="+", choices=METRIC_IDS, default=list(METRIC_IDS))
    run.add_argument("--normal-priority", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        print(json.dumps(verify_secondary_bundle(args.path), sort_keys=True))
        return 0
    config = SecondaryBatteryConfig(
        families=tuple(args.families),
        metrics=tuple(args.metrics),
        below_normal_priority=not args.normal_priority,
    )
    result = execute_secondary_battery(config)
    bundle = write_secondary_bundle(result, args.output_root)
    print(json.dumps(verify_secondary_bundle(bundle), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "METRIC_IDS",
    "ORDINARY_FAMILY_CODES",
    "SecondaryBatteryConfig",
    "conditional_expected_future_statistic",
    "execute_secondary_battery",
    "make_battery_candidate",
    "verify_secondary_bundle",
    "write_secondary_bundle",
]
