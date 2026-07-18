"""Exact PRE-FREEZE public-oracle upper bound for W12.

The generic cells expose only the candidate-visible public history and use the
repository-owned W12 law as a deliberately ineligible upper bound.  The live
certificate below exercises the semantic distinction that W12 is meant to
preserve: observed expression is not mechanism state, the same mechanism has
host-dependent futures, and opaque event-UID renaming is behaviorally inert.
It is evidence machinery only, not a candidate score or freeze authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
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
from .worlds.base import CounterfactualOracle, PrivateEpisode
from .worlds.w12 import World12


DEFAULT_W12_SOURCE = Path("prototype/unified_map/worlds/w12.py")
DEFAULT_W12_ARTIFACT = DEFAULT_W12_SOURCE
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_ADAPTER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w12.py")
_GENERIC_ADAPTER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w03.py")
_CERTIFICATE_HELPER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w09.py")
_CONFIG = _PublicOracleAdapterConfig(
    world_slot="W12",
    world_factory=World12,
    committed_source=DEFAULT_W12_SOURCE,
    generator_seed=92012,
    episode_index=13,
    oracle_seed=3012,
    reference_tolerance=0.01,
    source_class_name="World12",
    adapter_source=_ADAPTER_SOURCE,
    additional_evaluator_sources=(_CERTIFICATE_HELPER_SOURCE,),
)


def _source_dependency_closure() -> dict[str, Any]:
    roles = (
        ("world_specific_adapter", _ADAPTER_SOURCE),
        ("generic_public_oracle_adapter", _GENERIC_ADAPTER_SOURCE),
        ("world_certificate_helper", _CERTIFICATE_HELPER_SOURCE),
        ("world_implementation", DEFAULT_W12_SOURCE),
    )
    artifacts: list[dict[str, Any]] = []
    for role, relpath in roles:
        try:
            raw = (_REPOSITORY_ROOT / relpath).read_bytes()
        except OSError as exc:
            raise ProtocolViolation(
                f"W12 source dependency is unavailable: {relpath.as_posix()}"
            ) from exc
        if not raw:
            raise ProtocolViolation(
                f"W12 source dependency is empty: {relpath.as_posix()}"
            )
        artifacts.append(
            {
                "role": role,
                "artifact_relpath": relpath.as_posix(),
                "artifact_digest": digest_bytes(raw),
                "artifact_bytes": len(raw),
            }
        )
    preimage = {
        "protocol": "ucm-w12-source-dependency-root/1",
        "artifacts": artifacts,
    }
    return {
        "protocol": "ucm-w12-source-dependency-closure/1",
        "closed": True,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "aggregate_root": digest_json(preimage),
    }


def _latest_channel(episode: PrivateEpisode, channel_id: str) -> float:
    rows = [
        event
        for event in episode.public_history.events
        if event.kind.value == "observation_available"
        and event.payload.get("channel_id") == channel_id
    ]
    if not rows:
        raise ProtocolViolation(f"W12 fixture lacks public {channel_id}")
    rows.sort(key=lambda event: (event.available_at, event.event_uid))
    return float(rows[-1].payload["value"])


def _first_step(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"W12 {label} distribution is not an object")
    steps = value.get("steps")
    if type(steps) is not list or not steps or type(steps[0]) is not dict:
        raise ProtocolViolation(f"W12 {label} distribution lacks a first step")
    return steps[0]


def _posterior(oracle: CounterfactualOracle) -> dict[str, float]:
    row = oracle.latent_distribution.get("diagnostic_posterior")
    if type(row) is not dict or set(row) != {"C0", "C1"}:
        raise ProtocolViolation("W12 diagnostic posterior is absent")
    result = {label: float(row[label]) for label in ("C0", "C1")}
    if (
        any(value < 0.0 or value > 1.0 for value in result.values())
        or abs(sum(result.values()) - 1.0) > 1e-12
    ):
        raise ProtocolViolation("W12 diagnostic posterior is invalid")
    return result


def _policy_outputs(
    world: World12,
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


def _same_expression_host_state_cell(world: World12) -> dict[str, Any]:
    low_host, high_host = world.distinguishable_fixture(seed=1211)
    routine_expression = [
        _latest_channel(low_host, "obs_0"),
        _latest_channel(high_host, "obs_0"),
    ]
    host_markers = [
        _latest_channel(low_host, "obs_1"),
        _latest_channel(high_host, "obs_1"),
    ]
    direct_mechanisms = [
        _latest_channel(low_host, "obs_2"),
        _latest_channel(high_host, "obs_2"),
    ]
    if abs(routine_expression[0] - routine_expression[1]) > 1e-12:
        raise ProtocolViolation(
            "W12 same-expression fixture changed routine expression"
        )
    if (
        host_markers[0] == host_markers[1]
        or direct_mechanisms[0] == direct_mechanisms[1]
    ):
        raise ProtocolViolation(
            "W12 same-expression fixture lost its host/state contrast"
        )

    no_action = world.policy_set(1)[0]
    no_action_oracles = [
        world.counterfactual(low_host, no_action, 1, 1211),
        world.counterfactual(high_host, no_action, 1, 1211),
    ]
    posteriors = [_posterior(oracle) for oracle in no_action_oracles]
    if not (
        posteriors[0]["C0"] > posteriors[0]["C1"]
        and posteriors[1]["C1"] > posteriors[1]["C0"]
    ):
        raise ProtocolViolation(
            "W12 public host marker no longer separates host classes"
        )
    latent_means = [
        float(_first_step(oracle.latent_distribution, "latent")["mean"])
        for oracle in no_action_oracles
    ]
    observed_means = [
        float(_first_step(oracle.observation_distribution, "observation")["obs_0_mean"])
        for oracle in no_action_oracles
    ]
    if latent_means[0] == latent_means[1] or observed_means[0] == observed_means[1]:
        raise ProtocolViolation(
            "W12 equal expression falsely collapsed host/state futures"
        )

    utilities: list[list[float]] = []
    roots: list[list[str]] = []
    for episode in (low_host, high_host):
        row_utility, row_roots = _policy_outputs(
            world, episode, horizon=4, oracle_seed=1211
        )
        utilities.append(row_utility)
        roots.append(row_roots)
    if roots[0] == roots[1]:
        raise ProtocolViolation(
            "W12 same-expression host states became behaviorally identical"
        )
    return {
        "cell_id": "W12.same_expression.host_state",
        "candidate_visible_pair": True,
        "shared_routine_expression": routine_expression[0],
        "public_host_markers": host_markers,
        "public_direct_mechanism_values": direct_mechanisms,
        "diagnostic_posteriors": posteriors,
        "no_action_latent_means": latent_means,
        "no_action_observed_expression_means": observed_means,
        "policy_utility_vectors": utilities,
        "policy_output_roots": roots,
        "all_policy_outputs_distinct": all(
            left != right for left, right in zip(roots[0], roots[1], strict=True)
        ),
        "passed": True,
    }


def _same_mechanism_host_future_cell(world: World12) -> dict[str, Any]:
    low_host, high_host = world.same_mechanism_fixture(seed=1212)
    mechanism_values = [
        _latest_channel(low_host, "obs_2"),
        _latest_channel(high_host, "obs_2"),
    ]
    host_markers = [
        _latest_channel(low_host, "obs_1"),
        _latest_channel(high_host, "obs_1"),
    ]
    current_expression = [
        _latest_channel(low_host, "obs_0"),
        _latest_channel(high_host, "obs_0"),
    ]
    if abs(mechanism_values[0] - mechanism_values[1]) > 1e-12:
        raise ProtocolViolation(
            "W12 same-mechanism fixture changed direct mechanism state"
        )
    if (
        host_markers[0] == host_markers[1]
        or current_expression[0] == current_expression[1]
    ):
        raise ProtocolViolation("W12 same mechanism lost its host-expression contrast")

    no_action, a1 = world.policy_set(1)[:2]
    no_action_oracles = [
        world.counterfactual(low_host, no_action, 1, 1212),
        world.counterfactual(high_host, no_action, 1, 1212),
    ]
    no_action_latent_means = [
        float(_first_step(oracle.latent_distribution, "latent")["mean"])
        for oracle in no_action_oracles
    ]
    latent_mean_drift = abs(no_action_latent_means[0] - no_action_latent_means[1])
    no_action_observed_means = [
        float(_first_step(oracle.observation_distribution, "observation")["obs_0_mean"])
        for oracle in no_action_oracles
    ]
    if latent_mean_drift > 1e-10:
        raise ProtocolViolation(
            "W12 same mechanism no longer shares its natural latent future"
        )
    if no_action_observed_means[0] == no_action_observed_means[1]:
        raise ProtocolViolation("W12 host modifier no longer changes observed future")

    a1_oracles = [
        world.counterfactual(low_host, a1, 1, 1212),
        world.counterfactual(high_host, a1, 1, 1212),
    ]
    a1_latent_means = [
        float(_first_step(oracle.latent_distribution, "latent")["mean"])
        for oracle in a1_oracles
    ]
    if a1_latent_means[0] == a1_latent_means[1]:
        raise ProtocolViolation("W12 A1 future lost its host-dependent effect")

    utilities: list[list[float]] = []
    roots: list[list[str]] = []
    for episode in (low_host, high_host):
        row_utility, row_roots = _policy_outputs(
            world, episode, horizon=4, oracle_seed=1212
        )
        utilities.append(row_utility)
        roots.append(row_roots)
    if roots[0] == roots[1]:
        raise ProtocolViolation("W12 same mechanism collapsed host-dependent futures")
    return {
        "cell_id": "W12.same_mechanism.different_host_future",
        "candidate_visible_pair": True,
        "shared_public_direct_mechanism": mechanism_values[0],
        "public_host_markers": host_markers,
        "current_expression_values": current_expression,
        "no_action_latent_means": no_action_latent_means,
        "maximum_natural_latent_mean_drift": latent_mean_drift,
        "latent_mean_absolute_tolerance": 1e-10,
        "no_action_observed_expression_means": no_action_observed_means,
        "a1_host_dependent_latent_means": a1_latent_means,
        "policy_utility_vectors": utilities,
        "policy_output_roots": roots,
        "all_policy_outputs_distinct": all(
            left != right for left, right in zip(roots[0], roots[1], strict=True)
        ),
        "passed": True,
    }


def _alpha_rename_equivalence_cell(world: World12) -> dict[str, Any]:
    first, renamed = world.equivalent_fixture(seed=1213)
    channels = ("obs_0", "obs_1", "obs_2")
    first_panel = {channel: _latest_channel(first, channel) for channel in channels}
    renamed_panel = {channel: _latest_channel(renamed, channel) for channel in channels}
    if first.public_history.digest == renamed.public_history.digest:
        raise ProtocolViolation("W12 alpha-renamed histories unexpectedly share bytes")
    if first_panel != renamed_panel:
        raise ProtocolViolation("W12 alpha renaming changed semantic observations")
    first_utility, first_roots = _policy_outputs(
        world, first, horizon=4, oracle_seed=1213
    )
    renamed_utility, renamed_roots = _policy_outputs(
        world, renamed, horizon=4, oracle_seed=991213
    )
    if first_roots != renamed_roots:
        raise ProtocolViolation("W12 alpha renaming created a false behavior split")
    return {
        "cell_id": "W12.alpha_rename.equivalent",
        "semantic_public_panel": first_panel,
        "history_digests_differ": True,
        "left_policy_utility_vector": first_utility,
        "right_policy_utility_vector": renamed_utility,
        "left_policy_output_roots": first_roots,
        "right_policy_output_roots": renamed_roots,
        "all_policy_outputs_byte_identical": True,
        "passed": True,
    }


def _w12_semantic_certificate() -> dict[str, Any]:
    source_raw = _source_bytes(
        DEFAULT_W12_SOURCE,
        committed=DEFAULT_W12_SOURCE,
        world_slot="W12",
    )
    world = _exact_source_world_factory(_CONFIG, source_raw)()
    cells = [
        _same_expression_host_state_cell(world),
        _same_mechanism_host_future_cell(world),
        _alpha_rename_equivalence_cell(world),
    ]
    return {
        "protocol": "ucm-w12-host-expression-certificate/1",
        "role": "pre_freeze_world_semantic_probe_not_candidate_score",
        "candidate_visible_inputs_only": True,
        "formal_benchmark_claimed": False,
        "source_dependency_closure": _source_dependency_closure(),
        "live_behavior_cells": cells,
        "live_behavior_cell_ids": [cell["cell_id"] for cell in cells],
        "shared_mechanism_not_host_specific_disease": True,
        "source_limitations": [
            "reference-is-expected-utility-only-and-source-separation-not-certified",
            "finite-fixture-certificate-not-a-formal-benchmark-score",
        ],
    }


def run_w12_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W12_SOURCE,
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
    result = _attach_world_certificate(base, _w12_semantic_certificate())
    verify_w12_upper_bound_sanity(
        result, source_artifact=source_artifact, replay_runtime=True
    )
    return result


def verify_w12_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    # The shared helper recomputes the entire certificate, including exact
    # dependency bytes and its aggregate root, before verifying the generic
    # source-bound report.  Re-signing a forged dependency digest is therefore
    # rejected by live replay rather than accepted as internally consistent.
    _verify_world_certificate_report(
        value,
        _CONFIG,
        _w12_semantic_certificate,
        source_artifact=source_artifact,
        replay_runtime=replay_runtime,
    )


def w12_upper_bound_artifact_bytes(**kwargs: Any) -> bytes:
    return canonical_json_bytes(run_w12_upper_bound_sanity(**kwargs))


__all__ = [
    "DEFAULT_W12_ARTIFACT",
    "DEFAULT_W12_SOURCE",
    "run_w12_upper_bound_sanity",
    "verify_w12_upper_bound_sanity",
    "w12_upper_bound_artifact_bytes",
]


_register_loaded_evaluator_source(_ADAPTER_SOURCE, __file__)
