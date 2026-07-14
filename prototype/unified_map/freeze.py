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
    digest_json,
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

AUTHORIZATION_PROTOCOL = "ucm-freeze-authorization/1"
REQUIRED_FREEZE_EVIDENCE_AXES = (
    "semantic_scope",
    "world_generators",
    "oracle_reference",
    "catalog_schemas",
    "projection_boundary",
    "split_isolation",
    "seed_protocol",
    "expected_cells",
    "probe_thresholds",
    "metrics_weights",
    "mutation_matrix",
    "candidate_protocol",
    "baseline_budgets",
    "replay_entrypoints",
    "runtime_lock",
    "limitations_registry",
)


class FreezeStatus(str, Enum):
    PRE_FREEZE = "PRE-FREEZE"
    FROZEN_V1 = "FROZEN-v1"


class FreezeEvidenceStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"


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


@dataclass(frozen=True, slots=True)
class FreezeAxisEvidence:
    axis: str
    status: FreezeEvidenceStatus
    artifact_digest: str
    detail: str

    def __post_init__(self) -> None:
        _name(self.axis, "freeze evidence axis")
        if self.axis not in REQUIRED_FREEZE_EVIDENCE_AXES:
            raise ProtocolViolation("unknown freeze evidence axis")
        if type(self.status) is not FreezeEvidenceStatus:
            raise ProtocolViolation("freeze evidence status must be typed")
        _digest(self.artifact_digest, "freeze evidence artifact_digest")
        _name(self.detail, "freeze evidence detail")

    def to_wire(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "status": self.status.value,
            "artifact_digest": self.artifact_digest,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class FreezeAuthorization:
    benchmark_id: str
    scope_digest: str
    source_revision: str
    required_paths: tuple[str, ...]
    evidence: tuple[FreezeAxisEvidence, ...]

    def __post_init__(self) -> None:
        _name(self.benchmark_id, "authorization benchmark_id")
        _digest(self.scope_digest, "authorization scope_digest")
        _name(self.source_revision, "authorization source_revision")
        canonical_paths = tuple(
            sorted(
                (_relative_path(path) for path in self.required_paths),
                key=lambda value: value.encode("utf-8"),
            )
        )
        if canonical_paths != self.required_paths or len(canonical_paths) != len(
            set(canonical_paths)
        ):
            raise ProtocolViolation(
                "authorization required_paths must be unique and canonically sorted"
            )
        if type(self.evidence) is not tuple or any(
            type(item) is not FreezeAxisEvidence for item in self.evidence
        ):
            raise ProtocolViolation("authorization evidence must be typed")
        axes = tuple(item.axis for item in self.evidence)
        if axes != REQUIRED_FREEZE_EVIDENCE_AXES:
            raise ProtocolViolation(
                "authorization evidence must cover every frozen axis in canonical order"
            )
        not_passed = [item.axis for item in self.evidence if item.status is not FreezeEvidenceStatus.PASS]
        if not_passed:
            raise ProtocolViolation(
                f"cannot authorize freeze with non-PASS axes: {not_passed!r}"
            )

    @property
    def required_paths_digest(self) -> str:
        return digest_json(
            {
                "protocol": "ucm-freeze-required-paths/1",
                "paths": list(self.required_paths),
            }
        )

    def to_wire(self) -> dict[str, Any]:
        body = {
            "protocol": AUTHORIZATION_PROTOCOL,
            "benchmark_id": self.benchmark_id,
            "scope_digest": self.scope_digest,
            "source_revision": self.source_revision,
            "required_paths_digest": self.required_paths_digest,
            "evidence": [item.to_wire() for item in self.evidence],
        }
        body["authorization_digest"] = digest_json(body)
        return body

    @property
    def digest(self) -> str:
        return self.to_wire()["authorization_digest"]


def authorize_freeze(
    *,
    benchmark_id: str,
    scope_digest: str,
    source_revision: str,
    required_paths: Iterable[str],
    evidence: Iterable[FreezeAxisEvidence],
) -> FreezeAuthorization:
    """Issue a value-bound receipt only for an exact all-PASS evidence vector.

    This is an assembly guard, not a substitute for the evidence producers.
    Each axis digest must refer to a separately persisted, inventoried artifact;
    the final manifest binds this receipt and those file bytes together.
    """

    paths = tuple(
        sorted(
            (_relative_path(path) for path in required_paths),
            key=lambda value: value.encode("utf-8"),
        )
    )
    rows_by_axis: dict[str, FreezeAxisEvidence] = {}
    for row in evidence:
        if type(row) is not FreezeAxisEvidence:
            raise ProtocolViolation("freeze evidence contains an untyped row")
        if row.axis in rows_by_axis:
            raise ProtocolViolation("duplicate freeze evidence axis")
        rows_by_axis[row.axis] = row
    ordered = tuple(
        rows_by_axis[axis]
        for axis in REQUIRED_FREEZE_EVIDENCE_AXES
        if axis in rows_by_axis
    )
    return FreezeAuthorization(
        benchmark_id=benchmark_id,
        scope_digest=scope_digest,
        source_revision=source_revision,
        required_paths=paths,
        evidence=ordered,
    )


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
    freeze_authorization: FreezeAuthorization | None = None,
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
    if status is FreezeStatus.FROZEN_V1:
        if prefreeze_blockers or missing:
            raise ProtocolViolation(
                f"cannot freeze with blockers={list(prefreeze_blockers)!r}, missing={missing!r}"
            )
        if type(freeze_authorization) is not FreezeAuthorization:
            raise ProtocolViolation(
                "cannot freeze without an exact all-PASS FreezeAuthorization"
            )
        if (
            freeze_authorization.benchmark_id != benchmark_id
            or freeze_authorization.source_revision != source_revision
            or freeze_authorization.required_paths
            != tuple(sorted(required, key=lambda value: value.encode("utf-8")))
        ):
            raise ProtocolViolation(
                "freeze authorization does not match benchmark/revision/required paths"
            )
        inventoried_digests = {row.sha256 for row in files}
        unbound_axes = [
            row.axis
            for row in freeze_authorization.evidence
            if row.artifact_digest not in inventoried_digests
        ]
        if unbound_axes:
            raise ProtocolViolation(
                f"freeze evidence digests are not in file inventory: {unbound_axes!r}"
            )
    elif freeze_authorization is not None:
        raise ProtocolViolation("PRE-FREEZE manifest must not carry freeze authorization")
    if seed_commitment_digest is not None:
        _digest(seed_commitment_digest, "seed_commitment_digest")
    raw_extra = metadata or {}
    if type(raw_extra) is not dict:
        raise ProtocolViolation("freeze metadata must be an exact dict")
    extra = dict(raw_extra)
    if status is FreezeStatus.FROZEN_V1:
        assert freeze_authorization is not None
        if "freeze_authorization" in extra:
            raise ProtocolViolation("freeze authorization metadata is runner-owned")
        extra["freeze_authorization"] = freeze_authorization.to_wire()
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
        "freeze_authorization_digest": (
            freeze_authorization.digest if freeze_authorization is not None else None
        ),
        "files": [row.to_wire() for row in files],
        "metadata": extra,
    }
    _reject_secret_material(manifest)
    return manifest


def _validate_manifest_freeze_authorization(manifest: dict[str, Any]) -> None:
    status = manifest.get("benchmark_status")
    if status not in {item.value for item in FreezeStatus}:
        raise ProtocolViolation("freeze manifest has an unknown benchmark_status")
    metadata = manifest.get("metadata")
    if type(metadata) is not dict:
        raise ProtocolViolation("freeze manifest metadata is missing")
    wire = metadata.get("freeze_authorization")
    top_digest = manifest.get("freeze_authorization_digest")
    if status == FreezeStatus.PRE_FREEZE.value:
        if wire is not None or top_digest is not None:
            raise ProtocolViolation("PRE-FREEZE manifest carries a freeze authorization")
        return
    if type(wire) is not dict or wire.get("protocol") != AUTHORIZATION_PROTOCOL:
        raise ProtocolViolation("FROZEN-v1 manifest lacks a typed freeze authorization")
    evidence_wire = wire.get("evidence")
    if type(evidence_wire) is not list:
        raise ProtocolViolation("freeze authorization evidence is missing")
    rows: list[FreezeAxisEvidence] = []
    try:
        for item in evidence_wire:
            if type(item) is not dict or set(item) != {
                "axis",
                "status",
                "artifact_digest",
                "detail",
            }:
                raise ProtocolViolation("freeze authorization evidence row is not closed")
            rows.append(
                FreezeAxisEvidence(
                    axis=item["axis"],
                    status=FreezeEvidenceStatus(item["status"]),
                    artifact_digest=item["artifact_digest"],
                    detail=item["detail"],
                )
            )
        receipt = authorize_freeze(
            benchmark_id=manifest.get("benchmark_id"),
            scope_digest=wire.get("scope_digest"),
            source_revision=manifest.get("source_revision"),
            required_paths=tuple(manifest.get("required_paths", ())),
            evidence=tuple(rows),
        )
    except ProtocolViolation:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolViolation("freeze authorization is malformed") from exc
    if receipt.to_wire() != wire or receipt.digest != top_digest:
        raise ProtocolViolation("freeze authorization digest or binding mismatch")
    file_rows = manifest.get("files")
    if type(file_rows) is not list or any(type(item) is not dict for item in file_rows):
        raise ProtocolViolation("freeze file inventory is missing")
    inventoried_digests = {item.get("sha256") for item in file_rows}
    unbound_axes = [
        row.axis
        for row in receipt.evidence
        if row.artifact_digest not in inventoried_digests
    ]
    if unbound_axes:
        raise ProtocolViolation(
            f"freeze evidence digests are not in file inventory: {unbound_axes!r}"
        )


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
    _validate_manifest_freeze_authorization(manifest)
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
    _validate_manifest_freeze_authorization(manifest)
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
