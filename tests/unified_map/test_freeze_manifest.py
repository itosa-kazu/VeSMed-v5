from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
)
from prototype.unified_map.freeze import (
    EMPTY_REQUIRED_PATHS_BLOCKER,
    MISSING_REQUIRED_PATHS_BLOCKER,
    OFFICIAL_FREEZE_ISSUER_BLOCKERS,
    REQUIRED_FREEZE_EVIDENCE_AXES,
    FreezeAuthorization,
    FreezeAxisEvidence,
    FreezeEvidenceStatus,
    FreezeStatus,
    authorize_freeze,
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
        status=FreezeStatus.PRE_FREEZE,
        files=files,
        source_revision="deadbeef",
        created_at="2026-07-15T00:00:00Z",
        prefreeze_blockers=blockers or ("unit-test-prefreeze",),
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
    assert verification.prefreeze_integrity_ok and verification.file_count == 3
    assert verification.integrity_ok  # compatibility alias remains non-authoritative
    assert verification.declared_status is FreezeStatus.PRE_FREEZE
    assert not verification.authorized_frozen
    assert not verification.ok
    assert set(OFFICIAL_FREEZE_ISSUER_BLOCKERS) <= set(
        verification.authorization_blockers
    )


def test_freeze_manifest_is_non_overwriting_and_detects_byte_drift(tmp_path: Path) -> None:
    root, names = repo_fixture(tmp_path)
    built = manifest(root, names)
    target, _ = write_freeze_manifest(tmp_path / "freeze", built)
    with pytest.raises(FileExistsError):
        write_freeze_manifest(tmp_path / "freeze", built)
    root.joinpath(*names[1].split("/")).write_bytes(b"changed\n")
    verification = verify_freeze_manifest(root, target)
    assert not verification.prefreeze_integrity_ok
    assert not verification.ok
    assert verification.drifted_paths == (names[1],)


def test_frozen_status_requires_no_blockers_and_every_required_path(tmp_path: Path) -> None:
    root, names = repo_fixture(tmp_path)
    files = inventory_files(root, names[:-1])
    with pytest.raises(ProtocolViolation, match="FROZEN-v1 issuance is disabled"):
        build_freeze_manifest(
            benchmark_id="ucm-benchmark-v1",
            status=FreezeStatus.FROZEN_V1,
            files=files,
            source_revision="deadbeef",
            created_at="2026-07-15T00:00:00Z",
            prefreeze_blockers=("oracle-reference-missing",),
            required_paths=names,
        )


def _passing_evidence(
    artifact_digests: tuple[str, ...] | None = None,
) -> tuple[FreezeAxisEvidence, ...]:
    digests = artifact_digests or tuple(
        digest_bytes(f"evidence:{axis}".encode("ascii"))
        for axis in REQUIRED_FREEZE_EVIDENCE_AXES
    )
    assert digests
    return tuple(
        FreezeAxisEvidence(
            axis=axis,
            status=FreezeEvidenceStatus.PASS,
            artifact_digest=digests[index % len(digests)],
            detail=f"unit evidence for {axis}",
        )
        for index, axis in enumerate(REQUIRED_FREEZE_EVIDENCE_AXES)
    )


def test_empty_caller_blocker_list_cannot_authorize_a_freeze(tmp_path: Path) -> None:
    root, names = repo_fixture(tmp_path)
    with pytest.raises(ProtocolViolation, match="FROZEN-v1 issuance is disabled"):
        build_freeze_manifest(
            benchmark_id="ucm-benchmark-v1",
            status=FreezeStatus.FROZEN_V1,
            files=inventory_files(root, names),
            source_revision="deadbeef",
            created_at="2026-07-15T00:00:00Z",
            prefreeze_blockers=(),
            required_paths=names,
        )


@pytest.mark.parametrize("rows", [(), _passing_evidence()[:-1], _passing_evidence()])
def test_generic_authorization_api_never_trusts_caller_evidence(
    rows: tuple[FreezeAxisEvidence, ...],
) -> None:
    with pytest.raises(ProtocolViolation, match="issuer is disabled"):
        authorize_freeze(
            benchmark_id="ucm-benchmark-v1",
            scope_digest=digest_bytes(b"scope"),
            source_revision="deadbeef",
            required_paths=("research/unified_map/BENCHMARK.md",),
            evidence=rows,
        )


def test_sixteen_same_digest_pass_rows_cannot_self_sign_a_frozen_manifest(
    tmp_path: Path,
) -> None:
    root, names = repo_fixture(tmp_path)
    files = inventory_files(root, names)
    same_digest = (files[0].sha256,)
    with pytest.raises(ProtocolViolation, match="issuer is disabled"):
        authorize_freeze(
            benchmark_id="ucm-benchmark-v1",
            scope_digest=digest_bytes(b"scope"),
            source_revision="deadbeef",
            required_paths=names,
            evidence=_passing_evidence(same_digest),
        )
    with pytest.raises(ProtocolViolation, match="FROZEN-v1 issuance is disabled"):
        build_freeze_manifest(
            benchmark_id="ucm-benchmark-v1",
            status=FreezeStatus.FROZEN_V1,
            files=files,
            source_revision="deadbeef",
            created_at="2026-07-15T00:00:00Z",
            prefreeze_blockers=(),
            required_paths=names,
        )


def test_freeze_authorization_dto_cannot_be_constructed_directly() -> None:
    with pytest.raises(ProtocolViolation, match="issuer is disabled"):
        FreezeAuthorization(
            benchmark_id="ucm-benchmark-v1",
            scope_digest=digest_bytes(b"scope"),
            source_revision="deadbeef",
            required_paths=("research/unified_map/BENCHMARK.md",),
            evidence=_passing_evidence(),
        )
    forged = object.__new__(FreezeAuthorization)
    with pytest.raises(ProtocolViolation, match="issuer is disabled"):
        forged.to_wire()


def test_empty_or_missing_inventory_stays_explicitly_pre_freeze(
    tmp_path: Path,
) -> None:
    root, names = repo_fixture(tmp_path)
    empty = build_freeze_manifest(
        benchmark_id="ucm-benchmark-v1",
        status=FreezeStatus.PRE_FREEZE,
        files=(),
        source_revision="deadbeef",
        created_at="2026-07-15T00:00:00Z",
        prefreeze_blockers=(),
        required_paths=(),
    )
    assert EMPTY_REQUIRED_PATHS_BLOCKER in empty["prefreeze_blockers"]
    target, _ = write_freeze_manifest(tmp_path / "empty-prefreeze", empty)
    verified = verify_freeze_manifest(root, target)
    assert verified.prefreeze_integrity_ok and not verified.ok

    partial = build_freeze_manifest(
        benchmark_id="ucm-benchmark-v1",
        status=FreezeStatus.PRE_FREEZE,
        files=inventory_files(root, names[:-1]),
        source_revision="deadbeef",
        created_at="2026-07-15T00:00:00Z",
        prefreeze_blockers=(),
        required_paths=names,
    )
    assert partial["missing_required_paths"] == [names[-1]]
    assert MISSING_REQUIRED_PATHS_BLOCKER in partial["prefreeze_blockers"]


def _write_unvalidated_manifest(directory: Path, value: dict) -> Path:
    """Bypass the writer to exercise verify-time closed-schema validation."""

    directory.mkdir(parents=True)
    target = directory / "FREEZE_MANIFEST.json"
    payload = canonical_json_bytes(value)
    target.write_bytes(payload)
    target.with_name(target.name + ".sha256").write_bytes(
        (digest_bytes(payload) + "  FREEZE_MANIFEST.json\n").encode("ascii")
    )
    return target


@pytest.mark.parametrize(
    "attack",
    (
        "extra-top-level",
        "remove-authority-blocker",
        "false-missing-list",
        "open-file-row",
        "inventory-outside-required",
        "fake-authorization-digest",
        "fake-frozen-status",
    ),
)
def test_verify_rechecks_closed_manifest_invariants(
    tmp_path: Path,
    attack: str,
) -> None:
    root, names = repo_fixture(tmp_path / "repo")
    attacked = manifest(root, names)
    if attack == "extra-top-level":
        attacked["attacker_claim"] = "PASS"
    elif attack == "remove-authority-blocker":
        attacked["prefreeze_blockers"].remove(OFFICIAL_FREEZE_ISSUER_BLOCKERS[0])
    elif attack == "false-missing-list":
        attacked["missing_required_paths"] = [names[0]]
    elif attack == "open-file-row":
        attacked["files"][0]["attacker_claim"] = "PASS"
    elif attack == "inventory-outside-required":
        attacked["required_paths"] = list(names[1:])
    elif attack == "fake-authorization-digest":
        attacked["freeze_authorization_digest"] = digest_bytes(b"fake")
    elif attack == "fake-frozen-status":
        attacked["benchmark_status"] = FreezeStatus.FROZEN_V1.value
        attacked["prefreeze_blockers"] = []
    else:  # pragma: no cover - exhaustive test table
        raise AssertionError(attack)
    target = _write_unvalidated_manifest(tmp_path / f"attack-{attack}", attacked)
    with pytest.raises(ProtocolViolation):
        verify_freeze_manifest(root, target)


def test_recomputed_sidecar_and_arbitrary_root_never_upgrade_prefreeze(
    tmp_path: Path,
) -> None:
    first_root, names = repo_fixture(tmp_path / "first")
    built = manifest(first_root, names)

    # The attacker can alter a non-authoritative PRE-FREEZE claim and recompute
    # its unkeyed sidecar.  Byte integrity may still validate, but authority may
    # not: ``ok`` is reserved for an issuer-authenticated frozen artifact.
    built["metadata"]["attacker_claim"] = "FROZEN-v1"
    target = _write_unvalidated_manifest(tmp_path / "recomputed", built)
    first = verify_freeze_manifest(first_root, target)
    assert first.prefreeze_integrity_ok
    assert not first.authorized_frozen
    assert not first.ok

    # Mirroring the inventoried bytes under an arbitrary alternate root likewise
    # proves only that the bytes match this PRE-FREEZE inventory.
    second_root, _ = repo_fixture(tmp_path / "second")
    second = verify_freeze_manifest(second_root, target)
    assert second.prefreeze_integrity_ok
    assert not second.authorized_frozen
    assert not second.ok


def test_writer_rejects_caller_fabricated_frozen_wire_even_with_new_sidecar_root(
    tmp_path: Path,
) -> None:
    root, names = repo_fixture(tmp_path / "repo")
    attacked = manifest(root, names)
    attacked["benchmark_status"] = FreezeStatus.FROZEN_V1.value
    attacked["prefreeze_blockers"] = []
    attacked["freeze_authorization_digest"] = digest_bytes(b"fake-issuer")
    attacked["metadata"]["freeze_authorization"] = {
        "protocol": "ucm-freeze-authorization/1",
        "evidence": [item.to_wire() for item in _passing_evidence()],
    }
    with pytest.raises(ProtocolViolation, match="not authorized"):
        write_freeze_manifest(tmp_path / "attacker-selected-root", attacked)


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
