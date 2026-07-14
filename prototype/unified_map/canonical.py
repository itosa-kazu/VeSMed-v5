"""Canonical inert-data helpers for the isolated UCM track.

This module is deliberately independent of ``prototype.contract`` and the K0
runner.  It defines bytes used by the UCM wire protocol; it does not define a
clinical state representation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from typing import Any


class ProtocolViolation(ValueError):
    """Raised when a value cannot cross a UCM protocol boundary."""


def validate_json_like(
    value: Any,
    *,
    path: str = "$",
    max_depth: int = 64,
    max_nodes: int = 1_000_000,
) -> None:
    """Validate a closed, side-effect-free JSON-like value.

    Exact built-in types are required.  This intentionally rejects dataclass
    instances, mapping subclasses, callbacks and values whose serialization
    could execute user code.
    """

    remaining = [max_nodes]

    def walk(node: Any, where: str, depth: int) -> None:
        remaining[0] -= 1
        if remaining[0] < 0:
            raise ProtocolViolation(f"{path}: value exceeds max_nodes")
        if depth > max_depth:
            raise ProtocolViolation(f"{where}: value exceeds max_depth")

        kind = type(node)
        if node is None or kind in {bool, int, str}:
            return
        if kind is float:
            if not math.isfinite(node):
                raise ProtocolViolation(f"{where}: NaN/Infinity is forbidden")
            return
        if kind is list:
            for index, item in enumerate(node):
                walk(item, f"{where}[{index}]", depth + 1)
            return
        if kind is dict:
            for key, item in node.items():
                if type(key) is not str:
                    raise ProtocolViolation(
                        f"{where}: object keys must be exact strings"
                    )
                walk(item, f"{where}.{key}", depth + 1)
            return
        raise ProtocolViolation(
            f"{where}: unsupported protocol type {kind.__module__}.{kind.__name__}"
        )

    walk(value, path, 0)


def canonical_json_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 JSON with one terminal LF."""

    validate_json_like(value)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (encoded + "\n").encode("utf-8")


def digest_bytes(value: bytes) -> str:
    if type(value) is not bytes:
        raise ProtocolViolation("digest input must be exact bytes")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_json_bytes(value))


def domain_digest(domain: bytes, parts: Sequence[bytes]) -> str:
    """Hash length-delimited parts under an explicit protocol domain."""

    if type(domain) is not bytes or not domain or b"\0" not in domain:
        raise ProtocolViolation("hash domain must be non-empty bytes with NUL")
    if type(parts) not in {tuple, list}:
        raise ProtocolViolation("hash parts must be a list or tuple")
    digest = hashlib.sha256()
    digest.update(domain)
    for index, part in enumerate(parts):
        if type(part) is not bytes:
            raise ProtocolViolation(f"hash part {index} is not exact bytes")
        digest.update(len(part).to_bytes(8, "big", signed=False))
        digest.update(part)
    return "sha256:" + digest.hexdigest()


def reject_privileged_keys(
    value: Any,
    *,
    forbidden: frozenset[str],
    path: str = "$",
) -> None:
    """Reject judge-only field names recursively in candidate-visible data."""

    validate_json_like(value, path=path)

    def normalize_key(key: str) -> str:
        # Treat camelCase, kebab-case and punctuation aliases as the same
        # protocol field.  A blacklist that only catches ``test_id`` but lets
        # ``testId`` through is not an information boundary.
        snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
        snake = re.sub(r"[^A-Za-z0-9]+", "_", snake)
        return snake.strip("_").lower()

    def walk(node: Any, where: str) -> None:
        if type(node) is dict:
            for key, item in node.items():
                normalized = normalize_key(key)
                if normalized in forbidden:
                    raise ProtocolViolation(
                        f"{where}.{key}: judge-private field is forbidden"
                    )
                walk(item, f"{where}.{key}")
        elif type(node) is list:
            for index, item in enumerate(node):
                walk(item, f"{where}[{index}]")

    walk(value, path)
