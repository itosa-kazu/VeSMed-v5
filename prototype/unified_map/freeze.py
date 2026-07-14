"""Append-only benchmark freeze manifests and commit/reveal artifacts.

The module provides tooling only.  Importing or testing it never declares the
current benchmark frozen; a ``FROZEN-v1`` manifest can be created only when the
caller supplies an empty blocker list and an exact required-file inventory.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    validate_json_like,
)
from .splits import seed_commitment, verify_seed_commitment


MANIFEST_PROTOCOL = "ucm-freeze-manifest/1"
COMMIT_PROTOCOL = "ucm-seed-commit/1"
REVEAL_PROTOCOL = "ucm-seed-reveal/1"
ALLOWED_PREFIXES = (
    "research/unified_map/",
    "prototype/unified_map/",
    "tests/unified_map/",
)
FORBIDDEN_SECRET_FIELDS = frozenset(
    {"seed", "nonce", "secret", "raw_seed", "seed_bytes", "reveal"}
)


class FreezeStatus(str, Enum):
    PRE_FREEZE = "PRE-FREEZE"
    FROZEN_V1 = "FROZEN-v1"


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _digest(value: object, label: str) -> str:
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


def _relative_path(value: object) -> str:
    if type(value) is not str or "\\" in value or value.startswith("/"):
        raise ProtocolViolation("freeze path must be a relative POSIX path")
    pure = PurePosixPath(value)
    if (
        not value
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or not value.startswith(ALLOWED_PREFIXES)
    ):
        raise ProtocolViolation("freeze path is outside the isolated UCM roots")
    return pure.as_posix()


@dataclass(frozen=True, slots=True)
class FreezeFile:
    path: str
    bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _relative_path(self.path)
        if type(self.bytes) is not int or self.bytes < 0:
            raise ProtocolViolation("freeze file size must be non-negative")
        _digest(self.sha256, "freeze file sha256")

    def to_wire(self) -> dict[str, Any]:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}


def inventory_files(repo_root: Path, relative_paths: Iterable[str]) -> tuple[FreezeFile, ...]:
    if not isinstance(repo_root, Path):
        raise ProtocolViolation("repo_root must be pathlib.Path")
    root = repo_root.resolve()
    names = tuple(_relative_path(path) for path in relative_paths)
    if len(names) != len(set(names)):
        raise ProtocolViolation("freeze inventory contains duplicate paths")
    rows: list[FreezeFile] = []
    for name in names:
        path = root.joinpath(*PurePosixPath(name).parts)
        if path.is_symlink() or not path.is_file():
            raise ProtocolViolation(f"freeze inventory path is not a regular file: {name}")
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ProtocolViolation("freeze path escapes repo root") from exc
        payload = path.read_bytes()
        rows.append(FreezeFile(name, len(payload), digest_bytes(payload)))
    rows.sort(key=lambda row: row.path.encode("utf-8"))
    return tuple(rows)


def _reject_secret_material(value: Any, path: str = "$") -> None:
    validate_json_like(value, path=path)
    if type(value) is dict:
        for key, item in value.items():
            normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
            normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized)
            normalized = normalized.strip("_").lower()
            if normalized in FORBIDDEN_SECRET_FIELDS:
                raise ProtocolViolation(f"{path}.{key}: raw seed/reveal material is forbidden")
            _reject_secret_material(item, f"{path}.{key}")
    elif type(value) is list:
        for index, item in enumerate(value):
            _reject_secret_material(item, f"{path}[{index}]")


def build_freeze_manifest(
    *,
    benchmark_id: str,
    status: FreezeStatus,
    files: tuple[FreezeFile, ...],
    source_revision: str,
    created_at: str,
    prefreeze_blockers: tuple[str, ...],
    required_paths: tuple[str, ...],
    seed_commitment_digest: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _name(benchmark_id, "benchmark_id")
    if type(status) is not FreezeStatus:
        raise ProtocolViolation("status must be FreezeStatus")
    _name(source_revision, "source_revision")
    _name(created_at, "created_at")
    if type(files) is not tuple or any(type(row) is not FreezeFile for row in files):
        raise ProtocolViolation("files must be a tuple of FreezeFile")
    if tuple(sorted(files, key=lambda row: row.path.encode("utf-8"))) != files:
        raise ProtocolViolation("freeze files must be in canonical path order")
    if type(prefreeze_blockers) is not tuple or any(
        type(item) is not str or not item for item in prefreeze_blockers
    ):
        raise ProtocolViolation("prefreeze_blockers must be canonical strings")
    required = tuple(_relative_path(path) for path in required_paths)
    if len(required) != len(set(required)):
        raise ProtocolViolation("required_paths contains duplicates")
    present = {row.path for row in files}
    missing = sorted(set(required) - present)
    if status is FreezeStatus.FROZEN_V1 and (prefreeze_blockers or missing):
        raise ProtocolViolation(
            f"cannot freeze with blockers={list(prefreeze_blockers)!r}, missing={missing!r}"
        )
    if seed_commitment_digest is not None:
        _digest(seed_commitment_digest, "seed_commitment_digest")
    extra = metadata or {}
    if type(extra) is not dict:
        raise ProtocolViolation("freeze metadata must be an exact dict")
    _reject_secret_material(extra, "$.metadata")
    manifest = {
        "protocol": MANIFEST_PROTOCOL,
        "benchmark_id": benchmark_id,
        "benchmark_status": status.value,
        "source_revision": source_revision,
        "created_at": created_at,
        "prefreeze_blockers": list(prefreeze_blockers),
        "required_paths": sorted(required, key=lambda value: value.encode("utf-8")),
        "missing_required_paths": missing,
        "seed_commitment_digest": seed_commitment_digest,
        "files": [row.to_wire() for row in files],
        "metadata": extra,
    }
    _reject_secret_material(manifest)
    return manifest


def _exclusive_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_freeze_manifest(directory: Path, manifest: dict[str, Any]) -> tuple[Path, Path]:
    if not isinstance(directory, Path):
        raise ProtocolViolation("freeze directory must be pathlib.Path")
    if type(manifest) is not dict or manifest.get("protocol") != MANIFEST_PROTOCOL:
        raise ProtocolViolation("not a UCM freeze manifest")
    _reject_secret_material(manifest)
    payload = canonical_json_bytes(manifest)
    target = directory / "FREEZE_MANIFEST.json"
    sidecar = directory / "FREEZE_MANIFEST.json.sha256"
    if target.exists() or sidecar.exists():
        raise FileExistsError("freeze manifest or sidecar already exists")
    _exclusive_write(target, payload)
    try:
        _exclusive_write(
            sidecar,
            (digest_bytes(payload) + "  FREEZE_MANIFEST.json\n").encode("ascii"),
        )
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target, sidecar


@dataclass(frozen=True, slots=True)
class FreezeVerification:
    manifest_digest: str
    file_count: int
    drifted_paths: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.drifted_paths


def verify_freeze_manifest(repo_root: Path, manifest_path: Path) -> FreezeVerification:
    payload = manifest_path.read_bytes()
    sidecar_path = manifest_path.with_name(manifest_path.name + ".sha256")
    expected_sidecar = (digest_bytes(payload) + f"  {manifest_path.name}\n").encode("ascii")
    if not sidecar_path.is_file() or sidecar_path.read_bytes() != expected_sidecar:
        raise ProtocolViolation("freeze manifest sidecar mismatch")
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("freeze manifest is not JSON") from exc
    if canonical_json_bytes(manifest) != payload or manifest.get("protocol") != MANIFEST_PROTOCOL:
        raise ProtocolViolation("freeze manifest is not canonical or has wrong protocol")
    _reject_secret_material(manifest)
    rows = manifest.get("files")
    if type(rows) is not list:
        raise ProtocolViolation("freeze manifest files are missing")
    drift: list[str] = []
    root = repo_root.resolve()
    for item in rows:
        if type(item) is not dict:
            raise ProtocolViolation("freeze file row is not an object")
        name = _relative_path(item.get("path"))
        path = root.joinpath(*PurePosixPath(name).parts)
        if path.is_symlink() or not path.is_file():
            drift.append(name)
            continue
        file_payload = path.read_bytes()
        if item.get("bytes") != len(file_payload) or item.get("sha256") != digest_bytes(file_payload):
            drift.append(name)
    return FreezeVerification(digest_bytes(payload), len(rows), tuple(sorted(drift)))


def write_seed_commit(
    path: Path,
    *,
    benchmark_freeze_digest: str,
    commitment: str,
    draw_program_digest: str,
    committed_at: str,
) -> Path:
    for value, label in (
        (benchmark_freeze_digest, "benchmark_freeze_digest"),
        (commitment, "commitment"),
        (draw_program_digest, "draw_program_digest"),
    ):
        _digest(value, label)
    artifact = {
        "protocol": COMMIT_PROTOCOL,
        "benchmark_freeze_digest": benchmark_freeze_digest,
        "commitment": commitment,
        "draw_program_digest": draw_program_digest,
        "committed_at": _name(committed_at, "committed_at"),
    }
    _exclusive_write(path, canonical_json_bytes(artifact))
    return path


def write_seed_reveal(
    path: Path,
    *,
    commit_path: Path,
    seed: bytes,
    nonce: bytes,
    revealed_at: str,
) -> Path:
    commit_payload = commit_path.read_bytes()
    try:
        commit = json.loads(commit_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("seed commit artifact is invalid") from exc
    if canonical_json_bytes(commit) != commit_payload or commit.get("protocol") != COMMIT_PROTOCOL:
        raise ProtocolViolation("seed commit artifact is noncanonical or wrong protocol")
    commitment = commit.get("commitment")
    if not verify_seed_commitment(commitment, seed, nonce):
        raise ProtocolViolation("seed and nonce do not match commitment")
    artifact = {
        "protocol": REVEAL_PROTOCOL,
        "commit_artifact_digest": digest_bytes(commit_payload),
        "commitment": commitment,
        "seed_hex": seed.hex(),
        "nonce_hex": nonce.hex(),
        "revealed_at": _name(revealed_at, "revealed_at"),
    }
    _exclusive_write(path, canonical_json_bytes(artifact))
    return path
