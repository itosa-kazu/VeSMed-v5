"""Frozen-shape registry and corpus materializer for UCM microworlds.

This module is deliberately a *judge-side* adapter.  A registry slot is not
sent to a candidate and neither is the linkage between an opaque public row
and its private episode.  The adapter can materialize the currently executable
worlds, but it refuses to call the benchmark freeze-ready while a world lacks
an independently implemented reference oracle or an explicit stratum
classifier.

The central registry contains exactly the twenty semantic world slots.  W15 is
one slot with two separately scored panels; treating W15B as an ordinary
point-identified add-on to W15A would invalidate the benchmark semantics.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    reject_privileged_keys,
)
from .schema import PRIVILEGED_FIELD_NAMES
from .worlds.base import MicroWorld, PrivateEpisode, WorldSplit


DEFAULT_SPLIT_SIZES: Mapping[WorldSplit, int] = MappingProxyType(
    {
        WorldSplit.TRAIN: 4096,
        WorldSplit.VALIDATION: 1024,
        WorldSplit.SEALED_TEST: 2048,
    }
)


class ReadinessStatus(str, Enum):
    READY = "ready"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class HarnessBlocker:
    code: str
    world_slot: str
    panel_id: str
    interface: str
    detail: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "interface": self.interface,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ProbeDeclaration:
    """One judge-only probe producer declared before candidate execution.

    ``indexed_count`` is used for a fixed cohort such as W19's 256 tail/common
    pairs.  ``mapping_result`` is used by W06--W10, whose one method returns a
    named mapping of pair fixtures.
    """

    probe_id: str
    method_name: str
    indexed_count: int = 1
    mapping_result: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.probe_id, "probe_id"),
            (self.method_name, "method_name"),
        ):
            if type(value) is not str or not value or value.strip() != value:
                raise ProtocolViolation(f"{label} must be a canonical string")
        if type(self.indexed_count) is not int or self.indexed_count <= 0:
            raise ProtocolViolation("indexed_count must be positive")
        if type(self.mapping_result) is not bool:
            raise ProtocolViolation("mapping_result must be boolean")


@dataclass(frozen=True, slots=True)
class PanelDeclaration:
    panel_id: str
    module_name: str
    class_name: str
    strata: tuple[str, ...]
    probes: tuple[ProbeDeclaration, ...]
    split_sizes: tuple[tuple[WorldSplit, int], ...] = tuple(DEFAULT_SPLIT_SIZES.items())
    identification: str = "point"

    def __post_init__(self) -> None:
        for value, label in (
            (self.panel_id, "panel_id"),
            (self.module_name, "module_name"),
            (self.class_name, "class_name"),
        ):
            if type(value) is not str or not value or value.strip() != value:
                raise ProtocolViolation(f"{label} must be a canonical string")
        if type(self.strata) is not tuple or not self.strata:
            raise ProtocolViolation("panel strata must be a non-empty tuple")
        if self.strata[0] != "iid_support" or len(set(self.strata)) != len(self.strata):
            raise ProtocolViolation("strata must start with unique iid_support")
        if type(self.probes) is not tuple or any(
            type(item) is not ProbeDeclaration for item in self.probes
        ):
            raise ProtocolViolation("probes must be ProbeDeclaration values")
        sizes = dict(self.split_sizes)
        if set(sizes) != set(WorldSplit):
            raise ProtocolViolation("split_sizes must declare every WorldSplit")
        if any(type(value) is not int or value <= 0 for value in sizes.values()):
            raise ProtocolViolation("split sizes must be positive integers")
        if self.identification not in {"point", "partial", "none"}:
            raise ProtocolViolation("unknown identification kind")

    def instantiate(self) -> MicroWorld:
        module = importlib.import_module(self.module_name)
        world_type = getattr(module, self.class_name, None)
        if not isinstance(world_type, type) or not issubclass(world_type, MicroWorld):
            raise ProtocolViolation(
                f"{self.module_name}.{self.class_name} is not a MicroWorld"
            )
        world = world_type()
        if not isinstance(world, MicroWorld):
            raise ProtocolViolation("world factory returned the wrong type")
        return world

    def episode_count(self, split: WorldSplit, world: MicroWorld | None = None) -> int:
        if type(split) is not WorldSplit:
            raise ProtocolViolation("split must be WorldSplit")
        declared = dict(self.split_sizes)[split]
        if world is not None and hasattr(world, "population_size"):
            actual = getattr(world, "population_size")(split)
            if type(actual) is not int or actual <= 0:
                raise ProtocolViolation("world population_size returned an invalid count")
            if actual != declared:
                raise ProtocolViolation(
                    f"world population_size={actual} contradicts registry={declared}"
                )
        return declared

    def to_wire(self) -> dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "module_name": self.module_name,
            "class_name": self.class_name,
            "identification": self.identification,
            "split_sizes": {
                split.value: count for split, count in self.split_sizes
            },
            "strata": list(self.strata),
            "probes": [
                {
                    "probe_id": probe.probe_id,
                    "method_name": probe.method_name,
                    "indexed_count": probe.indexed_count,
                    "mapping_result": probe.mapping_result,
                }
                for probe in self.probes
            ],
        }


@dataclass(frozen=True, slots=True)
class WorldDeclaration:
    world_slot: str
    panels: tuple[PanelDeclaration, ...]

    def __post_init__(self) -> None:
        if (
            type(self.world_slot) is not str
            or len(self.world_slot) != 3
            or not self.world_slot.startswith("W")
            or not self.world_slot[1:].isdigit()
        ):
            raise ProtocolViolation("world_slot must have form W01")
        if type(self.panels) is not tuple or not self.panels:
            raise ProtocolViolation("world must declare at least one panel")
        panel_ids = [panel.panel_id for panel in self.panels]
        if len(panel_ids) != len(set(panel_ids)):
            raise ProtocolViolation("panel ids must be unique within a world")

    def to_wire(self) -> dict[str, Any]:
        return {
            "world_slot": self.world_slot,
            "panels": [panel.to_wire() for panel in self.panels],
        }


def _panel(
    slot: int,
    class_name: str,
    *,
    panel_id: str = "primary",
    strata: Iterable[str] = ("iid_support", "boundary_tail"),
    probes: Iterable[ProbeDeclaration] = (),
    identification: str = "point",
) -> PanelDeclaration:
    return PanelDeclaration(
        panel_id=panel_id,
        module_name=f"prototype.unified_map.worlds.w{slot:02d}",
        class_name=class_name,
        strata=tuple(strata),
        probes=tuple(probes),
        identification=identification,
    )


def _probe(name: str, *, count: int = 1, mapping: bool = False) -> ProbeDeclaration:
    return ProbeDeclaration(name.replace("_", "-"), name, count, mapping)


_DECLARATIONS = (
    WorldDeclaration("W01", (_panel(1, "W01World", probes=(_probe("collision_fixture"), _probe("false_split_fixture"))),)),
    WorldDeclaration("W02", (_panel(2, "W02World", probes=(_probe("collision_fixture"), _probe("false_split_fixture"), _probe("future_leak_fixture"))),)),
    WorldDeclaration("W03", (_panel(3, "W03World", strata=("iid_support", "boundary_tail", "behavior_pair"), probes=(_probe("collision_fixture"), _probe("false_split_fixture"))),)),
    WorldDeclaration("W04", (_panel(4, "W04World", strata=("iid_support", "boundary_tail", "policy_coverage_holdout", "behavior_pair"), probes=(_probe("collision_fixture"), _probe("false_split_fixture"), _probe("irreducible_fixture"))),)),
    WorldDeclaration("W05", (_panel(5, "W05World", strata=("iid_support", "boundary_tail", "policy_coverage_holdout"), probes=(_probe("collision_fixture"), _probe("false_split_fixture"), _probe("future_leak_fixture"))),)),
    WorldDeclaration("W06", (_panel(6, "World06", strata=("iid_support", "boundary_tail", "policy_coverage_holdout"), probes=(_probe("probe_fixtures", mapping=True),)),)),
    WorldDeclaration("W07", (_panel(7, "World07", strata=("iid_support", "boundary_tail", "policy_coverage_holdout"), probes=(_probe("probe_fixtures", mapping=True),)),)),
    WorldDeclaration("W08", (_panel(8, "World08", strata=("iid_support", "boundary_tail", "schedule_time_holdout"), probes=(_probe("probe_fixtures", mapping=True),)),)),
    WorldDeclaration("W09", (_panel(9, "World09", probes=(_probe("probe_fixtures", mapping=True),)),)),
    WorldDeclaration("W10", (_panel(10, "World10", strata=("iid_support", "boundary_tail", "compositional_holdout"), probes=(_probe("probe_fixtures", mapping=True),)),)),
    WorldDeclaration("W11", (_panel(11, "World11", strata=("iid_support", "boundary_tail", "behavior_pair"), probes=(_probe("distinguishable_fixture"), _probe("equivalent_fixture"))),)),
    WorldDeclaration("W12", (_panel(12, "World12", strata=("iid_support", "boundary_tail", "compositional_holdout"), probes=(_probe("distinguishable_fixture"), _probe("same_mechanism_fixture"), _probe("equivalent_fixture"))),)),
    WorldDeclaration("W13", (_panel(13, "World13", strata=("iid_support", "boundary_tail", "compositional_holdout"), probes=(_probe("distinguishable_fixture"), _probe("threshold_fixture"), _probe("equivalent_fixture"))),)),
    WorldDeclaration("W14", (_panel(14, "World14", strata=("iid_support", "boundary_tail", "schedule_time_holdout", "behavior_pair"), probes=(_probe("distinguishable_fixture"), _probe("equivalent_fixture"), _probe("alpha_equivalent_fixture"))),)),
    WorldDeclaration(
        "W15",
        (
            _panel(
                15,
                "World15A",
                panel_id="W15A-randomized-identifiable",
                strata=("iid_support", "boundary_tail", "policy_coverage_holdout", "behavior_pair"),
                probes=(_probe("distinguishable_fixture"), _probe("equivalent_fixture")),
                identification="point",
            ),
            _panel(
                15,
                "World15B",
                panel_id="W15B-observational-nonidentified",
                strata=("iid_support", "boundary_tail", "policy_coverage_holdout", "behavior_pair"),
                probes=(_probe("nonidentified_twin_fixture"), _probe("equivalent_fixture")),
                identification="none",
            ),
        ),
    ),
    WorldDeclaration("W16", (_panel(16, "W16World", strata=("iid_support", "boundary_tail", "extension_check", "behavior_pair"), probes=(_probe("pre_result_alias_pair"), _probe("extension_result_pair"))),)),
    WorldDeclaration("W17", (_panel(17, "W17World", strata=("iid_support", "boundary_tail", "extension_treatment", "behavior_pair"), probes=(_probe("extension_split_pair"),)),)),
    WorldDeclaration("W18", (_panel(18, "W18World", strata=("iid_support", "boundary_tail", "mechanism_ood", "behavior_pair"), probes=(_probe("attributable_ood_fixture"), _probe("irreducible_alias_pair"), _probe("known_extreme_fixture"))),)),
    WorldDeclaration("W19", (_panel(19, "W19World", strata=("iid_support", "boundary_tail", "policy_coverage_holdout", "behavior_pair"), probes=(_probe("tail_probe_pair", count=256), _probe("unidentified_tail_alias_pair"))),)),
    WorldDeclaration("W20", (_panel(20, "W20World", strata=("iid_support", "boundary_tail", "compositional_holdout", "schedule_time_holdout", "policy_coverage_holdout", "behavior_pair"), probes=(_probe("exposure_collision_pair"), _probe("sufficient_statistic_false_split_pair"))),)),
)


WORLD_REGISTRY: Mapping[str, WorldDeclaration] = MappingProxyType(
    {declaration.world_slot: declaration for declaration in _DECLARATIONS}
)
if tuple(WORLD_REGISTRY) != tuple(f"W{index:02d}" for index in range(1, 21)):
    raise RuntimeError("UCM world registry must contain exactly ordered W01--W20")


@dataclass(frozen=True, slots=True)
class RegistryReadiness:
    status: ReadinessStatus
    blockers: tuple[HarnessBlocker, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-world-registry-readiness/1",
            "status": self.status.value,
            "blockers": [blocker.to_wire() for blocker in self.blockers],
        }


def audit_registry_readiness() -> RegistryReadiness:
    """Audit freeze-critical interfaces without treating adapters as proof.

    The current executable worlds intentionally remain usable through the
    generic ``MicroWorld`` API.  That API, however, cannot prove that a
    production oracle and its reference implementation are independent, nor
    can it prove exact stratum membership.  Missing evidence is therefore an
    ``INCOMPLETE`` result, never a synthetic pass.
    """

    blockers: list[HarnessBlocker] = []
    for slot, declaration in WORLD_REGISTRY.items():
        for panel in declaration.panels:
            try:
                world = panel.instantiate()
            except Exception as exc:  # a broken factory is evidence, not a crash-only PASS
                blockers.append(
                    HarnessBlocker(
                        "UCM-E003-HARNESS_INCOMPLETE",
                        slot,
                        panel.panel_id,
                        "world_factory",
                        f"cannot instantiate declared world: {type(exc).__name__}: {exc}",
                    )
                )
                continue
            for interface, detail in (
                (
                    "reference_counterfactual",
                    "independent reference oracle is not implemented",
                ),
                (
                    "strata_for_episode",
                    "exact split-stratum membership interface is not implemented",
                ),
            ):
                if not callable(getattr(world, interface, None)):
                    blockers.append(
                        HarnessBlocker(
                            "UCM-E003-HARNESS_INCOMPLETE",
                            slot,
                            panel.panel_id,
                            interface,
                            detail,
                        )
                    )
            for probe in panel.probes:
                if not callable(getattr(world, probe.method_name, None)):
                    blockers.append(
                        HarnessBlocker(
                            "UCM-E003-HARNESS_INCOMPLETE",
                            slot,
                            panel.panel_id,
                            probe.method_name,
                            "declared probe producer is missing",
                        )
                    )
    return RegistryReadiness(
        ReadinessStatus.INCOMPLETE if blockers else ReadinessStatus.READY,
        tuple(blockers),
    )


class MaterializationStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    status: MaterializationStatus
    world_slot: str
    panel_id: str
    split: str
    population_count: int
    probe_record_count: int
    candidate_path: Path
    judge_path: Path
    candidate_digest: str
    judge_digest: str
    blockers: tuple[HarnessBlocker, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-materialization-result/1",
            "status": self.status.value,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "split": self.split,
            "population_count": self.population_count,
            "probe_record_count": self.probe_record_count,
            "candidate_file": self.candidate_path.name,
            "judge_file": self.judge_path.name,
            "candidate_digest": self.candidate_digest,
            "judge_digest": self.judge_digest,
            "blockers": [blocker.to_wire() for blocker in self.blockers],
        }


class _ExclusiveJsonl:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = path.open("xb")
        self.count = 0

    def append(self, row: dict[str, Any]) -> None:
        self._handle.write(canonical_json_bytes(row))
        self.count += 1

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()

    def __enter__(self) -> "_ExclusiveJsonl":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


def _opaque_alias(
    secret: bytes,
    *,
    slot: str,
    panel: str,
    split: WorldSplit,
    cohort: str,
    ordinal: int,
) -> str:
    message = canonical_json_bytes(
        {
            "cohort": cohort,
            "ordinal": ordinal,
            "panel": panel,
            "slot": slot,
            "split": split.value,
        }
    )
    return "r-" + hmac.new(secret, b"UCM-ROW-ALIAS-v1\0" + message, hashlib.sha256).hexdigest()


def _candidate_row(record_id: str, world: MicroWorld, episode: PrivateEpisode) -> dict[str, Any]:
    row = {
        "schema_version": "ucm-candidate-public-episode/1",
        "record_id": record_id,
        "catalog": world.catalog.to_wire(),
        "public_history": episode.public_history.to_wire(),
    }
    reject_privileged_keys(
        row,
        forbidden=PRIVILEGED_FIELD_NAMES,
        path="$.candidate_public",
    )
    return row


def _judge_row(
    record_id: str,
    *,
    slot: str,
    panel: PanelDeclaration,
    split: WorldSplit,
    episode: PrivateEpisode,
    cohort: str,
    ordinal: int | None,
    probe_id: str | None,
    pair_id: str | None,
    pair_side: int | None,
    strata: tuple[str, ...],
    unverified_strata: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": "ucm-judge-private-episode/1",
        "record_id": record_id,
        "world_slot": slot,
        "panel_id": panel.panel_id,
        "split": split.value,
        "cohort": cohort,
        "population_denominator": cohort == "population",
        "probe_denominator": cohort == "probe",
        "population_ordinal": ordinal,
        "probe_id": probe_id,
        "pair_id": pair_id,
        "pair_side": pair_side,
        "strata": list(strata),
        "unverified_declared_strata": list(unverified_strata),
        "case_key": episode.case_key,
        "environment_key": episode.environment_key,
        "generator_seed": episode.generator_seed,
        "public_history_digest": episode.public_history.digest,
        "hidden_state_at_cut": episode.hidden_state_at_cut,
        "invariant_parameters": episode.invariant_parameters,
        "diagnostic_target": episode.diagnostic_target,
        "factual_future": episode.factual_future,
        "action_propensities": episode.action_propensities,
        "factual_utility": episode.factual_utility,
        "oracle_anchor": episode.oracle_anchor,
        "identification": panel.identification,
    }


def _strata_for_episode(
    world: MicroWorld,
    panel: PanelDeclaration,
    episode: PrivateEpisode,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    classifier = getattr(world, "strata_for_episode", None)
    if not callable(classifier):
        return ("iid_support",), tuple(
            stratum for stratum in panel.strata if stratum != "iid_support"
        )
    value = classifier(episode)
    if type(value) is not tuple or any(type(item) is not str for item in value):
        raise ProtocolViolation("strata_for_episode must return tuple[str, ...]")
    if "iid_support" not in value:
        raise ProtocolViolation("every population episode must be in iid_support")
    unknown = set(value) - set(panel.strata)
    if unknown:
        raise ProtocolViolation(f"world returned undeclared strata: {sorted(unknown)!r}")
    return value, ()


def _flatten_probe_result(
    result: object,
    *,
    declaration: ProbeDeclaration,
) -> list[tuple[str, tuple[PrivateEpisode, ...]]]:
    if declaration.mapping_result:
        if type(result) is not dict:
            raise ProtocolViolation("mapping probe producer must return an exact dict")
        flattened = []
        for key in sorted(result):
            value = result[key]
            if type(key) is not str or type(value) is not tuple:
                raise ProtocolViolation("probe mapping must be str -> tuple")
            if not value or any(type(item) is not PrivateEpisode for item in value):
                raise ProtocolViolation("probe mapping contains a non-episode")
            flattened.append((f"{declaration.probe_id}:{key}", value))
        return flattened
    if type(result) is PrivateEpisode:
        return [(declaration.probe_id, (result,))]
    if type(result) is tuple and result and all(
        type(item) is PrivateEpisode for item in result
    ):
        return [(declaration.probe_id, result)]
    raise ProtocolViolation("probe producer must return episode, tuple, or declared mapping")


def materialize_world_split(
    world_slot: str,
    panel_id: str,
    split: WorldSplit,
    generator_seed: int,
    output_dir: Path,
    *,
    alias_secret: bytes,
    episode_limit: int | None = None,
    probe_limit: int | None = None,
) -> MaterializationResult:
    """Materialize separate public/private append-only JSONL streams.

    Limits are test/development conveniences.  Using either limit below the
    frozen declaration leaves a typed ``INCOMPLETE`` blocker in the result; a
    truncated corpus can therefore never masquerade as a full split.
    """

    if world_slot not in WORLD_REGISTRY:
        raise ProtocolViolation("unknown world slot")
    if type(panel_id) is not str:
        raise ProtocolViolation("panel_id must be a string")
    if type(split) is not WorldSplit:
        raise ProtocolViolation("split must be WorldSplit")
    if type(generator_seed) is not int or generator_seed < 0 or generator_seed >= 2**64:
        raise ProtocolViolation("generator_seed must be uint64")
    if type(alias_secret) is not bytes or len(alias_secret) < 32:
        raise ProtocolViolation("alias_secret must contain at least 256 bits")
    if not isinstance(output_dir, Path):
        raise ProtocolViolation("output_dir must be pathlib.Path")
    if episode_limit is not None and (type(episode_limit) is not int or episode_limit < 0):
        raise ProtocolViolation("episode_limit must be non-negative")
    if probe_limit is not None and (type(probe_limit) is not int or probe_limit < 0):
        raise ProtocolViolation("probe_limit must be non-negative")

    declaration = WORLD_REGISTRY[world_slot]
    panels = {panel.panel_id: panel for panel in declaration.panels}
    if panel_id not in panels:
        raise ProtocolViolation("unknown panel for world")
    panel = panels[panel_id]
    world = panel.instantiate()
    declared_count = panel.episode_count(split, world)
    requested_count = declared_count if episode_limit is None else min(
        episode_limit, declared_count
    )

    output_dir.mkdir(parents=True, exist_ok=False)
    candidate_path = output_dir / "candidate-public.jsonl"
    judge_path = output_dir / "judge-private.jsonl"
    blockers: list[HarnessBlocker] = []
    if requested_count != declared_count:
        blockers.append(
            HarnessBlocker(
                "UCM-E003-HARNESS_INCOMPLETE",
                world_slot,
                panel.panel_id,
                "split_size",
                f"materialized {requested_count} of declared {declared_count} population rows",
            )
        )
    if not callable(getattr(world, "strata_for_episode", None)):
        blockers.append(
            HarnessBlocker(
                "UCM-E003-HARNESS_INCOMPLETE",
                world_slot,
                panel.panel_id,
                "strata_for_episode",
                "non-IID stratum membership remains unverified",
            )
        )

    probe_written = 0
    with _ExclusiveJsonl(candidate_path) as public_writer, _ExclusiveJsonl(
        judge_path
    ) as judge_writer:
        for index in range(requested_count):
            episode = world.generate_episode(split, generator_seed, index)
            if type(episode) is not PrivateEpisode:
                raise ProtocolViolation("generate_episode returned a non-PrivateEpisode")
            if episode.split is not split or episode.environment_key != world.environment_key:
                raise ProtocolViolation("generated episode contradicts requested world/split")
            strata, unverified = _strata_for_episode(world, panel, episode)
            record_id = _opaque_alias(
                alias_secret,
                slot=world_slot,
                panel=panel.panel_id,
                split=split,
                cohort="population",
                ordinal=index,
            )
            public_writer.append(_candidate_row(record_id, world, episode))
            judge_writer.append(
                _judge_row(
                    record_id,
                    slot=world_slot,
                    panel=panel,
                    split=split,
                    episode=episode,
                    cohort="population",
                    ordinal=index,
                    probe_id=None,
                    pair_id=None,
                    pair_side=None,
                    strata=strata,
                    unverified_strata=unverified,
                )
            )

        if split is WorldSplit.SEALED_TEST:
            remaining = probe_limit
            probe_ordinal = 0
            for probe in panel.probes:
                count = probe.indexed_count
                if remaining is not None:
                    count = min(count, remaining)
                method = getattr(world, probe.method_name, None)
                if not callable(method):
                    blockers.append(
                        HarnessBlocker(
                            "UCM-E003-HARNESS_INCOMPLETE",
                            world_slot,
                            panel.panel_id,
                            probe.method_name,
                            "declared probe producer is missing",
                        )
                    )
                    continue
                for probe_index in range(count):
                    if probe.indexed_count > 1:
                        result = method(generator_seed, probe_index=probe_index)
                    else:
                        result = method(generator_seed)
                    groups = _flatten_probe_result(result, declaration=probe)
                    for local_name, episodes in groups:
                        pair_id = "p-" + hmac.new(
                            alias_secret,
                            b"UCM-PAIR-ALIAS-v1\0"
                            + canonical_json_bytes(
                                {
                                    "panel": panel.panel_id,
                                    "probe": local_name,
                                    "probe_index": probe_index,
                                    "slot": world_slot,
                                }
                            ),
                            hashlib.sha256,
                        ).hexdigest()
                        for side, episode in enumerate(episodes):
                            if type(episode) is not PrivateEpisode:
                                raise ProtocolViolation("probe contains a non-episode")
                            record_id = _opaque_alias(
                                alias_secret,
                                slot=world_slot,
                                panel=panel.panel_id,
                                split=split,
                                cohort="probe",
                                ordinal=probe_ordinal,
                            )
                            public_writer.append(_candidate_row(record_id, world, episode))
                            judge_writer.append(
                                _judge_row(
                                    record_id,
                                    slot=world_slot,
                                    panel=panel,
                                    split=split,
                                    episode=episode,
                                    cohort="probe",
                                    ordinal=None,
                                    probe_id=local_name,
                                    pair_id=pair_id,
                                    pair_side=side,
                                    strata=("behavior_pair",),
                                    unverified_strata=(),
                                )
                            )
                            probe_ordinal += 1
                            probe_written += 1
                if remaining is not None:
                    remaining -= count
                    if remaining <= 0:
                        break
            declared_probe_invocations = sum(
                probe.indexed_count for probe in panel.probes
            )
            if probe_limit is not None and probe_limit < declared_probe_invocations:
                blockers.append(
                    HarnessBlocker(
                        "UCM-E003-HARNESS_INCOMPLETE",
                        world_slot,
                        panel.panel_id,
                        "probe_count",
                        "probe cohort was intentionally truncated",
                    )
                )

    candidate_bytes = candidate_path.read_bytes()
    judge_bytes = judge_path.read_bytes()
    result = MaterializationResult(
        MaterializationStatus.INCOMPLETE if blockers else MaterializationStatus.COMPLETE,
        world_slot,
        panel.panel_id,
        split.value,
        requested_count,
        probe_written,
        candidate_path,
        judge_path,
        digest_bytes(candidate_bytes),
        digest_bytes(judge_bytes),
        tuple(blockers),
    )
    status_path = output_dir / "materialization-status.json"
    with status_path.open("xb") as handle:
        handle.write(canonical_json_bytes(result.to_wire()))
        handle.flush()
        os.fsync(handle.fileno())
    return result


def registry_digest() -> str:
    return digest_json(
        {
            "schema_version": "ucm-world-registry/1",
            "worlds": [WORLD_REGISTRY[slot].to_wire() for slot in WORLD_REGISTRY],
        }
    )


__all__ = [
    "DEFAULT_SPLIT_SIZES",
    "HarnessBlocker",
    "MaterializationResult",
    "MaterializationStatus",
    "PanelDeclaration",
    "ProbeDeclaration",
    "ReadinessStatus",
    "RegistryReadiness",
    "WORLD_REGISTRY",
    "WorldDeclaration",
    "audit_registry_readiness",
    "materialize_world_split",
    "registry_digest",
]
