"""Exact PRE-FREEZE public-oracle upper bound for W13.

The scored adapter state is the candidate-visible public history only.  The
world law is deliberately privileged and therefore remains an ineligible
upper bound with zero ledger credit.  A source-bound live certificate exercises
the nonlinear-comorbidity boundary: equal routine totals on opposite sides of
the threshold have different interaction transitions and futures, while UID
alpha-renaming does not create a false split.
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
from .worlds.w13 import World13


DEFAULT_W13_SOURCE = Path("prototype/unified_map/worlds/w13.py")
DEFAULT_W13_ARTIFACT = DEFAULT_W13_SOURCE
_ADAPTER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w13.py")
_CERTIFICATE_HELPER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w09.py")
_CONFIG = _PublicOracleAdapterConfig(
    world_slot="W13",
    world_factory=World13,
    committed_source=DEFAULT_W13_SOURCE,
    generator_seed=92013,
    # Index 0 is a predeclared train combination cell whose independent
    # quadrature agrees within the world's tested 0.05 absolute tolerance.
    episode_index=0,
    oracle_seed=3013,
    reference_tolerance=0.05,
    source_class_name="World13",
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
        raise ProtocolViolation(f"W13 fixture lacks public {channel_id}")
    rows.sort(key=lambda event: (event.available_at, event.event_uid))
    return float(rows[-1].payload["value"])


def _policy_outputs(
    world: World13,
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


def _threshold_transition_cell(world: World13) -> dict[str, Any]:
    below, above = world.threshold_fixture(seed=1312)
    below_total = _latest_channel(below, "obs_0")
    above_total = _latest_channel(above, "obs_0")
    below_interaction = _latest_channel(below, "obs_2")
    above_interaction = _latest_channel(above, "obs_2")
    if abs(below_total - above_total) > 1e-12:
        raise ProtocolViolation("W13 threshold pair no longer shares its routine total")
    if below_interaction != 0.0 or above_interaction <= 0.0:
        raise ProtocolViolation(
            "W13 threshold pair no longer crosses the interaction boundary"
        )

    # The public component panel identifies these values.  Replaying the
    # repository-owned nonlinear transition proves that z enters both dynamic
    # coordinates; an additive/no-interaction transition cannot reproduce it.
    # Derive the first pair exactly from the public sum/difference rather than
    # trusting the private fixture fields.
    component_pairs = tuple(
        (
            0.5 * (_latest_channel(ep, "obs_0") + _latest_channel(ep, "obs_1")),
            0.5 * (_latest_channel(ep, "obs_0") - _latest_channel(ep, "obs_1")),
        )
        for ep in (below, above)
    )
    nonlinear_next: list[list[float]] = []
    additive_next: list[list[float]] = []
    nonlinear_residuals: list[list[float]] = []
    for x0, x1 in component_pairs:
        next0, next1 = world._step(2, x0, x1, None)
        additive0 = 0.88 * x0 + 0.06
        additive1 = 0.84 * x1 + 0.08
        nonlinear_next.append([next0, next1])
        additive_next.append([additive0, additive1])
        nonlinear_residuals.append([next0 - additive0, next1 - additive1])
    if max(abs(value) for value in nonlinear_residuals[0]) > 1e-12:
        raise ProtocolViolation(
            "W13 below-threshold transition gained a nonlinear residual"
        )
    if min(nonlinear_residuals[1]) <= 0.0:
        raise ProtocolViolation(
            "W13 above-threshold transition lost its nonlinear residual"
        )

    below_utility, below_roots = _policy_outputs(
        world, below, horizon=1, oracle_seed=1312
    )
    above_utility, above_roots = _policy_outputs(
        world, above, horizon=1, oracle_seed=1312
    )
    if below_roots == above_roots or below_utility[0] == above_utility[0]:
        raise ProtocolViolation(
            "W13 threshold pair no longer has distinct live futures"
        )
    return {
        "cell_id": "W13.threshold_pair.nonlinear_transition",
        "candidate_visible_pair": True,
        "shared_routine_total": below_total,
        "public_interaction_values": [below_interaction, above_interaction],
        "public_components": [list(row) for row in component_pairs],
        "nonlinear_next_components": nonlinear_next,
        "additive_no_interaction_next_components": additive_next,
        "nonlinear_transition_residuals": nonlinear_residuals,
        "no_action_expected_utilities": [below_utility[0], above_utility[0]],
        "policy_utility_vectors": [below_utility, above_utility],
        "policy_output_roots": [below_roots, above_roots],
        "all_policy_outputs_distinct": all(
            left != right for left, right in zip(below_roots, above_roots, strict=True)
        ),
        "passed": True,
    }


def _interaction_class_cell(world: World13) -> dict[str, Any]:
    synergy, antagonism = world.distinguishable_fixture(seed=1311)
    components = [
        [
            0.5 * (_latest_channel(ep, "obs_0") + _latest_channel(ep, "obs_1")),
            0.5 * (_latest_channel(ep, "obs_0") - _latest_channel(ep, "obs_1")),
        ]
        for ep in (synergy, antagonism)
    ]
    if components[0] != components[1]:
        raise ProtocolViolation("W13 interaction-class pair changed its components")
    interactions = [
        _latest_channel(synergy, "obs_2"),
        _latest_channel(antagonism, "obs_2"),
    ]
    utilities: list[list[float]] = []
    roots: list[list[str]] = []
    for episode in (synergy, antagonism):
        row_utility, row_roots = _policy_outputs(
            world, episode, horizon=4, oracle_seed=1311
        )
        utilities.append(row_utility)
        roots.append(row_roots)
    if interactions[0] == interactions[1] or roots[0] == roots[1]:
        raise ProtocolViolation("W13 interaction classes are not behaviorally distinct")
    return {
        "cell_id": "W13.same_components.interaction_class",
        "candidate_visible_pair": True,
        "shared_public_components": components[0],
        "public_interaction_values": interactions,
        "policy_utility_vectors": utilities,
        "policy_output_roots": roots,
        "all_policy_outputs_distinct": all(
            left != right for left, right in zip(roots[0], roots[1], strict=True)
        ),
        "passed": True,
    }


def _equivalence_cell(world: World13) -> dict[str, Any]:
    first, renamed = world.equivalent_fixture(seed=1313)
    first_utility, first_roots = _policy_outputs(
        world, first, horizon=4, oracle_seed=1313
    )
    renamed_utility, renamed_roots = _policy_outputs(
        world, renamed, horizon=4, oracle_seed=1313
    )
    if first.public_history.digest == renamed.public_history.digest:
        raise ProtocolViolation("W13 alpha-renamed histories unexpectedly share bytes")
    if first_roots != renamed_roots:
        raise ProtocolViolation("W13 alpha renaming created a false behavior split")
    return {
        "cell_id": "W13.alpha_rename.equivalent",
        "history_digests_differ": True,
        "left_policy_utility_vector": first_utility,
        "right_policy_utility_vector": renamed_utility,
        "left_policy_output_roots": first_roots,
        "right_policy_output_roots": renamed_roots,
        "all_policy_outputs_byte_identical": True,
        "passed": True,
    }


def _w13_semantic_certificate() -> dict[str, Any]:
    source_raw = _source_bytes(
        DEFAULT_W13_SOURCE,
        committed=DEFAULT_W13_SOURCE,
        world_slot="W13",
    )
    world = _exact_source_world_factory(_CONFIG, source_raw)()
    cells = [
        _threshold_transition_cell(world),
        _interaction_class_cell(world),
        _equivalence_cell(world),
    ]
    return {
        "protocol": "ucm-w13-nonlinear-comorbidity-certificate/1",
        "role": "pre_freeze_world_semantic_probe_not_candidate_score",
        "candidate_visible_inputs_only": True,
        "formal_benchmark_claimed": False,
        "live_behavior_cells": cells,
        "live_behavior_cell_ids": [cell["cell_id"] for cell in cells],
        "nonlinear_interaction_exercised": True,
        "source_limitations": [
            "reference-is-expected-utility-only-and-source-separation-not-certified",
            "finite-fixture-certificate-not-a-formal-benchmark-score",
        ],
    }


def run_w13_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W13_SOURCE,
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
    result = _attach_world_certificate(base, _w13_semantic_certificate())
    verify_w13_upper_bound_sanity(
        result, source_artifact=source_artifact, replay_runtime=True
    )
    return result


def verify_w13_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    _verify_world_certificate_report(
        value,
        _CONFIG,
        _w13_semantic_certificate,
        source_artifact=source_artifact,
        replay_runtime=replay_runtime,
    )


def w13_upper_bound_artifact_bytes(**kwargs: Any) -> bytes:
    return canonical_json_bytes(run_w13_upper_bound_sanity(**kwargs))


__all__ = [
    "DEFAULT_W13_ARTIFACT",
    "DEFAULT_W13_SOURCE",
    "run_w13_upper_bound_sanity",
    "verify_w13_upper_bound_sanity",
    "w13_upper_bound_artifact_bytes",
]


_register_loaded_evaluator_source(_ADAPTER_SOURCE, __file__)
