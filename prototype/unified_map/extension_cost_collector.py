"""Live exact-byte evidence collector for the PRE-FREEZE M11 metric.

The legacy W16/W17 extension receipts establish useful ordering and corpus
facts, but they deliberately do not carry enough evidence to mint an M11
observation.  This module validates the mechanical *collection* boundary
without pretending to close benchmark authority: it rehashes an exact locally
committed tree, derives byte-owned quantities, and remains typed INCOMPLETE
until independent Git, evaluator, and migration-execution authority exists.

The caller supplies only a previously retained root commitment.  Migration
flags, example counts, artifact sizes, source diffs, old-benchmark scores and
the hard-failure bit are not accepted as caller-authored metric values.
Missing future-grade evidence produces a typed INCOMPLETE result.  Malformed,
cross-spliced, stale or non-canonical evidence is a protocol violation.
"""

from __future__ import annotations

import difflib
import json
import math
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    domain_digest,
    validate_json_like,
)
from .metrics_m09_m11 import (
    CanonicalMetricEvidence,
    ExtensionCostObservation,
    ExtensionDisposition,
    M11_OBSERVATION_SCHEMA,
)


BENCHMARK_STATUS = "PRE-FREEZE"
EVIDENCE_QUALIFICATION = "runtime_only"
FREEZE_AUTHORITY_STATUS = "not_claimed"
ROOT_MANIFEST_SCHEMA = "ucm-m11-live-evidence-root/1"
TREE_MANIFEST_SCHEMA = "ucm-m11-live-artifact-tree/1"
SOURCE_MANIFEST_SCHEMA = "ucm-m11-live-git-source-tree/2"
SEAL_MANIFEST_SCHEMA = "ucm-m11-live-model-state-seal/2"
RETRAIN_MANIFEST_SCHEMA = "ucm-m11-live-retrain-example-set/2"
RETRAIN_EXAMPLE_SCHEMA = "ucm-m11-live-retrain-example/1"
BENCHMARK_EVIDENCE_SCHEMA = "ucm-m11-live-old-benchmark-evidence/2"
MIGRATION_RECEIPT_SCHEMA = "ucm-m11-live-migration-outcome/1"
COLLECTOR_RESULT_SCHEMA = "ucm-m11-live-collector-result/1"

ROOT_MANIFEST_PATH = "ROOT-MANIFEST.json"
PRIMARY_SEAL_PATH = "receipts/primary-seal.json"
REVEAL_RECEIPT_PATH = "receipts/reveal.json"
MATERIALIZATION_RECEIPT_PATH = "receipts/materialization.json"
MIGRATION_RECEIPT_PATH = "receipts/migration-outcome.json"

_ROOT_DOMAIN = b"UCM_M11_LIVE_EVIDENCE_ROOT_V1\0"
_TREE_DOMAIN = b"UCM_M11_LIVE_TREE_V1\0"
_OLD_BENCHMARK_TARGET_DOMAIN = b"UCM_M11_OLD_BENCHMARK_TARGET_V1\0"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

OLD_BENCHMARK_METRIC_ID = "old-proper-score"
OLD_BENCHMARK_SCORE_DIRECTION = "minimize"
OLD_BENCHMARK_TARGET_SCOPE_DIGEST = domain_digest(
    _OLD_BENCHMARK_TARGET_DOMAIN,
    [
        canonical_json_bytes(
            {
                "metric_id": OLD_BENCHMARK_METRIC_ID,
                "score_direction": OLD_BENCHMARK_SCORE_DIRECTION,
                "target_role": "code-owned-old-benchmark-retention-target",
            }
        )
    ],
)

_FIXED_COMPLETE_PATHS = frozenset(
    {
        PRIMARY_SEAL_PATH,
        REVEAL_RECEIPT_PATH,
        MATERIALIZATION_RECEIPT_PATH,
        MIGRATION_RECEIPT_PATH,
        "before/artifact-tree.json",
        "after/artifact-tree.json",
        "before/source-manifest.json",
        "after/source-manifest.json",
        "before/seal.json",
        "after/seal.json",
        "retrain/manifest.json",
        "old-benchmark/before.json",
        "old-benchmark/after.json",
    }
)
_LEGACY_RECEIPT_PATHS = frozenset(
    {PRIMARY_SEAL_PATH, REVEAL_RECEIPT_PATH, MATERIALIZATION_RECEIPT_PATH}
)
_DYNAMIC_PREFIXES = (
    "before/artifacts/",
    "after/artifacts/",
    "before/source/",
    "after/source/",
    "retrain/examples/",
)


class CollectionStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class CollectionBlocker:
    code: str
    evidence_role: str
    detail: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.code, "blocker code"),
            (self.evidence_role, "blocker evidence_role"),
            (self.detail, "blocker detail"),
        ):
            _name(value, label)

    def to_wire(self) -> dict[str, str]:
        return {
            "code": self.code,
            "evidence_role": self.evidence_role,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ExtensionCostCollection:
    status: CollectionStatus
    absolute_root: str
    root_commitment: str
    observation: ExtensionCostObservation | None
    blockers: tuple[CollectionBlocker, ...]
    source_evidence_digests: tuple[tuple[str, str], ...]

    @staticmethod
    def _reject_disabled_complete() -> None:
        raise ProtocolViolation(
            "official M11 COMPLETE issuer is disabled until code-owned "
            "migration and evaluator verifiers exist"
        )

    def __post_init__(self) -> None:
        if type(self.status) is not CollectionStatus:
            raise ProtocolViolation("collector status must be typed")
        if self.status is CollectionStatus.COMPLETE:
            # COMPLETE is an authority-bearing state.  The migration executor
            # and old-benchmark evaluator issuers are intentionally absent in
            # PRE-FREEZE, so even a syntactically valid caller-created
            # observation must not be able to mint it through this public DTO.
            self._reject_disabled_complete()
        _name(self.absolute_root, "collector absolute_root")
        _digest_value(self.root_commitment, "collector root_commitment")
        if type(self.blockers) is not tuple or any(
            type(item) is not CollectionBlocker for item in self.blockers
        ):
            raise ProtocolViolation("collector blockers must be typed")
        if type(self.source_evidence_digests) is not tuple:
            raise ProtocolViolation("collector source evidence must be a tuple")
        if self.observation is not None or not self.blockers:
            raise ProtocolViolation("incomplete collector result requires blockers")

    def to_wire(self) -> dict[str, Any]:
        # Frozen dataclasses are not an authority boundary: callers can use
        # object.__setattr__.  Recheck at serialization, not only construction.
        if self.status is CollectionStatus.COMPLETE:
            self._reject_disabled_complete()
        return {
            "schema_version": COLLECTOR_RESULT_SCHEMA,
            "benchmark_status": BENCHMARK_STATUS,
            "evidence_qualification": EVIDENCE_QUALIFICATION,
            "freeze_authority_status": FREEZE_AUTHORITY_STATUS,
            "benchmark_freeze_eligible": False,
            "local_tree_custody_only": True,
            "status": self.status.value,
            "absolute_root": self.absolute_root,
            "root_commitment": self.root_commitment,
            "observation": (
                None
                if self.observation is None
                else self.observation.evidence.reference_wire()
            ),
            "source_evidence": [
                {"path": path, "artifact_digest": digest}
                for path, digest in self.source_evidence_digests
            ],
            "blockers": [item.to_wire() for item in self.blockers],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class _Snapshot:
    root: Path
    files: tuple[tuple[str, bytes, tuple[int, int, int]], ...]

    @property
    def byte_map(self) -> dict[str, bytes]:
        return {path: content for path, content, _ in self.files}


@dataclass(frozen=True, slots=True)
class _Tree:
    stage: str
    root_path: str
    files: tuple[tuple[str, bytes], ...]
    tree_digest: str
    modes: tuple[tuple[str, str], ...] = ()

    @property
    def size_bytes(self) -> int:
        return sum(len(content) for _, content in self.files)

    @property
    def byte_map(self) -> dict[str, bytes]:
        return dict(self.files)

    @property
    def mode_map(self) -> dict[str, str]:
        return dict(self.modes)


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    if any(ord(character) < 0x20 for character in value):
        raise ProtocolViolation(f"{label} contains a control character")
    return value


def _digest_value(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a lowercase SHA-256 digest")
    return value


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ProtocolViolation(f"{label} must be an exact boolean")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProtocolViolation(f"{label} must be a non-negative exact integer")
    return value


def _finite_number(value: object, label: str) -> float:
    if type(value) not in {int, float}:
        raise ProtocolViolation(f"{label} must be an exact finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ProtocolViolation(f"{label} must be an exact finite number") from exc
    if not math.isfinite(result):
        raise ProtocolViolation(f"{label} must be an exact finite number")
    return result


def _relative(value: object, label: str) -> str:
    path = _name(value, label)
    if "\\" in path or ":" in path:
        raise ProtocolViolation(f"{label} must be a canonical POSIX relative path")
    parsed = PurePosixPath(path)
    if (
        parsed.is_absolute()
        or str(parsed) != path
        or path in {".", ".."}
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ProtocolViolation(f"{label} must be a canonical POSIX relative path")
    return path


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    actual = frozenset(value)
    if actual != expected:
        raise ProtocolViolation(
            f"{label} schema mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    return value


def _decode_canonical(content: bytes, label: str) -> dict[str, Any]:
    if type(content) is not bytes or not content:
        raise ProtocolViolation(f"{label} must contain exact non-empty bytes")
    try:
        value = json.loads(content.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} must be canonical UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must encode an exact object")
    validate_json_like(value, path=label)
    if canonical_json_bytes(value) != content:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    return value


def _is_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _scan(root: Path) -> _Snapshot:
    lexical = root.absolute()
    if not os.path.lexists(os.fspath(lexical)):
        raise ProtocolViolation("M11 evidence root does not exist")
    root_info = os.lstat(lexical)
    if (
        stat.S_ISLNK(root_info.st_mode)
        or _is_reparse(root_info)
        or not stat.S_ISDIR(root_info.st_mode)
    ):
        raise ProtocolViolation("M11 evidence root must be a plain directory")
    resolved = lexical.resolve(strict=True)
    rows: list[tuple[str, bytes, tuple[int, int, int]]] = []
    for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix().encode()):
        relative = path.relative_to(resolved).as_posix()
        _relative(relative, "live evidence path")
        info_before = os.lstat(path)
        if stat.S_ISLNK(info_before.st_mode) or _is_reparse(info_before):
            raise ProtocolViolation(
                f"live evidence entry {relative!r} is a link/reparse"
            )
        if stat.S_ISDIR(info_before.st_mode):
            continue
        if not stat.S_ISREG(info_before.st_mode):
            raise ProtocolViolation(f"live evidence entry {relative!r} is not regular")
        if getattr(info_before, "st_nlink", 1) != 1:
            raise ProtocolViolation(f"live evidence entry {relative!r} is hard-linked")
        content = path.read_bytes()
        info_after = os.lstat(path)
        identity_before = (
            int(getattr(info_before, "st_ino", 0)),
            int(info_before.st_size),
            int(info_before.st_mtime_ns),
        )
        identity_after = (
            int(getattr(info_after, "st_ino", 0)),
            int(info_after.st_size),
            int(info_after.st_mtime_ns),
        )
        if identity_before != identity_after or len(content) != info_after.st_size:
            raise ProtocolViolation(
                f"live evidence entry {relative!r} changed during read"
            )
        rows.append((relative, content, identity_after))
    return _Snapshot(resolved, tuple(rows))


def _root_commitment(manifest_bytes: bytes) -> str:
    return domain_digest(_ROOT_DOMAIN, [manifest_bytes])


def _verify_root(
    root: Path | str, expected_root_commitment: str
) -> tuple[_Snapshot, dict[str, bytes], str]:
    _digest_value(expected_root_commitment, "expected_root_commitment")
    snapshot = _scan(Path(root))
    files = snapshot.byte_map
    manifest_bytes = files.get(ROOT_MANIFEST_PATH)
    if manifest_bytes is None:
        raise ProtocolViolation("M11 evidence root lacks ROOT-MANIFEST.json")
    if _root_commitment(manifest_bytes) != expected_root_commitment:
        raise ProtocolViolation("M11 evidence root commitment mismatch")
    manifest = _exact_keys(
        _decode_canonical(manifest_bytes, ROOT_MANIFEST_PATH),
        frozenset({"schema_version", "absolute_root", "files", "manifest_digest"}),
        ROOT_MANIFEST_PATH,
    )
    if manifest["schema_version"] != ROOT_MANIFEST_SCHEMA:
        raise ProtocolViolation("M11 root manifest schema_version is invalid")
    if manifest["absolute_root"] != snapshot.root.as_posix():
        raise ProtocolViolation(
            "M11 root manifest absolute_root is stale or cross-spliced"
        )
    claimed_manifest_digest = _digest_value(
        manifest["manifest_digest"], "root manifest_digest"
    )
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_digest"
    }
    if digest_json(unsigned) != claimed_manifest_digest:
        raise ProtocolViolation("M11 root manifest self-digest mismatch")
    rows = manifest["files"]
    if type(rows) is not list or not rows:
        raise ProtocolViolation(
            "M11 root manifest files must be a non-empty exact list"
        )
    expected_rows: list[dict[str, Any]] = []
    for index, item in enumerate(rows):
        row = _exact_keys(
            item,
            frozenset({"path", "size_bytes", "digest"}),
            f"root manifest file {index}",
        )
        path = _relative(row["path"], f"root manifest file {index} path")
        if path == ROOT_MANIFEST_PATH:
            raise ProtocolViolation("root manifest cannot inventory itself")
        size = _nonnegative_int(row["size_bytes"], f"root manifest {path} size")
        digest = _digest_value(row["digest"], f"root manifest {path} digest")
        expected_rows.append({"path": path, "size_bytes": size, "digest": digest})
    sorted_rows = sorted(expected_rows, key=lambda row: row["path"].encode("utf-8"))
    if expected_rows != sorted_rows:
        raise ProtocolViolation("M11 root manifest file rows are not canonical-order")
    paths = [row["path"] for row in expected_rows]
    if len(paths) != len(set(paths)):
        raise ProtocolViolation("M11 root manifest contains duplicate paths")
    if set(files) != set(paths) | {ROOT_MANIFEST_PATH}:
        raise ProtocolViolation("M11 live root differs from exact root manifest")
    for row in expected_rows:
        content = files[row["path"]]
        if len(content) != row["size_bytes"] or digest_bytes(content) != row["digest"]:
            raise ProtocolViolation(f"M11 live bytes differ for {row['path']!r}")
        # Only code-owned evidence manifests and receipts are required to use
        # canonical JSON.  Files inside source/artifact trees are opaque exact
        # bytes; a normal pretty-printed package.json or model config must not
        # be reinterpreted as an evidence envelope.
        if row["path"] in _FIXED_COMPLETE_PATHS | _LEGACY_RECEIPT_PATHS:
            _decode_canonical(content, row["path"])
    allowed = _FIXED_COMPLETE_PATHS | _LEGACY_RECEIPT_PATHS
    for path in paths:
        if path not in allowed and not path.startswith(_DYNAMIC_PREFIXES):
            raise ProtocolViolation(
                f"M11 evidence path {path!r} has no code-owned role"
            )
    if _scan(snapshot.root).files != snapshot.files:
        raise ProtocolViolation("M11 evidence root changed during collection")
    return snapshot, files, claimed_manifest_digest


def _tree_digest(stage: str, root_path: str, rows: list[dict[str, Any]]) -> str:
    return domain_digest(
        _TREE_DOMAIN,
        [
            canonical_json_bytes(
                {
                    "protocol": TREE_MANIFEST_SCHEMA,
                    "stage": stage,
                    "root_path": root_path,
                    "files": rows,
                }
            )
        ],
    )


def _parse_tree(files: Mapping[str, bytes], *, stage: str, kind: str) -> _Tree:
    manifest_path = f"{stage}/{kind}-tree.json"
    root_path = f"{stage}/{kind}s"
    value = _exact_keys(
        _decode_canonical(files[manifest_path], manifest_path),
        frozenset({"schema_version", "stage", "root_path", "files", "tree_digest"}),
        manifest_path,
    )
    if value["schema_version"] != TREE_MANIFEST_SCHEMA or value["stage"] != stage:
        raise ProtocolViolation(f"{manifest_path} stage/schema mismatch")
    if value["root_path"] != root_path:
        raise ProtocolViolation(f"{manifest_path} root_path is cross-spliced")
    rows = value["files"]
    if type(rows) is not list or not rows:
        raise ProtocolViolation(f"{manifest_path} must describe a non-empty tree")
    normalized: list[dict[str, Any]] = []
    payloads: list[tuple[str, bytes]] = []
    for index, item in enumerate(rows):
        row = _exact_keys(
            item,
            frozenset({"path", "size_bytes", "digest"}),
            f"{manifest_path} file {index}",
        )
        relative = _relative(row["path"], f"{manifest_path} file path")
        live_path = f"{root_path}/{relative}"
        content = files.get(live_path)
        if content is None:
            raise ProtocolViolation(f"{manifest_path} references a missing live file")
        size = _nonnegative_int(row["size_bytes"], f"{live_path} size")
        digest = _digest_value(row["digest"], f"{live_path} digest")
        if size != len(content) or digest != digest_bytes(content):
            raise ProtocolViolation(f"{manifest_path} does not bind exact live bytes")
        normalized.append({"path": relative, "size_bytes": size, "digest": digest})
        payloads.append((relative, content))
    if normalized != sorted(normalized, key=lambda row: row["path"].encode("utf-8")):
        raise ProtocolViolation(f"{manifest_path} file rows are not canonical-order")
    if len({row["path"] for row in normalized}) != len(normalized):
        raise ProtocolViolation(f"{manifest_path} contains duplicate paths")
    live_paths = {path for path in files if path.startswith(root_path + "/")}
    if live_paths != {f"{root_path}/{row['path']}" for row in normalized}:
        raise ProtocolViolation(f"{manifest_path} does not close its exact subtree")
    expected_digest = _tree_digest(stage, root_path, normalized)
    if (
        _digest_value(value["tree_digest"], f"{manifest_path} tree_digest")
        != expected_digest
    ):
        raise ProtocolViolation(f"{manifest_path} tree_digest mismatch")
    return _Tree(stage, root_path, tuple(payloads), expected_digest)


def _parse_source_tree(
    files: Mapping[str, bytes], *, stage: str
) -> tuple[_Tree, dict[str, Any]]:
    path = f"{stage}/source-manifest.json"
    value = _exact_keys(
        _decode_canonical(files[path], path),
        frozenset(
            {
                "schema_version",
                "stage",
                "root_path",
                "git_commit",
                "git_dirty",
                "base_git_commit",
                "files",
                "tree_digest",
            }
        ),
        path,
    )
    if value["schema_version"] != SOURCE_MANIFEST_SCHEMA or value["stage"] != stage:
        raise ProtocolViolation(f"{path} stage/schema mismatch")
    root_path = f"{stage}/source"
    if value["root_path"] != root_path:
        raise ProtocolViolation(f"{path} root_path is cross-spliced")
    if (
        type(value["git_commit"]) is not str
        or _GIT_COMMIT.fullmatch(value["git_commit"]) is None
    ):
        raise ProtocolViolation(f"{path} git_commit is invalid")
    _bool(value["git_dirty"], f"{path} git_dirty")
    if value["base_git_commit"] is not None and (
        type(value["base_git_commit"]) is not str
        or _GIT_COMMIT.fullmatch(value["base_git_commit"]) is None
    ):
        raise ProtocolViolation(f"{path} base_git_commit is invalid")
    rows = value["files"]
    if type(rows) is not list or not rows:
        raise ProtocolViolation(f"{path} must describe a non-empty source tree")
    normalized: list[dict[str, Any]] = []
    payloads: list[tuple[str, bytes]] = []
    for index, item in enumerate(rows):
        row = _exact_keys(
            item,
            frozenset({"path", "git_mode", "size_bytes", "digest"}),
            f"{path} file {index}",
        )
        relative = _relative(row["path"], f"{path} file path")
        git_mode = _name(row["git_mode"], f"{path} file git_mode")
        if git_mode not in {"100644", "100755"}:
            raise ProtocolViolation(f"{path} file git_mode is not a regular Git blob")
        live_path = f"{root_path}/{relative}"
        content = files.get(live_path)
        if content is None:
            raise ProtocolViolation(f"{path} references a missing live source file")
        size = _nonnegative_int(row["size_bytes"], f"{live_path} size")
        digest = _digest_value(row["digest"], f"{live_path} digest")
        if size != len(content) or digest != digest_bytes(content):
            raise ProtocolViolation(f"{path} does not bind exact source bytes")
        normalized.append(
            {
                "path": relative,
                "git_mode": git_mode,
                "size_bytes": size,
                "digest": digest,
            }
        )
        payloads.append((relative, content))
    if normalized != sorted(normalized, key=lambda row: row["path"].encode("utf-8")):
        raise ProtocolViolation(f"{path} file rows are not canonical-order")
    if len({row["path"] for row in normalized}) != len(normalized):
        raise ProtocolViolation(f"{path} contains duplicate paths")
    live_paths = {item for item in files if item.startswith(root_path + "/")}
    if live_paths != {f"{root_path}/{row['path']}" for row in normalized}:
        raise ProtocolViolation(f"{path} does not close its exact source subtree")
    tree_digest = _tree_digest(stage, root_path, normalized)
    if _digest_value(value["tree_digest"], f"{path} tree_digest") != tree_digest:
        raise ProtocolViolation(f"{path} tree_digest mismatch")
    modes = tuple((row["path"], row["git_mode"]) for row in normalized)
    return _Tree(stage, root_path, tuple(payloads), tree_digest, modes), value


def _git_command(
    repository: Path, arguments: tuple[str, ...], *, label: str
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            (
                "git",
                "--no-replace-objects",
                "-c",
                "core.quotepath=false",
                *arguments,
            ),
            cwd=repository,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProtocolViolation(f"{label} live Git verification failed") from exc
    return result


def _git_text(result: subprocess.CompletedProcess[bytes], *, label: str) -> str:
    if result.returncode != 0:
        raise ProtocolViolation(f"{label} live Git command failed")
    try:
        return result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ProtocolViolation(f"{label} live Git output is not UTF-8") from exc


def _git_tree(
    repository: Path, commit: str, *, label: str
) -> dict[str, tuple[str, bytes]]:
    result = _git_command(
        repository,
        ("ls-tree", "-r", "-z", "--full-tree", commit),
        label=f"{label} ls-tree",
    )
    if result.returncode != 0:
        raise ProtocolViolation(f"{label} commit tree is unavailable")
    rows: dict[str, tuple[str, bytes]] = {}
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            metadata, raw_path = raw.split(b"\t", 1)
            mode_bytes, type_bytes, object_id = metadata.split(b" ", 2)
            mode = mode_bytes.decode("ascii", errors="strict")
            object_type = type_bytes.decode("ascii", errors="strict")
            path = raw_path.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProtocolViolation(f"{label} Git tree row is malformed") from exc
        _relative(path, f"{label} Git path")
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ProtocolViolation(f"{label} Git tree contains a non-regular blob")
        blob_result = _git_command(
            repository,
            ("cat-file", "blob", object_id.decode("ascii", errors="strict")),
            label=f"{label} blob",
        )
        if blob_result.returncode != 0:
            raise ProtocolViolation(f"{label} Git blob is unavailable")
        if path in rows:
            raise ProtocolViolation(f"{label} Git tree contains duplicate paths")
        rows[path] = (mode, blob_result.stdout)
    return rows


def _verify_live_git(
    repository: Path | str | None,
    *,
    before_tree: _Tree,
    before_manifest: Mapping[str, Any],
    after_tree: _Tree,
    after_manifest: Mapping[str, Any],
) -> CollectionBlocker | None:
    if repository is None:
        return CollectionBlocker(
            "UCM-METRIC-B005",
            "live_git_repository",
            "no live clean Git repository authority was supplied",
        )
    lexical = Path(repository).absolute()
    if not os.path.lexists(os.fspath(lexical)):
        raise ProtocolViolation("live Git repository does not exist")
    info = os.lstat(lexical)
    if (
        stat.S_ISLNK(info.st_mode)
        or _is_reparse(info)
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise ProtocolViolation("live Git repository must be a plain directory")
    resolved = lexical.resolve(strict=True)
    top_level = Path(
        _git_text(
            _git_command(
                resolved,
                ("rev-parse", "--show-toplevel"),
                label="Git repository root",
            ),
            label="Git repository root",
        )
    ).resolve(strict=True)
    if top_level != resolved:
        raise ProtocolViolation("live Git repository must name the exact worktree root")
    status = _git_command(
        resolved,
        ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
        label="Git clean status",
    )
    if status.returncode != 0 or status.stdout:
        raise ProtocolViolation("live Git repository is not clean")
    head = _git_text(
        _git_command(resolved, ("rev-parse", "HEAD"), label="Git HEAD"),
        label="Git HEAD",
    )
    if head != after_manifest["git_commit"]:
        raise ProtocolViolation("live Git HEAD does not equal the after commit")
    ancestor = _git_command(
        resolved,
        (
            "merge-base",
            "--is-ancestor",
            before_manifest["git_commit"],
            after_manifest["git_commit"],
        ),
        label="Git ancestry",
    )
    if ancestor.returncode != 0:
        raise ProtocolViolation("before Git commit is not an ancestor of after")

    for stage, tree, manifest in (
        ("before", before_tree, before_manifest),
        ("after", after_tree, after_manifest),
    ):
        live_tree = _git_tree(resolved, manifest["git_commit"], label=f"{stage} Git")
        retained_modes = {row["path"]: row["git_mode"] for row in manifest["files"]}
        retained_bytes = tree.byte_map
        if set(live_tree) != set(retained_bytes):
            raise ProtocolViolation(
                f"{stage} retained source is not the exact Git tree"
            )
        for path, (mode, content) in live_tree.items():
            if retained_modes[path] != mode or retained_bytes[path] != content:
                raise ProtocolViolation(
                    f"{stage} retained source differs from its live Git commit"
                )
    # Re-check the mutable worktree/ref boundary after all object reads.  The
    # object commands above disable replace refs, so this closes both ordinary
    # live mutation and caller-installed replacement-object splices.
    final_status = _git_command(
        resolved,
        ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
        label="final Git clean status",
    )
    if final_status.returncode != 0 or final_status.stdout:
        raise ProtocolViolation("live Git repository changed during verification")
    final_head = _git_text(
        _git_command(resolved, ("rev-parse", "HEAD"), label="final Git HEAD"),
        label="final Git HEAD",
    )
    if final_head != after_manifest["git_commit"]:
        raise ProtocolViolation("live Git HEAD changed during verification")
    return None


def _parse_seal(
    files: Mapping[str, bytes],
    *,
    stage: str,
    artifact_tree: _Tree,
    source_tree: _Tree,
) -> dict[str, Any]:
    path = f"{stage}/seal.json"
    value = _exact_keys(
        _decode_canonical(files[path], path),
        frozenset(
            {
                "schema_version",
                "stage",
                "artifact_tree_digest",
                "source_tree_digest",
                "model_artifact_path",
                "model_artifact_digest",
                "model_schema_path",
                "model_schema_digest",
                "state_schema_path",
                "state_schema_digest",
                "state_snapshot_path",
                "state_snapshot_digest",
            }
        ),
        path,
    )
    if value["schema_version"] != SEAL_MANIFEST_SCHEMA or value["stage"] != stage:
        raise ProtocolViolation(f"{path} stage/schema mismatch")
    if value["artifact_tree_digest"] != artifact_tree.tree_digest:
        raise ProtocolViolation(f"{path} artifact tree is cross-spliced")
    if value["source_tree_digest"] != source_tree.tree_digest:
        raise ProtocolViolation(f"{path} source tree is cross-spliced")
    blob_roles = (
        ("model_artifact_path", "model_artifact_digest", "model artifact"),
        ("model_schema_path", "model_schema_digest", "model schema"),
        ("state_schema_path", "state_schema_digest", "state schema"),
        ("state_snapshot_path", "state_snapshot_digest", "state snapshot"),
    )
    bound_paths: list[str] = []
    for path_field, digest_field, role in blob_roles:
        blob_path = _relative(value[path_field], f"{path} {role} path")
        bound_paths.append(blob_path)
        blob = artifact_tree.byte_map.get(blob_path)
        if blob is None:
            raise ProtocolViolation(f"{path} {role} is absent from sealed tree")
        claimed = _digest_value(value[digest_field], f"{path} {role} digest")
        if claimed != digest_bytes(blob):
            raise ProtocolViolation(f"{path} {role} digest does not bind live bytes")
    if len(set(bound_paths)) != len(bound_paths):
        raise ProtocolViolation(f"{path} sealed blob roles must use distinct paths")
    return value


def _parse_retrain(files: Mapping[str, bytes]) -> tuple[int, str]:
    path = "retrain/manifest.json"
    value = _exact_keys(
        _decode_canonical(files[path], path),
        frozenset({"schema_version", "root_path", "examples", "example_set_digest"}),
        path,
    )
    if (
        value["schema_version"] != RETRAIN_MANIFEST_SCHEMA
        or value["root_path"] != "retrain/examples"
    ):
        raise ProtocolViolation("retrain manifest schema/root mismatch")
    rows = value["examples"]
    if type(rows) is not list:
        raise ProtocolViolation("retrain examples must be an exact list")
    normalized: list[dict[str, Any]] = []
    example_identities: list[tuple[str, str]] = []
    for index, item in enumerate(rows):
        row = _exact_keys(
            item,
            frozenset({"case_id", "example_id", "path", "size_bytes", "digest"}),
            f"retrain example {index}",
        )
        case_id = _name(row["case_id"], "retrain case_id")
        example_id = _name(row["example_id"], "retrain example_id")
        relative = _relative(row["path"], "retrain example path")
        live_path = f"retrain/examples/{relative}"
        content = files.get(live_path)
        if content is None:
            raise ProtocolViolation("retrain manifest references a missing example")
        size = _nonnegative_int(row["size_bytes"], f"{live_path} size")
        digest = _digest_value(row["digest"], f"{live_path} digest")
        if size != len(content) or digest != digest_bytes(content):
            raise ProtocolViolation("retrain example manifest does not bind live bytes")
        example = _exact_keys(
            _decode_canonical(content, live_path),
            frozenset({"schema_version", "case_id", "example_id", "payload"}),
            live_path,
        )
        if example["schema_version"] != RETRAIN_EXAMPLE_SCHEMA:
            raise ProtocolViolation("retrain example schema_version is invalid")
        if example["case_id"] != case_id or example["example_id"] != example_id:
            raise ProtocolViolation("retrain example identity is cross-spliced")
        example_identities.append((case_id, example_id))
        normalized.append(
            {
                "case_id": case_id,
                "example_id": example_id,
                "path": relative,
                "size_bytes": size,
                "digest": digest,
            }
        )
    if normalized != sorted(
        normalized,
        key=lambda row: (
            row["case_id"].encode("utf-8"),
            row["example_id"].encode("utf-8"),
        ),
    ):
        raise ProtocolViolation("retrain examples are not canonical-order")
    if len(set(example_identities)) != len(example_identities):
        raise ProtocolViolation("retrain case/example identities must be unique")
    if len({row["path"] for row in normalized}) != len(normalized):
        raise ProtocolViolation("retrain example paths must be unique")
    live_paths = {item for item in files if item.startswith("retrain/examples/")}
    if live_paths != {f"retrain/examples/{row['path']}" for row in normalized}:
        raise ProtocolViolation("retrain manifest does not close its exact subtree")
    unsigned = {
        "protocol": RETRAIN_MANIFEST_SCHEMA,
        "root_path": "retrain/examples",
        "examples": normalized,
    }
    set_digest = digest_json(unsigned)
    if (
        _digest_value(value["example_set_digest"], "retrain example_set_digest")
        != set_digest
    ):
        raise ProtocolViolation("retrain example set digest mismatch")
    # The cost axis counts code-owned example identities, never manifest rows.
    return len(set(example_identities)), set_digest


def _parse_old_benchmark(
    files: Mapping[str, bytes],
    *,
    stage: str,
    source_tree: _Tree,
    artifact_tree: _Tree,
) -> tuple[dict[str, Any], tuple[str, ...], float]:
    path = f"old-benchmark/{stage}.json"
    value = _exact_keys(
        _decode_canonical(files[path], path),
        frozenset(
            {
                "schema_version",
                "stage",
                "benchmark_scope_digest",
                "metric_id",
                "candidate_source_tree_digest",
                "candidate_artifact_tree_digest",
                "rows",
            }
        ),
        path,
    )
    if value["schema_version"] != BENCHMARK_EVIDENCE_SCHEMA or value["stage"] != stage:
        raise ProtocolViolation(f"{path} stage/schema mismatch")
    if value["metric_id"] != OLD_BENCHMARK_METRIC_ID:
        raise ProtocolViolation(f"{path} metric_id is not a code-owned target")
    if value["benchmark_scope_digest"] != OLD_BENCHMARK_TARGET_SCOPE_DIGEST:
        raise ProtocolViolation(f"{path} benchmark target binding is invalid")
    if value["candidate_source_tree_digest"] != source_tree.tree_digest:
        raise ProtocolViolation(f"{path} source evidence is cross-spliced")
    if value["candidate_artifact_tree_digest"] != artifact_tree.tree_digest:
        raise ProtocolViolation(f"{path} artifact evidence is cross-spliced")
    rows = value["rows"]
    if type(rows) is not list or not rows:
        raise ProtocolViolation(f"{path} rows must be a non-empty exact list")
    ids: list[str] = []
    scores: list[float] = []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(rows):
        row = _exact_keys(
            item, frozenset({"example_id", "score"}), f"{path} row {index}"
        )
        example_id = _name(row["example_id"], f"{path} example_id")
        score = _finite_number(row["score"], f"{path} score")
        ids.append(example_id)
        scores.append(score)
        normalized.append({"example_id": example_id, "score": row["score"]})
    if normalized != sorted(
        normalized, key=lambda row: row["example_id"].encode("utf-8")
    ):
        raise ProtocolViolation(f"{path} rows are not canonical-order")
    if len(ids) != len(set(ids)):
        raise ProtocolViolation(f"{path} example ids must be unique")
    try:
        score = math.fsum(scores) / len(scores)
    except (OverflowError, ValueError) as exc:
        raise ProtocolViolation(f"{path} aggregate is non-finite") from exc
    if not math.isfinite(score):
        raise ProtocolViolation(f"{path} aggregate is non-finite")
    return (
        {**value, "score_direction": OLD_BENCHMARK_SCORE_DIRECTION},
        tuple(ids),
        score,
    )


def _parse_receipt_chain(
    files: Mapping[str, bytes],
) -> tuple[dict[str, Any], tuple[CollectionBlocker, ...]]:
    primary = _decode_canonical(files[PRIMARY_SEAL_PATH], PRIMARY_SEAL_PATH)
    reveal = _decode_canonical(files[REVEAL_RECEIPT_PATH], REVEAL_RECEIPT_PATH)
    materialization = _decode_canonical(
        files[MATERIALIZATION_RECEIPT_PATH], MATERIALIZATION_RECEIPT_PATH
    )
    if primary.get("schema_version") != "ucm-extension-primary-seal-result/1":
        raise ProtocolViolation("primary seal receipt schema_version is invalid")
    if reveal.get("schema_version") != "ucm-extension-reveal-receipt/1":
        raise ProtocolViolation("reveal receipt schema_version is invalid")
    if (
        materialization.get("schema_version")
        != "ucm-extension-materialization-result/1"
    ):
        raise ProtocolViolation("materialization receipt schema_version is invalid")
    world = _name(primary.get("world_slot"), "primary receipt world_slot")
    if world not in {"W16", "W17"}:
        raise ProtocolViolation("M11 receipt world must be W16 or W17")
    if reveal.get("world_slot") != world or materialization.get("world_slot") != world:
        raise ProtocolViolation("extension receipts cross-splice different worlds")
    record_root = _digest_value(
        primary.get("record_set_digest"), "primary record_set_digest"
    )
    binding_root = _digest_value(
        primary.get("binding_set_digest"), "primary binding_set_digest"
    )
    if (
        reveal.get("primary_record_set_digest") != record_root
        or materialization.get("primary_record_set_digest") != record_root
    ):
        raise ProtocolViolation("extension receipts cross-splice primary record roots")
    if (
        reveal.get("primary_binding_set_digest") != binding_root
        or materialization.get("primary_binding_set_digest") != binding_root
    ):
        raise ProtocolViolation("extension receipts cross-splice primary binding roots")
    extension_scope = _digest_value(
        reveal.get("extension_scope_digest"), "reveal extension_scope_digest"
    )
    extension_pack = _digest_value(
        reveal.get("extension_pack_digest"), "reveal extension_pack_digest"
    )
    if (
        materialization.get("extension_scope_digest") != extension_scope
        or materialization.get("extension_pack_digest") != extension_pack
    ):
        raise ProtocolViolation("extension receipts cross-splice extension pack/scope")
    blockers: list[CollectionBlocker] = []
    if primary.get("freeze_grade_evidence") is not False:
        raise ProtocolViolation(
            "legacy primary receipt freeze_grade_evidence must be false"
        )
    if reveal.get("freeze_grade_evidence") is not False:
        raise ProtocolViolation(
            "legacy reveal receipt freeze_grade_evidence must be false"
        )
    if materialization.get("freeze_grade_evidence") is not False:
        raise ProtocolViolation(
            "legacy materialization receipt freeze_grade_evidence must be false"
        )
    if primary.get("structural_status") != "complete":
        blockers.append(
            CollectionBlocker(
                "M11-EVIDENCE-INCOMPLETE",
                "primary_state_seal",
                "primary structural seal is not complete",
            )
        )
    return {
        "world_slot": world,
        "record_root": record_root,
        "binding_root": binding_root,
    }, tuple(blockers)


def _parse_migration_receipt(
    files: Mapping[str, bytes],
    *,
    chain: Mapping[str, Any],
    before_seal: Mapping[str, Any],
    after_seal: Mapping[str, Any],
    retrain_digest: str,
) -> dict[str, Any]:
    path = MIGRATION_RECEIPT_PATH
    value = _exact_keys(
        _decode_canonical(files[path], path),
        frozenset(
            {
                "schema_version",
                "extension_id",
                "extension_kind",
                "world_slot",
                "primary_seal_digest",
                "reveal_receipt_digest",
                "materialization_receipt_digest",
                "before_seal_digest",
                "after_seal_digest",
                "retrain_example_set_digest",
                "execution_assurance",
                "source_hiding_verified",
                "query_contract_verified",
                "atomic_publish_verified",
                "completion_disposition",
            }
        ),
        path,
    )
    if value["schema_version"] != MIGRATION_RECEIPT_SCHEMA:
        raise ProtocolViolation("migration receipt schema_version is invalid")
    _name(value["extension_id"], "migration extension_id")
    expected_kind = "new_check" if chain["world_slot"] == "W16" else "new_treatment"
    if value["extension_kind"] != expected_kind:
        raise ProtocolViolation("migration extension_kind contradicts W16/W17")
    if value["world_slot"] != chain["world_slot"]:
        raise ProtocolViolation("migration receipt world is cross-spliced")
    bindings = {
        "primary_seal_digest": digest_bytes(files[PRIMARY_SEAL_PATH]),
        "reveal_receipt_digest": digest_bytes(files[REVEAL_RECEIPT_PATH]),
        "materialization_receipt_digest": digest_bytes(
            files[MATERIALIZATION_RECEIPT_PATH]
        ),
        "before_seal_digest": digest_bytes(files["before/seal.json"]),
        "after_seal_digest": digest_bytes(files["after/seal.json"]),
        "retrain_example_set_digest": retrain_digest,
    }
    for field, expected in bindings.items():
        if value[field] != expected:
            raise ProtocolViolation(
                f"migration receipt {field} is stale or cross-spliced"
            )
    for field in (
        "source_hiding_verified",
        "query_contract_verified",
        "atomic_publish_verified",
    ):
        _bool(value[field], f"migration receipt {field}")
    if value["execution_assurance"] != "fresh-process-exact-byte-custody-v1":
        raise ProtocolViolation("migration receipt execution assurance is invalid")
    if value["completion_disposition"] not in {
        ExtensionDisposition.COMPLETED.value,
        ExtensionDisposition.REQUIRES_FULL_CORE_REWRITE.value,
    }:
        raise ProtocolViolation("migration completion disposition is invalid")
    # A receipt cannot bind a seal while silently swapping its stage identity.
    if before_seal["stage"] != "before" or after_seal["stage"] != "after":
        raise ProtocolViolation("migration seal stages are invalid")
    return value


def _source_diff(before: _Tree, after: _Tree) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    left = before.byte_map
    right = after.byte_map
    left_modes = before.mode_map
    right_modes = after.mode_map
    for path in sorted(set(left) | set(right), key=lambda value: value.encode("utf-8")):
        old_present = path in left
        new_present = path in right
        old = left[path] if old_present else b""
        new = right[path] if new_present else b""
        mode_changed = (
            old_present
            and new_present
            and left_modes.get(path) != right_modes.get(path)
        )
        if old_present == new_present and old == new and not mode_changed:
            continue
        try:
            # keepends makes CRLF/LF and final-newline changes auditable instead
            # of silently collapsing distinct committed source bytes.
            old_lines = old.decode("utf-8", errors="strict").splitlines(keepends=True)
            new_lines = new.decode("utf-8", errors="strict").splitlines(keepends=True)
        except UnicodeDecodeError as exc:
            raise ProtocolViolation(
                f"core source file {path!r} is not UTF-8 text"
            ) from exc
        added = 0
        deleted = 0
        for item in difflib.ndiff(old_lines, new_lines):
            if item.startswith("+ "):
                added += 1
            elif item.startswith("- "):
                deleted += 1
        rows.append({"path": path, "added_lines": added, "deleted_lines": deleted})
    return rows


def _incomplete(
    snapshot: _Snapshot,
    expected_root_commitment: str,
    files: Mapping[str, bytes],
    blockers: list[CollectionBlocker],
) -> ExtensionCostCollection:
    if _scan(snapshot.root).files != snapshot.files:
        raise ProtocolViolation("M11 evidence root changed before incomplete result")
    references = tuple(
        (path, digest_bytes(content))
        for path, content in sorted(files.items(), key=lambda item: item[0].encode())
    )
    return ExtensionCostCollection(
        CollectionStatus.INCOMPLETE,
        snapshot.root.as_posix(),
        expected_root_commitment,
        None,
        tuple(blockers),
        references,
    )


def collect_extension_cost(
    root: Path | str,
    *,
    expected_root_commitment: str,
    live_git_repository: Path | str | None = None,
) -> ExtensionCostCollection:
    """Validate one locally committed M11 evidence tree.

    This is deliberately a local PRE-FREEZE collector.  The expected root
    commitment must come from earlier custody; recomputing it from a modified
    tree is not independent evidence.  Without code-owned migration and old
    benchmark execution verifiers the result remains typed INCOMPLETE.
    """

    snapshot, files, _ = _verify_root(root, expected_root_commitment)
    missing_legacy = sorted(_LEGACY_RECEIPT_PATHS - set(files))
    if missing_legacy:
        return _incomplete(
            snapshot,
            expected_root_commitment,
            files,
            [
                CollectionBlocker(
                    "M11-EVIDENCE-MISSING",
                    path,
                    "required W16/W17 ordering receipt is absent",
                )
                for path in missing_legacy
            ],
        )
    chain, chain_blockers = _parse_receipt_chain(files)
    missing_complete = sorted(_FIXED_COMPLETE_PATHS - set(files))
    if missing_complete or chain_blockers:
        blockers = list(chain_blockers)
        blockers.extend(
            CollectionBlocker(
                "M11-EVIDENCE-MISSING",
                path,
                "legacy extension receipts do not contain this derivation input",
            )
            for path in missing_complete
        )
        return _incomplete(snapshot, expected_root_commitment, files, blockers)

    before_artifacts = _parse_tree(files, stage="before", kind="artifact")
    after_artifacts = _parse_tree(files, stage="after", kind="artifact")
    before_source, before_git = _parse_source_tree(files, stage="before")
    after_source, after_git = _parse_source_tree(files, stage="after")
    if before_git["git_dirty"] or after_git["git_dirty"]:
        raise ProtocolViolation(
            "M11 source evidence must be sealed from clean Git trees"
        )
    if before_git["base_git_commit"] is not None:
        raise ProtocolViolation("before source manifest cannot have a base_git_commit")
    if after_git["base_git_commit"] != before_git["git_commit"]:
        raise ProtocolViolation(
            "after source manifest is not based on exact before commit"
        )
    if (
        before_git["git_commit"] == after_git["git_commit"]
        and before_source.tree_digest != after_source.tree_digest
    ):
        raise ProtocolViolation(
            "the same clean Git commit cannot bind different source trees"
        )
    git_blocker = _verify_live_git(
        live_git_repository,
        before_tree=before_source,
        before_manifest=before_git,
        after_tree=after_source,
        after_manifest=after_git,
    )

    before_seal = _parse_seal(
        files,
        stage="before",
        artifact_tree=before_artifacts,
        source_tree=before_source,
    )
    after_seal = _parse_seal(
        files,
        stage="after",
        artifact_tree=after_artifacts,
        source_tree=after_source,
    )
    retrain_examples, retrain_digest = _parse_retrain(files)
    before_benchmark, before_ids, before_score = _parse_old_benchmark(
        files,
        stage="before",
        source_tree=before_source,
        artifact_tree=before_artifacts,
    )
    after_benchmark, after_ids, after_score = _parse_old_benchmark(
        files,
        stage="after",
        source_tree=after_source,
        artifact_tree=after_artifacts,
    )
    if before_ids != after_ids:
        raise ProtocolViolation("old benchmark before/after cohorts are cross-spliced")
    for field in ("benchmark_scope_digest", "metric_id", "score_direction"):
        if before_benchmark[field] != after_benchmark[field]:
            raise ProtocolViolation(f"old benchmark before/after {field} mismatch")

    migration = _parse_migration_receipt(
        files,
        chain=chain,
        before_seal=before_seal,
        after_seal=after_seal,
        retrain_digest=retrain_digest,
    )
    # Validate the byte-level source delta even when authority is incomplete;
    # an INCOMPLETE result must not launder malformed or non-text source bytes.
    _source_diff(before_source, after_source)
    assurance_blockers = [
        CollectionBlocker(
            "M11-EVIDENCE-INCOMPLETE",
            field,
            "freeze-grade-direction execution receipt did not verify this boundary",
        )
        for field in (
            "source_hiding_verified",
            "query_contract_verified",
            "atomic_publish_verified",
        )
        if migration[field] is not True
    ]
    if git_blocker is not None:
        assurance_blockers.append(git_blocker)
    # These receipt fields are candidate/root-authored claims.  Until a
    # code-owned fresh-process verifier and evaluator receipt are available,
    # neither completion_disposition nor old benchmark row scores may mint an
    # M11 observation or its derived hard-failure bit.
    assurance_blockers.extend(
        (
            CollectionBlocker(
                "UCM-METRIC-B005",
                "migration_execution_verifier",
                "no code-owned verifier binds execution assurances and disposition",
            ),
            CollectionBlocker(
                "UCM-METRIC-B005",
                "old_benchmark_evaluator_receipt",
                "old benchmark row scores lack a code-owned evaluator receipt",
            ),
        )
    )
    if assurance_blockers:
        return _incomplete(
            snapshot, expected_root_commitment, files, assurance_blockers
        )

    diff_files = _source_diff(before_source, after_source)
    model_migration = (
        before_seal["model_artifact_digest"] != after_seal["model_artifact_digest"]
        or before_seal["model_schema_digest"] != after_seal["model_schema_digest"]
    )
    state_migration = (
        before_seal["state_snapshot_digest"] != after_seal["state_snapshot_digest"]
        or before_seal["state_schema_digest"] != after_seal["state_schema_digest"]
    )
    schema_migration = (
        before_seal["model_schema_digest"] != after_seal["model_schema_digest"]
        or before_seal["state_schema_digest"] != after_seal["state_schema_digest"]
    )
    payload = {
        "schema_version": M11_OBSERVATION_SCHEMA,
        "extension_id": migration["extension_id"],
        "extension_kind": migration["extension_kind"],
        "model_migration_required": model_migration,
        "state_migration_required": state_migration,
        "schema_migration_required": schema_migration,
        "retrain_examples": retrain_examples,
        "base_artifact_size_bytes": before_artifacts.size_bytes,
        "extended_artifact_size_bytes": after_artifacts.size_bytes,
        "core_diff_files": diff_files,
        "old_benchmark_before_score": before_score,
        "old_benchmark_after_score": after_score,
        "old_benchmark_score_direction": before_benchmark["score_direction"],
        "old_benchmark_denominator": len(before_ids),
        "completion_disposition": migration["completion_disposition"],
    }
    evidence = CanonicalMetricEvidence.from_payload(
        f"m11-live/{migration['extension_id']}.json", payload
    )
    observation = ExtensionCostObservation(evidence)
    # The final scan makes ordinary post-manifest path/byte mutation fail closed.
    if _scan(snapshot.root).files != snapshot.files:
        raise ProtocolViolation("M11 evidence root changed during derivation")
    references = tuple(
        (path, digest_bytes(content))
        for path, content in sorted(files.items(), key=lambda item: item[0].encode())
    )
    return ExtensionCostCollection(
        CollectionStatus.COMPLETE,
        snapshot.root.as_posix(),
        expected_root_commitment,
        observation,
        (),
        references,
    )


__all__ = [
    "BENCHMARK_EVIDENCE_SCHEMA",
    "BENCHMARK_STATUS",
    "COLLECTOR_RESULT_SCHEMA",
    "CollectionBlocker",
    "CollectionStatus",
    "ExtensionCostCollection",
    "MIGRATION_RECEIPT_PATH",
    "MIGRATION_RECEIPT_SCHEMA",
    "OLD_BENCHMARK_METRIC_ID",
    "OLD_BENCHMARK_SCORE_DIRECTION",
    "OLD_BENCHMARK_TARGET_SCOPE_DIGEST",
    "RETRAIN_EXAMPLE_SCHEMA",
    "RETRAIN_MANIFEST_SCHEMA",
    "ROOT_MANIFEST_PATH",
    "ROOT_MANIFEST_SCHEMA",
    "SEAL_MANIFEST_SCHEMA",
    "SOURCE_MANIFEST_SCHEMA",
    "TREE_MANIFEST_SCHEMA",
    "collect_extension_cost",
]
