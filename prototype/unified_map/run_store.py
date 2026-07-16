"""Fail-closed, locally sealed result bundles for UCM experiments.

This module is a *local integrity* layer, not an external custody service.  A
published bundle is closed over an exact, run-class-owned layout, every verify
rehashes the live bytes, and a sibling local seal prevents an attacker who only
rewrites the bundle from silently replacing its inventory and final marker.
The sibling seal and read-only mode live on the same filesystem as the bundle;
neither is WORM storage, an independent signature, nor a race-free kernel
boundary.  Verification receipts therefore remain explicitly PRE-FREEZE.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)


RUN_MANIFEST_PROTOCOL = "ucm-run-manifest/1"
INVENTORY_PROTOCOL = "ucm-output-inventory/2"
FINALIZED_PROTOCOL = "ucm-finalized-run/2"
LOCAL_SEAL_PROTOCOL = "ucm-local-run-seal/1"
CRASH_PLACEHOLDER_PROTOCOL = "ucm-run-crash-placeholders/2"
CRASH_EVIDENCE_PROTOCOL = "ucm-run-crash-evidence/1"
CRASH_RECORD_PROTOCOL = "ucm-run-crash-record/1"
VERIFICATION_RECEIPT_PROTOCOL = "ucm-run-verification-receipt/1"
CHECKSUM_PROTOCOL = "ucm-run-checksums/1"
TREE_PROTOCOL = "ucm-run-tree/1"
FINALIZATION_BINDING_PROTOCOL = "ucm-run-finalization-binding/1"
ROOT_BINDING_PROTOCOL = "ucm-results-root-binding/1"
CANDIDATE_SOURCE_MANIFEST_PROTOCOL = "ucm-candidate-source-manifest/1"
CANDIDATE_MODEL_MANIFEST_PROTOCOL = "ucm-candidate-model-manifest/1"

BENCHMARK_ID = "UCM-BENCHMARK-v1"
PRE_FREEZE_STATUS = "PRE-FREEZE"
INCOMPLETE_CODE = "UCM-E003-HARNESS_INCOMPLETE"

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMESTAMP_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)


class RunClass(str, Enum):
    DEVELOPMENT = "development"
    SEALED_VALIDATION = "sealed_validation"
    SEALED_TEST = "sealed_test"
    POST_TEST_TUNED = "post_test_tuned"
    REDTEAM = "redteam"
    REPRODUCTION = "reproduction"


class RunStatus(str, Enum):
    RUNNING = "running"
    FINALIZED = "finalized"
    CRASHED = "crashed"
    INELIGIBLE = "ineligible"


class IsolationAssurance(str, Enum):
    PYTHON_AUDIT = "python_audit"
    OS_SANDBOX = "os_sandbox"
    CONTAINER = "container"


# The benchmark currently has one exact output contract for every run class.
# It is intentionally repeated through a code-owned lookup rather than accepted
# from the run producer.  A later benchmark revision may split these layouts.
_DEVELOPMENT_REQUIRED_PAYLOAD_PATHS = (
    "candidate/source-manifest.json",
    "candidate/model-manifest.json",
    "candidate/model-artifact.sha256",
    "inputs/public-input-digests.jsonl",
    "raw/states.jsonl",
    "raw/updates.jsonl",
    "raw/predictions.jsonl",
    "raw/oracle-judge.jsonl",
    "raw/process-audit.jsonl",
    "raw/resources.jsonl",
    "metrics/per-query.jsonl",
    "metrics/per-episode.jsonl",
    "metrics/per-world.jsonl",
    "metrics/aggregate.json",
    "failures/compliance.json",
    "failures/collisions.jsonl",
    "failures/false-splits.jsonl",
    "failures/worst-trajectories.jsonl",
    "logs/stdout.log",
    "logs/stderr.log",
)
_CONTROL_PATHS = frozenset(
    {
        "RUN_MANIFEST.json",
        "checksums.sha256",
        "INVENTORY.json",
        "FINALIZED.json",
        "CRASH_PLACEHOLDERS.json",
        "CRASH_EVIDENCE.json",
    }
)

_MANDATORY_CRASH_EVIDENCE_PATHS = (
    "logs/stderr.log",
    "logs/stdout.log",
    "raw/process-audit.jsonl",
)


def required_payload_paths(run_class: RunClass) -> tuple[str, ...]:
    """Return the immutable benchmark-owned payload layout for ``run_class``."""

    if type(run_class) is not RunClass:
        raise ProtocolViolation("run_class must be typed")
    if run_class is RunClass.DEVELOPMENT:
        return _DEVELOPMENT_REQUIRED_PAYLOAD_PATHS
    raise ProtocolViolation(
        f"run_class={run_class.value!r} has no code-owned dedicated layout; "
        "sealed/redteam/reproduction publication is disabled PRE-FREEZE"
    )


def validate_run_id(run_id: str) -> None:
    if type(run_id) is not str or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ProtocolViolation(
            "run_id must be one safe path component of at most 128 characters"
        )
    if run_id in {".", ".."}:
        raise ProtocolViolation("run_id cannot be a dot path")
    stem = run_id.split(".", 1)[0].upper()
    if run_id.endswith(".") or stem in WINDOWS_RESERVED_NAMES:
        raise ProtocolViolation("run_id is unsafe on Windows")


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not SHA256_PATTERN.fullmatch(value):
        raise ProtocolViolation(f"{label} must be a lowercase sha256-prefixed digest")
    return value


def _timestamp(value: object, label: str) -> str:
    if type(value) is not str or not TIMESTAMP_PATTERN.fullmatch(value):
        raise ProtocolViolation(f"{label} must be an RFC3339 UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProtocolViolation(f"{label} must be a real RFC3339 UTC timestamp") from exc
    return value


def _timestamp_value(value: str) -> datetime:
    # _timestamp has already restricted this to UTC RFC3339 with terminal Z.
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ProtocolViolation(f"{label} keys differ; missing={missing!r}, extra={extra!r}")
    return value


def _safe_relative(path: str) -> Path:
    if (
        type(path) is not str
        or not path
        or "\\" in path
        or path.startswith("/")
        or ":" in path
        or any(ord(character) < 32 for character in path)
    ):
        raise ProtocolViolation("bundle path must be a non-empty POSIX path")
    # Path is safe here because backslashes and drive/absolute syntax were
    # rejected above.  On Windows, '/' remains the only accepted separator.
    relative = Path(*path.split("/"))
    if (
        relative == Path(".")
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ProtocolViolation("bundle path must stay within the run directory")
    for part in relative.parts:
        stem = part.split(".", 1)[0].upper()
        if part.endswith((" ", ".")) or stem in WINDOWS_RESERVED_NAMES:
            raise ProtocolViolation("bundle path is unsafe on Windows")
    return relative


def _normalized_root(root: Path) -> str:
    if not isinstance(root, Path):
        raise ProtocolViolation("run root must be pathlib.Path")
    # Do not call resolve(): following a junction/symlink would erase exactly
    # the provenance distinction that the verifier must reject.
    absolute = os.path.abspath(os.fspath(root))
    normalized = os.path.normcase(os.path.normpath(absolute)).replace("\\", "/")
    return normalized


def results_root_digest(root: Path) -> str:
    return digest_json(
        {
            "protocol": ROOT_BINDING_PROTOCOL,
            "absolute_root": _normalized_root(root),
        }
    )


def _is_reparse(stat_result: os.stat_result) -> bool:
    attributes = getattr(stat_result, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _assert_no_windows_alternate_streams(path: Path, label: str) -> None:
    """Reject named NTFS streams; fail closed if enumeration itself fails."""

    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class _Win32FindStreamData(ctypes.Structure):
        _fields_ = [
            ("stream_size", ctypes.c_longlong),
            ("stream_name", wintypes.WCHAR * 296),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    find_first = kernel32.FindFirstStreamW
    find_first.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(_Win32FindStreamData),
        wintypes.DWORD,
    ]
    find_first.restype = wintypes.HANDLE
    find_next = kernel32.FindNextStreamW
    find_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Win32FindStreamData)]
    find_next.restype = wintypes.BOOL
    find_close = kernel32.FindClose
    find_close.argtypes = [wintypes.HANDLE]
    find_close.restype = wintypes.BOOL

    data = _Win32FindStreamData()
    handle = find_first(str(path), 0, ctypes.byref(data), 0)
    invalid = ctypes.c_void_p(-1).value
    handle_value = ctypes.cast(handle, ctypes.c_void_p).value
    if handle_value == invalid:
        error = ctypes.get_last_error()
        # ERROR_HANDLE_EOF means this filesystem reports no streams (common
        # for directories or filesystems without NTFS stream support).
        if error == 38:
            return
        raise ProtocolViolation(f"cannot enumerate alternate streams for {label}: {error}")
    try:
        while True:
            stream_name = data.stream_name
            if stream_name != "::$DATA":
                raise ProtocolViolation(f"{label} contains a named alternate data stream")
            if not find_next(handle, ctypes.byref(data)):
                error = ctypes.get_last_error()
                if error == 38:
                    break
                raise ProtocolViolation(
                    f"cannot complete alternate-stream enumeration for {label}: {error}"
                )
    finally:
        find_close(handle)


def _assert_plain_directory(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ProtocolViolation(f"{label} does not exist") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise ProtocolViolation(f"{label} must be a plain, non-reparse directory")
    _assert_no_windows_alternate_streams(path, label)


def _assert_no_reparse_ancestors(path: Path, label: str) -> None:
    """Reject a lexical path whose existing ancestry crosses a link/reparse."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    chain = tuple(reversed(absolute.parents)) + (absolute,)
    for component in chain:
        # Drive anchors exist as directories but have no useful parent entry.
        if component == Path(component.anchor):
            continue
        try:
            info = component.lstat()
        except FileNotFoundError as exc:
            raise ProtocolViolation(f"{label} ancestor is missing: {component}") from exc
        if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
            raise ProtocolViolation(f"{label} ancestry crosses a symlink/junction/reparse point")
        if not stat.S_ISDIR(info.st_mode):
            raise ProtocolViolation(f"{label} ancestor is not a directory: {component}")


def _assert_plain_file(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ProtocolViolation(f"{label} is missing") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
        raise ProtocolViolation(f"{label} cannot be a symlink, junction, or reparse point")
    if not stat.S_ISREG(info.st_mode):
        raise ProtocolViolation(f"{label} must be a regular file")
    if getattr(info, "st_nlink", 1) != 1:
        raise ProtocolViolation(f"{label} cannot be hard-linked")
    _assert_no_windows_alternate_streams(path, label)
    return info


@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    python: str
    os: str
    container: str
    dependency_lock: str

    def __post_init__(self) -> None:
        _name(self.python, "runtime.python")
        _name(self.os, "runtime.os")
        _name(self.container, "runtime.container")
        _digest(self.dependency_lock, "runtime.dependency_lock")

    def to_wire(self) -> dict[str, Any]:
        return {
            "python": self.python,
            "os": self.os,
            "container": self.container,
            "dependency_lock": self.dependency_lock,
        }

    @classmethod
    def from_wire(cls, value: object) -> "RuntimeManifest":
        body = _exact_keys(
            value,
            frozenset({"python", "os", "container", "dependency_lock"}),
            "runtime",
        )
        return cls(
            python=body["python"],
            os=body["os"],
            container=body["container"],
            dependency_lock=body["dependency_lock"],
        )


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    results_root_digest: str
    run_class: RunClass
    status: RunStatus
    benchmark_id: str
    benchmark_freeze_digest: str
    scope_digest: str
    hidden_corpus_digest: str
    candidate_id: str
    candidate_source_seal: str
    model_artifact_digest: str
    git_commit: str
    git_dirty: bool
    training_replicate_id: str
    evaluation_replicate_id: str
    training_seed_tuple_digest: str
    evaluation_seed_tuple_digest: str
    train_data_digest: str
    validation_data_digest: str
    runtime: RuntimeManifest
    isolation_assurance: IsolationAssurance
    started_at: str
    finished_at: str
    supersedes_run_id: str | None = None

    def __post_init__(self) -> None:
        validate_run_id(self.run_id)
        _digest(self.results_root_digest, "results_root_digest")
        if type(self.run_class) is not RunClass:
            raise ProtocolViolation("run_class must be typed")
        if type(self.status) is not RunStatus:
            raise ProtocolViolation("run status must be typed")
        if self.benchmark_id != BENCHMARK_ID:
            raise ProtocolViolation(f"benchmark_id must be {BENCHMARK_ID!r}")
        for field_name in (
            "benchmark_freeze_digest",
            "scope_digest",
            "hidden_corpus_digest",
            "candidate_source_seal",
            "model_artifact_digest",
            "training_seed_tuple_digest",
            "evaluation_seed_tuple_digest",
            "train_data_digest",
            "validation_data_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        _name(self.candidate_id, "candidate_id")
        _name(self.git_commit, "git_commit")
        if type(self.git_dirty) is not bool:
            raise ProtocolViolation("git_dirty must be exact bool")
        _name(self.training_replicate_id, "training_replicate_id")
        _name(self.evaluation_replicate_id, "evaluation_replicate_id")
        if type(self.runtime) is not RuntimeManifest:
            raise ProtocolViolation("runtime must be typed RuntimeManifest")
        if type(self.isolation_assurance) is not IsolationAssurance:
            raise ProtocolViolation("isolation_assurance must be typed")
        _timestamp(self.started_at, "started_at")
        _timestamp(self.finished_at, "finished_at")
        if _timestamp_value(self.finished_at) < _timestamp_value(self.started_at):
            raise ProtocolViolation("finished_at cannot precede started_at")
        if self.supersedes_run_id is not None:
            validate_run_id(self.supersedes_run_id)
            if self.supersedes_run_id == self.run_id:
                raise ProtocolViolation("a run cannot supersede itself")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": RUN_MANIFEST_PROTOCOL,
            "run_id": self.run_id,
            "results_root_digest": self.results_root_digest,
            "run_class": self.run_class.value,
            "status": self.status.value,
            "benchmark_id": self.benchmark_id,
            "benchmark_freeze_digest": self.benchmark_freeze_digest,
            "scope_digest": self.scope_digest,
            "hidden_corpus_digest": self.hidden_corpus_digest,
            "candidate_id": self.candidate_id,
            "candidate_source_seal": self.candidate_source_seal,
            "model_artifact_digest": self.model_artifact_digest,
            "git_commit": self.git_commit,
            "git_dirty": self.git_dirty,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "training_seed_tuple_digest": self.training_seed_tuple_digest,
            "evaluation_seed_tuple_digest": self.evaluation_seed_tuple_digest,
            "train_data_digest": self.train_data_digest,
            "validation_data_digest": self.validation_data_digest,
            "runtime": self.runtime.to_wire(),
            "isolation_assurance": self.isolation_assurance.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "supersedes_run_id": self.supersedes_run_id,
        }

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["manifest_digest"] = digest_json(body)
        return body

    @property
    def digest(self) -> str:
        return self.to_wire()["manifest_digest"]

    @classmethod
    def from_wire(cls, value: object) -> "RunManifest":
        expected = frozenset(
            {
                "schema_version",
                "run_id",
                "results_root_digest",
                "run_class",
                "status",
                "benchmark_id",
                "benchmark_freeze_digest",
                "scope_digest",
                "hidden_corpus_digest",
                "candidate_id",
                "candidate_source_seal",
                "model_artifact_digest",
                "git_commit",
                "git_dirty",
                "training_replicate_id",
                "evaluation_replicate_id",
                "training_seed_tuple_digest",
                "evaluation_seed_tuple_digest",
                "train_data_digest",
                "validation_data_digest",
                "runtime",
                "isolation_assurance",
                "started_at",
                "finished_at",
                "supersedes_run_id",
                "manifest_digest",
            }
        )
        body = _exact_keys(value, expected, "RUN_MANIFEST.json")
        if body["schema_version"] != RUN_MANIFEST_PROTOCOL:
            raise ProtocolViolation("wrong run manifest schema_version")
        claimed_digest = _digest(body["manifest_digest"], "manifest_digest")
        unsigned = {key: item for key, item in body.items() if key != "manifest_digest"}
        if digest_json(unsigned) != claimed_digest:
            raise ProtocolViolation("run manifest self-digest mismatch")
        try:
            run_class = RunClass(body["run_class"])
            status = RunStatus(body["status"])
            isolation = IsolationAssurance(body["isolation_assurance"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("run manifest contains an unknown typed enum") from exc
        return cls(
            run_id=body["run_id"],
            results_root_digest=body["results_root_digest"],
            run_class=run_class,
            status=status,
            benchmark_id=body["benchmark_id"],
            benchmark_freeze_digest=body["benchmark_freeze_digest"],
            scope_digest=body["scope_digest"],
            hidden_corpus_digest=body["hidden_corpus_digest"],
            candidate_id=body["candidate_id"],
            candidate_source_seal=body["candidate_source_seal"],
            model_artifact_digest=body["model_artifact_digest"],
            git_commit=body["git_commit"],
            git_dirty=body["git_dirty"],
            training_replicate_id=body["training_replicate_id"],
            evaluation_replicate_id=body["evaluation_replicate_id"],
            training_seed_tuple_digest=body["training_seed_tuple_digest"],
            evaluation_seed_tuple_digest=body["evaluation_seed_tuple_digest"],
            train_data_digest=body["train_data_digest"],
            validation_data_digest=body["validation_data_digest"],
            runtime=RuntimeManifest.from_wire(body["runtime"]),
            isolation_assurance=isolation,
            started_at=body["started_at"],
            finished_at=body["finished_at"],
            supersedes_run_id=body["supersedes_run_id"],
        )


@dataclass(frozen=True, slots=True)
class CrashPlaceholder:
    path: str
    evidence_path: str
    reason_code: str
    evidence_digest: str

    def __post_init__(self) -> None:
        _safe_relative(self.path)
        _safe_relative(self.evidence_path)
        if self.evidence_path not in _MANDATORY_CRASH_EVIDENCE_PATHS:
            raise ProtocolViolation(
                "crash placeholder evidence_path must be a retained mandatory crash artifact"
            )
        _name(self.reason_code, "crash placeholder reason_code")
        _digest(self.evidence_digest, "crash placeholder evidence_digest")

    def to_wire(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "evidence_path": self.evidence_path,
            "reason_code": self.reason_code,
            "evidence_digest": self.evidence_digest,
        }

    @classmethod
    def from_wire(cls, value: object) -> "CrashPlaceholder":
        body = _exact_keys(
            value,
            frozenset({"path", "evidence_path", "reason_code", "evidence_digest"}),
            "crash placeholder",
        )
        return cls(
            path=body["path"],
            evidence_path=body["evidence_path"],
            reason_code=body["reason_code"],
            evidence_digest=body["evidence_digest"],
        )


@dataclass(frozen=True, slots=True)
class CrashEvidenceRecord:
    reason_code: str
    failure_type: str
    detail_digest: str
    worker_exit: int
    occurred_at: str

    def __post_init__(self) -> None:
        _name(self.reason_code, "crash evidence reason_code")
        _name(self.failure_type, "crash evidence failure_type")
        _digest(self.detail_digest, "crash evidence detail_digest")
        if type(self.worker_exit) is not int:
            raise ProtocolViolation("crash evidence worker_exit must be exact int")
        _timestamp(self.occurred_at, "crash evidence occurred_at")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": CRASH_RECORD_PROTOCOL,
            "reason_code": self.reason_code,
            "failure_type": self.failure_type,
            "detail_digest": self.detail_digest,
            "worker_exit": self.worker_exit,
            "occurred_at": self.occurred_at,
        }

    @classmethod
    def from_wire(cls, value: object) -> "CrashEvidenceRecord":
        body = _exact_keys(
            value,
            frozenset(
                {
                    "schema_version",
                    "reason_code",
                    "failure_type",
                    "detail_digest",
                    "worker_exit",
                    "occurred_at",
                }
            ),
            "crash evidence record",
        )
        if body["schema_version"] != CRASH_RECORD_PROTOCOL:
            raise ProtocolViolation("wrong crash evidence record schema")
        return cls(
            reason_code=body["reason_code"],
            failure_type=body["failure_type"],
            detail_digest=body["detail_digest"],
            worker_exit=body["worker_exit"],
            occurred_at=body["occurred_at"],
        )


def _validate_crash_record_context(
    record: CrashEvidenceRecord, manifest: RunManifest
) -> None:
    occurred = _timestamp_value(record.occurred_at)
    if not (
        _timestamp_value(manifest.started_at)
        <= occurred
        <= _timestamp_value(manifest.finished_at)
    ):
        raise ProtocolViolation("crash evidence occurred_at is outside the run interval")
    if manifest.status is RunStatus.CRASHED and record.worker_exit == 0:
        raise ProtocolViolation("crashed run evidence cannot report worker_exit=0")


@dataclass(frozen=True, slots=True)
class RunVerificationReceipt:
    run_id: str
    results_root_digest: str
    run_class: RunClass
    run_status: RunStatus
    benchmark_id: str
    benchmark_freeze_digest: str
    scope_digest: str
    hidden_corpus_digest: str
    candidate_id: str
    candidate_source_seal: str
    model_artifact_digest: str
    manifest_sha256: str
    inventory_sha256: str
    finalized_sha256: str
    local_seal_sha256: str
    tree_digest: str
    verified_file_count: int
    readonly_all_observed: bool
    windows_alternate_data_streams_checked: bool
    receipt_digest: str

    def __post_init__(self) -> None:
        validate_run_id(self.run_id)
        _digest(self.results_root_digest, "receipt results_root_digest")
        if type(self.run_class) is not RunClass or type(self.run_status) is not RunStatus:
            raise ProtocolViolation("verification receipt run enums must be typed")
        required_payload_paths(self.run_class)
        if self.benchmark_id != BENCHMARK_ID:
            raise ProtocolViolation("verification receipt benchmark mismatch")
        for label in (
            "benchmark_freeze_digest",
            "scope_digest",
            "hidden_corpus_digest",
            "candidate_source_seal",
            "model_artifact_digest",
            "manifest_sha256",
            "inventory_sha256",
            "finalized_sha256",
            "local_seal_sha256",
            "tree_digest",
            "receipt_digest",
        ):
            _digest(getattr(self, label), f"receipt {label}")
        _name(self.candidate_id, "receipt candidate_id")
        if type(self.verified_file_count) is not int or self.verified_file_count < 1:
            raise ProtocolViolation("verified_file_count must be positive")
        if type(self.readonly_all_observed) is not bool:
            raise ProtocolViolation("readonly_all_observed must be bool")
        if type(self.windows_alternate_data_streams_checked) is not bool:
            raise ProtocolViolation("windows_alternate_data_streams_checked must be bool")

        if digest_json(self._body_without_receipt()) != self.receipt_digest:
            raise ProtocolViolation("verification receipt self-digest mismatch")

    def _body_without_receipt(self) -> dict[str, Any]:
        return {
            "schema_version": VERIFICATION_RECEIPT_PROTOCOL,
            "status": PRE_FREEZE_STATUS,
            "blockers": [INCOMPLETE_CODE],
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "custody_assurance": "LOCAL_REHASH_AND_SIBLING_SEAL_ONLY",
            "external_worm_verified": False,
            "race_free_kernel_custody": False,
            "root_binding_scope": "LOCAL_ABSOLUTE_PATH_ONLY",
            "absolute_root_binding_portable": False,
            "filesystem_link_checks": "LSTAT_SYMLINK_REPARSE_AND_NLINK",
            "filesystem_link_checks_race_free": False,
            "xattrs_acl_custody_verified": False,
            "windows_alternate_data_streams_checked": self.windows_alternate_data_streams_checked,
            "readonly_is_authority": False,
            "run_id": self.run_id,
            "results_root_digest": self.results_root_digest,
            "run_class": self.run_class.value,
            "run_status": self.run_status.value,
            "benchmark_id": self.benchmark_id,
            "benchmark_freeze_digest": self.benchmark_freeze_digest,
            "scope_digest": self.scope_digest,
            "hidden_corpus_digest": self.hidden_corpus_digest,
            "candidate_id": self.candidate_id,
            "candidate_source_seal": self.candidate_source_seal,
            "model_artifact_digest": self.model_artifact_digest,
            "manifest_sha256": self.manifest_sha256,
            "inventory_sha256": self.inventory_sha256,
            "finalized_sha256": self.finalized_sha256,
            "local_seal_sha256": self.local_seal_sha256,
            "tree_digest": self.tree_digest,
            "verified_file_count": self.verified_file_count,
            "readonly_all_observed": self.readonly_all_observed,
        }

    def to_wire(self) -> dict[str, Any]:
        body = self._body_without_receipt()
        body["receipt_digest"] = self.receipt_digest
        return body


@dataclass(frozen=True, slots=True)
class _TreeSnapshot:
    directories: tuple[str, ...]
    files: tuple[tuple[str, bytes, os.stat_result], ...]


def _scan_tree(root: Path) -> _TreeSnapshot:
    _assert_plain_directory(root, "run directory")
    directories: list[str] = []
    files: list[tuple[str, bytes, os.stat_result]] = []

    def walk(directory: Path, prefix: str) -> None:
        _assert_no_windows_alternate_streams(
            directory, f"bundle directory {prefix or '.'!r}"
        )
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.encode("utf-8"))
        except OSError as exc:
            raise ProtocolViolation(f"cannot scan run directory {prefix or '.'!r}") from exc
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            _safe_relative(relative)
            entry_path = Path(entry.path)
            try:
                # On Windows a DirEntry retained after its scandir handle closes
                # can expose zeroed inode/link metadata.  lstat the path itself
                # so hardlink/reparse checks use authoritative live metadata.
                info = entry_path.lstat()
            except OSError as exc:
                raise ProtocolViolation(f"cannot stat bundle entry {relative!r}") from exc
            if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
                raise ProtocolViolation(
                    f"bundle entry {relative!r} is a symlink, junction, or reparse point"
                )
            if stat.S_ISDIR(info.st_mode):
                directories.append(relative)
                walk(entry_path, relative)
            elif stat.S_ISREG(info.st_mode):
                payload = entry_path.read_bytes()
                after = _assert_plain_file(entry_path, f"bundle file {relative!r}")
                before_identity = (
                    info.st_dev,
                    info.st_ino,
                    info.st_size,
                    getattr(info, "st_mtime_ns", None),
                )
                after_identity = (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    getattr(after, "st_mtime_ns", None),
                )
                if before_identity != after_identity or len(payload) != after.st_size:
                    raise ProtocolViolation(f"bundle file {relative!r} changed during verification")
                files.append((relative, payload, after))
            else:
                raise ProtocolViolation(f"bundle entry {relative!r} is not a regular file/directory")

    walk(root, "")
    return _TreeSnapshot(tuple(directories), tuple(files))


def _rows_from_files(files: Iterable[tuple[str, bytes, os.stat_result]]) -> list[dict[str, Any]]:
    return [
        {"path": path, "bytes": len(payload), "sha256": digest_bytes(payload)}
        for path, payload, _ in files
        if path not in {"INVENTORY.json", "FINALIZED.json"}
    ]


def _expected_directories(paths: Iterable[str]) -> tuple[str, ...]:
    directories: set[str] = set()
    for value in paths:
        parts = value.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            directories.add("/".join(parts[:index]))
    return tuple(sorted(directories, key=lambda item: item.encode("utf-8")))


def _checksum_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    lines = [
        f"{row['sha256'][7:]}  {row['path']}\n".encode("utf-8")
        for row in rows
    ]
    return b"".join(lines)


def _finalization_binding(manifest: RunManifest, manifest_sha256: str, tree_digest: str) -> str:
    return digest_json(
        {
            "protocol": FINALIZATION_BINDING_PROTOCOL,
            "run_id": manifest.run_id,
            "results_root_digest": manifest.results_root_digest,
            "run_class": manifest.run_class.value,
            "run_status": manifest.status.value,
            "benchmark_id": manifest.benchmark_id,
            "benchmark_freeze_digest": manifest.benchmark_freeze_digest,
            "scope_digest": manifest.scope_digest,
            "hidden_corpus_digest": manifest.hidden_corpus_digest,
            "candidate_id": manifest.candidate_id,
            "candidate_source_seal": manifest.candidate_source_seal,
            "model_artifact_digest": manifest.model_artifact_digest,
            "manifest_sha256": manifest_sha256,
            "tree_digest": tree_digest,
        }
    )


def _validate_candidate_artifact_bindings(
    manifest: RunManifest, payloads: dict[str, bytes]
) -> None:
    """Bind the three candidate artifacts to the typed outer manifest."""

    source_path = "candidate/source-manifest.json"
    if source_path in payloads:
        source = _exact_keys(
            _decode_json(payloads[source_path], source_path),
            frozenset({"schema_version", "candidate_id", "candidate_source_seal"}),
            "candidate source manifest",
        )
        expected_source = {
            "schema_version": CANDIDATE_SOURCE_MANIFEST_PROTOCOL,
            "candidate_id": manifest.candidate_id,
            "candidate_source_seal": manifest.candidate_source_seal,
        }
        if source != expected_source:
            raise ProtocolViolation("candidate source manifest differs from RunManifest")
    model_path = "candidate/model-manifest.json"
    if model_path in payloads:
        model = _exact_keys(
            _decode_json(payloads[model_path], model_path),
            frozenset(
                {
                    "schema_version",
                    "candidate_id",
                    "candidate_source_seal",
                    "model_artifact_digest",
                }
            ),
            "candidate model manifest",
        )
        expected_model = {
            "schema_version": CANDIDATE_MODEL_MANIFEST_PROTOCOL,
            "candidate_id": manifest.candidate_id,
            "candidate_source_seal": manifest.candidate_source_seal,
            "model_artifact_digest": manifest.model_artifact_digest,
        }
        if model != expected_model:
            raise ProtocolViolation("candidate model manifest differs from RunManifest")
    digest_path = "candidate/model-artifact.sha256"
    if digest_path in payloads:
        expected_digest_file = (manifest.model_artifact_digest + "\n").encode("ascii")
        if payloads[digest_path] != expected_digest_file:
            raise ProtocolViolation("candidate model-artifact.sha256 differs from RunManifest")


def _local_seal_path(root: Path, run_id: str) -> Path:
    return root / f".{run_id}.local-seal.json"


def _entry_exists(path: Path) -> bool:
    """Like lexists: broken symlinks/reparse entries still occupy the name."""

    return os.path.lexists(os.fspath(path))


class AppendOnlyRunWriter:
    """Build one exact run in a sibling temporary directory, then publish once."""

    def __init__(self, root: Path, run_id: str, manifest: RunManifest) -> None:
        validate_run_id(run_id)
        if not isinstance(root, Path):
            raise ProtocolViolation("run root must be pathlib.Path")
        if type(manifest) is not RunManifest:
            raise ProtocolViolation("manifest must be typed RunManifest")
        root.mkdir(parents=True, exist_ok=True)
        _assert_no_reparse_ancestors(root, "run root")
        _assert_plain_directory(root, "run root")
        self.root = Path(os.path.abspath(os.fspath(root)))
        if manifest.run_id != run_id:
            raise ProtocolViolation("run_id argument and manifest.run_id differ")
        if manifest.results_root_digest != results_root_digest(self.root):
            raise ProtocolViolation("manifest results_root_digest does not bind this root")
        if manifest.status is RunStatus.RUNNING:
            raise ProtocolViolation("published run manifests cannot retain status=running")
        # This lookup is also the fail-closed enable gate.  A RunClass enum is
        # not evidence that its dedicated commit/reveal/custody layout exists.
        required_payload_paths(manifest.run_class)
        self.manifest = manifest
        self.run_id = run_id
        self.target = self.root / run_id
        self.lock = self.root / f".{run_id}.lock"
        self.local_seal = _local_seal_path(self.root, run_id)
        if _entry_exists(self.target) or _entry_exists(self.local_seal):
            raise FileExistsError(f"run already exists: {self.target}")

        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.lock,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o600,
            )
            os.write(descriptor, (run_id + "\n").encode("ascii"))
            os.fsync(descriptor)
        except FileExistsError as exc:
            raise FileExistsError(f"run is already being produced: {run_id}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

        self.temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}.tmp-", dir=self.root))
        self._closed = False
        try:
            self._write_control("RUN_MANIFEST.json", canonical_json_bytes(manifest.to_wire()))
        except BaseException:
            self.abort()
            raise

    def _destination(self, relative: str, *, control: bool = False) -> Path:
        if self._closed:
            raise RuntimeError("run writer is closed")
        safe = _safe_relative(relative).as_posix()
        allowed = _CONTROL_PATHS if control else frozenset(required_payload_paths(self.manifest.run_class))
        if safe not in allowed:
            raise ProtocolViolation(f"path {safe!r} is not in the exact run-class layout")
        target = self.temporary / _safe_relative(safe)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _write_exact(self, target: Path, payload: bytes) -> None:
        with target.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

    def _write_control(self, relative: str, payload: bytes) -> None:
        self._write_exact(self._destination(relative, control=True), payload)

    def write_bytes(self, relative: str, payload: bytes) -> None:
        if type(payload) is not bytes:
            raise ProtocolViolation("run payload must be exact bytes")
        self._write_exact(self._destination(relative), payload)

    def write_json(self, relative: str, value: Any) -> None:
        self.write_bytes(relative, canonical_json_bytes(value))

    def _validate_layout_and_placeholders(
        self,
        crash_placeholders: tuple[CrashPlaceholder, ...],
        crash_evidence: CrashEvidenceRecord | None,
    ) -> None:
        snapshot = _scan_tree(self.temporary)
        actual = {path for path, _, _ in snapshot.files}
        payloads = {path: payload for path, payload, _ in snapshot.files}
        payload_required = set(required_payload_paths(self.manifest.run_class))
        unexpected = actual - payload_required - {"RUN_MANIFEST.json"}
        if unexpected:
            raise ProtocolViolation(
                f"run contains files outside the exact layout: {sorted(unexpected)!r}"
            )
        live_manifest = RunManifest.from_wire(
            _decode_json(payloads["RUN_MANIFEST.json"], "RUN_MANIFEST.json")
        )
        if live_manifest != self.manifest:
            raise ProtocolViolation("live RUN_MANIFEST.json differs from typed writer manifest")
        _validate_candidate_artifact_bindings(self.manifest, payloads)
        present_payload = actual & payload_required
        missing = payload_required - present_payload
        if self.manifest.status is RunStatus.FINALIZED:
            if crash_placeholders:
                raise ProtocolViolation("finalized runs cannot declare crash placeholders")
            if crash_evidence is not None:
                raise ProtocolViolation("finalized runs cannot declare crash evidence")
            if missing:
                raise ProtocolViolation(f"finalized run is missing required paths: {sorted(missing)!r}")
        else:
            if self.manifest.status not in {RunStatus.CRASHED, RunStatus.INELIGIBLE}:
                raise ProtocolViolation("unknown publishable run status")
            paths = tuple(item.path for item in crash_placeholders)
            if paths != tuple(sorted(paths, key=lambda item: item.encode("utf-8"))):
                raise ProtocolViolation("crash placeholders must be canonically sorted")
            if len(paths) != len(set(paths)):
                raise ProtocolViolation("crash placeholder paths must be unique")
            if missing and not crash_placeholders:
                raise ProtocolViolation(
                    "missing crashed/ineligible artifacts require explicit placeholders"
                )
            if set(paths) != missing:
                raise ProtocolViolation("crash placeholders must exactly cover missing required paths")
            if any(path not in payload_required for path in paths):
                raise ProtocolViolation("crash placeholder references a non-required path")

        evidence_required = (
            self.manifest.status is RunStatus.CRASHED or bool(crash_placeholders)
        )
        if evidence_required and crash_evidence is None:
            raise ProtocolViolation(
                "crashed or placeholder-bearing runs require typed crash evidence"
            )
        if crash_evidence is not None:
            _validate_crash_record_context(crash_evidence, self.manifest)
            mandatory = set(_MANDATORY_CRASH_EVIDENCE_PATHS)
            if not mandatory.issubset(actual):
                raise ProtocolViolation(
                    "process-audit/stdout/stderr must be retained real crash artifacts"
                )
            if mandatory & missing:
                raise ProtocolViolation("mandatory crash evidence cannot be placeholdered")
            if not payloads["raw/process-audit.jsonl"]:
                raise ProtocolViolation("raw/process-audit.jsonl cannot be an empty crash shell")
            for item in crash_placeholders:
                evidence_payload = payloads.get(item.evidence_path)
                if evidence_payload is None:
                    raise ProtocolViolation(
                        "crash placeholder evidence_path is not retained in the run"
                    )
                if not evidence_payload:
                    raise ProtocolViolation(
                        "crash placeholder cannot cite a zero-byte evidence artifact"
                    )
                if digest_bytes(evidence_payload) != item.evidence_digest:
                    raise ProtocolViolation(
                        "crash placeholder evidence_digest does not match retained bytes"
                    )

    def finalize(
        self,
        *,
        crash_placeholders: Iterable[CrashPlaceholder] = (),
        crash_evidence: CrashEvidenceRecord | None = None,
    ) -> Path:
        if self._closed:
            raise RuntimeError("run writer is closed")
        placeholders = tuple(crash_placeholders)
        if any(type(item) is not CrashPlaceholder for item in placeholders):
            raise ProtocolViolation("crash placeholders must be typed")
        if crash_evidence is not None and type(crash_evidence) is not CrashEvidenceRecord:
            raise ProtocolViolation("crash_evidence must be typed CrashEvidenceRecord")
        self._validate_layout_and_placeholders(placeholders, crash_evidence)
        placeholder_bytes: bytes | None = None
        if placeholders:
            placeholder_body = {
                "schema_version": CRASH_PLACEHOLDER_PROTOCOL,
                "run_id": self.run_id,
                "run_status": self.manifest.status.value,
                "placeholders": [item.to_wire() for item in placeholders],
            }
            placeholder_body["placeholder_digest"] = digest_json(placeholder_body)
            placeholder_bytes = canonical_json_bytes(placeholder_body)
            self._write_control("CRASH_PLACEHOLDERS.json", placeholder_bytes)

        if crash_evidence is not None:
            evidence_snapshot = _scan_tree(self.temporary)
            evidence_payloads = {
                path: payload for path, payload, _ in evidence_snapshot.files
            }
            evidence_rows = []
            for path in _MANDATORY_CRASH_EVIDENCE_PATHS:
                payload = evidence_payloads[path]
                evidence_rows.append(
                    {
                        "path": path,
                        "bytes": len(payload),
                        "sha256": digest_bytes(payload),
                    }
                )
            evidence_body = {
                "schema_version": CRASH_EVIDENCE_PROTOCOL,
                "run_id": self.run_id,
                "run_status": self.manifest.status.value,
                "record": crash_evidence.to_wire(),
                "retained_artifacts": evidence_rows,
                "placeholder_manifest_sha256": (
                    digest_bytes(placeholder_bytes)
                    if placeholder_bytes is not None
                    else None
                ),
                "placeholder_bindings_digest": digest_json(
                    {
                        "protocol": "ucm-crash-placeholder-bindings/1",
                        "placeholders": [item.to_wire() for item in placeholders],
                    }
                ),
            }
            evidence_body["crash_evidence_digest"] = digest_json(evidence_body)
            self._write_control(
                "CRASH_EVIDENCE.json", canonical_json_bytes(evidence_body)
            )

        base_snapshot = _scan_tree(self.temporary)
        base_rows = _rows_from_files(base_snapshot.files)
        self._write_control("checksums.sha256", _checksum_bytes(base_rows))

        inventory_snapshot = _scan_tree(self.temporary)
        inventory_rows = _rows_from_files(inventory_snapshot.files)
        inventory_paths = tuple(row["path"] for row in inventory_rows)
        expected_inventory_paths = {
            "RUN_MANIFEST.json",
            "checksums.sha256",
            *(
                set(required_payload_paths(self.manifest.run_class))
                - {item.path for item in placeholders}
            ),
        }
        if placeholders:
            expected_inventory_paths.add("CRASH_PLACEHOLDERS.json")
        if crash_evidence is not None:
            expected_inventory_paths.add("CRASH_EVIDENCE.json")
        if set(inventory_paths) != expected_inventory_paths:
            raise ProtocolViolation("live pre-publication tree differs from exact run layout")
        expected_dirs = _expected_directories(inventory_paths)
        if inventory_snapshot.directories != expected_dirs:
            raise ProtocolViolation("run contains extra or missing directories")
        tree_digest = digest_json(
            {
                "protocol": TREE_PROTOCOL,
                "directories": list(expected_dirs),
                "files": inventory_rows,
            }
        )
        manifest_bytes = (self.temporary / "RUN_MANIFEST.json").read_bytes()
        manifest_sha256 = digest_bytes(manifest_bytes)
        binding = _finalization_binding(self.manifest, manifest_sha256, tree_digest)
        inventory = {
            "schema_version": INVENTORY_PROTOCOL,
            "run_id": self.run_id,
            "results_root_digest": self.manifest.results_root_digest,
            "run_class": self.manifest.run_class.value,
            "run_status": self.manifest.status.value,
            "benchmark_id": self.manifest.benchmark_id,
            "benchmark_freeze_digest": self.manifest.benchmark_freeze_digest,
            "scope_digest": self.manifest.scope_digest,
            "hidden_corpus_digest": self.manifest.hidden_corpus_digest,
            "candidate_id": self.manifest.candidate_id,
            "candidate_source_seal": self.manifest.candidate_source_seal,
            "model_artifact_digest": self.manifest.model_artifact_digest,
            "manifest_sha256": manifest_sha256,
            "directories": list(expected_dirs),
            "files": inventory_rows,
            "tree_digest": tree_digest,
            "finalization_binding_digest": binding,
        }
        inventory_bytes = canonical_json_bytes(inventory)
        self._write_control("INVENTORY.json", inventory_bytes)
        checksums_bytes = (self.temporary / "checksums.sha256").read_bytes()
        finalized = {
            "schema_version": FINALIZED_PROTOCOL,
            "state": "FINALIZED",
            "run_id": self.run_id,
            "results_root_digest": self.manifest.results_root_digest,
            "run_class": self.manifest.run_class.value,
            "run_status": self.manifest.status.value,
            "benchmark_id": self.manifest.benchmark_id,
            "benchmark_freeze_digest": self.manifest.benchmark_freeze_digest,
            "scope_digest": self.manifest.scope_digest,
            "hidden_corpus_digest": self.manifest.hidden_corpus_digest,
            "candidate_id": self.manifest.candidate_id,
            "candidate_source_seal": self.manifest.candidate_source_seal,
            "model_artifact_digest": self.manifest.model_artifact_digest,
            "manifest_sha256": manifest_sha256,
            "inventory_sha256": digest_bytes(inventory_bytes),
            "checksums_sha256": digest_bytes(checksums_bytes),
            "tree_digest": tree_digest,
            "finalization_binding_digest": binding,
            "readonly_policy": "AUXILIARY_NOT_AUTHORITY",
            "external_worm_verified": False,
        }
        finalized_bytes = canonical_json_bytes(finalized)
        self._write_control("FINALIZED.json", finalized_bytes)

        seal_body = {
            "schema_version": LOCAL_SEAL_PROTOCOL,
            "state": "SEALED_LOCAL_ONLY",
            "run_id": self.run_id,
            "results_root_digest": self.manifest.results_root_digest,
            "run_class": self.manifest.run_class.value,
            "run_status": self.manifest.status.value,
            "benchmark_id": self.manifest.benchmark_id,
            "benchmark_freeze_digest": self.manifest.benchmark_freeze_digest,
            "scope_digest": self.manifest.scope_digest,
            "hidden_corpus_digest": self.manifest.hidden_corpus_digest,
            "candidate_id": self.manifest.candidate_id,
            "candidate_source_seal": self.manifest.candidate_source_seal,
            "model_artifact_digest": self.manifest.model_artifact_digest,
            "manifest_sha256": manifest_sha256,
            "inventory_sha256": digest_bytes(inventory_bytes),
            "finalized_sha256": digest_bytes(finalized_bytes),
            "checksums_sha256": digest_bytes(checksums_bytes),
            "tree_digest": tree_digest,
            "finalization_binding_digest": binding,
            "external_worm_verified": False,
        }
        seal_body["local_seal_digest"] = digest_json(seal_body)
        seal_bytes = canonical_json_bytes(seal_body)
        pending_seal = self.root / f".{self.run_id}.local-seal.pending"
        try:
            descriptor = os.open(
                pending_seal,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_BINARY", 0),
                0o400,
            )
            try:
                os.write(descriptor, seal_bytes)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if _entry_exists(self.target) or _entry_exists(self.local_seal):
                raise FileExistsError(f"run appeared before publish: {self.target}")
            self.temporary.rename(self.target)
            pending_seal.rename(self.local_seal)
            _apply_auxiliary_readonly(self.target)
            try:
                os.chmod(self.local_seal, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            except OSError:
                pass
            self.lock.unlink(missing_ok=True)
            self._closed = True
            return self.target
        except BaseException:
            pending_seal.unlink(missing_ok=True)
            # If target has already appeared, retain it and the lock as an
            # unmistakably incomplete publication rather than deleting evidence.
            if not _entry_exists(self.target):
                self.abort()
            raise

    def abort(self) -> None:
        if self._closed:
            return
        shutil.rmtree(self.temporary, ignore_errors=True)
        self.lock.unlink(missing_ok=True)
        self._closed = True

    def __enter__(self) -> "AppendOnlyRunWriter":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None:
            self.abort()
        elif not self._closed:
            self.abort()
        return False


def _apply_auxiliary_readonly(root: Path) -> None:
    # Read-only is deliberately not checked as an integrity precondition.  It
    # narrows accidental edits but an owner can chmod it back, so live rehash +
    # the expected local seal remain the actual portable checks.
    snapshot = _scan_tree(root)
    for path, _, _ in snapshot.files:
        try:
            os.chmod(root / _safe_relative(path), stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError:
            pass
    for relative in reversed(snapshot.directories):
        try:
            os.chmod(root / _safe_relative(relative), stat.S_IRUSR | stat.S_IXUSR)
        except OSError:
            pass
    try:
        os.chmod(root, stat.S_IRUSR | stat.S_IXUSR)
    except OSError:
        pass


def _decode_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} is not valid JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be a JSON object")
    if canonical_json_bytes(value) != payload:
        raise ProtocolViolation(f"{label} is not canonical JSON bytes")
    return value


def _parse_inventory(payload: bytes) -> dict[str, Any]:
    expected = frozenset(
        {
            "schema_version",
            "run_id",
            "results_root_digest",
            "run_class",
            "run_status",
            "benchmark_id",
            "benchmark_freeze_digest",
            "scope_digest",
            "hidden_corpus_digest",
            "candidate_id",
            "candidate_source_seal",
            "model_artifact_digest",
            "manifest_sha256",
            "directories",
            "files",
            "tree_digest",
            "finalization_binding_digest",
        }
    )
    body = _exact_keys(_decode_json(payload, "INVENTORY.json"), expected, "inventory")
    if body["schema_version"] != INVENTORY_PROTOCOL:
        raise ProtocolViolation("wrong inventory schema_version")
    if type(body["directories"]) is not list or any(type(item) is not str for item in body["directories"]):
        raise ProtocolViolation("inventory directories must be exact strings")
    if type(body["files"]) is not list:
        raise ProtocolViolation("inventory files must be a list")
    rows: list[dict[str, Any]] = []
    for item in body["files"]:
        row = _exact_keys(item, frozenset({"path", "bytes", "sha256"}), "inventory row")
        path = _safe_relative(row["path"]).as_posix()
        if type(row["bytes"]) is not int or row["bytes"] < 0:
            raise ProtocolViolation("inventory byte count must be non-negative int")
        _digest(row["sha256"], "inventory sha256")
        rows.append({"path": path, "bytes": row["bytes"], "sha256": row["sha256"]})
    paths = tuple(row["path"] for row in rows)
    if paths != tuple(sorted(paths, key=lambda item: item.encode("utf-8"))) or len(paths) != len(set(paths)):
        raise ProtocolViolation("inventory files must be unique and canonically sorted")
    directories = tuple(body["directories"])
    if directories != tuple(sorted(directories, key=lambda item: item.encode("utf-8"))) or len(directories) != len(set(directories)):
        raise ProtocolViolation("inventory directories must be unique and canonically sorted")
    for directory in directories:
        _safe_relative(directory)
    if directories != _expected_directories(paths):
        raise ProtocolViolation("inventory directory closure does not match its files")
    body["files"] = rows
    return body


def _parse_placeholders(payload: bytes, manifest: RunManifest) -> tuple[CrashPlaceholder, ...]:
    body = _exact_keys(
        _decode_json(payload, "CRASH_PLACEHOLDERS.json"),
        frozenset({"schema_version", "run_id", "run_status", "placeholders", "placeholder_digest"}),
        "crash placeholder manifest",
    )
    if body["schema_version"] != CRASH_PLACEHOLDER_PROTOCOL:
        raise ProtocolViolation("wrong crash placeholder schema")
    claimed = _digest(body["placeholder_digest"], "placeholder_digest")
    unsigned = {key: item for key, item in body.items() if key != "placeholder_digest"}
    if digest_json(unsigned) != claimed:
        raise ProtocolViolation("crash placeholder self-digest mismatch")
    if body["run_id"] != manifest.run_id or body["run_status"] != manifest.status.value:
        raise ProtocolViolation("crash placeholders are bound to a different run")
    if type(body["placeholders"]) is not list:
        raise ProtocolViolation("placeholders must be a list")
    result = tuple(CrashPlaceholder.from_wire(item) for item in body["placeholders"])
    paths = tuple(item.path for item in result)
    if paths != tuple(sorted(paths, key=lambda item: item.encode("utf-8"))) or len(paths) != len(set(paths)):
        raise ProtocolViolation("crash placeholders must be unique and canonically sorted")
    return result


def _parse_crash_evidence(
    payload: bytes,
    *,
    manifest: RunManifest,
    placeholders: tuple[CrashPlaceholder, ...],
    retained_payloads: dict[str, bytes],
    placeholder_manifest_bytes: bytes | None,
) -> CrashEvidenceRecord:
    body = _exact_keys(
        _decode_json(payload, "CRASH_EVIDENCE.json"),
        frozenset(
            {
                "schema_version",
                "run_id",
                "run_status",
                "record",
                "retained_artifacts",
                "placeholder_manifest_sha256",
                "placeholder_bindings_digest",
                "crash_evidence_digest",
            }
        ),
        "crash evidence control",
    )
    if body["schema_version"] != CRASH_EVIDENCE_PROTOCOL:
        raise ProtocolViolation("wrong crash evidence schema")
    claimed = _digest(body["crash_evidence_digest"], "crash_evidence_digest")
    unsigned = {
        key: value for key, value in body.items() if key != "crash_evidence_digest"
    }
    if digest_json(unsigned) != claimed:
        raise ProtocolViolation("crash evidence self-digest mismatch")
    if body["run_id"] != manifest.run_id or body["run_status"] != manifest.status.value:
        raise ProtocolViolation("crash evidence is bound to a different run")
    record = CrashEvidenceRecord.from_wire(body["record"])
    _validate_crash_record_context(record, manifest)
    expected_placeholder_sha256 = (
        digest_bytes(placeholder_manifest_bytes)
        if placeholder_manifest_bytes is not None
        else None
    )
    if body["placeholder_manifest_sha256"] != expected_placeholder_sha256:
        raise ProtocolViolation("crash evidence placeholder manifest binding mismatch")
    expected_bindings_digest = digest_json(
        {
            "protocol": "ucm-crash-placeholder-bindings/1",
            "placeholders": [item.to_wire() for item in placeholders],
        }
    )
    if body["placeholder_bindings_digest"] != expected_bindings_digest:
        raise ProtocolViolation("crash evidence placeholder binding digest mismatch")
    if type(body["retained_artifacts"]) is not list:
        raise ProtocolViolation("crash evidence retained_artifacts must be a list")
    expected_rows: list[dict[str, Any]] = []
    for path in _MANDATORY_CRASH_EVIDENCE_PATHS:
        if path not in retained_payloads:
            raise ProtocolViolation(
                "process-audit/stdout/stderr must be retained real crash artifacts"
            )
        artifact_payload = retained_payloads[path]
        expected_rows.append(
            {
                "path": path,
                "bytes": len(artifact_payload),
                "sha256": digest_bytes(artifact_payload),
            }
        )
    if body["retained_artifacts"] != expected_rows:
        raise ProtocolViolation("crash evidence retained artifact rows differ from live bytes")
    if not retained_payloads["raw/process-audit.jsonl"]:
        raise ProtocolViolation("raw/process-audit.jsonl cannot be an empty crash shell")
    for item in placeholders:
        evidence_payload = retained_payloads.get(item.evidence_path)
        if evidence_payload is None or not evidence_payload:
            raise ProtocolViolation(
                "crash placeholder evidence must resolve to a non-empty retained artifact"
            )
        if digest_bytes(evidence_payload) != item.evidence_digest:
            raise ProtocolViolation(
                "crash placeholder evidence_digest differs from retained artifact"
            )
    return record


def verify_run_bundle(
    root_or_bundle: Path,
    run_id: str | None = None,
    *,
    expected_manifest: RunManifest,
) -> RunVerificationReceipt:
    """Rehash and verify one publication against an out-of-band typed manifest.

    ``root_or_bundle`` may be either the results root (with ``run_id`` supplied)
    or the bundle path (with ``run_id=None``).  The expected manifest is
    mandatory: trusting a manifest read from the same mutable bundle would not
    authenticate candidate/benchmark/scope identity.
    """

    if not isinstance(root_or_bundle, Path):
        raise ProtocolViolation("verification path must be pathlib.Path")
    if type(expected_manifest) is not RunManifest:
        raise ProtocolViolation("expected_manifest must be typed RunManifest")
    if run_id is None:
        bundle = root_or_bundle
        root = bundle.parent
        actual_run_id = bundle.name
    else:
        validate_run_id(run_id)
        root = root_or_bundle
        bundle = root / run_id
        actual_run_id = run_id
    validate_run_id(actual_run_id)
    _assert_no_reparse_ancestors(root, "results root")
    _assert_plain_directory(root, "results root")
    if actual_run_id != expected_manifest.run_id:
        raise ProtocolViolation("verification run_id differs from expected manifest")
    actual_root_digest = results_root_digest(root)
    if actual_root_digest != expected_manifest.results_root_digest:
        raise ProtocolViolation("verification root differs from expected manifest")
    if expected_manifest.status is RunStatus.RUNNING:
        raise ProtocolViolation("a finalized bundle cannot bind a running manifest")
    required_payload_paths(expected_manifest.run_class)

    snapshot = _scan_tree(bundle)
    file_map = {path: (payload, info) for path, payload, info in snapshot.files}
    if len(file_map) != len(snapshot.files):
        raise ProtocolViolation("duplicate filesystem paths in bundle")
    for control in ("RUN_MANIFEST.json", "checksums.sha256", "INVENTORY.json", "FINALIZED.json"):
        if control not in file_map:
            raise ProtocolViolation(f"bundle is missing {control}")

    manifest_bytes = file_map["RUN_MANIFEST.json"][0]
    manifest = RunManifest.from_wire(_decode_json(manifest_bytes, "RUN_MANIFEST.json"))
    if manifest != expected_manifest or manifest.digest != expected_manifest.digest:
        raise ProtocolViolation("bundle manifest differs from out-of-band expected manifest")
    manifest_sha256 = digest_bytes(manifest_bytes)
    _validate_candidate_artifact_bindings(
        manifest, {path: payload for path, (payload, _) in file_map.items()}
    )

    inventory_bytes = file_map["INVENTORY.json"][0]
    inventory = _parse_inventory(inventory_bytes)
    inventory_rows = inventory["files"]
    inventory_paths = tuple(row["path"] for row in inventory_rows)
    expected_tree_files = set(inventory_paths) | {"INVENTORY.json", "FINALIZED.json"}
    if set(file_map) != expected_tree_files:
        missing = sorted(expected_tree_files - set(file_map))
        extra = sorted(set(file_map) - expected_tree_files)
        raise ProtocolViolation(f"exact tree differs; missing={missing!r}, extra={extra!r}")
    if snapshot.directories != tuple(inventory["directories"]):
        raise ProtocolViolation("live directory tree differs from inventory")

    live_rows = _rows_from_files(snapshot.files)
    if live_rows != inventory_rows:
        raise ProtocolViolation("live bundle bytes differ from inventory")
    live_tree_digest = digest_json(
        {
            "protocol": TREE_PROTOCOL,
            "directories": list(snapshot.directories),
            "files": live_rows,
        }
    )
    if inventory["tree_digest"] != live_tree_digest:
        raise ProtocolViolation("inventory tree_digest mismatch")

    required = set(required_payload_paths(manifest.run_class))
    actual_payload = set(inventory_paths) & required
    unexpected_payload = set(inventory_paths) - required - {
        "RUN_MANIFEST.json",
        "checksums.sha256",
        "CRASH_PLACEHOLDERS.json",
        "CRASH_EVIDENCE.json",
    }
    if unexpected_payload:
        raise ProtocolViolation(f"inventory has non-layout files: {sorted(unexpected_payload)!r}")
    missing_payload = required - actual_payload
    placeholders: tuple[CrashPlaceholder, ...] = ()
    placeholder_manifest_bytes: bytes | None = None
    if manifest.status is RunStatus.FINALIZED:
        if (
            missing_payload
            or "CRASH_PLACEHOLDERS.json" in file_map
            or "CRASH_EVIDENCE.json" in file_map
        ):
            raise ProtocolViolation("finalized run does not have the exact complete layout")
    else:
        if manifest.status not in {RunStatus.CRASHED, RunStatus.INELIGIBLE}:
            raise ProtocolViolation("invalid published run status")
        if missing_payload:
            if "CRASH_PLACEHOLDERS.json" not in file_map:
                raise ProtocolViolation("crashed/ineligible run lacks explicit placeholders")
            placeholder_manifest_bytes = file_map["CRASH_PLACEHOLDERS.json"][0]
            placeholders = _parse_placeholders(placeholder_manifest_bytes, manifest)
            if set(item.path for item in placeholders) != missing_payload:
                raise ProtocolViolation("crash placeholders do not exactly cover missing layout")
        elif "CRASH_PLACEHOLDERS.json" in file_map:
            raise ProtocolViolation("complete crashed/ineligible layout cannot add placeholders")
        evidence_required = manifest.status is RunStatus.CRASHED or bool(placeholders)
        if evidence_required and "CRASH_EVIDENCE.json" not in file_map:
            raise ProtocolViolation("crashed/placeholder run lacks typed crash evidence")
        if "CRASH_EVIDENCE.json" in file_map:
            _parse_crash_evidence(
                file_map["CRASH_EVIDENCE.json"][0],
                manifest=manifest,
                placeholders=placeholders,
                retained_payloads={
                    path: payload for path, (payload, _) in file_map.items()
                },
                placeholder_manifest_bytes=placeholder_manifest_bytes,
            )

    base_rows = [
        row
        for row in inventory_rows
        if row["path"] != "checksums.sha256"
    ]
    checksums_bytes = file_map["checksums.sha256"][0]
    if checksums_bytes != _checksum_bytes(base_rows):
        raise ProtocolViolation("checksums.sha256 is not the canonical live checksum set")

    binding = _finalization_binding(manifest, manifest_sha256, live_tree_digest)
    identity = {
        "run_id": manifest.run_id,
        "results_root_digest": manifest.results_root_digest,
        "run_class": manifest.run_class.value,
        "run_status": manifest.status.value,
        "benchmark_id": manifest.benchmark_id,
        "benchmark_freeze_digest": manifest.benchmark_freeze_digest,
        "scope_digest": manifest.scope_digest,
        "hidden_corpus_digest": manifest.hidden_corpus_digest,
        "candidate_id": manifest.candidate_id,
        "candidate_source_seal": manifest.candidate_source_seal,
        "model_artifact_digest": manifest.model_artifact_digest,
    }
    for key, expected in {
        **identity,
        "manifest_sha256": manifest_sha256,
        "tree_digest": live_tree_digest,
        "finalization_binding_digest": binding,
    }.items():
        if inventory.get(key) != expected:
            raise ProtocolViolation(f"inventory {key} binding mismatch")

    finalized_bytes = file_map["FINALIZED.json"][0]
    finalized_expected_keys = frozenset(
        {
            "schema_version",
            "state",
            *identity.keys(),
            "manifest_sha256",
            "inventory_sha256",
            "checksums_sha256",
            "tree_digest",
            "finalization_binding_digest",
            "readonly_policy",
            "external_worm_verified",
        }
    )
    finalized = _exact_keys(
        _decode_json(finalized_bytes, "FINALIZED.json"),
        finalized_expected_keys,
        "finalized marker",
    )
    finalized_bindings = {
        "schema_version": FINALIZED_PROTOCOL,
        "state": "FINALIZED",
        **identity,
        "manifest_sha256": manifest_sha256,
        "inventory_sha256": digest_bytes(inventory_bytes),
        "checksums_sha256": digest_bytes(checksums_bytes),
        "tree_digest": live_tree_digest,
        "finalization_binding_digest": binding,
        "readonly_policy": "AUXILIARY_NOT_AUTHORITY",
        "external_worm_verified": False,
    }
    if finalized != finalized_bindings:
        raise ProtocolViolation("FINALIZED.json is not mutually bound to the live inventory")

    seal_path = _local_seal_path(root, actual_run_id)
    seal_info = _assert_plain_file(seal_path, "local sibling seal")
    seal_bytes = seal_path.read_bytes()
    seal_after = _assert_plain_file(seal_path, "local sibling seal")
    if (
        seal_info.st_dev,
        seal_info.st_ino,
        seal_info.st_size,
        getattr(seal_info, "st_mtime_ns", None),
    ) != (
        seal_after.st_dev,
        seal_after.st_ino,
        seal_after.st_size,
        getattr(seal_after, "st_mtime_ns", None),
    ):
        raise ProtocolViolation("local sibling seal changed during verification")
    seal_expected_keys = frozenset(
        {
            "schema_version",
            "state",
            *identity.keys(),
            "manifest_sha256",
            "inventory_sha256",
            "finalized_sha256",
            "checksums_sha256",
            "tree_digest",
            "finalization_binding_digest",
            "external_worm_verified",
            "local_seal_digest",
        }
    )
    seal = _exact_keys(
        _decode_json(seal_bytes, "local sibling seal"), seal_expected_keys, "local seal"
    )
    claimed_seal_digest = _digest(seal["local_seal_digest"], "local_seal_digest")
    unsigned_seal = {key: item for key, item in seal.items() if key != "local_seal_digest"}
    if digest_json(unsigned_seal) != claimed_seal_digest:
        raise ProtocolViolation("local sibling seal self-digest mismatch")
    expected_seal = {
        "schema_version": LOCAL_SEAL_PROTOCOL,
        "state": "SEALED_LOCAL_ONLY",
        **identity,
        "manifest_sha256": manifest_sha256,
        "inventory_sha256": digest_bytes(inventory_bytes),
        "finalized_sha256": digest_bytes(finalized_bytes),
        "checksums_sha256": digest_bytes(checksums_bytes),
        "tree_digest": live_tree_digest,
        "finalization_binding_digest": binding,
        "external_worm_verified": False,
        "local_seal_digest": claimed_seal_digest,
    }
    if seal != expected_seal:
        raise ProtocolViolation("local sibling seal differs from the live finalization")

    readonly_all = all(
        not bool(info.st_mode & stat.S_IWUSR) for _, _, info in snapshot.files
    ) and not bool(seal_after.st_mode & stat.S_IWUSR)
    receipt_body = {
        "schema_version": VERIFICATION_RECEIPT_PROTOCOL,
        "status": PRE_FREEZE_STATUS,
        "blockers": [INCOMPLETE_CODE],
        "freeze_grade_evidence": False,
        "benchmark_freeze_eligible": False,
        "custody_assurance": "LOCAL_REHASH_AND_SIBLING_SEAL_ONLY",
        "external_worm_verified": False,
        "race_free_kernel_custody": False,
        "root_binding_scope": "LOCAL_ABSOLUTE_PATH_ONLY",
        "absolute_root_binding_portable": False,
        "filesystem_link_checks": "LSTAT_SYMLINK_REPARSE_AND_NLINK",
        "filesystem_link_checks_race_free": False,
        "xattrs_acl_custody_verified": False,
        "windows_alternate_data_streams_checked": os.name == "nt",
        "readonly_is_authority": False,
        **identity,
        "manifest_sha256": manifest_sha256,
        "inventory_sha256": digest_bytes(inventory_bytes),
        "finalized_sha256": digest_bytes(finalized_bytes),
        "local_seal_sha256": digest_bytes(seal_bytes),
        "tree_digest": live_tree_digest,
        "verified_file_count": len(snapshot.files),
        "readonly_all_observed": readonly_all,
    }
    receipt_digest = digest_json(receipt_body)
    return RunVerificationReceipt(
        run_id=manifest.run_id,
        results_root_digest=manifest.results_root_digest,
        run_class=manifest.run_class,
        run_status=manifest.status,
        benchmark_id=manifest.benchmark_id,
        benchmark_freeze_digest=manifest.benchmark_freeze_digest,
        scope_digest=manifest.scope_digest,
        hidden_corpus_digest=manifest.hidden_corpus_digest,
        candidate_id=manifest.candidate_id,
        candidate_source_seal=manifest.candidate_source_seal,
        model_artifact_digest=manifest.model_artifact_digest,
        manifest_sha256=manifest_sha256,
        inventory_sha256=digest_bytes(inventory_bytes),
        finalized_sha256=digest_bytes(finalized_bytes),
        local_seal_sha256=digest_bytes(seal_bytes),
        tree_digest=live_tree_digest,
        verified_file_count=len(snapshot.files),
        readonly_all_observed=readonly_all,
        windows_alternate_data_streams_checked=os.name == "nt",
        receipt_digest=receipt_digest,
    )
