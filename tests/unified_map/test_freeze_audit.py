from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from prototype.unified_map import mutation_evidence, mutation_runner
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
from prototype.unified_map.mutation_evidence import (
    BENCHMARK_ID as MUTATION_BENCHMARK_ID,
    MutationEvidenceBuilder,
    MutationEvidenceBundle,
)
from prototype.unified_map.mutation_matrix import (
    PORTABLE_EXECUTION_CASES,
    ObservationOutcome,
    SubjectKind,
    execution_seed_for_case,
)
from prototype.unified_map.schema import (
    ActionPlan,
    DiagnosisQuery,
    PlanKind,
    RolloutQuery,
    VisibleDelta,
    VisibleHistory,
)


BENCHMARK = "UCM-BENCHMARK-v1"
REVISION = "a" * 40
SCOPE = digest_bytes(b"unit-scope")
MUTATION_RUN_ID = "unit-structured-run"
TEST_MUTATION_RUNNER_PROTOCOL = "ucm-portable-mutation-runner/freeze-audit-test"


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
    run_id: str = MUTATION_RUN_ID,
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
            "run_id": run_id,
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


def _mutation_bundle(
    *,
    run_id: str = MUTATION_RUN_ID,
    base_seed: int = 100,
) -> MutationEvidenceBundle:
    history = VisibleHistory(
        events=(),
        as_of_available_at=0,
        catalog_digest=digest_bytes(b"freeze-audit-mutation-catalog"),
    )
    diagnosis_query = DiagnosisQuery(("fixture.negative", "fixture.positive"))
    rollout_query = RolloutQuery(
        horizon=1,
        plan=ActionPlan(PlanKind.NO_NEW_ACTION),
        requested_observables=("fixture.signal",),
        utility_digest=digest_bytes(b"freeze-audit-mutation-utility"),
    )
    delta = VisibleDelta(advance_to=1)
    builder = MutationEvidenceBuilder(
        run_id=run_id,
        runner_protocol=TEST_MUTATION_RUNNER_PROTOCOL,
        base_seed=base_seed,
        input_preimage={
            "history": history.to_wire(),
            "diagnosis_query": diagnosis_query.to_wire(),
            "rollout_query": rollout_query.to_wire(),
            "delta": delta.to_wire(),
        },
        execution_context={
            "benchmark_id": MUTATION_BENCHMARK_ID,
            "runtime_metadata": {
                "python_implementation": "CPython",
                "python_version": "3.12.0",
                "platform_system": "unit-test",
                "platform_release": "unit-test",
                "platform_machine": "unit-test",
                "byteorder": "little",
            },
            "portable_runner_contract": mutation_evidence.portable_runner_contract(
                TEST_MUTATION_RUNNER_PROTOCOL
            ),
            "runtime_import_cache_contract_digest": digest_json({"entries": []}),
            "source_preparation_error": None,
        },
    )
    for case in PORTABLE_EXECUTION_CASES:
        execution_seed = execution_seed_for_case(base_seed, case)
        unavailable = {
            "protocol": "ucm-portable-source-witness-unavailable/1",
            "stage": "pre-execution",
            "exception_type": "builtins.LookupError",
            "control": case.control_class_name,
            "execution_case_id": case.execution_case_id,
            "probe_id": case.probe_id,
            "execution_seed": execution_seed,
            "enabled_semantic_probes": list(case.semantic_probes),
        }
        invocation_digest = digest_json([])
        decision = {
            "runner_protocol": TEST_MUTATION_RUNNER_PROTOCOL,
            "decision_kind": (
                "mutant-observation"
                if case.subject_kind is SubjectKind.MUTANT
                else "specificity-observation"
            ),
            "execution_case_id": case.execution_case_id,
            "probe_id": case.probe_id,
            "report_available": False,
            "harness_stable_during_execution": False,
            "execution_binding_complete": False,
            "derived_outcome": "crashed",
            "input_preimage_digest": builder.input_preimage_digest,
            "invocation_transcript_digest": invocation_digest,
        }
        if case.subject_kind is SubjectKind.MUTANT:
            decision.update(
                {
                    "expected_gate": case.expected_gate,
                    "expected_failure_code": case.expected_failure_code,
                    "harness_incomplete": True,
                    "decision_processing_complete": False,
                    "actual_gate": None,
                    "actual_failure_code": None,
                }
            )
        else:
            decision.update(
                {
                    "classification": case.classification,
                    "probe_incomplete": True,
                    "report_processing_complete": False,
                    "semantic_equivalence_passed": None,
                }
            )
        builder.add_record(
            subject_id=case.subject_id,
            subject_kind=case.subject_kind,
            execution_case_id=case.execution_case_id,
            probe_id=case.probe_id,
            execution_seed=execution_seed,
            outcome=ObservationOutcome.CRASHED,
            actual_gate=None,
            actual_failure_code=None,
            classification=case.classification,
            pre_source_witness=unavailable,
            post_source_witness={**unavailable, "stage": "post-execution"},
            source_record={},
            report_transcript=None,
            error_transcript={
                "runner_protocol": TEST_MUTATION_RUNNER_PROTOCOL,
                "status": "error",
                "errors": [
                    {
                        "stage": "candidate-evaluation",
                        "exception_type": "builtins.LookupError",
                        "message": "unit-test unavailable execution case",
                    }
                ],
            },
            decision_record=decision,
            decisive_record=None,
        )
    return builder.finalize()


def _mutation_fixture(
    root: Path,
    bundle_bytes: bytes,
    *,
    run_id: str = MUTATION_RUN_ID,
) -> tuple[AxisEvidenceContract, str]:
    contract = _contract("mutation_matrix")
    _materialize_producer_sources(root, contract)
    raw_path = f"results/unified_map/{run_id}/raw/mutation-evidence.json"
    _write(root, raw_path, bundle_bytes)
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


def test_four_freeze_contracts_bind_authority_corpus_bridge_but_stay_incomplete(
    tmp_path: Path,
) -> None:
    for axis in (
        "world_generators",
        "projection_boundary",
        "split_isolation",
        "expected_cells",
    ):
        bound = _contract(axis)
        assert "prototype/unified_map/corpus_authority.py" in (
            bound.producer_source_paths
        )
        requirement = next(
            item
            for item in bound.requirements
            if item.check_id == "authority-bound-corpus-audit-digest"
        )
        assert requirement.predicate.value == "verified_artifact_digest"
        assert requirement.false_status is FreezeEvidenceStatus.INCOMPLETE

    contract = _contract("split_isolation")
    assert {
        "prototype/unified_map/family_manifest.py",
        "prototype/unified_map/strata_manifest.py",
    } <= set(contract.producer_source_paths)

    # Merely adding the source/condition cannot create freeze evidence.  The
    # structured execution artifact and a collector-owned typed extractor are
    # both still absent.
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "artifact-missing"

    # Even a canonical raw corpus-audit-shaped witness plus an execution
    # envelope cannot self-certify this new check.  Freeze remains incomplete
    # until a collector-owned typed extractor is implemented and registered.
    root = tmp_path / "with-self-report"
    _materialize_producer_sources(root, contract)
    raw_path = "results/unified_map/unit-corpus-authority/audit.json"
    _write(
        root,
        raw_path,
        canonical_json_bytes(
            {
                "protocol": "ucm-authority-bound-corpus-audit/1",
                "status": "pre_freeze_scaffold",
                "freeze_grade_evidence": False,
                "benchmark_freeze_eligible": False,
                "audit_digest": digest_json({"fixture": "corpus-audit"}),
            }
        ),
    )
    _persist(root, contract, _axis_wire(root, contract, (raw_path,)))
    result = _collect(root, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "measurement-invalid"
    assert "collector-owned typed extractor" in result.blockers[0].detail


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


def test_raw_artifacts_are_parsed_from_the_single_verified_byte_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _mutation_bundle()
    contract, bundle_path = _mutation_fixture(tmp_path, bundle.canonical_bytes())
    _persist(
        tmp_path,
        contract,
        _axis_wire(tmp_path, contract, (bundle_path,)),
    )

    watched = {(tmp_path / Path(bundle_path)).resolve()}
    read_counts = {path: 0 for path in watched}
    original_read_bytes = Path.read_bytes

    def changing_second_read(path: Path) -> bytes:
        resolved = path.resolve()
        if resolved in read_counts:
            read_counts[resolved] += 1
            if read_counts[resolved] > 1:
                return b"different bytes supplied by a second path read\n"
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", changing_second_read)
    result = _collect(tmp_path, contract)

    assert read_counts == {path: 1 for path in watched}
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers
    assert all(blocker.code == "predicate-incomplete" for blocker in result.blockers)
    assert any("killed-mutant-count" in blocker.detail for blocker in result.blockers)


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


def test_typed_stored_bundle_is_recomputed_and_complete_raw_custody_stays_incomplete(
    tmp_path: Path,
) -> None:
    bundle = _mutation_bundle()
    assert MutationEvidenceBundle.from_canonical_bytes(bundle.canonical_bytes()) == bundle
    assert bundle.to_wire()["blockers"] == [
        "UCM-E002-ISOLATION_INCOMPLETE",
        "UCM-E003-HARNESS_INCOMPLETE",
    ]
    contract, raw_path = _mutation_fixture(tmp_path, bundle.canonical_bytes())
    assert {
        "prototype/unified_map/mutation_evidence.py",
        "prototype/unified_map/mutation_runner.py",
        "prototype/unified_map/run_store.py",
    } <= set(contract.producer_source_paths)
    target = _persist(
        tmp_path,
        contract,
        _axis_wire(tmp_path, contract, (raw_path,)),
    )
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.artifact_digest == digest_bytes(target.read_bytes())
    failed = {blocker.detail.rsplit(": ", 1)[-1] for blocker in result.blockers}
    assert {
        "bundle-blockers",
        "covered-gate-count",
        "failed-specificity-controls",
        "gates",
        "killed-mutant-count",
        "missing-or-invalid-mutants",
        "passed-specificity-count",
    } <= failed
    assert result.to_freeze_evidence().status is FreezeEvidenceStatus.INCOMPLETE

    requirements = {item.check_id: item for item in contract.requirements}
    assert requirements["target-mutant-count"].expected == 26
    assert requirements["target-specificity-count"].expected == 4
    assert requirements["target-gate-count"].expected == 33
    assert requirements["killed-mutant-count"].expected == 26
    assert requirements["passed-specificity-count"].expected == 4
    assert requirements["covered-gate-count"].expected == 33


def _forge_embedded_matrix_summary(bundle: MutationEvidenceBundle) -> bytes:
    wire = json.loads(bundle.canonical_bytes().decode("utf-8"))
    blobs = wire["blobs"]
    assert type(blobs) is list
    matrix_digest = wire["matrix_blob_digest"]
    matrix_blob = next(
        row for row in blobs if type(row) is dict and row["sha256"] == matrix_digest
    )
    matrix_payload = base64.b64decode(matrix_blob["payload_b64"])
    matrix = json.loads(matrix_payload.decode("utf-8"))
    matrix["benchmark_status"] = "MUTATION-GATES-PASS"
    matrix["freeze_ready"] = True
    matrix["covered_gates"] = [f"C{index:02d}" for index in range(1, 34)]
    matrix["uncovered_gates"] = []
    unsigned_matrix = {key: value for key, value in matrix.items() if key != "matrix_digest"}
    matrix["matrix_digest"] = digest_json(unsigned_matrix)
    forged_payload = canonical_json_bytes(matrix)
    forged_digest = digest_bytes(forged_payload)
    matrix_blob.update(
        {
            "bytes": len(forged_payload),
            "payload_b64": base64.b64encode(forged_payload).decode("ascii"),
            "sha256": forged_digest,
        }
    )
    wire["matrix_blob_digest"] = forged_digest
    blobs.sort(key=lambda row: row["sha256"])
    unsigned_bundle = {key: value for key, value in wire.items() if key != "bundle_digest"}
    wire["bundle_digest"] = digest_json(unsigned_bundle)
    return canonical_json_bytes(wire)


def test_forged_green_mutation_summary_is_not_trusted(tmp_path: Path) -> None:
    forged = _forge_embedded_matrix_summary(_mutation_bundle())
    contract, raw_path = _mutation_fixture(tmp_path, forged)
    _persist(tmp_path, contract, _axis_wire(tmp_path, contract, (raw_path,)))
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "measurement-invalid"
    assert "recomputation" in result.blockers[0].detail


def test_legacy_loose_matrix_and_arbitrary_digest_witnesses_are_rejected(
    tmp_path: Path,
) -> None:
    from prototype.unified_map.mutation_matrix import evaluate_mutation_matrix

    contract = _contract("mutation_matrix")
    _materialize_producer_sources(tmp_path, contract)
    loose_path = "results/unified_map/unit-structured-run/mutation-kill-matrix.json"
    source_path = "results/unified_map/unit-structured-run/source-witness.bin"
    decisive_path = "results/unified_map/unit-structured-run/decisive-witness.bin"
    _write(tmp_path, loose_path, evaluate_mutation_matrix(()).canonical_bytes())
    _write(tmp_path, source_path, b"arbitrary source digest witness\n")
    _write(tmp_path, decisive_path, b"arbitrary decisive digest witness\n")
    raw_paths = tuple(sorted((loose_path, source_path, decisive_path)))
    _persist(
        tmp_path,
        contract,
        _axis_wire(tmp_path, contract, raw_paths),
    )
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "measurement-invalid"
    assert "exactly one raw artifact" in result.blockers[0].detail


def test_legacy_loose_matrix_cannot_pass_when_renamed_as_typed_bundle(
    tmp_path: Path,
) -> None:
    from prototype.unified_map.mutation_matrix import evaluate_mutation_matrix

    loose = evaluate_mutation_matrix(()).canonical_bytes()
    contract, raw_path = _mutation_fixture(tmp_path, loose)
    _persist(tmp_path, contract, _axis_wire(tmp_path, contract, (raw_path,)))
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "measurement-invalid"
    assert "mutation evidence bundle" in result.blockers[0].detail


def test_mutation_bundle_is_bound_to_axis_execution_run(tmp_path: Path) -> None:
    cross_run = _mutation_bundle(run_id="other-run")
    contract, raw_path = _mutation_fixture(tmp_path, cross_run.canonical_bytes())
    _persist(tmp_path, contract, _axis_wire(tmp_path, contract, (raw_path,)))
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert result.blockers[0].code == "measurement-invalid"
    assert "run_id binding mismatch" in result.blockers[0].detail


def test_collector_never_reruns_portable_mutation_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _mutation_bundle()
    contract, raw_path = _mutation_fixture(tmp_path, bundle.canonical_bytes())
    _persist(tmp_path, contract, _axis_wire(tmp_path, contract, (raw_path,)))

    def forbidden_runner(*args: object, **kwargs: object) -> object:
        raise AssertionError("freeze collector must not rerun a candidate or runner")

    monkeypatch.setattr(
        mutation_runner,
        "run_portable_mutation_evidence",
        forbidden_runner,
    )
    result = _collect(tmp_path, contract)
    assert result.status is FreezeEvidenceStatus.INCOMPLETE
    assert all(blocker.code == "predicate-incomplete" for blocker in result.blockers)


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
