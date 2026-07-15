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

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
    domain_digest,
    reject_privileged_keys,
    validate_json_like,
)


SOURCE_PROTOCOL = "ucm-pre-split-family-source/2"
ASSIGNMENT_PROTOCOL = "ucm-weighted-atomic-family-assignment/2"
RECEIPT_PROTOCOL = "ucm-family-materialization-receipt/2"
LEGACY_AUDIT_PROTOCOL = "ucm-legacy-family-adapter-audit/2"

INCOMPLETE_CODE = "UCM-E003-HARNESS_INCOMPLETE"

_PRODUCER_FORBIDDEN = frozenset(
    {
        "status",
        "freeze_grade_evidence",
        "benchmark_freeze_eligible",
        "family_digest",
        "patient_family_digest",
        "assignment_cluster_digest",
        "authority_digest",
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
        "builder_run_id",
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


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 71 or not value.startswith("sha256:"):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} must be hexadecimal") from exc
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


def _source_unit_semantic_wire(value: SourceUnitSemantic) -> str:
    if value is SourceUnitSemantic.PATIENT_FAMILY:
        return "patient_family"
    raise ProtocolViolation("source unit semantic enum identity is invalid")


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
        try:
            semantic_type = SourceMemberSemantic(row["semantic_type"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("producer member semantic_type is invalid") from exc
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

        has_w19_rows = any(
            member.semantic_type is SourceMemberSemantic.W19_ASSIGNMENT_ROW
            for member in self.members
        )
        if has_w19_rows and self.world_slot != "W19":
            raise ProtocolViolation("W19 assignment rows may only belong to W19 families")

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
        try:
            semantic_type = SourceUnitSemantic(row["semantic_type"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("producer source unit semantic_type is invalid") from exc
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
        has_w19_rows = any(
            member.semantic_type is SourceMemberSemantic.W19_ASSIGNMENT_ROW
            for member in self.members
        )
        if has_w19_rows and self.world_slot != "W19":
            raise ProtocolViolation("resolved W19 assignment row is outside W19")

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


@dataclass(frozen=True, slots=True)
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

    def __post_init__(self) -> None:
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
        for unit in self.units:
            unit.__post_init__()
            if unit.authority_scope_digest != self.authority_scope_digest:
                raise ProtocolViolation("source unit authority scope is stale or mismatched")
        for pair in self.pairs:
            pair.__post_init__()
        for link in self.atomic_links:
            link.__post_init__()
        for values, label in (
            ([item.unit_alias for item in self.units], "unit aliases"),
            ([item.authority_digest for item in self.units], "unit authority digests"),
            ([item.pair_alias for item in self.pairs], "pair aliases"),
            ([item.link_alias for item in self.atomic_links], "atomic link aliases"),
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

    def _body(self) -> dict[str, Any]:
        self.__post_init__()
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
            "blockers": [_SOURCE_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def source_digest(self) -> str:
        return digest_json(self._body())

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
        body["source_digest"] = self.source_digest
        return body

    def unit_by_digest(self, authority_digest: str) -> PreSplitSourceUnit | None:
        return next(
            (item for item in self.units if item.authority_digest == authority_digest),
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
    if len(pair_aliases) != len(set(pair_aliases)):
        raise ProtocolViolation("pair topology aliases must be unique")
    if len(link_aliases) != len(set(link_aliases)):
        raise ProtocolViolation("atomic link aliases must be unique")

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


@dataclass(frozen=True, slots=True)
class WeightedAtomicAssignment:
    source: PreSplitFamilySource
    split_policy_digest: str
    split_seed_commitment: str
    assignments: tuple[UnitSplitAssignment, ...]

    def __post_init__(self) -> None:
        if type(self.source) is not PreSplitFamilySource:
            raise ProtocolViolation("assignment source must be PreSplitFamilySource")
        self.source.__post_init__()
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

    @property
    def components(self) -> tuple[AtomicComponentAssignment, ...]:
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

    def _body(self) -> dict[str, Any]:
        self.__post_init__()
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
            "connected_components": _sorted_wire(self.components),
            "split_weight_totals": split_weights,
            "blockers": [_ASSIGNMENT_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def assignment_digest(self) -> str:
        return digest_json(self._body())

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["assignment_digest"] = self.assignment_digest
        return body

    def assignment_for(self, authority_digest: str) -> UnitSplitAssignment | None:
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


@dataclass(frozen=True, slots=True)
class RowMaterializationEvidence:
    """Post-split row evidence which can only join existing authority."""

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

    def __post_init__(self) -> None:
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
            }
        )
        _exact_keys(value, expected, "row materialization evidence")
        try:
            assigned_split = FamilySplit(value["split"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("row materialization split is invalid") from exc
        return cls(
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
        )

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
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
        }


@dataclass(frozen=True, slots=True)
class MaterializationReceipt:
    source: PreSplitFamilySource
    assignment: WeightedAtomicAssignment
    evidence: RowMaterializationEvidence

    def __post_init__(self) -> None:
        if type(self.source) is not PreSplitFamilySource:
            raise ProtocolViolation("receipt source must be PreSplitFamilySource")
        if type(self.assignment) is not WeightedAtomicAssignment:
            raise ProtocolViolation("receipt assignment must be WeightedAtomicAssignment")
        if type(self.evidence) is not RowMaterializationEvidence:
            raise ProtocolViolation("receipt evidence must be RowMaterializationEvidence")
        self.source.__post_init__()
        self.assignment.__post_init__()
        self.evidence.__post_init__()
        if self.assignment.source.source_digest != self.source.source_digest:
            raise ProtocolViolation("receipt source/assignment source mismatch")
        unit = self.source.unit_by_digest(self.evidence.authority_digest)
        if unit is None:
            raise ProtocolViolation("row cannot define an unknown source authority")
        if unit.member_by_digest(self.evidence.member_digest) is None:
            raise ProtocolViolation("row cannot define an unknown source member")
        assigned = self.assignment.assignment_for(self.evidence.authority_digest)
        if assigned is None or assigned.assigned_split is not self.evidence.assigned_split:
            raise ProtocolViolation("row split does not match the atomic assignment")

    def _body(self) -> dict[str, Any]:
        self.__post_init__()
        unit = self.source.unit_by_digest(self.evidence.authority_digest)
        assert unit is not None  # established by __post_init__
        assignment_cluster_digests = sorted(
            link.link_digest
            for link in self.source.atomic_links
            if link.semantic_type is AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER
            and any(
                reference.authority_digest == self.evidence.authority_digest
                and reference.member_digest == self.evidence.member_digest
                for reference in link.members
            )
        )
        body = {
            "schema_version": RECEIPT_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_origin": "pre_split_source",
            "source_digest": self.source.source_digest,
            "assignment_digest": self.assignment.assignment_digest,
            "family_digest": unit.family_digest,
            "assignment_cluster_digests": assignment_cluster_digests,
            "row_join": self.evidence.to_wire(),
            "blockers": [_RECEIPT_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def receipt_digest(self) -> str:
        return digest_json(self._body())

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["receipt_digest"] = self.receipt_digest
        return body


def issue_materialization_receipt(
    source: PreSplitFamilySource,
    assignment: WeightedAtomicAssignment,
    evidence: RowMaterializationEvidence,
) -> MaterializationReceipt:
    return MaterializationReceipt(source, assignment, evidence)


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
