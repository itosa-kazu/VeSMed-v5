"""Fail-closed pre-split family authority scaffolding for the UCM benchmark.

The benchmark needs counterfactual families to exist *before* a split is
chosen.  A row produced after materialisation is therefore evidence about a
previously declared family member; it is never an authority capable of
creating or renaming that family.

This module captures that boundary without pretending that the current
portable harness is freeze-grade.  The only successful artifact status is
``PRE_FREEZE_SCAFFOLD``.  Legacy/post-split grouping is always
``INCOMPLETE``, and every wire artifact hard-codes both
``freeze_grade_evidence = false`` and ``benchmark_freeze_eligible = false``.

The intended authority flow is::

    producer semantic drafts
      + builder-owned latent/noise/acquisition transcripts
        -> pre-split source
        -> weighted atomic connected-component assignment
        -> exact row materialisation receipts

No constructor in that flow accepts a producer-reported family digest.
Digests are derived from canonical builder inputs.  This is still only a
scaffold because custody, an independently sealed builder runtime, and atomic
publication have not yet been implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Any, Iterable, Mapping
from weakref import ReferenceType, ref

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
    domain_digest,
    reject_privileged_keys,
    validate_json_like,
)


SOURCE_PROTOCOL = "ucm-pre-split-family-source/3"
ASSIGNMENT_PROTOCOL = "ucm-weighted-atomic-family-assignment/2"
RECEIPT_PROTOCOL = "ucm-family-materialization-receipt/3"
LEDGER_PROTOCOL = "ucm-family-materialization-ledger/1"
EVIDENCE_PROTOCOL = "ucm-row-materialization-evidence/2"
ROW_BUNDLE_PROTOCOL = "ucm-pre-split-row-bundle-commitment/1"
LEGACY_AUDIT_PROTOCOL = "ucm-legacy-family-adapter-audit/2"

INCOMPLETE_CODE = "UCM-E003-HARNESS_INCOMPLETE"

_PRODUCER_FORBIDDEN = frozenset(
    {
        "schema_version",
        "status",
        "blockers",
        "freeze_grade_evidence",
        "benchmark_freeze_eligible",
        "benchmark_id",
        "benchmark_revision",
        "authority_origin",
        "authority_role",
        "family_digest",
        "patient_family_digest",
        "assignment_cluster_digest",
        "assignment_cluster_digests",
        "authority_digest",
        "authority_digests",
        "authority_scope_digest",
        "source_unit_digest",
        "source_digest",
        "member_digest",
        "component_digest",
        "assignment_digest",
        "receipt_digest",
        "pair_digest",
        "link_digest",
        "source_member_id",
        "split",
        "record_id",
        "case_key",
        "generator_seed",
        "seed",
        "master_seed",
        "split_seed",
        "latent_seed",
        "noise_seed",
        "acquisition_seed",
        "population_index",
        "episode_index",
        "randomness_transcript",
        "latent_transcript",
        "noise_transcript",
        "acquisition_transcript",
        "owner_role",
        "builder_id",
        "builder_version",
        "builder_run_id",
        "registry_digest",
        "generator_bundle_digest",
        "topology_contract_digest",
        "query_contract_digest",
        "split_policy_digest",
        "split_seed_commitment",
        "split_weight_totals",
        "pre_split_source",
        "assignments",
        "connected_components",
        "materialization_receipts",
        "materialization_slots",
        "materialization_slot_digest",
        "slot_digest",
        "cut_digest",
        "stage_label",
        "materialization_role",
        "pair_alias",
        "pair_side",
        "atomic_link_alias",
        "atomic_link_digest",
        "row_bundle_commitment_digest",
        "member_coverage",
        "ledger_digest",
        "evidence_digest",
        "family_identity",
        "randomness_identity",
        "input_digest",
        "row_join",
        "row_count",
        "total_weight",
        "units",
        "pair_topology",
        "atomic_links",
        "public_history_digest",
        "hidden_state_at_cut_digest",
        "query_cell_digest",
        "oracle_target_digest",
        "candidate_row_digest",
        "judge_row_digest",
        "raw_request_digest",
        "raw_response_digest",
    }
)


# A dataclass ``__post_init__`` method is an ordinary public Python method.
# Keeping the only initialization marker on the object would therefore let a
# hostile in-process caller delete that marker and invoke ``__post_init__`` to
# bless rewritten state.  Track first initialization by object identity outside
# the artifact as well.  Weak references avoid retaining completed artifacts or
# confusing a later object which reuses the same CPython id.
_SEALED_OBJECT_REFS: dict[int, ReferenceType[Any]] = {}
_SEALED_OBJECT_REFS_LOCK = RLock()


def _seal_or_validate_once(
    value: object,
    *,
    seal_attribute: str,
    expected_digest: str,
    allow_initialization: bool,
    missing_message: str,
    changed_message: str,
) -> None:
    _digest(expected_digest, f"{seal_attribute} expected digest")
    object_id = id(value)
    with _SEALED_OBJECT_REFS_LOCK:
        existing_reference = _SEALED_OBJECT_REFS.get(object_id)
        was_initialized = (
            existing_reference is not None and existing_reference() is value
        )
        try:
            sealed_digest = object.__getattribute__(value, seal_attribute)
        except AttributeError:
            if not allow_initialization or was_initialized:
                raise ProtocolViolation(missing_message)
            object.__setattr__(value, seal_attribute, expected_digest)

            def discard(dead_reference: ReferenceType[Any]) -> None:
                with _SEALED_OBJECT_REFS_LOCK:
                    if _SEALED_OBJECT_REFS.get(object_id) is dead_reference:
                        del _SEALED_OBJECT_REFS[object_id]

            _SEALED_OBJECT_REFS[object_id] = ref(value, discard)
            return
        if sealed_digest != expected_digest:
            raise ProtocolViolation(changed_message)
        if not was_initialized:
            # This covers reconstruction mechanisms which restore an init=False
            # field before invoking ``__post_init__``.  The exact digest has
            # already been re-derived above, so registering it is safe.
            def discard(dead_reference: ReferenceType[Any]) -> None:
                with _SEALED_OBJECT_REFS_LOCK:
                    if _SEALED_OBJECT_REFS.get(object_id) is dead_reference:
                        del _SEALED_OBJECT_REFS[object_id]

            _SEALED_OBJECT_REFS[object_id] = ref(value, discard)


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    return value


def _tuple_of_exact(
    value: object,
    item_type: type,
    label: str,
    *,
    non_empty: bool = False,
) -> tuple[Any, ...]:
    if type(value) is not tuple or any(type(item) is not item_type for item in value):
        raise ProtocolViolation(f"{label} must be tuple[{item_type.__name__}, ...]")
    if non_empty and not value:
        raise ProtocolViolation(f"{label} must not be empty")
    return value


def _safe_payload(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact JSON object")
    validate_json_like(value, path=label)
    reject_privileged_keys(value, forbidden=_PRODUCER_FORBIDDEN, path=label)
    # Round-trip through canonical bytes is intentionally unnecessary here:
    # validate_json_like already excludes mutable/custom serializer behavior,
    # and digest_json below binds the exact inert value.
    return value


def _exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ProtocolViolation(
            f"{label} keys do not match schema; missing={missing}, extra={extra}"
        )


def _sorted_wire(values: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        item.to_wire()
        for item in sorted(values, key=lambda item: canonical_json_bytes(item.to_wire()))
    ]


def compute_row_bundle_commitment(
    *,
    record_id: str,
    public_history_digest: str,
    hidden_state_at_cut_digest: str,
    oracle_target_digest: str,
    candidate_row_digest: str,
    judge_row_digest: str,
    raw_request_digest: str,
    raw_response_digest: str,
) -> str:
    """Commit one materialized row's payload before split assignment.

    Split, source-member, cut, query and topology joins are deliberately not
    repeated here: they are builder-owned fields in :class:`MaterializationSlot`.
    The commitment binds the row-specific payload which otherwise could be
    swapped wholesale between two valid slots while preserving caller-reported
    join metadata.
    """

    _name(record_id, "row bundle record_id")
    for value, label in (
        (public_history_digest, "row bundle public_history_digest"),
        (hidden_state_at_cut_digest, "row bundle hidden_state_at_cut_digest"),
        (oracle_target_digest, "row bundle oracle_target_digest"),
        (candidate_row_digest, "row bundle candidate_row_digest"),
        (judge_row_digest, "row bundle judge_row_digest"),
        (raw_request_digest, "row bundle raw_request_digest"),
        (raw_response_digest, "row bundle raw_response_digest"),
    ):
        _digest(value, label)
    return digest_json(
        {
            "schema_version": ROW_BUNDLE_PROTOCOL,
            "record_id": record_id,
            "public_history_digest": public_history_digest,
            "hidden_state_at_cut_digest": hidden_state_at_cut_digest,
            "oracle_target_digest": oracle_target_digest,
            "candidate_row_digest": candidate_row_digest,
            "judge_row_digest": judge_row_digest,
            "raw_request_digest": raw_request_digest,
            "raw_response_digest": raw_response_digest,
        }
    )


class FamilyScaffoldStatus(str, Enum):
    PRE_FREEZE_SCAFFOLD = "pre_freeze_scaffold"
    INCOMPLETE = "incomplete"


class SourceUnitSemantic(str, Enum):
    PATIENT_FAMILY = "patient_family"


class SourceMemberSemantic(str, Enum):
    PATIENT_TRAJECTORY = "patient_trajectory"
    COUNTERFACTUAL_VARIANT = "counterfactual_variant"
    PROBE_VARIANT = "probe_variant"
    RELEASE_STAGE = "release_stage"
    W19_ASSIGNMENT_ROW = "w19_assignment_row"


class PairSemantic(str, Enum):
    COUNTERFACTUAL = "counterfactual_pair"
    BEHAVIORAL = "behavior_pair"
    RESPONSE_REVERSAL = "response_reversal_pair"


class AtomicLinkSemantic(str, Enum):
    CUT_SET = "cut_set"
    RELEASE_S0_S1 = "release_s0_s1"
    QUOTA_CLUSTER = "quota_cluster"
    SHARED_PROBE_BASE = "shared_probe_base"
    W19_ASSIGNMENT_CLUSTER = "w19_assignment_cluster"


class FamilySplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    SEALED_TEST = "sealed_test"


class MaterializationRole(str, Enum):
    """Code-owned role of one pre-split materialization slot.

    A member may declare zero, one, or many slots.  The role is not inferred
    from the rows that happen to materialize later.
    """

    STANDARD_ROW = "standard_row"
    PAIR_SIDE = "pair_side"
    PROBE_ROW = "probe_row"
    RELEASE_STAGE_ROW = "release_stage_row"
    W19_ASSIGNMENT_ROW = "w19_assignment_row"


def _source_unit_semantic_wire(value: SourceUnitSemantic) -> str:
    if value is SourceUnitSemantic.PATIENT_FAMILY:
        return "patient_family"
    raise ProtocolViolation("source unit semantic enum identity is invalid")


def _source_unit_semantic_from_wire(value: object) -> SourceUnitSemantic:
    if type(value) is str and value == "patient_family":
        return SourceUnitSemantic.PATIENT_FAMILY
    raise ProtocolViolation("producer source unit semantic_type is invalid")


def _source_member_semantic_wire(value: SourceMemberSemantic) -> str:
    mapping = {
        SourceMemberSemantic.PATIENT_TRAJECTORY: "patient_trajectory",
        SourceMemberSemantic.COUNTERFACTUAL_VARIANT: "counterfactual_variant",
        SourceMemberSemantic.PROBE_VARIANT: "probe_variant",
        SourceMemberSemantic.RELEASE_STAGE: "release_stage",
        SourceMemberSemantic.W19_ASSIGNMENT_ROW: "w19_assignment_row",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("source member semantic enum identity is invalid") from exc


def _source_member_semantic_from_wire(value: object) -> SourceMemberSemantic:
    mapping = {
        "patient_trajectory": SourceMemberSemantic.PATIENT_TRAJECTORY,
        "counterfactual_variant": SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
        "probe_variant": SourceMemberSemantic.PROBE_VARIANT,
        "release_stage": SourceMemberSemantic.RELEASE_STAGE,
        "w19_assignment_row": SourceMemberSemantic.W19_ASSIGNMENT_ROW,
    }
    if type(value) is not str or value not in mapping:
        raise ProtocolViolation("producer member semantic_type is invalid")
    return mapping[value]


def _pair_semantic_wire(value: PairSemantic) -> str:
    mapping = {
        PairSemantic.COUNTERFACTUAL: "counterfactual_pair",
        PairSemantic.BEHAVIORAL: "behavior_pair",
        PairSemantic.RESPONSE_REVERSAL: "response_reversal_pair",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("pair semantic enum identity is invalid") from exc


def _atomic_link_semantic_wire(value: AtomicLinkSemantic) -> str:
    mapping = {
        AtomicLinkSemantic.CUT_SET: "cut_set",
        AtomicLinkSemantic.RELEASE_S0_S1: "release_s0_s1",
        AtomicLinkSemantic.QUOTA_CLUSTER: "quota_cluster",
        AtomicLinkSemantic.SHARED_PROBE_BASE: "shared_probe_base",
        AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER: "w19_assignment_cluster",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("atomic link semantic enum identity is invalid") from exc


def _family_split_wire(value: FamilySplit) -> str:
    mapping = {
        FamilySplit.TRAIN: "train",
        FamilySplit.VALIDATION: "validation",
        FamilySplit.SEALED_TEST: "sealed_test",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("family split enum identity is invalid") from exc


def _family_split_from_wire(value: object) -> FamilySplit:
    mapping = {
        "train": FamilySplit.TRAIN,
        "validation": FamilySplit.VALIDATION,
        "sealed_test": FamilySplit.SEALED_TEST,
    }
    if type(value) is not str or value not in mapping:
        raise ProtocolViolation("row materialization split is invalid")
    return mapping[value]


def _materialization_role_wire(value: MaterializationRole) -> str:
    mapping = {
        MaterializationRole.STANDARD_ROW: "standard_row",
        MaterializationRole.PAIR_SIDE: "pair_side",
        MaterializationRole.PROBE_ROW: "probe_row",
        MaterializationRole.RELEASE_STAGE_ROW: "release_stage_row",
        MaterializationRole.W19_ASSIGNMENT_ROW: "w19_assignment_row",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("materialization role enum identity is invalid") from exc


def _materialization_role_from_wire(value: object) -> MaterializationRole:
    mapping = {
        "standard_row": MaterializationRole.STANDARD_ROW,
        "pair_side": MaterializationRole.PAIR_SIDE,
        "probe_row": MaterializationRole.PROBE_ROW,
        "release_stage_row": MaterializationRole.RELEASE_STAGE_ROW,
        "w19_assignment_row": MaterializationRole.W19_ASSIGNMENT_ROW,
    }
    if type(value) is not str or value not in mapping:
        raise ProtocolViolation("row materialization role is invalid")
    return mapping[value]


@dataclass(frozen=True, slots=True)
class ScaffoldBlocker:
    code: str
    artifact: str
    detail: str

    def __post_init__(self) -> None:
        _name(self.code, "blocker code")
        _name(self.artifact, "blocker artifact")
        _name(self.detail, "blocker detail")

    def to_wire(self) -> dict[str, str]:
        self.__post_init__()
        return {"code": self.code, "artifact": self.artifact, "detail": self.detail}


_SOURCE_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "pre_split_family_source",
    "builder custody, independent runtime sealing, and atomic publication are not yet available",
)
_ASSIGNMENT_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "family_split_assignments",
    "weighted atomic assignments are structurally checked but not independently sealed",
)
_RECEIPT_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "family_materialization_receipt",
    "exact joins are structurally checked but the materializer and raw ledger are not independently sealed",
)
_EVIDENCE_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "row_materialization_evidence",
    "row evidence is structurally bound but builder custody and the raw ledger are not independently sealed",
)
_LEDGER_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "family_materialization_ledger",
    "closed slot coverage is structurally checked but builder custody and the raw "
    "ledger are not independently sealed",
)


def _code_owned_blocker_wire(kind: str) -> dict[str, str]:
    """Return one canonical blocker without trusting mutable singleton state."""

    if kind == "source":
        artifact = "pre_split_family_source"
        detail = (
            "builder custody, independent runtime sealing, and atomic publication "
            "are not yet available"
        )
    elif kind == "assignment":
        artifact = "family_split_assignments"
        detail = (
            "weighted atomic assignments are structurally checked but not "
            "independently sealed"
        )
    elif kind == "evidence":
        artifact = "row_materialization_evidence"
        detail = (
            "row evidence is structurally bound but builder custody and the raw "
            "ledger are not independently sealed"
        )
    elif kind == "receipt":
        artifact = "family_materialization_receipt"
        detail = (
            "exact joins are structurally checked but the materializer and raw "
            "ledger are not independently sealed"
        )
    elif kind == "ledger":
        artifact = "family_materialization_ledger"
        detail = (
            "closed slot coverage is structurally checked but builder custody and "
            "the raw ledger are not independently sealed"
        )
    else:  # pragma: no cover - every caller below uses one code-owned literal.
        raise ProtocolViolation("unknown code-owned family scaffold blocker")
    return ScaffoldBlocker(
        "UCM-E003-HARNESS_INCOMPLETE",
        artifact,
        detail,
    ).to_wire()


@dataclass(frozen=True, slots=True)
class SourceMemberDraft:
    """Producer semantic input.  It contains no row or family authority fields."""

    member_alias: str
    semantic_type: SourceMemberSemantic
    semantic_payload: dict[str, Any]

    def __post_init__(self) -> None:
        _name(self.member_alias, "member_alias")
        if type(self.semantic_type) is not SourceMemberSemantic:
            raise ProtocolViolation("member semantic_type must be SourceMemberSemantic")
        _safe_payload(self.semantic_payload, "member semantic_payload")

    @classmethod
    def from_wire(cls, value: object) -> "SourceMemberDraft":
        row = _safe_payload(value, "producer member draft")
        _exact_keys(
            row,
            frozenset({"member_alias", "semantic_type", "semantic_payload"}),
            "producer member draft",
        )
        semantic_type = _source_member_semantic_from_wire(row["semantic_type"])
        return cls(
            member_alias=row["member_alias"],
            semantic_type=semantic_type,
            semantic_payload=row["semantic_payload"],
        )

    def authority_payload(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "member_alias": self.member_alias,
            "semantic_type": _source_member_semantic_wire(self.semantic_type),
            "semantic_payload": self.semantic_payload,
        }

    def identity_payload(self) -> dict[str, Any]:
        """Return alias-neutral member semantics for family identity."""

        self.__post_init__()
        return {
            "semantic_type": _source_member_semantic_wire(self.semantic_type),
            "semantic_payload": self.semantic_payload,
        }


@dataclass(frozen=True, slots=True)
class ProducerSourceUnitDraft:
    """A pre-split producer draft; its digest is deliberately not an input."""

    unit_alias: str
    world_slot: str
    semantic_type: SourceUnitSemantic
    recipe_payload: dict[str, Any]
    weight: int
    members: tuple[SourceMemberDraft, ...]

    def __post_init__(self) -> None:
        _name(self.unit_alias, "unit_alias")
        _name(self.world_slot, "world_slot")
        if type(self.semantic_type) is not SourceUnitSemantic:
            raise ProtocolViolation("unit semantic_type must be SourceUnitSemantic")
        _safe_payload(self.recipe_payload, "unit recipe_payload")
        if type(self.weight) is not int or self.weight <= 0:
            raise ProtocolViolation("unit weight must be a positive integer")
        _tuple_of_exact(self.members, SourceMemberDraft, "unit members", non_empty=True)
        aliases = [member.member_alias for member in self.members]
        if len(aliases) != len(set(aliases)):
            raise ProtocolViolation("unit member aliases must be unique")

        w19_rows = [
            member
            for member in self.members
            if member.semantic_type is SourceMemberSemantic.W19_ASSIGNMENT_ROW
        ]
        if w19_rows and self.world_slot != "W19":
            raise ProtocolViolation("W19 assignment rows may only belong to W19 families")
        if len(w19_rows) > 1:
            raise ProtocolViolation(
                "one W19 patient family may declare only one assignment row"
            )
        if w19_rows and self.weight != 1:
            raise ProtocolViolation("W19 assignment-row patient family weight must be 1")

    @classmethod
    def from_wire(cls, value: object) -> "ProducerSourceUnitDraft":
        row = _safe_payload(value, "producer source unit draft")
        _exact_keys(
            row,
            frozenset(
                {
                    "unit_alias",
                    "world_slot",
                    "semantic_type",
                    "recipe_payload",
                    "weight",
                    "members",
                }
            ),
            "producer source unit draft",
        )
        if type(row["members"]) is not list:
            raise ProtocolViolation("producer source unit members must be a list")
        semantic_type = _source_unit_semantic_from_wire(row["semantic_type"])
        return cls(
            unit_alias=row["unit_alias"],
            world_slot=row["world_slot"],
            semantic_type=semantic_type,
            recipe_payload=row["recipe_payload"],
            weight=row["weight"],
            members=tuple(SourceMemberDraft.from_wire(item) for item in row["members"]),
        )

    def authority_payload(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "unit_alias": self.unit_alias,
            "world_slot": self.world_slot,
            "semantic_type": _source_unit_semantic_wire(self.semantic_type),
            "recipe_payload": self.recipe_payload,
            "weight": self.weight,
            "members": [
                item.authority_payload()
                for item in sorted(self.members, key=lambda item: item.member_alias)
            ],
        }

    def identity_payload(self) -> dict[str, Any]:
        """Return the family identity without local aliases or run metadata."""

        self.__post_init__()
        members = [item.identity_payload() for item in self.members]
        members.sort(key=canonical_json_bytes)
        member_bytes = [canonical_json_bytes(item) for item in members]
        if len(member_bytes) != len(set(member_bytes)):
            raise ProtocolViolation(
                "one family cannot contain duplicate semantic members hidden by aliases"
            )
        return {
            "world_slot": self.world_slot,
            "semantic_type": _source_unit_semantic_wire(self.semantic_type),
            "recipe_payload": self.recipe_payload,
            "members": members,
        }


@dataclass(frozen=True, slots=True)
class BuilderRandomnessTranscript:
    """Randomness evidence supplied on the authority-builder side of the API."""

    unit_alias: str
    builder_id: str
    builder_run_id: str
    latent_transcript: dict[str, Any]
    noise_transcript: dict[str, Any]
    acquisition_transcript: dict[str, Any]

    def __post_init__(self) -> None:
        _name(self.unit_alias, "transcript unit_alias")
        _name(self.builder_id, "transcript builder_id")
        _name(self.builder_run_id, "transcript builder_run_id")
        _safe_payload(self.latent_transcript, "latent transcript")
        _safe_payload(self.noise_transcript, "noise transcript")
        _safe_payload(self.acquisition_transcript, "acquisition transcript")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        body = {
            "owner_role": "authority_builder",
            "unit_alias": self.unit_alias,
            "builder_id": self.builder_id,
            "builder_run_id": self.builder_run_id,
            "latent_transcript": self.latent_transcript,
            "noise_transcript": self.noise_transcript,
            "acquisition_transcript": self.acquisition_transcript,
        }
        validate_json_like(body)
        return body

    def identity_payload(self) -> dict[str, Any]:
        """Return only builder-owned randomness, excluding run provenance."""

        self.__post_init__()
        return {
            "latent_transcript": self.latent_transcript,
            "noise_transcript": self.noise_transcript,
            "acquisition_transcript": self.acquisition_transcript,
        }


@dataclass(frozen=True, slots=True)
class SourceMember:
    member_alias: str
    semantic_type: SourceMemberSemantic
    semantic_payload: dict[str, Any]
    member_digest: str

    def __post_init__(self) -> None:
        _name(self.member_alias, "source member_alias")
        if type(self.semantic_type) is not SourceMemberSemantic:
            raise ProtocolViolation("source member semantic_type is invalid")
        _safe_payload(self.semantic_payload, "source member semantic_payload")
        _digest(self.member_digest, "source member_digest")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "member_alias": self.member_alias,
            "semantic_type": _source_member_semantic_wire(self.semantic_type),
            "semantic_payload": self.semantic_payload,
            "member_digest": self.member_digest,
        }

    def identity_payload(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "semantic_type": _source_member_semantic_wire(self.semantic_type),
            "semantic_payload": self.semantic_payload,
        }


@dataclass(frozen=True, slots=True)
class PreSplitSourceUnit:
    unit_alias: str
    world_slot: str
    semantic_type: SourceUnitSemantic
    recipe_payload: dict[str, Any]
    weight: int
    authority_scope_digest: str
    randomness_transcript: BuilderRandomnessTranscript
    members: tuple[SourceMember, ...]
    authority_digest: str

    def __post_init__(self) -> None:
        _name(self.unit_alias, "source unit_alias")
        _name(self.world_slot, "source world_slot")
        if type(self.semantic_type) is not SourceUnitSemantic:
            raise ProtocolViolation("source unit semantic_type is invalid")
        _safe_payload(self.recipe_payload, "source recipe_payload")
        if type(self.weight) is not int or self.weight <= 0:
            raise ProtocolViolation("source unit weight must be positive")
        _digest(self.authority_scope_digest, "source authority_scope_digest")
        if type(self.randomness_transcript) is not BuilderRandomnessTranscript:
            raise ProtocolViolation("source unit transcript has wrong type")
        _tuple_of_exact(self.members, SourceMember, "source unit members", non_empty=True)
        _digest(self.authority_digest, "source authority_digest")
        if self.randomness_transcript.unit_alias != self.unit_alias:
            raise ProtocolViolation("source unit/transcript alias mismatch")
        member_aliases = [item.member_alias for item in self.members]
        if len(member_aliases) != len(set(member_aliases)):
            raise ProtocolViolation("source unit member aliases must be unique")
        member_digests = [item.member_digest for item in self.members]
        if len(member_digests) != len(set(member_digests)):
            raise ProtocolViolation(
                "source unit semantic members must remain unique under alpha-renaming"
            )
        w19_rows = [
            member
            for member in self.members
            if member.semantic_type is SourceMemberSemantic.W19_ASSIGNMENT_ROW
        ]
        if w19_rows and self.world_slot != "W19":
            raise ProtocolViolation("resolved W19 assignment row is outside W19")
        if len(w19_rows) > 1:
            raise ProtocolViolation(
                "resolved W19 patient family has multiple assignment rows"
            )
        if w19_rows and self.weight != 1:
            raise ProtocolViolation("resolved W19 assignment-row family weight must be 1")

        authority_payload = {
            "schema_version": "ucm-pre-split-source-unit-authority/2",
            "authority_scope_digest": self.authority_scope_digest,
            "family_identity": {
                "world_slot": self.world_slot,
                "semantic_type": _source_unit_semantic_wire(self.semantic_type),
                "recipe_payload": self.recipe_payload,
                "members": [
                    item.identity_payload()
                    for item in sorted(
                        self.members,
                        key=lambda item: canonical_json_bytes(item.identity_payload()),
                    )
                ],
            },
            "randomness_identity": self.randomness_transcript.identity_payload(),
        }
        expected_authority_digest = domain_digest(
            b"UCM\0PRE_SPLIT_SOURCE_UNIT_V2\0",
            (canonical_json_bytes(authority_payload),),
        )
        if self.authority_digest != expected_authority_digest:
            raise ProtocolViolation("source authority_digest is not builder-derived")
        for member in self.members:
            expected_member_digest = domain_digest(
                b"UCM\0PRE_SPLIT_SOURCE_MEMBER_V2\0",
                (
                    self.authority_digest.encode("ascii"),
                    canonical_json_bytes(member.identity_payload()),
                ),
            )
            if member.member_digest != expected_member_digest:
                raise ProtocolViolation("source member_digest is not builder-derived")

    @property
    def family_digest(self) -> str | None:
        if self.semantic_type is SourceUnitSemantic.PATIENT_FAMILY:
            return self.authority_digest
        return None

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "unit_alias": self.unit_alias,
            "world_slot": self.world_slot,
            "semantic_type": _source_unit_semantic_wire(self.semantic_type),
            "recipe_payload": self.recipe_payload,
            "weight": self.weight,
            "authority_scope_digest": self.authority_scope_digest,
            "randomness_transcript": self.randomness_transcript.to_wire(),
            "members": _sorted_wire(self.members),
            "authority_digest": self.authority_digest,
            # W19 assignment clusters are separate AtomicLink authorities,
            # never source units, so every row retains its patient family.
            "family_digest": self.family_digest,
        }

    def member_by_digest(self, member_digest: str) -> SourceMember | None:
        return next(
            (item for item in self.members if item.member_digest == member_digest),
            None,
        )


@dataclass(frozen=True, slots=True)
class MemberRefDraft:
    unit_alias: str
    member_alias: str

    def __post_init__(self) -> None:
        _name(self.unit_alias, "member reference unit_alias")
        _name(self.member_alias, "member reference member_alias")


@dataclass(frozen=True, slots=True)
class PairSideDraft:
    unit_alias: str
    member_alias: str
    side: int

    def __post_init__(self) -> None:
        _name(self.unit_alias, "pair side unit_alias")
        _name(self.member_alias, "pair side member_alias")
        if type(self.side) is not int or self.side not in {0, 1}:
            raise ProtocolViolation("pair side must be exact integer 0 or 1")


@dataclass(frozen=True, slots=True)
class PairConstraintDraft:
    pair_alias: str
    semantic_type: PairSemantic
    sides: tuple[PairSideDraft, ...]

    def __post_init__(self) -> None:
        _name(self.pair_alias, "pair_alias")
        if type(self.semantic_type) is not PairSemantic:
            raise ProtocolViolation("pair semantic_type must be PairSemantic")
        _tuple_of_exact(self.sides, PairSideDraft, "pair sides")
        if len(self.sides) != 2 or {side.side for side in self.sides} != {0, 1}:
            raise ProtocolViolation("pair topology requires exactly sides 0 and 1")
        refs = [(side.unit_alias, side.member_alias) for side in self.sides]
        if len(refs) != len(set(refs)):
            raise ProtocolViolation("pair sides must reference two distinct members")
        if len({side.unit_alias for side in self.sides}) != 1:
            raise ProtocolViolation("pair sides must belong to the same pre-split family")


@dataclass(frozen=True, slots=True)
class AtomicLinkDraft:
    link_alias: str
    semantic_type: AtomicLinkSemantic
    members: tuple[MemberRefDraft, ...]

    def __post_init__(self) -> None:
        _name(self.link_alias, "atomic link_alias")
        if type(self.semantic_type) is not AtomicLinkSemantic:
            raise ProtocolViolation("atomic link semantic_type is invalid")
        _tuple_of_exact(self.members, MemberRefDraft, "atomic link members")
        refs = [(item.unit_alias, item.member_alias) for item in self.members]
        if len(refs) < 2:
            raise ProtocolViolation("atomic link requires at least two members")
        if len(refs) != len(set(refs)):
            raise ProtocolViolation("atomic link member references must be unique")


@dataclass(frozen=True, slots=True)
class SourceMemberRef:
    authority_digest: str
    member_digest: str

    def __post_init__(self) -> None:
        _digest(self.authority_digest, "member ref authority_digest")
        _digest(self.member_digest, "member ref member_digest")

    def to_wire(self) -> dict[str, str]:
        self.__post_init__()
        return {
            "authority_digest": self.authority_digest,
            "member_digest": self.member_digest,
        }


@dataclass(frozen=True, slots=True)
class PairSide:
    reference: SourceMemberRef
    side: int

    def __post_init__(self) -> None:
        if type(self.reference) is not SourceMemberRef:
            raise ProtocolViolation("resolved pair reference has wrong type")
        if type(self.side) is not int or self.side not in {0, 1}:
            raise ProtocolViolation("resolved pair side must be 0 or 1")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {"side": self.side, "reference": self.reference.to_wire()}


@dataclass(frozen=True, slots=True)
class PairConstraint:
    pair_alias: str
    semantic_type: PairSemantic
    sides: tuple[PairSide, ...]

    def __post_init__(self) -> None:
        _name(self.pair_alias, "resolved pair_alias")
        if type(self.semantic_type) is not PairSemantic:
            raise ProtocolViolation("resolved pair semantic_type is invalid")
        _tuple_of_exact(self.sides, PairSide, "resolved pair sides")
        if len(self.sides) != 2 or {item.side for item in self.sides} != {0, 1}:
            raise ProtocolViolation("resolved pair requires exactly sides 0 and 1")
        refs = [
            (item.reference.authority_digest, item.reference.member_digest)
            for item in self.sides
        ]
        if len(refs) != len(set(refs)):
            raise ProtocolViolation("resolved pair members must be distinct")
        if len({item.reference.authority_digest for item in self.sides}) != 1:
            raise ProtocolViolation("resolved pair sides do not share one family authority")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "pair_alias": self.pair_alias,
            "semantic_type": _pair_semantic_wire(self.semantic_type),
            "sides": _sorted_wire(self.sides),
            "pair_digest": self.pair_digest,
        }

    @property
    def pair_digest(self) -> str:
        self.__post_init__()
        return domain_digest(
            b"UCM\0PRE_SPLIT_PAIR_V1\0",
            (
                canonical_json_bytes(
                    {
                        "semantic_type": _pair_semantic_wire(self.semantic_type),
                        "sides": _sorted_wire(self.sides),
                    }
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class MaterializationSlotDraft:
    """Builder-side declaration of one row slot before split assignment.

    This is deliberately separate from :class:`SourceMemberDraft`: producers
    describe clinical semantics, while the authority builder owns the closed
    inventory of stage/cut/query joins.  Multiple slots may reference the same
    source member, and a member may have no slots.
    """

    slot_alias: str
    unit_alias: str
    member_alias: str
    materialization_role: MaterializationRole
    stage_label: str
    cut_digest: str
    query_cell_digest: str
    pair_alias: str | None = None
    pair_side: int | None = None
    atomic_link_alias: str | None = field(default=None, kw_only=True)
    row_bundle_commitment_digest: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        _name(self.slot_alias, "materialization slot_alias")
        _name(self.unit_alias, "materialization slot unit_alias")
        _name(self.member_alias, "materialization slot member_alias")
        if type(self.materialization_role) is not MaterializationRole:
            raise ProtocolViolation("materialization slot role has wrong type")
        _name(self.stage_label, "materialization stage_label")
        _digest(self.cut_digest, "materialization cut_digest")
        _digest(self.query_cell_digest, "materialization query_cell_digest")
        if (self.pair_alias is None) != (self.pair_side is None):
            raise ProtocolViolation(
                "materialization pair_alias/pair_side must be declared together"
            )
        if self.pair_alias is not None:
            _name(self.pair_alias, "pair-side materialization pair_alias")
            if type(self.pair_side) is not int or self.pair_side not in {0, 1}:
                raise ProtocolViolation(
                    "pair-side materialization requires exact pair_side 0 or 1"
                )
        elif self.materialization_role is MaterializationRole.PAIR_SIDE:
            raise ProtocolViolation(
                "pair-side materialization role requires pair_alias/pair_side"
            )
        if self.atomic_link_alias is not None:
            _name(self.atomic_link_alias, "materialization atomic_link_alias")
        if self.row_bundle_commitment_digest is None:
            raise ProtocolViolation(
                "materialization slot requires a pre-split row bundle commitment"
            )
        _digest(
            self.row_bundle_commitment_digest,
            "materialization row_bundle_commitment_digest",
        )


@dataclass(frozen=True, slots=True)
class MaterializationSlot:
    """Resolved pre-split slot bound to source and pair authority."""

    slot_alias: str
    reference: SourceMemberRef
    materialization_role: MaterializationRole
    stage_label: str
    cut_digest: str
    query_cell_digest: str
    pair_digest: str | None
    pair_side: int | None
    atomic_link_digest: str | None
    row_bundle_commitment_digest: str
    slot_digest: str

    def __post_init__(self) -> None:
        _name(self.slot_alias, "resolved materialization slot_alias")
        if type(self.reference) is not SourceMemberRef:
            raise ProtocolViolation("resolved materialization reference has wrong type")
        self.reference.__post_init__()
        if type(self.materialization_role) is not MaterializationRole:
            raise ProtocolViolation("resolved materialization role has wrong type")
        _name(self.stage_label, "resolved materialization stage_label")
        _digest(self.cut_digest, "resolved materialization cut_digest")
        _digest(self.query_cell_digest, "resolved materialization query_cell_digest")
        if (self.pair_digest is None) != (self.pair_side is None):
            raise ProtocolViolation(
                "resolved pair_digest/pair_side must be declared together"
            )
        if self.pair_digest is not None:
            _digest(self.pair_digest, "resolved pair-side pair_digest")
            if type(self.pair_side) is not int or self.pair_side not in {0, 1}:
                raise ProtocolViolation("resolved pair-side must be exact 0 or 1")
        elif self.materialization_role is MaterializationRole.PAIR_SIDE:
            raise ProtocolViolation(
                "resolved pair-side role requires pair authority"
            )
        if self.atomic_link_digest is not None:
            _digest(
                self.atomic_link_digest,
                "resolved materialization atomic_link_digest",
            )
        _digest(
            self.row_bundle_commitment_digest,
            "resolved materialization row_bundle_commitment_digest",
        )
        _digest(self.slot_digest, "resolved materialization slot_digest")
        expected = domain_digest(
            b"UCM\0PRE_SPLIT_MATERIALIZATION_SLOT_V1\0",
            (canonical_json_bytes(self.identity_payload()),),
        )
        if self.slot_digest != expected:
            raise ProtocolViolation(
                "materialization slot_digest is not builder-derived"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "reference": self.reference.to_wire(),
            "materialization_role": _materialization_role_wire(
                self.materialization_role
            ),
            "stage_label": self.stage_label,
            "cut_digest": self.cut_digest,
            "query_cell_digest": self.query_cell_digest,
            "pair_digest": self.pair_digest,
            "pair_side": self.pair_side,
            "atomic_link_digest": self.atomic_link_digest,
            "row_bundle_commitment_digest": self.row_bundle_commitment_digest,
        }

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "slot_alias": self.slot_alias,
            **self.identity_payload(),
            "slot_digest": self.slot_digest,
        }


@dataclass(frozen=True, slots=True)
class AtomicLink:
    link_alias: str
    semantic_type: AtomicLinkSemantic
    members: tuple[SourceMemberRef, ...]

    def __post_init__(self) -> None:
        _name(self.link_alias, "resolved atomic link_alias")
        if type(self.semantic_type) is not AtomicLinkSemantic:
            raise ProtocolViolation("resolved atomic link semantic_type is invalid")
        _tuple_of_exact(self.members, SourceMemberRef, "resolved atomic members")
        refs = [(item.authority_digest, item.member_digest) for item in self.members]
        if len(refs) < 2 or len(refs) != len(set(refs)):
            raise ProtocolViolation("resolved atomic link members must be unique")

    @property
    def link_digest(self) -> str:
        return domain_digest(
            b"UCM\0ATOMIC_LINK_V2\0",
            (
                canonical_json_bytes(
                    {
                        "semantic_type": _atomic_link_semantic_wire(self.semantic_type),
                        "members": _sorted_wire(self.members),
                    }
                ),
            ),
        )

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "link_alias": self.link_alias,
            "semantic_type": _atomic_link_semantic_wire(self.semantic_type),
            "members": _sorted_wire(self.members),
            "link_digest": self.link_digest,
            "assignment_cluster_digest": (
                self.link_digest
                if self.semantic_type is AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER
                else None
            ),
        }


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PreSplitFamilySource:
    benchmark_id: str
    benchmark_revision: str
    registry_digest: str
    generator_bundle_digest: str
    topology_contract_digest: str
    query_contract_digest: str
    builder_id: str
    builder_version: str
    units: tuple[PreSplitSourceUnit, ...]
    pairs: tuple[PairConstraint, ...]
    atomic_links: tuple[AtomicLink, ...]
    materialization_slots: tuple[MaterializationSlot, ...] = ()
    _sealed_source_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validate(allow_seal_initialization=True)

    def _validate(
        self, *, allow_seal_initialization: bool = False
    ) -> dict[str, Any]:
        _name(self.benchmark_id, "source benchmark_id")
        _name(self.benchmark_revision, "source benchmark_revision")
        for value, label in (
            (self.registry_digest, "source registry_digest"),
            (self.generator_bundle_digest, "source generator_bundle_digest"),
            (self.topology_contract_digest, "source topology_contract_digest"),
            (self.query_contract_digest, "source query_contract_digest"),
        ):
            _digest(value, label)
        _name(self.builder_id, "source builder_id")
        _name(self.builder_version, "source builder_version")
        _tuple_of_exact(self.units, PreSplitSourceUnit, "source units", non_empty=True)
        _tuple_of_exact(self.pairs, PairConstraint, "source pairs")
        _tuple_of_exact(self.atomic_links, AtomicLink, "source atomic_links")
        _tuple_of_exact(
            self.materialization_slots,
            MaterializationSlot,
            "source materialization_slots",
        )
        for unit in self.units:
            unit.__post_init__()
            if unit.authority_scope_digest != self.authority_scope_digest:
                raise ProtocolViolation("source unit authority scope is stale or mismatched")
            if unit.randomness_transcript.builder_id != self.builder_id:
                raise ProtocolViolation(
                    "source unit transcript builder_id does not match source builder"
                )
        for pair in self.pairs:
            pair.__post_init__()
        for link in self.atomic_links:
            link.__post_init__()
        for slot in self.materialization_slots:
            slot.__post_init__()
        for values, label in (
            ([item.unit_alias for item in self.units], "unit aliases"),
            ([item.authority_digest for item in self.units], "unit authority digests"),
            ([item.pair_alias for item in self.pairs], "pair aliases"),
            ([item.link_alias for item in self.atomic_links], "atomic link aliases"),
            (
                [item.slot_alias for item in self.materialization_slots],
                "materialization slot aliases",
            ),
            (
                [item.slot_digest for item in self.materialization_slots],
                "materialization slot digests",
            ),
        ):
            if len(values) != len(set(values)):
                raise ProtocolViolation(f"source {label} must be unique")
        known_member_objects = {
            (unit.authority_digest, member.member_digest): (unit, member)
            for unit in self.units
            for member in unit.members
        }
        known_members = set(known_member_objects)
        referenced = [
            (side.reference.authority_digest, side.reference.member_digest)
            for pair in self.pairs
            for side in pair.sides
        ] + [
            (member.authority_digest, member.member_digest)
            for link in self.atomic_links
            for member in link.members
        ]
        missing = sorted(set(referenced) - known_members)
        if missing:
            raise ProtocolViolation(f"source topology references missing members: {missing}")
        pair_signatures = [
            tuple(
                sorted(
                    (
                        side.reference.authority_digest,
                        side.reference.member_digest,
                        side.side,
                    )
                    for side in pair.sides
                )
            )
            for pair in self.pairs
        ]
        if len(pair_signatures) != len(set(pair_signatures)):
            raise ProtocolViolation("source contains duplicate pair topology")
        link_signatures = [
            (
                _atomic_link_semantic_wire(link.semantic_type),
                tuple(
                    sorted(
                        (member.authority_digest, member.member_digest)
                        for member in link.members
                    )
                ),
            )
            for link in self.atomic_links
        ]
        if len(link_signatures) != len(set(link_signatures)):
            raise ProtocolViolation("source contains duplicate atomic link topology")

        w19_cluster_membership: dict[tuple[str, str], int] = {}
        for link in self.atomic_links:
            if link.semantic_type is not AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER:
                continue
            # Literal rather than a mutable module-level quota: callers cannot
            # monkeypatch the W19 authority down to a toy cluster at runtime.
            if len(link.members) != 64:
                raise ProtocolViolation(
                    "W19 assignment cluster must contain exactly 64 assignment rows"
                )
            family_digests = [member.authority_digest for member in link.members]
            if len(family_digests) != len(set(family_digests)):
                raise ProtocolViolation(
                    "W19 assignment cluster must contain distinct patient families"
                )
            for reference in link.members:
                unit, member = known_member_objects[
                    (reference.authority_digest, reference.member_digest)
                ]
                if (
                    unit.world_slot != "W19"
                    or unit.semantic_type is not SourceUnitSemantic.PATIENT_FAMILY
                    or member.semantic_type is not SourceMemberSemantic.W19_ASSIGNMENT_ROW
                ):
                    raise ProtocolViolation(
                        "W19 assignment cluster may only link typed rows from W19 patient families"
                    )
                key = (reference.authority_digest, reference.member_digest)
                w19_cluster_membership[key] = w19_cluster_membership.get(key, 0) + 1
        expected_w19_rows = {
            key
            for key, (_, member) in known_member_objects.items()
            if member.semantic_type is SourceMemberSemantic.W19_ASSIGNMENT_ROW
        }
        actual_w19_rows = set(w19_cluster_membership)
        if expected_w19_rows != actual_w19_rows:
            missing_rows = sorted(expected_w19_rows - actual_w19_rows)
            extra_rows = sorted(actual_w19_rows - expected_w19_rows)
            raise ProtocolViolation(
                "W19 assignment-row topology is incomplete; "
                f"missing={missing_rows}, extra={extra_rows}"
            )
        if any(count != 1 for count in w19_cluster_membership.values()):
            raise ProtocolViolation(
                "W19 assignment row must belong to exactly one assignment cluster"
            )
        w19_cluster_authorities = [
            frozenset(reference.authority_digest for reference in link.members)
            for link in self.atomic_links
            if link.semantic_type is AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER
        ]
        if w19_cluster_authorities:
            component_by_authority = {
                authority_digest: frozenset(component)
                for component in _connected_components(self)
                for authority_digest in component
            }
            for cluster_authorities in w19_cluster_authorities:
                component = component_by_authority[next(iter(cluster_authorities))]
                if component != cluster_authorities:
                    raise ProtocolViolation(
                        "W19 assignment cluster cannot be bridged to another "
                        "cluster, family, or world"
                    )

        pair_by_digest = {item.pair_digest: item for item in self.pairs}
        link_by_digest = {item.link_digest: item for item in self.atomic_links}
        for link in self.atomic_links:
            member_objects = [
                known_member_objects[
                    (reference.authority_digest, reference.member_digest)
                ][1]
                for reference in link.members
            ]
            if link.semantic_type is AtomicLinkSemantic.RELEASE_S0_S1:
                if len(link.members) != 2 or any(
                    member.semantic_type is not SourceMemberSemantic.RELEASE_STAGE
                    for member in member_objects
                ):
                    raise ProtocolViolation(
                        "release S0/S1 atomic link requires exactly two typed release-stage members"
                    )
            elif link.semantic_type is AtomicLinkSemantic.SHARED_PROBE_BASE:
                if any(
                    member.semantic_type is not SourceMemberSemantic.PROBE_VARIANT
                    for member in member_objects
                ):
                    raise ProtocolViolation(
                        "shared-probe atomic link requires typed probe members"
                    )

        pair_slot_groups: dict[
            tuple[str, str, str, str], list[MaterializationSlot]
        ] = {}
        slots_by_reference: dict[tuple[str, str], list[MaterializationSlot]] = {}
        slots_by_atomic_link: dict[str, list[MaterializationSlot]] = {}
        physical_cell_keys: list[tuple[str, str, str, str]] = []
        for slot in self.materialization_slots:
            key = (slot.reference.authority_digest, slot.reference.member_digest)
            resolved = known_member_objects.get(key)
            if resolved is None:
                raise ProtocolViolation(
                    "materialization slot references an unknown source member"
                )
            unit, member = resolved
            slots_by_reference.setdefault(key, []).append(slot)
            physical_cell_keys.append(
                (
                    slot.reference.authority_digest,
                    slot.reference.member_digest,
                    slot.cut_digest,
                    slot.query_cell_digest,
                )
            )

            required_role = {
                SourceMemberSemantic.PROBE_VARIANT: MaterializationRole.PROBE_ROW,
                SourceMemberSemantic.RELEASE_STAGE: MaterializationRole.RELEASE_STAGE_ROW,
                SourceMemberSemantic.W19_ASSIGNMENT_ROW: MaterializationRole.W19_ASSIGNMENT_ROW,
            }.get(member.semantic_type)
            if required_role is not None and slot.materialization_role is not required_role:
                raise ProtocolViolation(
                    "typed source member must retain its typed materialization role"
                )
            if (
                slot.materialization_role is MaterializationRole.PROBE_ROW
                and member.semantic_type is not SourceMemberSemantic.PROBE_VARIANT
            ):
                raise ProtocolViolation(
                    "probe materialization slot must reference a probe member"
                )
            if (
                slot.materialization_role is MaterializationRole.RELEASE_STAGE_ROW
                and member.semantic_type is not SourceMemberSemantic.RELEASE_STAGE
            ):
                raise ProtocolViolation(
                    "release-stage materialization slot must reference a release-stage member"
                )
            if slot.materialization_role is MaterializationRole.W19_ASSIGNMENT_ROW:
                if (
                    unit.world_slot != "W19"
                    or member.semantic_type
                    is not SourceMemberSemantic.W19_ASSIGNMENT_ROW
                ):
                    raise ProtocolViolation(
                        "W19 materialization slot must reference a typed W19 assignment row"
                    )

            if slot.pair_digest is not None:
                assert slot.pair_side is not None
                pair = pair_by_digest.get(slot.pair_digest)
                if pair is None:
                    raise ProtocolViolation(
                        "pair-side materialization references an unknown pair"
                    )
                expected_sides = {
                    side.side: (
                        side.reference.authority_digest,
                        side.reference.member_digest,
                    )
                    for side in pair.sides
                }
                if expected_sides[slot.pair_side] != key:
                    raise ProtocolViolation(
                        "pair-side materialization member does not match declared pair side"
                    )
                group_key = (
                    slot.pair_digest,
                    slot.stage_label,
                    slot.cut_digest,
                    slot.query_cell_digest,
                )
                pair_slot_groups.setdefault(group_key, []).append(slot)
            if slot.atomic_link_digest is not None:
                link = link_by_digest.get(slot.atomic_link_digest)
                if link is None:
                    raise ProtocolViolation(
                        "materialization slot references an unknown atomic link"
                    )
                link_members = {
                    (reference.authority_digest, reference.member_digest)
                    for reference in link.members
                }
                if key not in link_members:
                    raise ProtocolViolation(
                        "materialization slot member is absent from its atomic link"
                    )
                slots_by_atomic_link.setdefault(slot.atomic_link_digest, []).append(slot)

        if len(physical_cell_keys) != len(set(physical_cell_keys)):
            raise ProtocolViolation(
                "closed materialization inventory contains duplicate physical cells"
            )
        for slots in pair_slot_groups.values():
            sides = [item.pair_side for item in slots]
            if len(slots) != 2 or set(sides) != {0, 1}:
                raise ProtocolViolation(
                    "pair materialization group must declare exactly sides 0 and 1"
                )
        if self.materialization_slots and expected_w19_rows:
            invalid_w19_rows: list[tuple[tuple[str, str], int]] = []
            for reference in sorted(expected_w19_rows):
                matching = slots_by_reference.get(reference, [])
                if (
                    len(matching) != 1
                    or matching[0].materialization_role
                    is not MaterializationRole.W19_ASSIGNMENT_ROW
                    or matching[0].atomic_link_digest is None
                    or link_by_digest[matching[0].atomic_link_digest].semantic_type
                    is not AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER
                ):
                    invalid_w19_rows.append((reference, len(matching)))
            if invalid_w19_rows:
                raise ProtocolViolation(
                    "closed W19 materialization inventory requires exactly one slot "
                    "with the typed, cluster-bound role per assignment row; "
                    f"invalid={invalid_w19_rows}"
                )
        if self.materialization_slots:
            declared_pair_digests = {key[0] for key in pair_slot_groups}
            missing_pairs = sorted(set(pair_by_digest) - declared_pair_digests)
            if missing_pairs:
                raise ProtocolViolation(
                    "closed materialization inventory omits declared pair topology; "
                    f"missing={missing_pairs}"
                )

            for link in self.atomic_links:
                if link.semantic_type not in {
                    AtomicLinkSemantic.RELEASE_S0_S1,
                    AtomicLinkSemantic.SHARED_PROBE_BASE,
                    AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER,
                }:
                    continue
                declared_members = {
                    (
                        slot.reference.authority_digest,
                        slot.reference.member_digest,
                    )
                    for slot in slots_by_atomic_link.get(link.link_digest, [])
                }
                required_members = {
                    (reference.authority_digest, reference.member_digest)
                    for reference in link.members
                }
                if declared_members != required_members:
                    raise ProtocolViolation(
                        "closed materialization inventory does not exactly cover "
                        f"atomic link {link.link_alias!r}"
                    )

        body = self._body_unchecked()
        expected_digest = digest_json(body)
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_source_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="pre-split family source seal is missing",
            changed_message="pre-split family source changed after construction",
        )
        return body

    def _body_unchecked(self) -> dict[str, Any]:
        body = {
            "schema_version": SOURCE_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_role": "builder_derived_unsealed",
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "registry_digest": self.registry_digest,
            "generator_bundle_digest": self.generator_bundle_digest,
            "topology_contract_digest": self.topology_contract_digest,
            "query_contract_digest": self.query_contract_digest,
            "authority_scope_digest": self.authority_scope_digest,
            "builder_id": self.builder_id,
            "builder_version": self.builder_version,
            "units": _sorted_wire(self.units),
            "pair_topology": _sorted_wire(self.pairs),
            "atomic_links": _sorted_wire(self.atomic_links),
            "materialization_slots": _sorted_wire(self.materialization_slots),
            "blockers": [_code_owned_blocker_wire("source")],
        }
        validate_json_like(body)
        return body

    def _body(self) -> dict[str, Any]:
        return self._validate()

    @property
    def source_digest(self) -> str:
        self._validate()
        return self._sealed_source_digest

    @property
    def authority_scope_digest(self) -> str:
        return digest_json(
            {
                "schema_version": "ucm-family-authority-scope/2",
                "benchmark_id": self.benchmark_id,
                "benchmark_revision": self.benchmark_revision,
                "registry_digest": self.registry_digest,
                "generator_bundle_digest": self.generator_bundle_digest,
                "topology_contract_digest": self.topology_contract_digest,
                "query_contract_digest": self.query_contract_digest,
                "builder_id": self.builder_id,
                "builder_version": self.builder_version,
            }
        )

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["source_digest"] = self._sealed_source_digest
        return body

    def unit_by_digest(self, authority_digest: str) -> PreSplitSourceUnit | None:
        self._validate()
        return next(
            (item for item in self.units if item.authority_digest == authority_digest),
            None,
        )

    def materialization_slot_by_digest(
        self, slot_digest: str
    ) -> MaterializationSlot | None:
        self._validate()
        return next(
            (
                item
                for item in self.materialization_slots
                if item.slot_digest == slot_digest
            ),
            None,
        )


def _build_unit(
    draft: ProducerSourceUnitDraft,
    transcript: BuilderRandomnessTranscript,
    authority_scope_digest: str,
) -> PreSplitSourceUnit:
    if transcript.unit_alias != draft.unit_alias:
        raise ProtocolViolation("draft/transcript aliases do not match")
    authority_body = {
        "schema_version": "ucm-pre-split-source-unit-authority/2",
        "authority_scope_digest": authority_scope_digest,
        "family_identity": draft.identity_payload(),
        "randomness_identity": transcript.identity_payload(),
    }
    authority_digest = domain_digest(
        b"UCM\0PRE_SPLIT_SOURCE_UNIT_V2\0",
        (canonical_json_bytes(authority_body),),
    )
    members = tuple(
        SourceMember(
            member_alias=member.member_alias,
            semantic_type=member.semantic_type,
            semantic_payload=member.semantic_payload,
            member_digest=domain_digest(
                b"UCM\0PRE_SPLIT_SOURCE_MEMBER_V2\0",
                (
                    authority_digest.encode("ascii"),
                    canonical_json_bytes(member.identity_payload()),
                ),
            ),
        )
        for member in draft.members
    )
    return PreSplitSourceUnit(
        unit_alias=draft.unit_alias,
        world_slot=draft.world_slot,
        semantic_type=draft.semantic_type,
        recipe_payload=draft.recipe_payload,
        weight=draft.weight,
        authority_scope_digest=authority_scope_digest,
        randomness_transcript=transcript,
        members=members,
        authority_digest=authority_digest,
    )


def build_pre_split_family_source(
    *,
    benchmark_id: str,
    benchmark_revision: str,
    registry_digest: str,
    generator_bundle_digest: str,
    topology_contract_digest: str,
    query_contract_digest: str,
    builder_id: str,
    builder_version: str,
    drafts: tuple[ProducerSourceUnitDraft, ...],
    transcripts: tuple[BuilderRandomnessTranscript, ...],
    pair_topology: tuple[PairConstraintDraft, ...] = (),
    atomic_links: tuple[AtomicLinkDraft, ...] = (),
    materialization_slots: tuple[MaterializationSlotDraft, ...] = (),
) -> PreSplitFamilySource:
    """Validate producer/builder separation and derive the pre-split source."""

    _name(benchmark_id, "benchmark_id")
    _name(benchmark_revision, "benchmark_revision")
    for value, label in (
        (registry_digest, "registry_digest"),
        (generator_bundle_digest, "generator_bundle_digest"),
        (topology_contract_digest, "topology_contract_digest"),
        (query_contract_digest, "query_contract_digest"),
    ):
        _digest(value, label)
    _name(builder_id, "builder_id")
    _name(builder_version, "builder_version")
    _tuple_of_exact(drafts, ProducerSourceUnitDraft, "drafts", non_empty=True)
    _tuple_of_exact(
        transcripts,
        BuilderRandomnessTranscript,
        "transcripts",
        non_empty=True,
    )
    _tuple_of_exact(pair_topology, PairConstraintDraft, "pair_topology")
    _tuple_of_exact(atomic_links, AtomicLinkDraft, "atomic_links")
    _tuple_of_exact(
        materialization_slots,
        MaterializationSlotDraft,
        "materialization_slots",
    )
    for item in materialization_slots:
        item.__post_init__()

    draft_aliases = [item.unit_alias for item in drafts]
    transcript_aliases = [item.unit_alias for item in transcripts]
    if len(draft_aliases) != len(set(draft_aliases)):
        raise ProtocolViolation("draft unit aliases must be unique")
    if len(transcript_aliases) != len(set(transcript_aliases)):
        raise ProtocolViolation("transcript unit aliases must be unique")
    if set(draft_aliases) != set(transcript_aliases):
        raise ProtocolViolation("every draft requires exactly one builder transcript")
    if any(item.builder_id != builder_id for item in transcripts):
        raise ProtocolViolation("transcript builder_id does not match source builder")
    pair_aliases = [item.pair_alias for item in pair_topology]
    link_aliases = [item.link_alias for item in atomic_links]
    slot_aliases = [item.slot_alias for item in materialization_slots]
    if len(pair_aliases) != len(set(pair_aliases)):
        raise ProtocolViolation("pair topology aliases must be unique")
    if len(link_aliases) != len(set(link_aliases)):
        raise ProtocolViolation("atomic link aliases must be unique")
    if len(slot_aliases) != len(set(slot_aliases)):
        raise ProtocolViolation("materialization slot aliases must be unique")

    transcript_by_alias = {item.unit_alias: item for item in transcripts}
    authority_scope_digest = digest_json(
        {
            "schema_version": "ucm-family-authority-scope/2",
            "benchmark_id": benchmark_id,
            "benchmark_revision": benchmark_revision,
            "registry_digest": registry_digest,
            "generator_bundle_digest": generator_bundle_digest,
            "topology_contract_digest": topology_contract_digest,
            "query_contract_digest": query_contract_digest,
            "builder_id": builder_id,
            "builder_version": builder_version,
        }
    )
    units = tuple(
        _build_unit(
            item,
            transcript_by_alias[item.unit_alias],
            authority_scope_digest,
        )
        for item in drafts
    )
    unit_by_alias = {item.unit_alias: item for item in units}

    def resolve(unit_alias: str, member_alias: str) -> SourceMemberRef:
        unit = unit_by_alias.get(unit_alias)
        if unit is None:
            raise ProtocolViolation(f"topology references missing unit {unit_alias!r}")
        member = next(
            (item for item in unit.members if item.member_alias == member_alias),
            None,
        )
        if member is None:
            raise ProtocolViolation(
                f"topology references missing member {unit_alias!r}/{member_alias!r}"
            )
        return SourceMemberRef(unit.authority_digest, member.member_digest)

    pairs = tuple(
        PairConstraint(
            pair_alias=item.pair_alias,
            semantic_type=item.semantic_type,
            sides=tuple(
                PairSide(resolve(side.unit_alias, side.member_alias), side.side)
                for side in item.sides
            ),
        )
        for item in pair_topology
    )
    links = tuple(
        AtomicLink(
            link_alias=item.link_alias,
            semantic_type=item.semantic_type,
            members=tuple(
                resolve(member.unit_alias, member.member_alias)
                for member in item.members
            ),
        )
        for item in atomic_links
    )
    pair_by_alias = {item.pair_alias: item for item in pairs}
    link_by_alias = {item.link_alias: item for item in links}
    slots: list[MaterializationSlot] = []
    for item in materialization_slots:
        reference = resolve(item.unit_alias, item.member_alias)
        pair_digest: str | None = None
        if item.pair_alias is not None:
            pair = pair_by_alias.get(item.pair_alias)
            if pair is None:
                raise ProtocolViolation(
                    "materialization slot references a missing pair alias"
                )
            pair_digest = pair.pair_digest
        atomic_link_digest: str | None = None
        if item.atomic_link_alias is not None:
            link = link_by_alias.get(item.atomic_link_alias)
            if link is None:
                raise ProtocolViolation(
                    "materialization slot references a missing atomic link alias"
                )
            atomic_link_digest = link.link_digest
        assert item.row_bundle_commitment_digest is not None
        identity = {
            "reference": reference.to_wire(),
            "materialization_role": _materialization_role_wire(
                item.materialization_role
            ),
            "stage_label": item.stage_label,
            "cut_digest": item.cut_digest,
            "query_cell_digest": item.query_cell_digest,
            "pair_digest": pair_digest,
            "pair_side": item.pair_side,
            "atomic_link_digest": atomic_link_digest,
            "row_bundle_commitment_digest": item.row_bundle_commitment_digest,
        }
        slots.append(
            MaterializationSlot(
                slot_alias=item.slot_alias,
                reference=reference,
                materialization_role=item.materialization_role,
                stage_label=item.stage_label,
                cut_digest=item.cut_digest,
                query_cell_digest=item.query_cell_digest,
                pair_digest=pair_digest,
                pair_side=item.pair_side,
                atomic_link_digest=atomic_link_digest,
                row_bundle_commitment_digest=item.row_bundle_commitment_digest,
                slot_digest=domain_digest(
                    b"UCM\0PRE_SPLIT_MATERIALIZATION_SLOT_V1\0",
                    (canonical_json_bytes(identity),),
                ),
            )
        )
    return PreSplitFamilySource(
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        registry_digest=registry_digest,
        generator_bundle_digest=generator_bundle_digest,
        topology_contract_digest=topology_contract_digest,
        query_contract_digest=query_contract_digest,
        builder_id=builder_id,
        builder_version=builder_version,
        units=units,
        pairs=pairs,
        atomic_links=links,
        materialization_slots=tuple(slots),
    )


@dataclass(frozen=True, slots=True)
class UnitSplitAssignment:
    authority_digest: str
    assigned_split: FamilySplit
    weight: int

    def __post_init__(self) -> None:
        _digest(self.authority_digest, "assignment authority_digest")
        if type(self.assigned_split) is not FamilySplit:
            raise ProtocolViolation("assigned_split must be FamilySplit")
        if type(self.weight) is not int or self.weight <= 0:
            raise ProtocolViolation("assignment weight must be positive")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "authority_digest": self.authority_digest,
            "split": _family_split_wire(self.assigned_split),
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class AtomicComponentAssignment:
    component_digest: str
    authority_digests: tuple[str, ...]
    assigned_split: FamilySplit
    total_weight: int

    def __post_init__(self) -> None:
        _digest(self.component_digest, "component_digest")
        if type(self.authority_digests) is not tuple or not self.authority_digests:
            raise ProtocolViolation("component authority_digests must be non-empty")
        if any(_digest(item, "component authority_digest") != item for item in self.authority_digests):
            raise ProtocolViolation("component authority digest is invalid")
        if len(self.authority_digests) != len(set(self.authority_digests)):
            raise ProtocolViolation("component authority digests must be unique")
        if type(self.assigned_split) is not FamilySplit:
            raise ProtocolViolation("component split must be FamilySplit")
        if type(self.total_weight) is not int or self.total_weight <= 0:
            raise ProtocolViolation("component total_weight must be positive")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "component_digest": self.component_digest,
            "authority_digests": sorted(self.authority_digests),
            "split": _family_split_wire(self.assigned_split),
            "total_weight": self.total_weight,
        }


def _connected_components(source: PreSplitFamilySource) -> tuple[tuple[str, ...], ...]:
    parent = {unit.authority_digest: unit.authority_digest for unit in source.units}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for pair in source.pairs:
        union(
            pair.sides[0].reference.authority_digest,
            pair.sides[1].reference.authority_digest,
        )
    for link in source.atomic_links:
        anchor = link.members[0].authority_digest
        for member in link.members[1:]:
            union(anchor, member.authority_digest)

    groups: dict[str, list[str]] = {}
    for value in sorted(parent):
        groups.setdefault(find(value), []).append(value)
    return tuple(sorted((tuple(values) for values in groups.values())))


@dataclass(frozen=True, slots=True, weakref_slot=True)
class WeightedAtomicAssignment:
    source: PreSplitFamilySource
    split_policy_digest: str
    split_seed_commitment: str
    assignments: tuple[UnitSplitAssignment, ...]
    _sealed_assignment_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validate(allow_seal_initialization=True)

    def _validate(
        self, *, allow_seal_initialization: bool = False
    ) -> dict[str, Any]:
        if type(self.source) is not PreSplitFamilySource:
            raise ProtocolViolation("assignment source must be PreSplitFamilySource")
        self.source._validate()
        _digest(self.split_policy_digest, "assignment split_policy_digest")
        _digest(self.split_seed_commitment, "assignment split_seed_commitment")
        _tuple_of_exact(
            self.assignments,
            UnitSplitAssignment,
            "unit assignments",
            non_empty=True,
        )
        assignment_by_digest: dict[str, UnitSplitAssignment] = {}
        for item in self.assignments:
            if item.authority_digest in assignment_by_digest:
                raise ProtocolViolation("source unit has duplicate split assignments")
            assignment_by_digest[item.authority_digest] = item
        units = {item.authority_digest: item for item in self.source.units}
        if set(assignment_by_digest) != set(units):
            missing = sorted(set(units) - set(assignment_by_digest))
            extra = sorted(set(assignment_by_digest) - set(units))
            raise ProtocolViolation(
                f"split assignment must exactly cover source units; missing={missing}, extra={extra}"
            )
        for digest, assignment in assignment_by_digest.items():
            if assignment.weight != units[digest].weight:
                raise ProtocolViolation("split assignment weight does not match source weight")
        for component in _connected_components(self.source):
            splits = {assignment_by_digest[item].assigned_split for item in component}
            if len(splits) != 1:
                raise ProtocolViolation(
                    "an atomic connected component cannot be divided across splits"
                )
        body = self._body_unchecked()
        expected_digest = digest_json(body)
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_assignment_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="weighted atomic assignment seal is missing",
            changed_message="weighted atomic assignment changed after construction",
        )
        return body

    @property
    def components(self) -> tuple[AtomicComponentAssignment, ...]:
        self._validate()
        return self._components_unchecked()

    def _components_unchecked(self) -> tuple[AtomicComponentAssignment, ...]:
        assignments = {item.authority_digest: item for item in self.assignments}
        weights = {item.authority_digest: item.weight for item in self.source.units}
        result: list[AtomicComponentAssignment] = []
        for component in _connected_components(self.source):
            assigned_split = assignments[component[0]].assigned_split
            component_digest = domain_digest(
                b"UCM\0ATOMIC_ASSIGNMENT_COMPONENT_V2\0",
                tuple(item.encode("ascii") for item in sorted(component)),
            )
            result.append(
                AtomicComponentAssignment(
                    component_digest=component_digest,
                    authority_digests=component,
                    assigned_split=assigned_split,
                    total_weight=sum(weights[item] for item in component),
                )
            )
        return tuple(result)

    def _body_unchecked(self) -> dict[str, Any]:
        split_weights = {
            _family_split_wire(split): sum(
                item.weight for item in self.assignments if item.assigned_split is split
            )
            for split in FamilySplit
        }
        body = {
            "schema_version": ASSIGNMENT_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "source_digest": self.source.source_digest,
            "split_policy_digest": self.split_policy_digest,
            "split_seed_commitment": self.split_seed_commitment,
            "assignments": _sorted_wire(self.assignments),
            "connected_components": _sorted_wire(self._components_unchecked()),
            "split_weight_totals": split_weights,
            "blockers": [_code_owned_blocker_wire("assignment")],
        }
        validate_json_like(body)
        return body

    def _body(self) -> dict[str, Any]:
        return self._validate()

    @property
    def assignment_digest(self) -> str:
        self._validate()
        return self._sealed_assignment_digest

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["assignment_digest"] = self._sealed_assignment_digest
        return body

    def assignment_for(self, authority_digest: str) -> UnitSplitAssignment | None:
        self._validate()
        return next(
            (item for item in self.assignments if item.authority_digest == authority_digest),
            None,
        )


def build_weighted_atomic_assignment(
    source: PreSplitFamilySource,
    split_by_authority_digest: Mapping[str, FamilySplit],
    *,
    split_policy_digest: str,
    split_seed_commitment: str,
) -> WeightedAtomicAssignment:
    if type(source) is not PreSplitFamilySource:
        raise ProtocolViolation("source must be PreSplitFamilySource")
    if type(split_by_authority_digest) is not dict:
        raise ProtocolViolation("split assignment input must be an exact dictionary")
    _digest(split_policy_digest, "split_policy_digest")
    _digest(split_seed_commitment, "split_seed_commitment")
    if any(type(key) is not str or type(value) is not FamilySplit for key, value in split_by_authority_digest.items()):
        raise ProtocolViolation("split assignment mapping has invalid key/value types")
    units = {item.authority_digest: item for item in source.units}
    if set(split_by_authority_digest) != set(units):
        raise ProtocolViolation("split assignment mapping must exactly cover source units")
    return WeightedAtomicAssignment(
        source=source,
        split_policy_digest=split_policy_digest,
        split_seed_commitment=split_seed_commitment,
        assignments=tuple(
            UnitSplitAssignment(
                authority_digest=digest,
                assigned_split=split_by_authority_digest[digest],
                weight=unit.weight,
            )
            for digest, unit in sorted(units.items())
        ),
    )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class RowMaterializationEvidence:
    """Post-split row claim which can only join pre-existing slot authority."""

    record_id: str
    assigned_split: FamilySplit
    authority_digest: str
    member_digest: str
    public_history_digest: str
    hidden_state_at_cut_digest: str
    query_cell_digest: str
    oracle_target_digest: str
    candidate_row_digest: str
    judge_row_digest: str
    raw_request_digest: str
    raw_response_digest: str
    materialization_slot_digest: str | None = None
    cut_digest: str | None = None
    stage_label: str | None = None
    materialization_role: MaterializationRole | None = None
    pair_digest: str | None = None
    pair_side: int | None = None
    atomic_link_digest: str | None = None
    evidence_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validated_body(allow_seal_initialization=True)

    def _validated_body(
        self, *, allow_seal_initialization: bool = False
    ) -> dict[str, Any]:
        _name(self.record_id, "receipt record_id")
        if type(self.assigned_split) is not FamilySplit:
            raise ProtocolViolation("receipt split must be FamilySplit")
        for value, label in (
            (self.authority_digest, "receipt authority_digest"),
            (self.member_digest, "receipt member_digest"),
            (self.public_history_digest, "receipt public_history_digest"),
            (self.hidden_state_at_cut_digest, "receipt hidden_state_at_cut_digest"),
            (self.query_cell_digest, "receipt query_cell_digest"),
            (self.oracle_target_digest, "receipt oracle_target_digest"),
            (self.candidate_row_digest, "receipt candidate_row_digest"),
            (self.judge_row_digest, "receipt judge_row_digest"),
            (self.raw_request_digest, "receipt raw_request_digest"),
            (self.raw_response_digest, "receipt raw_response_digest"),
        ):
            _digest(value, label)
        if (self.materialization_slot_digest is None) != (self.cut_digest is None):
            raise ProtocolViolation(
                "row materialization slot_digest and cut_digest must be declared together"
            )
        if self.materialization_slot_digest is not None:
            _digest(
                self.materialization_slot_digest,
                "receipt materialization_slot_digest",
            )
            _digest(self.cut_digest, "receipt cut_digest")
            _name(self.stage_label, "receipt stage_label")
            if type(self.materialization_role) is not MaterializationRole:
                raise ProtocolViolation(
                    "receipt materialization_role must be MaterializationRole"
                )
            if (self.pair_digest is None) != (self.pair_side is None):
                raise ProtocolViolation(
                    "receipt pair_digest/pair_side must be declared together"
                )
            if self.pair_digest is not None:
                _digest(self.pair_digest, "receipt pair_digest")
                if type(self.pair_side) is not int or self.pair_side not in {0, 1}:
                    raise ProtocolViolation("receipt pair_side must be exact 0 or 1")
            elif self.materialization_role is MaterializationRole.PAIR_SIDE:
                raise ProtocolViolation(
                    "pair-side receipt role requires pair_digest/pair_side"
                )
            if self.atomic_link_digest is not None:
                _digest(self.atomic_link_digest, "receipt atomic_link_digest")
        elif any(
            value is not None
            for value in (
                self.stage_label,
                self.materialization_role,
                self.pair_digest,
                self.pair_side,
                self.atomic_link_digest,
            )
        ):
            raise ProtocolViolation(
                "row without a materialization slot cannot claim stage/role/topology authority"
            )
        body = self._body_unchecked()
        expected_digest = digest_json(body)
        _seal_or_validate_once(
            self,
            seal_attribute="evidence_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="row materialization evidence seal is missing",
            changed_message="row materialization evidence changed after construction",
        )
        return body

    @property
    def row_bundle_commitment_digest(self) -> str:
        return compute_row_bundle_commitment(
            record_id=self.record_id,
            public_history_digest=self.public_history_digest,
            hidden_state_at_cut_digest=self.hidden_state_at_cut_digest,
            oracle_target_digest=self.oracle_target_digest,
            candidate_row_digest=self.candidate_row_digest,
            judge_row_digest=self.judge_row_digest,
            raw_request_digest=self.raw_request_digest,
            raw_response_digest=self.raw_response_digest,
        )

    @classmethod
    def from_wire(cls, value: object) -> "RowMaterializationEvidence":
        if type(value) is not dict:
            raise ProtocolViolation("row materialization evidence must be an exact object")
        validate_json_like(value, path="row materialization evidence")
        # A row may reference an existing authority digest, but it cannot
        # introduce a field named family_digest (or its aliases).
        reject_privileged_keys(
            value,
            forbidden=frozenset(
                {
                    "family_digest",
                    "patient_family_digest",
                    "assignment_cluster_digest",
                }
            ),
            path="row materialization evidence",
        )
        expected = frozenset(
            {
                "schema_version",
                "status",
                "freeze_grade_evidence",
                "benchmark_freeze_eligible",
                "record_id",
                "split",
                "authority_digest",
                "member_digest",
                "public_history_digest",
                "hidden_state_at_cut_digest",
                "query_cell_digest",
                "oracle_target_digest",
                "candidate_row_digest",
                "judge_row_digest",
                "raw_request_digest",
                "raw_response_digest",
                "materialization_slot_digest",
                "cut_digest",
                "stage_label",
                "materialization_role",
                "pair_digest",
                "pair_side",
                "atomic_link_digest",
                "row_bundle_commitment_digest",
                "blockers",
                "evidence_digest",
            }
        )
        _exact_keys(value, expected, "row materialization evidence")
        assigned_split = _family_split_from_wire(value["split"])
        materialization_role = (
            None
            if value["materialization_role"] is None
            else _materialization_role_from_wire(value["materialization_role"])
        )
        evidence = cls(
            record_id=value["record_id"],
            assigned_split=assigned_split,
            authority_digest=value["authority_digest"],
            member_digest=value["member_digest"],
            public_history_digest=value["public_history_digest"],
            hidden_state_at_cut_digest=value["hidden_state_at_cut_digest"],
            query_cell_digest=value["query_cell_digest"],
            oracle_target_digest=value["oracle_target_digest"],
            candidate_row_digest=value["candidate_row_digest"],
            judge_row_digest=value["judge_row_digest"],
            raw_request_digest=value["raw_request_digest"],
            raw_response_digest=value["raw_response_digest"],
            materialization_slot_digest=value["materialization_slot_digest"],
            cut_digest=value["cut_digest"],
            stage_label=value["stage_label"],
            materialization_role=materialization_role,
            pair_digest=value["pair_digest"],
            pair_side=value["pair_side"],
            atomic_link_digest=value["atomic_link_digest"],
        )
        _digest(value["evidence_digest"], "row materialization evidence_digest")
        _digest(
            value["row_bundle_commitment_digest"],
            "row materialization row_bundle_commitment_digest",
        )
        if value != evidence.to_wire():
            raise ProtocolViolation(
                "row materialization evidence wire is non-canonical or stale"
            )
        return evidence

    def _body_unchecked(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "record_id": self.record_id,
            "split": _family_split_wire(self.assigned_split),
            "authority_digest": self.authority_digest,
            "member_digest": self.member_digest,
            "public_history_digest": self.public_history_digest,
            "hidden_state_at_cut_digest": self.hidden_state_at_cut_digest,
            "query_cell_digest": self.query_cell_digest,
            "oracle_target_digest": self.oracle_target_digest,
            "candidate_row_digest": self.candidate_row_digest,
            "judge_row_digest": self.judge_row_digest,
            "raw_request_digest": self.raw_request_digest,
            "raw_response_digest": self.raw_response_digest,
            "materialization_slot_digest": self.materialization_slot_digest,
            "cut_digest": self.cut_digest,
            "stage_label": self.stage_label,
            "materialization_role": (
                _materialization_role_wire(self.materialization_role)
                if self.materialization_role is not None
                else None
            ),
            "pair_digest": self.pair_digest,
            "pair_side": self.pair_side,
            "atomic_link_digest": self.atomic_link_digest,
            "row_bundle_commitment_digest": self.row_bundle_commitment_digest,
            "blockers": [_code_owned_blocker_wire("evidence")],
        }

    def to_wire(self) -> dict[str, Any]:
        body = self._validated_body()
        return {**body, "evidence_digest": self.evidence_digest}


class _MaterializationValidationContext:
    """One-shot validated indexes shared by batch receipt operations.

    Revalidating a 64-member pre-split source for every W19 row turns exact
    coverage into a quadratic serialization path.  This context is deliberately
    ephemeral: it validates and hashes the source/assignment once, then exposes
    only indexes derived from those exact objects for one synchronous operation.
    It is never serialized, cached globally, or accepted from a caller.
    """

    __slots__ = (
        "source",
        "assignment",
        "source_digest",
        "assignment_digest",
        "units_by_authority",
        "members_by_reference",
        "member_reference_order",
        "assignments_by_authority",
        "slots_by_digest",
        "slot_references_by_digest",
        "w19_clusters_by_reference",
    )

    def __init__(
        self,
        source: PreSplitFamilySource,
        assignment: WeightedAtomicAssignment,
    ) -> None:
        if type(source) is not PreSplitFamilySource:
            raise ProtocolViolation("receipt source must be PreSplitFamilySource")
        if type(assignment) is not WeightedAtomicAssignment:
            raise ProtocolViolation(
                "receipt assignment must be WeightedAtomicAssignment"
            )
        source._validate()
        assignment._validate()
        source_digest = source.source_digest
        if assignment.source.source_digest != source_digest:
            raise ProtocolViolation("receipt source/assignment source mismatch")

        self.source = source
        self.assignment = assignment
        self.source_digest = source_digest
        self.assignment_digest = assignment.assignment_digest
        units = source.units
        assignment_items = assignment.assignments
        slots = source.materialization_slots
        if not slots:
            raise ProtocolViolation(
                "materialization receipt requires a closed pre-split slot inventory"
            )
        atomic_links = source.atomic_links
        self.units_by_authority = {
            item.authority_digest: item for item in units
        }
        self.members_by_reference = {
            (unit.authority_digest, member.member_digest): member
            for unit in units
            for member in unit.members
        }
        self.member_reference_order = tuple(
            (unit.authority_digest, member.member_digest)
            for unit in units
            for member in unit.members
        )
        self.assignments_by_authority = {
            item.authority_digest: item for item in assignment_items
        }
        self.slots_by_digest = {
            item.slot_digest: item for item in slots
        }
        self.slot_references_by_digest = {
            item.slot_digest: (
                item.reference.authority_digest,
                item.reference.member_digest,
            )
            for item in slots
        }
        clusters: dict[tuple[str, str], list[str]] = {}
        for link in atomic_links:
            if link.semantic_type is not AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER:
                continue
            link_digest = link.link_digest
            for reference in link.members:
                key = (reference.authority_digest, reference.member_digest)
                clusters.setdefault(key, []).append(link_digest)
        self.w19_clusters_by_reference = {
            key: tuple(sorted(values)) for key, values in clusters.items()
        }


@dataclass(frozen=True, slots=True, weakref_slot=True)
class MaterializationReceipt:
    source: PreSplitFamilySource
    assignment: WeightedAtomicAssignment
    evidence: RowMaterializationEvidence
    _sealed_receipt_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        context = _MaterializationValidationContext(self.source, self.assignment)
        self._validate_against_context(context, allow_seal_initialization=True)

    @classmethod
    def _from_validated_context(
        cls,
        context: _MaterializationValidationContext,
        evidence: RowMaterializationEvidence,
    ) -> "MaterializationReceipt":
        """Construct one receipt inside a caller-inaccessible validated batch."""

        receipt = object.__new__(cls)
        object.__setattr__(receipt, "source", context.source)
        object.__setattr__(receipt, "assignment", context.assignment)
        object.__setattr__(receipt, "evidence", evidence)
        receipt._validate_against_context(context, allow_seal_initialization=True)
        return receipt

    def _validate_against_context(
        self,
        context: _MaterializationValidationContext,
        *,
        allow_seal_initialization: bool = False,
    ) -> dict[str, Any]:
        if type(self.source) is not PreSplitFamilySource:
            raise ProtocolViolation("receipt source must be PreSplitFamilySource")
        if type(self.assignment) is not WeightedAtomicAssignment:
            raise ProtocolViolation(
                "receipt assignment must be WeightedAtomicAssignment"
            )
        if type(self.evidence) is not RowMaterializationEvidence:
            raise ProtocolViolation("receipt evidence must be RowMaterializationEvidence")

        # The common batch path uses the exact parent objects.  A reconstructed
        # but byte-equivalent parent is accepted only after its own full
        # validation; a foreign authority is rejected by digest.
        if self.source is not context.source:
            self.source._validate()
            if self.source.source_digest != context.source_digest:
                raise ProtocolViolation("ledger receipt belongs to a foreign source")
        if self.assignment is not context.assignment:
            self.assignment._validate()
            if self.assignment.assignment_digest != context.assignment_digest:
                raise ProtocolViolation(
                    "ledger receipt belongs to a foreign assignment"
                )
        self.evidence._validated_body()
        unit = context.units_by_authority.get(self.evidence.authority_digest)
        if unit is None:
            raise ProtocolViolation("row cannot define an unknown source authority")
        reference_key = (
            self.evidence.authority_digest,
            self.evidence.member_digest,
        )
        if reference_key not in context.members_by_reference:
            raise ProtocolViolation("row cannot define an unknown source member")
        assigned = context.assignments_by_authority.get(
            self.evidence.authority_digest
        )
        if assigned is None or assigned.assigned_split is not self.evidence.assigned_split:
            raise ProtocolViolation("row split does not match the atomic assignment")
        if self.evidence.materialization_slot_digest is None:
            raise ProtocolViolation(
                "row must join a declared pre-split materialization slot"
            )
        slot = context.slots_by_digest.get(
            self.evidence.materialization_slot_digest
        )
        if slot is None:
            raise ProtocolViolation(
                "row cannot define an unknown materialization slot"
            )
        if (
            slot.reference.authority_digest != self.evidence.authority_digest
            or slot.reference.member_digest != self.evidence.member_digest
        ):
            raise ProtocolViolation(
                "row source member does not match materialization slot"
            )
        if slot.cut_digest != self.evidence.cut_digest:
            raise ProtocolViolation("row cut does not match materialization slot")
        if slot.query_cell_digest != self.evidence.query_cell_digest:
            raise ProtocolViolation(
                "row query cell does not match materialization slot"
            )
        if slot.stage_label != self.evidence.stage_label:
            raise ProtocolViolation("row stage does not match materialization slot")
        if slot.materialization_role is not self.evidence.materialization_role:
            raise ProtocolViolation("row role does not match materialization slot")
        if (
            slot.pair_digest != self.evidence.pair_digest
            or slot.pair_side != self.evidence.pair_side
        ):
            raise ProtocolViolation(
                "row pair side does not match materialization slot"
            )
        if slot.atomic_link_digest != self.evidence.atomic_link_digest:
            raise ProtocolViolation(
                "row atomic link does not match materialization slot"
            )
        if (
            slot.row_bundle_commitment_digest
            != self.evidence.row_bundle_commitment_digest
        ):
            raise ProtocolViolation(
                "row payload does not match the pre-split row bundle commitment"
            )
        body = self._body_unchecked(context)
        expected_digest = digest_json(body)
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_receipt_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="materialization receipt seal is missing",
            changed_message="materialization receipt changed after construction",
        )
        # Return the exact body whose digest was checked.  Public wire methods
        # must not traverse the mutable parent graph a second time and attach
        # an older seal to a newer body.
        return body

    def _body_unchecked(
        self, context: _MaterializationValidationContext
    ) -> dict[str, Any]:
        unit = context.units_by_authority.get(self.evidence.authority_digest)
        assert unit is not None  # established by __post_init__
        slot = (
            context.slots_by_digest.get(self.evidence.materialization_slot_digest)
            if self.evidence.materialization_slot_digest is not None
            else None
        )
        assignment_cluster_digests = list(
            context.w19_clusters_by_reference.get(
                (
                    self.evidence.authority_digest,
                    self.evidence.member_digest,
                ),
                (),
            )
        )
        body = {
            "schema_version": RECEIPT_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_origin": "pre_split_source",
            "source_digest": context.source_digest,
            "assignment_digest": context.assignment_digest,
            "family_digest": unit.family_digest,
            "assignment_cluster_digests": assignment_cluster_digests,
            "row_join": self.evidence.to_wire(),
            "materialization_slot": slot.to_wire() if slot is not None else None,
            "blockers": [_code_owned_blocker_wire("receipt")],
        }
        validate_json_like(body)
        return body

    def _body(self) -> dict[str, Any]:
        context = _MaterializationValidationContext(self.source, self.assignment)
        return self._validate_against_context(context)

    @property
    def receipt_digest(self) -> str:
        context = _MaterializationValidationContext(self.source, self.assignment)
        self._validate_against_context(context)
        return self._sealed_receipt_digest

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["receipt_digest"] = self._sealed_receipt_digest
        return body


def issue_materialization_receipt(
    source: PreSplitFamilySource,
    assignment: WeightedAtomicAssignment,
    evidence: RowMaterializationEvidence,
) -> MaterializationReceipt:
    return MaterializationReceipt(source, assignment, evidence)


def issue_materialization_receipt_batch(
    source: PreSplitFamilySource,
    assignment: WeightedAtomicAssignment,
    evidences: tuple[RowMaterializationEvidence, ...],
) -> tuple[MaterializationReceipt, ...]:
    """Issue many exact receipts after one parent-authority validation.

    Every evidence and slot join is still checked independently.  Only the
    immutable-for-this-operation source/assignment validation and indexes are
    shared.  No validation context crosses this function boundary.
    """

    _tuple_of_exact(
        evidences,
        RowMaterializationEvidence,
        "materialization receipt batch evidences",
        non_empty=True,
    )
    context = _MaterializationValidationContext(source, assignment)
    return tuple(
        MaterializationReceipt._from_validated_context(context, evidence)
        for evidence in evidences
    )


@dataclass(frozen=True, slots=True)
class MaterializedSlotCoverage:
    slot_digest: str
    receipt_digest: str
    assigned_split: FamilySplit
    record_id: str

    def __post_init__(self) -> None:
        _digest(self.slot_digest, "coverage slot_digest")
        _digest(self.receipt_digest, "coverage receipt_digest")
        if type(self.assigned_split) is not FamilySplit:
            raise ProtocolViolation("coverage assigned_split has wrong type")
        _name(self.record_id, "coverage record_id")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "slot_digest": self.slot_digest,
            "receipt_digest": self.receipt_digest,
            "split": _family_split_wire(self.assigned_split),
            "record_id": self.record_id,
        }


@dataclass(frozen=True, slots=True)
class MemberMaterializationCoverage:
    """Ledger view for one source member, including explicit zero coverage."""

    authority_digest: str
    member_digest: str
    entries: tuple[MaterializedSlotCoverage, ...]

    def __post_init__(self) -> None:
        _digest(self.authority_digest, "member coverage authority_digest")
        _digest(self.member_digest, "member coverage member_digest")
        _tuple_of_exact(
            self.entries,
            MaterializedSlotCoverage,
            "member coverage entries",
        )
        for entry in self.entries:
            entry.__post_init__()
        slot_digests = [item.slot_digest for item in self.entries]
        receipt_digests = [item.receipt_digest for item in self.entries]
        if len(slot_digests) != len(set(slot_digests)):
            raise ProtocolViolation("member coverage contains duplicate slots")
        if len(receipt_digests) != len(set(receipt_digests)):
            raise ProtocolViolation("member coverage contains duplicate receipts")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "authority_digest": self.authority_digest,
            "member_digest": self.member_digest,
            "entries": _sorted_wire(self.entries),
        }


@dataclass(frozen=True, slots=True, weakref_slot=True)
class MaterializationReceiptLedger:
    """Exact post-split coverage of a pre-split materialization inventory.

    The expected set is derived solely from ``source.materialization_slots``.
    Receipts cannot enlarge or shrink that set, and therefore cannot create an
    apparent exact ledger from whatever rows happened to be emitted.
    """

    source: PreSplitFamilySource
    assignment: WeightedAtomicAssignment
    receipts: tuple[MaterializationReceipt, ...]
    _sealed_ledger_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validate(allow_seal_initialization=True)

    def _validate(
        self, *, allow_seal_initialization: bool = False
    ) -> tuple[dict[str, Any], tuple[MemberMaterializationCoverage, ...]]:
        if type(self.source) is not PreSplitFamilySource:
            raise ProtocolViolation("ledger source must be PreSplitFamilySource")
        if type(self.assignment) is not WeightedAtomicAssignment:
            raise ProtocolViolation(
                "ledger assignment must be WeightedAtomicAssignment"
            )
        context = _MaterializationValidationContext(self.source, self.assignment)
        if not context.slots_by_digest:
            raise ProtocolViolation(
                "exact ledger requires a closed pre-split materialization inventory"
            )
        # Snapshot the tuple reference once.  A concurrent or hostile rewrite
        # cannot make validation inspect one tuple and serialization emit a
        # different tuple.
        receipts = self.receipts
        _tuple_of_exact(
            receipts,
            MaterializationReceipt,
            "materialization ledger receipts",
            non_empty=True,
        )

        receipt_by_slot: dict[str, dict[str, Any]] = {}
        receipt_wires: list[dict[str, Any]] = []
        for receipt in receipts:
            receipt_body = receipt._validate_against_context(context)
            receipt_wire = {
                **receipt_body,
                "receipt_digest": receipt._sealed_receipt_digest,
            }
            receipt_wires.append(receipt_wire)
            slot_digest = receipt_body["row_join"]["materialization_slot_digest"]
            assert slot_digest is not None  # receipt validation + non-empty inventory
            if slot_digest in receipt_by_slot:
                raise ProtocolViolation(
                    "materialization ledger contains a duplicate slot receipt"
                )
            receipt_by_slot[slot_digest] = receipt_wire

        expected = set(context.slots_by_digest)
        actual = set(receipt_by_slot)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ProtocolViolation(
                "materialization ledger must exactly cover declared slots; "
                f"missing={missing}, extra={extra}"
            )

        for wire_key, label in (
            ("record_id", "record ids"),
            ("candidate_row_digest", "candidate row digests"),
            ("judge_row_digest", "judge row digests"),
            ("raw_request_digest", "raw request digests"),
            ("raw_response_digest", "raw response digests"),
        ):
            values = [item["row_join"][wire_key] for item in receipt_wires]
            if len(values) != len(set(values)):
                raise ProtocolViolation(
                    f"materialization ledger {label} must be unique"
                )
        coverage = self._member_coverage_from_snapshot(context, receipt_by_slot)
        body = self._body_unchecked(
            context,
            tuple(receipt_wires),
            coverage,
        )
        expected_digest = digest_json(body)
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_ledger_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="materialization ledger seal is missing",
            changed_message="materialization ledger changed after construction",
        )
        # Body and coverage are the exact snapshots which passed every join,
        # exact-set, uniqueness, and seal check above.
        return body, coverage

    def _member_coverage_from_snapshot(
        self,
        context: _MaterializationValidationContext,
        receipt_by_slot: dict[str, dict[str, Any]],
    ) -> tuple[MemberMaterializationCoverage, ...]:
        slots_by_member: dict[tuple[str, str], list[str]] = {}
        for slot_digest, key in context.slot_references_by_digest.items():
            slots_by_member.setdefault(key, []).append(slot_digest)
        coverage: list[MemberMaterializationCoverage] = []
        for authority_digest, member_digest in context.member_reference_order:
            key = (authority_digest, member_digest)
            entries: list[MaterializedSlotCoverage] = []
            for slot_digest in sorted(slots_by_member.get(key, [])):
                receipt_wire = receipt_by_slot[slot_digest]
                row_join = receipt_wire["row_join"]
                entries.append(
                    MaterializedSlotCoverage(
                        slot_digest=slot_digest,
                        receipt_digest=receipt_wire["receipt_digest"],
                        assigned_split=_family_split_from_wire(row_join["split"]),
                        record_id=row_join["record_id"],
                    )
                )
            coverage.append(
                MemberMaterializationCoverage(
                    authority_digest=authority_digest,
                    member_digest=member_digest,
                    entries=tuple(entries),
                )
            )
        return tuple(coverage)

    @property
    def member_coverage(self) -> tuple[MemberMaterializationCoverage, ...]:
        _, coverage = self._validate()
        return coverage

    def _body_unchecked(
        self,
        context: _MaterializationValidationContext,
        receipt_wires: tuple[dict[str, Any], ...],
        coverage: tuple[MemberMaterializationCoverage, ...],
    ) -> dict[str, Any]:
        body = {
            "schema_version": LEDGER_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "source_digest": context.source_digest,
            "assignment_digest": context.assignment_digest,
            "declared_slot_count": len(context.slots_by_digest),
            "receipt_count": len(receipt_wires),
            "receipts": sorted(
                receipt_wires, key=lambda item: canonical_json_bytes(item)
            ),
            "member_coverage": _sorted_wire(coverage),
            "blockers": [_code_owned_blocker_wire("ledger")],
        }
        validate_json_like(body)
        return body

    def _body(self) -> dict[str, Any]:
        body, _ = self._validate()
        return body

    @property
    def ledger_digest(self) -> str:
        self._validate()
        return self._sealed_ledger_digest

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["ledger_digest"] = self._sealed_ledger_digest
        return body


def build_materialization_receipt_ledger(
    source: PreSplitFamilySource,
    assignment: WeightedAtomicAssignment,
    receipts: tuple[MaterializationReceipt, ...],
) -> MaterializationReceiptLedger:
    return MaterializationReceiptLedger(source, assignment, receipts)


@dataclass(frozen=True, slots=True)
class LegacyPostSplitAdapterAudit:
    input_digest: str
    row_count: int
    blockers: tuple[ScaffoldBlocker, ...]

    def __post_init__(self) -> None:
        _digest(self.input_digest, "legacy input_digest")
        if type(self.row_count) is not int or self.row_count < 0:
            raise ProtocolViolation("legacy row_count must be non-negative")
        _tuple_of_exact(self.blockers, ScaffoldBlocker, "legacy blockers", non_empty=True)

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        body = {
            "schema_version": LEGACY_AUDIT_PROTOCOL,
            "status": "incomplete",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "input_digest": self.input_digest,
            "row_count": self.row_count,
            "pre_split_source": None,
            "assignments": None,
            "materialization_receipts": [],
            "blockers": _sorted_wire(self.blockers),
        }
        validate_json_like(body)
        return body


def audit_legacy_post_split_adapter(
    rows: Iterable[dict[str, Any]],
) -> LegacyPostSplitAdapterAudit:
    """Record legacy input without ever elevating its row grouping to authority."""

    if type(rows) not in {tuple, list}:
        raise ProtocolViolation("legacy rows must be an exact tuple or list")
    rows_tuple = tuple(rows)
    if any(type(row) is not dict for row in rows_tuple):
        raise ProtocolViolation("legacy rows must contain exact JSON objects")
    for index, row in enumerate(rows_tuple):
        validate_json_like(row, path=f"legacy rows[{index}]")
    blockers = (
        ScaffoldBlocker(
            INCOMPLETE_CODE,
            "legacy_post_split_adapter",
            "post-split rows cannot create CounterfactualFamily authority",
        ),
        ScaffoldBlocker(
            INCOMPLETE_CODE,
            "legacy_post_split_adapter",
            "producer-reported grouping and family digests are ignored rather than promoted",
        ),
    )
    return LegacyPostSplitAdapterAudit(
        input_digest=digest_json(list(rows_tuple)),
        row_count=len(rows_tuple),
        blockers=blockers,
    )
