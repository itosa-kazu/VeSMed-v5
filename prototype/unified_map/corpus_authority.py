"""Exact-byte corpus joins for the PRE-FREEZE family/strata authorities.

The family and strata modules deliberately do not read corpus files.  This
module is the narrow bridge between their typed, pre-split authority graph and
the physically separated candidate/judge JSONL streams.  It never derives a
family, split, slot, pair, or stratum from a corpus row.  Rows may only join the
already constructed authorities, and their exact canonical bytes must match
the digests committed by :class:`RowMaterializationEvidence`.

This is still a PRE-FREEZE scaffold.  A successful structural join proves no
external custody or atomic publication.  Every result therefore carries an
unconditional UCM-E003 blocker and is never freeze-grade or benchmark-freeze
eligible.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Iterable
from weakref import ReferenceType, ref

from . import strata_manifest as _strata_authority
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    reject_privileged_keys,
    validate_json_like,
)
from .family_manifest import (
    AtomicLinkSemantic,
    FamilySplit,
    MaterializationReceiptLedger,
    MaterializationRole,
    PreSplitFamilySource,
    WeightedAtomicAssignment,
)
from .schema import PRIVILEGED_FIELD_NAMES
from .strata_manifest import StrataReceiptBatch, StrataRowReceipt


SCOPE_PROTOCOL = "ucm-authority-bound-corpus-scope/1"
AUDIT_PROTOCOL = "ucm-authority-bound-corpus-audit/1"
INCOMPLETE_CODE = "UCM-E003-HARNESS_INCOMPLETE"

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_WORLD_RE = re.compile(r"W(?:0[1-9]|1[0-9]|20)\Z")

_CANDIDATE_AUTHORITY_KEYS = frozenset(
    {
        "assigned_split",
        "atomic_link_digest",
        "authority_digest",
        "behavior_pair",
        "combined_labels",
        "family_assignment_digest",
        "family_digest",
        "family_materialization_receipt_digest",
        "family_source_digest",
        "judge_frozen_labels",
        "materialization_slot_digest",
        "member_digest",
        "pair_digest",
        "pair_id",
        "pair_side",
        "pre_split_allocation_manifest_digest",
        "strata",
        "stratum",
    }
)

_CANDIDATE_ROW_KEYS = frozenset(
    {
        "schema_version",
        "record_id",
        "catalog",
        "public_history",
        "scope_digest",
    }
)

_ROOT_IDS = tuple(
    sorted(
        {
            "dual_channel_authority",
            "family_assignment",
            "family_materialization_ledger",
            "family_source",
            "generator_bundle",
            "judge_allocation_authority",
            "materialization_receipt_root",
            "pre_split_strata_allocation_manifest",
            "public_strata_classifier",
            "query_contract",
            "split_policy",
            "strata_receipt_batch",
            "topology_contract",
        }
    )
)


# ``frozen=True`` prevents ordinary assignment, but it does not prevent a
# hostile in-process caller from using ``object.__setattr__`` and then
# replacing an in-object digest.  Preserve the first canonical body digest by
# object identity outside both scope and audit artifacts.  This is a local
# integrity guard only; the unconditional custody/atomic-publication blocker
# remains because a Python weakref registry is not an external custodian.
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
        was_initialized = existing is not None and existing[0]() is value
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


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    return value


def _world(value: object, label: str) -> str:
    if type(value) is not str or _WORLD_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be one of W01..W20")
    return value


def _path(value: object, label: str) -> Path:
    if not isinstance(value, Path):
        raise ProtocolViolation(f"{label} must be pathlib.Path")
    return value


def _split_wire(value: FamilySplit) -> str:
    if type(value) is not FamilySplit:
        raise ProtocolViolation("corpus split must be FamilySplit")
    return value.value


class CorpusAuthorityStatus(str, Enum):
    PRE_FREEZE_SCAFFOLD = "pre_freeze_scaffold"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True, weakref_slot=True)
class AuthorityBoundCorpusScope:
    """One world/panel/split corpus and its exact typed authority graph.

    Paths are local replay handles and are omitted from :meth:`to_wire`.
    Whole-file digests remain in the path-independent scope so a reorder or a
    newline rewrite cannot be hidden by the ledger's set-oriented receipts.
    """

    benchmark_id: str
    benchmark_revision: str
    scope_digest: str
    world_slot: str
    panel_id: str
    training_replicate_id: str
    evaluation_replicate_id: str
    split: FamilySplit
    candidate_path: Path
    judge_path: Path
    candidate_corpus_digest: str
    judge_corpus_digest: str
    family_source: PreSplitFamilySource
    family_assignment: WeightedAtomicAssignment
    family_ledger: MaterializationReceiptLedger
    strata_batch: StrataReceiptBatch
    _sealed_contract_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validate(allow_seal_initialization=True)

    def _validate_fields(self) -> None:
        _name(self.benchmark_id, "corpus benchmark_id")
        _name(self.benchmark_revision, "corpus benchmark_revision")
        _digest(self.scope_digest, "corpus scope_digest")
        _world(self.world_slot, "corpus world_slot")
        _name(self.panel_id, "corpus panel_id")
        _name(self.training_replicate_id, "corpus training_replicate_id")
        _name(self.evaluation_replicate_id, "corpus evaluation_replicate_id")
        _split_wire(self.split)
        candidate = _path(self.candidate_path, "candidate_path")
        judge = _path(self.judge_path, "judge_path")
        if candidate == judge:
            raise ProtocolViolation("candidate and judge corpus paths must be distinct")
        _digest(self.candidate_corpus_digest, "candidate_corpus_digest")
        _digest(self.judge_corpus_digest, "judge_corpus_digest")
        if type(self.family_source) is not PreSplitFamilySource:
            raise ProtocolViolation("family_source must be PreSplitFamilySource")
        if type(self.family_assignment) is not WeightedAtomicAssignment:
            raise ProtocolViolation(
                "family_assignment must be WeightedAtomicAssignment"
            )
        if type(self.family_ledger) is not MaterializationReceiptLedger:
            raise ProtocolViolation(
                "family_ledger must be MaterializationReceiptLedger"
            )
        if type(self.strata_batch) is not StrataReceiptBatch:
            raise ProtocolViolation("strata_batch must be StrataReceiptBatch")

    def _validate(
        self,
        *,
        allow_seal_initialization: bool = False,
    ) -> dict[str, Any]:
        self._validate_fields()
        body = self._body_unchecked()
        expected_digest = digest_json(body)
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_contract_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="authority-bound corpus scope seal is missing",
            changed_message="authority-bound corpus scope changed after construction",
        )
        return body

    def _root_wires(self) -> tuple[dict[str, str], ...]:
        authority = self.strata_batch.authority
        roots = {
            "dual_channel_authority": authority.authority_digest,
            "family_assignment": self.family_assignment.assignment_digest,
            "family_materialization_ledger": self.family_ledger.ledger_digest,
            "family_source": self.family_source.source_digest,
            "generator_bundle": self.family_source.generator_bundle_digest,
            "judge_allocation_authority": authority.judge.allocation_manifest_digest,
            "materialization_receipt_root": (
                authority.judge.materialization_receipt_root_digest
            ),
            "pre_split_strata_allocation_manifest": (
                authority.judge.allocation_manifest.manifest_digest
            ),
            "public_strata_classifier": authority.public.classifier_digest,
            "query_contract": self.family_source.query_contract_digest,
            "split_policy": self.family_assignment.split_policy_digest,
            "strata_receipt_batch": self.strata_batch.batch_digest,
            "topology_contract": self.family_source.topology_contract_digest,
        }
        if set(roots) != set(_ROOT_IDS):  # defensive maintenance assertion
            raise ProtocolViolation("corpus scope authority root inventory is stale")
        return tuple(
            {"root_id": root_id, "digest": roots[root_id]}
            for root_id in _ROOT_IDS
        )

    def _body_unchecked(self) -> dict[str, Any]:
        body = {
            "protocol": SCOPE_PROTOCOL,
            "status": CorpusAuthorityStatus.PRE_FREEZE_SCAFFOLD.value,
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "scope_digest": self.scope_digest,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "split": _split_wire(self.split),
            "candidate_corpus_digest": self.candidate_corpus_digest,
            "judge_corpus_digest": self.judge_corpus_digest,
            "authority_roots": list(self._root_wires()),
            "blockers": [_custody_blocker().to_wire()],
        }
        validate_json_like(body)
        return body

    def to_wire(self) -> dict[str, Any]:
        return self._validate()

    @property
    def contract_digest(self) -> str:
        self._validate()
        return self._sealed_contract_digest


@dataclass(frozen=True, slots=True)
class CorpusAuthorityBlocker:
    code: str
    artifact: str
    detail: str

    def __post_init__(self) -> None:
        if self.code != INCOMPLETE_CODE:
            raise ProtocolViolation("corpus authority blocker code is not code-owned")
        _name(self.artifact, "corpus authority blocker artifact")
        _name(self.detail, "corpus authority blocker detail")

    def to_wire(self) -> dict[str, str]:
        self.__post_init__()
        return {
            "code": self.code,
            "artifact": self.artifact,
            "detail": self.detail,
        }


def _block(artifact: str, detail: str) -> CorpusAuthorityBlocker:
    return CorpusAuthorityBlocker(INCOMPLETE_CODE, artifact, detail)


def _custody_blocker() -> CorpusAuthorityBlocker:
    return _block(
        "external_custody_and_atomic_publication",
        "typed local joins do not prove independent pre-split custody or one atomic publication of the authority roots and both corpus streams",
    )


@dataclass(frozen=True, slots=True)
class CorpusRootBinding:
    root_id: str
    digest: str | None

    def __post_init__(self) -> None:
        _name(self.root_id, "corpus root_id")
        if self.digest is not None:
            _digest(self.digest, f"{self.root_id} root digest")

    def to_wire(self) -> dict[str, str | None]:
        self.__post_init__()
        return {"root_id": self.root_id, "digest": self.digest}


@dataclass(frozen=True, slots=True, weakref_slot=True)
class AuthorityBoundCorpusAudit:
    benchmark_id: str
    benchmark_revision: str
    scope_digest: str
    world_slot: str
    panel_id: str
    training_replicate_id: str
    evaluation_replicate_id: str
    split: FamilySplit
    candidate_corpus_digest: str
    judge_corpus_digest: str
    record_count: int
    roots: tuple[CorpusRootBinding, ...]
    structural_blockers: tuple[CorpusAuthorityBlocker, ...]
    _sealed_audit_body_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validate(allow_seal_initialization=True)

    def _validate(
        self,
        *,
        allow_seal_initialization: bool = False,
    ) -> dict[str, Any]:
        _name(self.benchmark_id, "audit benchmark_id")
        _name(self.benchmark_revision, "audit benchmark_revision")
        _digest(self.scope_digest, "audit scope_digest")
        _world(self.world_slot, "audit world_slot")
        _name(self.panel_id, "audit panel_id")
        _name(self.training_replicate_id, "audit training_replicate_id")
        _name(self.evaluation_replicate_id, "audit evaluation_replicate_id")
        _split_wire(self.split)
        _digest(self.candidate_corpus_digest, "audit candidate_corpus_digest")
        _digest(self.judge_corpus_digest, "audit judge_corpus_digest")
        if type(self.record_count) is not int or self.record_count < 0:
            raise ProtocolViolation("audit record_count must be non-negative int")
        if type(self.roots) is not tuple or any(
            type(item) is not CorpusRootBinding for item in self.roots
        ):
            raise ProtocolViolation("audit roots must be typed tuple")
        root_ids = tuple(item.root_id for item in self.roots)
        if root_ids != _ROOT_IDS:
            raise ProtocolViolation(
                "audit roots must exactly cover the code-owned canonical inventory"
            )
        if type(self.structural_blockers) is not tuple or any(
            type(item) is not CorpusAuthorityBlocker
            for item in self.structural_blockers
        ):
            raise ProtocolViolation("audit structural_blockers must be typed tuple")
        if not self.structural_blockers and any(
            item.digest is None for item in self.roots
        ):
            raise ProtocolViolation(
                "structurally complete audit cannot contain an unavailable root"
            )
        body = self._body_unchecked()
        expected_digest = digest_json(body)
        _seal_or_validate_once(
            self,
            seal_attribute="_sealed_audit_body_digest",
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
            missing_message="authority-bound corpus audit seal is missing",
            changed_message="authority-bound corpus audit changed after construction",
        )
        return body

    def _status_unchecked(self) -> CorpusAuthorityStatus:
        return (
            CorpusAuthorityStatus.PRE_FREEZE_SCAFFOLD
            if not self.structural_blockers
            else CorpusAuthorityStatus.INCOMPLETE
        )

    def _blockers_unchecked(self) -> tuple[CorpusAuthorityBlocker, ...]:
        return (*self.structural_blockers, _custody_blocker())

    @property
    def status(self) -> CorpusAuthorityStatus:
        self._validate()
        return self._status_unchecked()

    @property
    def structural_join_complete(self) -> bool:
        self._validate()
        return not self.structural_blockers

    @property
    def blockers(self) -> tuple[CorpusAuthorityBlocker, ...]:
        self._validate()
        return self._blockers_unchecked()

    def _body_unchecked(self) -> dict[str, Any]:
        body = {
            "protocol": AUDIT_PROTOCOL,
            "status": self._status_unchecked().value,
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "live_pre_split_materialization_complete": False,
            "structural_join_complete": not self.structural_blockers,
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "scope_digest": self.scope_digest,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "split": _split_wire(self.split),
            "candidate_corpus_digest": self.candidate_corpus_digest,
            "judge_corpus_digest": self.judge_corpus_digest,
            "record_count": self.record_count,
            "authority_roots": [item.to_wire() for item in self.roots],
            "blockers": [item.to_wire() for item in self._blockers_unchecked()],
        }
        validate_json_like(body)
        return body

    def to_wire(self) -> dict[str, Any]:
        body = self._validate()
        body["audit_digest"] = self._sealed_audit_body_digest
        validate_json_like(body)
        return body

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class _JsonlRow:
    record_id: str
    value: dict[str, Any]
    line_digest: str


def _read_canonical_jsonl(
    path: Path,
    *,
    artifact: str,
) -> tuple[bytes, tuple[_JsonlRow, ...]]:
    if path.is_symlink() or not path.is_file():
        raise ProtocolViolation(f"{artifact} is missing, not a regular file, or a symlink")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(
            f"{artifact} cannot be read: {type(exc).__name__}: {exc}"
        ) from exc
    if not payload:
        raise ProtocolViolation(f"{artifact} is empty")
    lines = payload.splitlines(keepends=True)
    if not lines or b"".join(lines) != payload:
        raise ProtocolViolation(f"{artifact} has an invalid line framing")
    rows: list[_JsonlRow] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        label = f"{artifact}[{index}]"
        if not line.endswith(b"\n") or line.endswith(b"\r\n"):
            raise ProtocolViolation(f"{label} must end in exactly one LF")
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation(f"{label} is not canonical UTF-8 JSON") from exc
        if type(value) is not dict:
            raise ProtocolViolation(f"{label} must be an exact JSON object")
        validate_json_like(value, path=label)
        if canonical_json_bytes(value) != line:
            raise ProtocolViolation(f"{label} bytes are not canonical JSON plus LF")
        record_id = _name(value.get("record_id"), f"{label} record_id")
        if record_id in seen:
            raise ProtocolViolation(f"{artifact} contains duplicate record_id {record_id!r}")
        seen.add(record_id)
        rows.append(_JsonlRow(record_id, value, digest_bytes(line)))
    return payload, tuple(rows)


def _root_bindings(
    scope: AuthorityBoundCorpusScope,
    blockers: list[CorpusAuthorityBlocker],
    *,
    bindings: Any | None,
    validated_rows: tuple[tuple[Any, ...], ...],
) -> tuple[CorpusRootBinding, ...]:
    values: dict[str, str | None] = {root_id: None for root_id in _ROOT_IDS}
    if bindings is None:
        return tuple(CorpusRootBinding(key, None) for key in sorted(values))
    authority = scope.strata_batch.authority
    try:
        receipt_wires = [
            receipt._wire_from_validated_unchecked(
                bindings,
                receipt_index,
                history_wire,
                combined_labels,
            )
            for receipt, receipt_index, history_wire, combined_labels in validated_rows
        ]
        batch_body = {
            "schema_version": _strata_authority.RECEIPT_BATCH_PROTOCOL,
            "status": "pre_freeze_scaffold",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_digest": bindings.authority_digest,
            "allocation_manifest_digest": bindings.judge_allocation_manifest_digest,
            "expected_join_count": len(
                authority.judge.materialization_ledger.receipts
            ),
            "receipt_count": len(scope.strata_batch.receipts),
            "receipts": sorted(
                receipt_wires,
                key=lambda item: item["receipt_digest"],
            ),
            "blockers": [_strata_authority._BATCH_BLOCKER.to_wire()],
        }
        validate_json_like(batch_body)
        values.update(
            {
                "dual_channel_authority": bindings.authority_digest,
                "family_assignment": scope.family_assignment._sealed_assignment_digest,
                "family_materialization_ledger": scope.family_ledger._sealed_ledger_digest,
                "family_source": scope.family_source._sealed_source_digest,
                "generator_bundle": scope.family_source.generator_bundle_digest,
                "judge_allocation_authority": (
                    bindings.judge_allocation_manifest_digest
                ),
                "materialization_receipt_root": (
                    authority.judge._materialization_receipt_root_from_digests_unchecked(
                        bindings.receipt_digests
                    )
                ),
                "pre_split_strata_allocation_manifest": (
                    authority.judge.allocation_manifest._sealed_manifest_digest
                ),
                "public_strata_classifier": bindings.public_classifier_digest,
                "query_contract": scope.family_source.query_contract_digest,
                "split_policy": scope.family_assignment.split_policy_digest,
                "strata_receipt_batch": digest_json(batch_body),
                "topology_contract": scope.family_source.topology_contract_digest,
            }
        )
    except (AttributeError, ProtocolViolation) as exc:
        blockers.append(
            _block(
                "authority_roots",
                f"validated authority roots cannot be snapshotted: {exc}",
            )
        )
    for root_id, value in values.items():
        try:
            if value is not None:
                _digest(value, f"{root_id} root")
        except ProtocolViolation as exc:
            blockers.append(_block(root_id, f"authority root is invalid: {exc}"))
    if set(values) != set(_ROOT_IDS):  # defensive maintenance assertion
        blockers.append(_block("authority_roots", "authority root inventory is stale"))
    return tuple(CorpusRootBinding(key, values[key]) for key in _ROOT_IDS)


def _audit_authority_graph(
    scope: AuthorityBoundCorpusScope,
    blockers: list[CorpusAuthorityBlocker],
) -> None:
    source = scope.family_source
    assignment = scope.family_assignment
    ledger = scope.family_ledger
    authority = scope.strata_batch.authority
    judge = authority.judge

    if assignment.source is not source:
        blockers.append(_block("family_assignment", "assignment has a foreign family source"))
    if ledger.source is not source or ledger.assignment is not assignment:
        blockers.append(
            _block("family_materialization_ledger", "ledger has a foreign source or assignment")
        )
    if (
        judge.family_source is not source
        or judge.family_assignment is not assignment
        or judge.materialization_ledger is not ledger
    ):
        blockers.append(
            _block("dual_channel_authority", "strata authority has a foreign family authority graph")
        )
    if authority.public.benchmark_id != scope.benchmark_id:
        blockers.append(_block("public_strata_classifier", "classifier benchmark_id is cross-scope"))
    if authority.public.benchmark_revision != scope.benchmark_revision:
        blockers.append(
            _block("public_strata_classifier", "classifier benchmark_revision is cross-scope")
        )
    if (
        source.benchmark_id != scope.benchmark_id
        or source.benchmark_revision != scope.benchmark_revision
    ):
        blockers.append(_block("family_source", "family source benchmark identity is cross-scope"))
    if authority.public.world_slot != scope.world_slot or judge.world_slot != scope.world_slot:
        blockers.append(_block("dual_channel_authority", "strata authority world is cross-scope"))


def _judge_scope_digest(row: dict[str, Any]) -> str:
    present = [key for key in ("scope_digest", "record_scope_digest") if key in row]
    if len(present) != 1:
        raise ProtocolViolation(
            "judge row must contain exactly one of scope_digest or record_scope_digest"
        )
    return _digest(row[present[0]], f"judge row {present[0]}")


def _audit_row(
    scope: AuthorityBoundCorpusScope,
    candidate: _JsonlRow,
    judge: _JsonlRow,
    receipt: StrataRowReceipt,
    *,
    combined_labels: tuple[str, ...],
    slot: Any,
    pair_alias_by_digest: dict[str, str],
    pair_digest_by_alias: dict[str, str],
) -> list[CorpusAuthorityBlocker]:
    blockers: list[CorpusAuthorityBlocker] = []
    record_id = candidate.record_id
    evidence = receipt.join.family_receipt.evidence
    artifact = f"record:{record_id}"

    if judge.record_id != record_id or evidence.record_id != record_id:
        blockers.append(_block(artifact, "candidate/judge/authority record_id does not exact-join"))
        return blockers
    if candidate.line_digest != evidence.candidate_row_digest:
        blockers.append(_block(artifact, "candidate live line bytes digest does not match pre-split row commitment"))
    if judge.line_digest != evidence.judge_row_digest:
        blockers.append(_block(artifact, "judge live line bytes digest does not match pre-split row commitment"))

    candidate_wire = candidate.value
    judge_wire = judge.value
    if candidate_wire.get("schema_version") != "ucm-candidate-public-episode/1":
        blockers.append(_block(artifact, "candidate row has an unknown schema_version"))
    candidate_keys = frozenset(candidate_wire)
    if candidate_keys != _CANDIDATE_ROW_KEYS:
        blockers.append(
            _block(
                artifact,
                "candidate row is not the exact closed public schema; "
                f"missing={sorted(_CANDIDATE_ROW_KEYS - candidate_keys)!r}, "
                f"extra={sorted(candidate_keys - _CANDIDATE_ROW_KEYS)!r}",
            )
        )
    if judge_wire.get("schema_version") != "ucm-judge-private-episode/1":
        blockers.append(_block(artifact, "judge row has an unknown schema_version"))
    try:
        reject_privileged_keys(
            candidate_wire,
            forbidden=PRIVILEGED_FIELD_NAMES | _CANDIDATE_AUTHORITY_KEYS,
            path=f"$.candidate[{record_id}]",
        )
    except ProtocolViolation as exc:
        blockers.append(_block(artifact, f"candidate row crosses the public boundary: {exc}"))

    try:
        candidate_scope = _digest(candidate_wire.get("scope_digest"), "candidate row scope_digest")
    except ProtocolViolation as exc:
        blockers.append(_block(artifact, str(exc)))
    else:
        if candidate_scope != scope.scope_digest:
            blockers.append(_block(artifact, "candidate row belongs to a foreign scope"))
    try:
        judge_scope = _judge_scope_digest(judge_wire)
    except ProtocolViolation as exc:
        blockers.append(_block(artifact, str(exc)))
    else:
        if judge_scope != scope.scope_digest:
            blockers.append(_block(artifact, "judge row belongs to a foreign scope"))

    if judge_wire.get("world_slot") != scope.world_slot:
        blockers.append(_block(artifact, "judge world_slot contradicts the authority scope"))
    if judge_wire.get("panel_id") != scope.panel_id:
        blockers.append(_block(artifact, "judge panel_id contradicts the authority scope"))
    if judge_wire.get("split") != _split_wire(scope.split):
        blockers.append(_block(artifact, "judge split contradicts the corpus scope"))
    if judge_wire.get("split") != evidence.assigned_split.value:
        blockers.append(_block(artifact, "judge split contradicts the weighted atomic assignment"))

    public_history = candidate_wire.get("public_history")
    if type(public_history) is not dict or public_history.get("protocol") != "ucm-visible-history/1":
        blockers.append(_block(artifact, "candidate public_history is absent or has an unknown protocol"))
    else:
        history_digest = digest_json(public_history)
        if history_digest != evidence.public_history_digest:
            blockers.append(_block(artifact, "candidate public history contradicts the family receipt"))
        if judge_wire.get("public_history_digest") != history_digest:
            blockers.append(_block(artifact, "judge public_history_digest does not exact-join candidate history"))
        catalog = candidate_wire.get("catalog")
        if type(catalog) is not dict or public_history.get("catalog_digest") != digest_json(catalog):
            blockers.append(_block(artifact, "candidate catalog and public history do not exact-join"))

    hidden_state = judge_wire.get("hidden_state_at_cut")
    if hidden_state is None or type(hidden_state) not in {dict, list, str, int, float, bool}:
        blockers.append(_block(artifact, "judge hidden_state_at_cut is absent or invalid"))
    else:
        try:
            hidden_digest = digest_json(hidden_state)
        except ProtocolViolation as exc:
            blockers.append(_block(artifact, f"judge hidden state is invalid: {exc}"))
        else:
            if hidden_digest != evidence.hidden_state_at_cut_digest:
                blockers.append(_block(artifact, "judge hidden state contradicts the family receipt"))

    expected_labels = list(combined_labels)
    if judge_wire.get("strata") != expected_labels:
        blockers.append(_block(artifact, "judge strata labels are missing, extra, reordered, or not authority-derived"))
    if judge_wire.get("unverified_declared_strata") != []:
        blockers.append(_block(artifact, "unverified self-reported strata cannot enter an authority-bound corpus"))

    if (
        slot.reference.authority_digest != evidence.authority_digest
        or slot.reference.member_digest != evidence.member_digest
        or slot.cut_digest != evidence.cut_digest
        or slot.query_cell_digest != evidence.query_cell_digest
        or slot.materialization_role is not evidence.materialization_role
        or slot.atomic_link_digest != evidence.atomic_link_digest
    ):
        blockers.append(_block(artifact, "row receipt is cross-bound to a foreign source member, cut, slot, role, or atomic link"))

    if slot.pair_digest is None:
        if judge_wire.get("pair_id") is not None or judge_wire.get("pair_side") is not None:
            blockers.append(_block(artifact, "non-pair slot cannot claim pair identity"))
    else:
        pair_id = judge_wire.get("pair_id")
        if type(pair_id) is not str or not pair_id:
            blockers.append(_block(artifact, "pair slot lacks a non-empty judge pair_id"))
        elif pair_id in pair_digest_by_alias and pair_digest_by_alias[pair_id] != slot.pair_digest:
            blockers.append(_block(artifact, "one judge pair_id aliases multiple pre-split pairs"))
        elif slot.pair_digest in pair_alias_by_digest and pair_alias_by_digest[slot.pair_digest] != pair_id:
            blockers.append(_block(artifact, "one pre-split pair is replaced by multiple judge pair_ids"))
        else:
            pair_alias_by_digest[slot.pair_digest] = pair_id
            pair_digest_by_alias[pair_id] = slot.pair_digest
        if judge_wire.get("pair_side") != slot.pair_side:
            blockers.append(_block(artifact, "judge pair_side contradicts pre-split pair topology"))

    if slot.materialization_role is MaterializationRole.W19_ASSIGNMENT_ROW:
        link = next(
            (
                item
                for item in scope.family_source.atomic_links
                if item.link_digest == slot.atomic_link_digest
            ),
            None,
        )
        if (
            scope.world_slot != "W19"
            or link is None
            or link.semantic_type is not AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER
            or judge_wire.get("cohort") != "population"
            or judge_wire.get("population_denominator") is not True
            or judge_wire.get("probe_denominator") is not False
        ):
            blockers.append(_block(artifact, "W19 assignment-row population was replaced by a foreign role, block, or cohort"))
    return blockers


def _dedupe_blockers(
    values: Iterable[CorpusAuthorityBlocker],
) -> tuple[CorpusAuthorityBlocker, ...]:
    by_key = {(item.artifact, item.detail): item for item in values}
    return tuple(by_key[key] for key in sorted(by_key))


def audit_authority_bound_corpus(
    scope: AuthorityBoundCorpusScope,
) -> AuthorityBoundCorpusAudit:
    """Audit exact live bytes against typed authorities, always PRE-FREEZE.

    Environmental and cross-authority discrepancies are returned as typed
    INCOMPLETE blockers.  Only a malformed API argument raises directly.
    """

    if type(scope) is not AuthorityBoundCorpusScope:
        raise ProtocolViolation("scope must be AuthorityBoundCorpusScope")
    # Wrong API types are caller errors.  A canonical-but-rewritten scope is
    # instead reported as typed incomplete evidence so the audit remains a
    # useful fail-closed diagnostic for first-digest drift.
    scope._validate_fields()
    blockers: list[CorpusAuthorityBlocker] = []
    try:
        scope._validate()
    except (AttributeError, ProtocolViolation) as exc:
        blockers.append(
            _block(
                "corpus_scope",
                f"sealed corpus scope validation failed: {exc}",
            )
        )
    try:
        _audit_authority_graph(scope, blockers)
    except (AttributeError, ProtocolViolation) as exc:
        blockers.append(
            _block(
                "authority_graph",
                f"typed authority graph cannot be traversed: {exc}",
            )
        )
    bindings: Any | None = None
    validated_rows: tuple[tuple[Any, ...], ...] = ()
    try:
        bindings, validated_rows = scope.strata_batch._validate_and_bind()
    except (AttributeError, ProtocolViolation) as exc:
        blockers.append(
            _block(
                "strata_receipt_batch",
                f"typed batch authority validation failed: {exc}",
            )
        )
    roots = _root_bindings(
        scope,
        blockers,
        bindings=bindings,
        validated_rows=validated_rows,
    )

    candidate_payload = b""
    judge_payload = b""
    candidate_rows: tuple[_JsonlRow, ...] = ()
    judge_rows: tuple[_JsonlRow, ...] = ()
    try:
        candidate_payload, candidate_rows = _read_canonical_jsonl(
            scope.candidate_path,
            artifact="candidate_corpus",
        )
    except ProtocolViolation as exc:
        blockers.append(_block("candidate_corpus", str(exc)))
    try:
        judge_payload, judge_rows = _read_canonical_jsonl(
            scope.judge_path,
            artifact="judge_corpus",
        )
    except ProtocolViolation as exc:
        blockers.append(_block("judge_corpus", str(exc)))

    actual_candidate_digest = digest_bytes(candidate_payload)
    actual_judge_digest = digest_bytes(judge_payload)
    if actual_candidate_digest != scope.candidate_corpus_digest:
        blockers.append(_block("candidate_corpus", "live candidate corpus digest contradicts the scope"))
    if actual_judge_digest != scope.judge_corpus_digest:
        blockers.append(_block("judge_corpus", "live judge corpus digest contradicts the scope"))

    validated_by_record: dict[
        str,
        tuple[StrataRowReceipt, tuple[str, ...]],
    ] = {}
    try:
        source_slots = {
            slot.slot_digest: slot for slot in scope.family_source.materialization_slots
        }
        expected_receipts = {}
        for receipt, _, _, combined_labels in validated_rows:
            record_id = receipt.join.family_receipt.evidence.record_id
            expected_receipts[record_id] = receipt
            validated_by_record[record_id] = (receipt, combined_labels)
        if len(expected_receipts) != len(scope.strata_batch.receipts):
            raise ProtocolViolation("strata batch contains duplicate record_id joins")
    except (AttributeError, ProtocolViolation) as exc:
        blockers.append(_block("strata_receipt_batch", f"cannot enumerate authoritative records: {exc}"))
        expected_receipts = {}

    candidate_ids = tuple(item.record_id for item in candidate_rows)
    judge_ids = tuple(item.record_id for item in judge_rows)
    if candidate_rows and judge_rows and candidate_ids != judge_ids:
        blockers.append(_block("corpus_record_order", "candidate/judge record_id order does not exact-join"))
    expected_ids = set(expected_receipts)
    for label, rows in (("candidate", candidate_rows), ("judge", judge_rows)):
        actual_ids = {item.record_id for item in rows}
        if actual_ids != expected_ids:
            blockers.append(
                _block(
                    f"{label}_corpus",
                    f"record coverage mismatch; missing={sorted(expected_ids - actual_ids)!r}, extra={sorted(actual_ids - expected_ids)!r}",
                )
            )

    candidate_by_id = {item.record_id: item for item in candidate_rows}
    judge_by_id = {item.record_id: item for item in judge_rows}
    pair_alias_by_digest: dict[str, str] = {}
    pair_digest_by_alias: dict[str, str] = {}
    for record_id in sorted(expected_ids & set(candidate_by_id) & set(judge_by_id)):
        try:
            receipt, combined_labels = validated_by_record[record_id]
            slot_digest = receipt.join.materialization_slot_digest
            slot = source_slots.get(slot_digest)
            if slot is None:
                raise ProtocolViolation(
                    "strata receipt joins an unknown materialization slot"
                )
            blockers.extend(
                _audit_row(
                    scope,
                    candidate_by_id[record_id],
                    judge_by_id[record_id],
                    receipt,
                    combined_labels=combined_labels,
                    slot=slot,
                    pair_alias_by_digest=pair_alias_by_digest,
                    pair_digest_by_alias=pair_digest_by_alias,
                )
            )
        except (AttributeError, ProtocolViolation) as exc:
            blockers.append(
                _block(
                    f"record:{record_id}",
                    f"typed authority row join is invalid: {exc}",
                )
            )

    return AuthorityBoundCorpusAudit(
        benchmark_id=scope.benchmark_id,
        benchmark_revision=scope.benchmark_revision,
        scope_digest=scope.scope_digest,
        world_slot=scope.world_slot,
        panel_id=scope.panel_id,
        training_replicate_id=scope.training_replicate_id,
        evaluation_replicate_id=scope.evaluation_replicate_id,
        split=scope.split,
        candidate_corpus_digest=actual_candidate_digest,
        judge_corpus_digest=actual_judge_digest,
        record_count=len(candidate_rows),
        roots=roots,
        structural_blockers=_dedupe_blockers(blockers),
    )


__all__ = [
    "AUDIT_PROTOCOL",
    "SCOPE_PROTOCOL",
    "AuthorityBoundCorpusAudit",
    "AuthorityBoundCorpusScope",
    "CorpusAuthorityBlocker",
    "CorpusAuthorityStatus",
    "CorpusRootBinding",
    "INCOMPLETE_CODE",
    "audit_authority_bound_corpus",
]
