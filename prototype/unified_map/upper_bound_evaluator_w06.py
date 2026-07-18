"""Exact PRE-FREEZE public-history oracle upper bound for W06.

W06's separate reference entrypoint returns expected utility only.  The shared
adapter records a live utility-only reference blocker and, without embedded
source-separation certification, makes no source-distinct claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes
from .upper_bound_evaluator_w03 import (
    _PublicOracleAdapterConfig,
    _collect_public_oracle_upper_bound,
    _register_loaded_evaluator_source,
    _verify_public_oracle_upper_bound,
)
from .worlds.w06 import World06


DEFAULT_W06_SOURCE = Path("prototype/unified_map/worlds/w06.py")
DEFAULT_W06_ARTIFACT = DEFAULT_W06_SOURCE
_ADAPTER_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w06.py")
_CONFIG = _PublicOracleAdapterConfig(
    world_slot="W06",
    world_factory=World06,
    committed_source=DEFAULT_W06_SOURCE,
    generator_seed=92006,
    episode_index=13,
    oracle_seed=3006,
    reference_tolerance=1e-10,
    source_class_name="World06",
    adapter_source=_ADAPTER_SOURCE,
)


def run_w06_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W06_SOURCE,
    generator_seed: int = _CONFIG.generator_seed,
    episode_index: int = _CONFIG.episode_index,
    oracle_seed: int = _CONFIG.oracle_seed,
) -> dict[str, Any]:
    result = _collect_public_oracle_upper_bound(
        _CONFIG,
        source_artifact=source_artifact,
        generator_seed=generator_seed,
        episode_index=episode_index,
        oracle_seed=oracle_seed,
    )
    verify_w06_upper_bound_sanity(
        result, source_artifact=source_artifact, replay_runtime=True
    )
    return result


def verify_w06_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    _verify_public_oracle_upper_bound(
        value,
        _CONFIG,
        source_artifact=source_artifact,
        replay_runtime=replay_runtime,
    )


def w06_upper_bound_artifact_bytes(**kwargs: Any) -> bytes:
    return canonical_json_bytes(run_w06_upper_bound_sanity(**kwargs))


__all__ = [
    "DEFAULT_W06_ARTIFACT",
    "DEFAULT_W06_SOURCE",
    "run_w06_upper_bound_sanity",
    "verify_w06_upper_bound_sanity",
    "w06_upper_bound_artifact_bytes",
]


_register_loaded_evaluator_source(_ADAPTER_SOURCE, __file__)
