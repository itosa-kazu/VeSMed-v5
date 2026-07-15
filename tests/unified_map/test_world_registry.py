from __future__ import annotations

from dataclasses import replace
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
    panels = {
        (slot, panel.panel_id)
        for slot, declaration in WORLD_REGISTRY.items()
        for panel in declaration.panels
    }
    for interface in (
        "pre_split_family_authority",
        "dual_channel_stratum_authority",
    ):
        assert {
            (blocker.world_slot, blocker.panel_id)
            for blocker in report.blockers
            if blocker.interface == interface
        } == panels
    extension_expected = {
        "extension_query_contract",
        "extension_execution_isolation",
        "extension_initialization_provenance",
        "extension_source_hiding",
        "extension_atomic_publish",
    }
    extension_blockers = tuple(
        blocker
        for blocker in report.blockers
        if blocker.interface in extension_expected
    )
    assert {blocker.world_slot for blocker in extension_blockers} == {"W16", "W17"}
    assert {blocker.interface for blocker in extension_blockers} == extension_expected
    assert len(extension_blockers) == 10
    assert len(report.blockers) == 2 * len(panels) + len(extension_blockers)
    with pytest.raises(ProtocolViolation, match="must remain INCOMPLETE"):
        replace(report, status=ReadinessStatus.READY)
    with pytest.raises(ProtocolViolation, match="requires an incomplete blocker"):
        replace(report, blockers=())
    object.__setattr__(report, "status", ReadinessStatus.READY)
    object.__setattr__(report, "blockers", ())
    assert report.to_wire()["status"] == "incomplete"


@pytest.mark.parametrize(
    ("world_slot", "split"),
    (
        ("W01", WorldSplit.TRAIN),
        ("W10", WorldSplit.SEALED_TEST),
        ("W18", WorldSplit.SEALED_TEST),
        ("W19", WorldSplit.SEALED_TEST),
    ),
)
def test_full_legacy_materialization_cannot_claim_family_or_stratum_authority(
    tmp_path: Path,
    world_slot: str,
    split: WorldSplit,
) -> None:
    result = materialize_world_split(
        world_slot,
        "primary",
        split,
        771001,
        tmp_path / world_slot.lower(),
        alias_secret=(world_slot.encode("ascii") * 16)[:32],
    )

    assert result.population_count == DEFAULT_SPLIT_SIZES[split]
    assert result.status is MaterializationStatus.INCOMPLETE
    assert {blocker.interface for blocker in result.blockers} == {
        "pre_split_family_authority",
        "dual_channel_stratum_authority",
    }
    assert result.to_wire()["status"] == "incomplete"


def test_singleton_probe_labels_remain_unverified_without_pair_authority(
    tmp_path: Path,
) -> None:
    result = materialize_world_split(
        "W18",
        "primary",
        WorldSplit.SEALED_TEST,
        771018,
        tmp_path / "w18-singleton",
        alias_secret=b"s" * 32,
        episode_limit=0,
        probe_limit=1,
    )
    private = [
        json.loads(line)
        for line in result.judge_path.read_text("utf-8").splitlines()
    ]

    assert len(private) == 1
    row = private[0]
    assert row["probe_id"] == "attributable-ood-fixture"
    assert row["population_denominator"] is False
    assert row["probe_denominator"] is True
    assert row["pair_id"] is None
    assert row["pair_side"] is None
    assert row["strata"] == []
    assert set(row["unverified_declared_strata"]) == {
        "iid_support",
        "boundary_tail",
        "mechanism_ood",
        "behavior_pair",
    }


def test_unverified_probe_classifier_runtime_failure_is_not_hidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = WORLD_REGISTRY["W18"].panels[0]
    world_type = type(panel.instantiate())

    def broken_classifier(self: object, episode: object) -> tuple[str, ...]:
        del self, episode
        raise RuntimeError("classifier implementation failed")

    monkeypatch.setattr(world_type, "strata_for_episode", broken_classifier)
    with pytest.raises(RuntimeError, match="classifier implementation failed"):
        materialize_world_split(
            "W18",
            "primary",
            WorldSplit.SEALED_TEST,
            771019,
            tmp_path / "w18-broken-classifier",
            alias_secret=b"f" * 32,
            episode_limit=0,
            probe_limit=1,
        )


@pytest.mark.parametrize(
    ("reported", "message"),
    (
        ((), "returned no labels"),
        (("iid_support", "iid_support"), "duplicate labels"),
        (("not_declared",), "undeclared label"),
        (["iid_support"], "must return tuple"),
    ),
)
def test_unverified_probe_classifier_malformed_result_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reported: object,
    message: str,
) -> None:
    panel = WORLD_REGISTRY["W18"].panels[0]
    world_type = type(panel.instantiate())

    def malformed_classifier(self: object, episode: object) -> object:
        del self, episode
        return reported

    monkeypatch.setattr(world_type, "strata_for_episode", malformed_classifier)
    with pytest.raises(ProtocolViolation, match=message):
        materialize_world_split(
            "W18",
            "primary",
            WorldSplit.SEALED_TEST,
            771020,
            tmp_path / f"w18-malformed-{message.replace(' ', '-')}",
            alias_secret=b"m" * 32,
            episode_limit=0,
            probe_limit=1,
        )


def test_legacy_materialization_cannot_clear_blockers_or_forge_wire_status(
    tmp_path: Path,
) -> None:
    incomplete = materialize_world_split(
        "W01",
        "primary",
        WorldSplit.TRAIN,
        771099,
        tmp_path / "enum-status",
        alias_secret=b"e" * 32,
        episode_limit=0,
    )
    with pytest.raises(ProtocolViolation, match="must remain INCOMPLETE"):
        replace(
            incomplete,
            status=MaterializationStatus.COMPLETE,
            blockers=(),
        )
    with pytest.raises(ProtocolViolation, match="requires an incomplete blocker"):
        replace(incomplete, blockers=())
    originals = tuple(
        (member, member._value_)
        for member in (
            MaterializationStatus.INCOMPLETE,
            MaterializationStatus.COMPLETE,
        )
    )
    try:
        object.__setattr__(MaterializationStatus.INCOMPLETE, "_value_", "complete")
        object.__setattr__(MaterializationStatus.COMPLETE, "_value_", "incomplete")
        object.__setattr__(incomplete, "status", MaterializationStatus.COMPLETE)
        object.__setattr__(incomplete, "blockers", ())
        assert incomplete.to_wire()["status"] == "incomplete"
    finally:
        for member, original in originals:
            object.__setattr__(member, "_value_", original)


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
    assert all(row["pair_side"] is None for row in private[2:])
    assert all(row["pair_id"] is None for row in private[2:])


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
