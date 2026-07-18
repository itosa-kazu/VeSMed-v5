"""Exact PRE-FREEZE public-oracle upper bound for W10.

W10's three assays share a specimen disturbance.  The certificate below binds
the adapter to the joint covariance semantics in the live world instead of
pretending that three correlated channels are three independent evidence
units.  It records a same-values/different-grouping precision witness and a
posterior-nullspace witness; neither is promoted to candidate or freeze-grade
evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import ProtocolViolation, canonical_json_bytes
from .upper_bound_evaluator_w03 import (
    _PublicOracleAdapterConfig,
    _collect_public_oracle_upper_bound,
    _exact_source_world_factory,
    _register_loaded_evaluator_source,
    _source_bytes,
)
from .upper_bound_evaluator_w09 import (
    _attach_world_certificate,
    _semantic_history_without_uids,
    _verify_world_certificate_report,
)
from .worlds.base import PrivateEpisode
from .worlds.w10 import World10


DEFAULT_W10_SOURCE = Path("prototype/unified_map/worlds/w10.py")
DEFAULT_W10_ARTIFACT = DEFAULT_W10_SOURCE
_W10_ADAPTER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w10.py")
_W09_CERTIFICATE_HELPER_SOURCE = Path(
    "prototype/unified_map/upper_bound_evaluator_w09.py"
)
_CONFIG = _PublicOracleAdapterConfig(
    world_slot="W10",
    world_factory=World10,
    committed_source=DEFAULT_W10_SOURCE,
    generator_seed=92010,
    episode_index=13,
    oracle_seed=3010,
    # Production uses nested Owen-Sobol and an alternate, but not formally
    # source-separated, implementation uses a much larger Philox/antithetic
    # sample.  The world contract certifies the former at CI99 < .005; .02 is
    # only the expected-utility cross-check tolerance.
    reference_tolerance=0.02,
    source_class_name="World10",
    adapter_source=_W10_ADAPTER_SOURCE,
    additional_evaluator_sources=(_W09_CERTIFICATE_HELPER_SOURCE,),
)


def _exact_w10_world() -> World10:
    raw = _source_bytes(
        DEFAULT_W10_SOURCE,
        committed=DEFAULT_W10_SOURCE,
        world_slot="W10",
    )
    return _exact_source_world_factory(_CONFIG, raw)()  # type: ignore[return-value]


def _assay_panel(episode: PrivateEpisode) -> tuple[list[float], list[str]]:
    rows: dict[int, tuple[float, str]] = {}
    for event in episode.public_history.events:
        if event.kind.value != "observation_available":
            continue
        channel = str(event.payload.get("channel_id", ""))
        if channel not in {"obs_0", "obs_1", "obs_2"}:
            continue
        slot = int(event.payload.get("assay_slot", int(channel[-1])))
        rows[slot] = (
            float(event.payload["value"]),
            str(event.payload.get("specimen_uid", event.event_uid)),
        )
    if set(rows) != {0, 1, 2}:
        raise ProtocolViolation("W10 certificate requires a complete assay panel")
    return (
        [rows[index][0] for index in range(3)],
        [rows[index][1] for index in range(3)],
    )


def _component_rows(world: World10, episode: PrivateEpisode) -> list[dict[str, float]]:
    rows = world._posterior(episode)
    return [
        {
            "class": float(row["class"]),
            "mean": float(row["mean"]),
            "variance": float(row["variance"]),
            "weight": float(row["weight"]),
        }
        for row in rows
    ]


def _w10_semantic_certificate() -> dict[str, Any]:
    world = _exact_w10_world()
    fixtures = world.probe_fixtures(generator_seed=1010)
    grouped, independent = fixtures["same_values_different_grouping"]
    null_left, null_right = fixtures["posterior_equivalent_nullspace"]
    rename_left, rename_right = fixtures["false_split_alpha_rename"]

    grouped_values, grouped_specimens = _assay_panel(grouped)
    independent_values, independent_specimens = _assay_panel(independent)
    if grouped_values != independent_values:
        raise ProtocolViolation("W10 grouping fixture changed assay values")
    if len(set(grouped_specimens)) != 1 or len(set(independent_specimens)) != 3:
        raise ProtocolViolation("W10 specimen grouping witness is stale")

    grouped_components = _component_rows(world, grouped)
    independent_components = _component_rows(world, independent)
    if len(grouped_components) != len(independent_components):
        raise ProtocolViolation("W10 component catalogs disagree")
    if [row["class"] for row in grouped_components] != [
        row["class"] for row in independent_components
    ]:
        raise ProtocolViolation("W10 grouping fixture changed class identity")
    variance_margins = [
        left["variance"] - right["variance"]
        for left, right in zip(grouped_components, independent_components, strict=True)
    ]
    if not variance_margins or any(margin <= 0.0 for margin in variance_margins):
        raise ProtocolViolation("W10 grouped assays falsely gained iid precision")

    null_left_components = _component_rows(world, null_left)
    null_right_components = _component_rows(world, null_right)
    null_differences = [
        abs(left[field] - right[field])
        for left, right in zip(null_left_components, null_right_components, strict=True)
        for field in ("class", "mean", "variance", "weight")
    ]
    maximum_nullspace_difference = max(null_differences, default=0.0)
    if maximum_nullspace_difference > 1e-12:
        raise ProtocolViolation("W10 posterior nullspace witness drifted")

    rename_left_components = _component_rows(world, rename_left)
    rename_right_components = _component_rows(world, rename_right)
    if rename_left_components != rename_right_components:
        raise ProtocolViolation("W10 alpha renaming changed the joint posterior")
    if rename_left.public_history.digest == rename_right.public_history.digest:
        raise ProtocolViolation("W10 alpha rename did not change opaque identifiers")
    if _semantic_history_without_uids(rename_left) != _semantic_history_without_uids(
        rename_right
    ):
        raise ProtocolViolation("W10 alpha rename changed semantic event content")

    covariance_oracle = world.counterfactual(grouped, world.policy_set(4)[0], 4, 10101)
    panel_rows = covariance_oracle.observation_distribution.get("same_specimen_panel")
    if type(panel_rows) is not list or not panel_rows:
        raise ProtocolViolation("W10 joint covariance oracle rows are absent")
    matrices = [row.get("conditional_covariance") for row in panel_rows]
    first_matrix = matrices[0]
    if (
        any(matrix != first_matrix for matrix in matrices)
        or type(first_matrix) is not list
        or len(first_matrix) != 3
        or any(type(row) is not list or len(row) != 3 for row in first_matrix)
    ):
        raise ProtocolViolation("W10 joint covariance matrices are inconsistent")
    diagonal = [float(first_matrix[index][index]) for index in range(3)]
    off_diagonal = [
        float(first_matrix[left][right])
        for left in range(3)
        for right in range(left + 1, 3)
    ]
    if (
        len(set(diagonal)) != 1
        or len(set(off_diagonal)) != 1
        or off_diagonal[0] <= 0.0
        or diagonal[0] <= off_diagonal[0]
    ):
        raise ProtocolViolation(
            "W10 covariance is not shared-rank-one plus sensor diagonal"
        )
    shared_disturbance_variance = off_diagonal[0]
    per_assay_sensor_variance = diagonal[0] - off_diagonal[0]

    return {
        "protocol": "ucm-w10-shared-mechanism-certificate/1",
        "role": "pre_freeze_world_semantic_probe_not_candidate_score",
        "oracle_consumes_candidate_visible_history_only": True,
        "fixture_selection_candidate_visible_only": False,
        "fixture_custody": "judge-side-pre-freeze-probe",
        "formal_benchmark_claimed": False,
        "joint_likelihood_contract": {
            "shared_mechanism": True,
            "covariance_source": "live-same-specimen-panel-oracle",
            "conditional_covariance": first_matrix,
            "same_specimen_shared_disturbance_variance": (shared_disturbance_variance),
            "per_assay_sensor_variance": per_assay_sensor_variance,
            "iid_channel_product_likelihood_claimed": False,
            "grouped_assay_count": 3,
            "grouped_specimen_evidence_units": 1,
            "independent_specimen_evidence_units": 3,
            "effective_sample_size_claimed": False,
        },
        "same_values_different_grouping": {
            "assay_values": grouped_values,
            "grouped_specimen_count": len(set(grouped_specimens)),
            "independent_specimen_count": len(set(independent_specimens)),
            "grouped_components": grouped_components,
            "independent_components": independent_components,
            "grouped_minus_independent_variance": variance_margins,
            "all_grouped_variances_larger": True,
        },
        "posterior_equivalent_nullspace": {
            "left_components": null_left_components,
            "right_components": null_right_components,
            "maximum_absolute_component_difference": maximum_nullspace_difference,
            "absolute_tolerance": 1e-12,
            "passed": True,
        },
        "alpha_rename_invariance": {
            "left_components": rename_left_components,
            "right_components": rename_right_components,
            "history_digests_differ": (
                rename_left.public_history.digest != rename_right.public_history.digest
            ),
            "passed": True,
        },
    }


def run_w10_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W10_SOURCE,
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
    result = _attach_world_certificate(base, _w10_semantic_certificate())
    verify_w10_upper_bound_sanity(
        result, source_artifact=source_artifact, replay_runtime=True
    )
    return result


def verify_w10_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    _verify_world_certificate_report(
        value,
        _CONFIG,
        _w10_semantic_certificate,
        source_artifact=source_artifact,
        replay_runtime=replay_runtime,
    )


def w10_upper_bound_artifact_bytes(**kwargs: Any) -> bytes:
    return canonical_json_bytes(run_w10_upper_bound_sanity(**kwargs))


__all__ = [
    "DEFAULT_W10_ARTIFACT",
    "DEFAULT_W10_SOURCE",
    "run_w10_upper_bound_sanity",
    "verify_w10_upper_bound_sanity",
    "w10_upper_bound_artifact_bytes",
]


_register_loaded_evaluator_source(_W10_ADAPTER_SOURCE, __file__)
