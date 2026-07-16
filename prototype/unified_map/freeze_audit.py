"""Fail-closed collection of benchmark-freeze evidence.

``freeze.py`` intentionally only assembles an all-PASS authorization.  This
module is the evidence boundary immediately before that assembler: it accepts
canonical, structured *execution* artifacts and derives PASS/FAIL/INCOMPLETE
itself.  A file name, a pytest test name, or a producer-supplied ``"PASS"``
string is never evidence.

Each axis artifact is bound to one benchmark id, source revision, semantic
scope digest, an exact evidence contract, the exact bytes of its producer
sources, and one or more raw run artifacts.  Required measurements have
collector-owned predicates and exact coverage.  Missing, stale, malformed, or
digest-unbound evidence is INCOMPLETE; a well-formed execution whose measured
predicate is false is FAIL.

The collector does not claim that the current repository is frozen.  The
default paths are deliberately absent until their corresponding executable
evidence has actually been materialized.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
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
from .freeze import (
    REQUIRED_FREEZE_EVIDENCE_AXES,
    FreezeAxisEvidence,
    FreezeEvidenceStatus,
)


AXIS_EVIDENCE_PROTOCOL = "ucm-freeze-axis-execution/1"
AUDIT_PROTOCOL = "ucm-freeze-evidence-audit/1"
CONTRACT_PROTOCOL = "ucm-freeze-axis-contract/1"
PLACEHOLDER_PROTOCOL = "ucm-freeze-axis-placeholder/1"

_EVIDENCE_PREFIX = "research/unified_map/"
_PRODUCER_PREFIX = "prototype/unified_map/"
_ISOLATED_PREFIXES = (
    "research/unified_map/",
    "prototype/unified_map/",
    "tests/unified_map/",
    "results/unified_map/",
)
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REVISION_RE = re.compile(r"[0-9a-f]{7,64}\Z")
_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    return value


def _revision(value: object) -> str:
    if type(value) is not str or _REVISION_RE.fullmatch(value) is None:
        raise ProtocolViolation("source_revision must be 7--64 lowercase hex digits")
    return value


def _relative_path(
    value: object,
    *,
    label: str,
    prefixes: tuple[str, ...],
) -> str:
    if type(value) is not str or not value or "\\" in value or value.startswith("/"):
        raise ProtocolViolation(f"{label} must be a relative POSIX path")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or not value.startswith(prefixes)
    ):
        raise ProtocolViolation(f"{label} is outside the isolated UCM roots")
    return pure.as_posix()


def _canonical_tuple(values: Iterable[str], label: str) -> tuple[str, ...]:
    result = tuple(values)
    if any(type(value) is not str or not value for value in result):
        raise ProtocolViolation(f"{label} must contain non-empty exact strings")
    ordered = tuple(sorted(result, key=lambda item: item.encode("utf-8")))
    if result != ordered or len(result) != len(set(result)):
        raise ProtocolViolation(f"{label} must be unique and canonically sorted")
    return result


def _wire_value(value: Any) -> Any:
    if type(value) is tuple:
        return list(value)
    validate_json_like(value)
    return value


class EvidencePredicate(str, Enum):
    """Collector-owned predicates; artifacts provide observations, not verdicts."""

    EXACT = "exact"
    EXACT_SET = "exact_set"
    EMPTY = "empty"
    NON_EMPTY = "non_empty"
    INTEGER_AT_LEAST = "integer_at_least"
    NUMBER_AT_MOST = "number_at_most"
    NO_OVERLAP = "no_overlap"
    VERIFIED_ARTIFACT_DIGEST = "verified_artifact_digest"
    VERIFIED_ARTIFACT_DIGESTS_AT_LEAST = "verified_artifact_digests_at_least"
    TARGET_BENCHMARK = "target_benchmark"
    TARGET_REVISION = "target_revision"
    TARGET_SCOPE_DIGEST = "target_scope_digest"


@dataclass(frozen=True, slots=True)
class CheckRequirement:
    check_id: str
    predicate: EvidencePredicate
    expected: Any = None
    extractor_id: str | None = None
    false_status: FreezeEvidenceStatus = FreezeEvidenceStatus.FAIL

    def __post_init__(self) -> None:
        _name(self.check_id, "check_id")
        if type(self.predicate) is not EvidencePredicate:
            raise ProtocolViolation("check predicate must be typed")
        if self.extractor_id is not None:
            _name(self.extractor_id, "check extractor_id")
        if self.false_status not in {
            FreezeEvidenceStatus.FAIL,
            FreezeEvidenceStatus.INCOMPLETE,
        }:
            raise ProtocolViolation("false_status must be FAIL or INCOMPLETE")
        if self.predicate is EvidencePredicate.EXACT:
            validate_json_like(self.expected, path="$.expected")
        elif self.predicate is EvidencePredicate.EXACT_SET:
            if type(self.expected) is not tuple:
                raise ProtocolViolation("exact_set expected value must be tuple[str, ...]")
            _canonical_tuple(self.expected, "exact_set expected value")
        elif self.predicate in {
            EvidencePredicate.INTEGER_AT_LEAST,
            EvidencePredicate.VERIFIED_ARTIFACT_DIGESTS_AT_LEAST,
        }:
            if type(self.expected) is not int or self.expected < 0:
                raise ProtocolViolation("count predicate expected value must be non-negative int")
        elif self.predicate is EvidencePredicate.NUMBER_AT_MOST:
            if (
                type(self.expected) not in {int, float}
                or not math.isfinite(float(self.expected))
            ):
                raise ProtocolViolation("numeric predicate expected value must be finite")
        elif self.expected is not None:
            raise ProtocolViolation("this predicate does not accept an expected value")

    def to_wire(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "predicate": self.predicate.value,
            "expected": _wire_value(self.expected),
            "extractor_id": self.extractor_id,
            "false_status": self.false_status.value,
        }


@dataclass(frozen=True, slots=True)
class AxisEvidenceContract:
    axis: str
    artifact_path: str
    authority: str
    producer_id: str
    producer_source_paths: tuple[str, ...]
    requirements: tuple[CheckRequirement, ...]

    def __post_init__(self) -> None:
        _name(self.axis, "evidence axis")
        if self.axis not in REQUIRED_FREEZE_EVIDENCE_AXES:
            raise ProtocolViolation("unknown freeze evidence axis")
        _relative_path(
            self.artifact_path,
            label="axis artifact_path",
            prefixes=(_EVIDENCE_PREFIX,),
        )
        if not self.artifact_path.endswith(".json"):
            raise ProtocolViolation("axis artifact_path must end in .json")
        _name(self.authority, "axis authority")
        _name(self.producer_id, "producer_id")
        _canonical_tuple(self.producer_source_paths, "producer source paths")
        if not self.producer_source_paths:
            raise ProtocolViolation("axis contract must bind at least one producer source")
        for path in self.producer_source_paths:
            _relative_path(
                path,
                label="producer source path",
                prefixes=(_PRODUCER_PREFIX,),
            )
        if type(self.requirements) is not tuple or not self.requirements:
            raise ProtocolViolation("axis contract must contain required checks")
        if any(type(item) is not CheckRequirement for item in self.requirements):
            raise ProtocolViolation("axis contract contains an untyped requirement")
        ids = tuple(item.check_id for item in self.requirements)
        if ids != tuple(sorted(ids, key=lambda item: item.encode("utf-8"))):
            raise ProtocolViolation("axis requirements must be canonically sorted")
        if len(ids) != len(set(ids)):
            raise ProtocolViolation("axis requirements contain duplicate check ids")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": CONTRACT_PROTOCOL,
            "axis": self.axis,
            "artifact_path": self.artifact_path,
            "authority": self.authority,
            "producer_id": self.producer_id,
            "producer_source_paths": list(self.producer_source_paths),
            "requirements": [item.to_wire() for item in self.requirements],
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


@dataclass(frozen=True, slots=True)
class AuditBlocker:
    code: str
    detail: str

    def __post_init__(self) -> None:
        _name(self.code, "audit blocker code")
        _name(self.detail, "audit blocker detail")

    def to_wire(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class AxisAuditResult:
    axis: str
    status: FreezeEvidenceStatus
    artifact_path: str
    artifact_digest: str
    contract_digest: str
    required_checks: tuple[str, ...]
    observed_checks: tuple[str, ...]
    blockers: tuple[AuditBlocker, ...]

    def __post_init__(self) -> None:
        if self.axis not in REQUIRED_FREEZE_EVIDENCE_AXES:
            raise ProtocolViolation("axis audit has an unknown axis")
        if type(self.status) is not FreezeEvidenceStatus:
            raise ProtocolViolation("axis audit status must be typed")
        _relative_path(
            self.artifact_path,
            label="axis audit artifact_path",
            prefixes=(_EVIDENCE_PREFIX,),
        )
        _digest(self.artifact_digest, "axis audit artifact_digest")
        _digest(self.contract_digest, "axis audit contract_digest")
        _canonical_tuple(self.required_checks, "required checks")
        _canonical_tuple(self.observed_checks, "observed checks")
        if type(self.blockers) is not tuple or any(
            type(item) is not AuditBlocker for item in self.blockers
        ):
            raise ProtocolViolation("axis audit blockers must be typed")
        if self.status is FreezeEvidenceStatus.PASS and self.blockers:
            raise ProtocolViolation("PASS axis audit cannot contain blockers")

    @property
    def detail(self) -> str:
        if not self.blockers:
            return (
                f"validated {len(self.observed_checks)} structured execution checks "
                "with exact bindings and coverage"
            )
        return f"{self.blockers[0].code}: {self.blockers[0].detail}"

    def to_freeze_evidence(self) -> FreezeAxisEvidence:
        return FreezeAxisEvidence(
            axis=self.axis,
            status=self.status,
            artifact_digest=self.artifact_digest,
            detail=self.detail,
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "status": self.status.value,
            "artifact_path": self.artifact_path,
            "artifact_digest": self.artifact_digest,
            "contract_digest": self.contract_digest,
            "required_checks": list(self.required_checks),
            "observed_checks": list(self.observed_checks),
            "blockers": [item.to_wire() for item in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class FreezeEvidenceAudit:
    benchmark_id: str
    source_revision: str
    scope_digest: str
    axes: tuple[AxisAuditResult, ...]

    def __post_init__(self) -> None:
        _name(self.benchmark_id, "benchmark_id")
        _revision(self.source_revision)
        _digest(self.scope_digest, "scope_digest")
        if type(self.axes) is not tuple or any(
            type(item) is not AxisAuditResult for item in self.axes
        ):
            raise ProtocolViolation("freeze audit axes must be typed")
        if tuple(item.axis for item in self.axes) != REQUIRED_FREEZE_EVIDENCE_AXES:
            raise ProtocolViolation("freeze audit must cover all axes in canonical order")

    @property
    def status(self) -> FreezeEvidenceStatus:
        if any(item.status is FreezeEvidenceStatus.FAIL for item in self.axes):
            return FreezeEvidenceStatus.FAIL
        if any(item.status is FreezeEvidenceStatus.INCOMPLETE for item in self.axes):
            return FreezeEvidenceStatus.INCOMPLETE
        return FreezeEvidenceStatus.PASS

    @property
    def evidence(self) -> tuple[FreezeAxisEvidence, ...]:
        return tuple(item.to_freeze_evidence() for item in self.axes)

    def to_wire(self) -> dict[str, Any]:
        body = {
            "protocol": AUDIT_PROTOCOL,
            "benchmark_id": self.benchmark_id,
            "source_revision": self.source_revision,
            "scope_digest": self.scope_digest,
            "status": self.status.value,
            "axes": [item.to_wire() for item in self.axes],
        }
        body["audit_digest"] = digest_json(body)
        return body

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


def _resolved_file(repo_root: Path, relative: str) -> Path:
    root = repo_root.resolve()
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise ProtocolViolation("evidence path escapes repository root") from exc
    return path


def _placeholder_digest(
    contract: AxisEvidenceContract,
    *,
    benchmark_id: str,
    source_revision: str,
    scope_digest: str,
    blockers: tuple[AuditBlocker, ...],
) -> str:
    return digest_json(
        {
            "protocol": PLACEHOLDER_PROTOCOL,
            "axis": contract.axis,
            "artifact_path": contract.artifact_path,
            "benchmark_id": benchmark_id,
            "source_revision": source_revision,
            "scope_digest": scope_digest,
            "contract_digest": contract.digest,
            "blockers": [item.to_wire() for item in blockers],
        }
    )


def _result(
    contract: AxisEvidenceContract,
    *,
    status: FreezeEvidenceStatus,
    benchmark_id: str,
    source_revision: str,
    scope_digest: str,
    blockers: Iterable[AuditBlocker] = (),
    observed_checks: Iterable[str] = (),
    artifact_digest: str | None = None,
) -> AxisAuditResult:
    blocker_rows = tuple(blockers)
    observed = tuple(sorted(set(observed_checks), key=lambda item: item.encode("utf-8")))
    if artifact_digest is None:
        artifact_digest = _placeholder_digest(
            contract,
            benchmark_id=benchmark_id,
            source_revision=source_revision,
            scope_digest=scope_digest,
            blockers=blocker_rows,
        )
    return AxisAuditResult(
        axis=contract.axis,
        status=status,
        artifact_path=contract.artifact_path,
        artifact_digest=artifact_digest,
        contract_digest=contract.digest,
        required_checks=tuple(item.check_id for item in contract.requirements),
        observed_checks=observed,
        blockers=blocker_rows,
    )


def _closed_object(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ProtocolViolation(f"{label} must be a closed object with keys {sorted(keys)!r}")
    return value


def _parse_time(value: object, label: str) -> datetime:
    if type(value) is not str or _UTC_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be whole-second UTC RFC3339")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    return parsed


@dataclass(frozen=True, slots=True)
class _VerifiedFile:
    """One immutable byte snapshot bound to its declared path and digest."""

    path: str
    digest: str
    payload: bytes


def _verify_file_row(
    repo_root: Path,
    row: Any,
    *,
    allowed_prefixes: tuple[str, ...],
    label: str,
) -> _VerifiedFile:
    item = _closed_object(row, frozenset({"path", "bytes", "sha256"}), label)
    relative = _relative_path(
        item["path"],
        label=f"{label} path",
        prefixes=allowed_prefixes,
    )
    if type(item["bytes"]) is not int or item["bytes"] < 0:
        raise ProtocolViolation(f"{label} bytes must be non-negative int")
    declared_digest = _digest(item["sha256"], f"{label} sha256")
    path = _resolved_file(repo_root, relative)
    if path.is_symlink() or not path.is_file():
        raise ProtocolViolation(f"{label} path is not a regular file: {relative}")
    payload = path.read_bytes()
    if len(payload) != item["bytes"] or digest_bytes(payload) != declared_digest:
        raise ProtocolViolation(f"{label} byte binding mismatch: {relative}")
    return _VerifiedFile(path=relative, digest=declared_digest, payload=payload)


def _exact_string_list(value: Any, label: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise ProtocolViolation(f"{label} must be a list of strings")
    result = tuple(value)
    return _canonical_tuple(result, label)


def _evaluate(
    requirement: CheckRequirement,
    observed: Any,
    *,
    verified_raw_digests: frozenset[str],
    benchmark_id: str,
    source_revision: str,
    scope_digest: str,
) -> bool:
    predicate = requirement.predicate
    if predicate is EvidencePredicate.EXACT:
        validate_json_like(observed, path=f"$.measurements.{requirement.check_id}")
        return observed == requirement.expected
    if predicate is EvidencePredicate.EXACT_SET:
        return _exact_string_list(observed, requirement.check_id) == requirement.expected
    if predicate is EvidencePredicate.EMPTY:
        if type(observed) is not list:
            raise ProtocolViolation(f"{requirement.check_id} must be a list")
        validate_json_like(observed)
        return not observed
    if predicate is EvidencePredicate.NON_EMPTY:
        if type(observed) is not list:
            raise ProtocolViolation(f"{requirement.check_id} must be a list")
        validate_json_like(observed)
        return bool(observed)
    if predicate is EvidencePredicate.INTEGER_AT_LEAST:
        if type(observed) is not int or observed < 0:
            raise ProtocolViolation(f"{requirement.check_id} must be non-negative int")
        return observed >= requirement.expected
    if predicate is EvidencePredicate.NUMBER_AT_MOST:
        if type(observed) not in {int, float} or not math.isfinite(float(observed)):
            raise ProtocolViolation(f"{requirement.check_id} must be finite number")
        return float(observed) <= float(requirement.expected)
    if predicate is EvidencePredicate.NO_OVERLAP:
        item = _closed_object(
            observed,
            frozenset({"left", "right"}),
            requirement.check_id,
        )
        left = _exact_string_list(item["left"], f"{requirement.check_id}.left")
        right = _exact_string_list(item["right"], f"{requirement.check_id}.right")
        return set(left).isdisjoint(right)
    if predicate is EvidencePredicate.VERIFIED_ARTIFACT_DIGEST:
        return _digest(observed, requirement.check_id) in verified_raw_digests
    if predicate is EvidencePredicate.VERIFIED_ARTIFACT_DIGESTS_AT_LEAST:
        values = _exact_string_list(observed, requirement.check_id)
        for value in values:
            _digest(value, requirement.check_id)
        return (
            len(values) >= requirement.expected
            and set(values).issubset(verified_raw_digests)
        )
    if predicate is EvidencePredicate.TARGET_BENCHMARK:
        return _name(observed, requirement.check_id) == benchmark_id
    if predicate is EvidencePredicate.TARGET_REVISION:
        return _revision(observed) == source_revision
    if predicate is EvidencePredicate.TARGET_SCOPE_DIGEST:
        return _digest(observed, requirement.check_id) == scope_digest
    raise AssertionError(f"unhandled evidence predicate: {predicate}")


def _mutation_matrix_observations(
    witness_payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Recompute matrix facts from the typed registry and witnessed raw bytes.

    The report's own ``freeze_ready``/``benchmark_status`` strings are ignored
    as claims: the collector reconstructs every ``MutationObservation``, calls
    the registry evaluator, and requires the complete canonical report to
    equal the recomputed bytes.  Source and decisive-record digests must also
    resolve to separate witnessed artifacts.
    """

    from .mutation_matrix import (
        MATRIX_PROTOCOL,
        MUTANT_SPECS,
        MutationObservation,
        ObservationOutcome,
        SubjectKind,
        evaluate_mutation_matrix,
    )

    candidates: list[tuple[str, bytes, dict[str, Any]]] = []
    for artifact_digest, payload in witness_payloads.items():
        try:
            wire = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if type(wire) is dict and wire.get("protocol") == MATRIX_PROTOCOL:
            if canonical_json_bytes(wire) != payload:
                raise ProtocolViolation("mutation matrix witness is not canonical JSON")
            candidates.append((artifact_digest, payload, wire))
    if len(candidates) != 1:
        raise ProtocolViolation("exactly one typed mutation matrix witness is required")
    matrix_artifact_digest, matrix_payload, wire = candidates[0]
    expected_top = frozenset(
        {
            "protocol",
            "benchmark_status",
            "freeze_ready",
            "registry_digest",
            "observations",
            "valid_kills",
            "missing_or_invalid_mutants",
            "covered_gates",
            "uncovered_gates",
            "passed_specificity_controls",
            "failed_specificity_controls",
            "matrix_digest",
        }
    )
    _closed_object(wire, expected_top, "mutation matrix witness")
    raw_observations = wire["observations"]
    if type(raw_observations) is not list:
        raise ProtocolViolation("mutation matrix observations must be a list")
    observations: list[MutationObservation] = []
    row_keys = frozenset(
        {
            "subject_id",
            "subject_kind",
            "source_digest",
            "execution_seed",
            "outcome",
            "actual_gate",
            "actual_failure_code",
            "decisive_record_digest",
            "classification",
        }
    )
    try:
        for index, raw in enumerate(raw_observations):
            row = _closed_object(raw, row_keys, f"mutation observation {index}")
            observations.append(
                MutationObservation(
                    subject_id=row["subject_id"],
                    subject_kind=SubjectKind(row["subject_kind"]),
                    source_digest=row["source_digest"],
                    execution_seed=row["execution_seed"],
                    outcome=ObservationOutcome(row["outcome"]),
                    actual_gate=row["actual_gate"],
                    actual_failure_code=row["actual_failure_code"],
                    decisive_record_digest=row["decisive_record_digest"],
                    classification=row["classification"],
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolViolation("mutation matrix contains malformed observations") from exc

    recomputed = evaluate_mutation_matrix(observations)
    if recomputed.canonical_bytes() != matrix_payload:
        raise ProtocolViolation(
            "mutation matrix summaries/digest do not equal collector recomputation"
        )

    witnessed = set(witness_payloads)
    unresolved_sources = sorted(
        {
            row.subject_id
            for row in observations
            if row.source_digest not in witnessed
        }
    )
    unresolved_records = sorted(
        {
            row.subject_id
            for row in observations
            if row.decisive_record_digest is None
            or row.decisive_record_digest not in witnessed
        }
    )
    mutant_specs = {row.mutant_id: row for row in MUTANT_SPECS}
    wrong_gate_kills: list[str] = []
    for row in observations:
        if row.subject_kind is not SubjectKind.MUTANT:
            continue
        spec = mutant_specs[row.subject_id]
        if row.outcome is ObservationOutcome.KILLED and not (
            row.actual_gate in spec.expected_gates
            and row.actual_failure_code in spec.expected_failure_codes
            and row.decisive_record_digest is not None
        ):
            wrong_gate_kills.append(f"{row.subject_id}:{row.execution_seed}")

    return {
        "decisive-record-digest-missing": unresolved_records,
        "gates": list(recomputed.covered_gates),
        "matrix-artifact-digest": matrix_artifact_digest,
        "source-record-digest-missing": unresolved_sources,
        "specificity-control-count": len(recomputed.passed_specificity_controls),
        "specificity-false-positives": list(recomputed.failed_specificity_controls),
        "surviving-mutants": list(recomputed.missing_or_invalid_mutants),
        "target-mutant-count": len(recomputed.valid_kills),
        "wrong-gate-kills": sorted(wrong_gate_kills),
    }


def _extract_observation(
    extractor_id: str | None,
    *,
    witness_digests: tuple[str, ...],
    raw_payloads: dict[str, bytes],
) -> Any:
    if extractor_id is None:
        raise ProtocolViolation(
            "no collector-owned typed extractor is registered for this check"
        )
    if extractor_id.startswith("mutation-matrix/"):
        field = extractor_id.removeprefix("mutation-matrix/")
        witnessed = {digest: raw_payloads[digest] for digest in witness_digests}
        derived = _mutation_matrix_observations(witnessed)
        if field not in derived:
            raise ProtocolViolation("unknown mutation matrix extractor field")
        return derived[field]
    raise ProtocolViolation(f"unknown collector-owned extractor: {extractor_id}")


def collect_axis_evidence(
    repo_root: Path,
    contract: AxisEvidenceContract,
    *,
    benchmark_id: str,
    source_revision: str,
    scope_digest: str,
) -> AxisAuditResult:
    """Validate one persisted execution artifact and derive a typed result."""

    if not isinstance(repo_root, Path):
        raise ProtocolViolation("repo_root must be pathlib.Path")
    _name(benchmark_id, "benchmark_id")
    _revision(source_revision)
    _digest(scope_digest, "scope_digest")
    official = next(
        (item for item in DEFAULT_AXIS_CONTRACTS if item.axis == contract.axis),
        None,
    )
    if official is None or contract.digest != official.digest:
        raise ProtocolViolation(
            "only the built-in freeze contract for an axis may produce freeze evidence"
        )
    artifact_path = _resolved_file(repo_root, contract.artifact_path)
    if artifact_path.is_symlink() or not artifact_path.is_file():
        return _result(
            contract,
            status=FreezeEvidenceStatus.INCOMPLETE,
            benchmark_id=benchmark_id,
            source_revision=source_revision,
            scope_digest=scope_digest,
            blockers=(
                AuditBlocker(
                    "artifact-missing",
                    f"required structured execution artifact is absent: {contract.artifact_path}",
                ),
            ),
        )

    payload = artifact_path.read_bytes()
    artifact_digest = digest_bytes(payload)
    try:
        wire = json.loads(payload.decode("utf-8"))
        if canonical_json_bytes(wire) != payload:
            raise ProtocolViolation("axis evidence is not canonical JSON bytes")
        top = _closed_object(
            wire,
            frozenset(
                {
                    "protocol",
                    "axis",
                    "benchmark_id",
                    "source_revision",
                    "scope_digest",
                    "contract_digest",
                    "producer_id",
                    "producer_sources",
                    "execution",
                    "raw_artifacts",
                    "measurements",
                }
            ),
            "axis evidence",
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ProtocolViolation) as exc:
        return _result(
            contract,
            status=FreezeEvidenceStatus.INCOMPLETE,
            benchmark_id=benchmark_id,
            source_revision=source_revision,
            scope_digest=scope_digest,
            blockers=(AuditBlocker("artifact-invalid", str(exc)),),
            artifact_digest=artifact_digest,
        )

    binding_errors: list[str] = []
    if top["protocol"] != AXIS_EVIDENCE_PROTOCOL:
        binding_errors.append("protocol")
    if top["axis"] != contract.axis:
        binding_errors.append("axis")
    if top["benchmark_id"] != benchmark_id:
        binding_errors.append("benchmark_id")
    if top["source_revision"] != source_revision:
        binding_errors.append("source_revision")
    if top["scope_digest"] != scope_digest:
        binding_errors.append("scope_digest")
    if top["contract_digest"] != contract.digest:
        binding_errors.append("contract_digest")
    if top["producer_id"] != contract.producer_id:
        binding_errors.append("producer_id")
    if binding_errors:
        return _result(
            contract,
            status=FreezeEvidenceStatus.INCOMPLETE,
            benchmark_id=benchmark_id,
            source_revision=source_revision,
            scope_digest=scope_digest,
            blockers=(
                AuditBlocker(
                    "binding-mismatch",
                    "artifact does not bind current " + ", ".join(binding_errors),
                ),
            ),
            artifact_digest=artifact_digest,
        )

    try:
        producer_rows = top["producer_sources"]
        if type(producer_rows) is not list:
            raise ProtocolViolation("producer_sources must be a list")
        verified_producers = tuple(
            _verify_file_row(
                repo_root,
                row,
                allowed_prefixes=(_PRODUCER_PREFIX,),
                label=f"producer_sources[{index}]",
            ).path
            for index, row in enumerate(producer_rows)
        )
        if verified_producers != contract.producer_source_paths:
            raise ProtocolViolation("producer_sources do not exactly cover contract sources")

        raw_rows = top["raw_artifacts"]
        if type(raw_rows) is not list or not raw_rows:
            raise ProtocolViolation("raw_artifacts must be a non-empty list")
        verified_raw_files = tuple(
            _verify_file_row(
                repo_root,
                row,
                allowed_prefixes=_ISOLATED_PREFIXES,
                label=f"raw_artifacts[{index}]",
            )
            for index, row in enumerate(raw_rows)
        )
        raw_paths = tuple(item.path for item in verified_raw_files)
        if raw_paths != tuple(sorted(raw_paths, key=lambda item: item.encode("utf-8"))):
            raise ProtocolViolation("raw_artifacts must be canonically path-sorted")
        if len(raw_paths) != len(set(raw_paths)):
            raise ProtocolViolation("raw_artifacts contain duplicate paths")
        if contract.artifact_path in raw_paths:
            raise ProtocolViolation("axis artifact cannot witness itself")
        raw_digests = frozenset(item.digest for item in verified_raw_files)
        if len(raw_digests) != len(verified_raw_files):
            raise ProtocolViolation("raw_artifacts contain duplicate byte digests")
        raw_payloads = {
            item.digest: item.payload for item in verified_raw_files
        }

        execution = _closed_object(
            top["execution"],
            frozenset(
                {"run_id", "command_digest", "started_at", "finished_at", "exit_code"}
            ),
            "execution",
        )
        _name(execution["run_id"], "execution run_id")
        _digest(execution["command_digest"], "execution command_digest")
        started = _parse_time(execution["started_at"], "execution started_at")
        finished = _parse_time(execution["finished_at"], "execution finished_at")
        if finished < started:
            raise ProtocolViolation("execution finished before it started")
        if type(execution["exit_code"]) is not int:
            raise ProtocolViolation("execution exit_code must be exact int")

        measurement_rows = top["measurements"]
        if type(measurement_rows) is not list:
            raise ProtocolViolation("measurements must be a list")
        parsed_measurements: dict[str, tuple[str, ...]] = {}
        row_order: list[str] = []
        for index, raw in enumerate(measurement_rows):
            row = _closed_object(
                raw,
                frozenset({"check_id", "witness_digests"}),
                f"measurements[{index}]",
            )
            check_id = _name(row["check_id"], "measurement check_id")
            if check_id in parsed_measurements:
                raise ProtocolViolation("measurements contain duplicate check_id")
            witnesses = _exact_string_list(
                row["witness_digests"],
                f"measurements[{index}].witness_digests",
            )
            if not witnesses:
                raise ProtocolViolation("every measurement needs a raw-artifact witness")
            for witness in witnesses:
                _digest(witness, "measurement witness digest")
            if not set(witnesses).issubset(raw_digests):
                raise ProtocolViolation("measurement references an unverified witness digest")
            parsed_measurements[check_id] = witnesses
            row_order.append(check_id)
        if tuple(row_order) != tuple(
            sorted(row_order, key=lambda item: item.encode("utf-8"))
        ):
            raise ProtocolViolation("measurements must be canonically check-id sorted")
    except ProtocolViolation as exc:
        return _result(
            contract,
            status=FreezeEvidenceStatus.INCOMPLETE,
            benchmark_id=benchmark_id,
            source_revision=source_revision,
            scope_digest=scope_digest,
            blockers=(AuditBlocker("evidence-unbound", str(exc)),),
            artifact_digest=artifact_digest,
        )

    required = {item.check_id: item for item in contract.requirements}
    observed_ids = tuple(parsed_measurements)
    if set(observed_ids) != set(required):
        missing = sorted(set(required) - set(observed_ids))
        unexpected = sorted(set(observed_ids) - set(required))
        return _result(
            contract,
            status=FreezeEvidenceStatus.INCOMPLETE,
            benchmark_id=benchmark_id,
            source_revision=source_revision,
            scope_digest=scope_digest,
            blockers=(
                AuditBlocker(
                    "coverage-mismatch",
                    f"missing={missing!r}, unexpected={unexpected!r}",
                ),
            ),
            observed_checks=observed_ids,
            artifact_digest=artifact_digest,
        )

    if execution["exit_code"] != 0:
        return _result(
            contract,
            status=FreezeEvidenceStatus.FAIL,
            benchmark_id=benchmark_id,
            source_revision=source_revision,
            scope_digest=scope_digest,
            blockers=(
                AuditBlocker(
                    "execution-failed",
                    f"structured producer exited with code {execution['exit_code']}",
                ),
            ),
            observed_checks=observed_ids,
            artifact_digest=artifact_digest,
        )

    failed: list[tuple[CheckRequirement, AuditBlocker]] = []
    for requirement in contract.requirements:
        try:
            observed = _extract_observation(
                requirement.extractor_id,
                witness_digests=parsed_measurements[requirement.check_id],
                raw_payloads=raw_payloads,
            )
            passed = _evaluate(
                requirement,
                observed,
                verified_raw_digests=raw_digests,
                benchmark_id=benchmark_id,
                source_revision=source_revision,
                scope_digest=scope_digest,
            )
        except ProtocolViolation as exc:
            return _result(
                contract,
                status=FreezeEvidenceStatus.INCOMPLETE,
                benchmark_id=benchmark_id,
                source_revision=source_revision,
                scope_digest=scope_digest,
                blockers=(
                    AuditBlocker(
                        "measurement-invalid",
                        f"{requirement.check_id}: {exc}",
                    ),
                ),
                observed_checks=observed_ids,
                artifact_digest=artifact_digest,
            )
        if not passed:
            failed.append(
                (
                    requirement,
                    AuditBlocker(
                        (
                            "predicate-incomplete"
                            if requirement.false_status
                            is FreezeEvidenceStatus.INCOMPLETE
                            else "predicate-failed"
                        ),
                        f"collector predicate failed: {requirement.check_id}",
                    ),
                )
            )
    if failed:
        status = (
            FreezeEvidenceStatus.FAIL
            if any(
                requirement.false_status is FreezeEvidenceStatus.FAIL
                for requirement, _ in failed
            )
            else FreezeEvidenceStatus.INCOMPLETE
        )
        return _result(
            contract,
            status=status,
            benchmark_id=benchmark_id,
            source_revision=source_revision,
            scope_digest=scope_digest,
            blockers=(blocker for _, blocker in failed),
            observed_checks=observed_ids,
            artifact_digest=artifact_digest,
        )
    return _result(
        contract,
        status=FreezeEvidenceStatus.PASS,
        benchmark_id=benchmark_id,
        source_revision=source_revision,
        scope_digest=scope_digest,
        observed_checks=observed_ids,
        artifact_digest=artifact_digest,
    )


def collect_freeze_evidence(
    repo_root: Path,
    *,
    benchmark_id: str,
    source_revision: str,
    scope_digest: str,
    contracts: tuple[AxisEvidenceContract, ...] | None = None,
) -> FreezeEvidenceAudit:
    """Collect all sixteen axes; partial contract vectors are rejected."""

    selected = DEFAULT_AXIS_CONTRACTS if contracts is None else contracts
    if type(selected) is not tuple or any(
        type(item) is not AxisEvidenceContract for item in selected
    ):
        raise ProtocolViolation("freeze evidence contracts must be typed tuple")
    if tuple(item.axis for item in selected) != REQUIRED_FREEZE_EVIDENCE_AXES:
        raise ProtocolViolation("contracts must cover all freeze axes in canonical order")
    if tuple(item.digest for item in selected) != tuple(
        item.digest for item in DEFAULT_AXIS_CONTRACTS
    ):
        raise ProtocolViolation("freeze evidence contracts cannot be caller-weakened")
    return FreezeEvidenceAudit(
        benchmark_id=benchmark_id,
        source_revision=source_revision,
        scope_digest=scope_digest,
        axes=tuple(
            collect_axis_evidence(
                repo_root,
                contract,
                benchmark_id=benchmark_id,
                source_revision=source_revision,
                scope_digest=scope_digest,
            )
            for contract in selected
        ),
    )


def _require(
    check_id: str,
    predicate: EvidencePredicate,
    expected: Any = None,
    *,
    extractor_id: str | None = None,
    false_status: FreezeEvidenceStatus = FreezeEvidenceStatus.FAIL,
) -> CheckRequirement:
    if predicate is EvidencePredicate.EXACT_SET and type(expected) is tuple:
        expected = tuple(sorted(set(expected), key=lambda item: item.encode("utf-8")))
    return CheckRequirement(
        check_id,
        predicate,
        expected,
        extractor_id,
        false_status,
    )


def _mutation_requirement(
    check_id: str,
    predicate: EvidencePredicate,
    expected: Any = None,
) -> CheckRequirement:
    return _require(
        check_id,
        predicate,
        expected,
        extractor_id=f"mutation-matrix/{check_id}",
        false_status=FreezeEvidenceStatus.INCOMPLETE,
    )


def _contract(
    axis: str,
    authority: str,
    producer_id: str,
    sources: Iterable[str],
    requirements: Iterable[CheckRequirement],
) -> AxisEvidenceContract:
    return AxisEvidenceContract(
        axis=axis,
        artifact_path=f"research/unified_map/freeze/v1/evidence/{axis}.json",
        authority=authority,
        producer_id=producer_id,
        producer_source_paths=tuple(
            sorted(set(sources), key=lambda item: item.encode("utf-8"))
        ),
        requirements=tuple(
            sorted(requirements, key=lambda item: item.check_id.encode("utf-8"))
        ),
    )


_WORLDS = tuple(f"W{index:02d}" for index in range(1, 21))
_WORLD_SOURCES = (
    "prototype/unified_map/world_registry.py",
    "prototype/unified_map/worlds/base.py",
) + tuple(f"prototype/unified_map/worlds/w{index:02d}.py" for index in range(1, 21))
_GATES = tuple(f"C{index:02d}" for index in range(1, 34))


DEFAULT_AXIS_CONTRACTS = (
    _contract(
        "semantic_scope",
        "Exact machine scope manifest, task/world support, and target bindings.",
        "ucm.semantic-scope-auditor/v1",
        ("prototype/unified_map/freeze_audit.py",),
        (
            _require("benchmark-binding", EvidencePredicate.TARGET_BENCHMARK),
            _require("revision-binding", EvidencePredicate.TARGET_REVISION),
            _require("scope-digest-binding", EvidencePredicate.TARGET_SCOPE_DIGEST),
            _require("scope-manifest-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require(
                "task-readouts",
                EvidencePredicate.EXACT_SET,
                ("diagnosis", "intervention", "natural_forecast", "new_readout", "ood"),
            ),
            _require("world-slots", EvidencePredicate.EXACT_SET, _WORLDS),
        ),
    ),
    _contract(
        "world_generators",
        "W01--W20 machine manifests, support checks, exact split coverage, and authority-bound corpus replay.",
        "ucm.world-generator-auditor/v1",
        _WORLD_SOURCES + ("prototype/unified_map/corpus_authority.py",),
        (
            _require(
                "authority-bound-corpus-audit-digest",
                EvidencePredicate.VERIFIED_ARTIFACT_DIGEST,
                false_status=FreezeEvidenceStatus.INCOMPLETE,
            ),
            _require("generator-manifest-count", EvidencePredicate.INTEGER_AT_LEAST, 20),
            _require("materialization-blockers", EvidencePredicate.EMPTY),
            _require("same-seed-replay-failures", EvidencePredicate.EMPTY),
            _require("split-coverage", EvidencePredicate.EXACT_SET, ("sealed_test", "train", "validation")),
            _require("support-property-failures", EvidencePredicate.EMPTY),
            _require(
                "world-manifest-digests",
                EvidencePredicate.VERIFIED_ARTIFACT_DIGESTS_AT_LEAST,
                20,
            ),
            _require("world-slots", EvidencePredicate.EXACT_SET, _WORLDS),
        ),
    ),
    _contract(
        "oracle_reference",
        "Source-distinct public-history production/reference oracles for every world.",
        "ucm.oracle-certification-auditor/v1",
        ("prototype/unified_map/oracle_certification.py",) + _WORLD_SOURCES,
        (
            _require(
                "certification-artifact-digests",
                EvidencePredicate.VERIFIED_ARTIFACT_DIGESTS_AT_LEAST,
                20,
            ),
            _require("error-bound-failures", EvidencePredicate.EMPTY),
            _require("normalization-failures", EvidencePredicate.EMPTY),
            _require("private-swap-failures", EvidencePredicate.EMPTY),
            _require("production-reference-mismatches", EvidencePredicate.EMPTY),
            _require("source-separation-failures", EvidencePredicate.EMPTY),
            _require("world-slots", EvidencePredicate.EXACT_SET, _WORLDS),
        ),
    ),
    _contract(
        "catalog_schemas",
        "Closed observation/action/policy/utility/time/diagnosis/output catalogs.",
        "ucm.catalog-schema-auditor/v1",
        (
            "prototype/unified_map/policy.py",
            "prototype/unified_map/schema.py",
            "prototype/unified_map/worlds/base.py",
        ),
        (
            _require("catalog-digest-mismatches", EvidencePredicate.EMPTY),
            _require("closed-schema-failures", EvidencePredicate.EMPTY),
            _require(
                "schema-categories",
                EvidencePredicate.EXACT_SET,
                ("action", "diagnosis", "observation", "output", "policy", "time", "utility"),
            ),
            _require("schema-manifest-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("world-slots", EvidencePredicate.EXACT_SET, _WORLDS),
        ),
    ),
    _contract(
        "projection_boundary",
        "Physical public/target/judge separation, closed public corpus rows, and malicious smuggling probes.",
        "ucm.projection-boundary-auditor/v1",
        (
            "prototype/unified_map/candidate_protocol.py",
            "prototype/unified_map/compliance.py",
            "prototype/unified_map/corpus_authority.py",
            "prototype/unified_map/schema.py",
            "prototype/unified_map/world_registry.py",
        ),
        (
            _require(
                "authority-bound-corpus-audit-digest",
                EvidencePredicate.VERIFIED_ARTIFACT_DIGEST,
                false_status=FreezeEvidenceStatus.INCOMPLETE,
            ),
            _require("candidate-private-field-leaks", EvidencePredicate.EMPTY),
            _require("physical-separation-failures", EvidencePredicate.EMPTY),
            _require("projection-artifact-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require(
                "projection-roles",
                EvidencePredicate.EXACT_SET,
                ("candidate_inputs", "judge_oracle", "trainer_targets"),
            ),
            _require("target-smuggling-survivors", EvidencePredicate.EMPTY),
        ),
    ),
    _contract(
        "split_isolation",
        "Family-atomic exact/family/prefix-near-duplicate/pair split isolation with exact authority-bound corpus joins.",
        "ucm.split-isolation-auditor/v1",
        (
            "prototype/unified_map/corpus_authority.py",
            "prototype/unified_map/family_manifest.py",
            "prototype/unified_map/splits.py",
            "prototype/unified_map/strata_manifest.py",
            "prototype/unified_map/world_registry.py",
        ),
        (
            _require(
                "authority-bound-corpus-audit-digest",
                EvidencePredicate.VERIFIED_ARTIFACT_DIGEST,
                false_status=FreezeEvidenceStatus.INCOMPLETE,
            ),
            _require("exact-overlap", EvidencePredicate.EMPTY),
            _require("family-overlap", EvidencePredicate.EMPTY),
            _require("pair-overlap", EvidencePredicate.EMPTY),
            _require("prefix-near-duplicate-overlap", EvidencePredicate.EMPTY),
            _require("same-seed-replay-failures", EvidencePredicate.EMPTY),
            _require("split-manifest-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("splits", EvidencePredicate.EXACT_SET, ("sealed_test", "train", "validation")),
            _require("stratum-unverified", EvidencePredicate.EMPTY),
            _require("world-slots", EvidencePredicate.EXACT_SET, _WORLDS),
        ),
    ),
    _contract(
        "seed_protocol",
        "Domain-separated DEV5/TRAIN5/EVAL5/REPRO5/REDTEAM5 commit/reveal protocol.",
        "ucm.seed-protocol-auditor/v1",
        (
            "prototype/unified_map/freeze.py",
            "prototype/unified_map/splits.py",
        ),
        (
            _require("commit-reveal-failures", EvidencePredicate.EMPTY),
            _require("dev5-panel-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("domain-collision-failures", EvidencePredicate.EMPTY),
            _require(
                "domains",
                EvidencePredicate.EXACT_SET,
                ("analysis", "DEV5", "EVAL5", "REDTEAM5", "REPRO5", "TRAIN5"),
            ),
            _require("draw-program-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("raw-secret-leak-failures", EvidencePredicate.EMPTY),
            _require("seed-derivation-manifest-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
        ),
    ),
    _contract(
        "expected_cells",
        "Exact world/split/replicate/family/cut/horizon/policy/pair cells joined to authority-bound corpus roots.",
        "ucm.expected-cells-auditor/v1",
        (
            "prototype/unified_map/corpus_authority.py",
            "prototype/unified_map/evaluation_cells.py",
            "prototype/unified_map/evaluator.py",
            "prototype/unified_map/world_registry.py",
        ),
        (
            _require(
                "authority-bound-corpus-audit-digest",
                EvidencePredicate.VERIFIED_ARTIFACT_DIGEST,
                false_status=FreezeEvidenceStatus.INCOMPLETE,
            ),
            _require("duplicate-record-ids", EvidencePredicate.EMPTY),
            _require("evaluation-replicates", EvidencePredicate.EXACT_SET, tuple(f"eval-{i:02d}" for i in range(1, 6))),
            _require("expected-cell-count", EvidencePredicate.INTEGER_AT_LEAST, 1),
            _require("expected-cells-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("reconstruction-mismatches", EvidencePredicate.EMPTY),
            _require("scope-digest-binding", EvidencePredicate.TARGET_SCOPE_DIGEST),
            _require("scope-join-failures", EvidencePredicate.EMPTY),
            _require("splits", EvidencePredicate.EXACT_SET, ("test", "train", "validation")),
            _require("training-replicates", EvidencePredicate.EXACT_SET, tuple(f"train-{i:02d}" for i in range(1, 6))),
            _require("unbound-dimensions", EvidencePredicate.EMPTY),
            _require("world-slots", EvidencePredicate.EXACT_SET, _WORLDS),
        ),
    ),
    _contract(
        "probe_thresholds",
        "Per-world probes, finite queries, oracle errors, effect gaps, and preregistered margins.",
        "ucm.probe-threshold-auditor/v1",
        (
            "prototype/unified_map/evaluator.py",
            "prototype/unified_map/oracle_certification.py",
            "prototype/unified_map/world_registry.py",
        ),
        (
            _require("effect-gap-violations", EvidencePredicate.EMPTY),
            _require(
                "finite-query-manifest-digests",
                EvidencePredicate.VERIFIED_ARTIFACT_DIGESTS_AT_LEAST,
                20,
            ),
            _require("missing-derivations", EvidencePredicate.EMPTY),
            _require("oracle-error-bound-violations", EvidencePredicate.EMPTY),
            _require(
                "threshold-names",
                EvidencePredicate.EXACT_SET,
                ("catastrophic_regret_margin", "delta_distinguishable", "epsilon_candidate_same", "epsilon_equivalent"),
            ),
            _require("thresholds-manifest-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("world-slots", EvidencePredicate.EXACT_SET, _WORLDS),
        ),
    ),
    _contract(
        "metrics_weights",
        "Metrics, calibration, weights, missingness, hierarchy, CI, and exact rebuild.",
        "ucm.metrics-weights-auditor/v1",
        (
            "prototype/unified_map/evaluator.py",
            "prototype/unified_map/metrics.py",
        ),
        (
            _require("analysis-seed-artifact-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("bootstrap-replicates", EvidencePredicate.EXACT, 10000),
            _require("calibration-bins", EvidencePredicate.EXACT, 15),
            _require("metric-config-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("oracle-upper-bound-failures", EvidencePredicate.EMPTY),
            _require("raw-summary-rebuild-mismatches", EvidencePredicate.EMPTY),
            _require(
                "tasks",
                EvidencePredicate.EXACT_SET,
                ("diagnosis", "intervention", "natural_forecast", "new_readout", "ood"),
            ),
            _require("world-weight-count", EvidencePredicate.EXACT, 20),
        ),
    ),
    _contract(
        "mutation_matrix",
        "Real C01--C33 mutant kills and four specificity controls with decisive records.",
        "ucm.mutation-matrix-auditor/v1",
        (
            "prototype/unified_map/compliance.py",
            "prototype/unified_map/mutation_matrix.py",
            "prototype/unified_map/mutation_runner.py",
        ),
        (
            _mutation_requirement(
                "decisive-record-digest-missing", EvidencePredicate.EMPTY
            ),
            _mutation_requirement("gates", EvidencePredicate.EXACT_SET, _GATES),
            _mutation_requirement(
                "matrix-artifact-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST
            ),
            _mutation_requirement(
                "source-record-digest-missing", EvidencePredicate.EMPTY
            ),
            _mutation_requirement(
                "specificity-control-count", EvidencePredicate.INTEGER_AT_LEAST, 4
            ),
            _mutation_requirement(
                "specificity-false-positives", EvidencePredicate.EMPTY
            ),
            _mutation_requirement("surviving-mutants", EvidencePredicate.EMPTY),
            _mutation_requirement(
                "target-mutant-count", EvidencePredicate.INTEGER_AT_LEAST, 26
            ),
            _mutation_requirement("wrong-gate-kills", EvidencePredicate.EMPTY),
        ),
    ),
    _contract(
        "candidate_protocol",
        "Closed candidate request/response/state/hash and isolated worker protocol.",
        "ucm.candidate-protocol-auditor/v1",
        (
            "prototype/unified_map/candidate_protocol.py",
            "prototype/unified_map/compliance.py",
            "prototype/unified_map/schema.py",
            "prototype/unified_map/state.py",
        ),
        (
            _require("closed-payload-failures", EvidencePredicate.EMPTY),
            _require("codecs", EvidencePredicate.EXACT_SET, ("canonical-json-v1", "raw-f64le-v1")),
            _require("hash-binding-failures", EvidencePredicate.EMPTY),
            _require("methods", EvidencePredicate.EXACT_SET, ("diagnose", "initialize", "rollout", "update")),
            _require("protocol-mutant-survivors", EvidencePredicate.EMPTY),
            _require("protocol-schema-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("shared-state-fanout-failures", EvidencePredicate.EMPTY),
            _require("worker-roles", EvidencePredicate.EXACT_SET, ("head-worker", "judge", "state-worker", "trainer")),
        ),
    ),
    _contract(
        "baseline_budgets",
        "Four-baseline waiver registry and exact compute/data/search/capacity budgets.",
        "ucm.baseline-budget-auditor/v1",
        ("prototype/unified_map/freeze_audit.py",),
        (
            _require(
                "baseline-ids",
                EvidencePredicate.EXACT_SET,
                ("FullHistoryBaseline", "K0OnlyBaseline", "SeparateTaskBaseline", "TrueStateUpperBound"),
            ),
            _require("budget-manifest-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("missing-budget-fields", EvidencePredicate.EMPTY),
            _require("nested-budget-failures", EvidencePredicate.EMPTY),
            _require("nonzero-layer-failures", EvidencePredicate.EMPTY),
            _require("train-fractions-percent", EvidencePredicate.EXACT, [1, 5, 10, 25, 50, 100]),
            _require("waiver-scope-failures", EvidencePredicate.EMPTY),
        ),
    ),
    _contract(
        "replay_entrypoints",
        "Runner/judge/aggregator/rebuilder entrypoints and clean-checkout exact replay.",
        "ucm.replay-entrypoint-auditor/v1",
        (
            "prototype/unified_map/evaluator.py",
            "prototype/unified_map/freeze.py",
            "prototype/unified_map/run_store.py",
            "prototype/unified_map/world_registry.py",
        ),
        (
            _require("checksum-failures", EvidencePredicate.EMPTY),
            _require("clean-checkout-exit-code", EvidencePredicate.EXACT, 0),
            _require("corpus-replay-mismatches", EvidencePredicate.EMPTY),
            _require(
                "entrypoints",
                EvidencePredicate.EXACT_SET,
                ("aggregator", "judge", "raw-to-summary-rebuilder", "replay", "runner"),
            ),
            _require("entrypoint-manifest-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("expected-raw-mismatches", EvidencePredicate.EMPTY),
            _require("missing-crash-placeholders", EvidencePredicate.EMPTY),
            _require("summary-rebuild-mismatches", EvidencePredicate.EMPTY),
        ),
    ),
    _contract(
        "runtime_lock",
        "Dependency/runtime/native isolation lock and deterministic clean replay.",
        "ucm.runtime-lock-auditor/v1",
        (
            "prototype/unified_map/candidate_protocol.py",
            "prototype/unified_map/freeze_audit.py",
            "prototype/unified_map/run_store.py",
        ),
        (
            _require("deterministic-replay-mismatches", EvidencePredicate.EMPTY),
            _require("environment-drift", EvidencePredicate.EMPTY),
            _require("missing-lock-fields", EvidencePredicate.EMPTY),
            _require("native-sandbox-transcript-gaps", EvidencePredicate.EMPTY),
            _require("runtime-lock-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require(
                "runtime-lock-fields",
                EvidencePredicate.EXACT_SET,
                ("blas", "container_or_appcontainer", "cpu", "cuda", "dependencies", "determinism", "gpu", "os", "python", "threads"),
            ),
        ),
    ),
    _contract(
        "limitations_registry",
        "Machine limitations registry with no undisclosed or unclassified blocker.",
        "ucm.limitations-registry-auditor/v1",
        (
            "prototype/unified_map/compliance.py",
            "prototype/unified_map/freeze_audit.py",
            "prototype/unified_map/mutation_matrix.py",
        ),
        (
            _require("blocking-harness-items", EvidencePredicate.EMPTY),
            _require("known-limitations", EvidencePredicate.NON_EMPTY),
            _require("limitations-registry-digest", EvidencePredicate.VERIFIED_ARTIFACT_DIGEST),
            _require("scope-digest-binding", EvidencePredicate.TARGET_SCOPE_DIGEST),
            _require("unclassified-harness-incomplete", EvidencePredicate.EMPTY),
            _require("undisclosed-blockers", EvidencePredicate.EMPTY),
        ),
    ),
)

if tuple(item.axis for item in DEFAULT_AXIS_CONTRACTS) != REQUIRED_FREEZE_EVIDENCE_AXES:
    raise RuntimeError("default freeze evidence contracts must follow the canonical axis order")


__all__ = [
    "AUDIT_PROTOCOL",
    "AXIS_EVIDENCE_PROTOCOL",
    "CONTRACT_PROTOCOL",
    "AxisAuditResult",
    "AxisEvidenceContract",
    "AuditBlocker",
    "CheckRequirement",
    "DEFAULT_AXIS_CONTRACTS",
    "EvidencePredicate",
    "FreezeEvidenceAudit",
    "collect_axis_evidence",
    "collect_freeze_evidence",
]
