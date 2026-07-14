"""Counter-based deterministic randomness for paired microworld rollouts."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from ..canonical import ProtocolViolation, canonical_json_bytes


def _key_bytes(master_seed: int, keys: tuple[Any, ...], lane: int) -> bytes:
    if type(master_seed) is not int or master_seed < 0 or master_seed >= 2**128:
        raise ProtocolViolation("master_seed must be an unsigned 128-bit integer")
    if type(lane) is not int or lane < 0:
        raise ProtocolViolation("random lane must be non-negative")
    key_wire: list[str | int] = []
    for key in keys:
        if type(key) not in {str, int}:
            raise ProtocolViolation("random keys must be exact strings or integers")
        key_wire.append(key)
    digest = hashlib.sha256()
    digest.update(b"UCM_KEYED_RANDOM_V1\0")
    digest.update(master_seed.to_bytes(16, "big", signed=False))
    digest.update(lane.to_bytes(8, "big", signed=False))
    digest.update(canonical_json_bytes(key_wire))
    return digest.digest()


def uniform01(master_seed: int, *keys: str | int, lane: int = 0) -> float:
    """A deterministic open-interval U(0,1) variate keyed by semantics."""

    raw = int.from_bytes(_key_bytes(master_seed, keys, lane)[:8], "big")
    return (raw + 0.5) / 2**64


def normal01(master_seed: int, *keys: str | int, lane: int = 0) -> float:
    """A deterministic standard normal using a fixed Box-Muller mapping."""

    first = uniform01(master_seed, *keys, lane=2 * lane)
    second = uniform01(master_seed, *keys, lane=2 * lane + 1)
    return math.sqrt(-2.0 * math.log(first)) * math.cos(
        2.0 * math.pi * second
    )


def bernoulli(
    probability: float,
    master_seed: int,
    *keys: str | int,
    lane: int = 0,
) -> bool:
    if type(probability) not in {int, float} or not 0.0 <= probability <= 1.0:
        raise ProtocolViolation("Bernoulli probability must be in [0,1]")
    return uniform01(master_seed, *keys, lane=lane) < probability


def categorical(
    probabilities: tuple[float, ...],
    master_seed: int,
    *keys: str | int,
    lane: int = 0,
) -> int:
    if type(probabilities) is not tuple or not probabilities:
        raise ProtocolViolation("categorical probabilities must be a tuple")
    if any(type(value) not in {int, float} or value < 0 for value in probabilities):
        raise ProtocolViolation("categorical probabilities must be non-negative")
    total = math.fsum(probabilities)
    if not math.isfinite(total) or total <= 0:
        raise ProtocolViolation("categorical probabilities have no finite mass")
    draw = uniform01(master_seed, *keys, lane=lane) * total
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += probability
        if draw < cumulative:
            return index
    return len(probabilities) - 1
