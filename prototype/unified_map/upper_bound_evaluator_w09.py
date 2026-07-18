"""Exact PRE-FREEZE public-oracle upper bound and baseline probes for W09.

The candidate-visible state in this adapter is only the W09 ``PublicHistory``.
The world law is used as a deliberately ineligible upper bound; the extra
certificate exercises W09's public baseline fixtures and is not a candidate
score or benchmark-freeze artifact.  Both the generic cells and the
world-specific certificate are reconstructed live from the repository-owned
``worlds/w09.py`` bytes on every verification.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    validate_json_like,
)
from .upper_bound_evaluator import (
    _attach_bundle_root,
    compute_upper_bound_bundle_root,
)
from .upper_bound_evaluator_w03 import (
    _PublicOracleAdapterConfig,
    _collect_public_oracle_upper_bound,
    _evaluator_source_closure,
    _exact_source_world_factory,
    _oracle_wire,
    _register_loaded_evaluator_source,
    _source_bytes,
    _verify_public_oracle_upper_bound,
)
from .worlds.base import PrivateEpisode
from .worlds.w09 import World09


DEFAULT_W09_SOURCE = Path("prototype/unified_map/worlds/w09.py")
DEFAULT_W09_ARTIFACT = DEFAULT_W09_SOURCE
_W09_ADAPTER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w09.py")
_CONFIG = _PublicOracleAdapterConfig(
    world_slot="W09",
    world_factory=World09,
    committed_source=DEFAULT_W09_SOURCE,
    generator_seed=92009,
    episode_index=13,
    oracle_seed=3009,
    reference_tolerance=1e-12,
    source_class_name="World09",
    adapter_source=_W09_ADAPTER_SOURCE,
)


def _exact_w09_world() -> World09:
    raw = _source_bytes(
        DEFAULT_W09_SOURCE,
        committed=DEFAULT_W09_SOURCE,
        world_slot="W09",
    )
    return _exact_source_world_factory(_CONFIG, raw)()  # type: ignore[return-value]


def _public_observation_values(episode: PrivateEpisode, channel_id: str) -> list[float]:
    rows = [
        event
        for event in episode.public_history.events
        if event.kind.value == "observation_available"
        and event.payload.get("channel_id") == channel_id
    ]
    rows.sort(
        key=lambda event: (
            event.collected_at if event.collected_at is not None else event.occurred_at,
            event.available_at,
            event.event_uid,
        )
    )
    return [float(event.payload["value"]) for event in rows]


def _semantic_history_without_uids(episode: PrivateEpisode) -> dict[str, Any]:
    wire = episode.public_history.to_wire()
    events = [
        {key: deepcopy(value) for key, value in event.items() if key != "event_uid"}
        for event in wire["events"]
    ]
    events.sort(key=canonical_json_bytes)
    return {
        "protocol": wire["protocol"],
        "catalog_digest": wire["catalog_digest"],
        "as_of_available_at": wire["as_of_available_at"],
        "events": events,
    }


def _utility_vector(
    world: World09, episode: PrivateEpisode, *, oracle_seed: int
) -> list[float]:
    return [
        float(world.counterfactual(episode, policy, 4, oracle_seed).expected_utility)
        for policy in world.policy_set(4)
    ]


def _output_roots(
    world: World09, episode: PrivateEpisode, *, oracle_seed: int
) -> list[str]:
    from .canonical import digest_json

    return [
        digest_json(_oracle_wire(world.counterfactual(episode, policy, 4, oracle_seed)))
        for policy in world.policy_set(4)
    ]


def _w09_semantic_certificate() -> dict[str, Any]:
    world = _exact_w09_world()
    fixtures = world.probe_fixtures(generator_seed=909)
    low_baseline, high_baseline = fixtures["same_absolute_collision"]
    translated_from, translated_to = fixtures["interior_translation"]
    private_left, private_right = fixtures["identical_prefix_private_decomposition"]
    rename_left, rename_right = fixtures["false_split_alpha_rename"]
    seed = 9091

    absolute_left = _public_observation_values(low_baseline, "obs_0")
    absolute_right = _public_observation_values(high_baseline, "obs_0")
    baseline_left = _public_observation_values(low_baseline, "obs_1")
    baseline_right = _public_observation_values(high_baseline, "obs_1")
    if absolute_left != absolute_right or not absolute_left:
        raise ProtocolViolation("W09 same-absolute fixture is stale")
    if not baseline_left or not baseline_right or baseline_left == baseline_right:
        raise ProtocolViolation("W09 baseline witness is absent")

    collision_left_utility = _utility_vector(world, low_baseline, oracle_seed=seed)
    collision_right_utility = _utility_vector(world, high_baseline, oracle_seed=seed)
    collision_best = [
        collision_left_utility.index(max(collision_left_utility)),
        collision_right_utility.index(max(collision_right_utility)),
    ]
    if collision_best[0] == collision_best[1]:
        raise ProtocolViolation("W09 baseline fixture no longer changes optimal policy")

    translated_left_utility = _utility_vector(world, translated_from, oracle_seed=seed)
    translated_right_utility = _utility_vector(world, translated_to, oracle_seed=seed)
    left_contrasts = [
        value - translated_left_utility[0] for value in translated_left_utility[1:3]
    ]
    right_contrasts = [
        value - translated_right_utility[0] for value in translated_right_utility[1:3]
    ]
    maximum_translation_contrast_drift = max(
        abs(left - right)
        for left, right in zip(left_contrasts, right_contrasts, strict=True)
    )
    if maximum_translation_contrast_drift > 0.01:
        raise ProtocolViolation(
            "W09 translation witness exceeds its declared tolerance"
        )

    private_left_roots = _output_roots(world, private_left, oracle_seed=seed)
    private_right_roots = _output_roots(world, private_right, oracle_seed=seed)
    rename_left_roots = _output_roots(world, rename_left, oracle_seed=seed)
    rename_right_roots = _output_roots(world, rename_right, oracle_seed=seed)
    if private_left.public_history.to_wire() != private_right.public_history.to_wire():
        raise ProtocolViolation("W09 private-decomposition prefixes differ")
    if private_left_roots != private_right_roots:
        raise ProtocolViolation("W09 public oracle consumed private decomposition")
    if rename_left_roots != rename_right_roots:
        raise ProtocolViolation("W09 alpha renaming created a false split")
    if rename_left.public_history.digest == rename_right.public_history.digest:
        raise ProtocolViolation("W09 alpha rename did not change opaque identifiers")
    if _semantic_history_without_uids(rename_left) != _semantic_history_without_uids(
        rename_right
    ):
        raise ProtocolViolation("W09 alpha rename changed semantic event content")

    return {
        "protocol": "ucm-w09-public-baseline-certificate/1",
        "role": "pre_freeze_world_semantic_probe_not_candidate_score",
        "oracle_consumes_candidate_visible_history_only": True,
        "fixture_selection_candidate_visible_only": False,
        "fixture_custody": "judge-side-pre-freeze-probe",
        "formal_benchmark_claimed": False,
        "same_absolute_different_baseline": {
            "absolute_series": absolute_left,
            "baseline_measurements": [baseline_left[-1], baseline_right[-1]],
            "utility_vectors": [collision_left_utility, collision_right_utility],
            "best_policy_indices": collision_best,
            "best_policy_differs": True,
        },
        "joint_translation": {
            "translated_channels": ["obs_0", "obs_1"],
            "translation_delta": 0.05,
            "treatment_contrast_indices": [1, 2],
            "maximum_contrast_drift": maximum_translation_contrast_drift,
            "absolute_tolerance": 0.01,
            "passed": True,
        },
        "private_decomposition_invariance": {
            "public_history_byte_identical": True,
            "policy_output_roots": private_left_roots,
            "private_swap_output_roots": private_right_roots,
            "passed": True,
        },
        "alpha_rename_invariance": {
            "semantic_event_values_unchanged": True,
            "history_digests_differ": (
                rename_left.public_history.digest != rename_right.public_history.digest
            ),
            "policy_output_roots": rename_left_roots,
            "renamed_policy_output_roots": rename_right_roots,
            "passed": True,
        },
    }


def _attach_world_certificate(
    base_report: dict[str, Any], certificate: dict[str, Any]
) -> dict[str, Any]:
    body = deepcopy(base_report)
    body.pop("bundle_root", None)
    body["world_semantic_certificate"] = deepcopy(certificate)
    return _attach_bundle_root(body)


def _verify_world_certificate_report(
    value: object,
    config: _PublicOracleAdapterConfig,
    certificate_factory: Callable[[], dict[str, Any]],
    *,
    source_artifact: Path | str | None,
    replay_runtime: bool,
) -> None:
    # Fail before executing the imported certificate factory if any adapter or
    # shared-helper bytes changed after import.  Otherwise a long-lived process
    # could bind fresh source digests to stale Python code objects.
    _evaluator_source_closure(config)
    if type(value) is not dict:
        raise ProtocolViolation("world-certificate report must be an object")
    report = deepcopy(value)
    validate_json_like(report)
    if report.get("bundle_root") != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("world-certificate bundle root mismatch")
    try:
        certificate = report.pop("world_semantic_certificate")
    except KeyError as exc:
        raise ProtocolViolation("world semantic certificate is absent") from exc
    expected_certificate = certificate_factory()
    if canonical_json_bytes(certificate) != canonical_json_bytes(expected_certificate):
        raise ProtocolViolation("world semantic certificate is not the live replay")

    # Restore the exact generic report root and let the shared verifier enforce
    # its closed schema, source binding, state/cell bindings and live replay.
    report["bundle_root"] = compute_upper_bound_bundle_root(report)
    _verify_public_oracle_upper_bound(
        report,
        config,
        source_artifact=source_artifact,
        replay_runtime=replay_runtime,
    )


def run_w09_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W09_SOURCE,
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
    result = _attach_world_certificate(base, _w09_semantic_certificate())
    verify_w09_upper_bound_sanity(
        result, source_artifact=source_artifact, replay_runtime=True
    )
    return result


def verify_w09_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    _verify_world_certificate_report(
        value,
        _CONFIG,
        _w09_semantic_certificate,
        source_artifact=source_artifact,
        replay_runtime=replay_runtime,
    )


def w09_upper_bound_artifact_bytes(**kwargs: Any) -> bytes:
    return canonical_json_bytes(run_w09_upper_bound_sanity(**kwargs))


__all__ = [
    "DEFAULT_W09_ARTIFACT",
    "DEFAULT_W09_SOURCE",
    "run_w09_upper_bound_sanity",
    "verify_w09_upper_bound_sanity",
    "w09_upper_bound_artifact_bytes",
]


_register_loaded_evaluator_source(_W09_ADAPTER_SOURCE, __file__)
