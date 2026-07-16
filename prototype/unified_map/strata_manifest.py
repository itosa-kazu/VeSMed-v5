"""Fail-closed dual-channel stratum authority scaffolding for UCM.

``world.strata_for_episode`` is useful development code, but a label stored on
an already materialised episode is not evidence that benchmark stratification
was frozen before the row existed.  This module captures the stronger
authority flow required by benchmark v1:

* a public channel replays typed rules over only canonical candidate-visible
  history and binds the exact classifier source digest;
* a judge channel derives private strata from a pre-split family authority,
  its atomic split assignment, and a code-owned generator allocation manifest;
* an exact row receipt joins the record, history, family, member and cut to
  independently derived results from both channels.

The judge channel never accepts a row-reported stratum or control digest.
``behavior_pair`` is derived only from pre-split family topology.  W10
compositional membership, W18 mechanism OOD membership and W19 tail membership
use dedicated frozen-allocation rule kinds, so realised outcomes or post-hoc
``crossed`` flags cannot silently become authorities.

This remains deliberately non-freeze-grade.  Every standalone wire artifact
hard-codes ``status = pre_freeze_scaffold``, both freeze flags to ``false``, and
an explicit ``UCM-E003-HARNESS_INCOMPLETE`` blocker.  Source custody, sealing,
atomic publication and integration with the corpus materialiser are not yet
implemented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Any, Iterable
from weakref import ReferenceType, ref

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
    domain_digest,
    reject_privileged_keys,
    validate_json_like,
)
from .family_manifest import (
    AtomicLinkSemantic,
    FamilySplit,
    MaterializationReceipt,
    MaterializationReceiptLedger,
    MaterializationRole,
    MaterializationSlot,
    PairSemantic,
    PreSplitFamilySource,
    WeightedAtomicAssignment,
)
from .schema import VisibleHistory


PUBLIC_CLASSIFIER_PROTOCOL = "ucm-public-strata-classifier/1"
JUDGE_AUTHORITY_PROTOCOL = "ucm-judge-strata-authority/2"
DUAL_AUTHORITY_PROTOCOL = "ucm-dual-channel-strata-authority/2"
PUBLIC_RESULT_PROTOCOL = "ucm-public-strata-result/1"
JUDGE_RESULT_PROTOCOL = "ucm-judge-strata-result/2"
ROW_RECEIPT_PROTOCOL = "ucm-dual-channel-strata-row-receipt/2"
RECEIPT_BATCH_PROTOCOL = "ucm-dual-channel-strata-receipt-batch/2"
SLOT_ALLOCATION_COMMITMENT_PROTOCOL = "ucm-slot-strata-allocation-commitment/1"
SLOT_ALLOCATION_ENTRY_PROTOCOL = "ucm-frozen-slot-strata-allocation/1"
ALLOCATION_MANIFEST_PROTOCOL = "ucm-pre-split-strata-allocation-manifest/1"

INCOMPLETE_CODE = "UCM-E003-HARNESS_INCOMPLETE"


# A seal stored only on a dataclass can be deleted and recreated by explicitly
# calling its public ``__post_init__`` method.  Track first initialization
# outside the artifact, exactly as the family authority does.  Weak references
# avoid retaining completed authorities or confusing a later recycled object id.
_SEALED_OBJECT_REFS: dict[int, tuple[ReferenceType[Any], str]] = {}
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
        existing = _SEALED_OBJECT_REFS.get(object_id)
        was_initialized = (
            existing is not None and existing[0]() is value
        )
        try:
            sealed_digest = object.__getattribute__(value, seal_attribute)
        except AttributeError:
            if not allow_initialization or was_initialized:
                raise ProtocolViolation(missing_message)
            object.__setattr__(value, seal_attribute, expected_digest)

            def discard(dead_reference: ReferenceType[Any]) -> None:
                with _SEALED_OBJECT_REFS_LOCK:
                    current = _SEALED_OBJECT_REFS.get(object_id)
                    if current is not None and current[0] is dead_reference:
                        del _SEALED_OBJECT_REFS[object_id]

            _SEALED_OBJECT_REFS[object_id] = (
                ref(value, discard),
                expected_digest,
            )
            return
        if was_initialized and existing[1] != expected_digest:
            raise ProtocolViolation(changed_message)
        if sealed_digest != expected_digest:
            raise ProtocolViolation(changed_message)
        if not was_initialized:
            def discard(dead_reference: ReferenceType[Any]) -> None:
                with _SEALED_OBJECT_REFS_LOCK:
                    current = _SEALED_OBJECT_REFS.get(object_id)
                    if current is not None and current[0] is dead_reference:
                        del _SEALED_OBJECT_REFS[object_id]

            _SEALED_OBJECT_REFS[object_id] = (
                ref(value, discard),
                expected_digest,
            )

STRATUM_ORDER = (
    "iid_support",
    "boundary_tail",
    "compositional_holdout",
    "schedule_time_holdout",
    "policy_coverage_holdout",
    "extension_check",
    "extension_treatment",
    "mechanism_ood",
    "behavior_pair",
)
KNOWN_STRATA = frozenset(STRATUM_ORDER)
_STRATUM_ORDER_INDEX = {label: index for index, label in enumerate(STRATUM_ORDER)}

# Frozen benchmark-v1 declaration copied as a code-owned contract rather than
# trusting a producer's per-row labels.  The family source already binds the
# registry digest; this table additionally makes missing/extra world labels
# fail closed at the strata boundary.
WORLD_DECLARED_STRATA: dict[str, tuple[str, ...]] = {
    "W01": ("iid_support", "boundary_tail"),
    "W02": ("iid_support", "boundary_tail"),
    "W03": ("iid_support", "boundary_tail", "behavior_pair"),
    "W04": (
        "iid_support",
        "boundary_tail",
        "policy_coverage_holdout",
        "behavior_pair",
    ),
    "W05": ("iid_support", "boundary_tail", "policy_coverage_holdout"),
    "W06": ("iid_support", "boundary_tail", "policy_coverage_holdout"),
    "W07": ("iid_support", "boundary_tail", "policy_coverage_holdout"),
    "W08": ("iid_support", "boundary_tail", "schedule_time_holdout"),
    "W09": ("iid_support", "boundary_tail"),
    "W10": ("iid_support", "boundary_tail", "compositional_holdout"),
    "W11": ("iid_support", "boundary_tail", "behavior_pair"),
    "W12": ("iid_support", "boundary_tail", "compositional_holdout"),
    "W13": ("iid_support", "boundary_tail", "compositional_holdout"),
    "W14": (
        "iid_support",
        "boundary_tail",
        "schedule_time_holdout",
        "behavior_pair",
    ),
    "W15": (
        "iid_support",
        "boundary_tail",
        "policy_coverage_holdout",
        "behavior_pair",
    ),
    "W16": ("iid_support", "boundary_tail", "extension_check", "behavior_pair"),
    "W17": (
        "iid_support",
        "boundary_tail",
        "extension_treatment",
        "behavior_pair",
    ),
    "W18": ("iid_support", "boundary_tail", "mechanism_ood", "behavior_pair"),
    "W19": (
        "iid_support",
        "boundary_tail",
        "policy_coverage_holdout",
        "behavior_pair",
    ),
    "W20": (
        "iid_support",
        "boundary_tail",
        "compositional_holdout",
        "schedule_time_holdout",
        "policy_coverage_holdout",
        "behavior_pair",
    ),
}

_LABEL_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

# Candidate-visible history cannot carry judge-owned joins, labels or control
# digests under spelling aliases.  ``reject_privileged_keys`` normalises snake,
# camel and kebab spellings recursively.
_PUBLIC_HISTORY_FORBIDDEN = frozenset(
    {
        "status",
        "blockers",
        "freeze_grade_evidence",
        "benchmark_freeze_eligible",
        "benchmark_id",
        "benchmark_revision",
        "strata",
        "stratum",
        "stratum_label",
        "stratum_labels",
        "public_strata",
        "judge_strata",
        "judge_only_strata",
        "public_replay_labels",
        "judge_only_labels",
        "judge_frozen_labels",
        "stratum_control_digest",
        "definition_contract_digest",
        "definition_source_digest",
        "classifier_digest",
        "classifier_source_digest",
        "generator_source_digest",
        "allocation_policy_digest",
        "allocation_manifest_digest",
        "entry_digest",
        "authority_digest",
        "authority_scope_digest",
        "family_digest",
        "patient_family_digest",
        "member_digest",
        "cut_digest",
        "source_digest",
        "assignment_digest",
        "split_policy_digest",
        "split_seed_commitment",
        "receipt_digest",
        "record_digest",
        "result_digest",
        "split",
        "record_id",
        "case_key",
        "generator_seed",
        "master_seed",
        "latent_seed",
        "noise_seed",
        "hidden_state",
        "oracle_anchor",
        "oracle_target",
        "judge_oracle",
        "allocation_facts",
        "world_slot",
        "world_id",
        "source_member_id",
        "assignment_unit_digest",
        "assignment_cluster_digest",
        "pair_group",
        "pair_digest",
        "pair_cell",
        "family_source_digest",
        "family_assignment_digest",
        "allocation_bucket",
        "mechanism_cell",
        "compositional_cell",
        "authority_role",
        "topology_contract_digest",
        "materialization_receipt_digest",
        "materialization_slot_digest",
        "query_cell_digest",
        "public_history_digest",
        "candidate_row_digest",
        "judge_row_digest",
        "hidden_state_at_cut_digest",
        "oracle_target_digest",
        "raw_request_digest",
        "raw_response_digest",
        "evidence_digest",
        "stage_label",
        "materialization_role",
        "pair_digest",
        "pair_side",
    }
)

# Event payloads are an information boundary, not an extensible place for
# materializer provenance.  Exact-name rejection above remains useful for
# precise diagnostics, but it cannot enumerate every future spelling of
# ``slotAlias``/``generatorBundleDigest``.  Reserve whole control-plane
# namespaces as well, and reject digest-shaped payload keys by default.  The
# history's canonical top-level ``catalog_digest`` is intentionally outside
# this payload-only gate.
_PUBLIC_PAYLOAD_RESERVED_TOKENS = frozenset(
    {
        "assignment",
        "authority",
        "builder",
        "family",
        "generator",
        "judge",
        "ledger",
        "materialization",
        "pair",
        "provenance",
        "receipt",
        "registry",
        "slot",
        "source",
        "split",
        "strata",
        "stratum",
    }
)

# Keys alone are not an information boundary: a producer could put a frozen
# split, family-topology or strata label in an otherwise innocuous public
# scalar such as ``marker``/``signal``/``value`` (or even ``event_uid``).  Keep
# the control-plane value namespace closed as well.  Digest-shaped values in
# both event identifiers and payloads are handled separately by
# ``_reject_digest_shaped_public_values`` below.
_PUBLIC_SCALAR_RESERVED_TOKENS = frozenset(
    {
        "assignment",
        "authority",
        "blocker",
        "builder",
        "family",
        "freeze",
        "generator",
        "hidden",
        "judge",
        "ledger",
        "materialization",
        "oracle",
        "pair",
        "provenance",
        "receipt",
        "registry",
        "seed",
        "slot",
        "source",
        "split",
        "strata",
        "stratum",
    }
)
_PUBLIC_SCALAR_RESERVED_EXACT = frozenset(
    {
        *KNOWN_STRATA,
        "train",
        "validation",
        "sealed_test",
        "response_reversal",
        "response_reversal_pair",
        "behavioral_pair",
    }
)
_PUBLIC_PAYLOAD_RESERVED_KEY_ALLOWLIST = frozenset(
    {
        # W10's public compositional rule consumes the actually observed assay
        # position.  It is a clinical/check datum, not a materializer slot.
        "assay_slot",
    }
)

# Closed benchmark-v1 projection.  Arbitrary producer payloads are not a
# public schema: without a closed projection a private receipt can simply be
# renamed to ``metadata.opaque`` and survive any key blacklist.  These keys
# cover the canonical event forms emitted by the current W01--W20 worlds and
# the shared policy engine.  Adding a genuinely public field therefore
# requires an explicit protocol change here rather than an implicit passthrough.
_PUBLIC_EVENT_PAYLOAD_KEYS: dict[str, frozenset[str]] = {
    "observation_available": frozenset(
        {
            "assay_slot",
            "channel_id",
            "check_id",
            "marker",
            "order_uid",
            "results",
            "schema_version",
            "signal",
            "specimen_uid",
            "value",
        }
    ),
    "performed_treatment": frozenset(
        {
            "action_id",
            "control_kind",
            "course_microticks",
            "dose",
            "parameters",
            "schema_version",
            "stopped_action_id",
        }
    ),
    "test_ordered": frozenset(
        {"check_id", "order_uid", "parameters", "schema_version"}
    ),
    "test_performed": frozenset(
        {"check_id", "order_uid", "parameters", "schema_version"}
    ),
    "context_available": frozenset(
        {"channel_id", "marker", "schema_version", "signal", "value"}
    ),
}
_PUBLIC_PARAMETER_KEYS = frozenset(
    {
        "adaptive_rule",
        "dose",
        "on_result_0",
        "on_result_1",
        "purpose",
        "result_available_offset",
    }
)
_PUBLIC_RESULT_KEYS = frozenset(
    {"assay_slot", "channel_id", "specimen_uid", "value"}
)


def _is_sha256_wire_value(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", value) is not None


def _reject_digest_shaped_public_values(value: object, *, path: str) -> None:
    if _is_sha256_wire_value(value):
        raise ProtocolViolation(
            f"{path}: digest-shaped judge-private value is forbidden"
        )
    if type(value) is dict:
        for key, child in value.items():
            assert type(key) is str
            _reject_digest_shaped_public_values(child, path=f"{path}.{key}")
    elif type(value) is list:
        for index, child in enumerate(value):
            _reject_digest_shaped_public_values(
                child,
                path=f"{path}[{index}]",
            )


def _validate_typed_public_event_payload(
    event: dict[str, Any],
    *,
    path: str,
) -> None:
    kind = event["kind"]
    payload = event["payload"]
    allowed = _PUBLIC_EVENT_PAYLOAD_KEYS.get(kind)
    if allowed is None:
        raise ProtocolViolation(f"{path}.kind: unknown public event kind")
    unknown = set(payload) - allowed
    if unknown:
        raise ProtocolViolation(
            f"{path}.payload.{sorted(unknown)[0]}: judge-private field is forbidden"
        )
    string_fields = (
        "action_id",
        "channel_id",
        "check_id",
        "control_kind",
        "order_uid",
        "schema_version",
        "specimen_uid",
    )
    for field_name in string_fields:
        if field_name in payload and (
            type(payload[field_name]) is not str or not payload[field_name]
        ):
            raise ProtocolViolation(
                f"{path}.payload.{field_name} must be a typed public string"
            )
    if "stopped_action_id" in payload and (
        payload["stopped_action_id"] is not None
        and (
            type(payload["stopped_action_id"]) is not str
            or not payload["stopped_action_id"]
        )
    ):
        raise ProtocolViolation(
            f"{path}.payload.stopped_action_id must be null or a public string"
        )
    for field_name in ("assay_slot", "course_microticks"):
        if field_name in payload and type(payload[field_name]) is not int:
            raise ProtocolViolation(
                f"{path}.payload.{field_name} must be a typed public integer"
            )
    for field_name in ("dose",):
        if field_name in payload and type(payload[field_name]) not in {int, float}:
            raise ProtocolViolation(
                f"{path}.payload.{field_name} must be a typed public number"
            )
    for field_name in ("marker", "signal", "value"):
        if field_name in payload and type(payload[field_name]) not in {
            bool,
            int,
            float,
            str,
        }:
            raise ProtocolViolation(
                f"{path}.payload.{field_name} must be a typed public scalar"
            )
    if "parameters" in payload:
        parameters = payload["parameters"]
        if type(parameters) is not dict:
            raise ProtocolViolation(
                f"{path}.payload.parameters must be a typed public object"
            )
        unknown_parameters = set(parameters) - _PUBLIC_PARAMETER_KEYS
        if unknown_parameters:
            raise ProtocolViolation(
                f"{path}.payload.parameters.{sorted(unknown_parameters)[0]}: "
                "judge-private field is forbidden"
            )
        for key, value in parameters.items():
            if key == "result_available_offset":
                valid_value = type(value) is int
            elif key == "dose":
                valid_value = type(value) in {int, float}
            else:
                valid_value = type(value) is str and bool(value)
            if not valid_value:
                raise ProtocolViolation(
                    f"{path}.payload.parameters.{key} has the wrong public type"
                )
    if "results" in payload:
        results = payload["results"]
        if type(results) is not list:
            raise ProtocolViolation(
                f"{path}.payload.results must be a typed public result list"
            )
        for index, result in enumerate(results):
            if type(result) is not dict:
                raise ProtocolViolation(
                    f"{path}.payload.results[{index}] must be a typed public result"
                )
            unknown_result = set(result) - _PUBLIC_RESULT_KEYS
            if unknown_result:
                raise ProtocolViolation(
                    f"{path}.payload.results[{index}].{sorted(unknown_result)[0]}: "
                    "judge-private field is forbidden"
                )
            if "channel_id" not in result or "value" not in result:
                raise ProtocolViolation(
                    f"{path}.payload.results[{index}] lacks channel_id/value"
                )
            if type(result["channel_id"]) is not str or not result["channel_id"]:
                raise ProtocolViolation(
                    f"{path}.payload.results[{index}].channel_id has the wrong public type"
                )
            if type(result["value"]) not in {bool, int, float, str}:
                raise ProtocolViolation(
                    f"{path}.payload.results[{index}].value has the wrong public type"
                )
            if "assay_slot" in result and type(result["assay_slot"]) is not int:
                raise ProtocolViolation(
                    f"{path}.payload.results[{index}].assay_slot has the wrong public type"
                )
            if "specimen_uid" in result and (
                type(result["specimen_uid"]) is not str
                or not result["specimen_uid"]
            ):
                raise ProtocolViolation(
                    f"{path}.payload.results[{index}].specimen_uid has the wrong public type"
                )
    _reject_digest_shaped_public_values(payload, path=f"{path}.payload")


def _normalized_protocol_key(key: str) -> str:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    snake = re.sub(r"[^A-Za-z0-9]+", "_", snake)
    return snake.strip("_").lower()


def _reject_reserved_public_scalar_namespace(
    value: object,
    *,
    path: str,
) -> None:
    """Reject judge/control-plane strings at every public scalar position."""

    def walk(node: object, where: str) -> None:
        if type(node) is str:
            normalized = _normalized_protocol_key(node)
            tokens = frozenset(normalized.split("_"))
            if (
                normalized in _PUBLIC_SCALAR_RESERVED_EXACT
                or bool(tokens & _PUBLIC_SCALAR_RESERVED_TOKENS)
            ):
                raise ProtocolViolation(
                    f"{where}: judge-private scalar namespace is forbidden"
                )
        elif type(node) is dict:
            for key, child in node.items():
                assert type(key) is str
                walk(child, f"{where}.{key}")
        elif type(node) is list:
            for index, child in enumerate(node):
                walk(child, f"{where}[{index}]")

    walk(value, path)


def _reject_reserved_public_payload_namespace(
    value: object,
    *,
    path: str,
) -> None:
    def walk(node: object, where: str) -> None:
        if type(node) is dict:
            for key, child in node.items():
                # validate_json_like has already established string keys.
                assert type(key) is str
                normalized = _normalized_protocol_key(key)
                tokens = frozenset(normalized.split("_"))
                if (
                    normalized not in _PUBLIC_PAYLOAD_RESERVED_KEY_ALLOWLIST
                    and (
                        "digest" in tokens
                        or "digests" in tokens
                        or tokens & _PUBLIC_PAYLOAD_RESERVED_TOKENS
                        or normalized.startswith("query_contract_")
                        or normalized == "query_contract"
                    )
                ):
                    raise ProtocolViolation(
                        f"{where}.{key}: judge-private field is forbidden"
                    )
                walk(child, f"{where}.{key}")
        elif type(node) is list:
            for index, child in enumerate(node):
                walk(child, f"{where}[{index}]")

    walk(value, path)

def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _world_slot(value: object, label: str = "world_slot") -> str:
    value = _name(value, label)
    if not re.fullmatch(r"W(?:0[1-9]|1[0-9]|20)", value):
        raise ProtocolViolation(f"{label} must be one of W01..W20")
    return value


def _label(value: object, label: str = "stratum label") -> str:
    value = _name(value, label)
    if not _LABEL_RE.fullmatch(value) or value not in KNOWN_STRATA:
        raise ProtocolViolation(f"{label} is not a known benchmark-v1 stratum")
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


def _sorted_wire(values: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        item.to_wire()
        for item in sorted(values, key=lambda item: canonical_json_bytes(item.to_wire()))
    ]


def _safe_public_history(value: object) -> dict[str, Any]:
    if type(value) is not VisibleHistory:
        raise ProtocolViolation("public history must be an exact VisibleHistory")
    # VisibleHistory validates tuple ordering and the cut, but its current
    # schema constructor does not recursively revalidate already-created event
    # objects.  A frozen event can still be rewritten via object.__setattr__;
    # every authority boundary must therefore re-enter the exact event schema.
    for event in value.events:
        event.__post_init__()
    value.__post_init__()
    wire = value.to_wire()
    validate_json_like(wire, path="public history")
    reject_privileged_keys(
        wire,
        forbidden=_PUBLIC_HISTORY_FORBIDDEN,
        path="public history",
    )
    for index, event in enumerate(wire["events"]):
        _validate_typed_public_event_payload(
            event,
            path=f"public history.events[{index}]",
        )
        _reject_reserved_public_payload_namespace(
            event["payload"],
            path=f"public history.events[{index}].payload",
        )
        _reject_digest_shaped_public_values(
            event["event_uid"],
            path=f"public history.events[{index}].event_uid",
        )
        _reject_reserved_public_scalar_namespace(
            event["event_uid"],
            path=f"public history.events[{index}].event_uid",
        )
        _reject_reserved_public_scalar_namespace(
            event["payload"],
            path=f"public history.events[{index}].payload",
        )
    return wire


def _canonical_labels(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(item) is not str for item in value):
        raise ProtocolViolation(f"{label} must be tuple[str, ...]")
    for item in value:
        _label(item, label)
    if len(value) != len(set(value)):
        raise ProtocolViolation(f"{label} must not contain duplicate labels")
    if value != _sort_labels(value):
        raise ProtocolViolation(f"{label} must be in canonical benchmark order")
    return value


def _sort_labels(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(values, key=lambda item: _STRATUM_ORDER_INDEX[item]))


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


def _assignment_for_validated_unchecked(
    assignment: WeightedAtomicAssignment,
    authority_digest: str,
) -> Any | None:
    """Lookup after the enclosing authority performed one strict validation."""

    return next(
        (
            item
            for item in assignment.assignments
            if item.authority_digest == authority_digest
        ),
        None,
    )


class StrataScaffoldStatus(str, Enum):
    PRE_FREEZE_SCAFFOLD = "pre_freeze_scaffold"
    INCOMPLETE = "incomplete"


class StratumChannel(str, Enum):
    PUBLIC_REPLAYABLE = "public_replayable"
    JUDGE_ONLY_FROZEN = "judge_only_frozen"
    DUAL_CONJUNCTION = "dual_conjunction"


class PublicRuleKind(str, Enum):
    ALWAYS = "always"
    W03_VISIBLE_SPARSE_HISTORY = "w03_visible_sparse_history"
    W10_VISIBLE_Q1_SUBSET_1_2 = "w10_visible_q1_subset_1_2"
    W14_VISIBLE_OBS0_BOUNDARY = "w14_visible_obs0_boundary"
    W15_VISIBLE_PANEL_BOUNDARY = "w15_visible_panel_boundary"
    W16_VISIBLE_OBS0_BOUNDARY = "w16_visible_obs0_boundary"
    W17_VISIBLE_OBS0_BOUNDARY = "w17_visible_obs0_boundary"
    W18_PUBLIC_BOUNDARY_EVIDENCE = "w18_public_boundary_evidence"


class JudgeRuleKind(str, Enum):
    ALLOCATION_DECISION = "code_owned_allocation_decision"
    W10_COMPOSITIONAL_CELL = "w10_frozen_compositional_cell"
    W18_MECHANISM_OOD = "w18_frozen_mechanism_ood"
    W18_BOUNDARY_CELL = "w18_frozen_boundary_cell"
    W19_BOUNDARY_TAIL = "w19_frozen_boundary_tail"
    W20_RESPONSE_REVERSAL_BOUNDARY = "w20_response_reversal_boundary"
    FAMILY_BEHAVIOR_PAIR = "family_behavior_pair_topology"


class AllocationDimension(str, Enum):
    BOUNDARY_TAIL = "boundary_tail"
    COMPOSITIONAL_HOLDOUT = "compositional_holdout"
    SCHEDULE_TIME_HOLDOUT = "schedule_time_holdout"
    POLICY_COVERAGE_HOLDOUT = "policy_coverage_holdout"
    EXTENSION_CHECK = "extension_check"
    EXTENSION_TREATMENT = "extension_treatment"
    MECHANISM_OOD = "mechanism_ood"


class AllocationCellValue(str, Enum):
    SUPPORT = "support"
    HOLDOUT = "holdout"
    HELDOUT_HOST_MECHANISM = "heldout_host_mechanism"
    FROZEN_BOUNDARY = "frozen_boundary"
    KNOWN_MECHANISM = "known_mechanism"
    DEVELOPMENT_ANOMALY_MECHANISM = "development_anomaly_mechanism"
    SEALED_NOVEL_MECHANISM = "sealed_novel_mechanism"
    COMMON = "common"
    RARE_TAIL = "rare_tail"


def _channel_wire(value: StratumChannel) -> str:
    mapping = {
        StratumChannel.PUBLIC_REPLAYABLE: "public_replayable",
        StratumChannel.JUDGE_ONLY_FROZEN: "judge_only_frozen",
        StratumChannel.DUAL_CONJUNCTION: "dual_conjunction",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("stratum channel enum identity is invalid") from exc


def _public_rule_kind_wire(value: PublicRuleKind) -> str:
    mapping = {
        PublicRuleKind.ALWAYS: "always",
        PublicRuleKind.W03_VISIBLE_SPARSE_HISTORY: "w03_visible_sparse_history",
        PublicRuleKind.W10_VISIBLE_Q1_SUBSET_1_2: "w10_visible_q1_subset_1_2",
        PublicRuleKind.W14_VISIBLE_OBS0_BOUNDARY: "w14_visible_obs0_boundary",
        PublicRuleKind.W15_VISIBLE_PANEL_BOUNDARY: "w15_visible_panel_boundary",
        PublicRuleKind.W16_VISIBLE_OBS0_BOUNDARY: "w16_visible_obs0_boundary",
        PublicRuleKind.W17_VISIBLE_OBS0_BOUNDARY: "w17_visible_obs0_boundary",
        PublicRuleKind.W18_PUBLIC_BOUNDARY_EVIDENCE: "w18_public_boundary_evidence",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("public rule enum identity is invalid") from exc


def _judge_rule_kind_wire(value: JudgeRuleKind) -> str:
    mapping = {
        JudgeRuleKind.ALLOCATION_DECISION: "code_owned_allocation_decision",
        JudgeRuleKind.W10_COMPOSITIONAL_CELL: "w10_frozen_compositional_cell",
        JudgeRuleKind.W18_MECHANISM_OOD: "w18_frozen_mechanism_ood",
        JudgeRuleKind.W18_BOUNDARY_CELL: "w18_frozen_boundary_cell",
        JudgeRuleKind.W19_BOUNDARY_TAIL: "w19_frozen_boundary_tail",
        JudgeRuleKind.W20_RESPONSE_REVERSAL_BOUNDARY: (
            "w20_response_reversal_pair_topology"
        ),
        JudgeRuleKind.FAMILY_BEHAVIOR_PAIR: "family_behavior_pair_topology",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("judge rule enum identity is invalid") from exc


def _allocation_dimension_wire(value: AllocationDimension) -> str:
    mapping = {
        AllocationDimension.BOUNDARY_TAIL: "boundary_tail",
        AllocationDimension.COMPOSITIONAL_HOLDOUT: "compositional_holdout",
        AllocationDimension.SCHEDULE_TIME_HOLDOUT: "schedule_time_holdout",
        AllocationDimension.POLICY_COVERAGE_HOLDOUT: "policy_coverage_holdout",
        AllocationDimension.EXTENSION_CHECK: "extension_check",
        AllocationDimension.EXTENSION_TREATMENT: "extension_treatment",
        AllocationDimension.MECHANISM_OOD: "mechanism_ood",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("allocation dimension enum identity is invalid") from exc


def _allocation_value_wire(value: AllocationCellValue) -> str:
    mapping = {
        AllocationCellValue.SUPPORT: "support",
        AllocationCellValue.HOLDOUT: "holdout",
        AllocationCellValue.HELDOUT_HOST_MECHANISM: "heldout_host_mechanism",
        AllocationCellValue.FROZEN_BOUNDARY: "frozen_boundary",
        AllocationCellValue.KNOWN_MECHANISM: "known_mechanism",
        AllocationCellValue.DEVELOPMENT_ANOMALY_MECHANISM: (
            "development_anomaly_mechanism"
        ),
        AllocationCellValue.SEALED_NOVEL_MECHANISM: "sealed_novel_mechanism",
        AllocationCellValue.COMMON: "common",
        AllocationCellValue.RARE_TAIL: "rare_tail",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ProtocolViolation("allocation cell value enum identity is invalid") from exc


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


_PUBLIC_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "public_strata_classifier",
    "classifier source custody and independent replay sealing are not yet available",
)
_JUDGE_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "judge_strata_authority",
    "typed per-slot allocation is structurally committed, but independent generator "
    "custody and atomic publication are not yet available",
)
_ALLOCATION_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "pre_split_strata_allocation_manifest",
    "typed slot commitments are structurally bound but builder custody and atomic "
    "publication are not independently sealed",
)
_DUAL_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "dual_channel_strata_authority",
    "public and judge manifests are structurally joined but not atomically sealed or published",
)
_PUBLIC_RESULT_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "public_strata_result",
    "public replay result is not yet emitted by an independently sealed classifier runtime",
)
_JUDGE_RESULT_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "judge_strata_result",
    "judge classification is not yet emitted from a sealed hidden-corpus runtime",
)
_RECEIPT_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "strata_row_receipt",
    "raw ledger, corpus materializer, and dual-channel receipt publication "
    "are not independently sealed",
)
_BATCH_BLOCKER = ScaffoldBlocker(
    INCOMPLETE_CODE,
    "strata_receipt_batch",
    "expected joins are checked but the raw corpus ledger and atomic batch seal "
    "are not integrated",
)


def _w10_visible_q1_subset_1_2(history: dict[str, Any]) -> bool:
    grouped: dict[tuple[int | None, int], set[int]] = {}
    for event in history.get("events", []):
        if (
            type(event) is not dict
            or event.get("kind") != "observation_available"
        ):
            continue
        payload = event.get("payload")
        if type(payload) is not dict or payload.get("check_id") != "Q1":
            continue
        assay_slot = payload.get("assay_slot")
        available_at = event.get("available_at")
        collected_at = event.get("collected_at")
        if (
            type(assay_slot) is not int
            or type(available_at) is not int
            or collected_at is not None
            and type(collected_at) is not int
        ):
            continue
        grouped.setdefault((collected_at, available_at), set()).add(assay_slot)
    return any(slots == {1, 2} for slots in grouped.values())


def _numeric_observation_values(
    history: dict[str, Any],
    channel_id: str,
) -> tuple[float, ...]:
    values: list[float] = []
    for event in history.get("events", []):
        if (
            type(event) is not dict
            or event.get("kind") != "observation_available"
        ):
            continue
        payload = event.get("payload")
        if type(payload) is not dict or payload.get("channel_id") != channel_id:
            continue
        value = payload.get("value")
        if type(value) in {int, float}:
            values.append(float(value))
    return tuple(values)


def _w03_visible_sparse_history(history: dict[str, Any]) -> bool:
    """Replay W03's exact missing-t=-2 obs_0 construction, fail closed."""

    timing: list[tuple[int, int]] = []
    for event in history.get("events", []):
        if (
            type(event) is not dict
            or event.get("kind") != "observation_available"
        ):
            continue
        payload = event.get("payload")
        if type(payload) is not dict or payload.get("channel_id") != "obs_0":
            continue
        collected_at = event.get("collected_at")
        available_at = event.get("available_at")
        if type(collected_at) is not int or type(available_at) is not int:
            return False
        timing.append((collected_at, available_at))
    return tuple(sorted(timing)) == ((-4, -4), (-3, -3), (-1, -1), (0, 0))


def _w14_visible_obs0_boundary(history: dict[str, Any]) -> bool:
    return any(
        value <= 0.05 or value >= 1.0
        for value in _numeric_observation_values(history, "obs_0")
    )


# These are the canonical public catalog identities emitted by World15A and
# World15B.  W15 is one registry slot with two panels and the numeric boundary
# predicates are intentionally different; event-count heuristics or a union of
# the thresholds would silently cross-label the other panel.  Live world
# cross-regression below the authority layer locks these digests to the served
# catalogs.
_W15A_PUBLIC_CATALOG_DIGEST = (
    "sha256:66dc290571db7b5c9970c21f321da322ebfcc8cf9dccfe92810a8cd33e356d63"
)
_W15B_PUBLIC_CATALOG_DIGEST = (
    "sha256:ba2767aba2c22745530e061a1f8fd16c55c33f0ff83e3975165134eaebbd5c13"
)


def _w15_visible_panel_boundary(history: dict[str, Any]) -> bool:
    """Replay distinct W15A/W15B predicates under the bound public catalog."""

    obs0 = _numeric_observation_values(history, "obs_0")
    catalog_digest = history.get("catalog_digest")
    if catalog_digest == _W15A_PUBLIC_CATALOG_DIGEST:
        return bool(obs0) and any(
            value <= 0.20 or value >= 1.20 for value in obs0
        )
    if catalog_digest == _W15B_PUBLIC_CATALOG_DIGEST and len(obs0) == 1:
        return abs(obs0[0]) >= 0.90
    return False


def _w16_visible_obs0_boundary(history: dict[str, Any]) -> bool:
    return any(
        value <= 0.0 or value >= 1.25
        for value in _numeric_observation_values(history, "obs_0")
    )


def _w17_visible_obs0_boundary(history: dict[str, Any]) -> bool:
    return any(
        value <= 0.0 or value >= 1.25
        for value in _numeric_observation_values(history, "obs_0")
    )


def _w18_public_boundary_evidence(history: dict[str, Any]) -> bool:
    latest: dict[str, float] = {}
    for event in history.get("events", []):
        if (
            type(event) is not dict
            or event.get("kind") != "observation_available"
        ):
            continue
        payload = event.get("payload")
        if type(payload) is not dict:
            continue
        channel = payload.get("channel_id")
        value = payload.get("value")
        if channel in {"obs_0", "obs_1"} and type(value) in {int, float}:
            latest[channel] = float(value)
    if set(latest) != {"obs_0", "obs_1"}:
        return False
    obs_0, obs_1 = latest["obs_0"], latest["obs_1"]
    known_support = (
        abs(obs_1 - obs_0) <= 0.060000000001
        or abs(obs_1 + obs_0) <= 0.060000000001
    )
    known_extreme_public = max(abs(obs_0), abs(obs_1)) >= 1.20
    return not known_support or known_extreme_public
@dataclass(frozen=True, slots=True)
class PublicRule:
    """Closed code-owned evaluator over candidate-visible history."""

    kind: PublicRuleKind
    path: tuple[str | int, ...] = ()
    operands: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if type(self.kind) is not PublicRuleKind:
            raise ProtocolViolation("public rule kind must be PublicRuleKind")
        if type(self.path) is not tuple or type(self.operands) is not tuple:
            raise ProtocolViolation(
                "public rule path/operands must be exact tuples"
            )
        if self.path or self.operands:
            raise ProtocolViolation(
                "public rules are code-owned and accept no caller path or operands"
            )
        if self.kind not in {
            PublicRuleKind.ALWAYS,
            PublicRuleKind.W03_VISIBLE_SPARSE_HISTORY,
            PublicRuleKind.W10_VISIBLE_Q1_SUBSET_1_2,
            PublicRuleKind.W14_VISIBLE_OBS0_BOUNDARY,
            PublicRuleKind.W15_VISIBLE_PANEL_BOUNDARY,
            PublicRuleKind.W16_VISIBLE_OBS0_BOUNDARY,
            PublicRuleKind.W17_VISIBLE_OBS0_BOUNDARY,
            PublicRuleKind.W18_PUBLIC_BOUNDARY_EVIDENCE,
        }:
            raise ProtocolViolation("unsupported public rule kind")

    def evaluate(self, history: VisibleHistory) -> bool:
        self.__post_init__()
        wire = _safe_public_history(history)
        return self._evaluate_wire_unchecked(wire)

    def _evaluate_wire_unchecked(self, wire: dict[str, Any]) -> bool:
        if self.kind is PublicRuleKind.ALWAYS:
            return True
        if self.kind is PublicRuleKind.W03_VISIBLE_SPARSE_HISTORY:
            return _w03_visible_sparse_history(wire)
        if self.kind is PublicRuleKind.W10_VISIBLE_Q1_SUBSET_1_2:
            return _w10_visible_q1_subset_1_2(wire)
        if self.kind is PublicRuleKind.W14_VISIBLE_OBS0_BOUNDARY:
            return _w14_visible_obs0_boundary(wire)
        if self.kind is PublicRuleKind.W15_VISIBLE_PANEL_BOUNDARY:
            return _w15_visible_panel_boundary(wire)
        if self.kind is PublicRuleKind.W16_VISIBLE_OBS0_BOUNDARY:
            return _w16_visible_obs0_boundary(wire)
        if self.kind is PublicRuleKind.W17_VISIBLE_OBS0_BOUNDARY:
            return _w17_visible_obs0_boundary(wire)
        if self.kind is PublicRuleKind.W18_PUBLIC_BOUNDARY_EVIDENCE:
            return _w18_public_boundary_evidence(wire)
        raise ProtocolViolation("unsupported public rule kind")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return self._to_wire_unchecked()

    def _to_wire_unchecked(self) -> dict[str, Any]:
        return {
            "kind": _public_rule_kind_wire(self.kind),
            "path": list(self.path),
            "operands": list(self.operands),
        }


@dataclass(frozen=True, slots=True)
class JudgeRule:
    """Code-owned judge rule over typed allocation or family topology."""

    kind: JudgeRuleKind
    fact_key: str | None = None
    match_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.kind) is not JudgeRuleKind:
            raise ProtocolViolation("judge rule kind must be JudgeRuleKind")
        if self.fact_key is not None or self.match_values:
            raise ProtocolViolation(
                "judge rules are code-owned and accept no caller fact key or match values"
            )
        if self.kind not in {
            JudgeRuleKind.ALLOCATION_DECISION,
            JudgeRuleKind.W10_COMPOSITIONAL_CELL,
            JudgeRuleKind.W18_MECHANISM_OOD,
            JudgeRuleKind.W18_BOUNDARY_CELL,
            JudgeRuleKind.W19_BOUNDARY_TAIL,
            JudgeRuleKind.W20_RESPONSE_REVERSAL_BOUNDARY,
            JudgeRuleKind.FAMILY_BEHAVIOR_PAIR,
        }:
            raise ProtocolViolation("unsupported judge rule kind")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return self._to_wire_unchecked()

    def _to_wire_unchecked(self) -> dict[str, Any]:
        return {
            "kind": _judge_rule_kind_wire(self.kind),
            "fact_key": self.fact_key,
            "match_values": list(self.match_values),
        }


@dataclass(frozen=True, slots=True)
class StratumDefinition:
    label: str
    channel: StratumChannel
    public_rule: PublicRule | None = None
    judge_rule: JudgeRule | None = None

    def __post_init__(self) -> None:
        _label(self.label)
        if type(self.channel) is not StratumChannel:
            raise ProtocolViolation("stratum definition channel is invalid")
        if self.channel is StratumChannel.PUBLIC_REPLAYABLE:
            if type(self.public_rule) is not PublicRule or self.judge_rule is not None:
                raise ProtocolViolation(
                    "public stratum needs exactly one PublicRule and no JudgeRule"
                )
            self.public_rule.__post_init__()
        elif self.channel is StratumChannel.JUDGE_ONLY_FROZEN:
            if type(self.judge_rule) is not JudgeRule or self.public_rule is not None:
                raise ProtocolViolation(
                    "judge stratum needs exactly one JudgeRule and no PublicRule"
                )
            self.judge_rule.__post_init__()
        elif self.channel is StratumChannel.DUAL_CONJUNCTION:
            if type(self.public_rule) is not PublicRule or type(
                self.judge_rule
            ) is not JudgeRule:
                raise ProtocolViolation(
                    "dual stratum needs both a PublicRule and a JudgeRule"
                )
            self.public_rule.__post_init__()
            self.judge_rule.__post_init__()
        else:  # pragma: no cover
            raise ProtocolViolation("unsupported stratum channel")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "label": self.label,
            "channel": _channel_wire(self.channel),
            "public_rule": self.public_rule.to_wire() if self.public_rule else None,
            "judge_rule": self.judge_rule.to_wire() if self.judge_rule else None,
        }


def _validate_definition_set(
    definitions: tuple[StratumDefinition, ...],
    *,
    channel: StratumChannel,
    non_empty: bool,
    label: str,
) -> None:
    _tuple_of_exact(definitions, StratumDefinition, label, non_empty=non_empty)
    for definition in definitions:
        definition.__post_init__()
        if definition.channel not in {channel, StratumChannel.DUAL_CONJUNCTION}:
            raise ProtocolViolation(f"{label} contains a definition for the wrong channel")
    labels = [item.label for item in definitions]
    if len(labels) != len(set(labels)):
        raise ProtocolViolation(f"{label} contains duplicate labels")


_BOUNDARY_CHANNEL_BY_WORLD: dict[str, StratumChannel] = {
    "W01": StratumChannel.JUDGE_ONLY_FROZEN,
    "W02": StratumChannel.JUDGE_ONLY_FROZEN,
    "W03": StratumChannel.PUBLIC_REPLAYABLE,
    "W04": StratumChannel.JUDGE_ONLY_FROZEN,
    "W05": StratumChannel.JUDGE_ONLY_FROZEN,
    "W06": StratumChannel.JUDGE_ONLY_FROZEN,
    "W07": StratumChannel.JUDGE_ONLY_FROZEN,
    "W08": StratumChannel.JUDGE_ONLY_FROZEN,
    "W09": StratumChannel.JUDGE_ONLY_FROZEN,
    "W10": StratumChannel.JUDGE_ONLY_FROZEN,
    "W11": StratumChannel.JUDGE_ONLY_FROZEN,
    "W12": StratumChannel.JUDGE_ONLY_FROZEN,
    "W13": StratumChannel.JUDGE_ONLY_FROZEN,
    "W14": StratumChannel.PUBLIC_REPLAYABLE,
    "W15": StratumChannel.PUBLIC_REPLAYABLE,
    "W16": StratumChannel.PUBLIC_REPLAYABLE,
    "W17": StratumChannel.PUBLIC_REPLAYABLE,
    "W18": StratumChannel.DUAL_CONJUNCTION,
    "W19": StratumChannel.JUDGE_ONLY_FROZEN,
    "W20": StratumChannel.JUDGE_ONLY_FROZEN,
}

_PUBLIC_RULE_KIND_BY_WORLD_LABEL: dict[tuple[str, str], PublicRuleKind] = {
    ("W03", "boundary_tail"): PublicRuleKind.W03_VISIBLE_SPARSE_HISTORY,
    ("W10", "compositional_holdout"): (
        PublicRuleKind.W10_VISIBLE_Q1_SUBSET_1_2
    ),
    ("W14", "boundary_tail"): PublicRuleKind.W14_VISIBLE_OBS0_BOUNDARY,
    ("W15", "boundary_tail"): PublicRuleKind.W15_VISIBLE_PANEL_BOUNDARY,
    ("W16", "boundary_tail"): PublicRuleKind.W16_VISIBLE_OBS0_BOUNDARY,
    ("W16", "extension_check"): PublicRuleKind.ALWAYS,
    ("W17", "boundary_tail"): PublicRuleKind.W17_VISIBLE_OBS0_BOUNDARY,
    ("W17", "extension_treatment"): PublicRuleKind.ALWAYS,
    ("W18", "boundary_tail"): PublicRuleKind.W18_PUBLIC_BOUNDARY_EVIDENCE,
}


def _required_channel(world_slot: str, label: str) -> StratumChannel:
    """Return the exact code-owned W01--W20 authority channel table."""

    _world_slot(world_slot)
    _label(label)
    if label not in WORLD_DECLARED_STRATA[world_slot]:
        raise ProtocolViolation(f"{world_slot} does not declare stratum {label}")
    if label == "iid_support":
        return StratumChannel.PUBLIC_REPLAYABLE
    if label == "behavior_pair":
        return StratumChannel.JUDGE_ONLY_FROZEN
    if label == "boundary_tail":
        return _BOUNDARY_CHANNEL_BY_WORLD[world_slot]
    if (world_slot, label) == ("W10", "compositional_holdout"):
        # Public assay subset AND the pre-split allocation cell for this label.
        return StratumChannel.DUAL_CONJUNCTION
    if (world_slot, label) in {
        ("W16", "extension_check"),
        ("W17", "extension_treatment"),
    }:
        return StratumChannel.PUBLIC_REPLAYABLE
    return StratumChannel.JUDGE_ONLY_FROZEN


def _code_owned_public_rule(world_slot: str, label: str) -> PublicRule:
    if label == "iid_support":
        return PublicRule(PublicRuleKind.ALWAYS)
    kind = _PUBLIC_RULE_KIND_BY_WORLD_LABEL.get((world_slot, label))
    if kind is None or _required_channel(world_slot, label) not in {
        StratumChannel.PUBLIC_REPLAYABLE,
        StratumChannel.DUAL_CONJUNCTION,
    }:
        raise ProtocolViolation(f"{world_slot} {label} has no public rule")
    return PublicRule(kind)


def _validate_typed_public_definition(
    world_slot: str,
    definition: StratumDefinition,
) -> None:
    assert definition.public_rule is not None
    expected = _code_owned_public_rule(world_slot, definition.label)
    if definition.public_rule != expected:
        raise ProtocolViolation(
            f"{world_slot} {definition.label} must use its code-owned public rule"
        )


def _code_owned_judge_rule(world_slot: str, label: str) -> JudgeRule:
    if _required_channel(world_slot, label) is StratumChannel.PUBLIC_REPLAYABLE:
        raise ProtocolViolation(f"{world_slot} {label} has no judge rule")
    if label == "behavior_pair":
        return JudgeRule(JudgeRuleKind.FAMILY_BEHAVIOR_PAIR)
    special = {
        ("W10", "compositional_holdout"): JudgeRuleKind.W10_COMPOSITIONAL_CELL,
        ("W18", "boundary_tail"): JudgeRuleKind.W18_BOUNDARY_CELL,
        ("W18", "mechanism_ood"): JudgeRuleKind.W18_MECHANISM_OOD,
        ("W19", "boundary_tail"): JudgeRuleKind.W19_BOUNDARY_TAIL,
        ("W20", "boundary_tail"): (
            JudgeRuleKind.W20_RESPONSE_REVERSAL_BOUNDARY
        ),
    }
    return JudgeRule(
        special.get((world_slot, label), JudgeRuleKind.ALLOCATION_DECISION)
    )


def _validate_typed_judge_definition(
    world_slot: str,
    definition: StratumDefinition,
) -> None:
    assert definition.judge_rule is not None
    expected = _code_owned_judge_rule(world_slot, definition.label)
    if definition.judge_rule != expected:
        raise ProtocolViolation(
            f"{world_slot} {definition.label} must use its code-owned judge rule"
        )


def _code_owned_definition_sets(
    world_slot: str,
) -> tuple[tuple[StratumDefinition, ...], tuple[StratumDefinition, ...]]:
    _world_slot(world_slot)
    public: list[StratumDefinition] = []
    judge: list[StratumDefinition] = []
    for label in WORLD_DECLARED_STRATA[world_slot]:
        channel = _required_channel(world_slot, label)
        public_rule = (
            _code_owned_public_rule(world_slot, label)
            if channel
            in {
                StratumChannel.PUBLIC_REPLAYABLE,
                StratumChannel.DUAL_CONJUNCTION,
            }
            else None
        )
        judge_rule = (
            _code_owned_judge_rule(world_slot, label)
            if channel
            in {
                StratumChannel.JUDGE_ONLY_FROZEN,
                StratumChannel.DUAL_CONJUNCTION,
            }
            else None
        )
        definition = StratumDefinition(
            label,
            channel,
            public_rule=public_rule,
            judge_rule=judge_rule,
        )
        if public_rule is not None:
            public.append(definition)
        if judge_rule is not None:
            judge.append(definition)
    return tuple(public), tuple(judge)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PublicClassifierAuthority:
    benchmark_id: str
    benchmark_revision: str
    world_slot: str
    classifier_id: str
    classifier_version: str
    classifier_source_digest: str
    definitions: tuple[StratumDefinition, ...] = field(init=False)
    _sealed_classifier_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "definitions",
            _code_owned_definition_sets(self.world_slot)[0],
        )
        self._validate(allow_seal_initialization=True)

    def _validate(self, *, allow_seal_initialization: bool = False) -> None:
        _name(self.benchmark_id, "public classifier benchmark_id")
        _name(self.benchmark_revision, "public classifier benchmark_revision")
        _world_slot(self.world_slot, "public classifier world_slot")
        _name(self.classifier_id, "public classifier_id")
        _name(self.classifier_version, "public classifier_version")
        _digest(self.classifier_source_digest, "public classifier_source_digest")
        _validate_definition_set(
            self.definitions,
            channel=StratumChannel.PUBLIC_REPLAYABLE,
            non_empty=True,
            label="public classifier definitions",
        )
        for definition in self.definitions:
            _validate_typed_public_definition(self.world_slot, definition)
        if self.definitions != _code_owned_definition_sets(self.world_slot)[0]:
            raise ProtocolViolation(
                "public classifier definitions are not the code-owned world contract"
            )
        iid = [item for item in self.definitions if item.label == "iid_support"]
        if len(iid) != 1 or iid[0].public_rule is None:
            raise ProtocolViolation("public classifier must define iid_support exactly once")
        if iid[0].public_rule.kind is not PublicRuleKind.ALWAYS:
            raise ProtocolViolation("iid_support must be a public ALWAYS rule")
        expected_digest = self._classifier_digest_unchecked()
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_classifier_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="public classifier seal is missing",
            changed_message="public classifier authority changed after construction",
        )

    @property
    def definition_contract_digest(self) -> str:
        self._validate()
        return self._definition_contract_digest_unchecked()

    def _definition_contract_digest_unchecked(self) -> str:
        return digest_json(
            {
                "schema_version": "ucm-public-strata-definition-contract/1",
                "world_slot": self.world_slot,
                "definitions": _sorted_wire(self.definitions),
            }
        )

    def _body(self) -> dict[str, Any]:
        self._validate()
        return self._body_unchecked()

    def _body_unchecked(self) -> dict[str, Any]:
        body = {
            "schema_version": PUBLIC_CLASSIFIER_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_role": "public_classifier_source_unsealed",
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "world_slot": self.world_slot,
            "classifier_id": self.classifier_id,
            "classifier_version": self.classifier_version,
            "classifier_source_digest": self.classifier_source_digest,
            "definition_contract_digest": self._definition_contract_digest_unchecked(),
            "definitions": _sorted_wire(self.definitions),
            "blockers": [_PUBLIC_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def classifier_digest(self) -> str:
        self._validate()
        return self._sealed_classifier_digest

    def _classifier_digest_unchecked(self) -> str:
        return digest_json(self._body_unchecked())

    def to_wire(self) -> dict[str, Any]:
        self._validate()
        body = self._body_unchecked()
        body["classifier_digest"] = self._sealed_classifier_digest
        return body

    def classify(self, public_history: VisibleHistory) -> tuple[str, ...]:
        self._validate()
        wire = _safe_public_history(public_history)
        return self._classify_wire_unchecked(wire)

    def _classify_wire_unchecked(
        self,
        wire: dict[str, Any],
    ) -> tuple[str, ...]:
        labels = [
            definition.label
            for definition in self.definitions
            if definition.public_rule is not None
            and definition.public_rule._evaluate_wire_unchecked(wire)
        ]
        return _sort_labels(labels)


def _entry_digest_from_receipt_digest(
    receipt_digest: str,
    *,
    allocation_manifest_digest: str,
    slot_allocation_entry_digest: str,
) -> str:
    _digest(receipt_digest, "generator allocation receipt digest")
    _digest(allocation_manifest_digest, "generator allocation manifest digest")
    _digest(slot_allocation_entry_digest, "slot allocation entry digest")
    return domain_digest(
        b"UCM\0FROZEN_GENERATOR_ALLOCATION_ENTRY_V3\0",
        (
            receipt_digest.encode("ascii"),
            allocation_manifest_digest.encode("ascii"),
            slot_allocation_entry_digest.encode("ascii"),
        ),
    )


def _family_receipt_sealed_digest_unchecked(
    receipt: MaterializationReceipt,
) -> str:
    # MaterializationReceiptLedger.__post_init__ has already checked each
    # receipt against the shared source/assignment context and its immutable
    # construction seal.  Reading that seal avoids N repeated parent-graph
    # validations while deriving a strata manifest from the validated ledger.
    return object.__getattribute__(receipt, "_sealed_receipt_digest")


def _family_ledger_sealed_digest_unchecked(
    ledger: MaterializationReceiptLedger,
) -> str:
    return object.__getattribute__(ledger, "_sealed_ledger_digest")


_ALLOCATION_DIMENSION_BY_LABEL: dict[str, AllocationDimension] = {
    "boundary_tail": AllocationDimension.BOUNDARY_TAIL,
    "compositional_holdout": AllocationDimension.COMPOSITIONAL_HOLDOUT,
    "schedule_time_holdout": AllocationDimension.SCHEDULE_TIME_HOLDOUT,
    "policy_coverage_holdout": AllocationDimension.POLICY_COVERAGE_HOLDOUT,
    "extension_check": AllocationDimension.EXTENSION_CHECK,
    "extension_treatment": AllocationDimension.EXTENSION_TREATMENT,
    "mechanism_ood": AllocationDimension.MECHANISM_OOD,
}


def _expected_allocation_dimensions(
    world_slot: str,
) -> tuple[AllocationDimension, ...]:
    _world_slot(world_slot)
    return tuple(
        _ALLOCATION_DIMENSION_BY_LABEL[label]
        for label in WORLD_DECLARED_STRATA[world_slot]
        if _required_channel(world_slot, label)
        is not StratumChannel.PUBLIC_REPLAYABLE
        and label != "behavior_pair"
        and (world_slot, label) != ("W20", "boundary_tail")
    )


def _allowed_allocation_values(
    world_slot: str,
    dimension: AllocationDimension,
) -> frozenset[AllocationCellValue]:
    if dimension is AllocationDimension.BOUNDARY_TAIL:
        if world_slot == "W18":
            return frozenset(
                {
                    AllocationCellValue.SUPPORT,
                    AllocationCellValue.FROZEN_BOUNDARY,
                }
            )
        if world_slot == "W19":
            return frozenset(
                {
                    AllocationCellValue.COMMON,
                    AllocationCellValue.RARE_TAIL,
                }
            )
    if (
        world_slot == "W10"
        and dimension is AllocationDimension.COMPOSITIONAL_HOLDOUT
    ):
        return frozenset(
            {
                AllocationCellValue.SUPPORT,
                AllocationCellValue.HELDOUT_HOST_MECHANISM,
            }
        )
    if world_slot == "W18" and dimension is AllocationDimension.MECHANISM_OOD:
        return frozenset(
            {
                AllocationCellValue.KNOWN_MECHANISM,
                AllocationCellValue.DEVELOPMENT_ANOMALY_MECHANISM,
                AllocationCellValue.SEALED_NOVEL_MECHANISM,
            }
        )
    return frozenset(
        {AllocationCellValue.SUPPORT, AllocationCellValue.HOLDOUT}
    )


def _positive_allocation_values(
    world_slot: str,
    dimension: AllocationDimension,
) -> frozenset[AllocationCellValue]:
    if (
        world_slot == "W10"
        and dimension is AllocationDimension.COMPOSITIONAL_HOLDOUT
    ):
        return frozenset({AllocationCellValue.HELDOUT_HOST_MECHANISM})
    if world_slot == "W18" and dimension is AllocationDimension.BOUNDARY_TAIL:
        return frozenset({AllocationCellValue.FROZEN_BOUNDARY})
    if world_slot == "W18" and dimension is AllocationDimension.MECHANISM_OOD:
        return frozenset(
            {
                AllocationCellValue.DEVELOPMENT_ANOMALY_MECHANISM,
                AllocationCellValue.SEALED_NOVEL_MECHANISM,
            }
        )
    if world_slot == "W19" and dimension is AllocationDimension.BOUNDARY_TAIL:
        return frozenset({AllocationCellValue.RARE_TAIL})
    return frozenset({AllocationCellValue.HOLDOUT})


@dataclass(frozen=True, slots=True)
class SlotAllocationCell:
    """One closed, typed allocation decision for one physical source slot."""

    dimension: AllocationDimension
    value: AllocationCellValue

    def __post_init__(self) -> None:
        if type(self.dimension) is not AllocationDimension:
            raise ProtocolViolation(
                "slot allocation dimension must be AllocationDimension"
            )
        if type(self.value) is not AllocationCellValue:
            raise ProtocolViolation(
                "slot allocation value must be AllocationCellValue"
            )

    def to_wire(self) -> dict[str, str]:
        self.__post_init__()
        return {
            "dimension": _allocation_dimension_wire(self.dimension),
            "value": _allocation_value_wire(self.value),
        }


def _validate_cells_for_world(
    world_slot: str,
    cells: tuple[SlotAllocationCell, ...],
) -> tuple[SlotAllocationCell, ...]:
    _world_slot(world_slot)
    _tuple_of_exact(
        cells,
        SlotAllocationCell,
        "slot allocation cells",
    )
    for cell in cells:
        cell.__post_init__()
    expected = _expected_allocation_dimensions(world_slot)
    actual = tuple(cell.dimension for cell in cells)
    if actual != expected:
        raise ProtocolViolation(
            "slot allocation cells must exactly cover the code-owned world "
            "dimensions in canonical order"
        )
    if len(actual) != len(set(actual)):
        raise ProtocolViolation(
            "slot allocation cells contain a duplicate dimension"
        )
    for cell in cells:
        if cell.value not in _allowed_allocation_values(
            world_slot,
            cell.dimension,
        ):
            raise ProtocolViolation(
                f"{world_slot} {_allocation_dimension_wire(cell.dimension)} "
                "has an invalid closed allocation value"
            )
    if world_slot == "W13":
        by_dimension = {cell.dimension: cell.value for cell in cells}
        boundary = by_dimension[AllocationDimension.BOUNDARY_TAIL]
        compositional = by_dimension[AllocationDimension.COMPOSITIONAL_HOLDOUT]
        if (boundary is AllocationCellValue.HOLDOUT) != (
            compositional is AllocationCellValue.HOLDOUT
        ):
            raise ProtocolViolation(
                "W13 threshold-shell must bind boundary_tail and "
                "compositional_holdout together"
            )
    if world_slot == "W20":
        mutually_exclusive = {
            AllocationDimension.COMPOSITIONAL_HOLDOUT,
            AllocationDimension.SCHEDULE_TIME_HOLDOUT,
            AllocationDimension.POLICY_COVERAGE_HOLDOUT,
        }
        positive_count = sum(
            cell.dimension in mutually_exclusive
            and cell.value is AllocationCellValue.HOLDOUT
            for cell in cells
        )
        if positive_count > 1:
            raise ProtocolViolation(
                "W20 slot may belong to at most one of compositional, schedule, "
                "and policy holdouts"
            )
    return cells


def _slot_allocation_commitment_body(
    world_slot: str,
    cells: tuple[SlotAllocationCell, ...],
) -> dict[str, Any]:
    _validate_cells_for_world(world_slot, cells)
    body = {
        "schema_version": SLOT_ALLOCATION_COMMITMENT_PROTOCOL,
        "world_slot": world_slot,
        "cells": [cell.to_wire() for cell in cells],
    }
    validate_json_like(body)
    return body


def compute_slot_strata_allocation_commitment(
    world_slot: str,
    cells: tuple[SlotAllocationCell, ...],
) -> str:
    """Hash a typed allocation before the family source or split exists.

    The returned digest is placed on ``MaterializationSlotDraft``.  It thereby
    enters the resolved slot, source, and later assignment digest.  The
    separate manifest reveals the exact typed cells and proves that they match
    that pre-split commitment.
    """

    return digest_json(_slot_allocation_commitment_body(world_slot, cells))


@dataclass(frozen=True, slots=True)
class SlotAllocationDraft:
    materialization_slot_digest: str
    cells: tuple[SlotAllocationCell, ...]

    def __post_init__(self) -> None:
        _digest(
            self.materialization_slot_digest,
            "slot allocation draft materialization_slot_digest",
        )
        _tuple_of_exact(
            self.cells,
            SlotAllocationCell,
            "slot allocation draft cells",
        )
        for cell in self.cells:
            cell.__post_init__()


def _slot_allocation_entry_body(
    slot: MaterializationSlot,
    cells: tuple[SlotAllocationCell, ...],
    allocation_commitment_digest: str,
) -> dict[str, Any]:
    _digest(
        allocation_commitment_digest,
        "frozen slot allocation commitment digest",
    )
    body = {
        "schema_version": SLOT_ALLOCATION_ENTRY_PROTOCOL,
        "materialization_slot": slot.to_wire(),
        "allocation_commitment_digest": allocation_commitment_digest,
        "cells": [cell.to_wire() for cell in cells],
    }
    validate_json_like(body)
    return body


def _slot_allocation_entry_digest(
    slot: MaterializationSlot,
    cells: tuple[SlotAllocationCell, ...],
    allocation_commitment_digest: str,
) -> str:
    return domain_digest(
        b"UCM\0PRE_SPLIT_STRATA_SLOT_ALLOCATION_V1\0",
        (
            canonical_json_bytes(
                _slot_allocation_entry_body(
                    slot,
                    cells,
                    allocation_commitment_digest,
                )
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class FrozenSlotAllocation:
    materialization_slot: MaterializationSlot
    cells: tuple[SlotAllocationCell, ...]
    allocation_commitment_digest: str
    slot_allocation_entry_digest: str

    def __post_init__(self) -> None:
        if type(self.materialization_slot) is not MaterializationSlot:
            raise ProtocolViolation(
                "frozen slot allocation requires an exact MaterializationSlot"
            )
        self.materialization_slot.__post_init__()
        _tuple_of_exact(
            self.cells,
            SlotAllocationCell,
            "frozen slot allocation cells",
        )
        for cell in self.cells:
            cell.__post_init__()
        _digest(
            self.allocation_commitment_digest,
            "frozen slot allocation commitment digest",
        )
        _digest(
            self.slot_allocation_entry_digest,
            "frozen slot allocation entry digest",
        )

    @property
    def materialization_slot_digest(self) -> str:
        return self.materialization_slot.slot_digest

    def _validate_for(
        self,
        world_slot: str,
        expected_slot: MaterializationSlot,
    ) -> None:
        self.__post_init__()
        if self.materialization_slot is not expected_slot:
            raise ProtocolViolation(
                "frozen slot allocation is not builder-resolved from its family source"
            )
        _validate_cells_for_world(world_slot, self.cells)
        expected_commitment = compute_slot_strata_allocation_commitment(
            world_slot,
            self.cells,
        )
        if self.allocation_commitment_digest != expected_commitment:
            raise ProtocolViolation(
                "slot allocation cells do not match their typed commitment"
            )
        if (
            expected_slot.strata_allocation_commitment_digest
            != expected_commitment
        ):
            raise ProtocolViolation(
                "slot allocation commitment is not bound into the pre-split slot"
            )
        expected_entry_digest = _slot_allocation_entry_digest(
            expected_slot,
            self.cells,
            expected_commitment,
        )
        if self.slot_allocation_entry_digest != expected_entry_digest:
            raise ProtocolViolation(
                "slot allocation entry digest is not builder-derived"
            )

    def value_for(self, dimension: AllocationDimension) -> AllocationCellValue:
        if type(dimension) is not AllocationDimension:
            raise ProtocolViolation("allocation lookup dimension has wrong type")
        matches = [cell.value for cell in self.cells if cell.dimension is dimension]
        if len(matches) != 1:
            raise ProtocolViolation(
                "frozen slot allocation lacks an exact typed dimension"
            )
        return matches[0]

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        body = _slot_allocation_entry_body(
            self.materialization_slot,
            self.cells,
            self.allocation_commitment_digest,
        )
        body["slot_allocation_entry_digest"] = (
            self.slot_allocation_entry_digest
        )
        return body


_RECIPE_ALLOCATION_FORBIDDEN_KEYS = frozenset(
    {
        "allocation",
        "allocation_cell",
        "allocation_cells",
        "strata",
        "stratum",
        "stratum_label",
        "stratum_labels",
        "public_strata",
        "judge_strata",
        "judge_frozen_labels",
        "boundary_tail_cell",
        "compositional_holdout_cell",
        "schedule_time_holdout_cell",
        "policy_coverage_holdout_cell",
        "extension_check_cell",
        "extension_treatment_cell",
        "mechanism_ood_cell",
        *KNOWN_STRATA,
    }
)


def _reject_recipe_allocation_authority(source: PreSplitFamilySource) -> None:
    def walk(value: object, path: str) -> None:
        if type(value) is dict:
            for key, child in value.items():
                assert type(key) is str
                normalized = _normalized_protocol_key(key)
                tokens = frozenset(normalized.split("_"))
                if (
                    normalized in _RECIPE_ALLOCATION_FORBIDDEN_KEYS
                    or "strata" in tokens
                    or "stratum" in tokens
                    or "allocation" in tokens
                ):
                    raise ProtocolViolation(
                        f"{path}.{key}: recipe payload cannot supply strata allocation authority"
                    )
                walk(child, f"{path}.{key}")
        elif type(value) is list:
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    for unit in source.units:
        walk(unit.recipe_payload, f"recipe_payload[{unit.unit_alias}]")


def _allocation_schema_digest() -> str:
    worlds: list[dict[str, Any]] = []
    for world_slot in sorted(WORLD_DECLARED_STRATA):
        dimensions = []
        for dimension in _expected_allocation_dimensions(world_slot):
            dimensions.append(
                {
                    "dimension": _allocation_dimension_wire(dimension),
                    "allowed_values": sorted(
                        _allocation_value_wire(value)
                        for value in _allowed_allocation_values(
                            world_slot,
                            dimension,
                        )
                    ),
                    "positive_values": sorted(
                        _allocation_value_wire(value)
                        for value in _positive_allocation_values(
                            world_slot,
                            dimension,
                        )
                    ),
                }
            )
        worlds.append(
            {
                "world_slot": world_slot,
                "dimensions": dimensions,
                "w20_holdout_dimensions_mutually_exclusive": world_slot == "W20",
            }
        )
    return digest_json(
        {
            "schema_version": "ucm-code-owned-strata-allocation-schema/1",
            "worlds": worlds,
        }
    )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PreSplitStrataAllocationManifest:
    """Builder-owned typed slot allocations committed before assignment."""

    family_source: PreSplitFamilySource
    world_slot: str
    generator_source_digest: str
    allocation_policy_digest: str
    builder_id: str
    builder_version: str
    entries: tuple[FrozenSlotAllocation, ...]
    _sealed_manifest_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._validate(allow_seal_initialization=True)

    def _validate(self, *, allow_seal_initialization: bool = False) -> None:
        if type(self.family_source) is not PreSplitFamilySource:
            raise ProtocolViolation(
                "allocation manifest family_source must be PreSplitFamilySource"
            )
        self.family_source._validate()
        _world_slot(self.world_slot, "allocation manifest world_slot")
        _digest(
            self.generator_source_digest,
            "allocation manifest generator_source_digest",
        )
        _digest(
            self.allocation_policy_digest,
            "allocation manifest allocation_policy_digest",
        )
        _name(self.builder_id, "allocation manifest builder_id")
        _name(self.builder_version, "allocation manifest builder_version")
        _tuple_of_exact(
            self.entries,
            FrozenSlotAllocation,
            "allocation manifest entries",
            non_empty=True,
        )
        foreign_worlds = sorted(
            {
                unit.world_slot
                for unit in self.family_source.units
                if unit.world_slot != self.world_slot
            }
        )
        if foreign_worlds:
            raise ProtocolViolation(
                "allocation manifest requires a world-scoped family source; "
                f"foreign_worlds={foreign_worlds}"
            )
        _reject_recipe_allocation_authority(self.family_source)
        source_slots = {
            slot.slot_digest: slot
            for slot in self.family_source.materialization_slots
        }
        if not source_slots:
            raise ProtocolViolation(
                "allocation manifest requires a closed physical slot inventory"
            )
        entry_digests = [
            entry.materialization_slot_digest for entry in self.entries
        ]
        if len(entry_digests) != len(set(entry_digests)):
            raise ProtocolViolation(
                "allocation manifest contains duplicate physical slots"
            )
        expected = set(source_slots)
        actual = set(entry_digests)
        if actual != expected:
            raise ProtocolViolation(
                "allocation manifest must exactly cover family source slots; "
                f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
            )
        if entry_digests != sorted(entry_digests):
            raise ProtocolViolation(
                "allocation manifest entries must be in canonical slot-digest order"
            )
        for entry in self.entries:
            entry._validate_for(
                self.world_slot,
                source_slots[entry.materialization_slot_digest],
            )
        self._w19_block_wires_unchecked()
        expected_digest = digest_json(self._body_unchecked())
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_manifest_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="pre-split strata allocation manifest seal is missing",
            changed_message="pre-split strata allocation manifest changed after construction",
        )

    def _entry_index_unchecked(self) -> dict[str, FrozenSlotAllocation]:
        return {
            entry.materialization_slot_digest: entry for entry in self.entries
        }

    def _w19_block_wires_unchecked(self) -> tuple[dict[str, Any], ...]:
        if self.world_slot != "W19":
            return ()
        entry_by_slot = self._entry_index_unchecked()
        blocks: list[dict[str, Any]] = []
        population_slots: set[str] = set()
        clusters = sorted(
            (
                link
                for link in self.family_source.atomic_links
                if link.semantic_type is AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER
            ),
            key=lambda link: link.link_digest,
        )
        if not clusters:
            raise ProtocolViolation(
                "W19 allocation manifest requires at least one assignment block"
            )
        for cluster in clusters:
            block_slots = sorted(
                slot.slot_digest
                for slot in self.family_source.materialization_slots
                if slot.materialization_role is MaterializationRole.W19_ASSIGNMENT_ROW
                and slot.atomic_link_digest == cluster.link_digest
            )
            if len(block_slots) != 64 or len(block_slots) != len(set(block_slots)):
                raise ProtocolViolation(
                    "each W19 allocation block must contain exactly 64 distinct slots"
                )
            overlap = population_slots.intersection(block_slots)
            if overlap:
                raise ProtocolViolation(
                    "W19 allocation blocks must be slot-disjoint"
                )
            population_slots.update(block_slots)
            rare_slots = [
                slot_digest
                for slot_digest in block_slots
                if entry_by_slot[slot_digest].value_for(
                    AllocationDimension.BOUNDARY_TAIL
                )
                is AllocationCellValue.RARE_TAIL
            ]
            common_slots = [
                slot_digest
                for slot_digest in block_slots
                if entry_by_slot[slot_digest].value_for(
                    AllocationDimension.BOUNDARY_TAIL
                )
                is AllocationCellValue.COMMON
            ]
            if len(rare_slots) != 1 or len(common_slots) != 63:
                raise ProtocolViolation(
                    "each W19 64-slot block requires exactly one RARE_TAIL and 63 COMMON"
                )
            block_body = {
                "atomic_link_digest": cluster.link_digest,
                "materialization_slot_digests": block_slots,
                "slot_count": 64,
                "common_count": 63,
                "rare_tail_count": 1,
                "rare_tail_slot_digest": rare_slots[0],
            }
            block_body["block_allocation_digest"] = domain_digest(
                b"UCM\0W19_STRATA_ALLOCATION_BLOCK_V1\0",
                (canonical_json_bytes(block_body),),
            )
            blocks.append(block_body)
        expected_population = {
            slot.slot_digest
            for slot in self.family_source.materialization_slots
            if slot.materialization_role is MaterializationRole.W19_ASSIGNMENT_ROW
        }
        if population_slots != expected_population:
            raise ProtocolViolation(
                "W19 allocation blocks do not form the exact population-slot union"
            )
        return tuple(blocks)

    def _population_union_digest_unchecked(self) -> str:
        slots = sorted(
            slot_digest
            for block in self._w19_block_wires_unchecked()
            for slot_digest in block["materialization_slot_digests"]
        )
        return domain_digest(
            b"UCM\0W19_STRATA_POPULATION_SLOT_UNION_V1\0",
            tuple(slot.encode("ascii") for slot in slots),
        )

    def _body_unchecked(self) -> dict[str, Any]:
        w19_blocks = list(self._w19_block_wires_unchecked())
        body = {
            "schema_version": ALLOCATION_MANIFEST_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_role": "builder_owned_pre_split_slot_allocation_unsealed",
            "benchmark_id": self.family_source.benchmark_id,
            "benchmark_revision": self.family_source.benchmark_revision,
            "world_slot": self.world_slot,
            "family_source_digest": self.family_source.source_digest,
            "generator_source_digest": self.generator_source_digest,
            "allocation_policy_digest": self.allocation_policy_digest,
            "allocation_schema_digest": _allocation_schema_digest(),
            "builder_id": self.builder_id,
            "builder_version": self.builder_version,
            "declared_slot_count": len(self.family_source.materialization_slots),
            "entries": [entry.to_wire() for entry in self.entries],
            "w19_blocks": w19_blocks,
            "w19_population_slot_union_digest": (
                self._population_union_digest_unchecked()
                if self.world_slot == "W19"
                else None
            ),
            "blockers": [_ALLOCATION_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def manifest_digest(self) -> str:
        self._validate()
        return self._sealed_manifest_digest

    def entry_for_slot(
        self,
        materialization_slot_digest: str,
    ) -> FrozenSlotAllocation | None:
        self._validate()
        _digest(
            materialization_slot_digest,
            "allocation manifest slot lookup digest",
        )
        return self._entry_index_unchecked().get(materialization_slot_digest)

    def to_wire(self) -> dict[str, Any]:
        self._validate()
        body = self._body_unchecked()
        body["manifest_digest"] = self._sealed_manifest_digest
        return body


def build_pre_split_strata_allocation_manifest(
    *,
    family_source: PreSplitFamilySource,
    world_slot: str,
    generator_source_digest: str,
    allocation_policy_digest: str,
    builder_id: str,
    builder_version: str,
    slot_drafts: tuple[SlotAllocationDraft, ...],
) -> PreSplitStrataAllocationManifest:
    if type(family_source) is not PreSplitFamilySource:
        raise ProtocolViolation(
            "allocation manifest builder requires PreSplitFamilySource"
        )
    family_source._validate()
    _world_slot(world_slot, "allocation manifest builder world_slot")
    _tuple_of_exact(
        slot_drafts,
        SlotAllocationDraft,
        "allocation manifest slot drafts",
        non_empty=True,
    )
    source_slots = {
        slot.slot_digest: slot for slot in family_source.materialization_slots
    }
    draft_digests = [draft.materialization_slot_digest for draft in slot_drafts]
    if len(draft_digests) != len(set(draft_digests)):
        raise ProtocolViolation("allocation manifest drafts contain duplicate slots")
    if set(draft_digests) != set(source_slots):
        raise ProtocolViolation(
            "allocation manifest drafts must exactly cover physical source slots"
        )
    resolved: list[FrozenSlotAllocation] = []
    for draft in sorted(
        slot_drafts,
        key=lambda item: item.materialization_slot_digest,
    ):
        draft.__post_init__()
        cells = _validate_cells_for_world(world_slot, draft.cells)
        slot = source_slots[draft.materialization_slot_digest]
        commitment = compute_slot_strata_allocation_commitment(world_slot, cells)
        if slot.strata_allocation_commitment_digest != commitment:
            raise ProtocolViolation(
                "slot draft cells do not reveal the commitment bound into the family source"
            )
        resolved.append(
            FrozenSlotAllocation(
                materialization_slot=slot,
                cells=cells,
                allocation_commitment_digest=commitment,
                slot_allocation_entry_digest=_slot_allocation_entry_digest(
                    slot,
                    cells,
                    commitment,
                ),
            )
        )
    return PreSplitStrataAllocationManifest(
        family_source=family_source,
        world_slot=world_slot,
        generator_source_digest=generator_source_digest,
        allocation_policy_digest=allocation_policy_digest,
        builder_id=builder_id,
        builder_version=builder_version,
        entries=tuple(resolved),
    )


@dataclass(frozen=True, slots=True)
class GeneratorAllocationEntry:
    """Exact receipt joined to its pre-split typed slot allocation."""

    materialization_receipt: MaterializationReceipt
    allocation_manifest: PreSplitStrataAllocationManifest

    def __post_init__(self) -> None:
        if type(self.materialization_receipt) is not MaterializationReceipt:
            raise ProtocolViolation(
                "allocation entry requires an exact MaterializationReceipt"
            )
        # The receipt's public digest property uses its strict validation path;
        # calling ``__post_init__`` here would permit a deleted seal to be
        # silently reinitialized.
        _ = self.materialization_receipt.receipt_digest
        if type(self.allocation_manifest) is not PreSplitStrataAllocationManifest:
            raise ProtocolViolation(
                "allocation entry requires PreSplitStrataAllocationManifest"
            )
        self.allocation_manifest._validate()
        if self.materialization_receipt.source is not self.allocation_manifest.family_source:
            raise ProtocolViolation(
                "allocation entry receipt and manifest have foreign family sources"
            )
        slot = self.slot_allocation
        evidence = self.materialization_receipt.evidence
        if (
            slot.materialization_slot.reference.authority_digest
            != evidence.authority_digest
            or slot.materialization_slot.reference.member_digest
            != evidence.member_digest
            or slot.materialization_slot.cut_digest != evidence.cut_digest
            or slot.materialization_slot.query_cell_digest
            != evidence.query_cell_digest
        ):
            raise ProtocolViolation(
                "allocation entry receipt does not exactly join its physical slot"
            )

    @property
    def authority_digest(self) -> str:
        return self.materialization_receipt.evidence.authority_digest

    @property
    def member_digest(self) -> str:
        return self.materialization_receipt.evidence.member_digest

    @property
    def cut_digest(self) -> str:
        cut_digest = self.materialization_receipt.evidence.cut_digest
        if cut_digest is None:
            raise ProtocolViolation(
                "allocation entry requires a declared pre-split materialization cut"
            )
        return cut_digest

    @property
    def materialization_slot_digest(self) -> str:
        slot_digest = self.materialization_receipt.evidence.materialization_slot_digest
        if slot_digest is None:
            raise ProtocolViolation(
                "allocation entry requires a declared pre-split materialization slot"
            )
        return slot_digest

    @property
    def record_digest(self) -> str:
        return self.materialization_receipt.evidence.candidate_row_digest

    @property
    def receipt_digest(self) -> str:
        return self.materialization_receipt.receipt_digest

    @property
    def slot_allocation(self) -> FrozenSlotAllocation:
        entry = self.allocation_manifest._entry_index_unchecked().get(
            self.materialization_slot_digest
        )
        if entry is None:
            raise ProtocolViolation(
                "allocation entry receipt has no exact typed slot allocation"
            )
        return entry

    @property
    def entry_digest(self) -> str:
        return _entry_digest_from_receipt_digest(
            self.receipt_digest,
            allocation_manifest_digest=self.allocation_manifest.manifest_digest,
            slot_allocation_entry_digest=(
                self.slot_allocation.slot_allocation_entry_digest
            ),
        )

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return self._to_wire_unchecked()

    def _to_wire_unchecked(
        self,
        *,
        receipt_digest: str | None = None,
    ) -> dict[str, Any]:
        resolved_receipt_digest = (
            self.materialization_receipt.receipt_digest
            if receipt_digest is None
            else receipt_digest
        )
        return {
            "authority_origin": "family_materialization_receipt",
            "family_materialization_receipt_digest": resolved_receipt_digest,
            "materialization_slot_digest": self.materialization_slot_digest,
            "authority_digest": self.authority_digest,
            "member_digest": self.member_digest,
            "cut_digest": self.cut_digest,
            "record_digest": self.record_digest,
            "pre_split_allocation_manifest_digest": (
                self.allocation_manifest.manifest_digest
            ),
            "slot_allocation_entry_digest": (
                self.slot_allocation.slot_allocation_entry_digest
            ),
            "entry_digest": _entry_digest_from_receipt_digest(
                resolved_receipt_digest,
                allocation_manifest_digest=self.allocation_manifest.manifest_digest,
                slot_allocation_entry_digest=(
                    self.slot_allocation.slot_allocation_entry_digest
                ),
            ),
        }


def build_generator_allocation_entry(
    materialization_receipt: MaterializationReceipt,
    allocation_manifest: PreSplitStrataAllocationManifest,
) -> GeneratorAllocationEntry:
    """Create a read-only allocation view from family authority evidence only."""

    return GeneratorAllocationEntry(materialization_receipt, allocation_manifest)


def _allocation_entry_wire_unchecked(
    receipt: MaterializationReceipt,
    receipt_digest: str,
    allocation_manifest_digest: str,
    slot_allocation: FrozenSlotAllocation,
) -> dict[str, Any]:
    evidence = receipt.evidence
    assert evidence.cut_digest is not None
    assert evidence.materialization_slot_digest is not None
    return {
        "authority_origin": "family_materialization_receipt",
        "family_materialization_receipt_digest": receipt_digest,
        "materialization_slot_digest": evidence.materialization_slot_digest,
        "authority_digest": evidence.authority_digest,
        "member_digest": evidence.member_digest,
        "cut_digest": evidence.cut_digest,
        "record_digest": evidence.candidate_row_digest,
        "pre_split_allocation_manifest_digest": allocation_manifest_digest,
        "slot_allocation_entry_digest": (
            slot_allocation.slot_allocation_entry_digest
        ),
        "entry_digest": _entry_digest_from_receipt_digest(
            receipt_digest,
            allocation_manifest_digest=allocation_manifest_digest,
            slot_allocation_entry_digest=(
                slot_allocation.slot_allocation_entry_digest
            ),
        ),
    }


@dataclass(frozen=True, slots=True, weakref_slot=True)
class JudgeStrataAuthority:
    family_source: PreSplitFamilySource
    family_assignment: WeightedAtomicAssignment
    world_slot: str
    definition_source_digest: str
    allocation_manifest: PreSplitStrataAllocationManifest
    materialization_ledger: MaterializationReceiptLedger
    definitions: tuple[StratumDefinition, ...] = field(init=False)
    _sealed_allocation_manifest_digest: str = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "definitions",
            _code_owned_definition_sets(self.world_slot)[1],
        )
        self._validate(allow_seal_initialization=True)

    @property
    def generator_source_digest(self) -> str:
        return self.allocation_manifest.generator_source_digest

    @property
    def allocation_policy_digest(self) -> str:
        return self.allocation_manifest.allocation_policy_digest

    def _validate(self, *, allow_seal_initialization: bool = False) -> None:
        if type(self.family_source) is not PreSplitFamilySource:
            raise ProtocolViolation("judge family_source must be PreSplitFamilySource")
        if type(self.family_assignment) is not WeightedAtomicAssignment:
            raise ProtocolViolation(
                "judge family_assignment must be WeightedAtomicAssignment"
            )
        _world_slot(self.world_slot, "judge world_slot")
        _digest(self.definition_source_digest, "judge definition_source_digest")
        if type(self.allocation_manifest) is not PreSplitStrataAllocationManifest:
            raise ProtocolViolation(
                "judge allocation_manifest must be PreSplitStrataAllocationManifest"
            )
        self.allocation_manifest._validate()
        if (
            self.allocation_manifest.family_source is not self.family_source
            or self.allocation_manifest.world_slot != self.world_slot
        ):
            raise ProtocolViolation(
                "judge typed allocation manifest has a foreign source or world"
            )
        _validate_definition_set(
            self.definitions,
            channel=StratumChannel.JUDGE_ONLY_FROZEN,
            non_empty=False,
            label="judge stratum definitions",
        )
        for definition in self.definitions:
            _validate_typed_judge_definition(self.world_slot, definition)
        if self.definitions != _code_owned_definition_sets(self.world_slot)[1]:
            raise ProtocolViolation(
                "judge definitions are not the code-owned world contract"
            )
        if type(self.materialization_ledger) is not MaterializationReceiptLedger:
            raise ProtocolViolation(
                "judge materialization_ledger must be MaterializationReceiptLedger"
            )
        self.materialization_ledger._validate()
        if (
            self.materialization_ledger.source is not self.family_source
            or self.materialization_ledger.assignment is not self.family_assignment
        ):
            raise ProtocolViolation(
                "judge typed materialization ledger has foreign source/assignment"
            )
        source_slots = {
            slot.slot_digest for slot in self.family_source.materialization_slots
        }
        manifest_slots = {
            entry.materialization_slot_digest
            for entry in self.allocation_manifest.entries
        }
        receipt_slots = {
            receipt.evidence.materialization_slot_digest
            for receipt in self.materialization_ledger.receipts
        }
        if source_slots != manifest_slots or source_slots != receipt_slots:
            raise ProtocolViolation(
                "judge source, allocation manifest, and receipt ledger must exactly "
                "cover the same physical slots"
            )

        entries_by_slot = self.allocation_manifest._entry_index_unchecked()
        assignments_by_authority = {
            item.authority_digest: item
            for item in self.family_assignment.assignments
        }
        exact_joins: set[tuple[str, str, str, str]] = set()
        for receipt in self.materialization_ledger.receipts:
            evidence = receipt.evidence
            assert evidence.materialization_slot_digest is not None
            assert evidence.cut_digest is not None
            slot_allocation = entries_by_slot.get(
                evidence.materialization_slot_digest
            )
            if slot_allocation is None:
                raise ProtocolViolation(
                    "receipt lacks an exact pre-split typed slot allocation"
                )
            slot = slot_allocation.materialization_slot
            if (
                slot.reference.authority_digest != evidence.authority_digest
                or slot.reference.member_digest != evidence.member_digest
                or slot.cut_digest != evidence.cut_digest
                or slot.query_cell_digest != evidence.query_cell_digest
            ):
                raise ProtocolViolation(
                    "receipt is cross-bound to a foreign slot allocation"
                )
            join = (
                evidence.authority_digest,
                evidence.member_digest,
                evidence.cut_digest,
                evidence.materialization_slot_digest,
            )
            if join in exact_joins:
                raise ProtocolViolation(
                    "materialization ledger contains duplicate exact slot joins"
                )
            exact_joins.add(join)
            assigned = assignments_by_authority.get(evidence.authority_digest)
            if assigned is None or assigned.assigned_split is not evidence.assigned_split:
                raise ProtocolViolation(
                    "materialization receipt split contradicts atomic assignment"
                )
            for definition in self.definitions:
                if definition.label not in {
                    "compositional_holdout",
                    "boundary_tail",
                    "mechanism_ood",
                }:
                    continue
                sealed_only = (
                    self.world_slot == "W10"
                    and definition.label == "compositional_holdout"
                    or self.world_slot == "W18"
                    and definition.label == "boundary_tail"
                )
                if (
                    sealed_only
                    and self._allocation_matches_label_unchecked(
                        definition.label,
                        slot_allocation,
                    )
                    and assigned.assigned_split is not FamilySplit.SEALED_TEST
                ):
                    raise ProtocolViolation(
                        f"{self.world_slot} {definition.label} may only match a "
                        "sealed-test family"
                    )
                if self.world_slot == "W18" and definition.label == "mechanism_ood":
                    mechanism_cell = slot_allocation.value_for(
                        AllocationDimension.MECHANISM_OOD
                    )
                    allowed_by_split = {
                        FamilySplit.TRAIN: {
                            AllocationCellValue.KNOWN_MECHANISM,
                        },
                        FamilySplit.VALIDATION: {
                            AllocationCellValue.KNOWN_MECHANISM,
                            AllocationCellValue.DEVELOPMENT_ANOMALY_MECHANISM,
                        },
                        FamilySplit.SEALED_TEST: {
                            AllocationCellValue.KNOWN_MECHANISM,
                            AllocationCellValue.SEALED_NOVEL_MECHANISM,
                        },
                    }[assigned.assigned_split]
                    if mechanism_cell not in allowed_by_split:
                        raise ProtocolViolation(
                            "W18 mechanism allocation value contradicts its "
                            "assigned split"
                        )

        self._validate_pair_coverage(exact_joins)
        self._w19_assignment_block_wires_unchecked()
        expected_digest = self._allocation_manifest_digest_unchecked()
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_allocation_manifest_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="judge strata authority seal is missing",
            changed_message="judge strata authority changed after construction",
        )

    def _validate_pair_coverage(
        self,
        exact_joins: set[tuple[str, str, str, str]],
    ) -> None:
        materialized_members = {(item[0], item[1]) for item in exact_joins}
        for pair in self.family_source.pairs:
            sides = {
                (side.reference.authority_digest, side.reference.member_digest)
                for side in pair.sides
            }
            if not sides <= materialized_members:
                raise ProtocolViolation(
                    "materialization ledger is missing a frozen pair side"
                )

    def _w19_assignment_block_wires_unchecked(
        self,
    ) -> tuple[dict[str, Any], ...]:
        if self.world_slot != "W19":
            return ()
        assignments_by_authority = {
            item.authority_digest: item
            for item in self.family_assignment.assignments
        }
        slots_by_digest = {
            slot.slot_digest: slot for slot in self.family_source.materialization_slots
        }
        blocks: list[dict[str, Any]] = []
        for pre_split_block in self.allocation_manifest._w19_block_wires_unchecked():
            splits = {
                assignments_by_authority[
                    slots_by_digest[slot_digest].reference.authority_digest
                ].assigned_split
                for slot_digest in pre_split_block["materialization_slot_digests"]
            }
            if len(splits) != 1:
                raise ProtocolViolation(
                    "each W19 64-slot allocation block must remain atomic in one split"
                )
            assigned_split = next(iter(splits))
            body = {
                **pre_split_block,
                "assigned_split": _family_split_wire(assigned_split),
            }
            body["judge_block_digest"] = domain_digest(
                b"UCM\0W19_JUDGE_STRATA_BLOCK_V1\0",
                (canonical_json_bytes(body),),
            )
            blocks.append(body)
        return tuple(blocks)

    @property
    def entries(self) -> tuple[GeneratorAllocationEntry, ...]:
        self._validate()
        return self._entries_unchecked()

    def _entries_unchecked(self) -> tuple[GeneratorAllocationEntry, ...]:
        return tuple(
            GeneratorAllocationEntry(receipt, self.allocation_manifest)
            for receipt in self.materialization_ledger.receipts
        )

    @property
    def materialization_receipt_root_digest(self) -> str:
        self._validate()
        return self._materialization_receipt_root_unchecked()

    def _materialization_receipt_root_unchecked(self) -> str:
        return self._materialization_receipt_root_from_digests_unchecked(
            tuple(
                _family_receipt_sealed_digest_unchecked(receipt)
                for receipt in self.materialization_ledger.receipts
            )
        )

    def _materialization_receipt_root_from_digests_unchecked(
        self,
        receipt_digests: tuple[str, ...],
    ) -> str:
        return domain_digest(
            b"UCM\0STRATA_MATERIALIZATION_RECEIPT_ROOT_V3\0",
            tuple(digest.encode("ascii") for digest in sorted(receipt_digests)),
        )

    @property
    def allocation_source_manifest_digest(self) -> str:
        self._validate()
        return self.allocation_manifest.manifest_digest

    def _allocation_source_manifest_unchecked(self) -> str:
        return self.allocation_manifest._sealed_manifest_digest

    @property
    def definition_contract_digest(self) -> str:
        self._validate()
        return self._definition_contract_unchecked()

    def _definition_contract_unchecked(self) -> str:
        return digest_json(
            {
                "schema_version": "ucm-judge-strata-definition-contract/3",
                "world_slot": self.world_slot,
                "definition_source_digest": self.definition_source_digest,
                "definitions": _sorted_wire(self.definitions),
            }
        )

    def _body(self) -> dict[str, Any]:
        self._validate()
        return self._body_unchecked()

    def _body_unchecked(
        self,
        receipt_digests: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        resolved_receipt_digests = (
            tuple(
                _family_receipt_sealed_digest_unchecked(receipt)
                for receipt in self.materialization_ledger.receipts
            )
            if receipt_digests is None
            else receipt_digests
        )
        allocation_manifest_digest = self.allocation_manifest._sealed_manifest_digest
        allocation_by_slot = self.allocation_manifest._entry_index_unchecked()
        entry_wires = [
            _allocation_entry_wire_unchecked(
                receipt,
                receipt_digest,
                allocation_manifest_digest,
                allocation_by_slot[receipt.evidence.materialization_slot_digest],
            )
            for receipt, receipt_digest in zip(
                self.materialization_ledger.receipts,
                resolved_receipt_digests,
                strict=True,
            )
        ]
        body = {
            "schema_version": JUDGE_AUTHORITY_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_role": "typed_pre_split_allocation_plus_exact_ledger_unsealed",
            "benchmark_id": self.family_source.benchmark_id,
            "benchmark_revision": self.family_source.benchmark_revision,
            "world_slot": self.world_slot,
            "family_source_digest": self.family_source.source_digest,
            "family_assignment_digest": self.family_assignment.assignment_digest,
            "split_policy_digest": self.family_assignment.split_policy_digest,
            "generator_source_digest": self.generator_source_digest,
            "pre_split_allocation_manifest_digest": allocation_manifest_digest,
            "allocation_source_manifest_digest": allocation_manifest_digest,
            "allocation_policy_digest": self.allocation_policy_digest,
            "definition_source_digest": self.definition_source_digest,
            "definition_contract_digest": self._definition_contract_unchecked(),
            "family_materialization_ledger_digest": (
                _family_ledger_sealed_digest_unchecked(self.materialization_ledger)
            ),
            "materialization_receipt_root_digest": (
                self._materialization_receipt_root_from_digests_unchecked(
                    resolved_receipt_digests
                )
            ),
            "definitions": _sorted_wire(self.definitions),
            "entries": sorted(entry_wires, key=canonical_json_bytes),
            "w19_blocks": list(self._w19_assignment_block_wires_unchecked()),
            "blockers": [_JUDGE_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def allocation_manifest_digest(self) -> str:
        self._validate()
        return self._sealed_allocation_manifest_digest

    def _allocation_manifest_digest_unchecked(
        self,
        receipt_digests: tuple[str, ...] | None = None,
    ) -> str:
        return digest_json(self._body_unchecked(receipt_digests))

    def to_wire(self) -> dict[str, Any]:
        self._validate()
        body = self._body_unchecked()
        body["allocation_manifest_digest"] = self._sealed_allocation_manifest_digest
        return body

    def entry_for(
        self,
        authority_digest: str,
        member_digest: str,
        cut_digest: str,
        materialization_slot_digest: str,
        receipt_digest: str,
    ) -> GeneratorAllocationEntry | None:
        self._validate()
        return self._entry_for_unchecked(
            authority_digest,
            member_digest,
            cut_digest,
            materialization_slot_digest,
            receipt_digest,
        )

    def _entry_for_unchecked(
        self,
        authority_digest: str,
        member_digest: str,
        cut_digest: str,
        materialization_slot_digest: str,
        receipt_digest: str,
    ) -> GeneratorAllocationEntry | None:
        for receipt in self.materialization_ledger.receipts:
            evidence = receipt.evidence
            if (
                evidence.authority_digest == authority_digest
                and evidence.member_digest == member_digest
                and evidence.cut_digest == cut_digest
                and evidence.materialization_slot_digest
                == materialization_slot_digest
                and _family_receipt_sealed_digest_unchecked(receipt)
                == receipt_digest
            ):
                return GeneratorAllocationEntry(receipt, self.allocation_manifest)
        return None

    def _is_behavior_pair_receipt(
        self,
        receipt: MaterializationReceipt,
    ) -> bool:
        evidence = receipt.evidence
        if (
            evidence.materialization_role is not MaterializationRole.PAIR_SIDE
            or evidence.pair_digest is None
            or type(evidence.pair_side) is not int
        ):
            return False
        accepted_semantics = (
            {PairSemantic.RESPONSE_REVERSAL}
            if self.world_slot == "W20"
            else {PairSemantic.BEHAVIORAL}
        )
        for pair in self.family_source.pairs:
            if (
                pair.semantic_type not in accepted_semantics
                or pair.pair_digest != evidence.pair_digest
            ):
                continue
            if any(
                side.side == evidence.pair_side
                and side.reference.authority_digest == evidence.authority_digest
                and side.reference.member_digest == evidence.member_digest
                for side in pair.sides
            ):
                return True
        return False

    def _allocation_matches_label_unchecked(
        self,
        label: str,
        slot_allocation: FrozenSlotAllocation,
    ) -> bool:
        dimension = _ALLOCATION_DIMENSION_BY_LABEL.get(label)
        if dimension is None:
            raise ProtocolViolation(
                f"{label} is not a typed allocation-backed stratum"
            )
        return slot_allocation.value_for(dimension) in _positive_allocation_values(
            self.world_slot,
            dimension,
        )

    def classify(self, entry: GeneratorAllocationEntry) -> tuple[str, ...]:
        if type(entry) is not GeneratorAllocationEntry:
            raise ProtocolViolation("judge classify entry has wrong type")
        entry.__post_init__()
        self._validate()
        if entry.allocation_manifest is not self.allocation_manifest:
            raise ProtocolViolation(
                "judge classify entry has a foreign allocation manifest"
            )
        known = self._entry_for_unchecked(
            entry.authority_digest,
            entry.member_digest,
            entry.cut_digest,
            entry.materialization_slot_digest,
            entry.receipt_digest,
        )
        if (
            known is None
            or known.materialization_receipt is not entry.materialization_receipt
            or known.entry_digest != entry.entry_digest
        ):
            raise ProtocolViolation(
                "judge classify requires the exact materialization-ledger receipt"
            )
        return self._classify_entry_unchecked(entry)

    def _classify_entry_unchecked(
        self,
        entry: GeneratorAllocationEntry,
    ) -> tuple[str, ...]:
        return self._classify_receipt_unchecked(entry.materialization_receipt)

    def _classify_receipt_unchecked(
        self,
        receipt: MaterializationReceipt,
    ) -> tuple[str, ...]:
        evidence = receipt.evidence
        assert evidence.materialization_slot_digest is not None
        slot_allocation = self.allocation_manifest._entry_index_unchecked().get(
            evidence.materialization_slot_digest
        )
        if slot_allocation is None:
            raise ProtocolViolation(
                "judge receipt lacks an exact typed slot allocation"
            )
        labels: list[str] = []
        for definition in self.definitions:
            assert definition.judge_rule is not None
            if definition.judge_rule.kind in {
                JudgeRuleKind.FAMILY_BEHAVIOR_PAIR,
                JudgeRuleKind.W20_RESPONSE_REVERSAL_BOUNDARY,
            }:
                matched = self._is_behavior_pair_receipt(receipt)
            else:
                matched = self._allocation_matches_label_unchecked(
                    definition.label,
                    slot_allocation,
                )
            if matched:
                labels.append(definition.label)
        return _sort_labels(labels)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class DualChannelStrataAuthority:
    public: PublicClassifierAuthority
    judge: JudgeStrataAuthority
    _sealed_authority_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._validate(allow_seal_initialization=True)

    def _validate(self, *, allow_seal_initialization: bool = False) -> None:
        if type(self.public) is not PublicClassifierAuthority:
            raise ProtocolViolation("dual public authority has wrong type")
        if type(self.judge) is not JudgeStrataAuthority:
            raise ProtocolViolation("dual judge authority has wrong type")
        self.public._validate()
        self.judge._validate()
        if (
            self.public.benchmark_id != self.judge.family_source.benchmark_id
            or self.public.benchmark_revision
            != self.judge.family_source.benchmark_revision
        ):
            raise ProtocolViolation("public/judge benchmark identity mismatch")
        if self.public.world_slot != self.judge.world_slot:
            raise ProtocolViolation("public/judge world mismatch")
        public_by_label = {item.label: item for item in self.public.definitions}
        judge_by_label = {item.label: item for item in self.judge.definitions}
        declared = set(WORLD_DECLARED_STRATA[self.public.world_slot])
        actual = set(public_by_label) | set(judge_by_label)
        if actual != declared:
            missing = sorted(declared - actual)
            extra = sorted(actual - declared)
            raise ProtocolViolation(
                "world stratum definitions must exactly match the frozen registry; "
                f"missing={missing}, extra={extra}"
            )
        for label in WORLD_DECLARED_STRATA[self.public.world_slot]:
            required = _required_channel(self.public.world_slot, label)
            public_definition = public_by_label.get(label)
            judge_definition = judge_by_label.get(label)
            if required is StratumChannel.PUBLIC_REPLAYABLE:
                if (
                    public_definition is None
                    or public_definition.channel is not required
                    or judge_definition is not None
                ):
                    raise ProtocolViolation(
                        f"{self.public.world_slot} {label} must be public-replayable only"
                    )
            elif required is StratumChannel.JUDGE_ONLY_FROZEN:
                if (
                    judge_definition is None
                    or judge_definition.channel is not required
                    or public_definition is not None
                ):
                    raise ProtocolViolation(
                        f"{self.public.world_slot} {label} must be judge-only frozen"
                    )
            else:
                if (
                    public_definition is None
                    or judge_definition is None
                    or public_definition.channel
                    is not StratumChannel.DUAL_CONJUNCTION
                    or judge_definition.channel
                    is not StratumChannel.DUAL_CONJUNCTION
                    or public_definition != judge_definition
                ):
                    raise ProtocolViolation(
                        f"{self.public.world_slot} {label} must be one identical "
                        "dual-conjunction definition"
                    )
        expected_digest = self._authority_digest_unchecked()
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_authority_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="dual-channel strata authority seal is missing",
            changed_message="dual-channel strata authority changed after construction",
        )

    def _body(self) -> dict[str, Any]:
        self._validate()
        return self._body_unchecked()

    def _body_unchecked(
        self,
        *,
        public_classifier_digest: str | None = None,
        judge_allocation_manifest_digest: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "schema_version": DUAL_AUTHORITY_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "benchmark_id": self.public.benchmark_id,
            "benchmark_revision": self.public.benchmark_revision,
            "world_slot": self.public.world_slot,
            "public_classifier_digest": (
                self.public._classifier_digest_unchecked()
                if public_classifier_digest is None
                else public_classifier_digest
            ),
            "judge_allocation_manifest_digest": (
                self.judge._allocation_manifest_digest_unchecked()
                if judge_allocation_manifest_digest is None
                else judge_allocation_manifest_digest
            ),
            "family_source_digest": self.judge.family_source.source_digest,
            "family_assignment_digest": self.judge.family_assignment.assignment_digest,
            "split_policy_digest": self.judge.family_assignment.split_policy_digest,
            "channel_definitions": {
                "public_replayable": list(_sort_labels(
                    item.label
                    for item in self.public.definitions
                    if item.channel is StratumChannel.PUBLIC_REPLAYABLE
                )),
                "judge_only_frozen": list(_sort_labels(
                    item.label
                    for item in self.judge.definitions
                    if item.channel is StratumChannel.JUDGE_ONLY_FROZEN
                )),
                "dual_conjunction": list(_sort_labels(
                    item.label
                    for item in self.public.definitions
                    if item.channel is StratumChannel.DUAL_CONJUNCTION
                )),
            },
            "blockers": [_DUAL_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def authority_digest(self) -> str:
        self._validate()
        return self._sealed_authority_digest

    def _authority_digest_unchecked(
        self,
        *,
        public_classifier_digest: str | None = None,
        judge_allocation_manifest_digest: str | None = None,
    ) -> str:
        return digest_json(
            self._body_unchecked(
                public_classifier_digest=public_classifier_digest,
                judge_allocation_manifest_digest=judge_allocation_manifest_digest,
            )
        )

    def to_wire(self) -> dict[str, Any]:
        self._validate()
        bindings = _authority_bindings_unchecked(self)
        body = self._body_unchecked(
            public_classifier_digest=bindings.public_classifier_digest,
            judge_allocation_manifest_digest=(
                bindings.judge_allocation_manifest_digest
            ),
        )
        body["authority_digest"] = bindings.authority_digest
        public_body = self.public._body_unchecked()
        public_body["classifier_digest"] = bindings.public_classifier_digest
        judge_body = self.judge._body_unchecked(bindings.receipt_digests)
        judge_body["allocation_manifest_digest"] = (
            bindings.judge_allocation_manifest_digest
        )
        body["public"] = public_body
        body["judge"] = judge_body
        return body

    def combine_labels(
        self,
        public_labels: tuple[str, ...],
        judge_labels: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Combine raw channel matches under the frozen per-label contract."""

        self._validate()
        _canonical_labels(public_labels, "combined public labels")
        _canonical_labels(judge_labels, "combined judge labels")
        public_contract = {item.label for item in self.public.definitions}
        judge_contract = {item.label for item in self.judge.definitions}
        unexpected_public = sorted(set(public_labels) - public_contract)
        unexpected_judge = sorted(set(judge_labels) - judge_contract)
        if unexpected_public or unexpected_judge:
            raise ProtocolViolation(
                "combined channel labels contradict the exact world contract; "
                f"unexpected_public={unexpected_public}, "
                f"unexpected_judge={unexpected_judge}"
            )
        return self._combine_labels_unchecked(public_labels, judge_labels)

    def _combine_labels_unchecked(
        self,
        public_labels: tuple[str, ...],
        judge_labels: tuple[str, ...],
    ) -> tuple[str, ...]:
        public_set, judge_set = set(public_labels), set(judge_labels)
        combined: list[str] = []
        for label in WORLD_DECLARED_STRATA[self.public.world_slot]:
            channel = _required_channel(self.public.world_slot, label)
            if channel is StratumChannel.PUBLIC_REPLAYABLE:
                matched = label in public_set
            elif channel is StratumChannel.JUDGE_ONLY_FROZEN:
                matched = label in judge_set
            else:
                matched = label in public_set and label in judge_set
            if matched:
                combined.append(label)
        return tuple(combined)


@dataclass(frozen=True, slots=True)
class StrataRowJoin:
    """Exact materialiser-side join; it contains no caller-provided labels."""

    family_receipt: MaterializationReceipt
    public_history: VisibleHistory

    def __post_init__(self) -> None:
        if type(self.family_receipt) is not MaterializationReceipt:
            raise ProtocolViolation(
                "strata row family_receipt must be MaterializationReceipt"
            )
        # This join is only a lightweight handle.  The issuing authority
        # strictly revalidates the exact receipt ledger before consuming it;
        # revalidating the full family graph here for every W19 row would make
        # batch construction quadratic.  A missing construction seal still
        # fails immediately, and a stale/mutated receipt fails at issuance.
        _digest(
            _family_receipt_sealed_digest_unchecked(self.family_receipt),
            "strata row family materialization receipt seal",
        )
        _safe_public_history(self.public_history)
        if (
            self.family_receipt.evidence.public_history_digest
            != self.public_history.digest
        ):
            raise ProtocolViolation(
                "strata row public history does not match family materialization receipt"
            )

    @property
    def record_digest(self) -> str:
        return self.family_receipt.evidence.candidate_row_digest

    @property
    def authority_digest(self) -> str:
        return self.family_receipt.evidence.authority_digest

    @property
    def member_digest(self) -> str:
        return self.family_receipt.evidence.member_digest

    @property
    def cut_digest(self) -> str:
        cut_digest = self.family_receipt.evidence.cut_digest
        if cut_digest is None:
            raise ProtocolViolation(
                "strata row requires a declared pre-split materialization cut"
            )
        return cut_digest

    @property
    def materialization_slot_digest(self) -> str:
        slot_digest = self.family_receipt.evidence.materialization_slot_digest
        if slot_digest is None:
            raise ProtocolViolation(
                "strata row requires a declared pre-split materialization slot"
            )
        return slot_digest

    @property
    def family_materialization_receipt_digest(self) -> str:
        return _family_receipt_sealed_digest_unchecked(self.family_receipt)

    @property
    def public_history_digest(self) -> str:
        return self.public_history.digest

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return self._to_wire_unchecked()

    def _to_wire_unchecked(
        self,
        *,
        family_receipt_digest: str | None = None,
        public_history_wire: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "record_digest": self.record_digest,
            "authority_digest": self.authority_digest,
            "member_digest": self.member_digest,
            "cut_digest": self.cut_digest,
            "materialization_slot_digest": self.materialization_slot_digest,
            "family_materialization_receipt_digest": (
                self.family_materialization_receipt_digest
                if family_receipt_digest is None
                else family_receipt_digest
            ),
            "public_history_digest": self.public_history_digest,
            "public_history": (
                self.public_history.to_wire()
                if public_history_wire is None
                else public_history_wire
            ),
        }


@dataclass(frozen=True, slots=True)
class PublicChannelResult:
    authority_digest: str
    classifier_digest: str
    classifier_source_digest: str
    public_history_digest: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.authority_digest, "public result authority_digest")
        _digest(self.classifier_digest, "public result classifier_digest")
        _digest(self.classifier_source_digest, "public result classifier_source_digest")
        _digest(self.public_history_digest, "public result public_history_digest")
        _canonical_labels(self.labels, "public result labels")

    def _body(self) -> dict[str, Any]:
        self.__post_init__()
        return self._body_unchecked()

    def _body_unchecked(self) -> dict[str, Any]:
        body = {
            "schema_version": PUBLIC_RESULT_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_digest": self.authority_digest,
            "classifier_digest": self.classifier_digest,
            "classifier_source_digest": self.classifier_source_digest,
            "public_history_digest": self.public_history_digest,
            "labels": list(self.labels),
            "blockers": [_PUBLIC_RESULT_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def result_digest(self) -> str:
        return digest_json(self._body())

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        body = self._body_unchecked()
        body["result_digest"] = digest_json(body)
        return body


@dataclass(frozen=True, slots=True)
class JudgeChannelResult:
    authority_digest: str
    public_classifier_digest: str
    allocation_manifest_digest: str
    generator_source_digest: str
    allocation_entry_digest: str
    public_history_digest: str
    public_replay_labels: tuple[str, ...]
    judge_frozen_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.authority_digest, "judge result authority_digest")
        _digest(self.public_classifier_digest, "judge result public_classifier_digest")
        _digest(self.allocation_manifest_digest, "judge result allocation_manifest_digest")
        _digest(self.generator_source_digest, "judge result generator_source_digest")
        _digest(self.allocation_entry_digest, "judge result allocation_entry_digest")
        _digest(self.public_history_digest, "judge result public_history_digest")
        _canonical_labels(
            self.public_replay_labels,
            "judge result public_replay_labels",
        )
        _canonical_labels(self.judge_frozen_labels, "judge result judge_frozen_labels")

    def _body(self) -> dict[str, Any]:
        self.__post_init__()
        return self._body_unchecked()

    def _body_unchecked(self) -> dict[str, Any]:
        body = {
            "schema_version": JUDGE_RESULT_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_digest": self.authority_digest,
            "public_classifier_digest": self.public_classifier_digest,
            "allocation_manifest_digest": self.allocation_manifest_digest,
            "generator_source_digest": self.generator_source_digest,
            "allocation_entry_digest": self.allocation_entry_digest,
            "public_history_digest": self.public_history_digest,
            "public_replay_labels": list(self.public_replay_labels),
            "judge_frozen_labels": list(self.judge_frozen_labels),
            "blockers": [_JUDGE_RESULT_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def result_digest(self) -> str:
        return digest_json(self._body())

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        body = self._body_unchecked()
        body["result_digest"] = digest_json(body)
        return body


@dataclass(frozen=True, slots=True)
class _AuthorityBindings:
    receipt_digests: tuple[str, ...]
    public_classifier_digest: str
    judge_allocation_manifest_digest: str
    authority_digest: str
    family_source_digest: str
    family_assignment_digest: str
    split_policy_digest: str


def _authority_bindings_unchecked(
    authority: DualChannelStrataAuthority,
) -> _AuthorityBindings:
    receipt_digests = tuple(
        _family_receipt_sealed_digest_unchecked(receipt)
        for receipt in authority.judge.materialization_ledger.receipts
    )
    public_classifier_digest = authority.public._sealed_classifier_digest
    judge_allocation_manifest_digest = (
        authority.judge._sealed_allocation_manifest_digest
    )
    authority_digest = authority._sealed_authority_digest
    return _AuthorityBindings(
        receipt_digests,
        public_classifier_digest,
        judge_allocation_manifest_digest,
        authority_digest,
        authority.judge.family_source._sealed_source_digest,
        authority.judge.family_assignment._sealed_assignment_digest,
        authority.judge.family_assignment.split_policy_digest,
    )


def _ledger_receipt_index_unchecked(
    authority: DualChannelStrataAuthority,
    receipt: MaterializationReceipt,
) -> int | None:
    for index, candidate in enumerate(authority.judge.materialization_ledger.receipts):
        if candidate is receipt:
            return index
    return None


def _derive_public_result(
    authority: DualChannelStrataAuthority,
    join: StrataRowJoin,
    *,
    bindings: _AuthorityBindings | None = None,
    public_labels: tuple[str, ...] | None = None,
    public_history_wire: dict[str, Any] | None = None,
) -> PublicChannelResult:
    resolved_bindings = (
        _authority_bindings_unchecked(authority)
        if bindings is None
        else bindings
    )
    resolved_history_wire = (
        _safe_public_history(join.public_history)
        if public_history_wire is None
        else public_history_wire
    )
    return PublicChannelResult(
        authority_digest=resolved_bindings.authority_digest,
        classifier_digest=resolved_bindings.public_classifier_digest,
        classifier_source_digest=authority.public.classifier_source_digest,
        public_history_digest=join.public_history_digest,
        labels=(
            authority.public._classify_wire_unchecked(resolved_history_wire)
            if public_labels is None
            else public_labels
        ),
    )


def _derive_judge_result(
    authority: DualChannelStrataAuthority,
    join: StrataRowJoin,
    *,
    bindings: _AuthorityBindings | None = None,
    public_labels: tuple[str, ...] | None = None,
    public_history_wire: dict[str, Any] | None = None,
) -> JudgeChannelResult:
    resolved_bindings = (
        _authority_bindings_unchecked(authority)
        if bindings is None
        else bindings
    )
    receipt_index = _ledger_receipt_index_unchecked(
        authority,
        join.family_receipt,
    )
    if receipt_index is None:
        raise ProtocolViolation("strata row has no exact frozen generator allocation")
    resolved_history_wire = (
        _safe_public_history(join.public_history)
        if public_history_wire is None
        else public_history_wire
    )
    resolved_public_labels = (
        authority.public._classify_wire_unchecked(resolved_history_wire)
        if public_labels is None
        else public_labels
    )
    receipt_digest = resolved_bindings.receipt_digests[receipt_index]
    slot_digest = join.family_receipt.evidence.materialization_slot_digest
    assert slot_digest is not None
    slot_allocation = authority.judge.allocation_manifest._entry_index_unchecked().get(
        slot_digest
    )
    if slot_allocation is None:
        raise ProtocolViolation(
            "strata row has no exact pre-split typed slot allocation"
        )
    return JudgeChannelResult(
        authority_digest=resolved_bindings.authority_digest,
        public_classifier_digest=resolved_bindings.public_classifier_digest,
        allocation_manifest_digest=resolved_bindings.judge_allocation_manifest_digest,
        generator_source_digest=authority.judge.generator_source_digest,
        allocation_entry_digest=_entry_digest_from_receipt_digest(
            receipt_digest,
            allocation_manifest_digest=(
                authority.judge.allocation_manifest._sealed_manifest_digest
            ),
            slot_allocation_entry_digest=(
                slot_allocation.slot_allocation_entry_digest
            ),
        ),
        public_history_digest=join.public_history_digest,
        public_replay_labels=resolved_public_labels,
        judge_frozen_labels=authority.judge._classify_receipt_unchecked(
            join.family_receipt
        ),
    )


def _result_wire_unchecked(
    result: PublicChannelResult | JudgeChannelResult,
) -> dict[str, Any]:
    body = result._body_unchecked()
    body["result_digest"] = digest_json(body)
    return body


@dataclass(frozen=True, slots=True)
class StrataRowReceipt:
    authority: DualChannelStrataAuthority
    join: StrataRowJoin
    public_result: PublicChannelResult
    judge_result: JudgeChannelResult

    def __post_init__(self) -> None:
        self._validate_and_bind()

    @classmethod
    def _from_validated_context(
        cls,
        *,
        authority: DualChannelStrataAuthority,
        join: StrataRowJoin,
        public_result: PublicChannelResult,
        judge_result: JudgeChannelResult,
        bindings: _AuthorityBindings,
    ) -> "StrataRowReceipt":
        receipt = object.__new__(cls)
        object.__setattr__(receipt, "authority", authority)
        object.__setattr__(receipt, "join", join)
        object.__setattr__(receipt, "public_result", public_result)
        object.__setattr__(receipt, "judge_result", judge_result)
        receipt._validate_and_bind(
            bindings=bindings,
            authority_already_validated=True,
        )
        return receipt

    def _validate_and_bind(
        self,
        *,
        bindings: _AuthorityBindings | None = None,
        authority_already_validated: bool = False,
    ) -> tuple[_AuthorityBindings, int, dict[str, Any], tuple[str, ...]]:
        if type(self.authority) is not DualChannelStrataAuthority:
            raise ProtocolViolation("strata receipt authority has wrong type")
        if type(self.join) is not StrataRowJoin:
            raise ProtocolViolation("strata receipt join has wrong type")
        if type(self.public_result) is not PublicChannelResult:
            raise ProtocolViolation("strata receipt public result has wrong type")
        if type(self.judge_result) is not JudgeChannelResult:
            raise ProtocolViolation("strata receipt judge result has wrong type")
        if not authority_already_validated:
            self.authority._validate()
        self.public_result.__post_init__()
        self.judge_result.__post_init__()
        if type(self.join.family_receipt) is not MaterializationReceipt:
            raise ProtocolViolation(
                "strata row family_receipt must be MaterializationReceipt"
            )
        receipt_index = _ledger_receipt_index_unchecked(
            self.authority,
            self.join.family_receipt,
        )
        if receipt_index is None:
            raise ProtocolViolation(
                "strata row family receipt does not match strata family authority"
            )
        public_history_wire = _safe_public_history(self.join.public_history)
        if (
            self.join.family_receipt.evidence.public_history_digest
            != self.join.public_history.digest
        ):
            raise ProtocolViolation(
                "strata row public history does not match family materialization receipt"
            )

        resolved_bindings = (
            _authority_bindings_unchecked(self.authority)
            if bindings is None
            else bindings
        )
        public_labels = self.authority.public._classify_wire_unchecked(
            public_history_wire
        )
        expected_public = _derive_public_result(
            self.authority,
            self.join,
            bindings=resolved_bindings,
            public_labels=public_labels,
            public_history_wire=public_history_wire,
        )
        expected_judge = _derive_judge_result(
            self.authority,
            self.join,
            bindings=resolved_bindings,
            public_labels=public_labels,
            public_history_wire=public_history_wire,
        )
        if self.public_result != expected_public:
            raise ProtocolViolation(
                "public stratum result is missing, extra, unknown, or stale"
            )
        if self.judge_result.public_replay_labels != self.public_result.labels:
            raise ProtocolViolation("public/judge replay channels disagree")
        if self.judge_result != expected_judge:
            raise ProtocolViolation(
                "judge stratum result is missing, extra, unknown, or stale"
            )

        unit = next(
            (
                item
                for item in self.authority.judge.family_source.units
                if item.authority_digest == self.join.authority_digest
            ),
            None,
        )
        member = (
            next(
                (
                    item
                    for item in unit.members
                    if item.member_digest == self.join.member_digest
                ),
                None,
            )
            if unit is not None
            else None
        )
        if unit is None or member is None:
            raise ProtocolViolation("strata receipt family/member join is unknown")
        assignment = _assignment_for_validated_unchecked(
            self.authority.judge.family_assignment,
            self.join.authority_digest
        )
        if assignment is None:
            raise ProtocolViolation("strata receipt family lacks an atomic assignment")
        combined_labels = self.authority._combine_labels_unchecked(
            self.public_result.labels,
            self.judge_result.judge_frozen_labels,
        )
        return (
            resolved_bindings,
            receipt_index,
            public_history_wire,
            combined_labels,
        )

    @property
    def combined_labels(self) -> tuple[str, ...]:
        return self._validate_and_bind()[3]

    def _body(self) -> dict[str, Any]:
        bindings, receipt_index, public_history_wire, combined_labels = (
            self._validate_and_bind()
        )
        return self._body_from_validated_unchecked(
            bindings,
            receipt_index,
            public_history_wire,
            combined_labels,
        )

    def _body_from_validated_unchecked(
        self,
        bindings: _AuthorityBindings,
        receipt_index: int,
        public_history_wire: dict[str, Any],
        combined_labels: tuple[str, ...],
    ) -> dict[str, Any]:
        assignment = _assignment_for_validated_unchecked(
            self.authority.judge.family_assignment,
            self.join.authority_digest
        )
        assert assignment is not None
        body = {
            "schema_version": ROW_RECEIPT_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_digest": bindings.authority_digest,
            "family_source_digest": bindings.family_source_digest,
            "family_assignment_digest": bindings.family_assignment_digest,
            "split_policy_digest": bindings.split_policy_digest,
            "generator_source_digest": self.authority.judge.generator_source_digest,
            "allocation_manifest_digest": bindings.judge_allocation_manifest_digest,
            "assigned_split": _family_split_wire(assignment.assigned_split),
            "row_join": self.join._to_wire_unchecked(
                family_receipt_digest=bindings.receipt_digests[receipt_index],
                public_history_wire=public_history_wire,
            ),
            "public_channel": _result_wire_unchecked(self.public_result),
            "judge_channel": _result_wire_unchecked(self.judge_result),
            "combined_labels": list(combined_labels),
            "blockers": [_RECEIPT_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    def _wire_from_validated_unchecked(
        self,
        bindings: _AuthorityBindings,
        receipt_index: int,
        public_history_wire: dict[str, Any],
        combined_labels: tuple[str, ...],
    ) -> dict[str, Any]:
        body = self._body_from_validated_unchecked(
            bindings,
            receipt_index,
            public_history_wire,
            combined_labels,
        )
        body["receipt_digest"] = digest_json(body)
        return body

    @property
    def receipt_digest(self) -> str:
        return digest_json(self._body())

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["receipt_digest"] = digest_json(body)
        return body


def issue_strata_row_receipt(
    authority: DualChannelStrataAuthority,
    join: StrataRowJoin,
) -> StrataRowReceipt:
    """Derive both channels; callers never submit labels or control digests."""

    if type(authority) is not DualChannelStrataAuthority:
        raise ProtocolViolation("strata authority has wrong type")
    if type(join) is not StrataRowJoin:
        raise ProtocolViolation("strata row join has wrong type")
    authority._validate()
    public_history_wire = _safe_public_history(join.public_history)
    bindings = _authority_bindings_unchecked(authority)
    public_labels = authority.public._classify_wire_unchecked(public_history_wire)
    public_result = _derive_public_result(
        authority,
        join,
        bindings=bindings,
        public_labels=public_labels,
        public_history_wire=public_history_wire,
    )
    judge_result = _derive_judge_result(
        authority,
        join,
        bindings=bindings,
        public_labels=public_labels,
        public_history_wire=public_history_wire,
    )
    return StrataRowReceipt._from_validated_context(
        authority=authority,
        join=join,
        public_result=public_result,
        judge_result=judge_result,
        bindings=bindings,
    )


def issue_strata_row_receipt_batch(
    authority: DualChannelStrataAuthority,
    joins: tuple[StrataRowJoin, ...],
) -> tuple[StrataRowReceipt, ...]:
    """Issue exact row receipts after one shared authority validation."""

    if type(authority) is not DualChannelStrataAuthority:
        raise ProtocolViolation("strata authority has wrong type")
    _tuple_of_exact(
        joins,
        StrataRowJoin,
        "strata row join batch",
        non_empty=True,
    )
    authority._validate()
    bindings = _authority_bindings_unchecked(authority)
    receipts: list[StrataRowReceipt] = []
    for join in joins:
        public_history_wire = _safe_public_history(join.public_history)
        public_labels = authority.public._classify_wire_unchecked(
            public_history_wire
        )
        public_result = _derive_public_result(
            authority,
            join,
            bindings=bindings,
            public_labels=public_labels,
            public_history_wire=public_history_wire,
        )
        judge_result = _derive_judge_result(
            authority,
            join,
            bindings=bindings,
            public_labels=public_labels,
            public_history_wire=public_history_wire,
        )
        receipts.append(
            StrataRowReceipt._from_validated_context(
                authority=authority,
                join=join,
                public_result=public_result,
                judge_result=judge_result,
                bindings=bindings,
            )
        )
    return tuple(receipts)


@dataclass(frozen=True, slots=True)
class StrataReceiptBatch:
    """Exact corpus-level coverage/uniqueness audit for frozen allocation joins."""

    authority: DualChannelStrataAuthority
    receipts: tuple[StrataRowReceipt, ...]

    def __post_init__(self) -> None:
        self._validate_and_bind()

    def _validate_and_bind(
        self,
    ) -> tuple[
        _AuthorityBindings,
        tuple[tuple[StrataRowReceipt, int, dict[str, Any], tuple[str, ...]], ...],
    ]:
        if type(self.authority) is not DualChannelStrataAuthority:
            raise ProtocolViolation("strata batch authority has wrong type")
        self.authority._validate()
        bindings = _authority_bindings_unchecked(self.authority)
        _tuple_of_exact(
            self.receipts,
            StrataRowReceipt,
            "strata batch receipts",
            non_empty=True,
        )
        expected = {
            (
                receipt.evidence.authority_digest,
                receipt.evidence.member_digest,
                receipt.evidence.cut_digest,
                receipt.evidence.materialization_slot_digest,
                receipt_digest,
            )
            for receipt, receipt_digest in zip(
                self.authority.judge.materialization_ledger.receipts,
                bindings.receipt_digests,
                strict=True,
            )
        }
        actual: list[tuple[str, str, str, str, str]] = []
        record_digests: list[str] = []
        family_receipt_digests: list[str] = []
        validated_rows: list[
            tuple[StrataRowReceipt, int, dict[str, Any], tuple[str, ...]]
        ] = []
        for receipt in self.receipts:
            if receipt.authority is not self.authority:
                raise ProtocolViolation("strata batch contains a foreign authority receipt")
            _, receipt_index, history_wire, combined_labels = (
                receipt._validate_and_bind(
                    bindings=bindings,
                    authority_already_validated=True,
                )
            )
            validated_rows.append(
                (receipt, receipt_index, history_wire, combined_labels)
            )
            actual.append(
                (
                    receipt.join.authority_digest,
                    receipt.join.member_digest,
                    receipt.join.cut_digest,
                    receipt.join.materialization_slot_digest,
                    bindings.receipt_digests[receipt_index],
                )
            )
            record_digests.append(receipt.join.record_digest)
            family_receipt_digests.append(bindings.receipt_digests[receipt_index])
        if len(actual) != len(set(actual)):
            raise ProtocolViolation("strata batch contains duplicate allocation joins")
        if set(actual) != expected:
            missing = sorted(expected - set(actual))
            extra = sorted(set(actual) - expected)
            raise ProtocolViolation(
                "strata batch must exactly cover frozen allocation joins; "
                f"missing={missing}, extra={extra}"
            )
        if len(record_digests) != len(set(record_digests)):
            raise ProtocolViolation("one record digest cannot bind multiple strata rows")
        if len(family_receipt_digests) != len(set(family_receipt_digests)):
            raise ProtocolViolation(
                "one family materialization receipt cannot bind multiple strata rows"
            )
        return bindings, tuple(validated_rows)

    def _body(self) -> dict[str, Any]:
        bindings, validated_rows = self._validate_and_bind()
        receipt_wires = [
            receipt._wire_from_validated_unchecked(
                bindings,
                receipt_index,
                history_wire,
                combined_labels,
            )
            for receipt, receipt_index, history_wire, combined_labels in validated_rows
        ]
        body = {
            "schema_version": RECEIPT_BATCH_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_digest": bindings.authority_digest,
            "allocation_manifest_digest": bindings.judge_allocation_manifest_digest,
            "expected_join_count": len(
                self.authority.judge.materialization_ledger.receipts
            ),
            "receipt_count": len(self.receipts),
            "receipts": sorted(
                receipt_wires,
                key=lambda item: item["receipt_digest"],
            ),
            "blockers": [_BATCH_BLOCKER.to_wire()],
        }
        validate_json_like(body)
        return body

    @property
    def batch_digest(self) -> str:
        return digest_json(self._body())

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["batch_digest"] = digest_json(body)
        return body
