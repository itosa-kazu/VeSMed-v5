"""Exact parser and digests for the Unified Clinical Map scope manifest.

The manifest is the closed, machine-readable definition of the scope under
which a state-sufficiency claim is made.  In particular, ``scope_digest`` is
derived from the exact canonical manifest bytes and is never a field in those
bytes (which would create a self-reference).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    validate_json_like,
)

SCOPE_MANIFEST_SCHEMA = "ucm-scope-manifest/1"
SCOPE_AXES = ("P", "O", "A", "Q", "Pi", "Tau", "Gamma", "Y", "U", "D", "R")
SCOPE_DOMAIN = b"UCM_SCOPE_V1\0"

_TOP_LEVEL_KEYS = frozenset({"schema_version", "benchmark_id", "scope_id", "axes"})
_AXIS_KEYS = frozenset({"declarations"})
_DECLARATION_KEYS = frozenset({"declaration_id", "value"})


def _exact_object(
    value: object,
    expected_keys: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    validate_json_like(value, path=label)
    actual = frozenset(value)
    if actual != expected_keys:
        raise ProtocolViolation(
            f"{label} has missing/extra fields; "
            f"missing={sorted(expected_keys - actual)!r}, "
            f"extra={sorted(actual - expected_keys)!r}"
        )
    return value


def _canonical_id(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a non-empty canonical string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ProtocolViolation(f"{label} must be strict UTF-8") from exc
    return value


def _decode_exact_canonical_object(payload: object) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation("scope manifest must be exact bytes")

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(
                    f"scope manifest contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolViolation("scope manifest is not strict UTF-8 JSON") from exc
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_pairs)
    except ProtocolViolation:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProtocolViolation("scope manifest is not valid JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation("scope manifest must encode an exact JSON object")
    validate_json_like(value, path="scope manifest")
    try:
        rebuilt = canonical_json_bytes(value)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ProtocolViolation(
            "scope manifest is not canonical strict UTF-8 JSON"
        ) from exc
    if rebuilt != payload:
        raise ProtocolViolation(
            "scope manifest bytes are not canonical sorted compact JSON plus one LF"
        )
    return value


@dataclass(frozen=True, slots=True)
class ScopeDeclaration:
    """One named declaration in a scope-axis registry."""

    declaration_id: str
    value: Any

    def __post_init__(self) -> None:
        _canonical_id(self.declaration_id, "scope declaration_id")
        validate_json_like(self.value, path=f"declaration {self.declaration_id}.value")
        try:
            canonical_json_bytes(self.value)
        except (UnicodeEncodeError, ValueError) as exc:
            raise ProtocolViolation(
                f"declaration {self.declaration_id}.value is not canonical JSON data"
            ) from exc

    def to_wire(self) -> dict[str, Any]:
        return {"declaration_id": self.declaration_id, "value": self.value}

    @classmethod
    def from_wire(cls, value: object, *, axis_id: str) -> "ScopeDeclaration":
        body = _exact_object(
            value, _DECLARATION_KEYS, f"scope axis {axis_id} declaration"
        )
        return cls(
            declaration_id=_canonical_id(
                body["declaration_id"], f"scope axis {axis_id} declaration_id"
            ),
            value=body["value"],
        )


@dataclass(frozen=True, slots=True)
class ScopeAxisDeclarations:
    """Closed, non-empty declaration registry for one scope axis."""

    declarations: tuple[ScopeDeclaration, ...]

    def __post_init__(self) -> None:
        if type(self.declarations) is not tuple or not self.declarations:
            raise ProtocolViolation("scope axis declarations must be a non-empty tuple")
        if any(type(item) is not ScopeDeclaration for item in self.declarations):
            raise ProtocolViolation("scope axis declaration has an invalid DTO type")
        ids = tuple(item.declaration_id for item in self.declarations)
        if len(set(ids)) != len(ids):
            raise ProtocolViolation("scope axis declaration_ids must be unique")
        if ids != tuple(sorted(ids, key=lambda item: item.encode("utf-8"))):
            raise ProtocolViolation(
                "scope axis declaration_ids must be sorted by exact UTF-8 bytes"
            )

    def to_wire(self) -> dict[str, Any]:
        return {"declarations": [item.to_wire() for item in self.declarations]}

    @classmethod
    def from_wire(cls, value: object, *, axis_id: str) -> "ScopeAxisDeclarations":
        body = _exact_object(value, _AXIS_KEYS, f"scope axis {axis_id}")
        rows = body["declarations"]
        if type(rows) is not list or not rows:
            raise ProtocolViolation(
                f"scope axis {axis_id} declarations must be a non-empty list"
            )
        return cls(
            tuple(ScopeDeclaration.from_wire(row, axis_id=axis_id) for row in rows)
        )


@dataclass(frozen=True, slots=True)
class ScopeManifest:
    """Validated DTO for ``ucm-scope-manifest/1`` exact bytes."""

    benchmark_id: str
    scope_id: str
    axes: Mapping[str, ScopeAxisDeclarations]
    schema_version: str = SCOPE_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not str
            or self.schema_version != SCOPE_MANIFEST_SCHEMA
        ):
            raise ProtocolViolation(
                "scope manifest schema_version is not code-owned v1"
            )
        _canonical_id(self.benchmark_id, "scope manifest benchmark_id")
        _canonical_id(self.scope_id, "scope manifest scope_id")
        if not isinstance(self.axes, Mapping):
            raise ProtocolViolation("scope manifest axes must be a mapping")
        axis_copy = dict(self.axes)
        if frozenset(axis_copy) != frozenset(SCOPE_AXES):
            raise ProtocolViolation(
                "scope manifest axes must contain exactly all 11 axes"
            )
        for axis_id in SCOPE_AXES:
            if type(axis_copy[axis_id]) is not ScopeAxisDeclarations:
                raise ProtocolViolation(f"scope axis {axis_id} has an invalid DTO type")
        object.__setattr__(self, "axes", MappingProxyType(axis_copy))

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark_id": self.benchmark_id,
            "scope_id": self.scope_id,
            "axes": {axis_id: self.axes[axis_id].to_wire() for axis_id in SCOPE_AXES},
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def manifest_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def scope_digest(self) -> str:
        digest = hashlib.sha256()
        digest.update(SCOPE_DOMAIN)
        digest.update(self.canonical_bytes)
        return "sha256:" + digest.hexdigest()

    @classmethod
    def from_wire(cls, value: object) -> "ScopeManifest":
        body = _exact_object(value, _TOP_LEVEL_KEYS, "scope manifest")
        if body["schema_version"] != SCOPE_MANIFEST_SCHEMA:
            raise ProtocolViolation(
                "scope manifest schema_version is not code-owned v1"
            )
        axes = _exact_object(body["axes"], frozenset(SCOPE_AXES), "scope manifest axes")
        return cls(
            benchmark_id=_canonical_id(
                body["benchmark_id"], "scope manifest benchmark_id"
            ),
            scope_id=_canonical_id(body["scope_id"], "scope manifest scope_id"),
            axes={
                axis_id: ScopeAxisDeclarations.from_wire(axes[axis_id], axis_id=axis_id)
                for axis_id in SCOPE_AXES
            },
        )


def parse_scope_manifest_bytes(payload: bytes) -> ScopeManifest:
    """Parse one exact canonical v1 scope manifest, failing closed."""

    value = _decode_exact_canonical_object(payload)
    manifest = ScopeManifest.from_wire(value)
    if manifest.canonical_bytes != payload:
        raise ProtocolViolation("scope manifest DTO round-trip changed exact bytes")
    return manifest


def scope_manifest_digest_from_bytes(payload: bytes) -> str:
    """Return the ordinary artifact digest after exact manifest validation."""

    manifest = parse_scope_manifest_bytes(payload)
    return digest_bytes(manifest.canonical_bytes)


def scope_digest_from_bytes(payload: bytes) -> str:
    """Return ``SHA256(SCOPE_DOMAIN || exact canonical manifest bytes)``."""

    manifest = parse_scope_manifest_bytes(payload)
    digest = hashlib.sha256()
    digest.update(SCOPE_DOMAIN)
    digest.update(manifest.canonical_bytes)
    return "sha256:" + digest.hexdigest()


__all__ = [
    "SCOPE_AXES",
    "SCOPE_DOMAIN",
    "SCOPE_MANIFEST_SCHEMA",
    "ScopeAxisDeclarations",
    "ScopeDeclaration",
    "ScopeManifest",
    "parse_scope_manifest_bytes",
    "scope_digest_from_bytes",
    "scope_manifest_digest_from_bytes",
]
