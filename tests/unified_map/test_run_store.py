from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from prototype.unified_map import mutation_evidence, run_store
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
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
from prototype.unified_map.run_store import (
    AppendOnlyRunWriter,
    CrashEvidenceRecord,
    CrashPlaceholder,
    IsolationAssurance,
    RunClass,
    RunManifest,
    RunStatus,
    RunVerificationReceipt,
    RuntimeManifest,
    MUTATION_EVIDENCE_PATH,
    required_payload_paths,
    results_root_digest,
    verify_run_bundle,
)
from prototype.unified_map.schema import (
    ActionPlan,
    DiagnosisQuery,
    PlanKind,
    RolloutQuery,
    VisibleDelta,
    VisibleHistory,
)


ZERO = "sha256:" + "0" * 64
ONE = "sha256:" + "1" * 64
EXPECTED_REQUIRED_PAYLOAD_PATHS = (
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
    "raw/mutation-evidence.json",
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
EXPECTED_REQUIRED_LAYOUT_DIGEST = (
    "sha256:e6d0fe15f4342cc129535bbbcfa5a567aae57056f5a1b99307e6179164ed6fd4"
)

TEST_MUTATION_RUNNER_PROTOCOL = "ucm-portable-mutation-runner/run-store-test"
TEST_MUTATION_RUNTIME_IMPORT_CACHE = {"entries": []}


def _mutation_bundle(run_id: str, *, base_seed: int = 100) -> MutationEvidenceBundle:
    history = VisibleHistory(
        events=(),
        as_of_available_at=0,
        catalog_digest=digest_bytes(b"run-store-mutation-catalog"),
    )
    diagnosis_query = DiagnosisQuery(("fixture.negative", "fixture.positive"))
    rollout_query = RolloutQuery(
        horizon=1,
        plan=ActionPlan(PlanKind.NO_NEW_ACTION),
        requested_observables=("fixture.signal",),
        utility_digest=digest_bytes(b"run-store-mutation-utility"),
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
            "runtime_import_cache_contract_digest": digest_json(
                TEST_MUTATION_RUNTIME_IMPORT_CACHE
            ),
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


def manifest(
    root: Path,
    *,
    run_id: str = "run-a",
    run_class: RunClass = RunClass.DEVELOPMENT,
    status: RunStatus = RunStatus.FINALIZED,
    candidate_id: str = "candidate-a",
) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        results_root_digest=results_root_digest(root),
        run_class=run_class,
        status=status,
        benchmark_id="UCM-BENCHMARK-v1",
        benchmark_freeze_digest=ZERO,
        scope_digest=ONE,
        hidden_corpus_digest="sha256:" + "2" * 64,
        candidate_id=candidate_id,
        candidate_source_seal="sha256:" + "3" * 64,
        model_artifact_digest="sha256:" + "4" * 64,
        git_commit="0123456789abcdef0123456789abcdef01234567",
        git_dirty=False,
        training_replicate_id="train-01",
        evaluation_replicate_id="eval-01",
        training_seed_tuple_digest="sha256:" + "5" * 64,
        evaluation_seed_tuple_digest="sha256:" + "6" * 64,
        train_data_digest="sha256:" + "7" * 64,
        validation_data_digest="sha256:" + "8" * 64,
        runtime=RuntimeManifest(
            python="3.13.5",
            os="windows",
            container="none-local-test",
            dependency_lock="sha256:" + "9" * 64,
        ),
        isolation_assurance=IsolationAssurance.PYTHON_AUDIT,
        started_at="2026-07-15T00:00:00Z",
        finished_at="2026-07-15T00:00:01Z",
    )


def _payload(path: str, expected: RunManifest | None = None) -> bytes:
    if path == "candidate/source-manifest.json" and expected is not None:
        return canonical_json_bytes(
            {
                "schema_version": "ucm-candidate-source-manifest/1",
                "candidate_id": expected.candidate_id,
                "candidate_source_seal": expected.candidate_source_seal,
            }
        )
    if path == "candidate/model-manifest.json" and expected is not None:
        return canonical_json_bytes(
            {
                "schema_version": "ucm-candidate-model-manifest/1",
                "candidate_id": expected.candidate_id,
                "candidate_source_seal": expected.candidate_source_seal,
                "model_artifact_digest": expected.model_artifact_digest,
            }
        )
    if path == "candidate/model-artifact.sha256" and expected is not None:
        return (expected.model_artifact_digest + "\n").encode("ascii")
    if path.endswith(".json"):
        return canonical_json_bytes({"artifact": path})
    if path.endswith(".jsonl"):
        return canonical_json_bytes({"artifact": path, "row": 1})
    return f"artifact={path}\n".encode("utf-8")


def _write_complete(writer: AppendOnlyRunWriter) -> None:
    for path in EXPECTED_REQUIRED_PAYLOAD_PATHS:
        if path == MUTATION_EVIDENCE_PATH:
            writer.write_mutation_evidence(_mutation_bundle(writer.manifest.run_id))
        else:
            writer.write_bytes(path, _payload(path, writer.manifest))


def _write_without_mutation_evidence(writer: AppendOnlyRunWriter) -> None:
    for path in EXPECTED_REQUIRED_PAYLOAD_PATHS:
        if path != MUTATION_EVIDENCE_PATH:
            writer.write_bytes(path, _payload(path, writer.manifest))


def _publish(root: Path, *, run_id: str = "run-a") -> tuple[Path, RunManifest]:
    expected = manifest(root, run_id=run_id)
    writer = AppendOnlyRunWriter(root, run_id, expected)
    _write_complete(writer)
    return writer.finalize(), expected


def _writable(path: Path, *, directory: bool = False) -> None:
    mode = stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if directory else 0)
    os.chmod(path, mode)


def test_run_bundle_is_exact_inventoried_rehashed_and_locally_sealed(
    tmp_path: Path,
) -> None:
    expected = manifest(tmp_path)
    writer = AppendOnlyRunWriter(tmp_path, "run-a", expected)
    assert not (tmp_path / "run-a").exists()
    _write_complete(writer)
    target = writer.finalize()

    assert target == tmp_path / "run-a"
    assert not (tmp_path / ".run-a.lock").exists()
    assert (tmp_path / ".run-a.local-seal.json").is_file()
    inventory_bytes = (target / "INVENTORY.json").read_bytes()
    inventory = json.loads(inventory_bytes)
    inventory_paths = [row["path"] for row in inventory["files"]]
    assert inventory_paths == sorted(inventory_paths, key=lambda item: item.encode())
    assert set(inventory_paths) == {
        "RUN_MANIFEST.json",
        "checksums.sha256",
        *required_payload_paths(RunClass.DEVELOPMENT),
    }
    for row in inventory["files"]:
        payload = (target / row["path"]).read_bytes()
        assert row["bytes"] == len(payload)
        assert row["sha256"] == digest_bytes(payload)

    receipt = verify_run_bundle(tmp_path, "run-a", expected_manifest=expected)
    assert type(receipt) is RunVerificationReceipt
    assert receipt.run_id == "run-a"
    assert receipt.run_class is RunClass.DEVELOPMENT
    assert receipt.run_status is RunStatus.FINALIZED
    assert receipt.to_wire()["status"] == "PRE-FREEZE"
    assert receipt.to_wire()["blockers"] == ["UCM-E003-HARNESS_INCOMPLETE"]
    assert receipt.to_wire()["freeze_grade_evidence"] is False
    assert receipt.to_wire()["benchmark_freeze_eligible"] is False
    assert receipt.to_wire()["external_worm_verified"] is False
    assert receipt.to_wire()["race_free_kernel_custody"] is False
    assert receipt.to_wire()["root_binding_scope"] == "LOCAL_ABSOLUTE_PATH_ONLY"
    assert receipt.to_wire()["absolute_root_binding_portable"] is False
    assert receipt.to_wire()["filesystem_link_checks_race_free"] is False
    assert receipt.to_wire()["xattrs_acl_custody_verified"] is False
    assert receipt.to_wire()["readonly_is_authority"] is False
    assert receipt.to_wire()["receipt_digest"] == digest_json(
        {key: value for key, value in receipt.to_wire().items() if key != "receipt_digest"}
    )

    with pytest.raises(FileExistsError):
        AppendOnlyRunWriter(tmp_path, "run-a", expected)


def test_mutation_evidence_uses_typed_only_same_run_write_path(tmp_path: Path) -> None:
    expected = manifest(tmp_path, run_id="typed-evidence")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    try:
        with pytest.raises(ProtocolViolation, match="requires write_mutation_evidence"):
            writer.write_bytes(MUTATION_EVIDENCE_PATH, b"{}")
        with pytest.raises(ProtocolViolation, match="requires write_mutation_evidence"):
            writer.write_json(MUTATION_EVIDENCE_PATH, {})
        with pytest.raises(ProtocolViolation, match="typed MutationEvidenceBundle"):
            writer.write_mutation_evidence({})  # type: ignore[arg-type]
        with pytest.raises(ProtocolViolation, match="run_id differs"):
            writer.write_mutation_evidence(_mutation_bundle("other-run"))
        forged_benchmark = _mutation_bundle(expected.run_id)
        object.__setattr__(forged_benchmark, "benchmark_id", "other-benchmark")
        with pytest.raises(ProtocolViolation, match="benchmark_id differs"):
            writer.write_mutation_evidence(forged_benchmark)

        writer.write_mutation_evidence(_mutation_bundle(expected.run_id))
        assert MutationEvidenceBundle.from_canonical_bytes(
            (writer.temporary / MUTATION_EVIDENCE_PATH).read_bytes()
        ).run_id == expected.run_id
    finally:
        writer.abort()


def test_finalized_run_requires_real_canonical_mutation_evidence(
    tmp_path: Path,
) -> None:
    expected = manifest(tmp_path, run_id="missing-mutation-evidence")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    _write_without_mutation_evidence(writer)
    try:
        with pytest.raises(ProtocolViolation, match="missing required paths"):
            writer.finalize()
    finally:
        writer.abort()

    expected = manifest(tmp_path, run_id="malformed-mutation-evidence")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    _write_without_mutation_evidence(writer)
    injected = writer.temporary / MUTATION_EVIDENCE_PATH
    injected.parent.mkdir(parents=True, exist_ok=True)
    injected.write_bytes(b"{}")
    try:
        with pytest.raises(ProtocolViolation, match="mutation evidence bundle"):
            writer.finalize()
    finally:
        writer.abort()


def test_finalize_reparses_live_mutation_evidence_bytes_and_binds_run(
    tmp_path: Path,
) -> None:
    expected = manifest(tmp_path, run_id="live-mutation-binding")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    _write_complete(writer)
    (writer.temporary / MUTATION_EVIDENCE_PATH).write_bytes(
        _mutation_bundle("substituted-run").canonical_bytes()
    )
    try:
        with pytest.raises(ProtocolViolation, match="run_id differs"):
            writer.finalize()
    finally:
        writer.abort()


@pytest.mark.parametrize(
    ("replace_after_scan", "expected_message"),
    [
        (2, "changed between checksum and inventory snapshots"),
        (3, "final pre-publication payload differs from inventory snapshot"),
    ],
)
def test_finalize_rejects_canonical_same_run_evidence_snapshot_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replace_after_scan: int,
    expected_message: str,
) -> None:
    expected = manifest(tmp_path, run_id=f"snapshot-swap-{replace_after_scan}")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    _write_complete(writer)
    replacement = _mutation_bundle(expected.run_id, base_seed=101).canonical_bytes()
    original_scan = run_store._scan_tree
    temporary_scan_count = 0

    def swapping_scan(root: Path) -> object:
        nonlocal temporary_scan_count
        snapshot = original_scan(root)
        if root == writer.temporary:
            temporary_scan_count += 1
            if temporary_scan_count == replace_after_scan:
                (writer.temporary / MUTATION_EVIDENCE_PATH).write_bytes(replacement)
        return snapshot

    monkeypatch.setattr(run_store, "_scan_tree", swapping_scan)
    with pytest.raises(ProtocolViolation, match=expected_message):
        writer.finalize()
    assert not (tmp_path / expected.run_id).exists()
    assert not (tmp_path / f".{expected.run_id}.local-seal.json").exists()


def test_control_generation_uses_inventory_snapshot_not_detached_live_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = manifest(tmp_path, run_id="inventory-snapshot-controls")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    _write_complete(writer)
    manifest_path = writer.temporary / "RUN_MANIFEST.json"
    original_manifest_bytes = manifest_path.read_bytes()
    original_scan = run_store._scan_tree
    original_write_control = writer._write_control
    temporary_scan_count = 0

    def transient_manifest_after_inventory_scan(root: Path) -> object:
        nonlocal temporary_scan_count
        snapshot = original_scan(root)
        if root == writer.temporary:
            temporary_scan_count += 1
            if temporary_scan_count == 3:
                manifest_path.write_bytes(b"transient bytes outside captured snapshot")
        return snapshot

    def restore_before_final_snapshot(relative: str, payload: bytes) -> None:
        original_write_control(relative, payload)
        if relative == "FINALIZED.json":
            manifest_path.write_bytes(original_manifest_bytes)

    monkeypatch.setattr(run_store, "_scan_tree", transient_manifest_after_inventory_scan)
    monkeypatch.setattr(writer, "_write_control", restore_before_final_snapshot)
    target = writer.finalize()
    receipt = verify_run_bundle(target, expected_manifest=expected)
    assert receipt.run_id == expected.run_id


def test_mutation_evidence_is_atomically_inventoried_and_live_reparsed(
    tmp_path: Path,
) -> None:
    target, expected = _publish(tmp_path, run_id="mutation-inventory")
    payload = (target / MUTATION_EVIDENCE_PATH).read_bytes()
    parsed = MutationEvidenceBundle.from_canonical_bytes(payload)
    assert parsed.run_id == expected.run_id
    assert parsed.benchmark_id == expected.benchmark_id

    inventory = json.loads((target / "INVENTORY.json").read_bytes())
    row = next(item for item in inventory["files"] if item["path"] == MUTATION_EVIDENCE_PATH)
    assert row == {
        "path": MUTATION_EVIDENCE_PATH,
        "bytes": len(payload),
        "sha256": digest_bytes(payload),
    }
    checksum_line = (
        f"{digest_bytes(payload)[7:]}  {MUTATION_EVIDENCE_PATH}\n".encode("ascii")
    )
    assert checksum_line in (target / "checksums.sha256").read_bytes().splitlines(
        keepends=True
    )
    receipt = verify_run_bundle(target, expected_manifest=expected)
    assert receipt.to_wire()["custody_assurance"] == (
        "LOCAL_REHASH_AND_SIBLING_SEAL_ONLY"
    )
    assert receipt.to_wire()["external_worm_verified"] is False

    evidence_path = target / MUTATION_EVIDENCE_PATH
    _writable(evidence_path)
    evidence_path.write_bytes(
        _mutation_bundle(expected.run_id, base_seed=101).canonical_bytes()
    )
    with pytest.raises(ProtocolViolation, match="live bundle bytes differ from inventory"):
        verify_run_bundle(target, expected_manifest=expected)

    evidence_path.write_bytes(payload)
    assert verify_run_bundle(target, expected_manifest=expected).run_id == expected.run_id
    evidence_path.write_bytes(_mutation_bundle("post-finalize-substitute").canonical_bytes())
    with pytest.raises(ProtocolViolation, match="run_id differs"):
        verify_run_bundle(target, expected_manifest=expected)


def test_post_rename_failure_retains_evidence_but_verifier_rejects_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = manifest(tmp_path, run_id="post-rename-failure")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    _write_complete(writer)

    def fail_after_target_and_seal_rename(root: Path) -> None:
        assert root == writer.target
        assert writer.target.is_dir()
        assert writer.local_seal.is_file()
        assert writer.lock.is_file()
        raise OSError("simulated post-rename readonly failure")

    monkeypatch.setattr(
        run_store,
        "_apply_auxiliary_readonly",
        fail_after_target_and_seal_rename,
    )
    with pytest.raises(OSError, match="simulated post-rename readonly failure"):
        writer.finalize()

    assert writer.target.is_dir()
    assert writer.local_seal.is_file()
    assert writer.lock.is_file()
    assert not (tmp_path / f".{expected.run_id}.local-seal.pending").exists()
    with pytest.raises(ProtocolViolation, match="incomplete publication marker"):
        verify_run_bundle(writer.target, expected_manifest=expected)

    # Preserve the failed publication through all assertions; only relax the
    # local seal mode so pytest can remove its temporary test root afterward.
    _writable(writer.local_seal)


def test_verifier_rejects_stray_pending_publication_marker(tmp_path: Path) -> None:
    target, expected = _publish(tmp_path, run_id="pending-marker")
    pending = tmp_path / f".{expected.run_id}.local-seal.pending"
    pending.write_bytes(b"unpublished local seal bytes")
    try:
        with pytest.raises(ProtocolViolation, match="local-seal.pending"):
            verify_run_bundle(target, expected_manifest=expected)
    finally:
        pending.unlink()


def test_manifest_is_typed_closed_and_bound_to_run_and_root(tmp_path: Path) -> None:
    expected = manifest(tmp_path)
    with pytest.raises(ProtocolViolation, match="typed RunManifest"):
        AppendOnlyRunWriter(tmp_path, "run-a", expected.to_wire())  # type: ignore[arg-type]
    with pytest.raises(ProtocolViolation, match="run_id argument"):
        AppendOnlyRunWriter(tmp_path, "other", expected)
    with pytest.raises(ProtocolViolation, match="results_root_digest"):
        AppendOnlyRunWriter(tmp_path / "other-root", "run-a", expected)

    wire = expected.to_wire()
    wire["producer_extension"] = "not-closed"
    with pytest.raises(ProtocolViolation, match="keys differ"):
        RunManifest.from_wire(wire)


def test_finalize_rechecks_live_manifest_and_candidate_artifact_bindings(
    tmp_path: Path,
) -> None:
    expected = manifest(tmp_path, run_id="manifest-tamper")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    _write_complete(writer)
    forged = expected.to_wire()
    forged["candidate_id"] = "candidate-b"
    forged["manifest_digest"] = digest_json(
        {key: value for key, value in forged.items() if key != "manifest_digest"}
    )
    (writer.temporary / "RUN_MANIFEST.json").write_bytes(canonical_json_bytes(forged))
    try:
        with pytest.raises(ProtocolViolation, match="typed writer manifest"):
            writer.finalize()
    finally:
        writer.abort()

    expected = manifest(tmp_path, run_id="candidate-tamper")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    for path in required_payload_paths(expected.run_class):
        if path == MUTATION_EVIDENCE_PATH:
            writer.write_mutation_evidence(_mutation_bundle(expected.run_id))
            continue
        payload = _payload(path, expected)
        if path == "candidate/source-manifest.json":
            payload = canonical_json_bytes(
                {
                    "schema_version": "ucm-candidate-source-manifest/1",
                    "candidate_id": "candidate-b",
                    "candidate_source_seal": expected.candidate_source_seal,
                }
            )
        writer.write_bytes(path, payload)
    try:
        with pytest.raises(ProtocolViolation, match="source manifest differs"):
            writer.finalize()
    finally:
        writer.abort()


def test_finalize_rejects_direct_temporary_tree_injection(tmp_path: Path) -> None:
    expected = manifest(tmp_path, run_id="temporary-extra")
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    _write_complete(writer)
    (writer.temporary / "attacker.bin").write_bytes(b"not declared")
    try:
        with pytest.raises(ProtocolViolation, match="outside the exact layout"):
            writer.finalize()
    finally:
        writer.abort()


def test_development_run_class_has_exact_code_owned_layout(tmp_path: Path) -> None:
    run_class = RunClass.DEVELOPMENT
    assert required_payload_paths(run_class) == EXPECTED_REQUIRED_PAYLOAD_PATHS
    assert digest_json(
        {
            "protocol": "ucm-run-required-layout/1",
            "paths": list(required_payload_paths(run_class)),
        }
    ) == EXPECTED_REQUIRED_LAYOUT_DIGEST
    run_id = f"run-{run_class.value}"
    expected = manifest(tmp_path, run_id=run_id, run_class=run_class)
    writer = AppendOnlyRunWriter(tmp_path, run_id, expected)
    _write_complete(writer)
    target = writer.finalize()
    receipt = verify_run_bundle(target, expected_manifest=expected)
    assert receipt.run_class is run_class
    assert receipt.to_wire()["status"] == "PRE-FREEZE"
    assert receipt.to_wire()["benchmark_freeze_eligible"] is False


@pytest.mark.parametrize(
    "run_class",
    [
        RunClass.SEALED_VALIDATION,
        RunClass.SEALED_TEST,
        RunClass.POST_TEST_TUNED,
        RunClass.REDTEAM,
        RunClass.REPRODUCTION,
    ],
)
def test_run_class_without_dedicated_layout_is_disabled_pre_freeze(
    tmp_path: Path, run_class: RunClass
) -> None:
    expected = manifest(tmp_path, run_id=f"disabled-{run_class.value}", run_class=run_class)
    with pytest.raises(ProtocolViolation, match="no code-owned dedicated layout"):
        required_payload_paths(run_class)
    with pytest.raises(ProtocolViolation, match="publication is disabled PRE-FREEZE"):
        AppendOnlyRunWriter(tmp_path, expected.run_id, expected)


def test_crashed_run_requires_typed_placeholders_for_exact_missing_layout(
    tmp_path: Path,
) -> None:
    expected = manifest(tmp_path, status=RunStatus.CRASHED)
    writer = AppendOnlyRunWriter(tmp_path, "run-a", expected)
    present = {"logs/stdout.log", "logs/stderr.log", "raw/process-audit.jsonl"}
    for path in present:
        writer.write_bytes(path, _payload(path))
    missing = sorted(
        set(required_payload_paths(expected.run_class)) - present,
        key=lambda item: item.encode(),
    )
    placeholders = tuple(
        CrashPlaceholder(
            path=path,
            evidence_path="raw/process-audit.jsonl",
            reason_code="WORKER_CRASHED_BEFORE_ARTIFACT",
            evidence_digest=digest_bytes(_payload("raw/process-audit.jsonl")),
        )
        for path in missing
    )
    crash_record = CrashEvidenceRecord(
        reason_code="WORKER_CRASHED",
        failure_type="WorkerProcessExit",
        detail_digest="sha256:" + "a" * 64,
        worker_exit=17,
        occurred_at="2026-07-15T00:00:00.5Z",
    )
    target = writer.finalize(
        crash_placeholders=placeholders,
        crash_evidence=crash_record,
    )
    receipt = verify_run_bundle(target, expected_manifest=expected)
    assert receipt.run_status is RunStatus.CRASHED
    crash_control = json.loads((target / "CRASH_EVIDENCE.json").read_bytes())
    assert crash_control["record"] == crash_record.to_wire()
    assert [row["path"] for row in crash_control["retained_artifacts"]] == [
        "logs/stderr.log",
        "logs/stdout.log",
        "raw/process-audit.jsonl",
    ]
    placeholder_rows = json.loads(
        (target / "CRASH_PLACEHOLDERS.json").read_bytes()
    )["placeholders"]
    assert MUTATION_EVIDENCE_PATH in {item["path"] for item in placeholder_rows}
    assert all(
        item["evidence_path"] == "raw/process-audit.jsonl"
        for item in placeholder_rows
    )
    inventory_rows = {
        row["path"]: row
        for row in json.loads((target / "INVENTORY.json").read_bytes())["files"]
    }
    assert MUTATION_EVIDENCE_PATH not in inventory_rows
    assert all(
        item["evidence_digest"]
        == inventory_rows[item["evidence_path"]]["sha256"]
        for item in placeholder_rows
    )

    second = manifest(tmp_path, run_id="run-b", status=RunStatus.CRASHED)
    writer = AppendOnlyRunWriter(tmp_path, "run-b", second)
    with pytest.raises(ProtocolViolation, match="require explicit placeholders"):
        writer.finalize()
    writer.abort()

    complete = manifest(tmp_path, run_id="run-ineligible", status=RunStatus.INELIGIBLE)
    writer = AppendOnlyRunWriter(tmp_path, "run-ineligible", complete)
    _write_complete(writer)
    target = writer.finalize()
    assert verify_run_bundle(target, expected_manifest=complete).run_status is RunStatus.INELIGIBLE


def _crash_record() -> CrashEvidenceRecord:
    return CrashEvidenceRecord(
        reason_code="WORKER_CRASHED",
        failure_type="WorkerProcessExit",
        detail_digest="sha256:" + "b" * 64,
        worker_exit=23,
        occurred_at="2026-07-15T00:00:00.75Z",
    )


def _partial_crash_placeholders(
    present: set[str], *, evidence_payload: bytes, digest_override: str | None = None
) -> tuple[CrashPlaceholder, ...]:
    missing = sorted(
        set(EXPECTED_REQUIRED_PAYLOAD_PATHS) - present,
        key=lambda item: item.encode(),
    )
    return tuple(
        CrashPlaceholder(
            path=path,
            evidence_path="raw/process-audit.jsonl",
            reason_code="WORKER_CRASHED_BEFORE_ARTIFACT",
            evidence_digest=(
                digest_override
                if digest_override is not None
                else digest_bytes(evidence_payload)
            ),
        )
        for path in missing
    )


def test_crash_placeholder_digest_must_resolve_to_retained_nonempty_artifact(
    tmp_path: Path,
) -> None:
    mandatory = {
        "logs/stdout.log",
        "logs/stderr.log",
        "raw/process-audit.jsonl",
    }

    expected = manifest(tmp_path, run_id="arbitrary-digest", status=RunStatus.CRASHED)
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    audit_payload = b'{"event":"worker-exit","exit":23}\n'
    writer.write_bytes("raw/process-audit.jsonl", audit_payload)
    writer.write_bytes("logs/stdout.log", b"worker started\n")
    writer.write_bytes("logs/stderr.log", b"worker failed\n")
    placeholders = _partial_crash_placeholders(
        mandatory,
        evidence_payload=audit_payload,
        digest_override="sha256:" + "c" * 64,
    )
    try:
        with pytest.raises(ProtocolViolation, match="does not match retained bytes"):
            writer.finalize(
                crash_placeholders=placeholders,
                crash_evidence=_crash_record(),
            )
    finally:
        writer.abort()

    expected = manifest(tmp_path, run_id="zero-shell", status=RunStatus.CRASHED)
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    writer.write_bytes("raw/process-audit.jsonl", b"")
    writer.write_bytes("logs/stdout.log", b"")
    writer.write_bytes("logs/stderr.log", b"")
    placeholders = _partial_crash_placeholders(mandatory, evidence_payload=b"")
    try:
        with pytest.raises(ProtocolViolation, match="cannot be an empty crash shell"):
            writer.finalize(
                crash_placeholders=placeholders,
                crash_evidence=_crash_record(),
            )
    finally:
        writer.abort()


def test_mandatory_crash_evidence_cannot_be_placeholdered_or_omitted(
    tmp_path: Path,
) -> None:
    present = {"logs/stdout.log", "raw/process-audit.jsonl"}
    audit_payload = b'{"event":"worker-exit","exit":23}\n'
    expected = manifest(tmp_path, run_id="missing-stderr", status=RunStatus.CRASHED)
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    writer.write_bytes("raw/process-audit.jsonl", audit_payload)
    writer.write_bytes("logs/stdout.log", b"worker started\n")
    placeholders = _partial_crash_placeholders(present, evidence_payload=audit_payload)
    try:
        with pytest.raises(ProtocolViolation, match="must be retained real crash artifacts"):
            writer.finalize(
                crash_placeholders=placeholders,
                crash_evidence=_crash_record(),
            )
    finally:
        writer.abort()

    expected = manifest(tmp_path, run_id="complete-crash-no-record", status=RunStatus.CRASHED)
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    _write_complete(writer)
    try:
        with pytest.raises(ProtocolViolation, match="require typed crash evidence"):
            writer.finalize()
    finally:
        writer.abort()

    present = {
        "logs/stdout.log",
        "logs/stderr.log",
        "raw/process-audit.jsonl",
    }
    expected = manifest(tmp_path, run_id="missing-record", status=RunStatus.CRASHED)
    writer = AppendOnlyRunWriter(tmp_path, expected.run_id, expected)
    writer.write_bytes("raw/process-audit.jsonl", audit_payload)
    writer.write_bytes("logs/stdout.log", b"worker started\n")
    writer.write_bytes("logs/stderr.log", b"worker failed\n")
    placeholders = _partial_crash_placeholders(present, evidence_payload=audit_payload)
    try:
        with pytest.raises(ProtocolViolation, match="require typed crash evidence"):
            writer.finalize(crash_placeholders=placeholders)
    finally:
        writer.abort()


def test_empty_shell_and_wrong_out_of_band_manifest_fail_closed(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    expected_empty = manifest(tmp_path, run_id="empty")
    with pytest.raises(ProtocolViolation):
        verify_run_bundle(tmp_path, "empty", expected_manifest=expected_empty)

    target, expected = _publish(tmp_path, run_id="real")
    wrong = replace(expected, candidate_id="substituted-candidate")
    with pytest.raises(ProtocolViolation, match="expected manifest"):
        verify_run_bundle(target, expected_manifest=wrong)


def test_finalize_then_raw_modification_is_detected_by_live_rehash(tmp_path: Path) -> None:
    target, expected = _publish(tmp_path)
    raw = target / "raw/predictions.jsonl"
    _writable(raw)
    raw.write_bytes(b'{"attacker":true}\n')
    with pytest.raises(ProtocolViolation, match="live bundle bytes differ"):
        verify_run_bundle(target, expected_manifest=expected)


def test_readonly_mode_is_observed_but_not_used_as_integrity_authority(
    tmp_path: Path,
) -> None:
    target, expected = _publish(tmp_path)
    _writable(target / "raw/predictions.jsonl")
    receipt = verify_run_bundle(target, expected_manifest=expected)
    assert receipt.readonly_all_observed is False
    assert receipt.to_wire()["readonly_is_authority"] is False


def _rewrite_all_in_bundle_seals(target: Path, expected: RunManifest) -> None:
    """Model an attacker who rewrites raw + checksums + inventory + marker.

    The sibling seal is deliberately left untouched.  This helper constructs a
    fully self-consistent replacement inside the bundle, so the rejection does
    not merely depend on a stale inventory row.
    """

    raw = target / "raw/predictions.jsonl"
    for path in (raw, target / "checksums.sha256", target / "INVENTORY.json", target / "FINALIZED.json"):
        _writable(path)
    raw.write_bytes(b'{"attacker":"rewrote-everything-inside"}\n')

    inventory_old = json.loads((target / "INVENTORY.json").read_bytes())
    base_paths = sorted(
        (
            path.relative_to(target).as_posix()
            for path in target.rglob("*")
            if path.is_file()
            and path.name not in {"checksums.sha256", "INVENTORY.json", "FINALIZED.json"}
        ),
        key=lambda item: item.encode(),
    )
    checksum_rows = []
    for relative in base_paths:
        payload = (target / relative).read_bytes()
        checksum_rows.append(
            {"path": relative, "bytes": len(payload), "sha256": digest_bytes(payload)}
        )
    checksums = b"".join(
        f"{row['sha256'][7:]}  {row['path']}\n".encode() for row in checksum_rows
    )
    (target / "checksums.sha256").write_bytes(checksums)

    inventory_paths = sorted(base_paths + ["checksums.sha256"], key=lambda item: item.encode())
    rows = []
    for relative in inventory_paths:
        payload = (target / relative).read_bytes()
        rows.append({"path": relative, "bytes": len(payload), "sha256": digest_bytes(payload)})
    directories = sorted(
        (
            path.relative_to(target).as_posix()
            for path in target.rglob("*")
            if path.is_dir()
        ),
        key=lambda item: item.encode(),
    )
    tree_digest = digest_json(
        {
            "protocol": "ucm-run-tree/1",
            "directories": directories,
            "files": rows,
        }
    )
    manifest_bytes = (target / "RUN_MANIFEST.json").read_bytes()
    manifest_sha256 = digest_bytes(manifest_bytes)
    binding = digest_json(
        {
            "protocol": "ucm-run-finalization-binding/1",
            "run_id": expected.run_id,
            "results_root_digest": expected.results_root_digest,
            "run_class": expected.run_class.value,
            "run_status": expected.status.value,
            "benchmark_id": expected.benchmark_id,
            "benchmark_freeze_digest": expected.benchmark_freeze_digest,
            "scope_digest": expected.scope_digest,
            "hidden_corpus_digest": expected.hidden_corpus_digest,
            "candidate_id": expected.candidate_id,
            "candidate_source_seal": expected.candidate_source_seal,
            "model_artifact_digest": expected.model_artifact_digest,
            "manifest_sha256": manifest_sha256,
            "tree_digest": tree_digest,
        }
    )
    inventory = dict(inventory_old)
    inventory.update(
        {
            "manifest_sha256": manifest_sha256,
            "directories": directories,
            "files": rows,
            "tree_digest": tree_digest,
            "finalization_binding_digest": binding,
        }
    )
    inventory_bytes = canonical_json_bytes(inventory)
    (target / "INVENTORY.json").write_bytes(inventory_bytes)

    finalized = json.loads((target / "FINALIZED.json").read_bytes())
    finalized.update(
        {
            "manifest_sha256": manifest_sha256,
            "inventory_sha256": digest_bytes(inventory_bytes),
            "checksums_sha256": digest_bytes(checksums),
            "tree_digest": tree_digest,
            "finalization_binding_digest": binding,
        }
    )
    (target / "FINALIZED.json").write_bytes(canonical_json_bytes(finalized))


def test_rewriting_raw_inventory_and_final_marker_still_fails_local_seal(
    tmp_path: Path,
) -> None:
    target, expected = _publish(tmp_path)
    _rewrite_all_in_bundle_seals(target, expected)
    with pytest.raises(ProtocolViolation, match="local sibling seal differs"):
        verify_run_bundle(target, expected_manifest=expected)


def test_extra_file_and_empty_directory_fail_exact_tree(tmp_path: Path) -> None:
    target, expected = _publish(tmp_path)
    _writable(target, directory=True)
    (target / "unlisted.bin").write_bytes(b"extra")
    with pytest.raises(ProtocolViolation, match="exact tree differs"):
        verify_run_bundle(target, expected_manifest=expected)

    target2, expected2 = _publish(tmp_path, run_id="run-b")
    _writable(target2, directory=True)
    (target2 / "empty-extra-dir").mkdir()
    with pytest.raises(ProtocolViolation, match="directory tree differs"):
        verify_run_bundle(target2, expected_manifest=expected2)


def test_missing_required_raw_file_fails_exact_tree(tmp_path: Path) -> None:
    target, expected = _publish(tmp_path)
    raw_dir = target / "raw"
    victim = raw_dir / "updates.jsonl"
    _writable(raw_dir, directory=True)
    _writable(victim)
    victim.unlink()
    with pytest.raises(ProtocolViolation, match="exact tree differs"):
        verify_run_bundle(target, expected_manifest=expected)


def test_symlink_or_reparse_entry_fails_closed(tmp_path: Path) -> None:
    target, expected = _publish(tmp_path)
    raw_dir = target / "raw"
    victim = raw_dir / "predictions.jsonl"
    _writable(raw_dir, directory=True)
    _writable(victim)
    victim.unlink()
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b'{"outside":true}\n')
    try:
        victim.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(ProtocolViolation, match="symlink, junction, or reparse"):
        verify_run_bundle(target, expected_manifest=expected)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction control")
def test_windows_junction_reparse_entry_fails_closed(tmp_path: Path) -> None:
    target, expected = _publish(tmp_path)
    _writable(target, directory=True)
    outside = tmp_path / "junction-target"
    outside.mkdir()
    junction = target / "junction-extra"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("junction creation unavailable")
    try:
        with pytest.raises(ProtocolViolation, match="symlink, junction, or reparse"):
            verify_run_bundle(target, expected_manifest=expected)
    finally:
        junction.rmdir()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ADS control")
def test_windows_named_alternate_data_stream_fails_closed(tmp_path: Path) -> None:
    target, expected = _publish(tmp_path)
    raw = target / "raw/predictions.jsonl"
    _writable(raw)
    stream_path = Path(str(raw) + ":attacker")
    try:
        stream_path.write_bytes(b"hidden replacement metadata")
    except OSError as exc:
        pytest.skip(f"named stream unavailable: {exc}")
    try:
        with pytest.raises(ProtocolViolation, match="named alternate data stream"):
            verify_run_bundle(target, expected_manifest=expected)
    finally:
        stream_path.unlink(missing_ok=True)


def test_hardlink_fails_closed_even_when_link_is_outside_tree(tmp_path: Path) -> None:
    target, expected = _publish(tmp_path)
    source = target / "raw/predictions.jsonl"
    outside = tmp_path / "outside-hardlink"
    try:
        os.link(source, outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hardlink creation unavailable: {exc}")
    with pytest.raises(ProtocolViolation, match="hard-linked"):
        verify_run_bundle(target, expected_manifest=expected)


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "a\\b",
        "",
        ".",
        "raw/data:stream",
        "NUL",
        "reports/COM1.json",
        "trailing.",
        "bad\x01name",
        "raw/not-in-the-layout.jsonl",
    ],
)
def test_bundle_rejects_unsafe_or_non_layout_paths(tmp_path: Path, path: str) -> None:
    expected = manifest(tmp_path, run_id="safe")
    writer = AppendOnlyRunWriter(tmp_path, "safe", expected)
    try:
        with pytest.raises(ProtocolViolation):
            writer.write_bytes(path, b"x")
    finally:
        writer.abort()


def test_abort_removes_partial_run_and_lock(tmp_path: Path) -> None:
    expected = manifest(tmp_path, run_id="failed")
    with pytest.raises(RuntimeError):
        with AppendOnlyRunWriter(tmp_path, "failed", expected) as writer:
            writer.write_bytes("raw/states.jsonl", b"partial")
            raise RuntimeError("boom")
    assert not (tmp_path / "failed").exists()
    assert not (tmp_path / ".failed.lock").exists()
    assert not list(tmp_path.glob(".failed.tmp-*"))


@pytest.mark.parametrize(
    "run_id",
    ["", "../x", "x/y", "x y", ".", "NUL", "COM1.json", "trailing.", "a" * 129],
)
def test_run_id_is_one_safe_component(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ProtocolViolation):
        AppendOnlyRunWriter(tmp_path, run_id, manifest(tmp_path))
