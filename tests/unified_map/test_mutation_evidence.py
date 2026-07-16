from __future__ import annotations

import base64
import json
from copy import deepcopy

import pytest

from prototype.unified_map import mutation_evidence
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.mutation_evidence import (
    BENCHMARK_ID,
    ContentAddressedBlob,
    MUTATION_EVIDENCE_BLOCKERS,
    PRE_FREEZE_STATUS,
    MutationEvidenceBuilder,
    MutationEvidenceBundle,
)
from prototype.unified_map.mutation_matrix import (
    MutationObservation,
    ObservationOutcome,
    SubjectKind,
    evaluate_mutation_matrix,
)


TEST_RUNNER_PROTOCOL = "ucm-portable-mutation-runner/unit-test"
TEST_BASE_SEED = 100
RAW_HISTORY_SEED = TEST_BASE_SEED + 2
EXPLICIT_SEED = TEST_BASE_SEED + 14
BEHAVIOR_SEED = TEST_BASE_SEED + 15
TEST_RUNTIME_METADATA = {
    "python_implementation": "CPython",
    "python_version": "3.12.0",
    "platform_system": "unit-test",
    "platform_release": "unit-test",
    "platform_machine": "unit-test",
    "byteorder": "little",
}
TEST_RUNTIME_IMPORT_CACHE = {"entries": []}
TEST_RUNTIME_CACHE_DIGEST = digest_json(TEST_RUNTIME_IMPORT_CACHE)

REPLAY_HEAD_CONTROLS = frozenset(
    {
        "GlobalSecondStateControl",
        "ImplicitRNGControl",
        "HistoryInBlobControl",
        "WarmFutureCacheControl",
        "ReplayBatchDivergenceControl",
        "DoubleCountEventControl",
        "HonestSeededControl",
        "BehaviorEquivalentSerializationControl",
        "DeclaredFullHistoryBaselineControl",
    }
)


def _input_preimage(*, delta: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "history": {"events": [{"event_uid": "event-a", "value": 0.4}]},
        "diagnosis_query": {"labels": ["a", "b"]},
        "rollout_query": {"horizon": 2},
        "delta": delta,
    }


def _execution_context() -> dict[str, object]:
    return {
        "benchmark_id": BENCHMARK_ID,
        "runtime_metadata": deepcopy(TEST_RUNTIME_METADATA),
        "portable_runner_contract": mutation_evidence.portable_runner_contract(
            TEST_RUNNER_PROTOCOL
        ),
        "runtime_import_cache_contract_digest": TEST_RUNTIME_CACHE_DIGEST,
        "source_preparation_error": None,
    }


def _error_transcript(errors: list[dict[str, object]]) -> dict[str, object]:
    return {
        "runner_protocol": TEST_RUNNER_PROTOCOL,
        "status": "error" if errors else "none",
        "errors": errors,
    }


def _fixed_scope_findings() -> list[dict[str, object]]:
    return [
        {
            "gate": "semantic-unity-boundary",
            "verdict": "incomplete",
            "failure_code": "UCM-E001-SEMANTIC_UNITY_UNVERIFIED",
            "detail": "semantic unity remains outside portable proof",
            "evidence": {},
        },
        {
            "gate": "portable-isolation-boundary",
            "verdict": "incomplete",
            "failure_code": "UCM-E002-ISOLATION_INCOMPLETE",
            "detail": "portable isolation remains incomplete",
            "evidence": {},
        },
    ]


def _paired_semantic_evidence(
    *,
    include_update: bool = False,
) -> dict[str, object]:
    phases: list[dict[str, object]] = [
        {
            "phase": "initialize",
            "honest_state_digest": "sha256:" + "1" * 64,
            "affine_state_digest": "sha256:" + "2" * 64,
            "state_serializations_distinct": True,
            "honest_behavior_digest": "sha256:" + "3" * 64,
            "affine_behavior_digest": "sha256:" + "4" * 64,
            "semantic_behavior_equivalent": True,
        }
    ]
    if include_update:
        phases.append(
            {
                "phase": "update",
                "honest_state_digest": "sha256:" + "5" * 64,
                "affine_state_digest": "sha256:" + "6" * 64,
                "state_serializations_distinct": True,
                "honest_behavior_digest": "sha256:" + "7" * 64,
                "affine_behavior_digest": "sha256:" + "8" * 64,
                "semantic_behavior_equivalent": True,
            }
        )
    return {
        "protocol": "ucm-portable-semantic-probes/4",
        "comparison": "paired-honest-vs-affine-scored-semantics",
        "absolute_tolerance": 1e-9,
        "relative_tolerance": 0.0,
        "phases": phases,
        "passed": True,
    }


def _builder(
    *,
    delta: dict[str, object] | None = None,
    execution_context: dict[str, object] | None = None,
) -> MutationEvidenceBuilder:
    return MutationEvidenceBuilder(
        run_id="mutation-unit-run",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=_input_preimage(delta=delta),
        execution_context=(
            _execution_context()
            if execution_context is None
            else execution_context
        ),
    )


def _source_witness(
    *,
    binding: dict[str, object],
    control_class_name: str,
    execution_seed: int,
    semantic_probes: tuple[str, ...],
) -> dict[str, object]:
    expected_candidate = (
        "prototype.unified_map.compliance:" + control_class_name
    )
    return {
        "protocol": "ucm-portable-control-source-binding/16",
        "control": control_class_name,
        "execution_seed": execution_seed,
        "control_mro": [],
        "source_identity_anchors": [],
        "external_attribute_identities": [],
        "external_global_dispatch": {},
        "external_class_surfaces": [],
        "external_runtime_object_identities": [],
        "external_runtime_values": {},
        "runtime_import_cache": deepcopy(TEST_RUNTIME_IMPORT_CACHE),
        "module_source_digests": {},
        "live_module_code_bindings": {},
        "live_detector_code_digests": {},
        "live_protocol_code_digests": {},
        "live_runtime_constants": {},
        "freeze_critical_runtime_contract": {},
        "critical_alias_identities": [],
        "expected_candidate": expected_candidate,
        "expected_live_execution_binding": binding,
        "portable_runner_contract": mutation_evidence.portable_runner_contract(
            TEST_RUNNER_PROTOCOL
        ),
        "semantic_probe_contract": "ucm-portable-semantic-probes/4",
        "enabled_semantic_probes": list(semantic_probes),
        "runtime_metadata": deepcopy(TEST_RUNTIME_METADATA),
    }


def _decisive_raw(
    *,
    binding_digit: str,
    control_class_name: str,
    execution_seed: int,
    outcome: str,
    findings: list[dict[str, object]],
    failure_codes: list[str],
    decision_kind: str,
    operational_state_closure: str | None = None,
    semantic_probes: tuple[str, ...] = (),
    paired_semantic_equivalence: dict[str, object] | None = None,
    classification: str = "ordinary_candidate",
    expected_gate: str = "C02",
    expected_failure_code: str = "UCM-F004-HEAD_HISTORY_ACCESS",
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    binding = {
        "candidate_bundle_digest": "sha256:" + binding_digit * 64,
        "candidate_model_digest": "sha256:" + binding_digit * 64,
        "harness_bundle_digest": "sha256:" + binding_digit * 64,
        "import_inventory_digest": "sha256:" + binding_digit * 64,
        "module_origin": "prototype/unified_map/compliance.py",
    }
    expected_candidate = (
        "prototype.unified_map.compliance:" + control_class_name
    )
    report_findings = deepcopy(findings)
    existing_codes = {row.get("failure_code") for row in report_findings}
    report_findings.extend(
        row
        for row in _fixed_scope_findings()
        if row["failure_code"] not in existing_codes
    )
    pre = _source_witness(
        binding=binding,
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        semantic_probes=semantic_probes,
    )
    post = deepcopy(pre)
    executed_source = {
        "protocol": "ucm-portable-executed-source-binding/2",
        "harness_witness": pre,
        "execution_binding": binding,
    }
    source = {
        "runner_protocol": TEST_RUNNER_PROTOCOL,
        "execution_bound_source_witness": executed_source,
        "execution_bound_source_witness_digest": digest_json(executed_source),
        "pre_source_witness_digest": digest_json(pre),
        "post_source_witness_digest": digest_json(post),
        "harness_stable_during_execution": True,
    }
    report: dict[str, object] = {
        "runner_protocol": TEST_RUNNER_PROTOCOL,
        "control_class_name": control_class_name,
        "expected_candidate": expected_candidate,
        "execution_seed": execution_seed,
        "candidate": expected_candidate,
        "operational_state_closure": (
            "pass" if outcome == "passed" else "fail"
        ),
        "semantic_unity": "incomplete",
        "isolation_completeness": "incomplete",
        "isolation_assurance": "unit-test portable boundary",
        "execution_binding": binding,
        "execution_binding_error": None,
        "harness_stable_during_execution": True,
        "pre_source_witness_digest": digest_json(pre),
        "post_source_witness_digest": digest_json(post),
        "post_source_witness_error": None,
        "findings": report_findings,
        "failure_codes": failure_codes,
        "candidate_bundle_digest": binding["candidate_bundle_digest"],
        "candidate_model_digest": binding["candidate_model_digest"],
        "harness_bundle_digest": binding["harness_bundle_digest"],
        "import_inventory_digest": binding["import_inventory_digest"],
        "module_origin": binding["module_origin"],
        "head_records": [
            {
                **binding,
                "consumed_state_hash": "sha256:" + "a" * 64,
                "isolation": "fresh-python-process-audit-v2",
                "operation": "diagnose",
                "request_digest": "sha256:" + "b" * 64,
                "response_digest": "sha256:" + "c" * 64,
                "seed": execution_seed + 1,
            },
            {
                **binding,
                "consumed_state_hash": "sha256:" + "a" * 64,
                "isolation": "fresh-python-process-audit-v2",
                "operation": "rollout",
                "request_digest": "sha256:" + "e" * 64,
                "response_digest": "sha256:" + "f" * 64,
                "seed": execution_seed + 2,
            },
            {
                **binding,
                "consumed_state_hash": "sha256:" + "a" * 64,
                "isolation": "fresh-python-process-audit-v2",
                "operation": "diagnose",
                "request_digest": "sha256:" + "b" * 64,
                "response_digest": "sha256:" + "c" * 64,
                "seed": execution_seed + 1,
            },
            {
                **binding,
                "consumed_state_hash": "sha256:" + "a" * 64,
                "isolation": "fresh-python-process-audit-v2",
                "operation": "rollout",
                "request_digest": "sha256:" + "e" * 64,
                "response_digest": "sha256:" + "f" * 64,
                "seed": execution_seed + 2,
            },
        ],
        "paired_semantic_equivalence": paired_semantic_equivalence,
    }
    if control_class_name not in REPLAY_HEAD_CONTROLS:
        report["head_records"] = []
    if operational_state_closure is not None:
        report["operational_state_closure"] = operational_state_closure
    report["head_records"].sort(
        key=lambda row: 0 if row["operation"] == "diagnose" else 1
    )
    decision: dict[str, object] = {
        "runner_protocol": TEST_RUNNER_PROTOCOL,
        "derived_outcome": outcome,
        "report_available": True,
        "harness_stable_during_execution": True,
        "execution_binding_complete": True,
    }
    if outcome == "killed":
        decision.update(
            {
                "decision_kind": "mutant-observation",
                "expected_gate": expected_gate,
                "expected_failure_code": expected_failure_code,
                "harness_incomplete": False,
                "decision_processing_complete": True,
                "actual_gate": expected_gate,
                "actual_failure_code": expected_failure_code,
            }
        )
    else:
        decision.update(
            {
                "decision_kind": "specificity-observation",
                "classification": classification,
                "probe_incomplete": False,
                "report_processing_complete": True,
                "semantic_equivalence_passed": (
                    None
                    if paired_semantic_equivalence is None
                    else paired_semantic_equivalence.get("passed") is True
                ),
            }
        )
    decisive = {
        "runner_protocol": TEST_RUNNER_PROTOCOL,
        "decision_kind": decision_kind,
        "candidate": expected_candidate,
        "source_record_payload_digest": digest_json(source),
        "report_transcript_payload_digest": digest_json(report),
        "decision_record_payload_digest": digest_json(decision),
        "runtime_metadata": deepcopy(TEST_RUNTIME_METADATA),
    }
    if outcome == "killed":
        decisive["finding"] = report_findings[0]
    else:
        decisive["classification"] = classification
    return pre, post, source, report, decision, decisive


def _bundle() -> MutationEvidenceBundle:
    builder = _builder()
    control = _decisive_raw(
        binding_digit="1",
        control_class_name="HonestSeededControl",
        execution_seed=EXPLICIT_SEED,
        outcome="passed",
        findings=[],
        failure_codes=[],
        decision_kind="specificity_pass",
        operational_state_closure="pass",
        semantic_probes=(
            "full_history_disclosure",
            "update_consistency",
            "warm_future_old_cut",
        ),
    )
    # Add in reverse lexical order; finalize must canonicalize record order.
    builder.add_record(
        subject_id="ExplicitSeedStochasticState",
        subject_kind=SubjectKind.SPECIFICITY_CONTROL,
        execution_seed=EXPLICIT_SEED,
        outcome=ObservationOutcome.PASSED,
        actual_gate=None,
        actual_failure_code=None,
        classification="ordinary_candidate",
        pre_source_witness=control[0],
        post_source_witness=control[1],
        source_record=control[2],
        report_transcript=control[3],
        error_transcript=_error_transcript([]),
        decision_record=control[4],
        decisive_record=control[5],
    )
    mutant = _decisive_raw(
        binding_digit="2",
        control_class_name="RawHistoryHeadControl",
        execution_seed=RAW_HISTORY_SEED,
        outcome="killed",
        findings=[
            {
                "gate": "C02/C09-head-history",
                "verdict": "fail",
                "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                "detail": "unit-test decisive failure",
                "evidence": {"probe": "head-history"},
            }
        ],
        failure_codes=["UCM-F004-HEAD_HISTORY_ACCESS"],
        decision_kind="mutant_kill",
    )
    builder.add_record(
        subject_id="RawHistoryHead",
        subject_kind=SubjectKind.MUTANT,
        execution_seed=RAW_HISTORY_SEED,
        outcome=ObservationOutcome.KILLED,
        actual_gate="C02",
        actual_failure_code="UCM-F004-HEAD_HISTORY_ACCESS",
        classification=None,
        pre_source_witness=mutant[0],
        post_source_witness=mutant[1],
        source_record=mutant[2],
        report_transcript=mutant[3],
        error_transcript=_error_transcript([]),
        decision_record=mutant[4],
        decisive_record=mutant[5],
    )
    return builder.finalize()


def _wire(bundle: MutationEvidenceBundle) -> dict[str, object]:
    return json.loads(bundle.canonical_bytes().decode("utf-8"))


def _resign(wire: dict[str, object]) -> bytes:
    unsigned = {key: value for key, value in wire.items() if key != "bundle_digest"}
    wire["bundle_digest"] = digest_json(unsigned)
    return canonical_json_bytes(wire)


def _record(wire: dict[str, object], subject_id: str) -> dict[str, object]:
    records = wire["records"]
    assert type(records) is list
    return next(
        item
        for item in records
        if type(item) is dict
        and type(item.get("observation")) is dict
        and item["observation"]["subject_id"] == subject_id
    )


def test_mutation_evidence_bundle_is_canonical_closed_and_content_addressed() -> None:
    bundle = _bundle()
    payload = bundle.canonical_bytes()
    parsed = MutationEvidenceBundle.from_canonical_bytes(payload)

    assert parsed == bundle
    assert parsed.canonical_bytes() == payload
    assert parsed.digest == bundle.digest
    assert parsed.benchmark_id == BENCHMARK_ID
    assert [row.subject_id for row in parsed.observations] == [
        "RawHistoryHead",
        "ExplicitSeedStochasticState",
    ]
    assert tuple(blob.digest for blob in parsed.blobs) == tuple(
        sorted(blob.digest for blob in parsed.blobs)
    )
    for blob in parsed.blobs:
        assert parsed.blob_bytes(blob.digest) == blob.payload
        assert ContentAddressedBlob.from_wire(blob.to_wire()) == blob
    assert parsed.blob_bytes(parsed.matrix_blob_digest) == evaluate_mutation_matrix(
        parsed.observations
    ).canonical_bytes()

    wire = parsed.to_wire()
    assert wire["status"] == PRE_FREEZE_STATUS
    assert wire["blockers"] == list(MUTATION_EVIDENCE_BLOCKERS)
    assert wire["freeze_grade_evidence"] is False
    assert wire["portable_isolation_complete"] is False
    assert wire["external_custody_verified"] is False


def test_bundle_parser_rejects_noncanonical_outer_or_blob_base64() -> None:
    bundle = _bundle()
    wire = _wire(bundle)
    pretty = json.dumps(wire, indent=2, ensure_ascii=False).encode("utf-8")
    with pytest.raises(ProtocolViolation, match="not canonical JSON"):
        MutationEvidenceBundle.from_canonical_bytes(pretty)

    forged = deepcopy(wire)
    blobs = forged["blobs"]
    assert type(blobs) is list and type(blobs[0]) is dict
    encoded = blobs[0]["payload_b64"]
    assert type(encoded) is str
    blobs[0]["payload_b64"] = encoded + "="
    with pytest.raises(ProtocolViolation, match="base64"):
        MutationEvidenceBundle.from_canonical_bytes(_resign(forged))


def test_bundle_rejects_missing_tampered_and_orphan_blobs() -> None:
    bundle = _bundle()
    wire = _wire(bundle)
    raw_record = _record(wire, "RawHistoryHead")

    missing = deepcopy(wire)
    missing_record = _record(missing, "RawHistoryHead")
    missing_digest = missing_record["decision_record_digest"]
    blobs = missing["blobs"]
    assert type(blobs) is list
    missing["blobs"] = [row for row in blobs if row["sha256"] != missing_digest]
    with pytest.raises(ProtocolViolation, match="blob is missing"):
        MutationEvidenceBundle.from_canonical_bytes(_resign(missing))

    tampered = deepcopy(wire)
    tampered_blobs = tampered["blobs"]
    assert type(tampered_blobs) is list
    target = next(
        row for row in tampered_blobs if row["sha256"] == raw_record["source_record_digest"]
    )
    target["payload_b64"] = base64.b64encode(b"tampered").decode("ascii")
    target["bytes"] = len(b"tampered")
    with pytest.raises(ProtocolViolation, match="sha256 does not match"):
        MutationEvidenceBundle.from_canonical_bytes(_resign(tampered))

    orphan = deepcopy(wire)
    orphan_blobs = orphan["blobs"]
    assert type(orphan_blobs) is list
    orphan_blobs.append(ContentAddressedBlob(b"orphan raw evidence").to_wire())
    orphan_blobs.sort(key=lambda row: row["sha256"])
    with pytest.raises(ProtocolViolation, match="orphan"):
        MutationEvidenceBundle.from_canonical_bytes(_resign(orphan))


@pytest.mark.parametrize(
    "field_name",
    ["decision_record_digest", "pre_source_witness_digest"],
)
def test_bundle_rejects_cross_row_blob_splicing(field_name: str) -> None:
    wire = _wire(_bundle())
    mutant = _record(wire, "RawHistoryHead")
    control = _record(wire, "ExplicitSeedStochasticState")
    mutant[field_name], control[field_name] = control[field_name], mutant[field_name]

    with pytest.raises(ProtocolViolation, match="binding mismatch"):
        MutationEvidenceBundle.from_canonical_bytes(_resign(wire))


@pytest.mark.parametrize(
    ("field_name", "forged"),
    [
        ("status", "FROZEN-v1"),
        ("blockers", []),
        ("freeze_grade_evidence", True),
        ("portable_isolation_complete", True),
        ("external_custody_verified", True),
    ],
)
def test_bundle_code_owned_pre_freeze_blockers_cannot_be_forged(
    field_name: str, forged: object
) -> None:
    wire = _wire(_bundle())
    wire[field_name] = forged
    with pytest.raises(ProtocolViolation, match="code-owned field"):
        MutationEvidenceBundle.from_canonical_bytes(_resign(wire))


def test_bundle_matrix_bytes_must_equal_registry_recomputation() -> None:
    wire = _wire(_bundle())
    old_digest = wire["matrix_blob_digest"]
    replacement = ContentAddressedBlob(canonical_json_bytes({"forged": "green"}))
    blobs = wire["blobs"]
    assert type(blobs) is list
    wire["blobs"] = [
        replacement.to_wire() if row["sha256"] == old_digest else row
        for row in blobs
    ]
    wire["blobs"].sort(key=lambda row: row["sha256"])
    wire["matrix_blob_digest"] = replacement.digest

    with pytest.raises(ProtocolViolation, match="registry recomputation"):
        MutationEvidenceBundle.from_canonical_bytes(_resign(wire))


def test_builder_rejects_false_decisive_records_and_is_single_use() -> None:
    builder = _builder()
    kwargs = {
        "subject_id": "RawHistoryHead",
        "subject_kind": SubjectKind.MUTANT,
        "execution_seed": RAW_HISTORY_SEED,
        "actual_gate": "C02",
        "actual_failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
        "classification": None,
        "pre_source_witness": {},
        "post_source_witness": {},
        "source_record": {},
        "report_transcript": {},
        "error_transcript": _error_transcript([]),
        "decision_record": {},
    }
    with pytest.raises(ProtocolViolation, match="needs decisive raw preimage"):
        builder.add_record(
            outcome=ObservationOutcome.KILLED,
            decisive_record=None,
            **kwargs,
        )
    with pytest.raises(ProtocolViolation, match="cannot supply decisive"):
        builder.add_record(
            outcome=ObservationOutcome.CRASHED,
            decisive_record={"forged": True},
            **kwargs,
        )

    empty_bundle = builder.finalize()
    assert empty_bundle.observations == ()
    with pytest.raises(RuntimeError, match="already finalized"):
        builder.finalize()


def test_crashed_record_retains_raw_error_without_counting_as_kill() -> None:
    builder = _builder()
    record = builder.add_record(
        subject_id="RawHistoryHead",
        subject_kind=SubjectKind.MUTANT,
        execution_seed=RAW_HISTORY_SEED,
        outcome=ObservationOutcome.CRASHED,
        actual_gate=None,
        actual_failure_code=None,
        classification=None,
        pre_source_witness={
            "control": "RawHistoryHeadControl",
            "execution_seed": RAW_HISTORY_SEED,
            "enabled_semantic_probes": [],
            "available": True,
        },
        post_source_witness={
            "control": "RawHistoryHeadControl",
            "execution_seed": RAW_HISTORY_SEED,
            "enabled_semantic_probes": [],
            "available": False,
        },
        source_record={"execution_binding": {}},
        report_transcript=None,
        error_transcript=_error_transcript(
            [
                {
                    "stage": "candidate-execution",
                    "exception_type": "builtins.RuntimeError",
                    "message": "worker failed",
                }
            ]
        ),
        decision_record={
            "runner_protocol": TEST_RUNNER_PROTOCOL,
            "decision_kind": "mutant-observation",
            "expected_gate": "C02",
            "expected_failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
            "report_available": False,
            "harness_stable_during_execution": False,
            "execution_binding_complete": False,
            "harness_incomplete": False,
            "decision_processing_complete": False,
            "derived_outcome": "crashed",
            "actual_gate": None,
            "actual_failure_code": None,
        },
        decisive_record=None,
    )
    bundle = builder.finalize()
    report = evaluate_mutation_matrix(bundle.observations)

    assert record.observation.decisive_record_digest is None
    assert record.report_transcript_digest is None
    error_wire = json.loads(bundle.blob_bytes(record.error_transcript_digest))
    assert error_wire["payload"]["errors"][0]["stage"] == "candidate-execution"
    assert report.valid_kills == ()
    assert "RawHistoryHead" in report.missing_or_invalid_mutants


def test_record_constructor_rejects_source_digest_relabelling() -> None:
    bundle = _bundle()
    record = bundle.records[0]
    observation = MutationObservation(
        subject_id=record.observation.subject_id,
        subject_kind=record.observation.subject_kind,
        source_digest="sha256:" + "f" * 64,
        execution_seed=record.observation.execution_seed,
        outcome=record.observation.outcome,
        actual_gate=record.observation.actual_gate,
        actual_failure_code=record.observation.actual_failure_code,
        decisive_record_digest=record.observation.decisive_record_digest,
        classification=record.observation.classification,
    )
    wire = record.to_wire()
    wire["observation"] = observation.to_wire()
    with pytest.raises(ProtocolViolation, match="source_digest"):
        type(record).from_wire(wire)


def _invalid_kill_builder(
    *,
    subject_id: str = "RawHistoryHead",
    control_class_name: str = "RawHistoryHeadControl",
    execution_seed: int = RAW_HISTORY_SEED,
    actual_gate: str = "C02",
    actual_failure_code: str = "UCM-F004-HEAD_HISTORY_ACCESS",
    pre: object | None = None,
    post: object | None = None,
    report: object | None = None,
    decision: object | None = None,
    decisive: object | None = None,
    errors: object | None = None,
    error_transcript: object | None = None,
    drop_report_fields: tuple[str, ...] = (),
    preserve_fixed_scope: bool = True,
    execution_context: dict[str, object] | None = None,
) -> MutationEvidenceBuilder:
    builder = _builder(execution_context=execution_context)
    base_pre, base_post, _, base_report, base_decision, _ = _decisive_raw(
        binding_digit="3",
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": "C02-head-history",
                "verdict": "fail",
                "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                "detail": "unit-test decisive failure",
                "evidence": {"probe": "head-history"},
            }
        ],
        failure_codes=["UCM-F004-HEAD_HISTORY_ACCESS"],
        decision_kind="mutant_kill",
        expected_gate=actual_gate,
        expected_failure_code=actual_failure_code,
    )
    pre_payload = (
        base_pre
        if pre is None
        else ({**base_pre, **pre} if type(pre) is dict else pre)
    )
    post_payload = (
        base_post
        if post is None
        else ({**base_post, **post} if type(post) is dict else post)
    )
    binding = base_report["execution_binding"]
    executed_source = {
        "protocol": "ucm-portable-executed-source-binding/2",
        "harness_witness": pre_payload,
        "execution_binding": binding,
    }
    source_payload = {
        "runner_protocol": TEST_RUNNER_PROTOCOL,
        "execution_bound_source_witness": executed_source,
        "execution_bound_source_witness_digest": digest_json(executed_source),
        "pre_source_witness_digest": digest_json(pre_payload),
        "post_source_witness_digest": digest_json(post_payload),
        "harness_stable_during_execution": pre_payload == post_payload,
    }
    if report is None:
        report_payload: object = {
            **base_report,
            "pre_source_witness_digest": digest_json(pre_payload),
            "post_source_witness_digest": digest_json(post_payload),
            "harness_stable_during_execution": pre_payload == post_payload,
        }
    elif type(report) is dict:
        report_payload = {**base_report, **report}
    else:
        report_payload = report
    if type(report_payload) is dict:
        report_findings = report_payload.get("findings")
        if type(report_findings) is list:
            if preserve_fixed_scope:
                existing_codes = {
                    finding.get("failure_code")
                    for finding in report_findings
                    if type(finding) is dict
                }
                report_findings.extend(
                    row
                    for row in _fixed_scope_findings()
                    if row["failure_code"] not in existing_codes
                )
            for index, finding in enumerate(report_findings):
                if type(finding) is dict:
                    finding.setdefault("detail", f"unit-test finding {index}")
                    finding.setdefault("evidence", {"fixture": index})
        for field_name in drop_report_fields:
            report_payload.pop(field_name, None)
    if decision is None:
        decision_payload: object = base_decision
    elif type(decision) is dict:
        decision_payload = {**base_decision, **decision}
    else:
        decision_payload = decision
    generated_decisive: dict[str, object] = {
        "runner_protocol": TEST_RUNNER_PROTOCOL,
        "decision_kind": "mutant_kill",
        "candidate": report_payload.get("candidate") if type(report_payload) is dict else "unavailable",
        "finding": (
            report_payload["findings"][0]
            if type(report_payload) is dict
            and type(report_payload.get("findings")) is list
            and report_payload["findings"]
            else {}
        ),
        "source_record_payload_digest": digest_json(source_payload),
        "report_transcript_payload_digest": digest_json(report_payload),
        "decision_record_payload_digest": digest_json(decision_payload),
        "runtime_metadata": deepcopy(TEST_RUNTIME_METADATA),
    }
    if decisive is None:
        decisive_payload: object = generated_decisive
    elif type(decisive) is dict:
        decisive_payload = {**generated_decisive, **decisive}
    else:
        decisive_payload = decisive
    builder.add_record(
        subject_id=subject_id,
        subject_kind=SubjectKind.MUTANT,
        execution_seed=execution_seed,
        outcome=ObservationOutcome.KILLED,
        actual_gate=actual_gate,
        actual_failure_code=actual_failure_code,
        classification=None,
        pre_source_witness=pre_payload,
        post_source_witness=post_payload,
        source_record=source_payload,
        report_transcript=report_payload,
        error_transcript=(
            _error_transcript([] if errors is None else errors)
            if error_transcript is None
            else error_transcript
        ),
        decision_record=decision_payload,
        decisive_record=decisive_payload,
    )
    return builder


def _invalid_pass_builder(
    *,
    subject_id: str = "ExplicitSeedStochasticState",
    control_class_name: str = "HonestSeededControl",
    execution_seed: int = EXPLICIT_SEED,
    classification: str = "ordinary_candidate",
    semantic_probes: tuple[str, ...] = (
        "full_history_disclosure",
        "update_consistency",
        "warm_future_old_cut",
    ),
    paired_semantic_equivalence: dict[str, object] | None = None,
    report: dict[str, object] | None = None,
    decision: dict[str, object] | None = None,
    decisive: dict[str, object] | None = None,
    delta: dict[str, object] | None = None,
    execution_context: dict[str, object] | None = None,
) -> MutationEvidenceBuilder:
    builder = _builder(delta=delta, execution_context=execution_context)
    pre, post, source, base_report, base_decision, base_decisive = _decisive_raw(
        binding_digit="4",
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        outcome="passed",
        findings=[],
        failure_codes=[],
        decision_kind="specificity_pass",
        operational_state_closure="pass",
        semantic_probes=semantic_probes,
        paired_semantic_equivalence=paired_semantic_equivalence,
        classification=classification,
    )
    report_payload = {**base_report, **({} if report is None else report)}
    report_findings = report_payload.get("findings")
    if type(report_findings) is list:
        for index, finding in enumerate(report_findings):
            if type(finding) is dict:
                finding.setdefault("detail", f"unit-test pass finding {index}")
                finding.setdefault("evidence", {"fixture": index})
    decision_payload = {**base_decision, **({} if decision is None else decision)}
    decisive_payload = {
        **base_decisive,
        "source_record_payload_digest": digest_json(source),
        "report_transcript_payload_digest": digest_json(report_payload),
        "decision_record_payload_digest": digest_json(decision_payload),
        **({} if decisive is None else decisive),
    }
    builder.add_record(
        subject_id=subject_id,
        subject_kind=SubjectKind.SPECIFICITY_CONTROL,
        execution_seed=execution_seed,
        outcome=ObservationOutcome.PASSED,
        actual_gate=None,
        actual_failure_code=None,
        classification=classification,
        pre_source_witness=pre,
        post_source_witness=post,
        source_record=source,
        report_transcript=report_payload,
        error_transcript=_error_transcript([]),
        decision_record=decision_payload,
        decisive_record=decisive_payload,
    )
    return builder


def test_same_row_kill_must_be_derived_from_stable_witness_and_raw_report() -> None:
    unstable = _invalid_kill_builder(
        pre={"stable": True}, post={"stable": False}
    )
    with pytest.raises(ProtocolViolation, match="unstable pre/post"):
        unstable.finalize()

    wrong_finding = _invalid_kill_builder(
        report={
            "execution_binding_error": None,
            "harness_stable_during_execution": True,
            "findings": [
                {
                    "gate": "C06-model",
                    "verdict": "fail",
                    "failure_code": "UCM-F009-MODEL_MUTATION",
                }
            ],
            "failure_codes": ["UCM-F009-MODEL_MUTATION"],
        }
    )
    with pytest.raises(ProtocolViolation, match="matching report finding"):
        wrong_finding.finalize()

    wrong_decision = _invalid_kill_builder(
        decision={"derived_outcome": "survived"}
    )
    with pytest.raises(ProtocolViolation, match="derived_outcome"):
        wrong_decision.finalize()


def test_killed_or_passed_builder_record_requires_raw_report() -> None:
    builder = _builder()
    with pytest.raises(ProtocolViolation, match="raw report transcript"):
        builder.add_record(
            subject_id="RawHistoryHead",
            subject_kind=SubjectKind.MUTANT,
            execution_seed=RAW_HISTORY_SEED,
            outcome=ObservationOutcome.KILLED,
            actual_gate="C02",
            actual_failure_code="UCM-F004-HEAD_HISTORY_ACCESS",
            classification=None,
            pre_source_witness={},
            post_source_witness={},
            source_record={},
            report_transcript=None,
            error_transcript=_error_transcript([]),
            decision_record={"derived_outcome": "killed"},
            decisive_record={"decision_kind": "mutant_kill"},
        )


def test_kill_rejects_contradictory_error_or_harness_incomplete_evidence() -> None:
    with_error = _invalid_kill_builder(
        errors=[
            {
                "stage": "candidate-execution",
                "exception_type": "builtins.RuntimeError",
                "message": "worker failed",
            }
        ]
    )
    with pytest.raises(ProtocolViolation, match="inconsistent with observation outcome"):
        with_error.finalize()

    with_e003 = _invalid_kill_builder(
        report={
            "execution_binding_error": None,
            "harness_stable_during_execution": True,
            "findings": [
                {
                    "gate": "C02-head-history",
                    "verdict": "fail",
                    "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                },
                {
                    "gate": "harness-postverify",
                    "verdict": "incomplete",
                    "failure_code": "UCM-E003-HARNESS_INCOMPLETE",
                },
            ],
            "failure_codes": ["UCM-F004-HEAD_HISTORY_ACCESS"],
        }
    )
    with pytest.raises(ProtocolViolation, match="harness-incomplete"):
        with_e003.finalize()

    with_e003_code_only = _invalid_kill_builder(
        report={
            "failure_codes": [
                "UCM-F004-HEAD_HISTORY_ACCESS",
                "UCM-E003-HARNESS_INCOMPLETE",
            ]
        }
    )
    with pytest.raises(ProtocolViolation, match="harness-incomplete"):
        with_e003_code_only.finalize()

    unbound = _invalid_kill_builder(
        report={
            "execution_binding_error": "binding mismatch",
            "harness_stable_during_execution": True,
            "findings": [
                {
                    "gate": "C02-head-history",
                    "verdict": "fail",
                    "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                }
            ],
            "failure_codes": ["UCM-F004-HEAD_HISTORY_ACCESS"],
        }
    )
    with pytest.raises(ProtocolViolation, match="execution binding"):
        unbound.finalize()


@pytest.mark.parametrize(
    "field_name",
    ["execution_binding", "execution_binding_error"],
)
def test_kill_requires_explicit_execution_binding_fields(field_name: str) -> None:
    missing_binding_field = _invalid_kill_builder(
        drop_report_fields=(field_name,)
    )
    with pytest.raises(ProtocolViolation, match="required execution fields"):
        missing_binding_field.finalize()


def test_kill_binds_code_owned_candidate_and_every_top_level_digest() -> None:
    candidate_swap = _invalid_kill_builder(
        report={"candidate": "prototype.unified_map.compliance:OtherControl"}
    )
    with pytest.raises(ProtocolViolation, match="candidate identity mismatch"):
        candidate_swap.finalize()

    top_level_drift = _invalid_kill_builder(
        report={"candidate_model_digest": "sha256:" + "9" * 64}
    )
    with pytest.raises(ProtocolViolation, match="candidate_model_digest differs"):
        top_level_drift.finalize()


def test_kill_rejects_head_record_binding_drift() -> None:
    base_report = _decisive_raw(
        binding_digit="3",
        control_class_name="GlobalSecondStateControl",
        execution_seed=TEST_BASE_SEED,
        outcome="killed",
        findings=[
            {
                "gate": "C04-update-purity",
                "verdict": "fail",
                "failure_code": "UCM-F006-HIDDEN_PATIENT_CACHE",
                "detail": "unit-test decisive failure",
                "evidence": {"probe": "hidden-state"},
            }
        ],
        failure_codes=["UCM-F006-HIDDEN_PATIENT_CACHE"],
        decision_kind="mutant_kill",
        expected_gate="C04",
        expected_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
    )[3]
    head_records = deepcopy(base_report["head_records"])
    assert type(head_records) is list and type(head_records[0]) is dict
    head_records[0]["harness_bundle_digest"] = "sha256:" + "8" * 64
    head_drift = _invalid_kill_builder(
        subject_id="GlobalSecondState",
        control_class_name="GlobalSecondStateControl",
        execution_seed=TEST_BASE_SEED,
        actual_gate="C04",
        actual_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
        report={
            "head_records": head_records,
            "findings": [
                {
                    "gate": "C04-update-purity",
                    "verdict": "fail",
                    "failure_code": "UCM-F006-HIDDEN_PATIENT_CACHE",
                }
            ],
            "failure_codes": ["UCM-F006-HIDDEN_PATIENT_CACHE"],
        },
    )

    with pytest.raises(ProtocolViolation, match="head record 0 execution binding"):
        head_drift.finalize()


def test_code_owned_subject_control_candidate_seed_gate_and_probe_mapping() -> None:
    specificity_as_mutant = _invalid_kill_builder(
        control_class_name="HonestSeededControl"
    )
    with pytest.raises(ProtocolViolation, match="code-owned subject mapping"):
        specificity_as_mutant.finalize()

    swapped_specificity = _invalid_pass_builder(
        control_class_name="BehaviorEquivalentSerializationControl"
    )
    with pytest.raises(ProtocolViolation, match="code-owned subject mapping"):
        swapped_specificity.finalize()

    forged_seed = _invalid_kill_builder(execution_seed=777)
    with pytest.raises(ProtocolViolation, match="base_seed plus code-owned row index"):
        forged_seed.finalize()

    forged_gate = _invalid_kill_builder(
        actual_gate="C09",
        report={
            "findings": [
                {
                    "gate": "C09-head-history",
                    "verdict": "fail",
                    "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                }
            ]
        },
        decision={"actual_gate": "C09", "expected_gate": "C09"},
    )
    with pytest.raises(ProtocolViolation, match="code-owned decisive gate"):
        forged_gate.finalize()

    forged_probes = _invalid_kill_builder(
        pre={"enabled_semantic_probes": ["full_history_disclosure"]},
        post={"enabled_semantic_probes": ["full_history_disclosure"]},
    )
    with pytest.raises(ProtocolViolation, match="semantic probes differ"):
        forged_probes.finalize()


def test_live_runner_source_witness_can_support_one_decisive_empty_head_row() -> None:
    from prototype.unified_map import mutation_runner

    execution_seed = RAW_HISTORY_SEED
    runtime_import_cache = mutation_runner._prepare_runtime_import_cache()
    runtime_cache_digest = digest_json(runtime_import_cache)
    witness = mutation_runner._source_binding_witness(
        "RawHistoryHeadControl",
        frozenset(),
        execution_seed=execution_seed,
        expected_runtime_import_cache_contract_digest=runtime_cache_digest,
    )
    assert {
        field_name: type(witness[field_name])
        for field_name in (
            "control_mro",
            "source_identity_anchors",
            "external_attribute_identities",
            "external_class_surfaces",
            "external_runtime_object_identities",
            "critical_alias_identities",
        )
    } == {
        "control_mro": list,
        "source_identity_anchors": list,
        "external_attribute_identities": list,
        "external_class_surfaces": list,
        "external_runtime_object_identities": list,
        "critical_alias_identities": list,
    }
    runtime_metadata = mutation_runner._runtime_metadata()
    execution_context = {
        "benchmark_id": BENCHMARK_ID,
        "runtime_metadata": runtime_metadata,
        "portable_runner_contract": mutation_evidence.portable_runner_contract(
            mutation_runner.RUNNER_PROTOCOL
        ),
        "runtime_import_cache_contract_digest": runtime_cache_digest,
        "source_preparation_error": None,
    }
    builder = MutationEvidenceBuilder(
        run_id="live-source-witness-empty-head",
        runner_protocol=mutation_runner.RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=_input_preimage(),
        execution_context=execution_context,
    )
    binding = witness["expected_live_execution_binding"]
    expected_candidate = witness["expected_candidate"]
    executed_source = {
        "protocol": "ucm-portable-executed-source-binding/2",
        "harness_witness": witness,
        "execution_binding": binding,
    }
    source = {
        "runner_protocol": mutation_runner.RUNNER_PROTOCOL,
        "execution_bound_source_witness": executed_source,
        "execution_bound_source_witness_digest": digest_json(executed_source),
        "pre_source_witness_digest": digest_json(witness),
        "post_source_witness_digest": digest_json(witness),
        "harness_stable_during_execution": True,
    }
    decisive_finding = {
        "gate": "C02-head-history",
        "verdict": "fail",
        "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
        "detail": "live-witness schema parity fixture",
        "evidence": {"fixture": "live-source-witness"},
    }
    report = {
        "runner_protocol": mutation_runner.RUNNER_PROTOCOL,
        "control_class_name": "RawHistoryHeadControl",
        "expected_candidate": expected_candidate,
        "execution_seed": execution_seed,
        "candidate": expected_candidate,
        "operational_state_closure": "fail",
        "semantic_unity": "incomplete",
        "isolation_completeness": "incomplete",
        "isolation_assurance": "live witness, portable isolation incomplete",
        "failure_codes": ["UCM-F004-HEAD_HISTORY_ACCESS"],
        **binding,
        "execution_binding": binding,
        "execution_binding_error": None,
        "pre_source_witness_digest": digest_json(witness),
        "post_source_witness_digest": digest_json(witness),
        "post_source_witness_error": None,
        "harness_stable_during_execution": True,
        "findings": [decisive_finding, *_fixed_scope_findings()],
        "head_records": [],
        "paired_semantic_equivalence": None,
    }
    decision = {
        "runner_protocol": mutation_runner.RUNNER_PROTOCOL,
        "decision_kind": "mutant-observation",
        "expected_gate": "C02",
        "expected_failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
        "report_available": True,
        "harness_stable_during_execution": True,
        "execution_binding_complete": True,
        "harness_incomplete": False,
        "decision_processing_complete": True,
        "derived_outcome": "killed",
        "actual_gate": "C02",
        "actual_failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
    }
    decisive = {
        "runner_protocol": mutation_runner.RUNNER_PROTOCOL,
        "decision_kind": "mutant_kill",
        "candidate": expected_candidate,
        "finding": decisive_finding,
        "source_record_payload_digest": digest_json(source),
        "report_transcript_payload_digest": digest_json(report),
        "decision_record_payload_digest": digest_json(decision),
        "runtime_metadata": runtime_metadata,
    }
    builder.add_record(
        subject_id="RawHistoryHead",
        subject_kind=SubjectKind.MUTANT,
        execution_seed=execution_seed,
        outcome=ObservationOutcome.KILLED,
        actual_gate="C02",
        actual_failure_code="UCM-F004-HEAD_HISTORY_ACCESS",
        classification=None,
        pre_source_witness=witness,
        post_source_witness=deepcopy(witness),
        source_record=source,
        report_transcript=report,
        error_transcript={
            "runner_protocol": mutation_runner.RUNNER_PROTOCOL,
            "status": "none",
            "errors": [],
        },
        decision_record=decision,
        decisive_record=decisive,
    )
    bundle = builder.finalize()
    assert bundle.observations[0].outcome is ObservationOutcome.KILLED


def test_execution_context_runner_contract_is_code_owned_not_caller_selected() -> None:
    exact_contract = mutation_evidence.portable_runner_contract(TEST_RUNNER_PROTOCOL)
    valid = MutationEvidenceBuilder(
        run_id="context-contract-valid",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=_input_preimage(),
        execution_context=_execution_context(),
    ).finalize()
    assert valid.observations == ()

    forged_contract = deepcopy(exact_contract)
    forged_contract["mutation_cases"][2]["control_class_name"] = (
        "HonestSeededControl"
    )
    forged = MutationEvidenceBuilder(
        run_id="context-contract-forged",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=_input_preimage(),
        execution_context={
            **_execution_context(),
            "portable_runner_contract": forged_contract,
        },
    )
    with pytest.raises(ProtocolViolation, match="code-owned registry"):
        forged.finalize()


def test_portable_registry_binds_exact_head_shapes_and_lineage_mask() -> None:
    contract = mutation_evidence.portable_runner_contract(TEST_RUNNER_PROTOCOL)
    assert contract["update_consistency_lineage_xor_mask"] == (
        mutation_evidence.UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
    )
    mutant_shapes = {
        row["matrix_subject_id"]: row["head_record_shape"]
        for row in contract["mutation_cases"]
    }
    assert mutant_shapes == {
        "GlobalSecondState": "replay_ddrr",
        "FileHandleState": "empty",
        "RawHistoryHead": "empty",
        "TrainerTargetSmuggler": "empty",
        "QueryReencoder": "empty",
        "MutableCheckpoint": "empty",
        "TrueStateReader": "empty",
        "FutureReader": "empty",
        "CounterfactualMutator": "empty",
        "ImplicitRNGState": "replay_ddrr",
        "HistoryInBlob": "replay_ddrr",
        "WarmFutureCache": "replay_ddrr",
        "ReplayBatchDivergence": "replay_ddrr",
        "DoubleCountEvent": "replay_ddrr",
    }
    assert [row["head_record_shape"] for row in contract["specificity_cases"]] == [
        "replay_ddrr",
        "replay_ddrr",
        "replay_ddrr",
    ]

    forged_contract = deepcopy(contract)
    forged_contract["update_consistency_lineage_xor_mask"] ^= 1
    forged = MutationEvidenceBuilder(
        run_id="context-lineage-mask-forged",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=_input_preimage(),
        execution_context={
            **_execution_context(),
            "portable_runner_contract": forged_contract,
        },
    )
    with pytest.raises(ProtocolViolation, match="code-owned registry"):
        forged.finalize()


def test_builder_and_parser_reject_every_code_owned_seed_overflow_boundary() -> None:
    row_count = 17
    operation_overflow_base = 2**64 - ((row_count - 1) + 3)
    with pytest.raises(ProtocolViolation, match="derived operation seeds"):
        MutationEvidenceBuilder(
            run_id="operation-seed-overflow",
            runner_protocol=TEST_RUNNER_PROTOCOL,
            base_seed=operation_overflow_base,
            input_preimage=_input_preimage(),
            execution_context=_execution_context(),
        )

    contract = mutation_evidence.portable_runner_contract(TEST_RUNNER_PROTOCOL)
    all_rows = contract["mutation_cases"] + contract["specificity_cases"]
    update_index = next(
        index
        for index, row in enumerate(all_rows)
        if "update_consistency" in row["semantic_probes"]
    )
    lineage_execution_seed = (
        (2**64 - 1)
        ^ mutation_evidence.UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
    )
    lineage_overflow_base = lineage_execution_seed - update_index
    with pytest.raises(ProtocolViolation, match="update-consistency lineage seeds"):
        MutationEvidenceBuilder(
            run_id="lineage-seed-overflow",
            runner_protocol=TEST_RUNNER_PROTOCOL,
            base_seed=lineage_overflow_base,
            input_preimage=_input_preimage(),
            execution_context=_execution_context(),
        )

    forged_wire = _wire(_bundle())
    forged_wire["base_seed"] = operation_overflow_base
    with pytest.raises(ProtocolViolation, match="derived operation seeds"):
        MutationEvidenceBundle.from_canonical_bytes(_resign(forged_wire))


def test_input_and_execution_context_payloads_are_exact_runner_preimages() -> None:
    hidden_input = MutationEvidenceBuilder(
        run_id="hidden-input-field",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage={**_input_preimage(), "hidden": True},
        execution_context=_execution_context(),
    )
    with pytest.raises(ProtocolViolation, match="input preimage payload.*closed"):
        hidden_input.finalize()

    missing_context_contract = _execution_context()
    missing_context_contract.pop("portable_runner_contract")
    hidden_context = MutationEvidenceBuilder(
        run_id="missing-context-contract",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=_input_preimage(),
        execution_context=missing_context_contract,
    )
    with pytest.raises(ProtocolViolation, match="execution context payload.*closed"):
        hidden_context.finalize()

    malformed_cache_context = _execution_context()
    malformed_cache_context["runtime_import_cache_contract_digest"] = None
    malformed_cache = MutationEvidenceBuilder(
        run_id="malformed-runtime-cache",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=_input_preimage(),
        execution_context=malformed_cache_context,
    )
    with pytest.raises(ProtocolViolation, match="runtime import cache contract digest"):
        malformed_cache.finalize()


def test_source_preparation_failure_cannot_be_promoted_to_a_decisive_outcome() -> None:
    failed_context = _execution_context()
    failed_context["runtime_import_cache_contract_digest"] = None
    failed_context["source_preparation_error"] = {
        "stage": "runtime-import-preparation",
        "exception_type": "builtins.RuntimeError",
        "message": "preparation failed",
    }
    empty = MutationEvidenceBuilder(
        run_id="source-preparation-failed-empty",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=_input_preimage(),
        execution_context=failed_context,
    ).finalize()
    assert empty.observations == ()

    forged_kill = _invalid_kill_builder(execution_context=failed_context)
    with pytest.raises(ProtocolViolation, match="must produce a crashed observation"):
        forged_kill.finalize()


def test_head_records_require_exact_four_record_replay_sequence() -> None:
    base_report = _decisive_raw(
        binding_digit="3",
        control_class_name="GlobalSecondStateControl",
        execution_seed=TEST_BASE_SEED,
        outcome="killed",
        findings=[
            {
                "gate": "C04-update-purity",
                "verdict": "fail",
                "failure_code": "UCM-F006-HIDDEN_PATIENT_CACHE",
                "detail": "unit-test decisive failure",
                "evidence": {},
            }
        ],
        failure_codes=["UCM-F006-HIDDEN_PATIENT_CACHE"],
        decision_kind="mutant_kill",
        expected_gate="C04",
        expected_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
    )[3]
    heads = deepcopy(base_report["head_records"])
    assert type(heads) is list and len(heads) == 4
    variants = (
        ([], "exact DDRR replay shape"),
        (heads[:3], "exact DDRR replay shape"),
        (heads + [deepcopy(heads[-1])], "exact DDRR replay shape"),
        (
            [deepcopy(heads[0]), deepcopy(heads[1]), deepcopy(heads[1]), deepcopy(heads[2])],
            "exact replay operation/seed sequence",
        ),
        (
            [deepcopy(heads[2]), deepcopy(heads[1]), deepcopy(heads[0]), deepcopy(heads[3])],
            "exact replay operation/seed sequence",
        ),
    )
    for variant, message in variants:
        invalid = _invalid_kill_builder(
            subject_id="GlobalSecondState",
            control_class_name="GlobalSecondStateControl",
            execution_seed=TEST_BASE_SEED,
            actual_gate="C04",
            actual_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
            report={
                "head_records": variant,
                "findings": [
                    {
                        "gate": "C04-update-purity",
                        "verdict": "fail",
                        "failure_code": "UCM-F006-HIDDEN_PATIENT_CACHE",
                    }
                ],
                "failure_codes": ["UCM-F006-HIDDEN_PATIENT_CACHE"],
            },
        )
        with pytest.raises(ProtocolViolation, match=message):
            invalid.finalize()


@pytest.mark.parametrize(
    ("field_name", "message"),
    [
        ("request_digest", "request/state/binding drifted"),
        ("response_digest", "response drift lacks"),
    ],
)
def test_non_f020_replay_kill_rejects_pair_request_or_response_drift(
    field_name: str,
    message: str,
) -> None:
    base_report = _decisive_raw(
        binding_digit="3",
        control_class_name="GlobalSecondStateControl",
        execution_seed=TEST_BASE_SEED,
        outcome="killed",
        findings=[
            {
                "gate": "C04-update-purity",
                "verdict": "fail",
                "failure_code": "UCM-F006-HIDDEN_PATIENT_CACHE",
                "detail": "unit-test decisive failure",
                "evidence": {},
            }
        ],
        failure_codes=["UCM-F006-HIDDEN_PATIENT_CACHE"],
        decision_kind="mutant_kill",
        expected_gate="C04",
        expected_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
    )[3]
    heads = deepcopy(base_report["head_records"])
    assert type(heads) is list and len(heads) == 4
    heads[1][field_name] = "sha256:" + "9" * 64
    invalid = _invalid_kill_builder(
        subject_id="GlobalSecondState",
        control_class_name="GlobalSecondStateControl",
        execution_seed=TEST_BASE_SEED,
        actual_gate="C04",
        actual_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
        report={
            "head_records": heads,
            "findings": [
                {
                    "gate": "C04-update-purity",
                    "verdict": "fail",
                    "failure_code": "UCM-F006-HIDDEN_PATIENT_CACHE",
                }
            ],
            "failure_codes": ["UCM-F006-HIDDEN_PATIENT_CACHE"],
        },
    )
    with pytest.raises(ProtocolViolation, match=message):
        invalid.finalize()


def test_f020_subject_allows_pair_response_drift_with_canonical_failure() -> None:
    execution_seed = TEST_BASE_SEED + 9
    base_report = _decisive_raw(
        binding_digit="3",
        control_class_name="ImplicitRNGControl",
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": "C30-reproducibility",
                "verdict": "fail",
                "failure_code": "UCM-F020-NONREPRODUCIBLE",
                "detail": "unit-test decisive failure",
                "evidence": {},
            }
        ],
        failure_codes=["UCM-F020-NONREPRODUCIBLE"],
        decision_kind="mutant_kill",
        expected_gate="C30",
        expected_failure_code="UCM-F020-NONREPRODUCIBLE",
    )[3]
    heads = deepcopy(base_report["head_records"])
    assert type(heads) is list and len(heads) == 4
    heads[1]["response_digest"] = "sha256:" + "9" * 64
    allowed = _invalid_kill_builder(
        subject_id="ImplicitRNGState",
        control_class_name="ImplicitRNGControl",
        execution_seed=execution_seed,
        actual_gate="C30",
        actual_failure_code="UCM-F020-NONREPRODUCIBLE",
        report={
            "head_records": heads,
            "findings": [
                {
                    "gate": "C30-reproducibility",
                    "verdict": "fail",
                    "failure_code": "UCM-F020-NONREPRODUCIBLE",
                }
            ],
            "failure_codes": ["UCM-F020-NONREPRODUCIBLE"],
        },
    )
    assert allowed.finalize().observations[0].outcome is ObservationOutcome.KILLED


def test_kill_rejects_non_scope_incomplete_and_requires_fixed_boundaries() -> None:
    target = {
        "gate": "C02-head-history",
        "verdict": "fail",
        "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
    }
    for failure_code in (None, "UCM-E099-DETECTOR_INCOMPLETE"):
        invalid = _invalid_kill_builder(
            report={
                "findings": [
                    deepcopy(target),
                    {
                        "gate": "detector-incomplete",
                        "verdict": "incomplete",
                        "failure_code": failure_code,
                    },
                ]
            }
        )
        with pytest.raises(ProtocolViolation, match="non-scope incomplete"):
            invalid.finalize()

    missing_scope = _invalid_kill_builder(
        report={"findings": [deepcopy(target)]},
        preserve_fixed_scope=False,
    )
    with pytest.raises(ProtocolViolation, match="exact fixed scope findings"):
        missing_scope.finalize()

    false_semantic_boundary = _invalid_kill_builder(
        report={"semantic_unity": "pass"}
    )
    with pytest.raises(ProtocolViolation, match="semantic-unity incompleteness"):
        false_semantic_boundary.finalize()

    wrong_closure = _invalid_kill_builder(
        report={"operational_state_closure": "pass"}
    )
    with pytest.raises(ProtocolViolation, match="operational closure FAIL"):
        wrong_closure.finalize()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"runner_protocol": "other-runner", "status": "none", "errors": []},
            "runner_protocol differs",
        ),
        (
            {
                "runner_protocol": TEST_RUNNER_PROTOCOL,
                "status": "none",
                "errors": [],
                "hidden": True,
            },
            "closed object",
        ),
        (
            {
                "runner_protocol": TEST_RUNNER_PROTOCOL,
                "status": "error",
                "errors": [],
            },
            "status differs",
        ),
    ],
)
def test_error_transcript_payload_is_closed_and_outcome_bound(
    payload: dict[str, object], message: str
) -> None:
    invalid = _invalid_kill_builder(error_transcript=payload)
    with pytest.raises(ProtocolViolation, match=message):
        invalid.finalize()


def test_decision_payload_is_closed_without_hidden_contradictions() -> None:
    invalid = _invalid_kill_builder(decision={"probe_incomplete": True})
    with pytest.raises(ProtocolViolation, match="closed object"):
        invalid.finalize()


def test_execution_binding_origin_is_the_code_owned_control_module() -> None:
    invalid = _invalid_kill_builder(
        report={
            "module_origin": "prototype/unified_map/candidate_impl.py",
            "execution_binding": {
                "candidate_bundle_digest": "sha256:" + "3" * 64,
                "candidate_model_digest": "sha256:" + "3" * 64,
                "harness_bundle_digest": "sha256:" + "3" * 64,
                "import_inventory_digest": "sha256:" + "3" * 64,
                "module_origin": "prototype/unified_map/candidate_impl.py",
            },
        },
        pre={
            "expected_live_execution_binding": {
                "candidate_bundle_digest": "sha256:" + "3" * 64,
                "candidate_model_digest": "sha256:" + "3" * 64,
                "harness_bundle_digest": "sha256:" + "3" * 64,
                "import_inventory_digest": "sha256:" + "3" * 64,
                "module_origin": "prototype/unified_map/candidate_impl.py",
            }
        },
        post={
            "expected_live_execution_binding": {
                "candidate_bundle_digest": "sha256:" + "3" * 64,
                "candidate_model_digest": "sha256:" + "3" * 64,
                "harness_bundle_digest": "sha256:" + "3" * 64,
                "import_inventory_digest": "sha256:" + "3" * 64,
                "module_origin": "prototype/unified_map/candidate_impl.py",
            }
        },
    )
    with pytest.raises(ProtocolViolation, match="code-owned control module"):
        invalid.finalize()


def test_failure_codes_decision_and_decisive_payloads_are_semantically_closed() -> None:
    missing_failed_code = _invalid_kill_builder(report={"failure_codes": []})
    with pytest.raises(ProtocolViolation, match="failure_codes do not equal"):
        missing_failed_code.finalize()

    decision_drift = _invalid_kill_builder(decision={"actual_gate": "C03"})
    with pytest.raises(ProtocolViolation, match="decision actual_gate mismatch"):
        decision_drift.finalize()

    decisive_candidate_drift = _invalid_kill_builder(
        decisive={"candidate": "prototype.unified_map.compliance:OtherControl"}
    )
    with pytest.raises(ProtocolViolation, match="decisive candidate mismatch"):
        decisive_candidate_drift.finalize()

    decisive_digest_drift = _invalid_kill_builder(
        decisive={"report_transcript_payload_digest": "sha256:" + "7" * 64}
    )
    with pytest.raises(ProtocolViolation, match="does not bind its raw payload"):
        decisive_digest_drift.finalize()

    duplicate_decisive_code = _invalid_kill_builder(
        report={
            "findings": [
                {
                    "gate": "C02-head-history",
                    "verdict": "fail",
                    "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                },
                {
                    "gate": "C09-head-history",
                    "verdict": "fail",
                    "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                },
            ],
            "failure_codes": ["UCM-F004-HEAD_HISTORY_ACCESS"],
        }
    )
    with pytest.raises(ProtocolViolation, match="exactly one.*report finding"):
        duplicate_decisive_code.finalize()


def test_specificity_pass_allows_only_fixed_scope_incomplete_findings() -> None:
    fixed_scope = _invalid_pass_builder(
        report={
            "findings": [
                {
                    "gate": "semantic-unity-boundary",
                    "verdict": "incomplete",
                    "failure_code": "UCM-E001-SEMANTIC_UNITY_UNVERIFIED",
                },
                {
                    "gate": "portable-isolation-boundary",
                    "verdict": "incomplete",
                    "failure_code": "UCM-E002-ISOLATION_INCOMPLETE",
                },
            ]
        }
    )
    assert fixed_scope.finalize().observations[0].outcome is ObservationOutcome.PASSED

    detector_incomplete = _invalid_pass_builder(
        report={
            "findings": [
                {
                    "gate": "C04-detector",
                    "verdict": "incomplete",
                    "failure_code": "UCM-E099-DETECTOR_INCOMPLETE",
                }
            ]
        }
    )
    with pytest.raises(ProtocolViolation, match="non-scope incomplete"):
        detector_incomplete.finalize()


def test_behavior_equivalent_pass_requires_input_bound_paired_phases() -> None:
    initialize_only = _invalid_pass_builder(
        subject_id="BehaviorEquivalentSerialization",
        control_class_name="BehaviorEquivalentSerializationControl",
        execution_seed=BEHAVIOR_SEED,
        semantic_probes=("update_consistency",),
        paired_semantic_equivalence=_paired_semantic_evidence(),
    )
    assert (
        initialize_only.finalize().observations[0].outcome
        is ObservationOutcome.PASSED
    )

    missing = _invalid_pass_builder(
        subject_id="BehaviorEquivalentSerialization",
        control_class_name="BehaviorEquivalentSerializationControl",
        execution_seed=BEHAVIOR_SEED,
        semantic_probes=("update_consistency",),
    )
    with pytest.raises(ProtocolViolation, match="lacks closed paired evidence"):
        missing.finalize()

    incomplete_update = _invalid_pass_builder(
        subject_id="BehaviorEquivalentSerialization",
        control_class_name="BehaviorEquivalentSerializationControl",
        execution_seed=BEHAVIOR_SEED,
        semantic_probes=("update_consistency",),
        paired_semantic_equivalence=_paired_semantic_evidence(),
        delta={"events": [{"event_uid": "event-b"}]},
    )
    with pytest.raises(ProtocolViolation, match="lacks closed paired evidence"):
        incomplete_update.finalize()

    full_update = _invalid_pass_builder(
        subject_id="BehaviorEquivalentSerialization",
        control_class_name="BehaviorEquivalentSerializationControl",
        execution_seed=BEHAVIOR_SEED,
        semantic_probes=("update_consistency",),
        paired_semantic_equivalence=_paired_semantic_evidence(
            include_update=True
        ),
        delta={"events": [{"event_uid": "event-b"}]},
    )
    assert full_update.finalize().observations[0].outcome is ObservationOutcome.PASSED


@pytest.mark.parametrize(
    ("report_patch", "decision_patch", "message"),
    [
        ({"operational_state_closure": "fail"}, {}, "operational closure PASS"),
        ({"semantic_unity": "fail"}, {}, "semantic-unity incompleteness"),
        ({"isolation_completeness": "fail"}, {}, "isolation incompleteness"),
        ({"findings": []}, {}, "exact fixed scope findings"),
        (
            {"paired_semantic_equivalence": {"passed": False}},
            {"semantic_equivalence_passed": False},
            "cannot carry paired evidence",
        ),
        ({}, {"classification": "forged"}, "classification mismatch"),
        (
            {},
            {},
            "specificity decisive runtime metadata differs",
        ),
    ],
)
def test_specificity_pass_semantics_are_closed(
    report_patch: dict[str, object],
    decision_patch: dict[str, object],
    message: str,
) -> None:
    decisive_patch = (
        {"runtime_metadata": {"forged": True}}
        if message == "specificity decisive runtime metadata differs"
        else None
    )
    builder = _invalid_pass_builder(
        report=report_patch,
        decision=decision_patch,
        decisive=decisive_patch,
    )
    with pytest.raises(ProtocolViolation, match=message):
        builder.finalize()


def test_invalid_unicode_surrogate_is_a_typed_protocol_violation() -> None:
    with pytest.raises(ProtocolViolation, match="Unicode surrogate"):
        mutation_evidence._decode_canonical_json(  # type: ignore[attr-defined]
            b'{"bad":"\\ud800"}\n', "surrogate fixture"
        )
    with pytest.raises(ProtocolViolation, match="Unicode surrogate"):
        MutationEvidenceBuilder(
            run_id="surrogate-run",
            runner_protocol="runner/unit",
            base_seed=1,
            input_preimage={"bad": "\ud800"},
            execution_context={},
        )


@pytest.mark.parametrize(
    "payload",
    [
        b"[" * 2000 + b"0" + b"]" * 2000,
        b'{"integer":' + b"1" * 5000 + b"}\n",
    ],
)
def test_pathological_json_parse_errors_are_typed_protocol_violations(
    payload: bytes,
) -> None:
    with pytest.raises(
        ProtocolViolation,
        match="not UTF-8 JSON|must be a JSON object",
    ):
        mutation_evidence._decode_canonical_json(  # type: ignore[attr-defined]
            payload, "pathological fixture"
        )
