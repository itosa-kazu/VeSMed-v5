"""Exact PRE-FREEZE public-oracle upper bound for W11.

The main cells use one candidate-visible public-history state.  A separate
live certificate shows the intended W11 boundary: a sum-only history retains
both mechanism modes, a public contrast can resolve the modes and reverse the
best treatment, and opaque UID alpha-renaming must not split the state.  The
certificate is upper-bound-only and carries no benchmark or candidate claim.
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
    _semantic_history_without_uids,
    _verify_world_certificate_report,
)
from .worlds.base import PrivateEpisode, WorldSplit
from .worlds.w11 import World11


DEFAULT_W11_SOURCE = Path("prototype/unified_map/worlds/w11.py")
DEFAULT_W11_ARTIFACT = DEFAULT_W11_SOURCE
_W11_ADAPTER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w11.py")
_W09_CERTIFICATE_HELPER_SOURCE = Path(
    "prototype/unified_map/upper_bound_evaluator_w09.py"
)
_CONFIG = _PublicOracleAdapterConfig(
    world_slot="W11",
    world_factory=World11,
    committed_source=DEFAULT_W11_SOURCE,
    generator_seed=92011,
    episode_index=2,
    oracle_seed=3011,
    reference_tolerance=0.02,
    source_class_name="World11",
    adapter_source=_W11_ADAPTER_SOURCE,
    additional_evaluator_sources=(_W09_CERTIFICATE_HELPER_SOURCE,),
)


def _exact_w11_world() -> World11:
    raw = _source_bytes(
        DEFAULT_W11_SOURCE,
        committed=DEFAULT_W11_SOURCE,
        world_slot="W11",
    )
    return _exact_source_world_factory(_CONFIG, raw)()  # type: ignore[return-value]


def _posterior(oracle: Any) -> list[float]:
    row = oracle.latent_distribution.get("diagnostic_posterior")
    if type(row) is not dict or set(row) != {"C0", "C1"}:
        raise ProtocolViolation("W11 diagnostic posterior is absent")
    values = [float(row["C0"]), float(row["C1"])]
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ProtocolViolation("W11 diagnostic posterior is invalid")
    return values


def _latest_channel(episode: PrivateEpisode, channel_id: str) -> float | None:
    rows = [
        event
        for event in episode.public_history.events
        if event.kind.value == "observation_available"
        and event.payload.get("channel_id") == channel_id
    ]
    if not rows:
        return None
    rows.sort(key=lambda event: (event.available_at, event.event_uid))
    return float(rows[-1].payload["value"])


def _policy_outputs(
    world: World11, episode: PrivateEpisode, *, oracle_seed: int
) -> tuple[list[float], list[str]]:
    oracles = [
        world.counterfactual(episode, policy, 4, oracle_seed)
        for policy in world.policy_set(4)
    ]
    return (
        [float(oracle.expected_utility) for oracle in oracles],
        [digest_json(_oracle_wire(oracle)) for oracle in oracles],
    )


def _w11_semantic_certificate() -> dict[str, Any]:
    world = _exact_w11_world()
    seed = 1111
    q1_missing = world.generate_episode(WorldSplit.SEALED_TEST, seed, 14)
    q1_missing_oracle = world.counterfactual(
        q1_missing, world.policy_set(4)[0], 4, seed
    )
    ambiguous_posterior = _posterior(q1_missing_oracle)
    if _latest_channel(q1_missing, "obs_1") is not None:
        raise ProtocolViolation("W11 ambiguity witness unexpectedly contains Q1")
    if min(ambiguous_posterior) < 0.05:
        raise ProtocolViolation("W11 sum-only witness is no longer multimodal")

    distinguishable_left, distinguishable_right = world.distinguishable_fixture(seed)
    if _latest_channel(distinguishable_left, "obs_0") != _latest_channel(
        distinguishable_right, "obs_0"
    ):
        raise ProtocolViolation("W11 distinguishable pair changed total burden")
    left_utility, left_roots = _policy_outputs(
        world, distinguishable_left, oracle_seed=seed
    )
    right_utility, right_roots = _policy_outputs(
        world, distinguishable_right, oracle_seed=seed
    )
    left_best = left_utility.index(max(left_utility))
    right_best = right_utility.index(max(right_utility))
    if left_best == right_best:
        raise ProtocolViolation("W11 public contrast no longer changes best policy")
    left_posterior = _posterior(
        world.counterfactual(distinguishable_left, world.policy_set(4)[0], 4, seed)
    )
    right_posterior = _posterior(
        world.counterfactual(distinguishable_right, world.policy_set(4)[0], 4, seed)
    )
    posterior_mode_indices = [
        left_posterior.index(max(left_posterior)),
        right_posterior.index(max(right_posterior)),
    ]
    if posterior_mode_indices != [0, 1]:
        raise ProtocolViolation("W11 public contrast did not resolve opposite modes")

    equivalent_left, equivalent_right = world.equivalent_fixture(seed + 2)
    equivalent_left_utility, equivalent_left_roots = _policy_outputs(
        world, equivalent_left, oracle_seed=seed
    )
    equivalent_right_utility, equivalent_right_roots = _policy_outputs(
        world, equivalent_right, oracle_seed=seed
    )
    if equivalent_left_roots != equivalent_right_roots:
        raise ProtocolViolation("W11 UID alpha rename created a false split")
    if equivalent_left.public_history.digest == equivalent_right.public_history.digest:
        raise ProtocolViolation("W11 alpha rename did not change opaque identifiers")
    if _semantic_history_without_uids(
        equivalent_left
    ) != _semantic_history_without_uids(equivalent_right):
        raise ProtocolViolation("W11 alpha rename changed semantic event content")

    return {
        "protocol": "ucm-w11-multimechanism-certificate/1",
        "role": "pre_freeze_world_semantic_probe_not_candidate_score",
        "oracle_consumes_candidate_visible_history_only": True,
        "fixture_selection_candidate_visible_only": False,
        "fixture_custody": "judge-side-pre-freeze-probe",
        "formal_benchmark_claimed": False,
        "sum_only_multimodal_posterior": {
            "split": WorldSplit.SEALED_TEST.value,
            "episode_index": 14,
            "q1_present": False,
            "posterior_label_order": ["C0", "C1"],
            "posterior": ambiguous_posterior,
            "minimum_mode_mass": min(ambiguous_posterior),
            "minimum_required_mass": 0.05,
            "passed": True,
        },
        "public_contrast_distinguishable_pair": {
            "shared_obs_0": _latest_channel(distinguishable_left, "obs_0"),
            "obs_1_values": [
                _latest_channel(distinguishable_left, "obs_1"),
                _latest_channel(distinguishable_right, "obs_1"),
            ],
            "posteriors": [left_posterior, right_posterior],
            "posterior_mode_indices": posterior_mode_indices,
            "posterior_modes_differ": True,
            "utility_vectors": [left_utility, right_utility],
            "policy_output_roots": [left_roots, right_roots],
            "best_policy_indices": [left_best, right_best],
            "best_policy_differs": True,
        },
        "alpha_rename_equivalent_pair": {
            "history_digests_differ": (
                equivalent_left.public_history.digest
                != equivalent_right.public_history.digest
            ),
            "left_utility_vector": equivalent_left_utility,
            "right_utility_vector": equivalent_right_utility,
            "left_policy_output_roots": equivalent_left_roots,
            "right_policy_output_roots": equivalent_right_roots,
            "all_policy_outputs_byte_identical": True,
        },
        "source_limitations": [
            "reference-is-expected-utility-only-and-source-separation-not-certified",
            "multimodal-certificate-is-a-finite-public-fixture-not-a-candidate-score",
        ],
    }


def run_w11_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W11_SOURCE,
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
    result = _attach_world_certificate(base, _w11_semantic_certificate())
    verify_w11_upper_bound_sanity(
        result, source_artifact=source_artifact, replay_runtime=True
    )
    return result


def verify_w11_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    _verify_world_certificate_report(
        value,
        _CONFIG,
        _w11_semantic_certificate,
        source_artifact=source_artifact,
        replay_runtime=replay_runtime,
    )


def w11_upper_bound_artifact_bytes(**kwargs: Any) -> bytes:
    return canonical_json_bytes(run_w11_upper_bound_sanity(**kwargs))


__all__ = [
    "DEFAULT_W11_ARTIFACT",
    "DEFAULT_W11_SOURCE",
    "run_w11_upper_bound_sanity",
    "verify_w11_upper_bound_sanity",
    "w11_upper_bound_artifact_bytes",
]


_register_loaded_evaluator_source(_W11_ADAPTER_SOURCE, __file__)
