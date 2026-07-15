from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.world_registry import materialize_world_split
from prototype.unified_map.worlds.base import PrivateEpisode, WorldSplit
from prototype.unified_map.worlds.w09 import World09


def _flatten_probe_episodes(
    fixtures: dict[str, tuple[PrivateEpisode, PrivateEpisode]],
) -> tuple[PrivateEpisode, ...]:
    return tuple(episode for pair in fixtures.values() for episode in pair)


def test_w09_probe_fixtures_are_sealed_and_do_not_reuse_train_index_zero() -> None:
    world = World09()
    seed = 909

    train_index_zero = world.generate_episode(WorldSplit.TRAIN, seed, 0)
    probe_episodes = _flatten_probe_episodes(world.probe_fixtures(seed))

    assert probe_episodes
    assert all(episode.split is WorldSplit.SEALED_TEST for episode in probe_episodes)
    train_history = canonical_json_bytes(train_index_zero.public_history.to_wire())
    assert all(
        canonical_json_bytes(episode.public_history.to_wire()) != train_history
        for episode in probe_episodes
    )


def test_materializer_rejects_legacy_train_derived_w09_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def legacy_train_probe(
        self: World09, generator_seed: int = 909
    ) -> dict[str, tuple[PrivateEpisode, PrivateEpisode]]:
        episode = self.generate_episode(WorldSplit.TRAIN, generator_seed, 0)
        return {
            "legacy_train_derived": (
                episode,
                replace(episode, case_key="w09-private-legacy-train-copy"),
            )
        }

    monkeypatch.setattr(World09, "probe_fixtures", legacy_train_probe)

    with pytest.raises(
        ProtocolViolation,
        match="probe episode contradicts requested world/split",
    ):
        materialize_world_split(
            "W09",
            "primary",
            WorldSplit.SEALED_TEST,
            909,
            tmp_path / "legacy-train-probe",
            alias_secret=b"w09-split-guard" * 3,
            episode_limit=0,
            probe_limit=1,
        )


def test_materializer_rejects_probe_from_wrong_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def wrong_environment_probe(
        self: World09, generator_seed: int = 909
    ) -> dict[str, tuple[PrivateEpisode, PrivateEpisode]]:
        episode = self.generate_episode(WorldSplit.SEALED_TEST, generator_seed, 0)
        forged = replace(
            episode,
            case_key="w09-private-wrong-environment",
            environment_key="ucm-benchmark-private-forged-environment-v1",
        )
        return {"wrong_environment": (forged, forged)}

    monkeypatch.setattr(World09, "probe_fixtures", wrong_environment_probe)

    with pytest.raises(
        ProtocolViolation,
        match="probe episode contradicts requested world/split",
    ):
        materialize_world_split(
            "W09",
            "primary",
            WorldSplit.SEALED_TEST,
            909,
            tmp_path / "wrong-environment-probe",
            alias_secret=b"w09-environment-guard" * 2,
            episode_limit=0,
            probe_limit=1,
        )
