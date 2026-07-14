"""Harness-owned sealing and identity for one shared UCM patient state."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4

from .canonical import ProtocolViolation, canonical_json_bytes, domain_digest


class StateClass(str, Enum):
    COMPRESSED_SHARED = "compressed_shared_state"
    DYNAMIC_SHARED = "dynamic_shared_state"
    FULL_HISTORY_BASELINE = "full_history_baseline"


ALLOWED_INERT_CODECS = frozenset(
    {
        "canonical-json-v1",
        "raw-f64le-v1",
    }
)


def _validate_payload_bytes(payload: bytes, codec: str) -> None:
    """Validate that an advertised inert codec really has inert bytes.

    Supporting a codec name without validating its bytes would allow an
    executable pickle (or a file handle wrapper) to be mislabeled as safe.
    Candidate code may interpret its own numeric/JSON state, but the harness
    never deserializes executable objects.
    """

    if codec == "canonical-json-v1":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("canonical JSON state payload is invalid") from exc
        if canonical_json_bytes(decoded) != payload:
            raise ProtocolViolation("canonical JSON state payload is not canonical")
        return
    if codec == "raw-f64le-v1":
        if len(payload) % 8:
            raise ProtocolViolation("raw-f64le state length must be a multiple of 8")
        # Parsing proves structural validity; non-finite values are rejected so
        # equality and downstream metrics remain deterministic.
        values = struct.iter_unpack("<d", payload)
        for (value,) in values:
            if value != value or value in {float("inf"), float("-inf")}:
                raise ProtocolViolation("raw-f64le state contains NaN/Infinity")
        return
    raise ProtocolViolation(f"state codec is not inert/allowed: {codec!r}")


def _digest(value: object, label: str) -> None:
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


@dataclass(frozen=True, slots=True)
class StatePayload:
    payload: bytes
    codec: str
    schema_version: str
    state_class: StateClass

    def __post_init__(self) -> None:
        if type(self.payload) is not bytes:
            raise ProtocolViolation("state payload must be exact bytes")
        if self.codec not in ALLOWED_INERT_CODECS:
            raise ProtocolViolation(f"state codec is not inert/allowed: {self.codec!r}")
        _validate_payload_bytes(self.payload, self.codec)
        if type(self.schema_version) is not str or not self.schema_version:
            raise ProtocolViolation("state schema_version must be non-empty")
        if type(self.state_class) is not StateClass:
            raise ProtocolViolation("state_class must be StateClass")

    @classmethod
    def from_json(
        cls,
        representation: Any,
        *,
        schema_version: str,
        state_class: StateClass,
    ) -> "StatePayload":
        return cls(
            payload=canonical_json_bytes(representation),
            codec="canonical-json-v1",
            schema_version=schema_version,
            state_class=state_class,
        )


@dataclass(frozen=True, slots=True)
class CandidateStateInput:
    """The only patient-specific value supplied to a fresh head worker."""

    payload: StatePayload

    def __post_init__(self) -> None:
        if type(self.payload) is not StatePayload:
            raise ProtocolViolation("head state input must contain StatePayload")


@dataclass(frozen=True, slots=True)
class HarnessStateRecord:
    state_instance_id: str
    state_id: str
    state_hash: str
    parent_state_hash: str | None
    operation: str
    delta_digest: str | None
    candidate_bundle_digest: str
    model_digest: str
    scope_digest: str
    catalog_digest: str
    as_of_available_at: int
    payload_size_bytes: int

    def __post_init__(self) -> None:
        if type(self.state_instance_id) is not str or not self.state_instance_id:
            raise ProtocolViolation("state_instance_id must be non-empty")
        if type(self.state_id) is not str or not self.state_id.startswith(
            "ucm-state:"
        ):
            raise ProtocolViolation("state_id is not harness-formatted")
        _digest(self.state_hash, "state_hash")
        if self.parent_state_hash is not None:
            _digest(self.parent_state_hash, "parent_state_hash")
        if self.delta_digest is not None:
            _digest(self.delta_digest, "delta_digest")
        for value, label in (
            (self.candidate_bundle_digest, "candidate_bundle_digest"),
            (self.model_digest, "model_digest"),
            (self.scope_digest, "scope_digest"),
            (self.catalog_digest, "catalog_digest"),
        ):
            _digest(value, label)
        if self.operation not in {"initialize", "update", "replay"}:
            raise ProtocolViolation("unknown state operation")
        if type(self.as_of_available_at) is not int:
            raise ProtocolViolation("as_of_available_at must be an integer")
        if type(self.payload_size_bytes) is not int or self.payload_size_bytes < 0:
            raise ProtocolViolation("payload_size_bytes must be non-negative")


@dataclass(frozen=True, slots=True)
class SealedState:
    candidate_input: CandidateStateInput
    record: HarnessStateRecord


def compute_state_hash(
    payload: StatePayload,
    *,
    candidate_bundle_digest: str,
    model_digest: str,
    scope_digest: str,
    catalog_digest: str,
    as_of_available_at: int,
) -> str:
    if type(payload) is not StatePayload:
        raise ProtocolViolation("payload must be StatePayload")
    for value, label in (
        (candidate_bundle_digest, "candidate_bundle_digest"),
        (model_digest, "model_digest"),
        (scope_digest, "scope_digest"),
        (catalog_digest, "catalog_digest"),
    ):
        _digest(value, label)
    if type(as_of_available_at) is not int:
        raise ProtocolViolation("as_of_available_at must be an integer")
    metadata = canonical_json_bytes(
        {
            "codec": payload.codec,
            "schema_version": payload.schema_version,
            "state_class": payload.state_class.value,
            "as_of_available_at": as_of_available_at,
        }
    )
    return domain_digest(
        b"UCM_STATE_V1\0",
        [
            candidate_bundle_digest.encode("ascii"),
            model_digest.encode("ascii"),
            scope_digest.encode("ascii"),
            catalog_digest.encode("ascii"),
            metadata,
            payload.payload,
        ],
    )


def seal_state(
    payload: StatePayload,
    *,
    candidate_bundle_digest: str,
    model_digest: str,
    scope_digest: str,
    catalog_digest: str,
    as_of_available_at: int,
    operation: str,
    parent_state_hash: str | None = None,
    delta_digest: str | None = None,
    state_instance_id: str | None = None,
) -> SealedState:
    state_hash = compute_state_hash(
        payload,
        candidate_bundle_digest=candidate_bundle_digest,
        model_digest=model_digest,
        scope_digest=scope_digest,
        catalog_digest=catalog_digest,
        as_of_available_at=as_of_available_at,
    )
    record = HarnessStateRecord(
        state_instance_id=state_instance_id or str(uuid4()),
        state_id="ucm-state:" + state_hash[7:23],
        state_hash=state_hash,
        parent_state_hash=parent_state_hash,
        operation=operation,
        delta_digest=delta_digest,
        candidate_bundle_digest=candidate_bundle_digest,
        model_digest=model_digest,
        scope_digest=scope_digest,
        catalog_digest=catalog_digest,
        as_of_available_at=as_of_available_at,
        payload_size_bytes=len(payload.payload),
    )
    return SealedState(candidate_input=CandidateStateInput(payload), record=record)
