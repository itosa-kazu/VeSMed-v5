from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_bytes
from prototype.unified_map.freeze import (
    FreezeStatus,
    build_freeze_manifest,
    inventory_files,
    verify_freeze_manifest,
    write_freeze_manifest,
    write_seed_commit,
    write_seed_reveal,
)
from prototype.unified_map.splits import seed_commitment


def repo_fixture(tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    names = (
        "research/unified_map/BENCHMARK.md",
        "prototype/unified_map/worlds/w01.py",
        "tests/unified_map/test_worlds_w01_w05.py",
    )
    for index, name in enumerate(names):
        path = tmp_path.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"fixture-{index}\n".encode("ascii"))
    return tmp_path, names


def manifest(root: Path, names: tuple[str, ...], *, blockers: tuple[str, ...] = ()) -> dict:
    files = inventory_files(root, reversed(names))
    return build_freeze_manifest(
        benchmark_id="ucm-benchmark-v1",
        status=FreezeStatus.PRE_FREEZE if blockers else FreezeStatus.FROZEN_V1,
        files=files,
        source_revision="deadbeef",
        created_at="2026-07-15T00:00:00Z",
        prefreeze_blockers=blockers,
        required_paths=names,
        metadata={"claim_level": "synthetic-only"},
    )


def test_inventory_and_manifest_are_order_independent_and_canonical(tmp_path: Path) -> None:
    root, names = repo_fixture(tmp_path)
    first = manifest(root, names)
    second = manifest(root, tuple(reversed(names)))
    assert first["files"] == second["files"]
    target, sidecar = write_freeze_manifest(tmp_path / "freeze", first)
    assert target.read_bytes().endswith(b"\n")
    assert sidecar.read_text("ascii") == (
        digest_bytes(target.read_bytes()) + "  FREEZE_MANIFEST.json\n"
    )
    verification = verify_freeze_manifest(root, target)
    assert verification.ok and verification.file_count == 3


def test_freeze_manifest_is_non_overwriting_and_detects_byte_drift(tmp_path: Path) -> None:
    root, names = repo_fixture(tmp_path)
    built = manifest(root, names)
    target, _ = write_freeze_manifest(tmp_path / "freeze", built)
    with pytest.raises(FileExistsError):
        write_freeze_manifest(tmp_path / "freeze", built)
    root.joinpath(*names[1].split("/")).write_bytes(b"changed\n")
    verification = verify_freeze_manifest(root, target)
    assert not verification.ok
    assert verification.drifted_paths == (names[1],)


def test_frozen_status_requires_no_blockers_and_every_required_path(tmp_path: Path) -> None:
    root, names = repo_fixture(tmp_path)
    files = inventory_files(root, names[:-1])
    with pytest.raises(ProtocolViolation, match="cannot freeze"):
        build_freeze_manifest(
            benchmark_id="ucm-benchmark-v1",
            status=FreezeStatus.FROZEN_V1,
            files=files,
            source_revision="deadbeef",
            created_at="2026-07-15T00:00:00Z",
            prefreeze_blockers=("oracle-reference-missing",),
            required_paths=names,
        )


@pytest.mark.parametrize(
    "metadata",
    [
        {"seed": "secret"},
        {"nested": {"nonce": "x"}},
        {"nested": {"rawSeed": "x"}},
    ],
)
def test_freeze_manifest_rejects_raw_seed_or_reveal_material(
    tmp_path: Path, metadata: dict
) -> None:
    root, names = repo_fixture(tmp_path)
    with pytest.raises(ProtocolViolation, match="raw seed/reveal"):
        build_freeze_manifest(
            benchmark_id="ucm-benchmark-v1",
            status=FreezeStatus.PRE_FREEZE,
            files=inventory_files(root, names),
            source_revision="deadbeef",
            created_at="2026-07-15T00:00:00Z",
            prefreeze_blockers=("not-ready",),
            required_paths=names,
            metadata=metadata,
        )


def test_seed_reveal_is_separate_append_only_and_hash_chained(tmp_path: Path) -> None:
    seed = bytes(range(32))
    nonce = b"n" * 16
    commitment = seed_commitment(seed, nonce)
    commit_path = write_seed_commit(
        tmp_path / "CONFIRM5_COMMIT.json",
        benchmark_freeze_digest="sha256:" + "a" * 64,
        commitment=commitment,
        draw_program_digest="sha256:" + "b" * 64,
        committed_at="2026-07-15T00:00:00Z",
    )
    assert seed.hex() not in commit_path.read_text("utf-8")
    reveal_path = write_seed_reveal(
        tmp_path / "CONFIRM5_REVEAL.json",
        commit_path=commit_path,
        seed=seed,
        nonce=nonce,
        revealed_at="2026-07-15T01:00:00Z",
    )
    reveal = json.loads(reveal_path.read_bytes())
    assert reveal["commit_artifact_digest"] == digest_bytes(commit_path.read_bytes())
    assert reveal["seed_hex"] == seed.hex()
    with pytest.raises(FileExistsError):
        write_seed_reveal(
            reveal_path,
            commit_path=commit_path,
            seed=seed,
            nonce=nonce,
            revealed_at="2026-07-15T02:00:00Z",
        )


def test_bad_seed_reveal_does_not_create_artifact(tmp_path: Path) -> None:
    seed = b"s" * 32
    nonce = b"n" * 16
    commit_path = write_seed_commit(
        tmp_path / "commit.json",
        benchmark_freeze_digest="sha256:" + "a" * 64,
        commitment=seed_commitment(seed, nonce),
        draw_program_digest="sha256:" + "b" * 64,
        committed_at="2026-07-15T00:00:00Z",
    )
    reveal_path = tmp_path / "reveal.json"
    with pytest.raises(ProtocolViolation, match="do not match"):
        write_seed_reveal(
            reveal_path,
            commit_path=commit_path,
            seed=b"x" * 32,
            nonce=nonce,
            revealed_at="2026-07-15T01:00:00Z",
        )
    assert not reveal_path.exists()
