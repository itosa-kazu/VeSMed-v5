from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.world_registry import (
    DEFAULT_SPLIT_SIZES,
    MaterializationStatus,
    ReadinessStatus,
    WORLD_REGISTRY,
    audit_registry_readiness,
    materialize_world_split,
    registry_digest,
)
from prototype.unified_map.worlds.base import WorldSplit


def _walk_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if type(value) is dict:
        for key, item in value.items():
            keys.add(key)
            keys.update(_walk_keys(item))
    elif type(value) is list:
        for item in value:
            keys.update(_walk_keys(item))
    return keys


def test_registry_is_exactly_ordered_w01_w20_and_w15_panels_are_explicit() -> None:
    assert tuple(WORLD_REGISTRY) == tuple(f"W{index:02d}" for index in range(1, 21))
    assert len(WORLD_REGISTRY) == 20
    assert [panel.panel_id for panel in WORLD_REGISTRY["W15"].panels] == [
        "W15A-randomized-identifiable",
        "W15B-observational-nonidentified",
    ]
    assert [panel.identification for panel in WORLD_REGISTRY["W15"].panels] == [
        "point",
        "none",
    ]
    assert registry_digest().startswith("sha256:")


def test_all_panels_declare_exact_default_population_and_nonempty_probe_contracts() -> None:
    for declaration in WORLD_REGISTRY.values():
        for panel in declaration.panels:
            assert dict(panel.split_sizes) == dict(DEFAULT_SPLIT_SIZES)
            assert panel.strata[0] == "iid_support"
            assert panel.probes
            # Declaration validation must remain inspectable even while a
            # world module is absent/broken; readiness audit reports that as a
            # typed blocker rather than making the registry itself unloadable.
            assert panel.episode_count(WorldSplit.TRAIN) == 4096
            assert panel.episode_count(WorldSplit.VALIDATION) == 1024
            assert panel.episode_count(WorldSplit.SEALED_TEST) == 2048


def test_registry_audit_keeps_two_stage_extension_freeze_evidence_incomplete() -> None:
    report = audit_registry_readiness()
    assert report.status is ReadinessStatus.INCOMPLETE
    assert {blocker.world_slot for blocker in report.blockers} == {"W16", "W17"}
    expected = {
        "extension_query_contract",
        "extension_execution_isolation",
        "extension_initialization_provenance",
        "extension_source_hiding",
        "extension_atomic_publish",
    }
    assert {blocker.interface for blocker in report.blockers} == expected
    assert len(report.blockers) == 10


def test_materializer_physically_separates_public_and_private_rows_and_denominators(
    tmp_path: Path,
) -> None:
    result = materialize_world_split(
        "W19",
        "primary",
        WorldSplit.SEALED_TEST,
        190019,
        tmp_path / "w19",
        alias_secret=b"a" * 32,
        episode_limit=2,
        probe_limit=1,
    )
    assert result.status is MaterializationStatus.INCOMPLETE
    assert result.population_count == 2
    assert result.probe_record_count == 2
    assert any(blocker.interface == "split_size" for blocker in result.blockers)
    assert any(blocker.interface == "probe_count" for blocker in result.blockers)

    public = [json.loads(line) for line in result.candidate_path.read_text("utf-8").splitlines()]
    private = [json.loads(line) for line in result.judge_path.read_text("utf-8").splitlines()]
    assert len(public) == len(private) == 4
    assert [row["record_id"] for row in public] == [row["record_id"] for row in private]
    forbidden = {
        "world_id",
        "world_slot",
        "case_id",
        "case_key",
        "split",
        "generator_seed",
        "environment_key",
        "hidden_state",
        "hidden_state_at_cut",
        "oracle",
        "oracle_anchor",
        "future",
        "factual_future",
        "pair_id",
        "probe_id",
    }
    for row in public:
        assert not (_walk_keys(row) & forbidden)
    assert all(row["population_denominator"] for row in private[:2])
    assert all(not row["probe_denominator"] for row in private[:2])
    assert all(not row["population_denominator"] for row in private[2:])
    assert all(row["probe_denominator"] for row in private[2:])
    assert {row["pair_side"] for row in private[2:]} == {0, 1}
    assert private[2]["pair_id"] == private[3]["pair_id"]


def test_materializer_is_deterministic_but_exclusive_and_never_overwrites(
    tmp_path: Path,
) -> None:
    arguments = dict(
        world_slot="W01",
        panel_id="primary",
        split=WorldSplit.TRAIN,
        generator_seed=101,
        alias_secret=b"z" * 32,
        episode_limit=3,
    )
    first = materialize_world_split(output_dir=tmp_path / "first", **arguments)
    second = materialize_world_split(output_dir=tmp_path / "second", **arguments)
    assert first.candidate_digest == second.candidate_digest
    assert first.judge_digest == second.judge_digest
    with pytest.raises(FileExistsError):
        materialize_world_split(output_dir=tmp_path / "first", **arguments)


def test_materializer_rejects_short_alias_secret_and_unknown_panel(tmp_path: Path) -> None:
    with pytest.raises(ProtocolViolation):
        materialize_world_split(
            "W01",
            "primary",
            WorldSplit.TRAIN,
            1,
            tmp_path / "bad-secret",
            alias_secret=b"short",
            episode_limit=1,
        )
    with pytest.raises(ProtocolViolation):
        materialize_world_split(
            "W15",
            "primary",
            WorldSplit.TRAIN,
            1,
            tmp_path / "bad-panel",
            alias_secret=b"x" * 32,
            episode_limit=1,
        )
