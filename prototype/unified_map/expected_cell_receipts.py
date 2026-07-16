"""Typed custody receipts for exact expected-cell JSON preimages.

``evaluation_cells.py`` currently binds query/oracle/request/response *digests*
through the pre-split family authority graph.  A digest alone is not custody of
the bytes which produced it.  This module closes that narrow gap without
claiming that benchmark freeze is complete:

* every query, oracle, raw request and raw response is retained as exact,
  canonical JSON bytes;
* a per-cell receipt exact-joins those bytes to a live-validated
  :class:`~prototype.unified_map.family_manifest.MaterializationReceipt`;
* sorted batches reject duplicate identities; and
* a root exact-joins the union of batch receipts to an
  :class:`~prototype.unified_map.evaluator.EvaluationManifest`.

The artifacts remain ``PRE-FREEZE``.  They do not establish external custody,
isolation, append-only publication, pair-endpoint authority, or an authorized
freeze issuer.  Consequently their wire forms contain code-owned E002/E003
blockers and can never set ``benchmark_freeze_eligible``.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    domain_digest,
    validate_json_like,
)
from .evaluator import (
    EvaluationCohort,
    EvaluationManifest,
    EvaluationSplit,
    EvaluationTask,
    ExpectedEvaluationCell,
    ExpectedPairCell,
    OODAttribution,
)
from .family_manifest import (
    FamilySplit,
    MaterializationReceipt,
    MaterializationReceiptLedger,
)
from . import evaluation_cells as evaluation_cells_module
from .evaluation_cells import (
    BenchmarkCoverageLock,
    ExpectedCellsScopeContract,
    FrozenCorpusShard,
    LockedShardCoverage,
    QueryCellContract,
)
from .world_registry import registry_digest


PREIMAGE_PROTOCOL = "ucm-expected-cell-canonical-preimage/1"
RECEIPT_PROTOCOL = "ucm-expected-cell-preimage-receipt/1"
BATCH_PROTOCOL = "ucm-expected-cell-preimage-batch/1"
ROOT_PROTOCOL = "ucm-expected-cell-preimage-root/1"
E002_CODE = "UCM-E002-ISOLATION_INCOMPLETE"
E003_CODE = "UCM-E003-HARNESS_INCOMPLETE"

# A reviewed code change must replace this unready default with the eventual
# v1 lock.  Tests may temporarily replace this module global with a fully typed
# fixture lock, exactly as ``test_evaluation_cells.py`` does for the compiler.
CODE_OWNED_COVERAGE_LOCK = evaluation_cells_module.BENCHMARK_V1_COVERAGE_LOCK
# Exact corpus shard wires (including candidate/judge/status digests) require a
# separate reviewed pin because BenchmarkCoverageLock intentionally fixes only
# the outer coverage shape and authority roots.  Empty means PRE-FREEZE cannot
# issue a structural root yet.
CODE_OWNED_CORPUS_SCOPE_PINS: tuple[FrozenCorpusShard, ...] = ()
CODE_OWNED_SCOPE_CONTRACT_DIGEST: str | None = None
CODE_OWNED_EXPECTED_MANIFEST_DIGEST: str | None = None
CODE_OWNED_MATERIALIZATION_LEDGERS: tuple[MaterializationReceiptLedger, ...] = ()


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
    if value != value.lower():
        raise ProtocolViolation(f"{label} must use lowercase hexadecimal")
    return value


def _exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ProtocolViolation(
            f"{label} schema mismatch: missing={missing}, extra={extra}"
        )


def _seal_or_validate(
    instance: object,
    attribute: str,
    expected: str,
    *,
    initialize: bool,
    label: str,
) -> None:
    current = getattr(instance, attribute, None)
    if initialize and current is None:
        object.__setattr__(instance, attribute, expected)
        return
    if current is None:
        raise ProtocolViolation(f"{label} seal is missing")
    _digest(current, f"{label} seal")
    if current != expected:
        raise ProtocolViolation(f"{label} changed after construction")


def _blockers() -> list[dict[str, str]]:
    """Return fresh, code-owned blockers; callers never supply status fields."""

    return [
        {
            "code": E002_CODE,
            "artifact": "expected-cell-preimage-custody",
            "detail": "these local receipts do not prove candidate/judge isolation",
        },
        {
            "code": E003_CODE,
            "artifact": "expected-cell-preimage-custody",
            "detail": (
                "external custody, pair endpoints, append-only publication, and "
                "authorized freeze issuance remain incomplete"
            ),
        },
    ]


class CellPreimageKind(str, Enum):
    QUERY_CELL = "query_cell"
    ORACLE_TARGET = "oracle_target"
    RAW_REQUEST = "raw_request"
    RAW_RESPONSE = "raw_response"


def _kind_wire(value: CellPreimageKind) -> str:
    if value is CellPreimageKind.QUERY_CELL:
        return "query_cell"
    if value is CellPreimageKind.ORACLE_TARGET:
        return "oracle_target"
    if value is CellPreimageKind.RAW_REQUEST:
        return "raw_request"
    if value is CellPreimageKind.RAW_RESPONSE:
        return "raw_response"
    raise ProtocolViolation("preimage kind enum identity is invalid")


def _kind_from_wire(value: object) -> CellPreimageKind:
    if value == "query_cell" and type(value) is str:
        return CellPreimageKind.QUERY_CELL
    if value == "oracle_target" and type(value) is str:
        return CellPreimageKind.ORACLE_TARGET
    if value == "raw_request" and type(value) is str:
        return CellPreimageKind.RAW_REQUEST
    if value == "raw_response" and type(value) is str:
        return CellPreimageKind.RAW_RESPONSE
    raise ProtocolViolation("preimage kind is invalid")


def _decode_canonical_object(value: bytes, label: str) -> dict[str, Any]:
    if type(value) is not bytes:
        raise ProtocolViolation(f"{label} must be exact bytes")
    try:
        text = value.decode("utf-8", errors="strict")
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} must be canonical UTF-8 JSON") from exc
    if type(payload) is not dict:
        raise ProtocolViolation(f"{label} must encode an exact JSON object")
    validate_json_like(payload, path=label)
    if canonical_json_bytes(payload) != value:
        raise ProtocolViolation(f"{label} bytes are not exact canonical JSON")
    return payload


@dataclass(frozen=True, slots=True)
class CanonicalCellPreimage:
    """Immutable snapshot of one exact canonical JSON object preimage."""

    kind: CellPreimageKind
    canonical_bytes: bytes
    _sealed_artifact_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validated_body(initialize=True)

    @classmethod
    def from_payload(
        cls, kind: CellPreimageKind, payload: dict[str, Any]
    ) -> "CanonicalCellPreimage":
        if type(payload) is not dict:
            raise ProtocolViolation("preimage payload must be an exact object")
        # Canonicalization is the custody boundary.  No reference to ``payload``
        # survives, so later nested caller mutation cannot change the receipt.
        return cls(kind, canonical_json_bytes(payload))

    @classmethod
    def from_wire(cls, value: object) -> "CanonicalCellPreimage":
        if type(value) is not dict:
            raise ProtocolViolation("canonical preimage wire must be an exact object")
        validate_json_like(value, path="canonical preimage wire")
        _exact_keys(
            value,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "encoding",
                    "byte_length",
                    "canonical_bytes_base64",
                    "preimage_digest",
                    "artifact_digest",
                }
            ),
            "canonical preimage wire",
        )
        if value["schema_version"] != PREIMAGE_PROTOCOL:
            raise ProtocolViolation("canonical preimage protocol is invalid")
        if value["encoding"] != "base64":
            raise ProtocolViolation("canonical preimage encoding is invalid")
        encoded = value["canonical_bytes_base64"]
        if type(encoded) is not str or not encoded:
            raise ProtocolViolation("canonical preimage base64 must be non-empty")
        try:
            raw = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as exc:
            raise ProtocolViolation("canonical preimage base64 is invalid") from exc
        if base64.b64encode(raw).decode("ascii") != encoded:
            raise ProtocolViolation("canonical preimage base64 is non-canonical")
        if type(value["byte_length"]) is not int or value["byte_length"] != len(raw):
            raise ProtocolViolation("canonical preimage byte_length mismatch")
        _digest(value["preimage_digest"], "canonical preimage digest")
        _digest(value["artifact_digest"], "canonical preimage artifact digest")
        result = cls(_kind_from_wire(value["kind"]), raw)
        if canonical_json_bytes(value) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("canonical preimage wire is stale or non-canonical")
        return result

    def _body_unchecked(self) -> dict[str, Any]:
        encoded = base64.b64encode(self.canonical_bytes).decode("ascii")
        return {
            "schema_version": PREIMAGE_PROTOCOL,
            "kind": _kind_wire(self.kind),
            "encoding": "base64",
            "byte_length": len(self.canonical_bytes),
            "canonical_bytes_base64": encoded,
            "preimage_digest": digest_bytes(self.canonical_bytes),
        }

    def _validated_body(self, *, initialize: bool = False) -> dict[str, Any]:
        if type(self.kind) is not CellPreimageKind:
            raise ProtocolViolation("preimage kind must be CellPreimageKind")
        _decode_canonical_object(self.canonical_bytes, "canonical preimage")
        body = self._body_unchecked()
        artifact_digest = digest_json(body)
        _seal_or_validate(
            self,
            "_sealed_artifact_digest",
            artifact_digest,
            initialize=initialize,
            label="canonical preimage",
        )
        return body

    @property
    def payload(self) -> dict[str, Any]:
        # Return a fresh object so no mutable child is shared with the receipt.
        return _decode_canonical_object(self.canonical_bytes, "canonical preimage")

    @property
    def preimage_digest(self) -> str:
        self._validated_body()
        return digest_bytes(self.canonical_bytes)

    @property
    def artifact_digest(self) -> str:
        self._validated_body()
        return self._sealed_artifact_digest

    def to_wire(self) -> dict[str, Any]:
        body = self._validated_body()
        return {**body, "artifact_digest": self._sealed_artifact_digest}


_QUERY_KEYS = frozenset(
    {
        "shard_id",
        "source_record_id",
        "cut_alias",
        "task",
        "horizon",
        "policy_alias",
        "ood_attribution",
        "unsafe_action_ids",
    }
)
def _query_wire(query: CanonicalCellPreimage) -> dict[str, Any]:
    payload = query.payload
    _exact_keys(payload, _QUERY_KEYS, "query-cell preimage")
    return payload


def _validate_query_join(
    query: CanonicalCellPreimage,
    cell: ExpectedEvaluationCell,
    materialization: MaterializationReceipt,
) -> dict[str, Any]:
    payload = _query_wire(query)
    for key in ("shard_id", "source_record_id", "cut_alias", "policy_alias"):
        _name(payload[key], f"query-cell {key}")
    if payload["cut_alias"] != cell.cut_alias:
        raise ProtocolViolation("query cut_alias does not join expected cell")
    if payload["task"] != cell.task.value:
        raise ProtocolViolation("query task does not join expected cell")
    if type(payload["horizon"]) is not int or payload["horizon"] < 0:
        raise ProtocolViolation("query horizon must be a non-negative integer")
    if payload["horizon"] != cell.horizon:
        raise ProtocolViolation("query horizon does not join expected cell")
    if payload["policy_alias"] != cell.policy_alias:
        raise ProtocolViolation("query policy_alias does not join expected cell")
    allowed_tasks = {item.value for item in EvaluationTask}
    if type(payload["task"]) is not str or payload["task"] not in allowed_tasks:
        raise ProtocolViolation("query task is invalid")
    allowed_ood = {item.value for item in OODAttribution}
    if (
        type(payload["ood_attribution"]) is not str
        or payload["ood_attribution"] not in allowed_ood
    ):
        raise ProtocolViolation("query ood_attribution is invalid")
    if payload["ood_attribution"] != cell.ood_attribution.value:
        raise ProtocolViolation("query ood_attribution does not join expected cell")
    unsafe = payload["unsafe_action_ids"]
    if (
        type(unsafe) is not list
        or any(type(item) is not str or not item for item in unsafe)
        or unsafe != sorted(set(unsafe))
    ):
        raise ProtocolViolation("query unsafe_action_ids must be sorted and unique")
    if (
        type(unsafe) is not list
        or any(type(item) is not str or not item for item in unsafe)
        or unsafe != sorted(set(unsafe))
    ):
        raise ProtocolViolation("query unsafe_action_ids must be sorted and unique")
    query_unsafe = set(unsafe)
    cell_unsafe = set(cell.unsafe_action_ids)
    w19_tail_intervention = (
        cell.world_slot == "W19"
        and cell.tail_member
        and cell.cohort is EvaluationCohort.POPULATION
        and cell.task is EvaluationTask.INTERVENTION
    )
    # Only W19 tail intervention cells may gain the separately frozen
    # contraindicated action at materialization.  Every other cell exact-joins
    # its pre-split unsafe inventory.
    if w19_tail_intervention:
        if not query_unsafe.issubset(cell_unsafe):
            raise ProtocolViolation("query unsafe_action_ids contradict expected cell")
    elif query_unsafe != cell_unsafe:
        raise ProtocolViolation("query unsafe_action_ids do not exact-join expected cell")
    return payload


def _expected_split(value: FamilySplit) -> EvaluationSplit:
    if value is FamilySplit.TRAIN:
        return EvaluationSplit.TRAIN
    if value is FamilySplit.VALIDATION:
        return EvaluationSplit.VALIDATION
    if value is FamilySplit.SEALED_TEST:
        return EvaluationSplit.TEST
    raise ProtocolViolation("materialization split enum identity is invalid")


def _derived_cell_record_id(
    cell: ExpectedEvaluationCell, source_record_id: str
) -> str:
    """Recompute the code-owned identity used by ``evaluation_cells.py``."""

    identity = {
        "scope_digest": cell.scope_digest,
        "world_slot": cell.world_slot,
        "panel_id": cell.panel_id,
        "source_record_id": source_record_id,
        "split": cell.split.value,
        "family_id": cell.family_id,
        "cut_alias": cell.cut_alias,
        "training_replicate_id": cell.training_replicate_id,
        "evaluation_replicate_id": cell.evaluation_replicate_id,
        "task": cell.task.value,
        "horizon": cell.horizon,
        "policy_alias": cell.policy_alias,
    }
    return "c-" + digest_json(
        {"schema_version": "ucm-evaluation-cell-id/1", **identity}
    )[7:]


def _derived_family_id(
    cell: ExpectedEvaluationCell, source_family_digest: str
) -> str:
    _digest(source_family_digest, "source family digest")
    return "f-" + digest_json(
        {
            "schema_version": "ucm-evaluation-family-id/1",
            "scope_digest": cell.scope_digest,
            "world_slot": cell.world_slot,
            "panel_id": cell.panel_id,
            "split": cell.split.value,
            "evaluation_replicate_id": cell.evaluation_replicate_id,
            "source_family_digest": source_family_digest,
        }
    )[7:]


def _derived_episode_alias(
    cell: ExpectedEvaluationCell, source_record_id: str
) -> str:
    return "e-" + digest_json(
        {
            "schema_version": "ucm-evaluation-episode-alias/1",
            "scope_digest": cell.scope_digest,
            "world_slot": cell.world_slot,
            "panel_id": cell.panel_id,
            "split": cell.split.value,
            "evaluation_replicate_id": cell.evaluation_replicate_id,
            "source_record_id": source_record_id,
        }
    )[7:]


def _derived_pair_id(cell: ExpectedPairCell, source_pair_id: str) -> str:
    """Recompute the path-free pair identity available at this layer.

    This binds the contract's source-pair name to manifest metadata.  It does
    not prove custody of the two endpoint rows; that remains an E003 blocker.
    """

    _name(source_pair_id, "source pair id")
    identity = {
        "scope_digest": cell.scope_digest,
        "world_slot": cell.world_slot,
        "panel_id": cell.panel_id,
        "source_pair_id": source_pair_id,
        "split": cell.split.value,
        "family_id": cell.family_id,
        "training_replicate_id": cell.training_replicate_id,
        "evaluation_replicate_id": cell.evaluation_replicate_id,
    }
    return "p-" + digest_json(
        {"schema_version": "ucm-evaluation-pair-cell-id/1", **identity}
    )[7:]


@dataclass(frozen=True, slots=True)
class ExpectedCellPreimageReceipt:
    """Exact bytes and authority join for one expected evaluation cell."""

    expected_cell: ExpectedEvaluationCell
    materialization_receipt: MaterializationReceipt
    query_cell: CanonicalCellPreimage
    oracle_target: CanonicalCellPreimage
    raw_request: CanonicalCellPreimage
    raw_response: CanonicalCellPreimage
    _sealed_receipt_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validated_body(initialize=True)

    @classmethod
    def from_wire(
        cls,
        value: object,
        *,
        expected_cell: ExpectedEvaluationCell,
        materialization_receipt: MaterializationReceipt,
    ) -> "ExpectedCellPreimageReceipt":
        if type(value) is not dict:
            raise ProtocolViolation("expected-cell receipt wire must be an exact object")
        validate_json_like(value, path="expected-cell receipt wire")
        _exact_keys(
            value,
            frozenset(
                {
                    "schema_version",
                    "status",
                    "freeze_grade_evidence",
                    "benchmark_freeze_eligible",
                    "identity_digest",
                    "expected_cell",
                    "expected_cell_digest",
                    "materialization_receipt",
                    "materialization_receipt_digest",
                    "preimages",
                    "blockers",
                    "receipt_digest",
                }
            ),
            "expected-cell receipt wire",
        )
        preimages = value["preimages"]
        if type(preimages) is not dict:
            raise ProtocolViolation("expected-cell preimages must be an exact object")
        _exact_keys(
            preimages,
            frozenset(
                {"query_cell", "oracle_target", "raw_request", "raw_response"}
            ),
            "expected-cell preimages",
        )
        result = cls(
            expected_cell=expected_cell,
            materialization_receipt=materialization_receipt,
            query_cell=CanonicalCellPreimage.from_wire(preimages["query_cell"]),
            oracle_target=CanonicalCellPreimage.from_wire(preimages["oracle_target"]),
            raw_request=CanonicalCellPreimage.from_wire(preimages["raw_request"]),
            raw_response=CanonicalCellPreimage.from_wire(preimages["raw_response"]),
        )
        if canonical_json_bytes(value) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("expected-cell receipt wire is stale or non-canonical")
        return result

    def _identity_wire(self) -> dict[str, Any]:
        evidence = self.materialization_receipt.evidence
        query = _query_wire(self.query_cell)
        return {
            "record_id": self.expected_cell.record_id,
            "source_record_id": query["source_record_id"],
            "materialization_record_id": evidence.record_id,
            "scope_digest": self.expected_cell.scope_digest,
            "materialization_slot_digest": evidence.materialization_slot_digest,
            "query_cell_digest": self.query_cell.preimage_digest,
        }

    @property
    def identity_digest(self) -> str:
        self._validated_body()
        return domain_digest(
            b"UCM\0EXPECTED_CELL_PREIMAGE_IDENTITY_V1\0",
            (canonical_json_bytes(self._identity_wire()),),
        )

    def _body_unchecked(self) -> dict[str, Any]:
        cell_wire = self.expected_cell.to_wire()
        materialization_wire = self.materialization_receipt.to_wire()
        identity_digest = domain_digest(
            b"UCM\0EXPECTED_CELL_PREIMAGE_IDENTITY_V1\0",
            (canonical_json_bytes(self._identity_wire()),),
        )
        body = {
            "schema_version": RECEIPT_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "identity_digest": identity_digest,
            "expected_cell": cell_wire,
            "expected_cell_digest": digest_json(cell_wire),
            "materialization_receipt": materialization_wire,
            "materialization_receipt_digest": (
                self.materialization_receipt.receipt_digest
            ),
            "preimages": {
                "query_cell": self.query_cell.to_wire(),
                "oracle_target": self.oracle_target.to_wire(),
                "raw_request": self.raw_request.to_wire(),
                "raw_response": self.raw_response.to_wire(),
            },
            "blockers": _blockers(),
        }
        validate_json_like(body)
        return body

    def _validated_body(self, *, initialize: bool = False) -> dict[str, Any]:
        if type(self.expected_cell) is not ExpectedEvaluationCell:
            raise ProtocolViolation("receipt expected_cell has wrong type")
        self.expected_cell.__post_init__()
        if type(self.materialization_receipt) is not MaterializationReceipt:
            raise ProtocolViolation("receipt materialization parent has wrong type")
        self.materialization_receipt.to_wire()  # live parent-authority validation
        expected_kinds = (
            (self.query_cell, CellPreimageKind.QUERY_CELL, "query_cell"),
            (self.oracle_target, CellPreimageKind.ORACLE_TARGET, "oracle_target"),
            (self.raw_request, CellPreimageKind.RAW_REQUEST, "raw_request"),
            (self.raw_response, CellPreimageKind.RAW_RESPONSE, "raw_response"),
        )
        for preimage, kind, label in expected_kinds:
            if type(preimage) is not CanonicalCellPreimage or preimage.kind is not kind:
                raise ProtocolViolation(f"receipt {label} preimage has wrong kind")
            preimage.to_wire()
        evidence = self.materialization_receipt.evidence
        if evidence.record_id != self.expected_cell.record_id:
            raise ProtocolViolation(
                "materialization row record_id does not join expected cell"
            )
        if self.expected_cell.split is not _expected_split(evidence.assigned_split):
            raise ProtocolViolation("expected cell split does not join materialization")
        unit = next(
            (
                item
                for item in self.materialization_receipt.source.units
                if item.authority_digest == evidence.authority_digest
            ),
            None,
        )
        if unit is None or unit.world_slot != self.expected_cell.world_slot:
            raise ProtocolViolation("expected cell world does not join source authority")
        selected_query = _validate_query_join(
            self.query_cell, self.expected_cell, self.materialization_receipt
        )
        if self.expected_cell.family_id != _derived_family_id(
            self.expected_cell, unit.family_digest
        ):
            raise ProtocolViolation(
                "expected cell family_id is not derived from source family authority"
            )
        source_record_id = selected_query["source_record_id"]
        if self.expected_cell.record_id != _derived_cell_record_id(
            self.expected_cell, source_record_id
        ):
            raise ProtocolViolation(
                "expected cell record_id is not derived from its exact source/query identity"
            )
        if self.expected_cell.episode_alias != _derived_episode_alias(
            self.expected_cell, source_record_id
        ):
            raise ProtocolViolation(
                "expected cell episode_alias is not derived from its exact source identity"
            )
        expected_digests = (
            (evidence.query_cell_digest, self.query_cell.preimage_digest, "query cell"),
            (
                evidence.oracle_target_digest,
                self.oracle_target.preimage_digest,
                "oracle target",
            ),
            (evidence.raw_request_digest, self.raw_request.preimage_digest, "raw request"),
            (
                evidence.raw_response_digest,
                self.raw_response.preimage_digest,
                "raw response",
            ),
        )
        for committed, actual, label in expected_digests:
            if committed != actual:
                raise ProtocolViolation(f"{label} preimage does not match committed digest")
        body = self._body_unchecked()
        receipt_digest = digest_json(body)
        _seal_or_validate(
            self,
            "_sealed_receipt_digest",
            receipt_digest,
            initialize=initialize,
            label="expected-cell receipt",
        )
        return body

    @property
    def record_id(self) -> str:
        self._validated_body()
        return self.expected_cell.record_id

    @property
    def selected_query_wire(self) -> dict[str, Any]:
        self._validated_body()
        return dict(
            _validate_query_join(
                self.query_cell,
                self.expected_cell,
                self.materialization_receipt,
            )
        )

    @property
    def receipt_digest(self) -> str:
        self._validated_body()
        return self._sealed_receipt_digest

    def to_wire(self) -> dict[str, Any]:
        body = self._validated_body()
        return {**body, "receipt_digest": self._sealed_receipt_digest}


@dataclass(frozen=True, slots=True)
class ExpectedCellReceiptBatch:
    """Canonical sorted subset of expected-cell receipts."""

    batch_id: str
    receipts: tuple[ExpectedCellPreimageReceipt, ...]
    _sealed_batch_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validated_body(initialize=True)

    @classmethod
    def from_wire(
        cls,
        value: object,
        *,
        receipts: tuple[ExpectedCellPreimageReceipt, ...],
    ) -> "ExpectedCellReceiptBatch":
        if type(value) is not dict:
            raise ProtocolViolation("expected-cell batch wire must be an exact object")
        validate_json_like(value, path="expected-cell batch wire")
        _exact_keys(
            value,
            frozenset(
                {
                    "schema_version",
                    "status",
                    "freeze_grade_evidence",
                    "benchmark_freeze_eligible",
                    "batch_id",
                    "scope_digest",
                    "record_ids",
                    "receipt_digests",
                    "exact_set_digest",
                    "receipts",
                    "blockers",
                    "batch_digest",
                }
            ),
            "expected-cell batch wire",
        )
        result = cls(value["batch_id"], receipts)
        if canonical_json_bytes(value) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("expected-cell batch wire is stale or non-canonical")
        return result

    @property
    def scope_digest(self) -> str:
        self._validated_body()
        return self.receipts[0].expected_cell.scope_digest

    def _set_entries(self) -> list[dict[str, str]]:
        return [
            {
                "record_id": item.expected_cell.record_id,
                "identity_digest": item.identity_digest,
                "receipt_digest": item.receipt_digest,
            }
            for item in self.receipts
        ]

    @property
    def exact_set_digest(self) -> str:
        self._validated_body()
        return domain_digest(
            b"UCM\0EXPECTED_CELL_PREIMAGE_BATCH_SET_V1\0",
            (canonical_json_bytes(self._set_entries()),),
        )

    def _body_unchecked(self) -> dict[str, Any]:
        entries = self._set_entries()
        body = {
            "schema_version": BATCH_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "batch_id": self.batch_id,
            "scope_digest": self.receipts[0].expected_cell.scope_digest,
            "record_ids": [item["record_id"] for item in entries],
            "receipt_digests": [item["receipt_digest"] for item in entries],
            "exact_set_digest": domain_digest(
                b"UCM\0EXPECTED_CELL_PREIMAGE_BATCH_SET_V1\0",
                (canonical_json_bytes(entries),),
            ),
            "receipts": [item.to_wire() for item in self.receipts],
            "blockers": _blockers(),
        }
        validate_json_like(body)
        return body

    def _validated_body(self, *, initialize: bool = False) -> dict[str, Any]:
        _name(self.batch_id, "expected-cell batch_id")
        if type(self.receipts) is not tuple or not self.receipts:
            raise ProtocolViolation("expected-cell batch receipts must be non-empty tuple")
        if any(type(item) is not ExpectedCellPreimageReceipt for item in self.receipts):
            raise ProtocolViolation("expected-cell batch contains wrong receipt type")
        for receipt in self.receipts:
            receipt.to_wire()
        record_ids = [item.expected_cell.record_id for item in self.receipts]
        if record_ids != sorted(record_ids):
            raise ProtocolViolation("expected-cell batch receipts must be sorted by record_id")
        if len(record_ids) != len(set(record_ids)):
            raise ProtocolViolation("expected-cell batch receipt identities must be unique")
        receipt_digests = [item.receipt_digest for item in self.receipts]
        if len(receipt_digests) != len(set(receipt_digests)):
            raise ProtocolViolation("expected-cell batch receipt digests must be unique")
        selected_queries = [
            canonical_json_bytes(item.selected_query_wire) for item in self.receipts
        ]
        if len(selected_queries) != len(set(selected_queries)):
            raise ProtocolViolation(
                "expected-cell batch executable query identities must be unique"
            )
        slot_digests = [
            item.materialization_receipt.evidence.materialization_slot_digest
            for item in self.receipts
        ]
        if any(item is None for item in slot_digests) or len(slot_digests) != len(
            set(slot_digests)
        ):
            raise ProtocolViolation(
                "expected-cell batch materialization slots must be unique"
            )
        scopes = {item.expected_cell.scope_digest for item in self.receipts}
        if len(scopes) != 1:
            raise ProtocolViolation("expected-cell batch crosses scope digests")
        body = self._body_unchecked()
        batch_digest = digest_json(body)
        _seal_or_validate(
            self,
            "_sealed_batch_digest",
            batch_digest,
            initialize=initialize,
            label="expected-cell batch",
        )
        return body

    @property
    def batch_digest(self) -> str:
        self._validated_body()
        return self._sealed_batch_digest

    def to_wire(self) -> dict[str, Any]:
        body = self._validated_body()
        return {**body, "batch_digest": self._sealed_batch_digest}


@dataclass(frozen=True, slots=True)
class ExpectedCellReceiptRoot:
    """Exact manifest-to-receipt-set root; still never freeze authority."""

    manifest: EvaluationManifest
    scope_contract: ExpectedCellsScopeContract
    batches: tuple[ExpectedCellReceiptBatch, ...]
    _sealed_root_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validated_body(initialize=True)

    @classmethod
    def from_wire(
        cls,
        value: object,
        *,
        manifest: EvaluationManifest,
        scope_contract: ExpectedCellsScopeContract,
        batches: tuple[ExpectedCellReceiptBatch, ...],
    ) -> "ExpectedCellReceiptRoot":
        if type(value) is not dict:
            raise ProtocolViolation("expected-cell root wire must be an exact object")
        validate_json_like(value, path="expected-cell root wire")
        _exact_keys(
            value,
            frozenset(
                {
                    "schema_version",
                    "status",
                    "freeze_grade_evidence",
                    "benchmark_freeze_eligible",
                    "benchmark_id",
                    "benchmark_revision",
                    "scope_digest",
                    "coverage_lock_digest",
                    "scope_contract_encoding",
                    "scope_contract_preimage_base64",
                    "scope_contract_digest",
                    "scope_contract_pin_digest",
                    "corpus_scope_pins",
                    "materialization_authority_pins",
                    "manifest_encoding",
                    "manifest_preimage_base64",
                    "manifest_digest",
                    "expected_manifest_pin_digest",
                    "expected_record_ids",
                    "expected_pair_ids",
                    "batch_ids",
                    "batch_digests",
                    "receipt_entries",
                    "receipt_set_root",
                    "batches",
                    "blockers",
                    "root_digest",
                }
            ),
            "expected-cell root wire",
        )
        result = cls(manifest, scope_contract, batches)
        if canonical_json_bytes(value) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("expected-cell root wire is stale or non-canonical")
        return result

    def _all_receipts(self) -> tuple[ExpectedCellPreimageReceipt, ...]:
        return tuple(receipt for batch in self.batches for receipt in batch.receipts)

    def _receipt_entries(self) -> list[dict[str, str]]:
        """Canonical semantic union, independent of transport batching."""

        return sorted(
            (
                {
                    "record_id": item.expected_cell.record_id,
                    "receipt_digest": item.receipt_digest,
                }
                for item in self._all_receipts()
            ),
            key=lambda item: item["record_id"],
        )

    def _corpus_scope_pins(self) -> list[dict[str, Any]]:
        return [
            {
                "shard_id": shard.shard_id,
                "world_slot": shard.world_slot,
                "panel_id": shard.panel_id,
                "split": shard.split.value,
                "training_replicate_id": shard.training_replicate_id,
                "evaluation_replicate_id": shard.evaluation_replicate_id,
                "candidate_digest": shard.candidate_digest,
                "judge_digest": shard.judge_digest,
                "status_digest": shard.status_digest,
            }
            for shard in sorted(
                CODE_OWNED_CORPUS_SCOPE_PINS,
                key=lambda item: canonical_json_bytes(item.to_wire()),
            )
        ]

    def _materialization_authority_pins(self) -> list[dict[str, Any]]:
        return sorted(
            (
                {
                    "source_digest": ledger.source.source_digest,
                    "assignment_digest": ledger.assignment.assignment_digest,
                    "ledger_digest": ledger.ledger_digest,
                    "receipt_digests": sorted(
                        item.receipt_digest for item in ledger.receipts
                    ),
                }
                for ledger in CODE_OWNED_MATERIALIZATION_LEDGERS
            ),
            key=canonical_json_bytes,
        )

    @property
    def receipt_set_root(self) -> str:
        self._validated_body()
        return domain_digest(
            b"UCM\0EXPECTED_CELL_PREIMAGE_ROOT_V1\0",
            (
                self.manifest.canonical_bytes,
                self.scope_contract.canonical_bytes,
                canonical_json_bytes(CODE_OWNED_COVERAGE_LOCK.to_wire()),
                canonical_json_bytes(self._corpus_scope_pins()),
                canonical_json_bytes(self._materialization_authority_pins()),
                canonical_json_bytes(self._receipt_entries()),
            ),
        )

    def _body_unchecked(self) -> dict[str, Any]:
        manifest_bytes = self.manifest.canonical_bytes
        scope_contract_bytes = self.scope_contract.canonical_bytes
        receipt_entries = self._receipt_entries()
        body = {
            "schema_version": ROOT_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "benchmark_id": CODE_OWNED_COVERAGE_LOCK.benchmark_id,
            "benchmark_revision": CODE_OWNED_COVERAGE_LOCK.benchmark_revision,
            "scope_digest": self.manifest.scope_digest,
            "coverage_lock_digest": CODE_OWNED_COVERAGE_LOCK.digest,
            "scope_contract_encoding": "base64",
            "scope_contract_preimage_base64": base64.b64encode(
                scope_contract_bytes
            ).decode("ascii"),
            "scope_contract_digest": digest_bytes(scope_contract_bytes),
            "scope_contract_pin_digest": CODE_OWNED_SCOPE_CONTRACT_DIGEST,
            "corpus_scope_pins": self._corpus_scope_pins(),
            "materialization_authority_pins": (
                self._materialization_authority_pins()
            ),
            "manifest_encoding": "base64",
            "manifest_preimage_base64": base64.b64encode(manifest_bytes).decode("ascii"),
            "manifest_digest": digest_bytes(manifest_bytes),
            "expected_manifest_pin_digest": CODE_OWNED_EXPECTED_MANIFEST_DIGEST,
            "expected_record_ids": sorted(
                item.record_id for item in self.manifest.expected_cells
            ),
            "expected_pair_ids": sorted(
                item.pair_id for item in self.manifest.expected_pairs
            ),
            "batch_ids": [item.batch_id for item in self.batches],
            "batch_digests": [item.batch_digest for item in self.batches],
            "receipt_entries": receipt_entries,
            "receipt_set_root": domain_digest(
                b"UCM\0EXPECTED_CELL_PREIMAGE_ROOT_V1\0",
                (
                    manifest_bytes,
                    scope_contract_bytes,
                    canonical_json_bytes(CODE_OWNED_COVERAGE_LOCK.to_wire()),
                    canonical_json_bytes(self._corpus_scope_pins()),
                    canonical_json_bytes(self._materialization_authority_pins()),
                    canonical_json_bytes(receipt_entries),
                ),
            ),
            "batches": [item.to_wire() for item in self.batches],
            "blockers": _blockers(),
        }
        validate_json_like(body)
        return body

    def _validated_body(self, *, initialize: bool = False) -> dict[str, Any]:
        if type(self.manifest) is not EvaluationManifest:
            raise ProtocolViolation("expected-cell root manifest has wrong type")
        self.manifest.__post_init__()
        # EvaluationManifest validates child types at construction but its
        # public method is not a recursive post-construction seal.  Revalidate
        # every live child before reading manifest bytes, so an object-level
        # int/float rewrite cannot hide behind Python's loose equality.
        for cell in self.manifest.expected_cells:
            cell.__post_init__()
        for pair in self.manifest.expected_pairs:
            pair.__post_init__()
            pair.thresholds.__post_init__()
        if self.manifest.w19_safety is not None:
            self.manifest.w19_safety.__post_init__()
        lock = CODE_OWNED_COVERAGE_LOCK
        if type(lock) is not BenchmarkCoverageLock:
            raise ProtocolViolation("code-owned coverage lock has wrong type")
        lock.__post_init__()
        for locked_shard in lock.shards:
            locked_shard.__post_init__()
            for template in (
                *locked_shard.population_queries,
                *locked_shard.probe_queries,
            ):
                template.__post_init__()
        if not lock.ready:
            raise ProtocolViolation("code-owned coverage lock is not ready")
        if type(self.scope_contract) is not ExpectedCellsScopeContract:
            raise ProtocolViolation("expected-cell root scope contract has wrong type")
        self.scope_contract.__post_init__()
        self.scope_contract.family_lineage.__post_init__()
        self.scope_contract.authority_roots.__post_init__()
        for shard in self.scope_contract.shards:
            shard.__post_init__()
        for query in self.scope_contract.queries:
            query.__post_init__()
        for pair in self.scope_contract.pairs:
            pair.__post_init__()
            pair.thresholds.__post_init__()
        if self.scope_contract.w19_safety is not None:
            self.scope_contract.w19_safety.__post_init__()
        if (
            self.scope_contract.benchmark_id != lock.benchmark_id
            or self.scope_contract.benchmark_revision != lock.benchmark_revision
        ):
            raise ProtocolViolation(
                "scope contract benchmark identity is not code-owned"
            )
        if self.scope_contract.coverage_lock_digest != lock.digest:
            raise ProtocolViolation(
                "scope contract does not join code-owned coverage lock"
            )
        if self.scope_contract.scope_digest != lock.scope_digest:
            raise ProtocolViolation("scope digest is not pinned by coverage lock")
        if (
            self.scope_contract.family_lineage.source_digest
            != lock.family_source_digest
            or self.scope_contract.family_lineage.manifest_digest
            != lock.family_manifest_digest
            or self.scope_contract.family_lineage.seal_digest
            != lock.family_seal_digest
            or self.scope_contract.authority_roots.scope_manifest_digest
            != lock.scope_manifest_digest
            or self.scope_contract.authority_roots.raw_roots_digest
            != lock.raw_roots_digest
        ):
            raise ProtocolViolation(
                "scope contract authority roots do not join code-owned coverage lock"
            )
        pins = CODE_OWNED_CORPUS_SCOPE_PINS
        if type(pins) is not tuple or not pins:
            raise ProtocolViolation("code-owned corpus scope pins are not ready")
        if any(type(item) is not FrozenCorpusShard for item in pins):
            raise ProtocolViolation("code-owned corpus scope pin has wrong type")
        for pin in pins:
            pin.__post_init__()
        pin_ids = [item.shard_id for item in pins]
        if len(pin_ids) != len(set(pin_ids)):
            raise ProtocolViolation("code-owned corpus scope pin identities repeat")
        pinned_wires = sorted(
            (canonical_json_bytes(item.to_wire()) for item in pins)
        )
        contract_shard_wires = sorted(
            canonical_json_bytes(item.to_wire())
            for item in self.scope_contract.shards
        )
        if contract_shard_wires != pinned_wires:
            raise ProtocolViolation(
                "scope contract corpus shards do not exact-join code-owned pins"
            )
        pin_coverage_identities = {
            (
                item.world_slot,
                item.panel_id,
                item.split,
                item.training_replicate_id,
                item.evaluation_replicate_id,
            )
            for item in pins
        }
        if len(pin_coverage_identities) != len(pins):
            raise ProtocolViolation(
                "code-owned corpus pins repeat a coverage identity"
            )
        if len(pins) != len(lock.shards) or pin_coverage_identities != {
            item.identity for item in lock.shards
        }:
            raise ProtocolViolation(
                "corpus scope pins do not exactly cover code-owned shard identities"
            )
        locked_by_coverage_identity = {item.identity: item for item in lock.shards}
        for pin in pins:
            identity = (
                pin.world_slot,
                pin.panel_id,
                pin.split,
                pin.training_replicate_id,
                pin.evaluation_replicate_id,
            )
            locked_shard = locked_by_coverage_identity[identity]
            if {item.value for item in pin.required_tasks} != {
                item.task.value for item in locked_shard.population_queries
            }:
                raise ProtocolViolation(
                    "corpus required_tasks contradict code-owned population query scope"
                )
        if self.scope_contract.scope_digest != self.manifest.scope_digest:
            raise ProtocolViolation("scope contract does not join manifest scope")
        if self.scope_contract.registry_digest != registry_digest():
            raise ProtocolViolation("scope contract registry digest is not code-owned")
        if self.manifest.cell_contract_digest != self.scope_contract.digest:
            raise ProtocolViolation(
                "manifest is not pinned to the exact expected-cell scope contract"
            )
        for manifest_value, contract_value, label in (
            (
                self.manifest.forced_known_max_known,
                self.scope_contract.forced_known_max_known,
                "forced_known_max_known",
            ),
            (
                self.manifest.forced_known_max_unknown,
                self.scope_contract.forced_known_max_unknown,
                "forced_known_max_unknown",
            ),
        ):
            if canonical_json_bytes({"value": manifest_value}) != canonical_json_bytes(
                {"value": float(contract_value)}
            ):
                raise ProtocolViolation(
                    f"manifest {label} does not exact-join scope contract"
                )
        contract_safety = self.scope_contract.w19_safety
        manifest_safety = self.manifest.w19_safety
        if (contract_safety is None) != (manifest_safety is None):
            raise ProtocolViolation("manifest W19 safety does not join scope contract")
        if contract_safety is not None and manifest_safety is not None:
            if (
                contract_safety.contraindicated_action_id
                != manifest_safety.contraindicated_action_id
                or canonical_json_bytes(
                    {"value": float(contract_safety.catastrophic_margin)}
                )
                != canonical_json_bytes(
                    {"value": manifest_safety.catastrophic_margin}
                )
            ):
                raise ProtocolViolation(
                    "manifest W19 action/margin do not exact-join scope contract"
                )
        # Pair endpoints are not yet retained here (E003), but the path-free
        # metadata that both artifacts already carry must still exact-join.
        contract_pairs = self.scope_contract.pairs
        manifest_pairs = self.manifest.expected_pairs
        if len(contract_pairs) != len(manifest_pairs):
            raise ProtocolViolation(
                "manifest pair metadata does not exactly cover scope contract"
            )
        contract_shards_by_id = {
            item.shard_id: item for item in self.scope_contract.shards
        }
        used_contract_pair_identities: set[tuple[str, str]] = set()
        for manifest_pair in manifest_pairs:
            matches: list[Any] = []
            for contract_pair in contract_pairs:
                shard = contract_shards_by_id.get(contract_pair.shard_id)
                if shard is None:
                    continue
                if (
                    manifest_pair.scope_digest != self.scope_contract.scope_digest
                    or manifest_pair.world_slot != shard.world_slot
                    or manifest_pair.panel_id != shard.panel_id
                    or manifest_pair.split is not shard.split
                    or manifest_pair.training_replicate_id
                    != shard.training_replicate_id
                    or manifest_pair.evaluation_replicate_id
                    != shard.evaluation_replicate_id
                ):
                    continue
                if manifest_pair.pair_id == _derived_pair_id(
                    manifest_pair, contract_pair.source_pair_id
                ):
                    matches.append(contract_pair)
            if len(matches) != 1:
                raise ProtocolViolation(
                    "manifest pair_id is not exactly derived from one contract pair"
                )
            contract_pair = matches[0]
            identity = (contract_pair.shard_id, contract_pair.source_pair_id)
            if identity in used_contract_pair_identities:
                raise ProtocolViolation(
                    "multiple manifest pairs map to one contract pair identity"
                )
            used_contract_pair_identities.add(identity)
            if canonical_json_bytes(manifest_pair.thresholds.to_wire()) != (
                canonical_json_bytes(contract_pair.thresholds.to_wire())
            ):
                raise ProtocolViolation(
                    "manifest pair thresholds do not exact-join scope contract"
                )
        if used_contract_pair_identities != {
            (item.shard_id, item.source_pair_id) for item in contract_pairs
        }:
            raise ProtocolViolation(
                "manifest pair metadata does not exactly cover scope contract"
            )
        if CODE_OWNED_SCOPE_CONTRACT_DIGEST is None:
            raise ProtocolViolation("code-owned scope contract pin is not ready")
        _digest(
            CODE_OWNED_SCOPE_CONTRACT_DIGEST,
            "code-owned scope contract digest",
        )
        if self.scope_contract.digest != CODE_OWNED_SCOPE_CONTRACT_DIGEST:
            raise ProtocolViolation("scope contract is not code-owned")
        if CODE_OWNED_EXPECTED_MANIFEST_DIGEST is None:
            raise ProtocolViolation("code-owned expected manifest pin is not ready")
        _digest(
            CODE_OWNED_EXPECTED_MANIFEST_DIGEST,
            "code-owned expected manifest digest",
        )
        if self.manifest.digest != CODE_OWNED_EXPECTED_MANIFEST_DIGEST:
            raise ProtocolViolation("expected manifest is not code-owned")
        if type(self.batches) is not tuple or not self.batches:
            raise ProtocolViolation("expected-cell root batches must be non-empty tuple")
        if any(type(item) is not ExpectedCellReceiptBatch for item in self.batches):
            raise ProtocolViolation("expected-cell root contains wrong batch type")
        for batch in self.batches:
            batch.to_wire()
        batch_ids = [item.batch_id for item in self.batches]
        if batch_ids != sorted(batch_ids):
            raise ProtocolViolation("expected-cell root batches must be sorted by batch_id")
        if len(batch_ids) != len(set(batch_ids)):
            raise ProtocolViolation("expected-cell root batch identities must be unique")
        batch_digests = [item.batch_digest for item in self.batches]
        if len(batch_digests) != len(set(batch_digests)):
            raise ProtocolViolation("expected-cell root batch digests must be unique")
        receipts = self._all_receipts()
        record_ids = [item.expected_cell.record_id for item in receipts]
        if len(record_ids) != len(set(record_ids)):
            raise ProtocolViolation("expected-cell root contains duplicate receipt identity")
        ledgers = CODE_OWNED_MATERIALIZATION_LEDGERS
        if type(ledgers) is not tuple or not ledgers:
            raise ProtocolViolation("code-owned materialization ledgers are not ready")
        if any(type(item) is not MaterializationReceiptLedger for item in ledgers):
            raise ProtocolViolation("code-owned materialization ledger has wrong type")
        authority_receipts: dict[str, bytes] = {}
        ledger_digests: list[str] = []
        for ledger in ledgers:
            ledger.to_wire()
            ledger_digests.append(ledger.ledger_digest)
            for authority_receipt in ledger.receipts:
                wire = canonical_json_bytes(authority_receipt.to_wire())
                digest = authority_receipt.receipt_digest
                if digest in authority_receipts:
                    raise ProtocolViolation(
                        "one materialization receipt belongs to multiple code-owned ledgers"
                    )
                authority_receipts[digest] = wire
        if len(ledger_digests) != len(set(ledger_digests)):
            raise ProtocolViolation("code-owned materialization ledgers repeat")
        actual_parent_digests = {
            item.materialization_receipt.receipt_digest for item in receipts
        }
        if actual_parent_digests != set(authority_receipts):
            raise ProtocolViolation(
                "expected-cell receipts do not exactly cover code-owned materialization ledgers"
            )
        for receipt in receipts:
            parent = receipt.materialization_receipt
            expected_parent_wire = authority_receipts.get(parent.receipt_digest)
            if expected_parent_wire != canonical_json_bytes(parent.to_wire()):
                raise ProtocolViolation(
                    "expected-cell receipt uses a foreign materialization authority"
                )
        parent_digests = [
            item.materialization_receipt.receipt_digest for item in receipts
        ]
        if len(parent_digests) != len(set(parent_digests)):
            raise ProtocolViolation(
                "expected cells must use unique materialization receipts"
            )
        slot_digests = [
            item.materialization_receipt.evidence.materialization_slot_digest
            for item in receipts
        ]
        if any(item is None for item in slot_digests) or len(slot_digests) != len(
            set(slot_digests)
        ):
            raise ProtocolViolation("expected cells must use unique materialization slots")
        for attribute, label in (
            ("raw_request", "raw request"),
            ("raw_response", "raw response"),
        ):
            digests = [getattr(item, attribute).preimage_digest for item in receipts]
            if len(digests) != len(set(digests)):
                raise ProtocolViolation(
                    f"expected cells must use unique actual {label} preimages"
                )
        expected_by_id = {
            item.record_id: item for item in self.manifest.expected_cells
        }
        if set(record_ids) != set(expected_by_id):
            missing = sorted(set(expected_by_id) - set(record_ids))
            extra = sorted(set(record_ids) - set(expected_by_id))
            raise ProtocolViolation(
                f"expected-cell root is not an exact manifest set: "
                f"missing={missing}, extra={extra}"
            )
        shards_by_id = {item.shard_id: item for item in self.scope_contract.shards}
        locked_by_identity = {item.identity: item for item in lock.shards}
        contract_query_wires = {
            canonical_json_bytes(item.to_wire()): item
            for item in self.scope_contract.queries
        }
        selected_query_wires = [
            canonical_json_bytes(item.selected_query_wire) for item in receipts
        ]
        if len(selected_query_wires) != len(set(selected_query_wires)):
            raise ProtocolViolation(
                "expected-cell root contains duplicate executable query identity"
            )
        if set(selected_query_wires) != set(contract_query_wires):
            missing = len(set(contract_query_wires) - set(selected_query_wires))
            extra = len(set(selected_query_wires) - set(contract_query_wires))
            raise ProtocolViolation(
                "receipt queries are not the exact scope-contract set: "
                f"missing={missing}, extra={extra}"
            )
        observed_template_wires_by_source: dict[
            tuple[str, str, EvaluationCohort], set[bytes]
        ] = {}
        for receipt in receipts:
            expected = expected_by_id[receipt.expected_cell.record_id]
            if canonical_json_bytes(receipt.expected_cell.to_wire()) != (
                canonical_json_bytes(expected.to_wire())
            ):
                raise ProtocolViolation("receipt expected-cell identity contradicts manifest")
            if receipt.expected_cell.scope_digest != self.manifest.scope_digest:
                raise ProtocolViolation("receipt scope does not join manifest")
            cell = receipt.expected_cell
            selected_query = receipt.selected_query_wire
            shard = shards_by_id.get(selected_query["shard_id"])
            if shard is None:
                raise ProtocolViolation("receipt query references an unpinned corpus shard")
            if (
                cell.world_slot != shard.world_slot
                or cell.panel_id != shard.panel_id
                or cell.split is not shard.split
                or cell.training_replicate_id != shard.training_replicate_id
                or cell.evaluation_replicate_id != shard.evaluation_replicate_id
            ):
                raise ProtocolViolation(
                    "expected cell world/panel/split/replicates do not join corpus pin"
                )
            if cell.task not in shard.required_tasks:
                raise ProtocolViolation("expected cell task is not declared by corpus shard")
            locked = locked_by_identity.get(
                (
                    shard.world_slot,
                    shard.panel_id,
                    shard.split,
                    shard.training_replicate_id,
                    shard.evaluation_replicate_id,
                )
            )
            if locked is None:
                raise ProtocolViolation("corpus shard is outside code-owned coverage lock")
            allowed_templates = (
                locked.population_queries
                if cell.cohort is EvaluationCohort.POPULATION
                else locked.probe_queries
            )
            selected_template_wire = canonical_json_bytes(
                {
                    "cut_alias": cell.cut_alias,
                    "task": cell.task.value,
                    "horizon": cell.horizon,
                    "policy_alias": cell.policy_alias,
                }
            )
            allowed_template_wires = {
                canonical_json_bytes(item.to_wire()) for item in allowed_templates
            }
            if selected_template_wire not in allowed_template_wires:
                raise ProtocolViolation(
                    "receipt query is outside code-owned cohort coverage"
                )
            observed_template_wires_by_source.setdefault(
                (
                    selected_query["shard_id"],
                    selected_query["source_record_id"],
                    cell.cohort,
                ),
                set(),
            ).add(selected_template_wire)
            query_unsafe = set(selected_query["unsafe_action_ids"])
            if cell.tail_member and not (
                cell.world_slot == "W19"
                and cell.cohort is EvaluationCohort.POPULATION
            ):
                raise ProtocolViolation("tail_member is invalid outside W19 population")
            if (
                cell.world_slot == "W19"
                and cell.tail_member
                and cell.task is EvaluationTask.INTERVENTION
            ):
                if self.manifest.w19_safety is None:
                    raise ProtocolViolation(
                        "W19 tail intervention receipt requires manifest safety authority"
                    )
                expected_unsafe = query_unsafe | {
                    self.manifest.w19_safety.contraindicated_action_id
                }
                if set(cell.unsafe_action_ids) != expected_unsafe:
                    raise ProtocolViolation(
                        "W19 tail unsafe_action_ids do not exact-join safety authority"
                    )
        for (shard_id, source_record_id, cohort), observed_wires in (
            observed_template_wires_by_source.items()
        ):
            shard = shards_by_id[shard_id]
            locked = locked_by_identity[
                (
                    shard.world_slot,
                    shard.panel_id,
                    shard.split,
                    shard.training_replicate_id,
                    shard.evaluation_replicate_id,
                )
            ]
            locked_templates = (
                locked.population_queries
                if cohort is EvaluationCohort.POPULATION
                else locked.probe_queries
            )
            expected_wires = {
                canonical_json_bytes(item.to_wire()) for item in locked_templates
            }
            if observed_wires != expected_wires:
                raise ProtocolViolation(
                    "source query template denominator contradicts code-owned scope: "
                    f"shard={shard_id}, source={source_record_id}, "
                    f"cohort={cohort.value}"
                )
        tail_aliases = tuple(
            sorted(
                {
                    item.episode_alias
                    for item in self.manifest.expected_cells
                    if item.world_slot == "W19"
                    and item.cohort is EvaluationCohort.POPULATION
                    and item.tail_member
                }
            )
        )
        if tail_aliases:
            safety = self.manifest.w19_safety
            if safety is None:
                raise ProtocolViolation("W19 tail cohort lacks safety authority")
            if safety.tail_episode_aliases != tail_aliases:
                raise ProtocolViolation(
                    "W19 safety aliases do not exactly cover the tail cohort"
                )
            if safety.tail_cohort_digest != safety.compute_digest(tail_aliases):
                raise ProtocolViolation("W19 tail cohort digest is not live-derived")
            intervention_aliases = {
                item.episode_alias
                for item in self.manifest.expected_cells
                if item.world_slot == "W19"
                and item.cohort is EvaluationCohort.POPULATION
                and item.tail_member
                and item.task is EvaluationTask.INTERVENTION
            }
            if intervention_aliases != set(tail_aliases):
                raise ProtocolViolation(
                    "W19 tail cohort lacks exact intervention-cell coverage"
                )
        elif self.manifest.w19_safety is not None:
            raise ProtocolViolation("W19 safety authority exists without a tail cohort")
        body = self._body_unchecked()
        root_digest = digest_json(body)
        _seal_or_validate(
            self,
            "_sealed_root_digest",
            root_digest,
            initialize=initialize,
            label="expected-cell root",
        )
        return body

    @property
    def root_digest(self) -> str:
        self._validated_body()
        return self._sealed_root_digest

    @property
    def benchmark_freeze_eligible(self) -> bool:
        self._validated_body()
        return False

    def to_wire(self) -> dict[str, Any]:
        body = self._validated_body()
        return {**body, "root_digest": self._sealed_root_digest}


__all__ = [
    "BATCH_PROTOCOL",
    "CanonicalCellPreimage",
    "CellPreimageKind",
    "E002_CODE",
    "E003_CODE",
    "ExpectedCellPreimageReceipt",
    "ExpectedCellReceiptBatch",
    "ExpectedCellReceiptRoot",
    "PREIMAGE_PROTOCOL",
    "RECEIPT_PROTOCOL",
    "ROOT_PROTOCOL",
]
