from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from prototype.unified_map.freeze import (
    REQUIRED_FREEZE_EVIDENCE_AXES,
    FreezeAxisEvidence,
    FreezeEvidenceStatus,
)
from prototype.unified_map.freeze_audit import (
    AXIS_EVIDENCE_PROTOCOL,
    AxisEvidenceContract,
    DEFAULT_AXIS_CONTRACTS,
    collect_axis_evidence,
    collect_freeze_evidence,
)
from prototype.unified_map.mutation_matrix import (
    MutationObservation,
    ObservationOutcome,
    SubjectKind,
    evaluate_mutation_matrix,
)


BENCHMARK = "UCM-BENCHMARK-v1"
REVISION = "a" * 40
SCOPE = digest_bytes(b"unit-scope")


def _contract(axis: str) -> AxisEvidenceContract:
    return next(item for item in DEFAULT_AXIS_CONTRACTS if item.axis == axis)


def _write(root: Path, relative: str, payload: bytes) -> Path:
    path = root / Path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _file_row(root: Path, relative: str) -> dict[str, object]:
    payload = (root / Path(relative)).read_bytes()
    return {
        "path": relative,
        "bytes": len(payload),
        "sha256": digest_bytes(payload),
    }


def _materialize_producer_sources(root: Path, contract: AxisEvidenceContract) -> None:
    for relative in contract.producer_source_paths:
        _write(root, relative, f"# producer fixture for {relative}\n".encode("utf-8"))


def _axis_wire(
    root: Path,
    contract: AxisEvidenceContract,
    raw_paths: tuple[str, ...],
    *,
    benchmark_id: str = BENCHMARK,
    revision: str = REVISION,
    scope_digest: str = SCOPE,
    exit_code: int = 0,
    check_ids: tuple[str, ...] | None = None,
) -> dict[str, object]:
    raw_rows = [_file_row(root, relative) for relative in raw_paths]
    witness_digests = sorted(str(row["sha256"]) for row in raw_rows)
    ids = check_ids or tuple(item.check_id for item in contract.requirements)
    return {
        "protocol": AXIS_EVIDENCE_PROTOCOL,
        "axis": contract.axis,
        "benchmark_id": benchmark_id,
        "source_revision": revision,
        "scope_digest": scope_digest,
        "contract_digest": contract.digest,
        "producer_id": contract.producer_id,
        "producer_sources": [
            _file_row(root, relative) for relative in contract.producer_source_paths
        ],
        "execution": {
            "run_id": "unit-structured-run",
            "command_digest": digest_json(["python", "axis_producer.py"]),
            "started_at": "2026-07-15T00:00:00Z",
            "finished_at": "2026-07-15T00:00:01Z",
            "exit_code": exit_code,
        },
        "raw_artifacts": raw_rows,
        "measurements": [
            {"check_id": check_id, "witness_digests": witness_digests}
            for check_id in ids
        ],
    }


def _persist(root: Path, contract: AxisEvidenceContract, wire: dict[str, object]) -> Path:
    return _write(root, contract.artifact_path, canonical_json_bytes(wire))


def _collect(root: Path, contract: AxisEvidenceContract):
    return collect_axis_evidence(
        root,
        contract,
        benchmark_id=BENCHMARK,
        source_revision=REVISION,
        scope_digest=SCOPE,
    )


def _generic_fixture(root: Path) -> tuple[AxisEvidenceContract, str]:
    contract = _contract("semantic_scope")
    _materialize_producer_sources(root, contract)
    raw_path = "results/unified_map/unit-run/raw.json"
    _write(
        root,
        raw_path,
        canonical_json_bytes(
            {
                "status": "PASS",
                "tests": ["test_scope_is_green"],
                "benchmark_id": BENCHMARK,
                "source_revision": REVISION,
                "scope_digest": SCOPE,
                "world_slots": [f"W{index:02d}" for index in range(1, 21)],
            }
        ),
    )
    return contract, raw_path


def _mutation_fixture(root: Path, report_bytes: bytes) -> tuple[AxisEvidenceContract, str]:
    contract = _contract("mutation_matrix")
    _materialize_producer_sources(root, contract)
    raw_path = "results/unified_map/mutation-run/mutation-kill-matrix.json"
    _write(root, raw_path, report_bytes)
    return contract, raw_path


def test_default_audit_covers_exact_axes_and_missing_artifacts_are_typed_incomplete(
    tmp_path: Path,
) -> None:
    assert tuple(item.axis for item in DEFAULT_AXIS_CONTRACTS) == (
        REQUIRED_FREEZE_EVIDENCE_AXES
    )
    audit = collect_freeze_evidence(
        tmp_path,
        benchmark_id=BENCHMARK,
        source_revision=REVISION,
        scope_digest=SCOPE,
    )
    assert audit.status is FreezeEvidenceStatus.INCOMPLETE
    assert len(audit.axes) == 16
    assert all(row.status is FreezeEvidenceStatus.INCOMPLETE for row in audit.axes)
    assert all(row.blockers[0].code == "artifact-missing" for row in audit.axes)
    assert all(type(row) is FreezeAxisEvidence for row in audit.evidence)


def test_forged_all_green_generic_artifact_stays_incomplete_without_typed_extractor(
    tmp_path: Path,
) -> None:
    contract, raw_path = _generic_fixture(tmp_path)
    _persist(tmp_path, contract, _axis_wire(tmp_path, contract, (raw_path,)))
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "measurement-invalid"
    assert "collector-owned typed extractor" in result.blockers[0].detail


def test_measurement_cannot_supply_self_reported_observed_pass(tmp_path: Path) -> None:
    contract, raw_path = _generic_fixture(tmp_path)
    wire = _axis_wire(tmp_path, contract, (raw_path,))
    measurements = wire["measurements"]
    assert isinstance(measurements, list)
    measurements[0]["observed"] = "PASS"
    _persist(tmp_path, contract, wire)
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "evidence-unbound"
    assert "closed object" in result.blockers[0].detail


def test_test_name_and_existing_log_cannot_replace_required_coverage(tmp_path: Path) -> None:
    contract, raw_path = _generic_fixture(tmp_path)
    _persist(
        tmp_path,
        contract,
        _axis_wire(
            tmp_path,
            contract,
            (raw_path,),
            check_ids=("pytest::test_freeze_is_green",),
        ),
    )
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "coverage-mismatch"


@pytest.mark.parametrize(
    ("field", "stale"),
    [
        ("benchmark_id", "UCM-BENCHMARK-v0"),
        ("source_revision", "b" * 40),
        ("scope_digest", digest_bytes(b"stale-scope")),
    ],
)
def test_stale_benchmark_revision_or_scope_is_incomplete(
    tmp_path: Path,
    field: str,
    stale: str,
) -> None:
    contract, raw_path = _generic_fixture(tmp_path)
    wire = _axis_wire(tmp_path, contract, (raw_path,))
    wire[field] = stale
    _persist(tmp_path, contract, wire)
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "binding-mismatch"


def test_raw_artifact_digest_is_recomputed_not_trusted(tmp_path: Path) -> None:
    contract, raw_path = _generic_fixture(tmp_path)
    _persist(tmp_path, contract, _axis_wire(tmp_path, contract, (raw_path,)))
    (tmp_path / Path(raw_path)).write_bytes(b"tampered after receipt\n")
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "evidence-unbound"
    assert "byte binding mismatch" in result.blockers[0].detail


def test_missing_required_measurement_is_incomplete_not_pass(tmp_path: Path) -> None:
    contract, raw_path = _generic_fixture(tmp_path)
    required = tuple(item.check_id for item in contract.requirements)
    _persist(
        tmp_path,
        contract,
        _axis_wire(tmp_path, contract, (raw_path,), check_ids=required[:-1]),
    )
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "coverage-mismatch"


def test_nonzero_structured_execution_is_typed_fail(tmp_path: Path) -> None:
    contract, raw_path = _generic_fixture(tmp_path)
    _persist(
        tmp_path,
        contract,
        _axis_wire(tmp_path, contract, (raw_path,), exit_code=7),
    )
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.FAIL
    assert result.blockers[0].code == "execution-failed"


def test_real_mutation_report_is_recomputed_and_partial_matrix_is_incomplete(
    tmp_path: Path,
) -> None:
    report = evaluate_mutation_matrix(())
    contract, raw_path = _mutation_fixture(tmp_path, report.canonical_bytes())
    target = _persist(
        tmp_path,
        contract,
        _axis_wire(tmp_path, contract, (raw_path,)),
    )
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.artifact_digest == digest_bytes(target.read_bytes())
    assert any("gates" in blocker.detail for blocker in result.blockers)
    assert result.to_freeze_evidence().status is FreezeEvidenceStatus.INCOMPLETE


def test_forged_green_mutation_summary_is_not_trusted(tmp_path: Path) -> None:
    report = evaluate_mutation_matrix(())
    wire = report.to_wire()
    wire["benchmark_status"] = "MUTATION-GATES-PASS"
    wire["freeze_ready"] = True
    wire["covered_gates"] = [f"C{index:02d}" for index in range(1, 34)]
    wire["uncovered_gates"] = []
    body = dict(wire)
    body.pop("matrix_digest")
    wire["matrix_digest"] = digest_json(body)
    contract, raw_path = _mutation_fixture(tmp_path, canonical_json_bytes(wire))
    _persist(tmp_path, contract, _axis_wire(tmp_path, contract, (raw_path,)))
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "measurement-invalid"
    assert "recomputation" in result.blockers[0].detail


def test_mutation_source_and_decisive_digests_must_resolve_to_raw_bytes(
    tmp_path: Path,
) -> None:
    row = MutationObservation(
        subject_id="RawHistoryHead",
        subject_kind=SubjectKind.MUTANT,
        source_digest=digest_bytes(b"unwitnessed source"),
        execution_seed=17,
        outcome=ObservationOutcome.KILLED,
        actual_gate="C02",
        actual_failure_code="UCM-F004-HEAD_HISTORY_ACCESS",
        decisive_record_digest=digest_bytes(b"unwitnessed decisive record"),
    )
    report = evaluate_mutation_matrix((row,))
    contract, raw_path = _mutation_fixture(tmp_path, report.canonical_bytes())
    _persist(tmp_path, contract, _axis_wire(tmp_path, contract, (raw_path,)))
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    failed_details = {item.detail for item in result.blockers}
    assert any("decisive-record-digest-missing" in item for item in failed_details)
    assert any("source-record-digest-missing" in item for item in failed_details)


def test_caller_cannot_weaken_an_official_axis_contract(tmp_path: Path) -> None:
    official = _contract("semantic_scope")
    weakened = AxisEvidenceContract(
        axis=official.axis,
        artifact_path=official.artifact_path,
        authority=official.authority,
        producer_id=official.producer_id,
        producer_source_paths=official.producer_source_paths,
        requirements=official.requirements[:1],
    )
    with pytest.raises(ProtocolViolation, match="built-in freeze contract"):
        _collect(tmp_path, weakened)


def test_noncanonical_axis_json_is_incomplete(tmp_path: Path) -> None:
    contract, raw_path = _generic_fixture(tmp_path)
    wire = _axis_wire(tmp_path, contract, (raw_path,))
    target = tmp_path / Path(contract.artifact_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(wire, indent=2), encoding="utf-8")
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "artifact-invalid"
