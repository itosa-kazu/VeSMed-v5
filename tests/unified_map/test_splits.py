from __future__ import annotations

import itertools

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_json
from prototype.unified_map.splits import (
    CounterfactualFamily,
    SeedDeriver,
    SplitArtifact,
    audit_split_isolation,
    partition_families,
    seed_commitment,
    verify_seed_commitment,
)
from prototype.unified_map.worlds.base import WorldSplit


def digest(value: object) -> str:
    return digest_json(value)


def family(index: int) -> CounterfactualFamily:
    return CounterfactualFamily(
        family_key=f"private-family-{index}",
        environment_key="private-environment",
        latent_draw_digest=digest(["latent", index]),
        noise_skeleton_digest=digest(["noise", index]),
        acquisition_schedule_digest=digest(["schedule", index]),
    )


def test_seed_derivation_is_purpose_separated_and_order_independent() -> None:
    deriver = SeedDeriver(b"s" * 32, "ucm-benchmark-v1")
    scopes = [
        {
            "purpose": purpose,
            "world_key": "private-world",
            "replicate_id": replicate,
            "item_index": 7,
        }
        for purpose, replicate in itertools.product(["process", "schedule"], range(3))
    ]
    forward = [deriver.derive_uint64(**scope) for scope in scopes]
    reverse = [deriver.derive_uint64(**scope) for scope in reversed(scopes)]
    assert forward == list(reversed(reverse))
    assert len(set(forward)) == len(forward)


def test_seed_commitment_reveals_without_publishing_secret_early() -> None:
    seed = bytes(range(32))
    nonce = b"n" * 16
    commitment = seed_commitment(seed, nonce)
    assert verify_seed_commitment(commitment, seed, nonce)
    assert not verify_seed_commitment(commitment, b"x" * 32, nonce)


def test_family_partition_has_exact_counts_and_ignores_input_order() -> None:
    families = [family(index) for index in range(10)]
    first = partition_families(
        families,
        split_secret=b"k" * 32,
        train_count=6,
        validation_count=2,
        test_count=2,
    )
    second = partition_families(
        reversed(families),
        split_secret=b"k" * 32,
        train_count=6,
        validation_count=2,
        test_count=2,
    )
    assert first == second
    assert list(first.values()).count(WorldSplit.TRAIN) == 6
    assert list(first.values()).count(WorldSplit.VALIDATION) == 2
    assert list(first.values()).count(WorldSplit.SEALED_TEST) == 2


def artifact(
    index: int,
    split: WorldSplit,
    *,
    family_id: int | None = None,
    prefix_id: int | None = None,
    pair_group: str | None = None,
) -> SplitArtifact:
    return SplitArtifact(
        artifact_digest=digest(["artifact", index]),
        family_digest=digest(["family", index if family_id is None else family_id]),
        split=split,
        episode_alias=f"opaque-{index}",
        prefix_fingerprint=digest(["prefix", index if prefix_id is None else prefix_id]),
        pair_group=pair_group,
    )


def test_split_audit_accepts_multiple_artifacts_from_same_family_in_one_split() -> None:
    rows = [
        artifact(0, WorldSplit.TRAIN, family_id=0),
        artifact(1, WorldSplit.TRAIN, family_id=0),
        artifact(2, WorldSplit.VALIDATION, family_id=2),
        artifact(3, WorldSplit.SEALED_TEST, family_id=3),
    ]
    report = audit_split_isolation(rows)
    assert report.artifact_count == 4
    assert report.family_count == 3


@pytest.mark.parametrize("leak", ["family", "prefix", "pair_group"])
def test_split_audit_rejects_atomic_or_near_duplicate_leakage(leak: str) -> None:
    first = artifact(
        0,
        WorldSplit.TRAIN,
        family_id=5 if leak == "family" else 0,
        prefix_id=5 if leak == "prefix" else 0,
        pair_group="paired" if leak == "pair_group" else None,
    )
    second = artifact(
        1,
        WorldSplit.SEALED_TEST,
        family_id=5 if leak == "family" else 1,
        prefix_id=5 if leak == "prefix" else 1,
        pair_group="paired" if leak == "pair_group" else None,
    )
    with pytest.raises(ProtocolViolation, match="cross-split leakage"):
        audit_split_isolation([first, second])


def test_partition_rejects_duplicate_family_identity() -> None:
    duplicated = family(1)
    with pytest.raises(ProtocolViolation, match="unique"):
        partition_families(
            [duplicated, duplicated],
            split_secret=b"k" * 32,
            train_count=1,
            validation_count=0,
            test_count=1,
        )
