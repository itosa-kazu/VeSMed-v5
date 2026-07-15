"""Append-only benchmark freeze manifests and commit/reveal artifacts.

This module deliberately separates two very different claims:

* a ``PRE-FREEZE`` manifest can prove the integrity of the bytes it inventories;
* a ``FROZEN-v1`` manifest additionally needs a code-owned issuer receipt.

The latter issuer is intentionally disabled until the canonical required-path
inventory and all sixteen collector contracts are sealed.  In particular,
caller-created ``PASS`` rows, an empty/one-file inventory, or a recomputed
sidecar can never turn a pre-freeze integrity check into freeze authorization.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, NoReturn

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

# These are code-owned state blockers, not caller assertions.  They are added
# to every PRE-FREEZE manifest and make the disabled issuer state explicit in
# the persisted artifact.  Removing either blocker requires a future code
# change that introduces the canonical inventory and collector-backed issuer;
# accepting caller evidence here would recreate the self-signing vulnerability.
OFFICIAL_FREEZE_ISSUER_BLOCKERS = (
    "UCM-FREEZE-I001:official-freeze-issuer-disabled",
    "UCM-FREEZE-I002:canonical-required-path-and-collector-authority-unsealed",
)
EMPTY_REQUIRED_PATHS_BLOCKER = "UCM-FREEZE-I003:required-path-inventory-empty"
MISSING_REQUIRED_PATHS_BLOCKER = "UCM-FREEZE-I004:required-paths-missing"

_MANIFEST_KEYS = frozenset(
    {
        "protocol",
        "benchmark_id",
        "benchmark_status",
        "source_revision",
        "created_at",
        "prefreeze_blockers",
        "required_paths",
        "missing_required_paths",
        "seed_commitment_digest",
        "freeze_authorization_digest",
        "files",
        "metadata",
    }
)
_FREEZE_FILE_KEYS = frozenset({"path", "bytes", "sha256"})


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
    if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
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
        self._disabled()

    @staticmethod
    def _disabled() -> NoReturn:
        """Reject construction and serialization of public authority DTOs."""

        raise ProtocolViolation(
            "official FreezeAuthorization issuer is disabled; blockers="
            f"{list(OFFICIAL_FREEZE_ISSUER_BLOCKERS)!r}"
        )

    @property
    def required_paths_digest(self) -> str:
        self._disabled()

    def to_wire(self) -> dict[str, Any]:
        self._disabled()

    @property
    def digest(self) -> str:
        self._disabled()


def authorize_freeze(
    *,
    benchmark_id: str,
    scope_digest: str,
    source_revision: str,
    required_paths: Iterable[str],
    evidence: Iterable[FreezeAxisEvidence],
) -> FreezeAuthorization:
    """Fail closed until the code-owned freeze issuer is implemented.

    A generic assembler cannot authenticate the provenance of caller-created
    :class:`FreezeAxisEvidence` objects.  Even sixteen syntactically valid PASS
    rows are therefore evidence *data*, not authority.  A future issuer must
    consume the sealed collectors directly and own the exact required-path
    inventory; it must not relax this function into a public signing oracle.
    """

    # Do not iterate caller-provided iterables before failing: their iteration
    # is not part of the trusted evidence boundary and may execute arbitrary
    # code.  Touch the scalar values only to make the intentionally unused API
    # parameters explicit for type checkers/readers.
    del benchmark_id, scope_digest, source_revision, required_paths, evidence
    raise ProtocolViolation(
        "official FreezeAuthorization issuer is disabled; blockers="
        f"{list(OFFICIAL_FREEZE_ISSUER_BLOCKERS)!r}"
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
    if status is FreezeStatus.FROZEN_V1:
        raise ProtocolViolation(
            "FROZEN-v1 issuance is disabled; only PRE-FREEZE manifests may be "
            f"assembled; blockers={list(OFFICIAL_FREEZE_ISSUER_BLOCKERS)!r}"
        )
    _name(source_revision, "source_revision")
    _name(created_at, "created_at")
    if type(files) is not tuple or any(type(row) is not FreezeFile for row in files):
        raise ProtocolViolation("files must be a tuple of FreezeFile")
    # Frozen dataclasses are not an authority boundary (object.__setattr__ can
    # mutate them), so re-run every field validator at assembly time.
    for row in files:
        FreezeFile(path=row.path, bytes=row.bytes, sha256=row.sha256)
    if tuple(sorted(files, key=lambda row: row.path.encode("utf-8"))) != files:
        raise ProtocolViolation("freeze files must be in canonical path order")
    file_paths = tuple(row.path for row in files)
    if len(file_paths) != len(set(file_paths)):
        raise ProtocolViolation("freeze files contain duplicate paths")
    if type(prefreeze_blockers) is not tuple or any(
        type(item) is not str or not item or item.strip() != item
        for item in prefreeze_blockers
    ):
        raise ProtocolViolation("prefreeze_blockers must be canonical strings")
    if len(prefreeze_blockers) != len(set(prefreeze_blockers)):
        raise ProtocolViolation("prefreeze_blockers contains duplicates")
    if type(required_paths) is not tuple:
        raise ProtocolViolation("required_paths must be an exact tuple")
    required = tuple(_relative_path(path) for path in required_paths)
    if len(required) != len(set(required)):
        raise ProtocolViolation("required_paths contains duplicates")
    present = {row.path for row in files}
    required_set = set(required)
    extra_files = sorted(present - required_set, key=lambda value: value.encode("utf-8"))
    if extra_files:
        raise ProtocolViolation(
            f"freeze inventory contains paths outside required_paths: {extra_files!r}"
        )
    missing = sorted(required_set - present, key=lambda value: value.encode("utf-8"))
    if freeze_authorization is not None:
        raise ProtocolViolation("PRE-FREEZE manifest must not carry freeze authorization")
    if seed_commitment_digest is not None:
        _digest(seed_commitment_digest, "seed_commitment_digest")
    raw_extra = {} if metadata is None else metadata
    if type(raw_extra) is not dict:
        raise ProtocolViolation("freeze metadata must be an exact dict")
    extra = dict(raw_extra)
    if "freeze_authorization" in extra:
        raise ProtocolViolation("PRE-FREEZE metadata cannot carry freeze authorization")
    _reject_secret_material(extra, "$.metadata")

    effective_blockers = set(prefreeze_blockers)
    effective_blockers.update(OFFICIAL_FREEZE_ISSUER_BLOCKERS)
    if not required:
        effective_blockers.add(EMPTY_REQUIRED_PATHS_BLOCKER)
    if missing:
        effective_blockers.add(MISSING_REQUIRED_PATHS_BLOCKER)
    ordered_blockers = sorted(
        effective_blockers,
        key=lambda value: value.encode("utf-8"),
    )
    ordered_required = sorted(required, key=lambda value: value.encode("utf-8"))
    manifest = {
        "protocol": MANIFEST_PROTOCOL,
        "benchmark_id": benchmark_id,
        "benchmark_status": status.value,
        "source_revision": source_revision,
        "created_at": created_at,
        "prefreeze_blockers": ordered_blockers,
        "required_paths": ordered_required,
        "missing_required_paths": missing,
        "seed_commitment_digest": seed_commitment_digest,
        "freeze_authorization_digest": None,
        "files": [row.to_wire() for row in files],
        "metadata": extra,
    }
    _reject_secret_material(manifest)
    _validate_manifest_schema(manifest)
    return manifest


def _validate_manifest_schema(manifest: dict[str, Any]) -> tuple[FreezeFile, ...]:
    """Revalidate a persisted PRE-FREEZE manifest as closed inert data.

    This function never upgrades integrity to authority.  It deliberately
    rejects every FROZEN-v1 wire object while the official issuer is disabled.
    """

    if type(manifest) is not dict or set(manifest) != _MANIFEST_KEYS:
        raise ProtocolViolation("freeze manifest top-level schema is not closed")
    if manifest["protocol"] != MANIFEST_PROTOCOL:
        raise ProtocolViolation("not a UCM freeze manifest")
    _name(manifest["benchmark_id"], "benchmark_id")
    _name(manifest["source_revision"], "source_revision")
    _name(manifest["created_at"], "created_at")

    raw_status = manifest["benchmark_status"]
    if raw_status == FreezeStatus.FROZEN_V1.value:
        raise ProtocolViolation(
            "FROZEN-v1 manifest is not authorized: official freeze issuer is disabled"
        )
    if raw_status != FreezeStatus.PRE_FREEZE.value:
        raise ProtocolViolation("freeze manifest has an unknown benchmark_status")

    raw_blockers = manifest["prefreeze_blockers"]
    if type(raw_blockers) is not list or any(
        type(item) is not str or not item or item.strip() != item
        for item in raw_blockers
    ):
        raise ProtocolViolation("prefreeze_blockers must be a list of canonical strings")
    canonical_blockers = sorted(
        raw_blockers,
        key=lambda value: value.encode("utf-8"),
    )
    if raw_blockers != canonical_blockers or len(raw_blockers) != len(set(raw_blockers)):
        raise ProtocolViolation("prefreeze_blockers must be unique and canonical")
    absent_authority_blockers = sorted(
        set(OFFICIAL_FREEZE_ISSUER_BLOCKERS) - set(raw_blockers)
    )
    if absent_authority_blockers:
        raise ProtocolViolation(
            "PRE-FREEZE manifest omits code-owned issuer blockers: "
            f"{absent_authority_blockers!r}"
        )

    raw_required = manifest["required_paths"]
    if type(raw_required) is not list:
        raise ProtocolViolation("required_paths must be a canonical list")
    required = [_relative_path(path) for path in raw_required]
    if required != sorted(required, key=lambda value: value.encode("utf-8")) or len(
        required
    ) != len(set(required)):
        raise ProtocolViolation("required_paths must be unique and canonical")

    raw_files = manifest["files"]
    if type(raw_files) is not list:
        raise ProtocolViolation("freeze manifest files must be a canonical list")
    rows: list[FreezeFile] = []
    for item in raw_files:
        if type(item) is not dict or set(item) != _FREEZE_FILE_KEYS:
            raise ProtocolViolation("freeze file row schema is not closed")
        rows.append(
            FreezeFile(
                path=item["path"],
                bytes=item["bytes"],
                sha256=item["sha256"],
            )
        )
    row_paths = [row.path for row in rows]
    if row_paths != sorted(row_paths, key=lambda value: value.encode("utf-8")) or len(
        row_paths
    ) != len(set(row_paths)):
        raise ProtocolViolation("freeze files must be unique and canonical")
    extra_files = sorted(
        set(row_paths) - set(required),
        key=lambda value: value.encode("utf-8"),
    )
    if extra_files:
        raise ProtocolViolation(
            f"freeze inventory contains paths outside required_paths: {extra_files!r}"
        )

    expected_missing = sorted(
        set(required) - set(row_paths),
        key=lambda value: value.encode("utf-8"),
    )
    raw_missing = manifest["missing_required_paths"]
    if type(raw_missing) is not list:
        raise ProtocolViolation("missing_required_paths must be a canonical list")
    parsed_missing = [_relative_path(path) for path in raw_missing]
    if parsed_missing != expected_missing:
        raise ProtocolViolation(
            "missing_required_paths does not equal required_paths minus inventory"
        )
    blocker_set = set(raw_blockers)
    if not required and EMPTY_REQUIRED_PATHS_BLOCKER not in blocker_set:
        raise ProtocolViolation("empty required_paths lacks its code-owned blocker")
    if required and EMPTY_REQUIRED_PATHS_BLOCKER in blocker_set:
        raise ProtocolViolation("non-empty required_paths carries the empty-inventory blocker")
    if expected_missing and MISSING_REQUIRED_PATHS_BLOCKER not in blocker_set:
        raise ProtocolViolation("missing required paths lack their code-owned blocker")
    if not expected_missing and MISSING_REQUIRED_PATHS_BLOCKER in blocker_set:
        raise ProtocolViolation("complete inventory carries the missing-path blocker")

    seed_digest = manifest["seed_commitment_digest"]
    if seed_digest is not None:
        _digest(seed_digest, "seed_commitment_digest")
    if manifest["freeze_authorization_digest"] is not None:
        raise ProtocolViolation("PRE-FREEZE manifest carries a freeze authorization digest")
    metadata = manifest["metadata"]
    if type(metadata) is not dict:
        raise ProtocolViolation("freeze manifest metadata must be an exact dict")
    if "freeze_authorization" in metadata:
        raise ProtocolViolation("PRE-FREEZE manifest carries freeze authorization metadata")
    _reject_secret_material(manifest)
    return tuple(rows)


def _exclusive_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_freeze_manifest(directory: Path, manifest: dict[str, Any]) -> tuple[Path, Path]:
    if not isinstance(directory, Path):
        raise ProtocolViolation("freeze directory must be pathlib.Path")
    _validate_manifest_schema(manifest)
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
    declared_status: FreezeStatus
    missing_required_paths: tuple[str, ...]
    authorization_blockers: tuple[str, ...]

    @property
    def prefreeze_integrity_ok(self) -> bool:
        """Whether the PRE-FREEZE manifest matches the inspected file bytes."""

        return not self.drifted_paths

    @property
    def integrity_ok(self) -> bool:
        """Compatibility alias; this remains PRE-FREEZE-only integrity."""

        return self.prefreeze_integrity_ok

    @property
    def authorized_frozen(self) -> bool:
        """Whether a code-owned issuer authenticated a FROZEN-v1 manifest.

        The issuer is currently disabled, so a successfully parsed manifest is
        necessarily PRE-FREEZE and this property is necessarily false.
        """

        return False

    @property
    def ok(self) -> bool:
        """Freeze-grade verification, never mere PRE-FREEZE byte integrity."""

        return self.prefreeze_integrity_ok and self.authorized_frozen


def verify_freeze_manifest(repo_root: Path, manifest_path: Path) -> FreezeVerification:
    if not isinstance(repo_root, Path) or not isinstance(manifest_path, Path):
        raise ProtocolViolation("repo_root and manifest_path must be pathlib.Path")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ProtocolViolation("freeze manifest path is not a regular file")
    payload = manifest_path.read_bytes()
    sidecar_path = manifest_path.with_name(manifest_path.name + ".sha256")
    expected_sidecar = (digest_bytes(payload) + f"  {manifest_path.name}\n").encode("ascii")
    if (
        sidecar_path.is_symlink()
        or not sidecar_path.is_file()
        or sidecar_path.read_bytes() != expected_sidecar
    ):
        raise ProtocolViolation("freeze manifest sidecar mismatch")
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("freeze manifest is not JSON") from exc
    if canonical_json_bytes(manifest) != payload or manifest.get("protocol") != MANIFEST_PROTOCOL:
        raise ProtocolViolation("freeze manifest is not canonical or has wrong protocol")
    typed_rows = _validate_manifest_schema(manifest)
    drift: list[str] = []
    root = repo_root.resolve()
    for row in typed_rows:
        name = row.path
        path = root.joinpath(*PurePosixPath(name).parts)
        if path.is_symlink() or not path.is_file():
            drift.append(name)
            continue
        try:
            path.resolve().relative_to(root)
        except ValueError:
            drift.append(name)
            continue
        file_payload = path.read_bytes()
        if row.bytes != len(file_payload) or row.sha256 != digest_bytes(file_payload):
            drift.append(name)
    return FreezeVerification(
        manifest_digest=digest_bytes(payload),
        file_count=len(typed_rows),
        drifted_paths=tuple(sorted(drift, key=lambda value: value.encode("utf-8"))),
        declared_status=FreezeStatus.PRE_FREEZE,
        missing_required_paths=tuple(manifest["missing_required_paths"]),
        authorization_blockers=tuple(manifest["prefreeze_blockers"]),
    )


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
