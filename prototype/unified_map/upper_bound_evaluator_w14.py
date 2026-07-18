"""Exact PRE-FREEZE public-oracle upper bound for W14.

The adapter binds one candidate-visible public-history state and uses the
repository world law only as an explicitly privileged, ineligible upper bound.
Its live semantic cells prove the intended path-dependence boundary: histories
with the same current observation can imply different finite lag states and
opposite best actions, whereas different raw paths with the same sufficient lag
state have identical futures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import ProtocolViolation, canonical_json_bytes, digest_json
from .upper_bound_evaluator_w03 import (
    _PublicOracleAdapterConfig,
    _collect_public_oracle_upper_bound,
    _exact_source_world_factory,
    _oracle_wire,
    _register_loaded_evaluator_source,
    _source_bytes,
)
from .upper_bound_evaluator_w09 import (
    _attach_world_certificate,
    _verify_world_certificate_report,
)
from .worlds.base import PrivateEpisode
from .worlds.w14 import World14


DEFAULT_W14_SOURCE = Path("prototype/unified_map/worlds/w14.py")
DEFAULT_W14_ARTIFACT = DEFAULT_W14_SOURCE
_ADAPTER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w14.py")
_CERTIFICATE_HELPER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w09.py")
_CONFIG = _PublicOracleAdapterConfig(
    world_slot="W14",
    world_factory=World14,
    committed_source=DEFAULT_W14_SOURCE,
    generator_seed=92014,
    episode_index=13,
    oracle_seed=3014,
    reference_tolerance=0.04,
    source_class_name="World14",
    adapter_source=_ADAPTER_SOURCE,
    additional_evaluator_sources=(_CERTIFICATE_HELPER_SOURCE,),
)


def _latest_channel(episode: PrivateEpisode, channel_id: str) -> float:
    rows = [
        event
        for event in episode.public_history.events
        if event.kind.value == "observation_available"
        and event.payload.get("channel_id") == channel_id
    ]
    if not rows:
        raise ProtocolViolation(f"W14 fixture lacks public {channel_id}")
    rows.sort(key=lambda event: (event.available_at, event.event_uid))
    return float(rows[-1].payload["value"])


def _policy_outputs(
    world: World14,
    episode: PrivateEpisode,
    *,
    horizon: int,
    oracle_seed: int,
) -> tuple[list[float], list[str]]:
    oracles = [
        world.counterfactual(episode, policy, horizon, oracle_seed)
        for policy in world.policy_set(horizon)
    ]
    return (
        [float(oracle.expected_utility) for oracle in oracles],
        [digest_json(_oracle_wire(oracle)) for oracle in oracles],
    )


def _same_snapshot_different_memory_cell(world: World14) -> dict[str, Any]:
    low_memory, high_memory = world.distinguishable_fixture(seed=1411)
    latest = [
        _latest_channel(low_memory, "obs_0"),
        _latest_channel(high_memory, "obs_0"),
    ]
    if latest[0] != latest[1]:
        raise ProtocolViolation("W14 path pair no longer shares its current snapshot")
    summaries = [
        list(world._public_memory_summary(low_memory)),
        list(world._public_memory_summary(high_memory)),
    ]
    if summaries[0][0] != summaries[1][0] or summaries[0][1] == summaries[1][1]:
        raise ProtocolViolation("W14 path pair no longer differs only in lag memory")

    low_utility, low_roots = _policy_outputs(
        world, low_memory, horizon=1, oracle_seed=1411
    )
    high_utility, high_roots = _policy_outputs(
        world, high_memory, horizon=1, oracle_seed=1411
    )
    best = [low_utility.index(max(low_utility)), high_utility.index(max(high_utility))]
    if best[0] == best[1] or low_roots == high_roots:
        raise ProtocolViolation("W14 lag-state pair no longer changes live behavior")
    return {
        "cell_id": "W14.same_current.different_path_memory",
        "candidate_visible_pair": True,
        "latest_observation_values": latest,
        "latest_observation_only_collides": True,
        "public_finite_state_values": summaries,
        "path_memory_values_differ": True,
        "policy_utility_vectors": [low_utility, high_utility],
        "policy_output_roots": [low_roots, high_roots],
        "best_policy_indices": best,
        "best_policy_differs": True,
        "history_deletion_changes_behavioral_state": True,
        "passed": True,
    }


def _same_sufficient_state_cell(world: World14) -> dict[str, Any]:
    first, second = world.equivalent_fixture(seed=1413)
    if first.public_history.digest == second.public_history.digest:
        raise ProtocolViolation("W14 convergent raw paths unexpectedly share bytes")
    summaries = [
        list(world._public_memory_summary(first)),
        list(world._public_memory_summary(second)),
    ]
    if summaries[0] != summaries[1]:
        raise ProtocolViolation("W14 equivalent fixture lost finite-state convergence")
    first_utility, first_roots = _policy_outputs(
        world, first, horizon=8, oracle_seed=1413
    )
    second_utility, second_roots = _policy_outputs(
        world, second, horizon=8, oracle_seed=1413
    )
    if first_roots != second_roots:
        raise ProtocolViolation("W14 equal lag state created a false behavior split")
    return {
        "cell_id": "W14.different_paths.same_finite_state",
        "candidate_visible_pair": True,
        "history_digests_differ": True,
        "shared_public_finite_state": summaries[0],
        "left_policy_utility_vector": first_utility,
        "right_policy_utility_vector": second_utility,
        "left_policy_output_roots": first_roots,
        "right_policy_output_roots": second_roots,
        "all_policy_outputs_byte_identical": True,
        "passed": True,
    }


def _alpha_equivalence_cell(world: World14) -> dict[str, Any]:
    first, renamed = world.alpha_equivalent_fixture(seed=1414)
    first_utility, first_roots = _policy_outputs(
        world, first, horizon=4, oracle_seed=1414
    )
    renamed_utility, renamed_roots = _policy_outputs(
        world, renamed, horizon=4, oracle_seed=1414
    )
    if first.public_history.digest == renamed.public_history.digest:
        raise ProtocolViolation("W14 alpha-renamed histories unexpectedly share bytes")
    if first_roots != renamed_roots:
        raise ProtocolViolation("W14 alpha renaming created a false behavior split")
    return {
        "cell_id": "W14.alpha_rename.equivalent",
        "history_digests_differ": True,
        "left_policy_utility_vector": first_utility,
        "right_policy_utility_vector": renamed_utility,
        "left_policy_output_roots": first_roots,
        "right_policy_output_roots": renamed_roots,
        "all_policy_outputs_byte_identical": True,
        "passed": True,
    }


def _w14_semantic_certificate() -> dict[str, Any]:
    source_raw = _source_bytes(
        DEFAULT_W14_SOURCE,
        committed=DEFAULT_W14_SOURCE,
        world_slot="W14",
    )
    world = _exact_source_world_factory(_CONFIG, source_raw)()
    cells = [
        _same_snapshot_different_memory_cell(world),
        _same_sufficient_state_cell(world),
        _alpha_equivalence_cell(world),
    ]
    return {
        "protocol": "ucm-w14-path-memory-certificate/1",
        "role": "pre_freeze_world_semantic_probe_not_candidate_score",
        "candidate_visible_inputs_only": True,
        "formal_benchmark_claimed": False,
        "live_behavior_cells": cells,
        "live_behavior_cell_ids": [cell["cell_id"] for cell in cells],
        "path_memory_exercised": True,
        "latest-observation-state-claim": False,
        "source_limitations": [
            "reference-is-expected-utility-only-and-source-separation-not-certified",
            "finite-fixture-certificate-not-a-formal-benchmark-score",
        ],
    }


def run_w14_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W14_SOURCE,
    generator_seed: int = _CONFIG.generator_seed,
    episode_index: int = _CONFIG.episode_index,
    oracle_seed: int = _CONFIG.oracle_seed,
) -> dict[str, Any]:
    base = _collect_public_oracle_upper_bound(
        _CONFIG,
        source_artifact=source_artifact,
        generator_seed=generator_seed,
        episode_index=episode_index,
        oracle_seed=oracle_seed,
    )
    result = _attach_world_certificate(base, _w14_semantic_certificate())
    verify_w14_upper_bound_sanity(
        result, source_artifact=source_artifact, replay_runtime=True
    )
    return result


def verify_w14_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    _verify_world_certificate_report(
        value,
        _CONFIG,
        _w14_semantic_certificate,
        source_artifact=source_artifact,
        replay_runtime=replay_runtime,
    )


def w14_upper_bound_artifact_bytes(**kwargs: Any) -> bytes:
    return canonical_json_bytes(run_w14_upper_bound_sanity(**kwargs))


__all__ = [
    "DEFAULT_W14_ARTIFACT",
    "DEFAULT_W14_SOURCE",
    "run_w14_upper_bound_sanity",
    "verify_w14_upper_bound_sanity",
    "w14_upper_bound_artifact_bytes",
]


_register_loaded_evaluator_source(_ADAPTER_SOURCE, __file__)
