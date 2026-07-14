"""Judge-only seed derivation and counterfactual-family atomic splitting."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Iterable

from .canonical import ProtocolViolation, canonical_json_bytes, digest_json
from .worlds.base import WorldSplit


KDF_DOMAIN = b"UCM-BENCHMARK-KDF-v1\0"
COMMIT_DOMAIN = b"UCM-CONFIRM5-v1\0"


def _canonical_name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _sha256(value: object, label: str) -> str:
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
class SeedDeriver:
    """A purpose-separated deterministic KDF whose secret stays judge-side."""

    master_secret: bytes
    benchmark_id: str

    def __post_init__(self) -> None:
        if type(self.master_secret) is not bytes or len(self.master_secret) < 32:
            raise ProtocolViolation("master_secret must contain at least 256 bits")
        _canonical_name(self.benchmark_id, "benchmark_id")

    def derive_bytes(
        self,
        *,
        purpose: str,
        world_key: str,
        replicate_id: int,
        item_index: int,
        length: int = 32,
    ) -> bytes:
        _canonical_name(purpose, "purpose")
        _canonical_name(world_key, "world_key")
        if type(replicate_id) is not int or replicate_id < 0:
            raise ProtocolViolation("replicate_id must be non-negative")
        if type(item_index) is not int or item_index < 0:
            raise ProtocolViolation("item_index must be non-negative")
        if type(length) is not int or not 1 <= length <= 32:
            raise ProtocolViolation("derived seed length must be in [1,32]")
        message = KDF_DOMAIN + canonical_json_bytes(
            {
                "benchmark_id": self.benchmark_id,
                "item_index": item_index,
                "purpose": purpose,
                "replicate_id": replicate_id,
                "world_key": world_key,
            }
        )
        return hmac.new(self.master_secret, message, hashlib.sha256).digest()[:length]

    def derive_uint64(self, **scope: object) -> int:
        return int.from_bytes(self.derive_bytes(length=8, **scope), "big")


def seed_commitment(seed: bytes, nonce: bytes) -> str:
    if type(seed) is not bytes or len(seed) != 32:
        raise ProtocolViolation("confirmation seed must be exactly 256 bits")
    if type(nonce) is not bytes or len(nonce) < 16:
        raise ProtocolViolation("confirmation nonce must contain at least 128 bits")
    return "sha256:" + hashlib.sha256(COMMIT_DOMAIN + seed + nonce).hexdigest()


def verify_seed_commitment(commitment: str, seed: bytes, nonce: bytes) -> bool:
    _sha256(commitment, "commitment")
    return hmac.compare_digest(commitment, seed_commitment(seed, nonce))


@dataclass(frozen=True, slots=True)
class CounterfactualFamily:
    """Judge-only identity for every artifact sharing one latent/noise family."""

    family_key: str
    environment_key: str
    latent_draw_digest: str
    noise_skeleton_digest: str
    acquisition_schedule_digest: str

    def __post_init__(self) -> None:
        _canonical_name(self.family_key, "family_key")
        _canonical_name(self.environment_key, "environment_key")
        _sha256(self.latent_draw_digest, "latent_draw_digest")
        _sha256(self.noise_skeleton_digest, "noise_skeleton_digest")
        _sha256(self.acquisition_schedule_digest, "acquisition_schedule_digest")

    @property
    def digest(self) -> str:
        return digest_json(
            {
                "protocol": "ucm-counterfactual-family/1",
                "environment_key": self.environment_key,
                "latent_draw_digest": self.latent_draw_digest,
                "noise_skeleton_digest": self.noise_skeleton_digest,
                "acquisition_schedule_digest": self.acquisition_schedule_digest,
            }
        )


def partition_families(
    families: Iterable[CounterfactualFamily],
    *,
    split_secret: bytes,
    train_count: int,
    validation_count: int,
    test_count: int,
) -> dict[str, WorldSplit]:
    """Assign whole families to exact-size splits by keyed deterministic order."""

    if type(split_secret) is not bytes or len(split_secret) < 32:
        raise ProtocolViolation("split_secret must contain at least 256 bits")
    counts = (train_count, validation_count, test_count)
    if any(type(value) is not int or value < 0 for value in counts):
        raise ProtocolViolation("split counts must be non-negative integers")
    items = tuple(families)
    if len(items) != sum(counts):
        raise ProtocolViolation("split counts must exactly cover all families")
    keys = [family.family_key for family in items]
    digests = [family.digest for family in items]
    if len(keys) != len(set(keys)) or len(digests) != len(set(digests)):
        raise ProtocolViolation("family keys and identities must be unique")

    def order_key(family: CounterfactualFamily) -> tuple[bytes, str]:
        score = hmac.new(
            split_secret,
            b"UCM-FAMILY-SPLIT-v1\0" + family.digest.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return score, family.digest

    ordered = sorted(items, key=order_key)
    result: dict[str, WorldSplit] = {}
    boundaries = (train_count, train_count + validation_count)
    for index, family in enumerate(ordered):
        if index < boundaries[0]:
            split = WorldSplit.TRAIN
        elif index < boundaries[1]:
            split = WorldSplit.VALIDATION
        else:
            split = WorldSplit.SEALED_TEST
        result[family.family_key] = split
    return result


@dataclass(frozen=True, slots=True)
class SplitArtifact:
    """Judge-side row used to prove split isolation before corpus freeze."""

    artifact_digest: str
    family_digest: str
    split: WorldSplit
    episode_alias: str
    prefix_fingerprint: str
    pair_group: str | None = None

    def __post_init__(self) -> None:
        _sha256(self.artifact_digest, "artifact_digest")
        _sha256(self.family_digest, "family_digest")
        if type(self.split) is not WorldSplit:
            raise ProtocolViolation("split must be WorldSplit")
        _canonical_name(self.episode_alias, "episode_alias")
        _sha256(self.prefix_fingerprint, "prefix_fingerprint")
        if self.pair_group is not None:
            _canonical_name(self.pair_group, "pair_group")


@dataclass(frozen=True, slots=True)
class SplitAudit:
    artifact_count: int
    family_count: int
    pair_group_count: int
    per_split_artifacts: dict[str, int]


def audit_split_isolation(rows: Iterable[SplitArtifact]) -> SplitAudit:
    """Hard-fail exact/family/prefix/pair leakage across splits."""

    artifacts = tuple(rows)
    if not artifacts:
        raise ProtocolViolation("split audit needs at least one artifact")
    owners: dict[tuple[str, str], WorldSplit] = {}
    episode_aliases: set[str] = set()
    family_digests: set[str] = set()
    pair_groups: set[str] = set()
    counts = {split.value: 0 for split in WorldSplit}

    def claim(kind: str, identity: str, split: WorldSplit) -> None:
        key = kind, identity
        previous = owners.setdefault(key, split)
        if previous is not split:
            raise ProtocolViolation(
                f"cross-split leakage for {kind} {identity}: "
                f"{previous.value} vs {split.value}"
            )

    for row in artifacts:
        if row.episode_alias in episode_aliases:
            raise ProtocolViolation("episode_alias is reused")
        episode_aliases.add(row.episode_alias)
        family_digests.add(row.family_digest)
        counts[row.split.value] += 1
        claim("artifact", row.artifact_digest, row.split)
        claim("family", row.family_digest, row.split)
        claim("prefix", row.prefix_fingerprint, row.split)
        if row.pair_group is not None:
            pair_groups.add(row.pair_group)
            claim("pair_group", row.pair_group, row.split)
    return SplitAudit(
        artifact_count=len(artifacts),
        family_count=len(family_digests),
        pair_group_count=len(pair_groups),
        per_split_artifacts=counts,
    )
