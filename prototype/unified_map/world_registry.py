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
from typing import Any, Callable, Iterable, Mapping, Sequence

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    reject_privileged_keys,
)
from .extensions import (
    ExtensionFirstQueryRequest,
    ExtensionFirstQueryResult,
    ExtensionRunner,
    FirstQueryTranscript,
    MigrationOutcome,
    OpaqueExtensionCustody,
    RevealedExtensionPack,
)
from .schema import PRIVILEGED_FIELD_NAMES, VisibleHistory
from .state import (
    CandidateStateInput,
    HarnessStateRecord,
    SealedState,
    StatePayload,
    compute_state_hash,
)
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
class ExtensionWorldDeclaration:
    """Judge-only construction metadata for a two-stage world.

    The custody factory name is deliberately not included in a candidate row.
    It is registry metadata used to create a fresh randomized hiding commitment
    before any primary candidate artifact or state is sealed.
    """

    world_slot: str
    custody_factory_name: str
    extension_population_count: int = 512
    probe_pair_repetitions: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if self.world_slot not in {"W16", "W17"}:
            raise ProtocolViolation("only W16/W17 are two-stage extension worlds")
        if (
            type(self.custody_factory_name) is not str
            or not self.custody_factory_name
            or self.custody_factory_name.strip() != self.custody_factory_name
        ):
            raise ProtocolViolation("custody_factory_name must be canonical")
        if (
            type(self.extension_population_count) is not int
            or self.extension_population_count <= 0
        ):
            raise ProtocolViolation("extension_population_count must be positive")
        if type(self.probe_pair_repetitions) is not tuple or not self.probe_pair_repetitions:
            raise ProtocolViolation("extension probe allocation must be non-empty")
        names: list[str] = []
        for name, count in self.probe_pair_repetitions:
            if type(name) is not str or not name or name.strip() != name:
                raise ProtocolViolation("extension probe name must be canonical")
            if type(count) is not int or count <= 0:
                raise ProtocolViolation("extension probe repetition must be positive")
            names.append(name)
        if len(names) != len(set(names)):
            raise ProtocolViolation("extension probe allocation names must be unique")
        if self.extension_pair_count != 256:
            raise ProtocolViolation("W16/W17 must freeze exactly 256 extension pairs")

    @property
    def extension_pair_count(self) -> int:
        return sum(count for _, count in self.probe_pair_repetitions)

    def to_wire(self) -> dict[str, Any]:
        # The Python factory name is process configuration, not candidate data.
        return {
            "world_slot": self.world_slot,
            "extension_population_count": self.extension_population_count,
            "extension_pair_count": self.extension_pair_count,
            "probe_pair_repetitions": {
                name: count for name, count in self.probe_pair_repetitions
            },
            "query_contract_verified": False,
            "execution_assurance": "portable-callback",
            "initialization_receipt_provenance_verified": False,
            "source_hiding_verified": False,
            "atomic_publish_verified": False,
            "freeze_grade_status": "incomplete",
        }


EXTENSION_WORLD_REGISTRY: Mapping[str, ExtensionWorldDeclaration] = MappingProxyType(
    {
        "W16": ExtensionWorldDeclaration(
            "W16",
            "make_w16_extension_custody",
            probe_pair_repetitions=(
                ("pre_result_alias_pair", 128),
                ("extension_result_pair", 128),
            ),
        ),
        "W17": ExtensionWorldDeclaration(
            "W17",
            "make_w17_extension_custody",
            probe_pair_repetitions=(("extension_split_pair", 256),),
        ),
    }
)


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
    for slot in EXTENSION_WORLD_REGISTRY:
        try:
            _instantiate_extension_fixture(slot)
        except Exception as exc:
            blockers.append(
                HarnessBlocker(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    slot,
                    WORLD_REGISTRY[slot].panels[0].panel_id,
                    "two_stage_extension_factory",
                    f"cannot construct committed extension fixture: {type(exc).__name__}: {exc}",
                )
            )
            continue
        for interface, detail in (
            (
                "extension_query_contract",
                "exact W16/W17 first-query contract is not registry-owned/frozen",
            ),
            (
                "extension_execution_isolation",
                "portable callback does not prove fresh-process or physical state-only closure",
            ),
            (
                "extension_initialization_provenance",
                "initialize execution receipts remain caller-supplied",
            ),
            (
                "extension_source_hiding",
                "extension literals remain visible in repository source",
            ),
            (
                "extension_atomic_publish",
                "cross-root S1 publish is not an atomic transaction",
            ),
        ):
            blockers.append(
                HarnessBlocker(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    slot,
                    WORLD_REGISTRY[slot].panels[0].panel_id,
                    interface,
                    detail,
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

    def __post_init__(self) -> None:
        if type(self.status) is not MaterializationStatus:
            raise ProtocolViolation("materialization status must be typed")
        if type(self.blockers) is not tuple or any(
            type(blocker) is not HarnessBlocker for blocker in self.blockers
        ):
            raise ProtocolViolation("materialization blockers must be typed")
        expected = (
            MaterializationStatus.INCOMPLETE
            if self.blockers
            else MaterializationStatus.COMPLETE
        )
        if self.status is not expected:
            raise ProtocolViolation(
                "materialization status must be derived from its blocker set"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-materialization-result/1",
            # Never trust a mutable status field when the blocker set is the
            # authoritative fail-closed evidence.
            "status": (
                MaterializationStatus.INCOMPLETE.value
                if self.blockers
                else MaterializationStatus.COMPLETE.value
            ),
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


def _validated_digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} is not hexadecimal") from exc
    return value


@dataclass(frozen=True, slots=True)
class ExtensionPrimaryMaterialization:
    """Append-only S0 corpus and opaque commitment, before candidate sealing."""

    status: MaterializationStatus
    world_slot: str
    panel_id: str
    split: str
    record_count: int
    primary_scope_digest: str
    candidate_path: Path
    candidate_commitment_path: Path
    judge_path: Path
    candidate_digest: str
    candidate_commitment_digest: str
    judge_digest: str
    record_set_digest: str
    blockers: tuple[HarnessBlocker, ...]

    def __post_init__(self) -> None:
        if type(self.status) is not MaterializationStatus:
            raise ProtocolViolation("extension primary status must be typed")
        if self.status is not MaterializationStatus.INCOMPLETE:
            raise ProtocolViolation(
                "S0-only extension primary materialization must remain INCOMPLETE"
            )
        if not self.blockers:
            raise ProtocolViolation(
                "incomplete extension primary materialization requires a blocker"
            )
        if type(self.record_count) is not int or self.record_count < 0:
            raise ProtocolViolation("extension primary record_count is invalid")
        for value, label in (
            (self.primary_scope_digest, "primary_scope_digest"),
            (self.candidate_digest, "candidate_digest"),
            (self.candidate_commitment_digest, "candidate_commitment_digest"),
            (self.judge_digest, "judge_digest"),
            (self.record_set_digest, "record_set_digest"),
        ):
            _validated_digest(value, label)

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-extension-primary-materialization/1",
            # Defense in depth: even low-level mutation of a frozen dataclass
            # must not serialize S0-only evidence as globally complete.
            "status": MaterializationStatus.INCOMPLETE.value,
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "split": self.split,
            "record_count": self.record_count,
            "primary_scope_digest": self.primary_scope_digest,
            "candidate_file": self.candidate_path.name,
            "candidate_commitment_file": self.candidate_commitment_path.name,
            "judge_file": self.judge_path.name,
            "candidate_digest": self.candidate_digest,
            "candidate_commitment_digest": self.candidate_commitment_digest,
            "judge_digest": self.judge_digest,
            "record_set_digest": self.record_set_digest,
            "blockers": [blocker.to_wire() for blocker in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class ExtensionInitializationReceipt:
    """Typed judge receipt for the external initialize execution.

    This is necessary binding evidence, but still not a cryptographic trust
    boundary: the current registry accepts it from its caller and therefore
    reports that provenance as ``HARNESS_INCOMPLETE`` for freeze purposes.
    """

    record_id: str
    state_hash: str
    candidate_bundle_digest: str
    model_digest: str
    catalog_digest: str
    scope_digest: str
    request_digest: str
    response_digest: str
    isolation: str
    worker_pid: int

    def __post_init__(self) -> None:
        if type(self.record_id) is not str or not self.record_id.startswith("r-"):
            raise ProtocolViolation("initialize receipt record_id is not opaque")
        for value, label in (
            (self.state_hash, "state_hash"),
            (self.candidate_bundle_digest, "candidate_bundle_digest"),
            (self.model_digest, "model_digest"),
            (self.catalog_digest, "catalog_digest"),
            (self.scope_digest, "scope_digest"),
            (self.request_digest, "request_digest"),
            (self.response_digest, "response_digest"),
        ):
            _validated_digest(value, label)
        if self.isolation != "fresh-python-process-audit-v1":
            raise ProtocolViolation("initialize receipt is not from a fresh worker")
        if type(self.worker_pid) is not int or self.worker_pid <= 0:
            raise ProtocolViolation("initialize receipt requires a worker pid")

    def to_wire(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "state_hash": self.state_hash,
            "candidate_bundle_digest": self.candidate_bundle_digest,
            "model_digest": self.model_digest,
            "catalog_digest": self.catalog_digest,
            "scope_digest": self.scope_digest,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "isolation": self.isolation,
            "worker_pid": self.worker_pid,
        }


@dataclass(frozen=True, slots=True)
class ExtensionStateBindingReceipt:
    record_id: str
    public_history_digest: str
    state_hash: str
    scope_digest: str
    candidate_bundle_digest: str
    model_digest: str
    catalog_digest: str
    as_of_available_at: int
    payload_hex: str
    payload_digest: str
    payload_codec: str
    payload_schema_version: str
    state_class: str
    initialization_receipt_digest: str
    primary_seal_digest: str

    def __post_init__(self) -> None:
        if type(self.record_id) is not str or not self.record_id.startswith("r-"):
            raise ProtocolViolation("extension binding record_id is not opaque")
        for value, label in (
            (self.public_history_digest, "public_history_digest"),
            (self.state_hash, "state_hash"),
            (self.scope_digest, "scope_digest"),
            (self.candidate_bundle_digest, "candidate_bundle_digest"),
            (self.model_digest, "model_digest"),
            (self.catalog_digest, "catalog_digest"),
            (self.payload_digest, "payload_digest"),
            (self.initialization_receipt_digest, "initialization_receipt_digest"),
            (self.primary_seal_digest, "primary_seal_digest"),
        ):
            _validated_digest(value, label)
        if type(self.as_of_available_at) is not int:
            raise ProtocolViolation("binding as_of_available_at must be an integer")
        for value, label in (
            (self.payload_hex, "payload_hex"),
            (self.payload_codec, "payload_codec"),
            (self.payload_schema_version, "payload_schema_version"),
            (self.state_class, "state_class"),
        ):
            if type(value) is not str or not value:
                raise ProtocolViolation(f"{label} must be non-empty")
        try:
            payload = bytes.fromhex(self.payload_hex)
        except ValueError as exc:
            raise ProtocolViolation("binding payload_hex is invalid") from exc
        if digest_bytes(payload) != self.payload_digest:
            raise ProtocolViolation("binding payload digest mismatch")

    def to_wire(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "public_history_digest": self.public_history_digest,
            "state_hash": self.state_hash,
            "scope_digest": self.scope_digest,
            "candidate_bundle_digest": self.candidate_bundle_digest,
            "model_digest": self.model_digest,
            "catalog_digest": self.catalog_digest,
            "as_of_available_at": self.as_of_available_at,
            "payload_hex": self.payload_hex,
            "payload_digest": self.payload_digest,
            "payload_codec": self.payload_codec,
            "payload_schema_version": self.payload_schema_version,
            "state_class": self.state_class,
            "initialization_receipt_digest": self.initialization_receipt_digest,
            "primary_seal_digest": self.primary_seal_digest,
        }


@dataclass(frozen=True, slots=True)
class ExtensionSealResult:
    status: MaterializationStatus
    structural_status: MaterializationStatus
    world_slot: str
    record_set_digest: str
    binding_set_digest: str | None
    bindings: tuple[ExtensionStateBindingReceipt, ...]
    blockers: tuple[HarnessBlocker, ...]

    def __post_init__(self) -> None:
        if type(self.status) is not MaterializationStatus:
            raise ProtocolViolation("extension seal status must be typed")
        if type(self.structural_status) is not MaterializationStatus:
            raise ProtocolViolation("extension structural seal status must be typed")
        if self.status is not MaterializationStatus.INCOMPLETE:
            raise ProtocolViolation(
                "caller-supplied initialize evidence cannot claim freeze-grade seal COMPLETE"
            )
        _validated_digest(self.record_set_digest, "record_set_digest")
        if self.binding_set_digest is not None:
            _validated_digest(self.binding_set_digest, "binding_set_digest")
        if self.structural_status is MaterializationStatus.COMPLETE:
            if not self.bindings or self.binding_set_digest is None or not self.blockers:
                raise ProtocolViolation("complete extension seal lacks exact bindings")
        elif self.bindings or self.binding_set_digest is not None or not self.blockers:
            raise ProtocolViolation("incomplete extension seal cannot claim bindings")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-extension-primary-seal-result/1",
            "status": MaterializationStatus.INCOMPLETE.value,
            "structural_status": self.structural_status.value,
            "freeze_grade_evidence": False,
            "world_slot": self.world_slot,
            "record_set_digest": self.record_set_digest,
            "binding_set_digest": self.binding_set_digest,
            "bindings": [item.to_wire() for item in self.bindings],
            "blockers": [blocker.to_wire() for blocker in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class ExtensionRevealReceipt:
    world_slot: str
    primary_record_set_digest: str
    primary_binding_set_digest: str
    extension_scope_digest: str
    extension_pack_digest: str
    candidate_reveal_path: Path
    candidate_reveal_digest: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.primary_record_set_digest, "primary_record_set_digest"),
            (self.primary_binding_set_digest, "primary_binding_set_digest"),
            (self.extension_scope_digest, "extension_scope_digest"),
            (self.extension_pack_digest, "extension_pack_digest"),
            (self.candidate_reveal_digest, "candidate_reveal_digest"),
        ):
            _validated_digest(value, label)

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-extension-reveal-receipt/1",
            "world_slot": self.world_slot,
            "primary_record_set_digest": self.primary_record_set_digest,
            "primary_binding_set_digest": self.primary_binding_set_digest,
            "extension_scope_digest": self.extension_scope_digest,
            "extension_pack_digest": self.extension_pack_digest,
            "candidate_reveal_file": self.candidate_reveal_path.name,
            "candidate_reveal_digest": self.candidate_reveal_digest,
            "evidence_scope": "runtime-ordering-only",
            "source_hiding_verified": False,
            "freeze_grade_evidence": False,
        }


@dataclass(frozen=True, slots=True)
class ExtensionPortableQueryEvidence:
    """Non-freeze-grade wrapper around an in-process first-query transcript."""

    status: MaterializationStatus
    record_id: str
    transcript: FirstQueryTranscript
    query_contract_verified: bool = False
    state_only_closure_verified: bool = False
    execution_assurance: str = "portable-callback"

    def __post_init__(self) -> None:
        if self.status is not MaterializationStatus.INCOMPLETE:
            raise ProtocolViolation("portable query evidence must remain INCOMPLETE")
        if type(self.record_id) is not str or not self.record_id.startswith("r-"):
            raise ProtocolViolation("portable query record id is invalid")
        if type(self.transcript) is not FirstQueryTranscript:
            raise ProtocolViolation("portable query requires FirstQueryTranscript")
        if self.query_contract_verified or self.state_only_closure_verified:
            raise ProtocolViolation("portable callback cannot verify query/closure")
        if self.execution_assurance != "portable-callback":
            raise ProtocolViolation("portable query assurance is invalid")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-extension-portable-query-evidence/1",
            "status": MaterializationStatus.INCOMPLETE.value,
            "record_id": self.record_id,
            "request_digest": self.transcript.request_digest,
            "primary_state_hash": self.transcript.primary_state_hash,
            "candidate_outcome_status": self.transcript.status.value,
            "candidate_outcome_verdict": self.transcript.verdict.value,
            "query_contract_verified": False,
            "state_only_closure_verified": False,
            "execution_assurance": "portable-callback",
            "freeze_grade_evidence": False,
        }


@dataclass(frozen=True, slots=True)
class ExtensionMaterializationResult:
    status: MaterializationStatus
    corpus_status: MaterializationStatus
    world_slot: str
    split: str
    population_count: int
    probe_record_count: int
    primary_record_set_digest: str
    primary_binding_set_digest: str | None
    extension_scope_digest: str | None
    extension_pack_digest: str | None
    candidate_path: Path | None
    candidate_manifest_path: Path | None
    judge_path: Path | None
    candidate_digest: str | None
    candidate_manifest_digest: str | None
    judge_digest: str | None
    evidence_scope: str
    ordering_complete: bool
    extension_evaluation_complete: bool
    query_contract_verified: bool
    execution_assurance: str
    blockers: tuple[HarnessBlocker, ...]

    def __post_init__(self) -> None:
        if type(self.status) is not MaterializationStatus:
            raise ProtocolViolation("extension materialization status must be typed")
        if type(self.corpus_status) is not MaterializationStatus:
            raise ProtocolViolation("extension corpus status must be typed")
        _validated_digest(self.primary_record_set_digest, "primary_record_set_digest")
        for value, label in (
            (self.primary_binding_set_digest, "primary_binding_set_digest"),
            (self.extension_scope_digest, "extension_scope_digest"),
            (self.extension_pack_digest, "extension_pack_digest"),
            (self.candidate_digest, "candidate_digest"),
            (self.candidate_manifest_digest, "candidate_manifest_digest"),
            (self.judge_digest, "judge_digest"),
        ):
            if value is not None:
                _validated_digest(value, label)
        if self.evidence_scope != "ordering-and-corpus-only":
            raise ProtocolViolation("unknown extension materialization evidence scope")
        for value, label in (
            (self.ordering_complete, "ordering_complete"),
            (self.extension_evaluation_complete, "extension_evaluation_complete"),
            (self.query_contract_verified, "query_contract_verified"),
        ):
            if type(value) is not bool:
                raise ProtocolViolation(f"{label} must be boolean")
        if self.execution_assurance != "portable-callback":
            raise ProtocolViolation("unsupported extension execution assurance")
        if self.extension_evaluation_complete or self.query_contract_verified:
            raise ProtocolViolation(
                "portable callback materialization cannot claim verified evaluation"
            )
        if self.status is MaterializationStatus.COMPLETE:
            raise ProtocolViolation(
                "ordering/corpus evidence cannot claim extension evaluation COMPLETE"
            )
        if self.corpus_status is MaterializationStatus.COMPLETE:
            required = (
                self.primary_binding_set_digest,
                self.extension_scope_digest,
                self.extension_pack_digest,
                self.candidate_path,
                self.candidate_manifest_path,
                self.judge_path,
                self.candidate_digest,
                self.candidate_manifest_digest,
                self.judge_digest,
            )
            if any(value is None for value in required) or not self.ordering_complete:
                raise ProtocolViolation("complete extension corpus lacks evidence")
        if not self.blockers:
            raise ProtocolViolation("incomplete extension result requires a blocker")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-extension-materialization-result/1",
            "status": MaterializationStatus.INCOMPLETE.value,
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "corpus_status": self.corpus_status.value,
            "world_slot": self.world_slot,
            "split": self.split,
            "population_count": self.population_count,
            "probe_record_count": self.probe_record_count,
            "primary_record_set_digest": self.primary_record_set_digest,
            "primary_binding_set_digest": self.primary_binding_set_digest,
            "extension_scope_digest": self.extension_scope_digest,
            "extension_pack_digest": self.extension_pack_digest,
            "candidate_file": None if self.candidate_path is None else self.candidate_path.name,
            "candidate_manifest_file": (
                None
                if self.candidate_manifest_path is None
                else self.candidate_manifest_path.name
            ),
            "judge_file": None if self.judge_path is None else self.judge_path.name,
            "candidate_digest": self.candidate_digest,
            "candidate_manifest_digest": self.candidate_manifest_digest,
            "judge_digest": self.judge_digest,
            "evidence_scope": self.evidence_scope,
            "ordering_complete": self.ordering_complete,
            "extension_evaluation_complete": False,
            "query_contract_verified": False,
            "execution_assurance": "portable-callback",
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


def _candidate_row(
    record_id: str,
    world: MicroWorld,
    episode: PrivateEpisode,
    *,
    catalog: object | None = None,
    scope_digest: str | None = None,
) -> dict[str, Any]:
    selected_catalog = world.catalog if catalog is None else catalog
    to_wire = getattr(selected_catalog, "to_wire", None)
    digest = getattr(selected_catalog, "digest", None)
    if not callable(to_wire) or type(digest) is not str:
        raise ProtocolViolation("candidate row catalog is invalid")
    if episode.public_history.catalog_digest != digest:
        raise ProtocolViolation("candidate row catalog/history digest mismatch")
    row = {
        "schema_version": "ucm-candidate-public-episode/1",
        "record_id": record_id,
        "catalog": to_wire(),
        "public_history": episode.public_history.to_wire(),
    }
    if scope_digest is not None:
        row["scope_digest"] = _validated_digest(scope_digest, "scope_digest")
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


def _require_physically_separate_roots(candidate_root: Path, judge_root: Path) -> None:
    candidate = candidate_root.resolve(strict=False)
    judge = judge_root.resolve(strict=False)
    if candidate == judge or candidate in judge.parents or judge in candidate.parents:
        raise ProtocolViolation(
            "candidate/public and judge/private roots must be physically disjoint"
        )


def _write_exclusive(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _instantiate_extension_fixture(
    world_slot: str,
) -> tuple[PanelDeclaration, OpaqueExtensionCustody, MicroWorld]:
    specification = EXTENSION_WORLD_REGISTRY.get(world_slot)
    if specification is None:
        raise ProtocolViolation("world is not a registered two-stage extension world")
    declaration = WORLD_REGISTRY[world_slot]
    if len(declaration.panels) != 1:
        raise ProtocolViolation("extension world must have exactly one panel")
    panel = declaration.panels[0]
    if tuple(name for name, _ in specification.probe_pair_repetitions) != tuple(
        probe.method_name for probe in panel.probes
    ):
        raise ProtocolViolation(
            "extension pair allocation does not exactly match declared probes"
        )
    module = importlib.import_module(panel.module_name)
    custody_factory = getattr(module, specification.custody_factory_name, None)
    world_type = getattr(module, panel.class_name, None)
    if not callable(custody_factory):
        raise ProtocolViolation("extension custody factory is missing")
    if not isinstance(world_type, type) or not issubclass(world_type, MicroWorld):
        raise ProtocolViolation("extension world class is invalid")
    custody = custody_factory()
    if type(custody) is not OpaqueExtensionCustody:
        raise ProtocolViolation("extension custody factory returned the wrong type")
    world = world_type(extension_commitment=custody.public.commitment)
    if not isinstance(world, MicroWorld):
        raise ProtocolViolation("extension primary factory returned the wrong type")
    if getattr(world, "extension_commitment", None) != custody.public.commitment:
        raise ProtocolViolation("extension world did not bind the fresh commitment")
    return panel, custody, world


def _extension_probe_seed(
    world_slot: str, generator_seed: int, method_name: str, repetition: int
) -> int:
    material = canonical_json_bytes(
        {
            "protocol": "ucm-extension-probe-seed/1",
            "world_slot": world_slot,
            "generator_seed": generator_seed,
            "method_name": method_name,
            "repetition": repetition,
        }
    )
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


class ExtensionRegistrySession:
    """Judge-owned W16/W17 materialization state machine.

    A session owns the opaque extension custody and therefore must never cross
    into a candidate process.  Candidate-visible artifacts are limited to the
    S0 public rows and the hiding commitment until *all* externally produced
    candidate states are bound to exact S0 records and sealed.  Only then can
    this object open the global pack, issue every first query through
    :class:`ExtensionRunner`'s state-only envelope, and finally expose the
    independent S1 patient corpus for explicit migration/retraining.
    """

    def __init__(
        self,
        *,
        world_slot: str,
        split: WorldSplit,
        generator_seed: int,
        alias_secret: bytes,
        primary_scope_digest: str,
        candidate_output_root: Path,
        judge_output_root: Path,
        episode_limit: int | None = None,
    ) -> None:
        if world_slot not in EXTENSION_WORLD_REGISTRY:
            raise ProtocolViolation("only W16/W17 use ExtensionRegistrySession")
        if type(split) is not WorldSplit:
            raise ProtocolViolation("split must be WorldSplit")
        if type(generator_seed) is not int or not 0 <= generator_seed < 2**64:
            raise ProtocolViolation("generator_seed must be uint64")
        if type(alias_secret) is not bytes or len(alias_secret) < 32:
            raise ProtocolViolation("alias_secret must contain at least 256 bits")
        self._primary_scope_digest = _validated_digest(
            primary_scope_digest, "primary_scope_digest"
        )
        if not isinstance(candidate_output_root, Path) or not isinstance(
            judge_output_root, Path
        ):
            raise ProtocolViolation("extension output roots must be pathlib.Path")
        _require_physically_separate_roots(candidate_output_root, judge_output_root)
        if episode_limit is not None and (
            type(episode_limit) is not int or episode_limit < 0
        ):
            raise ProtocolViolation("episode_limit must be non-negative")

        panel, custody, world = _instantiate_extension_fixture(world_slot)
        declared_count = panel.episode_count(split, world)
        requested_count = (
            declared_count
            if episode_limit is None
            else min(episode_limit, declared_count)
        )
        candidate_output_root.mkdir(parents=True, exist_ok=False)
        judge_output_root.mkdir(parents=True, exist_ok=False)
        candidate_path = candidate_output_root / "primary-public.jsonl"
        commitment_path = candidate_output_root / "extension-commitment.json"
        judge_path = judge_output_root / "primary-private.jsonl"

        episodes: dict[str, PrivateEpisode] = {}
        record_rows: list[dict[str, str]] = []
        with _ExclusiveJsonl(candidate_path) as public_writer, _ExclusiveJsonl(
            judge_path
        ) as judge_writer:
            for index in range(requested_count):
                episode = world.generate_episode(split, generator_seed, index)
                if type(episode) is not PrivateEpisode:
                    raise ProtocolViolation(
                        "extension primary generator returned a non-episode"
                    )
                if (
                    episode.split is not split
                    or episode.environment_key != world.environment_key
                ):
                    raise ProtocolViolation(
                        "extension primary episode contradicts requested split"
                    )
                record_id = _opaque_alias(
                    alias_secret,
                    slot=world_slot,
                    panel=panel.panel_id,
                    split=split,
                    cohort="extension-primary",
                    ordinal=index,
                )
                strata, unverified = _strata_for_episode(world, panel, episode)
                public_writer.append(
                    _candidate_row(
                        record_id,
                        world,
                        episode,
                        scope_digest=self._primary_scope_digest,
                    )
                )
                private = _judge_row(
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
                private.update(
                    {
                        "extension_stage": "S0",
                        "record_scope_digest": self._primary_scope_digest,
                        "extension_commitment": custody.public.commitment,
                    }
                )
                judge_writer.append(private)
                episodes[record_id] = episode
                record_rows.append(
                    {
                        "record_id": record_id,
                        "public_history_digest": episode.public_history.digest,
                        "scope_digest": self._primary_scope_digest,
                    }
                )

        commitment_wire = {
            "schema_version": "ucm-extension-candidate-commitment/1",
            "primary_catalog_digest": world.catalog.digest,
            "primary_scope_digest": self._primary_scope_digest,
            "commitment": custody.public.to_wire(),
        }
        commitment_bytes = canonical_json_bytes(commitment_wire)
        candidate_bytes = candidate_path.read_bytes()
        for marker in custody.hiding_markers:
            if marker in candidate_bytes or marker in commitment_bytes:
                raise ProtocolViolation(
                    "clear extension marker reached candidate wire before seal"
                )
        _write_exclusive(commitment_path, commitment_bytes)
        judge_bytes = judge_path.read_bytes()
        record_set_digest = digest_json(record_rows)
        blockers = [
            HarnessBlocker(
                "UCM-E003-HARNESS_INCOMPLETE",
                world_slot,
                panel.panel_id,
                "primary_state_seal",
                "extension reveal is blocked until exact external candidate states are sealed",
            )
        ]
        if requested_count != declared_count:
            blockers.append(
                HarnessBlocker(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    world_slot,
                    panel.panel_id,
                    "split_size",
                    f"materialized {requested_count} of declared {declared_count} primary rows",
                )
            )
        primary = ExtensionPrimaryMaterialization(
            status=MaterializationStatus.INCOMPLETE,
            world_slot=world_slot,
            panel_id=panel.panel_id,
            split=split.value,
            record_count=requested_count,
            primary_scope_digest=self._primary_scope_digest,
            candidate_path=candidate_path,
            candidate_commitment_path=commitment_path,
            judge_path=judge_path,
            candidate_digest=digest_bytes(candidate_bytes),
            candidate_commitment_digest=digest_bytes(commitment_bytes),
            judge_digest=digest_bytes(judge_bytes),
            record_set_digest=record_set_digest,
            blockers=tuple(blockers),
        )
        _write_exclusive(
            judge_output_root / "primary-materialization-status.json",
            canonical_json_bytes(primary.to_wire()),
        )

        self._world_slot = world_slot
        self._split = split
        self._generator_seed = generator_seed
        self._alias_secret = alias_secret
        self._candidate_output_root = candidate_output_root.resolve(strict=True)
        self._judge_output_root = judge_output_root.resolve(strict=True)
        self._panel = panel
        self._custody = custody
        self._primary_world = world
        self._episodes = episodes
        self._primary = primary
        self._seal_result: ExtensionSealResult | None = None
        self._runners: dict[str, ExtensionRunner] = {}
        self._states: dict[str, SealedState] = {}
        self._reveal: RevealedExtensionPack | None = None
        self._reveal_receipt: ExtensionRevealReceipt | None = None
        self._extension_scope_digest: str | None = None
        self._activated_world: MicroWorld | None = None
        self._first_query_record_ids: set[str] = set()
        self._first_query_raw_bytes: dict[str, bytes] = {}
        self._first_query_path = self._judge_output_root / "first-query-private.jsonl"
        self._first_query_handle: Any | None = None
        self._extension_result: ExtensionMaterializationResult | None = None

    @property
    def primary(self) -> ExtensionPrimaryMaterialization:
        return self._primary

    @property
    def candidate_commitment_wire(self) -> dict[str, Any]:
        """The complete pre-seal extension object allowed on candidate wire."""

        return {
            "schema_version": "ucm-extension-candidate-commitment/1",
            "primary_catalog_digest": self._primary_world.catalog.digest,
            "primary_scope_digest": self._primary_scope_digest,
            "commitment": self._custody.public.to_wire(),
        }

    def _incomplete_seal(self, interface: str, detail: str) -> ExtensionSealResult:
        return ExtensionSealResult(
            status=MaterializationStatus.INCOMPLETE,
            structural_status=MaterializationStatus.INCOMPLETE,
            world_slot=self._world_slot,
            record_set_digest=self._primary.record_set_digest,
            binding_set_digest=None,
            bindings=(),
            blockers=(
                HarnessBlocker(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    self._world_slot,
                    self._panel.panel_id,
                    interface,
                    detail,
                ),
            ),
        )

    def seal_primary(
        self,
        *,
        candidate_root: Path,
        model_artifact: bytes,
        states_by_record_id: Mapping[str, SealedState],
        initialization_receipts_by_record_id: Mapping[
            str, ExtensionInitializationReceipt
        ] | None = None,
    ) -> ExtensionSealResult:
        """Bind externally produced opaque states to every exact S0 record.

        The registry never synthesizes a candidate state from history.  The
        judge-owned histories are used only to verify record/history lineage
        inside ``ExtensionRunner.seal_primary`` and are not retained in a
        candidate request envelope.
        """

        if self._seal_result is not None:
            raise ProtocolViolation("extension primary seal attempt is append-only")
        if not isinstance(candidate_root, Path):
            raise ProtocolViolation("candidate_root must be pathlib.Path")
        if type(model_artifact) is not bytes:
            raise ProtocolViolation("model_artifact must be exact bytes")
        if not isinstance(states_by_record_id, Mapping):
            raise ProtocolViolation("states_by_record_id must be a mapping")
        unresolved_primary = tuple(
            blocker
            for blocker in self._primary.blockers
            if blocker.interface != "primary_state_seal"
        )
        if unresolved_primary:
            result = self._incomplete_seal(
                "primary_corpus",
                "release extension seal requires the full declared S0 cohort with no primary materialization blockers",
            )
            self._seal_result = result
            self._persist_seal_result(result)
            return result
        if not isinstance(initialization_receipts_by_record_id, Mapping):
            result = self._incomplete_seal(
                "initialization_execution_receipt",
                "every S0 state requires a typed external fresh-worker initialize receipt",
            )
            self._seal_result = result
            self._persist_seal_result(result)
            return result
        try:
            _require_physically_separate_roots(
                candidate_root, self._candidate_output_root
            )
            _require_physically_separate_roots(candidate_root, self._judge_output_root)
        except ProtocolViolation as exc:
            result = self._incomplete_seal("candidate_bundle", str(exc))
            self._seal_result = result
            self._persist_seal_result(result)
            return result

        expected_ids = set(self._episodes)
        supplied_ids = set(states_by_record_id)
        if supplied_ids != expected_ids:
            result = self._incomplete_seal(
                "record_join",
                "candidate state record ids do not exactly match the frozen primary record set",
            )
            self._seal_result = result
            self._persist_seal_result(result)
            return result
        if set(initialization_receipts_by_record_id) != expected_ids:
            result = self._incomplete_seal(
                "initialization_execution_receipt",
                "initialize receipt record ids do not exactly match the frozen primary record set",
            )
            self._seal_result = result
            self._persist_seal_result(result)
            return result

        local_runners: dict[str, ExtensionRunner] = {}
        local_states: dict[str, SealedState] = {}
        receipts: list[ExtensionStateBindingReceipt] = []
        try:
            for record_id in sorted(expected_ids):
                state = states_by_record_id[record_id]
                initialization = initialization_receipts_by_record_id[record_id]
                if type(state) is not SealedState:
                    raise ProtocolViolation("every exact record requires a SealedState")
                if type(state.candidate_input) is not CandidateStateInput:
                    raise ProtocolViolation(
                        "sealed state requires an exact CandidateStateInput"
                    )
                if type(state.candidate_input.payload) is not StatePayload:
                    raise ProtocolViolation("sealed state requires an exact StatePayload")
                if type(state.record) is not HarnessStateRecord:
                    raise ProtocolViolation(
                        "sealed state requires an exact HarnessStateRecord"
                    )
                if type(initialization) is not ExtensionInitializationReceipt:
                    raise ProtocolViolation(
                        "every exact record requires ExtensionInitializationReceipt"
                    )
                episode = self._episodes[record_id]
                record = state.record
                payload = state.candidate_input.payload
                recomputed_state_hash = compute_state_hash(
                    payload,
                    candidate_bundle_digest=record.candidate_bundle_digest,
                    model_digest=record.model_digest,
                    scope_digest=record.scope_digest,
                    catalog_digest=record.catalog_digest,
                    as_of_available_at=record.as_of_available_at,
                )
                if record.state_hash != recomputed_state_hash:
                    raise ProtocolViolation("sealed state hash does not match its payload")
                expected_state_id = "ucm-state:" + recomputed_state_hash[7:23]
                if record.state_id != expected_state_id:
                    raise ProtocolViolation("sealed state_id does not match its state hash")
                if record.operation != "initialize":
                    raise ProtocolViolation(
                        "extension primary state must be an initialize result"
                    )
                if record.parent_state_hash is not None or record.delta_digest is not None:
                    raise ProtocolViolation(
                        "extension primary initialize state cannot claim a parent/delta"
                    )
                if record.payload_size_bytes != len(payload.payload):
                    raise ProtocolViolation("sealed state payload_size_bytes mismatch")
                if record.scope_digest != self._primary_scope_digest:
                    raise ProtocolViolation("sealed state/record scope digest mismatch")
                if record.catalog_digest != self._primary_world.catalog.digest:
                    raise ProtocolViolation("sealed state/record catalog digest mismatch")
                if record.as_of_available_at != episode.public_history.as_of_available_at:
                    raise ProtocolViolation("sealed state/record cut mismatch")
                for actual, expected, label in (
                    (initialization.record_id, record_id, "record id"),
                    (initialization.state_hash, record.state_hash, "state hash"),
                    (
                        initialization.candidate_bundle_digest,
                        record.candidate_bundle_digest,
                        "candidate bundle digest",
                    ),
                    (initialization.model_digest, record.model_digest, "model digest"),
                    (
                        initialization.catalog_digest,
                        record.catalog_digest,
                        "catalog digest",
                    ),
                    (initialization.scope_digest, record.scope_digest, "scope digest"),
                ):
                    if actual != expected:
                        raise ProtocolViolation(
                            f"initialize receipt/{label} binding mismatch"
                        )
                expected_request_digest = digest_json(
                    {
                        "protocol": "ucm-extension-initialize-request/1",
                        "operation": "initialize",
                        "record_id": record_id,
                        "public_history_digest": episode.public_history.digest,
                        "candidate_bundle_digest": record.candidate_bundle_digest,
                        "model_digest": record.model_digest,
                        "catalog_digest": record.catalog_digest,
                        "scope_digest": record.scope_digest,
                        "as_of_available_at": record.as_of_available_at,
                    }
                )
                expected_response_digest = digest_json(
                    {
                        "protocol": "ucm-extension-initialize-response/1",
                        "operation": "initialize",
                        "record_id": record_id,
                        "state_hash": record.state_hash,
                        "state_id": record.state_id,
                        "payload_digest": digest_bytes(payload.payload),
                        "payload_size_bytes": len(payload.payload),
                        "payload_codec": payload.codec,
                        "payload_schema_version": payload.schema_version,
                        "state_class": payload.state_class.value,
                    }
                )
                if initialization.request_digest != expected_request_digest:
                    raise ProtocolViolation(
                        "initialize receipt request digest is not registry-bound"
                    )
                if initialization.response_digest != expected_response_digest:
                    raise ProtocolViolation(
                        "initialize receipt response digest is not registry-bound"
                    )
                runner = ExtensionRunner(
                    self._custody,
                    primary_catalog_digest=self._primary_world.catalog.digest,
                )
                seal = runner.seal_primary(
                    candidate_root=candidate_root,
                    model_artifact=model_artifact,
                    states=(state,),
                    histories={record.state_hash: episode.public_history},
                )
                receipts.append(
                    ExtensionStateBindingReceipt(
                        record_id,
                        episode.public_history.digest,
                        record.state_hash,
                        record.scope_digest,
                        record.candidate_bundle_digest,
                        record.model_digest,
                        record.catalog_digest,
                        record.as_of_available_at,
                        state.candidate_input.payload.payload.hex(),
                        digest_bytes(state.candidate_input.payload.payload),
                        state.candidate_input.payload.codec,
                        state.candidate_input.payload.schema_version,
                        state.candidate_input.payload.state_class.value,
                        digest_json(initialization.to_wire()),
                        seal.seal_digest,
                    )
                )
                local_runners[record_id] = runner
                local_states[record_id] = state
        except (OSError, ProtocolViolation) as exc:
            result = self._incomplete_seal(
                "primary_state_seal", f"candidate seal rejected: {type(exc).__name__}: {exc}"
            )
            self._seal_result = result
            self._persist_seal_result(result)
            return result

        binding_set_digest = digest_json([item.to_wire() for item in receipts])
        result = ExtensionSealResult(
            status=MaterializationStatus.INCOMPLETE,
            structural_status=MaterializationStatus.COMPLETE,
            world_slot=self._world_slot,
            record_set_digest=self._primary.record_set_digest,
            binding_set_digest=binding_set_digest,
            bindings=tuple(receipts),
            blockers=(
                HarnessBlocker(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    self._world_slot,
                    self._panel.panel_id,
                    "initialization_receipt_provenance",
                    "typed initialize receipts are caller-supplied and not independently authenticated by this registry prototype",
                ),
            ),
        )
        self._runners = local_runners
        self._states = local_states
        self._seal_result = result
        self._persist_seal_result(result)
        return result

    def _persist_seal_result(self, result: ExtensionSealResult) -> None:
        _write_exclusive(
            self._judge_output_root / "primary-seal-result.json",
            canonical_json_bytes(result.to_wire()),
        )

    def _incomplete_extension(
        self, interface: str, detail: str
    ) -> ExtensionMaterializationResult:
        return ExtensionMaterializationResult(
            status=MaterializationStatus.INCOMPLETE,
            corpus_status=MaterializationStatus.INCOMPLETE,
            world_slot=self._world_slot,
            split=self._split.value,
            population_count=0,
            probe_record_count=0,
            primary_record_set_digest=self._primary.record_set_digest,
            primary_binding_set_digest=(
                None
                if self._seal_result is None
                else self._seal_result.binding_set_digest
            ),
            extension_scope_digest=self._extension_scope_digest,
            extension_pack_digest=(
                None if self._reveal is None else self._reveal.pack_digest
            ),
            candidate_path=None,
            candidate_manifest_path=None,
            judge_path=None,
            candidate_digest=None,
            candidate_manifest_digest=None,
            judge_digest=None,
            evidence_scope="ordering-and-corpus-only",
            ordering_complete=False,
            extension_evaluation_complete=False,
            query_contract_verified=False,
            execution_assurance="portable-callback",
            blockers=(
                HarnessBlocker(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    self._world_slot,
                    self._panel.panel_id,
                    interface,
                    detail,
                ),
            ),
        )

    def _assert_pre_reveal_s0_closure_immutable(self) -> None:
        """Rehash the complete S0 corpus/receipt closure before opening S1.

        This audit deliberately runs before even the global extension pack is
        opened.  The per-record runner subsequently revalidates the separately
        sealed candidate tree, model bytes, state payload, and history.
        """

        if (
            self._seal_result is None
            or self._seal_result.structural_status
            is not MaterializationStatus.COMPLETE
        ):
            raise ProtocolViolation("pre-reveal S0 closure lacks an exact seal")
        exact_files = (
            (self._primary.candidate_path, self._primary.candidate_digest),
            (
                self._primary.candidate_commitment_path,
                self._primary.candidate_commitment_digest,
            ),
            (self._primary.judge_path, self._primary.judge_digest),
        )
        for path, expected_digest in exact_files:
            if not path.is_file() or digest_bytes(path.read_bytes()) != expected_digest:
                raise ProtocolViolation(
                    f"pre-reveal sealed primary artifact changed: {path.name}"
                )
        exact_receipts = (
            (
                self._judge_output_root / "primary-materialization-status.json",
                canonical_json_bytes(self._primary.to_wire()),
            ),
            (
                self._judge_output_root / "primary-seal-result.json",
                canonical_json_bytes(self._seal_result.to_wire()),
            ),
        )
        for path, expected_bytes in exact_receipts:
            if not path.is_file() or path.read_bytes() != expected_bytes:
                raise ProtocolViolation(
                    f"pre-reveal sealed primary receipt changed: {path.name}"
                )

    def reveal_extension_catalog(self) -> ExtensionRevealReceipt:
        """Open only the global S1 contract; do not expose any S1 patient row."""

        if self._reveal_receipt is not None:
            raise ProtocolViolation("extension reveal is append-only")
        if (
            self._seal_result is None
            or self._seal_result.structural_status
            is not MaterializationStatus.COMPLETE
            or not self._runners
        ):
            raise ProtocolViolation(
                "extension reveal requires exact candidate/model/state seals"
            )
        self._assert_pre_reveal_s0_closure_immutable()
        reveals = [self._runners[key].reveal() for key in sorted(self._runners)]
        reveal = reveals[0]
        if any(
            item.commitment != reveal.commitment
            or item.pack_digest != reveal.pack_digest
            or item.pack_bytes != reveal.pack_bytes
            for item in reveals[1:]
        ):
            raise ProtocolViolation("per-record extension reveals disagree")
        activate = getattr(self._primary_world, "activate_extension", None)
        if not callable(activate):
            raise ProtocolViolation("extension world lacks post-seal activation")
        world = activate(reveal)
        if not isinstance(world, MicroWorld):
            raise ProtocolViolation("extension activation returned the wrong world")
        extension_catalog = getattr(world, "extension_catalog", None)
        if extension_catalog is None:
            raise ProtocolViolation("activated world lacks extension catalog")
        extension_scope_digest = digest_json(
            {
                "protocol": "ucm-extension-scope/1",
                "primary_scope_digest": self._primary_scope_digest,
                "extension_pack_digest": reveal.pack_digest,
            }
        )
        candidate_reveal_path = self._candidate_output_root / "extension-reveal.json"
        candidate_reveal = {
            "schema_version": "ucm-extension-candidate-reveal/1",
            "commitment": self._custody.public.to_wire(),
            "primary_catalog_digest": self._primary_world.catalog.digest,
            "primary_scope_digest": self._primary_scope_digest,
            "primary_record_set_digest": self._primary.record_set_digest,
            "primary_binding_set_digest": self._seal_result.binding_set_digest,
            "extension_catalog_digest": extension_catalog.digest,
            "extension_scope_digest": extension_scope_digest,
            "extension_pack_digest": reveal.pack_digest,
            "extension_pack": reveal.pack,
            "evidence_scope": "runtime-ordering-only",
            "source_hiding_verified": False,
            "freeze_grade_evidence": False,
        }
        reject_privileged_keys(
            candidate_reveal,
            forbidden=PRIVILEGED_FIELD_NAMES,
            path="$.extension_candidate_reveal",
        )
        reveal_bytes = canonical_json_bytes(candidate_reveal)
        _write_exclusive(candidate_reveal_path, reveal_bytes)
        receipt = ExtensionRevealReceipt(
            self._world_slot,
            self._primary.record_set_digest,
            self._seal_result.binding_set_digest,
            extension_scope_digest,
            reveal.pack_digest,
            candidate_reveal_path,
            digest_bytes(reveal_bytes),
        )
        _write_exclusive(
            self._judge_output_root / "extension-reveal-receipt.json",
            canonical_json_bytes(receipt.to_wire()),
        )
        self._reveal = reveal
        self._reveal_receipt = receipt
        self._extension_scope_digest = extension_scope_digest
        self._activated_world = world
        return receipt

    def _assert_post_query_closure_immutable(self) -> None:
        """Rehash S0, reveal, and first-query closure immediately before S1."""

        if (
            self._seal_result is None
            or self._reveal_receipt is None
            or self._reveal is None
        ):
            raise ProtocolViolation("primary closure is not fully sealed/revealed")
        self._assert_pre_reveal_s0_closure_immutable()
        exact_receipts = (
            (
                self._judge_output_root / "extension-reveal-receipt.json",
                canonical_json_bytes(self._reveal_receipt.to_wire()),
            ),
        )
        for path, expected_bytes in exact_receipts:
            if not path.is_file() or path.read_bytes() != expected_bytes:
                raise ProtocolViolation(f"sealed judge receipt changed: {path.name}")
        reveal_path = self._reveal_receipt.candidate_reveal_path
        if (
            not reveal_path.is_file()
            or digest_bytes(reveal_path.read_bytes())
            != self._reveal_receipt.candidate_reveal_digest
        ):
            raise ProtocolViolation("sealed candidate reveal artifact changed")
        self._flush_first_query_stream(final=True)
        expected_query_bytes = b"".join(self._first_query_raw_bytes.values())
        if (
            not self._first_query_path.is_file()
            or self._first_query_path.read_bytes() != expected_query_bytes
        ):
            raise ProtocolViolation("sealed first-query judge receipt changed")
        # ``reveal`` revalidates candidate tree, model bytes, sealed state and
        # judge-custodied history even when the pack was already opened.
        for runner in self._runners.values():
            current = runner.reveal()
            if (
                current.commitment != self._reveal.commitment
                or current.pack_digest != self._reveal.pack_digest
            ):
                raise ProtocolViolation("extension reveal changed after first query")

    def _flush_first_query_stream(self, *, final: bool) -> None:
        handle = self._first_query_handle
        if handle is None:
            return
        handle.flush()
        if final:
            os.fsync(handle.fileno())
            handle.close()
            self._first_query_handle = None

    def materialize_extension(
        self,
        *,
        episode_limit: int | None = None,
        probe_limit: int | None = None,
    ) -> ExtensionMaterializationResult:
        """Write S1 rows only after every sealed S0 state had its first query."""

        if self._extension_result is not None:
            raise ProtocolViolation("extension materialization is append-only")
        if episode_limit is not None and (
            type(episode_limit) is not int or episode_limit < 0
        ):
            raise ProtocolViolation("episode_limit must be non-negative")
        if probe_limit is not None and (
            type(probe_limit) is not int or probe_limit < 0
        ):
            raise ProtocolViolation("probe_limit must be non-negative")
        if self._seal_result is None or not self._runners:
            return self._incomplete_extension(
                "primary_state_seal",
                "no exact candidate/model/state seal exists; extension remains opaque",
            )
        if (
            self._reveal is None
            or self._activated_world is None
            or self._reveal_receipt is None
            or self._extension_scope_digest is None
        ):
            return self._incomplete_extension(
                "extension_reveal",
                "global extension catalog must be revealed before first queries",
            )
        missing_first_queries = set(self._runners) - self._first_query_record_ids
        if missing_first_queries:
            return self._incomplete_extension(
                "first_query_cohort",
                f"{len(missing_first_queries)} sealed primary records lack a state-only first query",
            )
        self._assert_post_query_closure_immutable()
        reveal = self._reveal
        world = self._activated_world
        extension_catalog = getattr(world, "extension_catalog")
        extension_scope_digest = self._extension_scope_digest

        specification = EXTENSION_WORLD_REGISTRY[self._world_slot]
        declared_count = specification.extension_population_count
        requested_count = (
            declared_count
            if episode_limit is None
            else min(episode_limit, declared_count)
        )
        candidate_path = self._candidate_output_root / "extension-public.jsonl"
        candidate_manifest_path = (
            self._candidate_output_root / "extension-public-manifest.json"
        )
        judge_path = self._judge_output_root / "extension-private.jsonl"
        blockers: list[HarnessBlocker] = [
            blocker
            for blocker in self._primary.blockers
            if blocker.interface != "primary_state_seal"
        ]
        if requested_count != declared_count:
            blockers.append(
                HarnessBlocker(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    self._world_slot,
                    self._panel.panel_id,
                    "extension_split_size",
                    f"materialized {requested_count} of declared {declared_count} extension rows",
                )
            )

        probe_written = 0
        extension_rows: list[dict[str, str]] = []
        generator = getattr(world, "generate_extension_episode", None)
        if not callable(generator):
            raise ProtocolViolation("activated world lacks extension generator")
        with _ExclusiveJsonl(candidate_path) as public_writer, _ExclusiveJsonl(
            judge_path
        ) as judge_writer:
            for index in range(requested_count):
                episode = generator(self._split, self._generator_seed, index)
                if type(episode) is not PrivateEpisode:
                    raise ProtocolViolation("extension generator returned a non-episode")
                if (
                    episode.split is not self._split
                    or episode.environment_key != world.environment_key
                ):
                    raise ProtocolViolation(
                        "extension population episode contradicts requested world/split"
                    )
                record_id = _opaque_alias(
                    self._alias_secret,
                    slot=self._world_slot,
                    panel=self._panel.panel_id,
                    split=self._split,
                    cohort="extension-population",
                    ordinal=index,
                )
                strata, unverified = _strata_for_episode(world, self._panel, episode)
                public_writer.append(
                    _candidate_row(
                        record_id,
                        world,
                        episode,
                        catalog=extension_catalog,
                        scope_digest=extension_scope_digest,
                    )
                )
                private = _judge_row(
                    record_id,
                    slot=self._world_slot,
                    panel=self._panel,
                    split=self._split,
                    episode=episode,
                    cohort="population",
                    ordinal=index,
                    probe_id=None,
                    pair_id=None,
                    pair_side=None,
                    strata=strata,
                    unverified_strata=unverified,
                )
                private.update(
                    {
                        "extension_stage": "S1",
                        "record_scope_digest": extension_scope_digest,
                        "primary_record_set_digest": self._primary.record_set_digest,
                        "primary_binding_set_digest": self._seal_result.binding_set_digest,
                        "extension_pack_digest": reveal.pack_digest,
                    }
                )
                judge_writer.append(private)
                extension_rows.append(
                    {
                        "record_id": record_id,
                        "public_history_digest": episode.public_history.digest,
                        "scope_digest": extension_scope_digest,
                    }
                )

            # The fixed pair cohort is a sealed-test audit fixture.  W16/W17
            # producers hard-code SEALED_TEST in these methods, so invoking
            # them for TRAIN/VALIDATION would silently cross split custody.
            declared_pair_invocations = (
                specification.extension_pair_count
                if self._split is WorldSplit.SEALED_TEST
                else 0
            )
            requested_pair_invocations = (
                declared_pair_invocations
                if probe_limit is None
                else min(probe_limit, declared_pair_invocations)
            )
            remaining = requested_pair_invocations
            probe_ordinal = 0
            allocation = dict(specification.probe_pair_repetitions)
            for probe in self._panel.probes:
                method = getattr(world, probe.method_name, None)
                if not callable(method):
                    blockers.append(
                        HarnessBlocker(
                            "UCM-E003-HARNESS_INCOMPLETE",
                            self._world_slot,
                            self._panel.panel_id,
                            probe.method_name,
                            "post-seal probe producer is missing",
                        )
                    )
                    continue
                repetitions = min(allocation[probe.method_name], remaining)
                for repetition in range(repetitions):
                    probe_seed = _extension_probe_seed(
                        self._world_slot,
                        self._generator_seed,
                        probe.method_name,
                        repetition,
                    )
                    result = method(probe_seed)
                    groups = _flatten_probe_result(result, declaration=probe)
                    for local_name, episodes in groups:
                        pair_id = "p-" + hmac.new(
                            self._alias_secret,
                            b"UCM-EXTENSION-PAIR-ALIAS-v1\0"
                            + canonical_json_bytes(
                                {
                                    "panel": self._panel.panel_id,
                                    "probe": local_name,
                                    "repetition": repetition,
                                    "slot": self._world_slot,
                                }
                            ),
                            hashlib.sha256,
                        ).hexdigest()
                        for side, episode in enumerate(episodes):
                            if type(episode) is not PrivateEpisode:
                                raise ProtocolViolation(
                                    "extension probe contains a non-episode"
                                )
                            if (
                                episode.split is not self._split
                                or episode.environment_key != world.environment_key
                            ):
                                raise ProtocolViolation(
                                    "extension probe episode contradicts requested world/split"
                                )
                            if (
                                episode.public_history.catalog_digest
                                == world.catalog.digest
                            ):
                                catalog = world.catalog
                                record_scope = self._primary_scope_digest
                            elif (
                                episode.public_history.catalog_digest
                                == extension_catalog.digest
                            ):
                                catalog = extension_catalog
                                record_scope = extension_scope_digest
                            else:
                                raise ProtocolViolation(
                                    "extension probe history has an unbound catalog"
                                )
                            record_id = _opaque_alias(
                                self._alias_secret,
                                slot=self._world_slot,
                                panel=self._panel.panel_id,
                                split=self._split,
                                cohort="extension-probe",
                                ordinal=probe_ordinal,
                            )
                            public_writer.append(
                                _candidate_row(
                                    record_id,
                                    world,
                                    episode,
                                    catalog=catalog,
                                    scope_digest=record_scope,
                                )
                            )
                            private = _judge_row(
                                record_id,
                                slot=self._world_slot,
                                panel=self._panel,
                                split=self._split,
                                episode=episode,
                                cohort="probe",
                                ordinal=None,
                                probe_id=local_name,
                                pair_id=pair_id,
                                pair_side=side,
                                strata=("behavior_pair",),
                                unverified_strata=(),
                            )
                            private.update(
                                {
                                    "extension_stage": "S1-probe",
                                    "record_scope_digest": record_scope,
                                    "primary_record_set_digest": self._primary.record_set_digest,
                                    "primary_binding_set_digest": self._seal_result.binding_set_digest,
                                    "extension_pack_digest": reveal.pack_digest,
                                    "probe_repetition": repetition,
                                }
                            )
                            judge_writer.append(private)
                            extension_rows.append(
                                {
                                    "record_id": record_id,
                                    "public_history_digest": episode.public_history.digest,
                                    "scope_digest": record_scope,
                                }
                            )
                            probe_ordinal += 1
                            probe_written += 1
                remaining -= repetitions
                if remaining <= 0:
                    break
            if requested_pair_invocations != declared_pair_invocations:
                blockers.append(
                    HarnessBlocker(
                        "UCM-E003-HARNESS_INCOMPLETE",
                        self._world_slot,
                        self._panel.panel_id,
                        "extension_probe_count",
                        f"materialized {requested_pair_invocations} of declared {declared_pair_invocations} extension pairs",
                    )
                )

        candidate_manifest = {
            "schema_version": "ucm-extension-candidate-manifest/1",
            "primary_catalog_digest": self._primary_world.catalog.digest,
            "primary_scope_digest": self._primary_scope_digest,
            "primary_record_set_digest": self._primary.record_set_digest,
            "primary_binding_set_digest": self._seal_result.binding_set_digest,
            "candidate_reveal_digest": self._reveal_receipt.candidate_reveal_digest,
            "first_query_record_set_digest": digest_json(
                sorted(self._first_query_record_ids)
            ),
            "extension_catalog_digest": extension_catalog.digest,
            "extension_scope_digest": extension_scope_digest,
            "extension_pack_digest": reveal.pack_digest,
            "declared_extension_population_count": declared_count,
            "declared_extension_pair_count": declared_pair_invocations,
            "record_set_digest": digest_json(extension_rows),
            "evidence_scope": "ordering-and-corpus-only",
            "ordering_complete": True,
            "query_contract_verified": False,
            "execution_assurance": "portable-callback",
            "state_only_closure_verified": False,
            "initialization_receipt_provenance_verified": False,
            "source_hiding_verified": False,
            "atomic_publish_verified": False,
            "extension_evaluation_complete": False,
        }
        # No world/test/private identity or opening key is placed on candidate wire.
        reject_privileged_keys(
            candidate_manifest,
            forbidden=PRIVILEGED_FIELD_NAMES,
            path="$.extension_candidate_manifest",
        )
        manifest_bytes = canonical_json_bytes(candidate_manifest)
        _write_exclusive(candidate_manifest_path, manifest_bytes)
        candidate_bytes = candidate_path.read_bytes()
        judge_bytes = judge_path.read_bytes()
        corpus_status = (
            MaterializationStatus.INCOMPLETE
            if blockers
            else MaterializationStatus.COMPLETE
        )
        evidence_blockers = [
            *blockers,
            HarnessBlocker(
                "UCM-E003-HARNESS_INCOMPLETE",
                self._world_slot,
                self._panel.panel_id,
                "first_query_contract",
                "registry does not yet own/freeze the exact W16/W17 extension query contract",
            ),
            HarnessBlocker(
                "UCM-E003-HARNESS_INCOMPLETE",
                self._world_slot,
                self._panel.panel_id,
                "first_query_execution_assurance",
                "portable in-process callback does not prove fresh-process state-only closure",
            ),
            HarnessBlocker(
                "UCM-E003-HARNESS_INCOMPLETE",
                self._world_slot,
                self._panel.panel_id,
                "initialization_receipt_provenance",
                "typed initialize receipts are caller-supplied and not independently authenticated by this registry prototype",
            ),
            HarnessBlocker(
                "UCM-E003-HARNESS_INCOMPLETE",
                self._world_slot,
                self._panel.panel_id,
                "extension_source_hiding",
                "W16/W17 extension pack literals remain present in repository source; runtime commitment proves ordering, not source secrecy",
            ),
            HarnessBlocker(
                "UCM-E003-HARNESS_INCOMPLETE",
                self._world_slot,
                self._panel.panel_id,
                "atomic_extension_publish",
                "candidate and judge S1 artifacts are not yet published as one cross-root atomic transaction",
            ),
        ]
        result = ExtensionMaterializationResult(
            status=MaterializationStatus.INCOMPLETE,
            corpus_status=corpus_status,
            world_slot=self._world_slot,
            split=self._split.value,
            population_count=requested_count,
            probe_record_count=probe_written,
            primary_record_set_digest=self._primary.record_set_digest,
            primary_binding_set_digest=self._seal_result.binding_set_digest,
            extension_scope_digest=extension_scope_digest,
            extension_pack_digest=reveal.pack_digest,
            candidate_path=candidate_path,
            candidate_manifest_path=candidate_manifest_path,
            judge_path=judge_path,
            candidate_digest=digest_bytes(candidate_bytes),
            candidate_manifest_digest=digest_bytes(manifest_bytes),
            judge_digest=digest_bytes(judge_bytes),
            evidence_scope="ordering-and-corpus-only",
            ordering_complete=True,
            extension_evaluation_complete=False,
            query_contract_verified=False,
            execution_assurance="portable-callback",
            blockers=tuple(evidence_blockers),
        )
        _write_exclusive(
            self._judge_output_root / "extension-materialization-status.json",
            canonical_json_bytes(result.to_wire()),
        )
        self._reveal = reveal
        self._activated_world = world
        self._extension_result = result
        return result

    def first_query_portable_callback(
        self,
        *,
        record_id: str,
        query: dict[str, Any],
        invoke: Callable[[ExtensionFirstQueryRequest], ExtensionFirstQueryResult],
        expected_prediction: dict[str, Any] | None = None,
        tolerance: float = 1e-9,
    ) -> ExtensionPortableQueryEvidence:
        """Exercise the state-only *wire* with a non-isolating prototype callback.

        The request envelope contains no history, but an in-process callable can
        still close over history or read files.  Consequently this method only
        proves ordering/request shape; every persisted receipt is explicitly
        non-freeze-grade until a registry-owned isolated executor replaces it.
        """

        if self._reveal is None or self._activated_world is None:
            raise ProtocolViolation(
                "first extension query requires post-seal reveal/materialization"
            )
        runner = self._runners.get(record_id)
        state = self._states.get(record_id)
        if runner is None or state is None:
            raise ProtocolViolation("first extension query record join is unknown")
        captured: list[ExtensionFirstQueryResult] = []

        def capture(request: ExtensionFirstQueryRequest) -> ExtensionFirstQueryResult:
            result = invoke(request)
            captured.append(result)
            return result

        transcript = runner.first_state_only_query(
            state_hash=state.record.state_hash,
            query=query,
            invoke=capture,
            expected_prediction=expected_prediction,
            tolerance=tolerance,
        )
        result = captured[0]
        raw = {
            "schema_version": "ucm-extension-first-query-raw/1",
            "record_id": record_id,
            "public_history_digest": self._episodes[record_id].public_history.digest,
            "primary_scope_digest": state.record.scope_digest,
            "primary_state_hash": transcript.primary_state_hash,
            "request_digest": transcript.request_digest,
            "query": query,
            "state_snapshot_before": transcript.state_snapshot_before,
            "state_snapshot_after": transcript.state_snapshot_after,
            "outcome": {
                "status": transcript.status.value,
                "prediction": result.prediction,
                "verdict": transcript.verdict.value,
                "max_numeric_error": transcript.max_numeric_error,
                "expected_prediction_supplied": expected_prediction is not None,
            },
            "query_contract_verified": False,
            "execution_assurance": "portable-callback",
            "state_only_closure_verified": False,
            "freeze_grade_evidence": False,
        }
        raw_bytes = canonical_json_bytes(raw)
        if self._first_query_handle is None:
            mode = "ab" if self._first_query_path.exists() else "xb"
            self._first_query_handle = self._first_query_path.open(mode)
        self._first_query_handle.write(raw_bytes)
        # Flush Python buffering so a judge can inspect progress; one fsync is
        # performed when the exact cohort is finalized before S1 publication.
        self._first_query_handle.flush()
        self._first_query_record_ids.add(record_id)
        self._first_query_raw_bytes[record_id] = raw_bytes
        return ExtensionPortableQueryEvidence(
            MaterializationStatus.INCOMPLETE,
            record_id,
            transcript,
        )

    def authorize_migration(
        self,
        *,
        record_id: str,
        migrate: Callable[[VisibleHistory, RevealedExtensionPack], StatePayload],
        migrated_candidate_root: Path | None = None,
        migrated_model_artifact: bytes | None = None,
        training_examples: Sequence[bytes] = (),
    ) -> MigrationOutcome:
        """Delegate measured replay; runner permits it only after scope_insufficient."""

        if self._reveal is None or self._activated_world is None:
            raise ProtocolViolation("migration requires a post-seal reveal")
        runner = self._runners.get(record_id)
        state = self._states.get(record_id)
        if runner is None or state is None:
            raise ProtocolViolation("migration record join is unknown")
        self._flush_first_query_stream(final=True)
        catalog = getattr(self._activated_world, "extension_catalog", None)
        if catalog is None:
            raise ProtocolViolation("activated world lacks extension catalog")
        outcome = runner.authorize_migration(
            state_hash=state.record.state_hash,
            migrate=migrate,
            extension_catalog_digest=catalog.digest,
            migrated_candidate_root=migrated_candidate_root,
            migrated_model_artifact=migrated_model_artifact,
            training_examples=training_examples,
        )
        cost = outcome.cost
        raw = {
            "schema_version": "ucm-extension-migration-raw/1",
            "record_id": record_id,
            "authorization_digest": outcome.authorization_digest,
            "primary_state_hash": outcome.primary_state_hash,
            "migrated_state_hash": outcome.migrated_state.record.state_hash,
            "migrated_scope_digest": outcome.migrated_state.record.scope_digest,
            "migrated_catalog_digest": outcome.migrated_state.record.catalog_digest,
            "cost": {
                "replay_history_bytes": cost.replay_history_bytes,
                "old_state_bytes": cost.old_state_bytes,
                "new_state_bytes": cost.new_state_bytes,
                "state_growth_bytes": cost.state_growth_bytes,
                "candidate_changed_bytes": cost.candidate_changed_bytes,
                "candidate_core_diff_loc": cost.candidate_core_diff_loc,
                "model_artifact_bytes": cost.model_artifact_bytes,
                "model_changed_bytes": cost.model_changed_bytes,
                "training_examples": cost.training_examples,
                "training_bytes": cost.training_bytes,
            },
            "s0_snapshot_before": outcome.s0_snapshot_before,
            "s0_snapshot_after": outcome.s0_snapshot_after,
        }
        _write_exclusive(
            self._judge_output_root / f"migration-{record_id}.json",
            canonical_json_bytes(raw),
        )
        return outcome


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
    if world_slot in EXTENSION_WORLD_REGISTRY:
        blockers.append(
            HarnessBlocker(
                "UCM-E003-HARNESS_INCOMPLETE",
                world_slot,
                panel.panel_id,
                "two_stage_extension",
                "generic materializer writes only the S0 cohort and cannot prove the sealed W16/W17 reveal/query/S1 protocol",
            )
        )
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
                if world_slot in EXTENSION_WORLD_REGISTRY:
                    break
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
                            if (
                                episode.split is not split
                                or episode.environment_key != world.environment_key
                            ):
                                raise ProtocolViolation(
                                    "probe episode contradicts requested world/split"
                                )
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
            "schema_version": "ucm-world-registry/2",
            "worlds": [WORLD_REGISTRY[slot].to_wire() for slot in WORLD_REGISTRY],
            "two_stage_extensions": [
                EXTENSION_WORLD_REGISTRY[slot].to_wire()
                for slot in EXTENSION_WORLD_REGISTRY
            ],
        }
    )


__all__ = [
    "DEFAULT_SPLIT_SIZES",
    "EXTENSION_WORLD_REGISTRY",
    "ExtensionMaterializationResult",
    "ExtensionInitializationReceipt",
    "ExtensionPrimaryMaterialization",
    "ExtensionPortableQueryEvidence",
    "ExtensionRegistrySession",
    "ExtensionRevealReceipt",
    "ExtensionSealResult",
    "ExtensionStateBindingReceipt",
    "ExtensionWorldDeclaration",
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
