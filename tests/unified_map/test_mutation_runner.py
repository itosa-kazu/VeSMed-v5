from __future__ import annotations

import functools
import inspect
import json
import subprocess
import sys
import types
from dataclasses import make_dataclass
from enum import Enum

import pytest

from prototype.unified_map import (
    candidate_protocol,
    canonical,
    compliance,
    metrics,
    mutation_evidence,
    mutation_matrix,
    mutation_runner,
)
from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.compliance import (
    ComplianceVerdict,
    HistoryInBlobControl,
    control_entrypoint,
    evaluate_candidate_compliance,
)
from prototype.unified_map.mutation_matrix import evaluate_mutation_matrix
from prototype.unified_map.mutation_runner import (
    _live_callable_digest,
    _source_digest,
    _specificity_report_eligible,
    paired_serialization_equivalence_evidence,
    run_portable_mutation_evidence,
)
from prototype.unified_map.schema import (
    ActionPlan,
    CandidateVisibleEvent,
    DiagnosisQuery,
    EventKind,
    PlanKind,
    PlannedAction,
    RolloutQuery,
    VisibleDelta,
    VisibleHistory,
)
from prototype.unified_map.state import StateClass, StatePayload


CATALOG = "sha256:" + "c" * 64
UTILITY = "sha256:" + "d" * 64


def inputs() -> tuple[VisibleHistory, DiagnosisQuery, RolloutQuery, VisibleDelta]:
    event = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        occurred_at=0,
        available_at=0,
        event_uid="portable-mutation-initial",
        payload={"signal": 0.88},
    )
    follow_up = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        occurred_at=1,
        available_at=1,
        event_uid="portable-mutation-update",
        payload={"signal": 0.24},
    )
    return (
        VisibleHistory((event,), 0, CATALOG),
        DiagnosisQuery(("a", "b")),
        RolloutQuery(
            2,
            ActionPlan(PlanKind.NO_NEW_ACTION),
            ("x",),
            UTILITY,
        ),
        VisibleDelta(1, (follow_up,)),
    )


def mutable_nested_inputs() -> tuple[
    VisibleHistory, DiagnosisQuery, RolloutQuery, VisibleDelta
]:
    event = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        occurred_at=0,
        available_at=0,
        event_uid="portable-mutation-nested-initial",
        payload={"nested": {"value": "captured"}},
    )
    follow_up = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        occurred_at=1,
        available_at=1,
        event_uid="portable-mutation-nested-update",
        payload={"nested": {"value": "captured-delta"}},
    )
    return (
        VisibleHistory((event,), 0, CATALOG),
        DiagnosisQuery(("a", "b")),
        RolloutQuery(
            2,
            ActionPlan(
                PlanKind.ACTION_SEQUENCE,
                (
                    PlannedAction(
                        0,
                        "dose",
                        {"nested": {"amount": 1}},
                    ),
                ),
            ),
            ("x",),
            UTILITY,
        ),
        VisibleDelta(1, (follow_up,)),
    )


def _blob_payload(
    bundle: mutation_evidence.MutationEvidenceBundle, digest: str
) -> dict:
    body = json.loads(bundle.blob_bytes(digest).decode("utf-8"))
    return body["payload"]


def test_portable_mutants_emit_real_decisive_records_and_control_passes() -> None:
    history, diagnosis, rollout, delta = inputs()
    bundle = run_portable_mutation_evidence(
        run_id="portable-real-evidence-701",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=701,
    )
    rows = bundle.observations
    by_id = {row.subject_id: row for row in rows}
    assert by_id["GlobalSecondState"].actual_failure_code == (
        "UCM-F006-HIDDEN_PATIENT_CACHE"
    )
    assert by_id["FileHandleState"].actual_failure_code == (
        "UCM-F008-STATE_NOT_CLOSED"
    )
    assert by_id["RawHistoryHead"].actual_failure_code == (
        "UCM-F004-HEAD_HISTORY_ACCESS"
    )
    assert by_id["TrainerTargetSmuggler"].actual_failure_code == (
        "UCM-F002-ORACLE_TRUE_STATE_ACCESS"
    )
    assert by_id["QueryReencoder"].actual_failure_code == (
        "UCM-F004-HEAD_HISTORY_ACCESS"
    )
    assert by_id["CounterfactualMutator"].actual_failure_code == (
        "UCM-F012-QUERY_MUTATES_FACT"
    )
    assert by_id["MutableCheckpoint"].actual_failure_code == (
        "UCM-F009-MODEL_MUTATION"
    )
    assert by_id["TrueStateReader"].actual_failure_code == (
        "UCM-F002-ORACLE_TRUE_STATE_ACCESS"
    )
    assert by_id["FutureReader"].actual_failure_code == "UCM-F001-FUTURE_LEAK"
    assert by_id["ImplicitRNGState"].actual_failure_code == (
        "UCM-F020-NONREPRODUCIBLE"
    )
    assert by_id["HistoryInBlob"].actual_failure_code == (
        "UCM-F018-FULL_HISTORY_MISCLAIM"
    )
    assert by_id["WarmFutureCache"].actual_failure_code == "UCM-F001-FUTURE_LEAK"
    assert by_id["ReplayBatchDivergence"].actual_failure_code == (
        "UCM-F019-UPDATE_INCONSISTENT"
    )
    assert by_id["DoubleCountEvent"].actual_failure_code == (
        "UCM-F019-UPDATE_INCONSISTENT"
    )
    assert all(row.decisive_record_digest is not None for row in rows)
    assert by_id["ExplicitSeedStochasticState"].outcome.value == "passed"
    assert by_id["BehaviorEquivalentSerialization"].outcome.value == "passed"
    assert by_id["DeclaredFullHistoryBaseline"].outcome.value == "passed"

    assert isinstance(bundle, mutation_evidence.MutationEvidenceBundle)
    assert bundle.benchmark_id == mutation_evidence.BENCHMARK_ID
    assert mutation_evidence.MutationEvidenceBundle.from_canonical_bytes(
        bundle.canonical_bytes()
    ) == bundle
    wire = bundle.to_wire()
    assert wire["status"] == "PRE-FREEZE"
    assert wire["blockers"] == [
        "UCM-E002-ISOLATION_INCOMPLETE",
        "UCM-E003-HARNESS_INCOMPLETE",
    ]
    context = json.loads(
        bundle.blob_bytes(bundle.execution_context_digest).decode("utf-8")
    )
    code_owned_contract = mutation_evidence.portable_runner_contract(
        mutation_runner.RUNNER_PROTOCOL
    )
    assert context["payload"]["portable_runner_contract"] == code_owned_contract
    head_shape_by_subject = {
        row["matrix_subject_id"]: row["head_record_shape"]
        for row in code_owned_contract["mutation_cases"]
    } | {
        row["subject_id"]: row["head_record_shape"]
        for row in code_owned_contract["specificity_cases"]
    }
    input_preimage = json.loads(
        bundle.blob_bytes(context["input_preimage_digest"]).decode("utf-8")
    )
    assert input_preimage["payload"] == {
        "history": history.to_wire(),
        "diagnosis_query": diagnosis.to_wire(),
        "rollout_query": rollout.to_wire(),
        "delta": delta.to_wire(),
    }
    for record in bundle.records:
        observation = record.observation
        pre = _blob_payload(bundle, record.pre_source_witness_digest)
        post = _blob_payload(bundle, record.post_source_witness_digest)
        source = _blob_payload(bundle, record.source_record_digest)
        report_payload = _blob_payload(bundle, record.report_transcript_digest)
        error = _blob_payload(bundle, record.error_transcript_digest)
        decision = _blob_payload(bundle, record.decision_record_digest)
        decisive = _blob_payload(bundle, observation.decisive_record_digest)
        assert pre == post
        assert pre["expected_candidate"] == report_payload["expected_candidate"]
        assert report_payload["candidate"] == report_payload["expected_candidate"]
        assert report_payload["execution_seed"] == observation.execution_seed
        assert report_payload["input_preimage_digest"] == context[
            "input_preimage_digest"
        ]
        assert report_payload["request_records"]
        assert report_payload["invocation_transcript_digest"] == canonical.digest_json(
            report_payload["request_records"]
        )
        assert decision["input_preimage_digest"] == context["input_preimage_digest"]
        assert (
            decision["invocation_transcript_digest"]
            == report_payload["invocation_transcript_digest"]
        )
        assert decisive["input_preimage_digest"] == context["input_preimage_digest"]
        assert (
            decisive["invocation_transcript_digest"]
            == report_payload["invocation_transcript_digest"]
        )
        expected_head_shape = head_shape_by_subject[observation.subject_id]
        if expected_head_shape == "empty":
            assert report_payload["head_records"] == []
        else:
            assert sorted(
                (row["operation"], row["seed"])
                for row in report_payload["head_records"]
            ) == sorted(
                [
                    ("diagnose", observation.execution_seed + 1),
                    ("diagnose", observation.execution_seed + 1),
                    ("rollout", observation.execution_seed + 2),
                    ("rollout", observation.execution_seed + 2),
                ]
            )
        assert source["harness_stable_during_execution"] is True
        assert error == {
            "runner_protocol": mutation_runner.RUNNER_PROTOCOL,
            "status": "none",
            "errors": [],
        }
        assert decision["derived_outcome"] == observation.outcome.value
        assert decisive["source_record_payload_digest"] == canonical.digest_json(
            source
        )
        assert decisive["report_transcript_payload_digest"] == canonical.digest_json(
            report_payload
        )
        assert decisive["decision_record_payload_digest"] == canonical.digest_json(
            decision
        )


def test_partial_real_evidence_remains_harness_incomplete() -> None:
    history, diagnosis, rollout, delta = inputs()
    bundle = run_portable_mutation_evidence(
        run_id="portable-partial-evidence-733",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=733,
    )
    report = evaluate_mutation_matrix(
        bundle.observations
    )
    assert not report.freeze_ready
    assert report.benchmark_status == "HARNESS_INCOMPLETE"
    assert len(report.valid_kills) == 17
    assert len(report.missing_or_invalid_mutants) == 9
    assert len(report.passed_specificity_controls) == 4
    assert len(report.failed_specificity_controls) == 0
    assert len(report.covered_gates) == 13
    assert len(report.uncovered_gates) == 20
    assert set(report.valid_kills) == {
        "GlobalSecondState",
        "FileHandleState",
        "RawHistoryHead",
        "TrainerTargetSmuggler",
        "QueryReencoder",
        "MutableCheckpoint",
        "TrueStateReader",
        "FutureReader",
        "CounterfactualMutator",
        "ImplicitRNGState",
        "HistoryInBlob",
        "WarmFutureCache",
        "ReplayBatchDivergence",
        "DoubleCountEvent",
        "NonIdPointEstimate",
        "DangerousMeanCompressor",
        "UnsafeClosedWorld",
    }
    assert set(report.covered_gates) == {
        "C02",
        "C04",
        "C06",
        "C07",
        "C08",
        "C16",
        "C22",
        "C23",
        "C27",
        "C30",
        "C19",
        "C24",
        "C25",
    }
    assert set(report.passed_specificity_controls) == {
        "ExplicitSeedStochasticState",
        "BehaviorEquivalentSerialization",
        "DeclaredFullHistoryBaseline",
        "CorrectNonidentifiedSet",
    }


def test_new_detectors_distinguish_attacks_from_benign_counterparts() -> None:
    history, diagnosis, rollout, delta = inputs()

    def report(control: str):
        return evaluate_candidate_compliance(
            control_entrypoint(control),
            history=history,
            diagnosis_query=diagnosis,
            rollout_query=rollout,
            delta=delta,
            seed=811,
            semantic_probes=frozenset(
                {
                    "full_history_disclosure",
                    "update_consistency",
                    "warm_future_old_cut",
                }
            ),
        )

    history_attack = report("HistoryInBlobControl")
    declared_history = report("DeclaredFullHistoryBaselineControl")
    assert "UCM-F018-FULL_HISTORY_MISCLAIM" in history_attack.failure_codes
    compressed_payload = HistoryInBlobControl().initialize(history, inference_seed=811)
    assert b"portable-mutation-initial" not in compressed_payload.payload
    assert b"ucm-visible-history/1" not in compressed_payload.payload
    history_finding = next(
        finding
        for finding in history_attack.findings
        if finding.failure_code == "UCM-F018-FULL_HISTORY_MISCLAIM"
    )
    assert history_finding.evidence["recovery_method"] == "base64-zlib-json"
    assert "UCM-F018-FULL_HISTORY_MISCLAIM" not in declared_history.failure_codes
    assert declared_history.operational_state_closure is ComplianceVerdict.PASS
    assert any(
        finding.gate == "C27-fixed-codec-full-history-disclosure"
        and finding.verdict is ComplianceVerdict.PASS
        for finding in declared_history.findings
    )

    warm_attack = report("WarmFutureCacheControl")
    honest = report("HonestSeededControl")
    assert "UCM-F001-FUTURE_LEAK" in warm_attack.failure_codes
    warm_finding = next(
        finding
        for finding in warm_attack.findings
        if finding.failure_code == "UCM-F001-FUTURE_LEAK"
    )
    assert warm_finding.evidence["before_behavior_digest"] != (
        warm_finding.evidence["after_initialize_later_digest"]
    )
    assert warm_finding.evidence["before_behavior_digest"] != (
        warm_finding.evidence["after_update_old_delta_digest"]
    )
    assert warm_finding.evidence["before_raw_wire_digest"] != (
        warm_finding.evidence["after_initialize_later_raw_wire_digest"]
    )
    assert warm_finding.evidence["before_raw_wire_digest"] != (
        warm_finding.evidence["after_update_old_delta_raw_wire_digest"]
    )
    assert warm_finding.evidence["initialize_later_stable"] is False
    assert warm_finding.evidence["update_old_delta_stable"] is False
    assert warm_finding.evidence["initialize_later_raw_exact"] is False
    assert warm_finding.evidence["update_old_delta_raw_exact"] is False
    assert len(warm_finding.evidence["before_head_transcript"]) == 2
    assert len(warm_finding.evidence["initialize_later_transcript"]) == 3
    assert len(warm_finding.evidence["update_old_delta_transcript"]) == 4
    assert all(
        row["request_digest"].startswith("sha256:")
        and row["response_digest"].startswith("sha256:")
        for key in (
            "before_head_transcript",
            "initialize_later_transcript",
            "update_old_delta_transcript",
        )
        for row in warm_finding.evidence[key]
    )
    assert "UCM-F001-FUTURE_LEAK" not in honest.failure_codes
    assert "UCM-F019-UPDATE_INCONSISTENT" not in honest.failure_codes

    replay_attack = report("ReplayBatchDivergenceControl")
    replay_finding = next(
        finding
        for finding in replay_attack.findings
        if finding.failure_code == "UCM-F019-UPDATE_INCONSISTENT"
    )
    assert replay_finding.evidence["incremental_equals_replay"] is False
    assert replay_finding.evidence["duplicate_event_is_idempotent"] is True
    assert replay_finding.evidence["relative_tolerance"] == 0.0
    assert replay_finding.evidence["all_query_lineage_coverage"] is False
    assert len(replay_finding.evidence["state_transition_transcript"]) == 4
    assert len(replay_finding.evidence["incremental_head_transcript"]) == 2

    double_attack = report("DoubleCountEventControl")
    double_finding = next(
        finding
        for finding in double_attack.findings
        if finding.failure_code == "UCM-F019-UPDATE_INCONSISTENT"
    )
    assert double_finding.evidence["incremental_equals_replay"] is True
    assert double_finding.evidence["duplicate_event_is_idempotent"] is False

    affine = report("BehaviorEquivalentSerializationControl")
    assert affine.operational_state_closure is ComplianceVerdict.PASS
    assert not affine.failure_codes

    matched = report("MatchedStochasticApproxControl")
    assert matched.operational_state_closure is ComplianceVerdict.PASS
    assert "UCM-F019-UPDATE_INCONSISTENT" not in matched.failure_codes
    matched_finding = next(
        finding
        for finding in matched.findings
        if finding.gate == "C22-incremental-replay-duplicate-equivalence"
    )
    assert matched_finding.verdict is ComplianceVerdict.PASS
    assert matched_finding.evidence["incremental_behavior_digest"] != (
        matched_finding.evidence["replay_behavior_digest"]
    )
    assert matched_finding.evidence["incremental_equals_replay"] is True
    assert matched_finding.evidence["duplicate_event_is_idempotent"] is True


def test_history_probe_is_budgeted_and_narrowly_scoped() -> None:
    history, diagnosis, rollout, delta = inputs()
    payload = StatePayload.from_json(
        {"many_strings": ["AAAA" for _ in range(257)]},
        schema_version="budget-probe/1",
        state_class=StateClass.COMPRESSED_SHARED,
    )
    method, evidence, incomplete = compliance._recovers_full_history(
        payload, history
    )
    assert method is None
    assert incomplete == "string-count budget exceeded"
    assert evidence["scope"] == "fixed-recoverable-codec-c27-only"
    assert evidence["encryption_or_c31_coverage"] is False
    assert evidence["decode_attempts"] <= evidence["budgets"]["max_decode_attempts"]
    assert evidence["nodes_visited"] <= evidence["budgets"]["max_nodes"]

    junk_report = evaluate_candidate_compliance(
        control_entrypoint("HistoryBudgetJunkControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=829,
        semantic_probes=frozenset({"full_history_disclosure"}),
    )
    assert junk_report.operational_state_closure is ComplianceVerdict.INCOMPLETE
    assert not _specificity_report_eligible(junk_report)
    assert any(
        finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
        and finding.verdict is ComplianceVerdict.INCOMPLETE
        for finding in junk_report.findings
    )

    unsupported = StatePayload(
        payload=b"\x00" * 8,
        codec="raw-f64le-v1",
        schema_version="raw-history-probe/1",
        state_class=StateClass.COMPRESSED_SHARED,
    )
    method, evidence, incomplete = compliance._recovers_full_history(
        unsupported, history
    )
    assert method is None
    assert incomplete == "unsupported fixed-probe codec: raw-f64le-v1"
    assert evidence["scope"] == "fixed-recoverable-codec-c27-only"


def test_enabled_delta_probes_without_delta_are_explicitly_incomplete() -> None:
    history, diagnosis, rollout, _ = inputs()
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=None,
        seed=907,
        semantic_probes=frozenset(
            {"update_consistency", "warm_future_old_cut"}
        ),
    )
    probe_findings = {
        finding.gate: finding
        for finding in report.findings
        if finding.gate
        in {
            "C22-incremental-replay-duplicate-equivalence",
            "C23-late-event-old-cut-stability",
        }
    }
    assert set(probe_findings) == {
        "C22-incremental-replay-duplicate-equivalence",
        "C23-late-event-old-cut-stability",
    }
    assert all(
        finding.verdict is ComplianceVerdict.INCOMPLETE
        and finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
        for finding in probe_findings.values()
    )
    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE


def test_behavior_equivalent_serialization_has_paired_semantic_proof() -> None:
    history, diagnosis, rollout, delta = inputs()
    evidence = paired_serialization_equivalence_evidence(
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=877,
    )
    assert evidence["passed"] is True
    assert {phase["phase"] for phase in evidence["phases"]} == {
        "initialize",
        "update",
    }
    assert all(
        phase["state_serializations_distinct"]
        and phase["semantic_behavior_equivalent"]
        for phase in evidence["phases"]
    )


def test_source_binding_includes_probe_profile_live_code_and_control_mro(
    monkeypatch,
) -> None:
    without_probe = _source_digest("HonestSeededControl", frozenset())
    with_probe = _source_digest(
        "HonestSeededControl", frozenset({"update_consistency"})
    )
    assert without_probe != with_probe
    original = compliance._semantic_behavior_equal

    def patched_equal(left, right):
        return original(left, right)

    monkeypatch.setattr(compliance, "_semantic_behavior_equal", patched_equal)
    monkeypatched = _source_digest(
        "HonestSeededControl", frozenset({"update_consistency"})
    )
    assert monkeypatched != with_probe

    monkeypatch.setattr(compliance, "_semantic_behavior_equal", original)
    original_tolerance = compliance.SEMANTIC_ABS_TOLERANCE
    monkeypatch.setattr(compliance, "SEMANTIC_ABS_TOLERANCE", 999.0)
    constant_patched = _source_digest(
        "HonestSeededControl", frozenset({"update_consistency"})
    )
    assert constant_patched != with_probe

    monkeypatch.setattr(
        compliance, "SEMANTIC_ABS_TOLERANCE", original_tolerance
    )
    original_invoke = candidate_protocol.FreshProcessExecutor.invoke

    def patched_invoke(self, request):
        return original_invoke(self, request)

    monkeypatch.setattr(
        candidate_protocol.FreshProcessExecutor, "invoke", patched_invoke
    )
    executor_patched = _source_digest(
        "HonestSeededControl", frozenset({"update_consistency"})
    )
    assert executor_patched != with_probe


def test_source_binding_tracks_live_adjudicator_and_wire_parser(
    monkeypatch,
) -> None:
    probes = frozenset({"update_consistency"})
    baseline = _source_digest("HonestSeededControl", probes)

    original_decisive = mutation_runner._decisive_finding

    def patched_decisive(findings, expected_failure_code, *, expected_gate):
        return original_decisive(
            findings,
            expected_failure_code,
            expected_gate=expected_gate,
        )

    monkeypatch.setattr(
        mutation_runner, "_decisive_finding", patched_decisive
    )
    decisive_patched = _source_digest("HonestSeededControl", probes)
    assert decisive_patched != baseline

    monkeypatch.setattr(
        mutation_runner, "_decisive_finding", original_decisive
    )
    original_parser = candidate_protocol.response_from_wire

    def patched_response_from_wire(value):
        return original_parser(value)

    monkeypatch.setattr(
        candidate_protocol, "response_from_wire", patched_response_from_wire
    )
    parser_patched = _source_digest("HonestSeededControl", probes)
    assert parser_patched != baseline


def test_decisive_finding_requires_direct_gate_failure_membership() -> None:
    finding = compliance.ComplianceFinding(
        gate="C21/C22-update-consistency",
        verdict=ComplianceVerdict.FAIL,
        failure_code="UCM-F019-UPDATE_INCONSISTENT",
        detail="composite detector label",
    )
    assert (
        mutation_runner._decisive_finding(
            (finding,),
            "UCM-F019-UPDATE_INCONSISTENT",
            expected_gate="C21",
        )
        is None
    )
    assert (
        mutation_runner._decisive_finding(
            (finding,),
            "UCM-F019-UPDATE_INCONSISTENT",
            expected_gate="C22",
        )
        is finding
    )


@pytest.mark.parametrize(
    ("gate", "failure_code"),
    [
        (True, "UCM-F019-UPDATE_INCONSISTENT"),
        (1, "UCM-F019-UPDATE_INCONSISTENT"),
        ("C22", True),
        ("C22", 1),
    ],
)
def test_runner_direct_gate_failure_membership_is_type_strict(
    gate: object, failure_code: object
) -> None:
    assert not mutation_runner._direct_gate_allows_failure_code(
        gate, failure_code
    )


def test_callable_reference_rejects_truly_orphaned_function() -> None:
    name = "_ucm_test_anchored_orphan_callable"
    namespace = vars(candidate_protocol)
    exec(f"def {name}():\n    return None\n", namespace)
    orphan = namespace.pop(name)

    with pytest.raises(ProtocolViolation, match="has no owner alias"):
        mutation_runner._registered_callable_reference(orphan, "test.orphan")


def test_callable_reference_rejects_foreign_owner_with_anchored_consumer(
    monkeypatch,
) -> None:
    module_name = "_ucm_test_foreign_callable_owner"
    owner = types.ModuleType(module_name)
    exec("def foreign():\n    return None\n", owner.__dict__)
    foreign = owner.foreign
    del owner.foreign
    monkeypatch.setitem(sys.modules, module_name, owner)
    monkeypatch.setattr(
        compliance, "_ucm_test_foreign_callable", foreign, raising=False
    )

    with pytest.raises(ProtocolViolation, match="has no anchored owner"):
        mutation_runner._registered_callable_reference(
            foreign, "test.foreign_owner"
        )


def test_callable_reference_rejects_orphaned_builtin_consumer_alias(
    monkeypatch,
) -> None:
    import _operator

    orphaned_builtin = _operator.index
    monkeypatch.setattr(_operator, "index", object())
    monkeypatch.setattr(
        compliance, "_ucm_test_orphaned_builtin", orphaned_builtin, raising=False
    )

    with pytest.raises(ProtocolViolation, match="has no owner alias"):
        mutation_runner._registered_callable_reference(
            orphaned_builtin, "test.orphaned_builtin"
        )


def test_source_binding_tracks_mutation_evidence_builder_and_live_alias(
    monkeypatch,
) -> None:
    probes = frozenset({"update_consistency"})
    baseline = _source_digest("HonestSeededControl", probes)
    original_finalize = mutation_evidence.MutationEvidenceBuilder.finalize

    def patched_finalize(self):
        return original_finalize(self)

    monkeypatch.setattr(
        mutation_evidence.MutationEvidenceBuilder,
        "finalize",
        patched_finalize,
    )
    assert _source_digest("HonestSeededControl", probes) != baseline
    monkeypatch.setattr(
        mutation_evidence.MutationEvidenceBuilder,
        "finalize",
        original_finalize,
    )

    original_contract = mutation_runner.portable_runner_contract
    monkeypatch.setattr(mutation_runner, "portable_runner_contract", object)
    with pytest.raises(ProtocolViolation, match="critical alias identity mismatch"):
        _source_digest("HonestSeededControl", probes)
    monkeypatch.setattr(
        mutation_runner, "portable_runner_contract", original_contract
    )

    monkeypatch.setattr(mutation_runner, "MutationEvidenceBuilder", object)
    with pytest.raises(ProtocolViolation, match="critical alias identity mismatch"):
        _source_digest("HonestSeededControl", probes)


def test_source_binding_tracks_runner_contract_and_rejects_foreign_globals(
    monkeypatch,
) -> None:
    probes = frozenset({"update_consistency"})
    baseline = _source_digest("HonestSeededControl", probes)

    original_protocol = mutation_runner.RUNNER_PROTOCOL
    monkeypatch.setattr(mutation_runner, "RUNNER_PROTOCOL", "evil-runner")
    assert _source_digest("HonestSeededControl", probes) != baseline
    monkeypatch.setattr(mutation_runner, "RUNNER_PROTOCOL", original_protocol)

    original_cases = mutation_runner.PORTABLE_MUTATION_CASES
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", ())
    assert _source_digest("HonestSeededControl", probes) != baseline
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_MUTATION_CASES", original_cases
    )

    original_decisive = mutation_runner._decisive_finding

    class AlteredVerdict:
        FAIL = ComplianceVerdict.PASS

    altered_globals = dict(original_decisive.__globals__)
    altered_globals["ComplianceVerdict"] = AlteredVerdict
    foreign_decisive = types.FunctionType(
        original_decisive.__code__,
        altered_globals,
        original_decisive.__name__,
        original_decisive.__defaults__,
        original_decisive.__closure__,
    )
    foreign_decisive.__kwdefaults__ = original_decisive.__kwdefaults__
    monkeypatch.setattr(
        mutation_runner, "_decisive_finding", foreign_decisive
    )
    with pytest.raises(ProtocolViolation, match="foreign globals"):
        _source_digest("HonestSeededControl", probes)
    monkeypatch.setattr(
        mutation_runner, "_decisive_finding", original_decisive
    )

    original_parser = candidate_protocol.response_from_wire
    parser_globals = dict(original_parser.__globals__)
    parser_globals["RESPONSE_PROTOCOL"] = "evil-response"
    foreign_parser = types.FunctionType(
        original_parser.__code__,
        parser_globals,
        original_parser.__name__,
        original_parser.__defaults__,
        original_parser.__closure__,
    )
    foreign_parser.__kwdefaults__ = original_parser.__kwdefaults__
    monkeypatch.setattr(
        candidate_protocol, "response_from_wire", foreign_parser
    )
    with pytest.raises(ProtocolViolation, match="foreign globals"):
        _source_digest("HonestSeededControl", probes)


def test_live_callable_binding_tracks_defaults_kwdefaults_and_closure(
    monkeypatch,
) -> None:
    probes = frozenset({"update_consistency"})
    baseline = _source_digest("HonestSeededControl", probes)

    entrypoint_function = compliance.control_entrypoint
    original_entrypoint_kw = dict(entrypoint_function.__kwdefaults__ or {})
    repository_root = str(
        candidate_protocol.Path(compliance.__file__).resolve().parents[2]
    )
    monkeypatch.setattr(
        entrypoint_function,
        "__kwdefaults__",
        {**original_entrypoint_kw, "bundle_root": repository_root},
    )
    assert _source_digest("HonestSeededControl", probes) != baseline
    monkeypatch.setattr(
        entrypoint_function, "__kwdefaults__", original_entrypoint_kw
    )

    validator = candidate_protocol.validate_json_like
    original_validator_kw = dict(validator.__kwdefaults__ or {})
    monkeypatch.setattr(
        validator,
        "__kwdefaults__",
        {**original_validator_kw, "max_depth": 128},
    )
    with pytest.raises(
        ProtocolViolation, match="runtime inventory callable defaults/closure mismatch"
    ):
        _source_digest("HonestSeededControl", probes)
    monkeypatch.setattr(validator, "__kwdefaults__", original_validator_kw)

    initializer = candidate_protocol.SequentialProcessExecutor.__init__
    original_initializer_kw = dict(initializer.__kwdefaults__ or {})
    monkeypatch.setattr(
        initializer,
        "__kwdefaults__",
        {**original_initializer_kw, "timeout_seconds": 99.0},
    )
    assert _source_digest("HonestSeededControl", probes) != baseline

    def closure_factory(flag: bool):
        def same_code() -> bool:
            return flag

        return same_code

    assert _live_callable_digest(
        closure_factory(False), "closure-false"
    ) != _live_callable_digest(closure_factory(True), "closure-true")

    class DangerousClosureValue:
        pass

    dangerous_value = DangerousClosureValue()

    def unsafe_factory(value):
        def same_code():
            return value

        return same_code

    with pytest.raises(ProtocolViolation, match="registered alias|unsafe runtime"):
        _live_callable_digest(
            unsafe_factory(dangerous_value), "unsafe-closure"
        )


def test_live_callable_binding_recursively_binds_nested_functions_and_cycles() -> None:
    def factory(flag: bool):
        def nested() -> bool:
            return flag

        def outer():
            return nested

        return outer

    assert _live_callable_digest(
        factory(False), "nested-false"
    ) != _live_callable_digest(factory(True), "nested-true")

    def cycle_factory():
        function = None

        def cyclic():
            return function

        function = cyclic
        return cyclic

    with pytest.raises(ProtocolViolation, match="cyclic live callable"):
        _live_callable_digest(cycle_factory(), "cyclic-function-closure")


def test_live_callable_binding_binds_outer_wrapper_and_wrapped_chain(
    monkeypatch,
) -> None:
    baseline = _source_digest("HonestSeededControl", frozenset())
    original = compliance._semantic_behavior_equal

    @functools.wraps(original)
    def fail_open(*args, **kwargs):
        del args, kwargs
        return True

    assert fail_open.__wrapped__ is original
    monkeypatch.setattr(compliance, "_semantic_behavior_equal", fail_open)
    assert _source_digest("HonestSeededControl", frozenset()) != baseline


def test_live_callable_digest_is_stable_after_hot_execution() -> None:
    def hot(value: int) -> int:
        return (value + 1) * 2

    before = _live_callable_digest(hot, "hot-before")
    for value in range(100_000):
        hot(value)
    after = _live_callable_digest(hot, "hot-after")
    assert after == before


def test_source_binding_tracks_same_code_evaluator_closure_state(
    monkeypatch,
) -> None:
    original = compliance.evaluate_candidate_compliance

    def factory(bypass: bool):
        def evaluate_alias(*args, **kwargs):
            if bypass:
                return None
            return original(*args, **kwargs)

        return evaluate_alias

    first = factory(False)
    second = factory(True)
    assert first.__code__ is second.__code__
    monkeypatch.setattr(compliance, "evaluate_candidate_compliance", first)
    monkeypatch.setattr(mutation_runner, "evaluate_candidate_compliance", first)
    first_digest = _source_digest("HonestSeededControl", frozenset())
    monkeypatch.setattr(compliance, "evaluate_candidate_compliance", second)
    monkeypatch.setattr(mutation_runner, "evaluate_candidate_compliance", second)
    second_digest = _source_digest("HonestSeededControl", frozenset())
    assert first_digest != second_digest


@pytest.mark.parametrize(
    ("module", "name", "replacement"),
    [
        (candidate_protocol, "_DENIED_AUDIT_EVENTS", frozenset()),
        (candidate_protocol, "MAX_STATE_PAYLOAD_BYTES", 1),
        (candidate_protocol, "MAX_SESSION_REQUESTS", 1),
        (candidate_protocol, "MAX_CAPTURED_STREAM_BYTES", 1),
        (candidate_protocol, "_CANDIDATE_FAILURE_PHASES", frozenset()),
        (candidate_protocol, "_HARNESS_FAILURE_PHASES", frozenset()),
        (candidate_protocol, "_WORKER_FAILURE_PHASES", frozenset()),
        (compliance, "PORTABLE_COMPLIANCE_PROBE_TIMEOUT_SECONDS", 0.001),
        (mutation_runner, "PORTABLE_MUTATION_CASES", ()),
        (mutation_runner, "PORTABLE_SPECIFICITY_CASES", ()),
    ],
)
def test_source_binding_tracks_freeze_critical_constants(
    monkeypatch, module, name: str, replacement
) -> None:
    baseline = _source_digest("HonestSeededControl", frozenset())
    monkeypatch.setattr(module, name, replacement)
    assert _source_digest("HonestSeededControl", frozenset()) != baseline


@pytest.mark.parametrize(
    ("name", "replacement"),
    [
        ("MAX_IMPORT_MANIFEST_BYTES", 1),
        ("IMPORT_INVENTORY_PROTOCOL", "rewritten"),
        ("RUNTIME_IMPORT_CLOSURE_PROTOCOL", "rewritten"),
        ("RUNTIME_BINDING_KIND", "rewritten"),
        ("HARNESS_BUNDLE_PROTOCOL", "rewritten"),
        ("BOOTSTRAP_PROTOCOL", "rewritten"),
        ("_HARNESS_SOURCE_RELATIVE_PATHS", ("poison.py",)),
        (
            "_UNIFIED_WORKER_BOOTSTRAP",
            candidate_protocol._UNIFIED_WORKER_BOOTSTRAP + "\n# rewritten",
        ),
    ],
)
def test_runtime_inventory_snapshot_constants_are_preverified(
    monkeypatch, name: str, replacement
) -> None:
    monkeypatch.setattr(candidate_protocol, name, replacement)
    with pytest.raises(
        ProtocolViolation, match="runtime inventory limit/authority constants changed"
    ):
        mutation_runner._prepare_runtime_import_cache()


@pytest.mark.parametrize(
    "name",
    [
        "_source_cache_relative_path",
        "canonical_json_bytes",
        "digest_json",
        "validate_json_like",
    ],
)
def test_runtime_inventory_snapshot_helpers_are_preverified(
    monkeypatch, name: str
) -> None:
    monkeypatch.setattr(candidate_protocol, name, lambda *args, **kwargs: b"poison")
    with pytest.raises(
        ProtocolViolation, match="runtime inventory callable identity mismatch"
    ):
        mutation_runner._prepare_runtime_import_cache()


@pytest.mark.parametrize(
    "name",
    ["GATE_SPECS", "MUTANT_SPECS", "SPECIFICITY_CONTROLS"],
)
def test_source_binding_tracks_mutation_matrix_registries(
    monkeypatch, name: str
) -> None:
    baseline = _source_digest("HonestSeededControl", frozenset())
    monkeypatch.setattr(mutation_matrix, name, ())
    assert _source_digest("HonestSeededControl", frozenset()) != baseline


def test_source_binding_rejects_foreign_dataclass_registry_entry(
    monkeypatch,
) -> None:
    original = mutation_matrix.MUTANT_SPECS
    foreign_type = make_dataclass(
        "MutantSpec",
        [
            ("mutant_id", str),
            ("expected_gates", tuple[str, ...]),
            ("expected_failure_codes", tuple[str, ...]),
        ],
    )
    foreign_type.__module__ = mutation_matrix.__name__
    foreign_type.__qualname__ = "MutantSpec"
    first = original[0]
    foreign = foreign_type(
        first.mutant_id,
        first.expected_gates,
        first.expected_failure_codes,
    )
    monkeypatch.setattr(
        mutation_matrix,
        "MUTANT_SPECS",
        (foreign, *original[1:]),
    )
    with pytest.raises(ProtocolViolation, match="registered owner alias"):
        _source_digest("HonestSeededControl", frozenset())


def test_source_binding_rejects_critical_imported_alias_rewrite(
    monkeypatch,
) -> None:
    class FakeComplianceVerdict:
        PASS = ComplianceVerdict.PASS
        FAIL = ComplianceVerdict.PASS
        INCOMPLETE = ComplianceVerdict.PASS

    monkeypatch.setattr(
        mutation_runner, "ComplianceVerdict", FakeComplianceVerdict
    )
    with pytest.raises(ProtocolViolation, match="critical alias identity mismatch"):
        _source_digest("HonestSeededControl", frozenset())


@pytest.mark.parametrize(
    ("consumer", "name"),
    [
        (candidate_protocol, "ActionPlan"),
        (candidate_protocol, "CandidateVisibleEvent"),
        (candidate_protocol, "DiagnosisQuery"),
        (candidate_protocol, "EventKind"),
        (candidate_protocol, "PlanKind"),
        (candidate_protocol, "PlannedAction"),
        (candidate_protocol, "RolloutQuery"),
        (candidate_protocol, "VisibleDelta"),
        (candidate_protocol, "VisibleHistory"),
        (candidate_protocol, "CandidateStateInput"),
        (candidate_protocol, "SealedState"),
        (candidate_protocol, "StateClass"),
        (candidate_protocol, "StatePayload"),
        (compliance, "CandidateCallViolation"),
        (compliance, "CandidateEntrypoint"),
        (compliance, "DiagnoseRequest"),
        (compliance, "DiagnoseResponse"),
        (compliance, "DiagnosisResult"),
        (compliance, "FreshProcessExecutor"),
        (compliance, "HeadExecution"),
        (compliance, "InitializeRequest"),
        (compliance, "InvocationOutcome"),
        (compliance, "Operation"),
        (compliance, "ResultStatus"),
        (compliance, "RolloutRequest"),
        (compliance, "RolloutResponse"),
        (compliance, "RolloutResult"),
        (compliance, "SequentialProcessExecutor"),
        (compliance, "StateResponse"),
        (compliance, "UpdateRequest"),
        (compliance, "WorkerInvocationError"),
        (compliance, "assert_shared_state_fanout"),
        (compliance, "invoke_diagnose"),
        (compliance, "invoke_rollout"),
        (compliance, "DiagnosisQuery"),
        (compliance, "RolloutQuery"),
        (compliance, "VisibleDelta"),
        (compliance, "VisibleHistory"),
        (compliance, "event_sort_key"),
        (compliance, "CandidateStateInput"),
        (compliance, "StateClass"),
        (compliance, "StatePayload"),
        (compliance, "seal_state"),
    ],
)
def test_source_binding_rejects_all_critical_protocol_alias_rewrites(
    monkeypatch,
    consumer,
    name: str,
) -> None:
    monkeypatch.setattr(consumer, name, object())
    with pytest.raises(ProtocolViolation):
        _source_digest("HonestSeededControl", frozenset())


def test_update_probe_execution_failure_is_incomplete_not_a_kill(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()

    def fail_probe(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("deliberate probe infrastructure failure")

    monkeypatch.setattr(compliance, "_head_behavior", fail_probe)
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=919,
        semantic_probes=frozenset({"update_consistency"}),
    )
    assert "UCM-F019-UPDATE_INCONSISTENT" not in report.failure_codes
    finding = next(
        item
        for item in report.findings
        if item.gate == "C22-incremental-replay-duplicate-equivalence"
    )
    assert finding.verdict is ComplianceVerdict.INCOMPLETE
    assert finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE


def test_semantic_tolerance_has_no_large_scale_relative_escape() -> None:
    assert compliance.SEMANTIC_REL_TOLERANCE == 0.0
    assert not compliance._semantic_behavior_equal(1e12, 1e12 + 500.0)


def test_compliance_never_loads_candidates_in_parent_process() -> None:
    source = inspect.getsource(compliance)
    assert "InProcessExecutor" not in source
    assert "_load_candidate" not in source


@pytest.mark.parametrize(
    ("module", "name", "replacement"),
    [
        (candidate_protocol, "Path", object),
        (candidate_protocol, "subprocess", candidate_protocol.contextlib),
        (candidate_protocol, "contextlib", candidate_protocol.os),
        (candidate_protocol, "os", candidate_protocol.sys),
        (candidate_protocol, "sys", candidate_protocol.os),
        (compliance, "math", compliance.os),
    ],
)
def test_source_binding_rejects_referenced_module_and_class_alias_rewrites(
    monkeypatch,
    module,
    name: str,
    replacement,
) -> None:
    baseline = _source_digest("HonestSeededControl", frozenset())
    monkeypatch.setattr(module, name, replacement)
    with pytest.raises(ProtocolViolation, match="identity mismatch"):
        _source_digest("HonestSeededControl", frozenset())
    monkeypatch.undo()
    assert _source_digest("HonestSeededControl", frozenset()) == baseline


def test_source_binding_rejects_synchronized_executor_clone_before_metaclass_use(
) -> None:
    original = candidate_protocol.FreshProcessExecutor
    poisoned_accesses: list[str] = []

    class PoisonMeta(type):
        def __getattribute__(cls, name):
            poisoned_accesses.append(name)
            raise AssertionError("source binding executed a foreign metaclass")

    namespace = {
        key: value
        for key, value in vars(original).items()
        if key not in {"__dict__", "__weakref__"}
    }
    namespace["__module__"] = candidate_protocol.__name__
    namespace["__qualname__"] = "FreshProcessExecutor"
    clone = PoisonMeta("FreshProcessExecutor", original.__bases__, namespace)
    poisoned_accesses.clear()
    setattr(candidate_protocol, "FreshProcessExecutor", clone)
    setattr(compliance, "FreshProcessExecutor", clone)
    try:
        with pytest.raises(ProtocolViolation, match="identity mismatch"):
            _source_digest("HonestSeededControl", frozenset())
        assert poisoned_accesses == []
    finally:
        setattr(candidate_protocol, "FreshProcessExecutor", original)
        setattr(compliance, "FreshProcessExecutor", original)


def test_source_binding_rejects_synchronized_same_name_verdict_enum(
    monkeypatch,
) -> None:
    foreign = Enum(
        "ComplianceVerdict",
        {"PASS": "pass", "FAIL": "fail", "INCOMPLETE": "incomplete"},
        type=str,
    )
    type.__setattr__(foreign, "__module__", compliance.__name__)
    type.__setattr__(foreign, "__qualname__", "ComplianceVerdict")
    monkeypatch.setattr(compliance, "ComplianceVerdict", foreign)
    monkeypatch.setattr(mutation_runner, "ComplianceVerdict", foreign)

    with pytest.raises(ProtocolViolation, match="identity mismatch"):
        _source_digest("HonestSeededControl", frozenset())


def _binding_kwargs(
    *,
    bundle: str = "sha256:" + "a" * 64,
    model: str = "sha256:" + "b" * 64,
    harness: str = "sha256:" + "f" * 64,
    inventory: str = "sha256:" + "e" * 64,
    origin: str = "candidate_bundle/control.py",
) -> dict[str, str]:
    return {
        "candidate_bundle_digest": bundle,
        "candidate_model_digest": model,
        "harness_bundle_digest": harness,
        "import_inventory_digest": inventory,
        "module_origin": origin,
    }


def _install_exact_fresh_executor(monkeypatch) -> dict[str, str]:
    binding = _binding_kwargs()

    class ExactFreshExecutor:
        def __init__(self, entrypoint):
            del entrypoint

        def invoke(self, request):
            candidate = compliance.HonestSeededControl()
            response = candidate_protocol._dispatch_candidate(candidate, request)
            request_digest = candidate_protocol.digest_json(request.to_wire())
            return candidate_protocol.InvocationOutcome(
                response=response,
                request_digest=request_digest,
                response_digest=candidate_protocol.digest_json(response.to_wire()),
                isolation="test-exact-bound-worker",
                received_request_digest=request_digest,
                **binding,
            )

    monkeypatch.setattr(compliance, "FreshProcessExecutor", ExactFreshExecutor)
    return binding


def test_candidate_worker_failure_retains_complete_execution_binding() -> None:
    binding = _binding_kwargs()
    history, _, _, _ = inputs()
    request = candidate_protocol.InitializeRequest(history, 19)
    request_digest = candidate_protocol.digest_json(request.to_wire())
    error = candidate_protocol.WorkerInvocationError(
        "candidate policy rejection",
        failure_code="UCM-F004-HEAD_HISTORY_ACCESS",
        failure_origin="candidate",
        request_digest=request_digest,
        request_fully_sent=True,
        received_request_digest=request_digest,
        **binding,
    )

    class FailingExecutor:
        def invoke(self, request):
            del request
            raise error

    collector = compliance._ExecutionBindingCollector()
    executor = compliance._BindingObservedExecutor(FailingExecutor(), collector)
    with pytest.raises(candidate_protocol.WorkerInvocationError) as raised:
        executor.invoke(request)

    assert raised.value is error
    assert collector.complete
    assert collector.observed == 1
    finding = compliance._failure_from_worker(error, "C02-head-history-denial")
    assert finding.verdict is ComplianceVerdict.FAIL
    assert finding.failure_code == "UCM-F004-HEAD_HISTORY_ACCESS"
    assert finding.evidence["candidate_bundle_digest"] == binding[
        "candidate_bundle_digest"
    ]
    assert finding.evidence["module_origin"] == binding["module_origin"]
    assert finding.evidence["harness_bundle_digest"] == binding[
        "harness_bundle_digest"
    ]


@pytest.mark.parametrize(
    "malformed_code",
    [
        "",
        "None",
        "UCM-F",
        "UCM-FXYZ-BAD",
        "UCM-F001-_",
        "UCM-F001--",
        "UCM-F001-FOO-",
        "UCM-F001-FOO--BAR",
        "UCM-F001-FOO__BAR",
    ],
)
def test_malformed_candidate_worker_failure_is_harness_incomplete(
    malformed_code: str,
) -> None:
    with pytest.raises(
        ProtocolViolation, match="candidate failures must use a canonical UCM-F code"
    ):
        candidate_protocol.WorkerInvocationError(
            "malformed candidate failure",
            failure_code=malformed_code,
            failure_origin="candidate",
            **_binding_kwargs(),
        )

    error = candidate_protocol.WorkerInvocationError(
        "malformed candidate failure",
        failure_code="UCM-F008-STATE_NOT_CLOSED",
        failure_origin="candidate",
        **_binding_kwargs(),
    )
    # The constructor is the primary boundary.  Keep the downstream parser
    # defensive as well: a hostile or stale object can still have its public
    # attribute rewritten after otherwise-valid construction.
    error.failure_code = malformed_code

    finding = compliance._failure_from_worker(error, "candidate-error-parser")

    assert finding.verdict is ComplianceVerdict.INCOMPLETE
    assert finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert finding.evidence["reported_failure_code"] == malformed_code


def test_candidate_call_violation_code_is_validated_without_secondary_error() -> None:
    valid = candidate_protocol.CandidateCallViolation(
        "UCM-F008-STATE_NOT_CLOSED", "candidate response was not closed"
    )
    valid_finding = compliance._failure_from_exception(valid, "candidate-call")
    assert valid_finding.verdict is ComplianceVerdict.FAIL
    assert valid_finding.failure_code == "UCM-F008-STATE_NOT_CLOSED"

    malformed = candidate_protocol.CandidateCallViolation(
        "not-a-canonical-failure-code", "malformed envelope"
    )
    malformed_finding = compliance._failure_from_exception(
        malformed, "candidate-call-parser"
    )
    assert malformed_finding.verdict is ComplianceVerdict.INCOMPLETE
    assert malformed_finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert malformed_finding.evidence["reported_failure_code"] == (
        "not-a-canonical-failure-code"
    )


def test_candidate_failure_missing_binding_is_incomplete_and_not_decisive(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()
    binding = _binding_kwargs()
    calls = 0

    class MissingFailureBindingExecutor:
        def __init__(self, entrypoint):
            del entrypoint

        def invoke(self, request):
            nonlocal calls
            calls += 1
            if calls > 2:
                request_digest = candidate_protocol.digest_json(request.to_wire())
                raise candidate_protocol.WorkerInvocationError(
                    "candidate operation failed without its snapshot binding",
                    failure_code="UCM-F008-STATE_NOT_CLOSED",
                    failure_origin="candidate",
                    request_digest=request_digest,
                    request_fully_sent=True,
                    received_request_digest=request_digest,
                )
            candidate = compliance.HonestSeededControl()
            response = candidate_protocol._dispatch_candidate(candidate, request)
            request_digest = candidate_protocol.digest_json(request.to_wire())
            return candidate_protocol.InvocationOutcome(
                response=response,
                request_digest=request_digest,
                response_digest=candidate_protocol.digest_json(response.to_wire()),
                isolation="test-missing-error-binding",
                received_request_digest=request_digest,
                **binding,
            )

    monkeypatch.setattr(
        compliance, "FreshProcessExecutor", MissingFailureBindingExecutor
    )
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=43,
    )

    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE
    assert any(
        finding.verdict is ComplianceVerdict.FAIL
        and finding.failure_code == "UCM-F008-STATE_NOT_CLOSED"
        for finding in report.findings
    )
    binding_finding = next(
        finding
        for finding in report.findings
        if finding.gate == "execution-source-binding"
    )
    assert binding_finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert any(
        "candidate_bundle_digest" in violation
        for violation in binding_finding.evidence["binding_violations"]
    )

    file_handle_case = next(
        case
        for case in mutation_runner.PORTABLE_MUTATION_CASES
        if case.matrix_subject_id == "FileHandleState"
    )
    expected_candidate = control_entrypoint(file_handle_case.control_class_name)
    runner_report = compliance.ComplianceReport(
        candidate=(
            f"{expected_candidate.module}:{expected_candidate.qualname}"
        ),
        operational_state_closure=report.operational_state_closure,
        semantic_unity=report.semantic_unity,
        isolation_completeness=report.isolation_completeness,
        isolation_assurance=report.isolation_assurance,
        findings=report.findings,
        candidate_bundle_digest=report.candidate_bundle_digest,
        candidate_model_digest=report.candidate_model_digest,
        harness_bundle_digest=report.harness_bundle_digest,
        import_inventory_digest=report.import_inventory_digest,
        module_origin=report.module_origin,
    )

    def return_incomplete_report(*args, **kwargs):
        del args, kwargs
        return runner_report

    monkeypatch.setattr(
        compliance, "FreshProcessExecutor", candidate_protocol.FreshProcessExecutor
    )
    monkeypatch.setattr(
        compliance, "evaluate_candidate_compliance", return_incomplete_report
    )
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", return_incomplete_report
    )
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_MUTATION_CASES", (file_handle_case,)
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_SPECIFICITY_CASES", ())
    bundle = run_portable_mutation_evidence(
        run_id="incomplete-report-61",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=61,
    )
    rows = bundle.observations
    assert rows[0].outcome is mutation_matrix.ObservationOutcome.CRASHED
    assert rows[0].actual_failure_code is None
    assert rows[0].decisive_record_digest is None


@pytest.mark.parametrize(
    ("changed_field", "changed_value", "message"),
    [
        ("candidate_bundle_digest", "sha256:" + "1" * 64, "bundle digest"),
        ("candidate_model_digest", "sha256:" + "2" * 64, "model digest"),
        ("harness_bundle_digest", "sha256:" + "4" * 64, "harness bundle digest"),
        ("import_inventory_digest", "sha256:" + "3" * 64, "inventory digest"),
        ("module_origin", "candidate_bundle/other.py", "module origin"),
    ],
)
def test_execution_binding_collector_rejects_cross_worker_drift(
    changed_field: str, changed_value: str, message: str
) -> None:
    collector = compliance._ExecutionBindingCollector()
    first = types.SimpleNamespace(**_binding_kwargs())
    changed = _binding_kwargs()
    changed[changed_field] = changed_value
    collector.observe(first)
    collector.observe(types.SimpleNamespace(**changed))
    assert not collector.complete
    assert any(message in violation for violation in collector.violations)


@pytest.mark.parametrize(
    "changed_field",
    [
        "candidate_bundle_digest",
        "candidate_model_digest",
        "harness_bundle_digest",
        "import_inventory_digest",
        "module_origin",
    ],
)
def test_runner_execution_binding_rejects_head_record_drift(
    changed_field: str,
) -> None:
    binding = _binding_kwargs()
    head_binding = dict(binding)
    head_binding[changed_field] = (
        "candidate_bundle/other.py"
        if changed_field == "module_origin"
        else "sha256:" + "1" * 64
    )
    report = compliance.ComplianceReport(
        candidate="module:qualname",
        operational_state_closure=ComplianceVerdict.FAIL,
        semantic_unity=ComplianceVerdict.INCOMPLETE,
        isolation_completeness=ComplianceVerdict.INCOMPLETE,
        isolation_assurance="test",
        findings=(),
        head_records=(head_binding,),
        **binding,
    )

    with pytest.raises(ProtocolViolation, match="head record 0 execution binding"):
        mutation_runner._report_execution_binding(
            report, expected_candidate="module:qualname"
        )


def test_runner_execution_binding_rejects_missing_head_harness_digest() -> None:
    binding = _binding_kwargs()
    head_binding = dict(binding)
    del head_binding["harness_bundle_digest"]
    report = compliance.ComplianceReport(
        candidate="module:qualname",
        operational_state_closure=ComplianceVerdict.FAIL,
        semantic_unity=ComplianceVerdict.INCOMPLETE,
        isolation_completeness=ComplianceVerdict.INCOMPLETE,
        isolation_assurance="test",
        findings=(),
        head_records=(head_binding,),
        **binding,
    )

    with pytest.raises(ProtocolViolation, match="head record 0 harness_bundle_digest"):
        mutation_runner._report_execution_binding(
            report, expected_candidate="module:qualname"
        )


def test_runner_execution_binding_must_match_live_snapshot_witness() -> None:
    binding = _binding_kwargs()
    expected = dict(binding)
    expected["harness_bundle_digest"] = "sha256:" + "1" * 64
    report = compliance.ComplianceReport(
        candidate="module:qualname",
        operational_state_closure=ComplianceVerdict.FAIL,
        semantic_unity=ComplianceVerdict.INCOMPLETE,
        isolation_completeness=ComplianceVerdict.INCOMPLETE,
        isolation_assurance="test",
        findings=(),
        **binding,
    )

    with pytest.raises(ProtocolViolation, match="live source snapshot"):
        mutation_runner._report_execution_binding(
            report,
            expected_candidate="module:qualname",
            expected_execution_binding=expected,
        )


@pytest.mark.parametrize("exception_kind", ["worker", "parser"])
def test_startup_and_parser_failures_are_harness_incomplete(
    monkeypatch, exception_kind: str
) -> None:
    history, diagnosis, rollout, _ = inputs()

    class BrokenFreshExecutor:
        def __init__(self, entrypoint):
            del entrypoint

        def invoke(self, request):
            del request
            if exception_kind == "worker":
                raise candidate_protocol.WorkerInvocationError(
                    "worker could not start",
                    failure_code="UCM-E003-HARNESS_INCOMPLETE",
                    failure_origin="harness",
                )
            raise ProtocolViolation("malformed worker envelope")

    monkeypatch.setattr(compliance, "FreshProcessExecutor", BrokenFreshExecutor)
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=41,
    )

    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE
    assert any(
        finding.verdict is ComplianceVerdict.INCOMPLETE
        and finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
        for finding in report.findings
    )
    assert not any(
        finding.verdict is ComplianceVerdict.FAIL
        and finding.failure_code == "UCM-F008-STATE_NOT_CLOSED"
        for finding in report.findings
    )


def test_fresh_executor_constructor_failure_is_harness_incomplete(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, _ = inputs()

    class BrokenConstructor:
        def __init__(self, entrypoint):
            del entrypoint
            raise RuntimeError("worker constructor failed")

    monkeypatch.setattr(compliance, "FreshProcessExecutor", BrokenConstructor)
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=42,
    )

    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE
    finding = next(
        item
        for item in report.findings
        if item.gate == "candidate-worker-construction"
    )
    assert finding.verdict is ComplianceVerdict.INCOMPLETE
    assert finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"


def test_harness_seal_candidate_call_violation_is_incomplete(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, _ = inputs()
    _install_exact_fresh_executor(monkeypatch)

    def broken_seal(*args, **kwargs):
        del args, kwargs
        raise candidate_protocol.CandidateCallViolation(
            "UCM-F008-STATE_NOT_CLOSED", "synthetic harness seal fault"
        )

    monkeypatch.setattr(compliance, "seal_state", broken_seal)
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=44,
    )

    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE
    seal_finding = next(
        item for item in report.findings if item.gate == "harness-state-seal"
    )
    assert seal_finding.verdict is ComplianceVerdict.INCOMPLETE
    assert seal_finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert not any(
        item.verdict is ComplianceVerdict.FAIL
        and item.failure_code == "UCM-F008-STATE_NOT_CLOSED"
        for item in report.findings
    )


def test_update_request_constructor_failure_is_harness_incomplete(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()
    _install_exact_fresh_executor(monkeypatch)

    def broken_update_request(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("update request constructor failed")

    monkeypatch.setattr(compliance, "UpdateRequest", broken_update_request)
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=46,
    )

    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE
    finding = next(
        item for item in report.findings if item.gate == "C21/C22-fresh-update"
    )
    assert finding.verdict is ComplianceVerdict.INCOMPLETE
    assert finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"


def test_head_record_serializer_failure_is_harness_incomplete(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, _ = inputs()
    _install_exact_fresh_executor(monkeypatch)

    def broken_to_wire(self):
        del self
        raise RuntimeError("head record serializer failed")

    monkeypatch.setattr(
        candidate_protocol.HeadExecutionRecord, "to_wire", broken_to_wire
    )
    monkeypatch.setattr(
        compliance,
        "assert_shared_state_fanout",
        lambda records: (_ for _ in ()).throw(RuntimeError("stop after heads")),
    )
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=48,
    )

    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE
    assert report.head_records == ()
    finding = next(
        item
        for item in report.findings
        if item.gate == "harness-head-record-serialization"
    )
    assert finding.verdict is ComplianceVerdict.INCOMPLETE
    assert finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"


def test_warm_response_serializer_candidate_call_violation_is_incomplete(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, _ = inputs()
    binding = _install_exact_fresh_executor(monkeypatch)
    warm_phase = False
    original_to_wire = candidate_protocol.StateResponse.to_wire

    def conditional_to_wire(self):
        if warm_phase:
            raise candidate_protocol.CandidateCallViolation(
                "UCM-F008-STATE_NOT_CLOSED",
                "synthetic warm serializer harness fault",
            )
        return original_to_wire(self)

    def exact_warm_sequence(
        entrypoint, requests, collector, *, timeout_seconds
    ):
        nonlocal warm_phase
        del entrypoint, timeout_seconds

        class ExactSequentialDelegate:
            def __init__(self) -> None:
                self.candidate = compliance.HonestSeededControl()

            def invoke(self, request):
                response = candidate_protocol._dispatch_candidate(
                    self.candidate, request
                )
                request_digest = candidate_protocol.digest_json(request.to_wire())
                return candidate_protocol.InvocationOutcome(
                    response=response,
                    request_digest=request_digest,
                    response_digest=candidate_protocol.digest_json(
                        response.to_wire()
                    ),
                    isolation="test-exact-sequential-worker",
                    received_request_digest=request_digest,
                    **binding,
                )

        executor = compliance._BindingObservedExecutor(
            ExactSequentialDelegate(),
            collector,
            execution_mode="sequential",
        )
        outcomes = tuple(executor.invoke(request) for request in requests)
        warm_phase = True
        return outcomes

    monkeypatch.setattr(
        candidate_protocol.StateResponse, "to_wire", conditional_to_wire
    )
    monkeypatch.setattr(
        compliance, "_invoke_observed_sequence", exact_warm_sequence
    )
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=49,
    )

    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE
    finding = next(
        item
        for item in report.findings
        if item.gate == "C04-warm-cold-serialization"
    )
    assert finding.verdict is ComplianceVerdict.INCOMPLETE
    assert finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert not any(
        item.verdict is ComplianceVerdict.FAIL
        and item.failure_code == "UCM-F008-STATE_NOT_CLOSED"
        for item in report.findings
    )


def test_initialize_replay_helper_failure_is_harness_incomplete(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, _ = inputs()
    binding = _binding_kwargs()
    serializer_calls = 0
    original_to_wire = candidate_protocol.StateResponse.to_wire

    class BoundInitializeExecutor:
        def __init__(self, entrypoint):
            del entrypoint

        def invoke(self, request):
            assert type(request) is candidate_protocol.InitializeRequest
            state = compliance.HonestSeededControl().initialize(
                request.history, inference_seed=request.seed
            )
            response = candidate_protocol.StateResponse(
                candidate_protocol.Operation.INITIALIZE, state
            )
            request_digest = candidate_protocol.digest_json(request.to_wire())
            return candidate_protocol.InvocationOutcome(
                response=response,
                request_digest=request_digest,
                response_digest=candidate_protocol.digest_json(
                    original_to_wire(response)
                ),
                isolation="test-initialize-replay-helper",
                received_request_digest=request_digest,
                **binding,
            )

    def broken_to_wire(self):
        nonlocal serializer_calls
        serializer_calls += 1
        if serializer_calls > 2:
            raise RuntimeError("initialize response serializer unavailable")
        return original_to_wire(self)

    monkeypatch.setattr(compliance, "FreshProcessExecutor", BoundInitializeExecutor)
    monkeypatch.setattr(candidate_protocol.StateResponse, "to_wire", broken_to_wire)
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=42,
    )

    finding = next(
        item for item in report.findings if item.gate == "C28-initialize-replay-compare"
    )
    assert finding.verdict is ComplianceVerdict.INCOMPLETE
    assert finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert report.operational_state_closure is ComplianceVerdict.INCOMPLETE
    assert "UCM-F008-STATE_NOT_CLOSED" not in report.failure_codes


def test_compliance_seal_uses_worker_exact_bundle_and_model_binding(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, _ = inputs()
    binding = _binding_kwargs()

    def outcome(candidate, request):
        response = candidate_protocol._dispatch_candidate(candidate, request)
        request_digest = candidate_protocol.digest_json(request.to_wire())
        return candidate_protocol.InvocationOutcome(
            response=response,
            request_digest=request_digest,
            response_digest=candidate_protocol.digest_json(response.to_wire()),
            isolation="test-exact-worker",
            received_request_digest=request_digest,
            **binding,
        )

    class ExactFreshExecutor:
        def __init__(self, entrypoint):
            del entrypoint

        def invoke(self, request):
            return outcome(compliance.HonestSeededControl(), request)

    class ExactSequentialExecutor:
        def __init__(self, entrypoint, *, timeout_seconds):
            del entrypoint, timeout_seconds

        def invoke_sequence(self, requests):
            candidate = compliance.HonestSeededControl()
            return tuple(outcome(candidate, request) for request in requests)

    real_seal_state = compliance.seal_state
    sealed_bindings: list[tuple[str, str]] = []

    def recording_seal_state(payload, **kwargs):
        sealed_bindings.append(
            (kwargs["candidate_bundle_digest"], kwargs["model_digest"])
        )
        return real_seal_state(payload, **kwargs)

    monkeypatch.setattr(compliance, "FreshProcessExecutor", ExactFreshExecutor)
    monkeypatch.setattr(
        compliance, "SequentialProcessExecutor", ExactSequentialExecutor
    )
    monkeypatch.setattr(compliance, "seal_state", recording_seal_state)

    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=47,
    )

    assert sealed_bindings == [
        (binding["candidate_bundle_digest"], binding["candidate_model_digest"])
    ]
    assert report.candidate_bundle_digest == binding["candidate_bundle_digest"]
    assert report.candidate_model_digest == binding["candidate_model_digest"]
    assert report.harness_bundle_digest == binding["harness_bundle_digest"]
    assert report.import_inventory_digest == binding["import_inventory_digest"]
    assert report.module_origin == binding["module_origin"]
    assert report.head_records
    for head_record in report.head_records:
        assert head_record["candidate_bundle_digest"] == binding[
            "candidate_bundle_digest"
        ]
        assert head_record["candidate_model_digest"] == binding[
            "candidate_model_digest"
        ]
        assert head_record["harness_bundle_digest"] == binding[
            "harness_bundle_digest"
        ]
        assert head_record["import_inventory_digest"] == binding[
            "import_inventory_digest"
        ]
        assert head_record["module_origin"] == binding["module_origin"]
    assert report.operational_state_closure is ComplianceVerdict.PASS


def test_compliance_binding_drift_is_harness_incomplete_before_seal(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, _ = inputs()
    calls = 0
    seal_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class DriftingFreshExecutor:
        def __init__(self, entrypoint):
            del entrypoint

        def invoke(self, request):
            nonlocal calls
            calls += 1
            candidate = compliance.HonestSeededControl()
            response = candidate_protocol._dispatch_candidate(candidate, request)
            request_digest = candidate_protocol.digest_json(request.to_wire())
            binding = _binding_kwargs(
                bundle="sha256:" + ("a" if calls == 1 else "f") * 64
            )
            return candidate_protocol.InvocationOutcome(
                response=response,
                request_digest=request_digest,
                response_digest=candidate_protocol.digest_json(response.to_wire()),
                isolation="test-drifting-worker",
                received_request_digest=request_digest,
                **binding,
            )

    def seal_must_not_run(*args, **kwargs):
        seal_calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(compliance, "FreshProcessExecutor", DriftingFreshExecutor)
    monkeypatch.setattr(compliance, "seal_state", seal_must_not_run)
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=53,
    )

    assert seal_calls == []
    binding_finding = next(
        finding
        for finding in report.findings
        if finding.gate == "execution-source-binding"
    )
    assert binding_finding.verdict is ComplianceVerdict.INCOMPLETE
    assert binding_finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert any(
        "candidate bundle digest drifted" in item
        for item in binding_finding.evidence["binding_violations"]
    )


@pytest.mark.parametrize(
    ("owner", "attribute"),
    [
        (compliance.math, "isclose"),
        (candidate_protocol.subprocess, "Popen"),
        (candidate_protocol.subprocess.Popen, "__init__"),
        (candidate_protocol.subprocess.Popen, "wait"),
        (candidate_protocol.subprocess.Popen, "poll"),
        (candidate_protocol.subprocess.Popen, "kill"),
        (candidate_protocol.subprocess.Popen, "terminate"),
        (candidate_protocol.subprocess, "TimeoutExpired"),
        (candidate_protocol.threading, "Lock"),
        (candidate_protocol.threading, "Thread"),
        (candidate_protocol.threading.Thread, "__init__"),
        (candidate_protocol.threading.Thread, "start"),
        (candidate_protocol.threading.Thread, "join"),
        (candidate_protocol.threading.Thread, "is_alive"),
        (candidate_protocol.queue, "Queue"),
        (candidate_protocol.queue.Queue, "__init__"),
        (candidate_protocol.queue.Queue, "put"),
        (candidate_protocol.queue.Queue, "get"),
        (candidate_protocol.queue.Queue, "get_nowait"),
        (candidate_protocol.queue, "Empty"),
        (candidate_protocol.tempfile, "TemporaryDirectory"),
        (candidate_protocol.tempfile.TemporaryDirectory, "__init__"),
        (candidate_protocol.tempfile.TemporaryDirectory, "__enter__"),
        (candidate_protocol.tempfile.TemporaryDirectory, "__exit__"),
        (candidate_protocol.sysconfig, "get_paths"),
        (candidate_protocol.sysconfig, "get_config_var"),
        (candidate_protocol.os, "fspath"),
        (candidate_protocol.os, "fsdecode"),
        (candidate_protocol.os.path, "normcase"),
        (candidate_protocol.os, "open"),
        (candidate_protocol.os, "write"),
        (candidate_protocol.os, "fsync"),
        (candidate_protocol.os, "close"),
        (candidate_protocol.os, "dup"),
        (candidate_protocol.os, "dup2"),
        (candidate_protocol.os, "read"),
        (candidate_protocol.os, "pipe"),
        (candidate_protocol.os, "urandom"),
        (candidate_protocol.Path, "__new__"),
        (candidate_protocol.Path, "read_bytes"),
        (candidate_protocol.Path, "open"),
        (candidate_protocol.Path, "stat"),
        (candidate_protocol.Path, "resolve"),
        (candidate_protocol.Path, "relative_to"),
        (candidate_protocol.Path, "as_posix"),
        (candidate_protocol.Path, "is_file"),
        (candidate_protocol.Path, "is_dir"),
        (candidate_protocol.Path, "is_symlink"),
        (candidate_protocol.Path, "mkdir"),
        (candidate_protocol.Path, "write_bytes"),
        (candidate_protocol.Path, "chmod"),
        (candidate_protocol.importlib, "import_module"),
        (candidate_protocol.importlib.util, "cache_from_source"),
        (candidate_protocol.time, "monotonic"),
        (candidate_protocol.os, "walk"),
        (candidate_protocol.os, "stat"),
        (candidate_protocol.json, "loads"),
        (candidate_protocol.json, "dumps"),
        (candidate_protocol.math, "isfinite"),
        (candidate_protocol.base64, "b64encode"),
        (candidate_protocol.base64, "b64decode"),
        (candidate_protocol.re, "compile"),
        (candidate_protocol.re, "fullmatch"),
        (canonical.hashlib, "sha256"),
        (canonical.json, "dumps"),
        (mutation_runner.dis, "get_instructions"),
        (mutation_runner.inspect, "getsource"),
        (mutation_runner.inspect, "isfunction"),
        (mutation_runner.inspect, "isclass"),
        (mutation_runner.inspect, "ismodule"),
        (mutation_runner.inspect, "isbuiltin"),
        (type(candidate_protocol.Path.cwd()), "resolve"),
        (type(candidate_protocol.Path.cwd()), "read_bytes"),
        (type(candidate_protocol.Path.cwd()), "open"),
        (type(candidate_protocol.Path.cwd()), "parents"),
        (type(candidate_protocol.Path.cwd()), "__fspath__"),
        (type(candidate_protocol.Path.cwd()), "__str__"),
        (type(candidate_protocol.Path.cwd()), "parts"),
    ],
)
def test_source_binding_rejects_critical_external_attribute_rewrite(
    monkeypatch, owner, attribute: str
) -> None:
    monkeypatch.setattr(owner, attribute, lambda *args, **kwargs: None)
    with pytest.raises(ProtocolViolation, match="external attribute identity mismatch"):
        _source_digest("HonestSeededControl", frozenset())


def test_source_binding_rejects_dynamic_adjudicator_numpy_max_rewrite(
    monkeypatch,
) -> None:
    required_attributes = {
        "compliance.math.fsum",
        "compliance.math.isclose",
        "compliance.math.isfinite",
        "compliance.os.getpid",
        "compliance.random.Random",
        "metrics.np.max",
        "metrics.np.argmax",
        "worlds_w04.math.fsum",
        "worlds_w04.math.log",
        "worlds_w15.math.exp",
        "worlds_w15.math.fsum",
        "worlds_w18.math.exp",
        "worlds_w18.math.fsum",
        "worlds_w18.math.sqrt",
    }
    assert required_attributes <= set(
        mutation_runner._SOURCE_IDENTITY_ANCHORS["external_attributes"]
    )
    baseline = _source_digest("HonestSeededControl", frozenset())
    assert baseline.startswith("sha256:")

    monkeypatch.setattr(metrics.np, "max", lambda *args, **kwargs: -1.0)
    with pytest.raises(
        ProtocolViolation,
        match=r"external attribute identity mismatch: (?:evaluator|metrics)\.np\.max",
    ):
        _source_digest("HonestSeededControl", frozenset())


@pytest.mark.parametrize(
    ("owner", "attribute", "label"),
    (
        (compliance.random, "Random", "compliance.random.Random"),
        (compliance.os, "getpid", "compliance.os.getpid"),
        (compliance.math, "fsum", "compliance.math.fsum"),
    ),
)
def test_source_binding_rejects_dynamic_compliance_dependency_rewrite(
    monkeypatch, owner: object, attribute: str, label: str
) -> None:
    baseline = _source_digest("DangerousMeanCompressorControl", frozenset())
    assert baseline.startswith("sha256:")

    monkeypatch.setattr(owner, attribute, lambda *args, **kwargs: None)
    with pytest.raises(
        ProtocolViolation,
        match=rf"external attribute identity mismatch: {label}",
    ):
        _source_digest("DangerousMeanCompressorControl", frozenset())


@pytest.mark.parametrize(
    "class_expression",
    [
        "candidate_protocol.subprocess.Popen",
        "candidate_protocol.threading.Thread",
        "candidate_protocol.queue.Queue",
        "candidate_protocol.tempfile.TemporaryDirectory",
    ],
)
def test_source_binding_rejects_inherited_new_rewrite_in_isolated_process(
    class_expression: str,
) -> None:
    """Do not rewrite a shared ``object.__new__`` surface in pytest itself."""

    repository_root = candidate_protocol.Path(__file__).resolve().parents[2]
    script = inspect.cleandoc(
        f"""
        from prototype.unified_map import candidate_protocol
        from prototype.unified_map.canonical import ProtocolViolation
        from prototype.unified_map.mutation_runner import _source_digest

        owner = {class_expression}
        setattr(owner, "__new__", lambda *args, **kwargs: None)
        try:
            _source_digest("HonestSeededControl", frozenset())
        except ProtocolViolation as exc:
            assert "external attribute identity mismatch" in str(exc), str(exc)
        else:
            raise AssertionError("inherited __new__ rewrite was accepted")
        print("isolated-inherited-new-rejected")
        """
    )
    executable = str(
        candidate_protocol.Path(candidate_protocol.sys.executable).resolve()
    )
    completed = subprocess.run(
        [executable, "-S", "-c", script],
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert completed.stdout.strip() == "isolated-inherited-new-rejected"


def test_inherited_new_probe_block_leaves_parent_constructors_usable() -> None:
    """Canary the four constructors that must never be rewritten in pytest."""

    completed = subprocess.run(
        [sys.executable, "-S", "-c", "pass"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    thread_ran: list[bool] = []
    thread = candidate_protocol.threading.Thread(
        target=lambda: thread_ran.append(True)
    )
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert thread_ran == [True]

    work_queue = candidate_protocol.queue.Queue()
    work_queue.put("constructor-canary")
    assert work_queue.get_nowait() == "constructor-canary"

    with candidate_protocol.tempfile.TemporaryDirectory() as directory:
        assert candidate_protocol.Path(directory).is_dir()


@pytest.mark.parametrize(
    ("owner", "attribute", "replacement"),
    [
        (candidate_protocol.sys, "executable", "C:/unapproved/python.exe"),
        (candidate_protocol.sys, "base_prefix", "C:/unapproved/runtime"),
        (candidate_protocol.os, "devnull", "unapproved-null"),
        (candidate_protocol.subprocess, "PIPE", 123456),
        (candidate_protocol.os, "O_WRONLY", -1),
        (candidate_protocol.os, "O_RDWR", -1),
        (candidate_protocol.os, "O_CREAT", -1),
        (candidate_protocol.os, "O_TRUNC", -1),
        (candidate_protocol.os, "O_APPEND", -1),
        (candidate_protocol.os, "O_EXCL", -1),
    ],
)
def test_source_binding_rejects_spawn_and_audit_runtime_value_rewrite(
    monkeypatch, owner, attribute: str, replacement
) -> None:
    monkeypatch.setattr(owner, attribute, replacement)
    with pytest.raises(ProtocolViolation, match="external runtime value mismatch"):
        mutation_runner._external_runtime_value_contract(
            candidate_protocol=candidate_protocol
        )


def test_source_binding_binds_approved_worker_executable_exact_bytes() -> None:
    contract = mutation_runner._external_runtime_value_contract(
        candidate_protocol=candidate_protocol
    )
    executable = candidate_protocol.Path(candidate_protocol.sys.executable).resolve()
    raw = executable.read_bytes()
    assert contract["worker_executable"] == {
        "resolved_path": str(executable),
        "size_bytes": len(raw),
        "sha256": canonical.digest_bytes(raw),
    }


def test_source_binding_rejects_worker_bootstrap_environment_rewrite(
    monkeypatch,
) -> None:
    key = "SystemRoot"
    if key in candidate_protocol.os.environ:
        monkeypatch.setenv(key, candidate_protocol.os.environ[key] + "-rewritten")
    else:
        monkeypatch.setenv(key, "C:/unapproved-system-root")
    with pytest.raises(ProtocolViolation, match="external runtime value mismatch"):
        mutation_runner._external_runtime_value_contract(
            candidate_protocol=candidate_protocol
        )


def test_source_binding_rejects_candidate_protocol_origin_rewrite(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        candidate_protocol,
        "__file__",
        str(candidate_protocol.Path(candidate_protocol.__file__).with_name("poison.py")),
    )
    with pytest.raises(ProtocolViolation, match="external runtime value mismatch"):
        mutation_runner._external_runtime_value_contract(
            candidate_protocol=candidate_protocol
        )


def test_source_binding_tracks_in_place_external_method_code_rewrite(
    monkeypatch,
) -> None:
    baseline = _source_digest("HonestSeededControl", frozenset())

    def replacement(self, *args, **kwargs):
        del self, args, kwargs
        return None

    monkeypatch.setattr(
        candidate_protocol.subprocess.Popen.__init__,
        "__code__",
        replacement.__code__,
    )
    assert _source_digest("HonestSeededControl", frozenset()) != baseline


@pytest.mark.parametrize(
    ("owner", "attribute"),
    [
        (candidate_protocol.subprocess.Popen, "_wait"),
        (candidate_protocol.subprocess.Popen, "_internal_poll"),
        (candidate_protocol.threading.Thread, "run"),
        (candidate_protocol.queue.Queue, "_get"),
        (candidate_protocol.queue.Queue, "_put"),
    ],
)
def test_source_binding_rejects_external_internal_dispatch_rewrite(
    monkeypatch, owner, attribute: str
) -> None:
    monkeypatch.setattr(owner, attribute, lambda *args, **kwargs: None)
    with pytest.raises(
        ProtocolViolation, match="external class descriptor identity mismatch"
    ):
        _source_digest("HonestSeededControl", frozenset())


@pytest.mark.parametrize(
    ("owner", "attribute"),
    [
        (candidate_protocol.tempfile, "mkdtemp"),
        *(
            [(candidate_protocol.threading, "_start_joinable_thread")]
            if hasattr(candidate_protocol.threading, "_start_joinable_thread")
            else [(candidate_protocol.threading, "_start_new_thread")]
        ),
        *(
            [(candidate_protocol.subprocess, "_fork_exec")]
            if hasattr(candidate_protocol.subprocess, "_fork_exec")
            else [
                (
                    candidate_protocol.subprocess._winapi,
                    "CreateProcess",
                )
            ]
        ),
        (sys.modules[candidate_protocol.Path.__module__].io, "open"),
        (candidate_protocol.os.path, "realpath"),
    ],
)
def test_source_binding_rejects_external_module_global_dispatch_rewrite(
    monkeypatch, owner, attribute: str
) -> None:
    monkeypatch.setattr(owner, attribute, lambda *args, **kwargs: None)
    with pytest.raises(
        ProtocolViolation, match="external .*mismatch"
    ):
        _source_digest("HonestSeededControl", frozenset())


@pytest.mark.parametrize(
    ("owner", "attribute"),
    [
        (candidate_protocol, "_RUNTIME_IMPORT_CACHE_LOCK"),
        (candidate_protocol.os, "environ"),
    ],
)
def test_source_binding_rejects_critical_runtime_object_replacement(
    monkeypatch, owner, attribute: str
) -> None:
    replacement = {} if attribute == "environ" else object()
    monkeypatch.setattr(owner, attribute, replacement)
    with pytest.raises(
        ProtocolViolation, match="external runtime object identity mismatch"
    ):
        _source_digest("HonestSeededControl", frozenset())


@pytest.mark.parametrize(
    "malformed",
    [
        "sha256:+" + "a" * 63,
        "sha256:" + "A" * 64,
    ],
)
def test_execution_binding_digests_require_canonical_lowercase_hex(
    malformed: str,
) -> None:
    with pytest.raises(ProtocolViolation, match="lowercase hexadecimal"):
        compliance._binding_digest(malformed, "test digest")
    with pytest.raises(ProtocolViolation, match="lowercase hexadecimal"):
        mutation_runner._exact_digest(malformed, "test digest")


@pytest.mark.parametrize(
    "origin",
    [
        "/absolute/candidate.py",
        "candidate_bundle\\control.py",
        "candidate_bundle/../control.py",
        "C:/candidate/control.py",
    ],
)
def test_execution_binding_rejects_noncanonical_module_origin(
    origin: str,
) -> None:
    collector = compliance._ExecutionBindingCollector()
    collector.observe(types.SimpleNamespace(**_binding_kwargs(origin=origin)))
    assert not collector.complete
    assert any("canonical bundle-relative POSIX" in item for item in collector.violations)

    report = types.SimpleNamespace(
        candidate="module:qualname", **_binding_kwargs(origin=origin)
    )
    with pytest.raises(ProtocolViolation, match="canonical bundle-relative POSIX"):
        mutation_runner._report_execution_binding(
            report, expected_candidate="module:qualname"
        )


def test_source_binding_tracks_generated_dataclass_method_defaults(
    monkeypatch,
) -> None:
    baseline = _source_digest("HonestSeededControl", frozenset())
    initializer = mutation_matrix.MutationObservation.__init__
    monkeypatch.setattr(initializer, "__defaults__", ("altered-classification",))
    assert _source_digest("HonestSeededControl", frozenset()) != baseline


def test_fresh_standalone_source_witness_is_stable_before_and_after_execution() -> None:
    repository_root = candidate_protocol.Path(__file__).resolve().parents[2]
    script = inspect.cleandoc(
        """
        import tempfile

        assert tempfile.tempdir is None
        assert tempfile._name_sequence is None

        from prototype.unified_map.canonical import digest_json
        from prototype.unified_map.compliance import (
            control_entrypoint,
            evaluate_candidate_compliance,
        )
        from prototype.unified_map.mutation_runner import (
            _prepare_runtime_import_cache,
            _source_binding_witness,
            _source_digest,
        )
        from prototype.unified_map.schema import (
            ActionPlan,
            CandidateVisibleEvent,
            DiagnosisQuery,
            EventKind,
            PlanKind,
            RolloutQuery,
            VisibleHistory,
        )

        first = _source_digest("HonestSeededControl", frozenset())
        second = _source_digest("HonestSeededControl", frozenset())
        assert first == second

        catalog = "sha256:" + "c" * 64
        utility = "sha256:" + "d" * 64
        history = VisibleHistory(
            (
                CandidateVisibleEvent(
                    EventKind.OBSERVATION_AVAILABLE,
                    occurred_at=0,
                    available_at=0,
                    event_uid="standalone-source-witness",
                    payload={"signal": 0.88},
                ),
            ),
            0,
            catalog,
        )
        diagnosis = DiagnosisQuery(("a", "b"))
        rollout = RolloutQuery(
            2,
            ActionPlan(PlanKind.NO_NEW_ACTION),
            ("x",),
            utility,
        )
        cache_contract_digest = digest_json(_prepare_runtime_import_cache())
        pre = _source_binding_witness(
            "HonestSeededControl",
            frozenset(),
            expected_runtime_import_cache_contract_digest=cache_contract_digest,
        )
        report = evaluate_candidate_compliance(
            control_entrypoint("HonestSeededControl"),
            history=history,
            diagnosis_query=diagnosis,
            rollout_query=rollout,
            seed=7331,
            semantic_probes=frozenset(),
        )
        post = _source_binding_witness(
            "HonestSeededControl",
            frozenset(),
            expected_runtime_import_cache_contract_digest=cache_contract_digest,
        )
        assert report.candidate.endswith(":HonestSeededControl")
        assert digest_json(pre) == digest_json(post)
        print("fresh-source-and-pre-post-stable")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert completed.stdout.strip() == "fresh-source-and-pre-post-stable"


def test_transient_self_restore_during_execution_cannot_produce_a_kill(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()
    case = mutation_runner.PORTABLE_MUTATION_CASES[0]
    finding = compliance.ComplianceFinding(
        gate="C04-clean-process-replay",
        verdict=ComplianceVerdict.FAIL,
        failure_code=case.expected_failure_code,
        detail="synthetic decisive result",
    )
    report = compliance.ComplianceReport(
        candidate="test:self-restoring",
        operational_state_closure=ComplianceVerdict.FAIL,
        semantic_unity=ComplianceVerdict.INCOMPLETE,
        isolation_completeness=ComplianceVerdict.INCOMPLETE,
        isolation_assurance="test",
        findings=(finding,),
        **_binding_kwargs(),
    )
    original_compliance_evaluator = compliance.evaluate_candidate_compliance
    original_runner_evaluator = mutation_runner.evaluate_candidate_compliance

    def self_restoring_evaluator(*args, **kwargs):
        del args, kwargs
        compliance.evaluate_candidate_compliance = original_compliance_evaluator
        mutation_runner.evaluate_candidate_compliance = original_runner_evaluator
        return report

    monkeypatch.setattr(
        compliance, "evaluate_candidate_compliance", self_restoring_evaluator
    )
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", self_restoring_evaluator
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", (case,))
    monkeypatch.setattr(mutation_runner, "PORTABLE_SPECIFICITY_CASES", ())

    bundle = run_portable_mutation_evidence(
        run_id="self-restoring-source-59",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=59,
    )
    rows = bundle.observations

    assert len(rows) == 1
    assert rows[0].outcome is mutation_matrix.ObservationOutcome.CRASHED
    assert rows[0].actual_failure_code is None
    assert rows[0].decisive_record_digest is None


def test_pre_execution_source_witness_failure_is_recorded_per_row(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()
    mutant_case = mutation_runner.PORTABLE_MUTATION_CASES[0]
    specificity_case = mutation_runner.PORTABLE_SPECIFICITY_CASES[0]
    witness_calls = 0

    def unavailable_witness(*args, **kwargs):
        nonlocal witness_calls
        del args, kwargs
        witness_calls += 1
        raise RuntimeError("source witness unavailable before execution")

    def evaluator_must_not_run(*args, **kwargs):
        del args, kwargs
        raise AssertionError("candidate execution must not start without a witness")

    def prepared_cache():
        return {"protocol": "test-runtime-cache", "cache_digest": CATALOG}

    monkeypatch.setattr(
        mutation_runner, "_prepare_runtime_import_cache", prepared_cache
    )
    monkeypatch.setattr(mutation_runner, "_source_binding_witness", unavailable_witness)
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator_must_not_run
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", (mutant_case,))
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_SPECIFICITY_CASES", (specificity_case,)
    )

    bundle = run_portable_mutation_evidence(
        run_id="pre-source-unavailable-63",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=63,
    )
    rows = bundle.observations

    assert len(rows) == 2
    assert all(
        row.outcome is mutation_matrix.ObservationOutcome.CRASHED for row in rows
    )
    assert all(row.actual_failure_code is None for row in rows)
    assert all(row.decisive_record_digest is None for row in rows)
    assert rows[0].source_digest != rows[1].source_digest
    assert witness_calls == 4
    for record in bundle.records:
        assert record.report_transcript_digest is None
        assert _blob_payload(bundle, record.post_source_witness_digest)[
            "stage"
        ] == "post-execution"
        error = _blob_payload(bundle, record.error_transcript_digest)
        assert error["status"] == "error"
        assert [item["stage"] for item in error["errors"]] == [
            "pre-execution",
            "post-execution",
        ]
        assert _blob_payload(bundle, record.decision_record_digest)[
            "derived_outcome"
        ] == "crashed"


def test_paired_specificity_probe_is_inside_pre_post_source_witness(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()
    paired_case = next(
        row
        for row in mutation_runner.PORTABLE_SPECIFICITY_CASES
        if row[0] == "BehaviorEquivalentSerialization"
    )
    binding = _binding_kwargs()
    witness_calls = 0
    paired_calls = 0

    def prepared_cache():
        return {"protocol": "test-runtime-cache", "cache_digest": CATALOG}

    def witness(control_class_name, semantic_probes, **kwargs):
        nonlocal witness_calls
        execution_seed = kwargs["execution_seed"]
        entrypoint = mutation_runner.control_entrypoint(control_class_name)
        witness_calls += 1
        return {
            "protocol": "test-source-witness",
            "control": control_class_name,
            "expected_candidate": f"{entrypoint.module}:{entrypoint.qualname}",
            "execution_seed": execution_seed,
            "enabled_semantic_probes": sorted(semantic_probes),
            "semantic_abs_tolerance": compliance.SEMANTIC_ABS_TOLERANCE,
            "expected_live_execution_binding": dict(binding),
        }

    def evaluator(entrypoint, **kwargs):
        del kwargs
        return compliance.ComplianceReport(
            candidate=f"{entrypoint.module}:{entrypoint.qualname}",
            operational_state_closure=ComplianceVerdict.PASS,
            semantic_unity=ComplianceVerdict.INCOMPLETE,
            isolation_completeness=ComplianceVerdict.INCOMPLETE,
            isolation_assurance="test",
            findings=(),
            head_records=(),
            **binding,
        )

    def tampering_paired_probe(**kwargs):
        nonlocal paired_calls
        del kwargs
        paired_calls += 1
        monkeypatch.setattr(
            compliance,
            "SEMANTIC_ABS_TOLERANCE",
            compliance.SEMANTIC_ABS_TOLERANCE + 1.0,
        )
        return {"protocol": "test-paired-probe", "passed": True}

    monkeypatch.setattr(
        mutation_runner, "_prepare_runtime_import_cache", prepared_cache
    )
    monkeypatch.setattr(mutation_runner, "_source_binding_witness", witness)
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator
    )
    monkeypatch.setattr(
        mutation_runner,
        "paired_serialization_equivalence_evidence",
        tampering_paired_probe,
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", ())
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_SPECIFICITY_CASES", (paired_case,)
    )

    bundle = run_portable_mutation_evidence(
        run_id="paired-probe-source-drift-64",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=64,
    )
    rows = bundle.observations

    assert paired_calls == 1
    assert witness_calls == 2
    assert len(rows) == 1
    assert rows[0].outcome is mutation_matrix.ObservationOutcome.CRASHED
    assert rows[0].decisive_record_digest is None
    record = bundle.records[0]
    assert _blob_payload(bundle, record.pre_source_witness_digest) != _blob_payload(
        bundle, record.post_source_witness_digest
    )
    error = _blob_payload(bundle, record.error_transcript_digest)
    assert error["status"] == "error"
    assert any(
        item["stage"] == "post-execution"
        and item["exception_type"] == "UCM-E003-HARNESS_INCOMPLETE"
        for item in error["errors"]
    )


def test_runner_executes_captured_snapshot_after_caller_nested_mutation(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = mutable_nested_inputs()
    captured_preimage = json.loads(
        canonical.canonical_json_bytes(
            {
                "history": history.to_wire(),
                "diagnosis_query": diagnosis.to_wire(),
                "rollout_query": rollout.to_wire(),
                "delta": delta.to_wire(),
            }
        )
    )
    case = next(
        row
        for row in mutation_runner.PORTABLE_MUTATION_CASES
        if row.matrix_subject_id == "FileHandleState"
    )
    witness_calls = 0
    evaluated_inputs: list[tuple[object, ...]] = []

    def prepared_cache():
        return {"protocol": "test-runtime-cache", "cache_digest": CATALOG}

    def witness(control_class_name, semantic_probes, **kwargs):
        nonlocal witness_calls
        if witness_calls == 0:
            history.events[0].payload["nested"]["value"] = "caller-mutated"
            rollout.plan.actions[0].parameters["nested"]["amount"] = 99
            delta.events[0].payload["nested"]["value"] = "caller-delta-mutated"
        witness_calls += 1
        execution_seed = kwargs["execution_seed"]
        entrypoint = mutation_runner.control_entrypoint(control_class_name)
        return {
            "protocol": "test-source-witness",
            "control": control_class_name,
            "expected_candidate": f"{entrypoint.module}:{entrypoint.qualname}",
            "execution_seed": execution_seed,
            "enabled_semantic_probes": sorted(semantic_probes),
        }

    def evaluator(entrypoint, **kwargs):
        del entrypoint
        execution_inputs = (
            kwargs["history"],
            kwargs["diagnosis_query"],
            kwargs["rollout_query"],
            kwargs["delta"],
        )
        evaluated_inputs.append(execution_inputs)
        assert execution_inputs[0].to_wire() == captured_preimage["history"]
        assert execution_inputs[1].to_wire() == captured_preimage["diagnosis_query"]
        assert execution_inputs[2].to_wire() == captured_preimage["rollout_query"]
        assert execution_inputs[3].to_wire() == captured_preimage["delta"]
        assert execution_inputs[0] is not history
        assert execution_inputs[2] is not rollout
        raise RuntimeError("intentional stop after detached-input assertion")

    monkeypatch.setattr(
        mutation_runner, "_prepare_runtime_import_cache", prepared_cache
    )
    monkeypatch.setattr(mutation_runner, "_source_binding_witness", witness)
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", (case,))
    monkeypatch.setattr(mutation_runner, "PORTABLE_SPECIFICITY_CASES", ())

    bundle = run_portable_mutation_evidence(
        run_id="captured-input-vs-caller-mutation-69",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=69,
    )

    assert len(evaluated_inputs) == 1
    assert history.events[0].payload["nested"]["value"] == "caller-mutated"
    assert rollout.plan.actions[0].parameters["nested"]["amount"] == 99
    context = json.loads(
        bundle.blob_bytes(bundle.execution_context_digest).decode("utf-8")
    )
    captured_blob = json.loads(
        bundle.blob_bytes(context["input_preimage_digest"]).decode("utf-8")
    )
    assert captured_blob["payload"] == captured_preimage
    assert mutation_evidence.MutationEvidenceBundle.from_canonical_bytes(
        bundle.canonical_bytes()
    ) == bundle


def test_one_row_input_mutation_cannot_pollute_a_later_row(monkeypatch) -> None:
    history, diagnosis, rollout, delta = mutable_nested_inputs()
    cases = tuple(
        row
        for row in mutation_runner.PORTABLE_MUTATION_CASES
        if row.matrix_subject_id in {"FileHandleState", "RawHistoryHead"}
    )
    seen_inputs: list[
        tuple[VisibleHistory, DiagnosisQuery, RolloutQuery, VisibleDelta | None]
    ] = []

    def prepared_cache():
        return {"protocol": "test-runtime-cache", "cache_digest": CATALOG}

    def witness(control_class_name, semantic_probes, **kwargs):
        execution_seed = kwargs["execution_seed"]
        entrypoint = mutation_runner.control_entrypoint(control_class_name)
        return {
            "protocol": "test-source-witness",
            "control": control_class_name,
            "expected_candidate": f"{entrypoint.module}:{entrypoint.qualname}",
            "execution_seed": execution_seed,
            "enabled_semantic_probes": sorted(semantic_probes),
        }

    def evaluator(entrypoint, **kwargs):
        del entrypoint
        row_inputs = (
            kwargs["history"],
            kwargs["diagnosis_query"],
            kwargs["rollout_query"],
            kwargs["delta"],
        )
        seen_inputs.append(row_inputs)
        assert row_inputs[0].events[0].payload["nested"]["value"] == "captured"
        assert (
            row_inputs[2].plan.actions[0].parameters["nested"]["amount"] == 1
        )
        assert row_inputs[3].events[0].payload["nested"]["value"] == (
            "captured-delta"
        )
        if len(seen_inputs) == 1:
            row_inputs[0].events[0].payload["nested"]["value"] = "row-one"
            row_inputs[2].plan.actions[0].parameters["nested"]["amount"] = 77
            row_inputs[3].events[0].payload["nested"]["value"] = "row-one-delta"
        raise RuntimeError("intentional per-row execution stop")

    monkeypatch.setattr(
        mutation_runner, "_prepare_runtime_import_cache", prepared_cache
    )
    monkeypatch.setattr(mutation_runner, "_source_binding_witness", witness)
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", cases)
    monkeypatch.setattr(mutation_runner, "PORTABLE_SPECIFICITY_CASES", ())

    bundle = run_portable_mutation_evidence(
        run_id="per-row-input-copy-isolation-70",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=70,
    )

    assert len(seen_inputs) == 2
    assert seen_inputs[0][0] is not seen_inputs[1][0]
    assert seen_inputs[0][2] is not seen_inputs[1][2]
    assert seen_inputs[0][3] is not seen_inputs[1][3]
    stages = [
        {
            item["stage"]
            for item in _blob_payload(bundle, record.error_transcript_digest)[
                "errors"
            ]
        }
        for record in bundle.records
    ]
    assert "execution-input-postcondition" in stages[0]
    assert "execution-input-postcondition" not in stages[1]
    assert history.events[0].payload["nested"]["value"] == "captured"
    assert rollout.plan.actions[0].parameters["nested"]["amount"] == 1
    assert mutation_evidence.MutationEvidenceBundle.from_canonical_bytes(
        bundle.canonical_bytes()
    ) == bundle


def test_paired_probe_reparses_independent_inputs_after_control_mutation(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = mutable_nested_inputs()
    paired_case = next(
        row
        for row in mutation_runner.PORTABLE_SPECIFICITY_CASES
        if row[0] == "BehaviorEquivalentSerialization"
    )
    binding = _binding_kwargs()
    control_inputs: list[tuple[object, ...]] = []
    paired_inputs: list[tuple[object, ...]] = []

    def prepared_cache():
        return {"protocol": "test-runtime-cache", "cache_digest": CATALOG}

    def witness(control_class_name, semantic_probes, **kwargs):
        execution_seed = kwargs["execution_seed"]
        entrypoint = mutation_runner.control_entrypoint(control_class_name)
        return {
            "protocol": "test-source-witness",
            "control": control_class_name,
            "expected_candidate": f"{entrypoint.module}:{entrypoint.qualname}",
            "execution_seed": execution_seed,
            "enabled_semantic_probes": sorted(semantic_probes),
            "expected_live_execution_binding": dict(binding),
        }

    def evaluator(entrypoint, **kwargs):
        row_inputs = (
            kwargs["history"],
            kwargs["diagnosis_query"],
            kwargs["rollout_query"],
            kwargs["delta"],
        )
        control_inputs.append(row_inputs)
        row_inputs[0].events[0].payload["nested"]["value"] = "control-mutated"
        row_inputs[2].plan.actions[0].parameters["nested"]["amount"] = 55
        return compliance.ComplianceReport(
            candidate=f"{entrypoint.module}:{entrypoint.qualname}",
            operational_state_closure=ComplianceVerdict.PASS,
            semantic_unity=ComplianceVerdict.INCOMPLETE,
            isolation_completeness=ComplianceVerdict.INCOMPLETE,
            isolation_assurance="test",
            findings=(),
            head_records=(),
            **binding,
        )

    def paired_probe(**kwargs):
        probe_inputs = (
            kwargs["history"],
            kwargs["diagnosis_query"],
            kwargs["rollout_query"],
            kwargs["delta"],
        )
        paired_inputs.append(probe_inputs)
        assert probe_inputs[0].events[0].payload["nested"]["value"] == "captured"
        assert probe_inputs[2].plan.actions[0].parameters["nested"]["amount"] == 1
        return {"protocol": "test-paired-probe", "passed": True}

    monkeypatch.setattr(
        mutation_runner, "_prepare_runtime_import_cache", prepared_cache
    )
    monkeypatch.setattr(mutation_runner, "_source_binding_witness", witness)
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator
    )
    monkeypatch.setattr(
        mutation_runner, "paired_serialization_equivalence_evidence", paired_probe
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", ())
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_SPECIFICITY_CASES", (paired_case,)
    )

    bundle = run_portable_mutation_evidence(
        run_id="paired-probe-input-copy-isolation-71",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=71,
    )

    assert len(control_inputs) == len(paired_inputs) == 1
    assert control_inputs[0][0] is not paired_inputs[0][0]
    assert control_inputs[0][2] is not paired_inputs[0][2]
    error = _blob_payload(bundle, bundle.records[0].error_transcript_digest)
    assert any(
        item["stage"] == "execution-input-postcondition"
        and item["exception_type"] == "UCM-E003-HARNESS_INCOMPLETE"
        for item in error["errors"]
    )
    assert not any(
        item["stage"] == "paired-input-postcondition" for item in error["errors"]
    )
    assert mutation_evidence.MutationEvidenceBundle.from_canonical_bytes(
        bundle.canonical_bytes()
    ) == bundle


def test_runtime_inventory_prewarm_failure_is_recorded_per_row(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()
    mutant_case = mutation_runner.PORTABLE_MUTATION_CASES[0]
    specificity_case = mutation_runner.PORTABLE_SPECIFICITY_CASES[0]

    def unavailable_inventory(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("runtime inventory unavailable")

    def evaluator_must_not_run(*args, **kwargs):
        del args, kwargs
        raise AssertionError("candidate execution must not start without inventory")

    monkeypatch.setattr(
        candidate_protocol, "_runtime_import_read_allowlist", unavailable_inventory
    )
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator_must_not_run
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", (mutant_case,))
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_SPECIFICITY_CASES", (specificity_case,)
    )

    bundle = run_portable_mutation_evidence(
        run_id="runtime-prewarm-unavailable-65",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=65,
    )
    rows = bundle.observations

    assert len(rows) == 2
    assert all(
        row.outcome is mutation_matrix.ObservationOutcome.CRASHED for row in rows
    )
    assert all(row.decisive_record_digest is None for row in rows)


def test_transient_runtime_inventory_builder_cannot_poison_then_restore(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()
    mutant_case = mutation_runner.PORTABLE_MUTATION_CASES[0]
    original = candidate_protocol._runtime_import_read_allowlist
    poison_calls = 0

    def poison_then_restore(*, deadline):
        nonlocal poison_calls
        del deadline
        poison_calls += 1
        path = candidate_protocol._normalized_file_path(
            candidate_protocol.Path.cwd() / "judge-private.py"
        )
        poisoned = (
            ((path, 0, canonical.digest_bytes(b"")),),
            (),
            (path,),
            1,
            0,
        )
        monkeypatch.setattr(candidate_protocol, "_RUNTIME_IMPORT_CACHE", poisoned)
        monkeypatch.setattr(
            candidate_protocol, "_runtime_import_read_allowlist", original
        )
        return poisoned

    def evaluator_must_not_run(*args, **kwargs):
        del args, kwargs
        raise AssertionError("candidate execution must not start after cache poisoning")

    monkeypatch.setattr(
        candidate_protocol, "_runtime_import_read_allowlist", poison_then_restore
    )
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator_must_not_run
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", (mutant_case,))
    monkeypatch.setattr(mutation_runner, "PORTABLE_SPECIFICITY_CASES", ())

    bundle = run_portable_mutation_evidence(
        run_id="runtime-cache-poison-66",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=66,
    )
    rows = bundle.observations

    assert poison_calls == 0
    assert len(rows) == 1
    assert rows[0].outcome is mutation_matrix.ObservationOutcome.CRASHED
    assert rows[0].actual_failure_code is None
    assert rows[0].decisive_record_digest is None


def test_runtime_inventory_zip_authority_helper_is_preverified(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        candidate_protocol, "_approved_runtime_zip_paths", lambda: ()
    )

    with pytest.raises(
        ProtocolViolation, match="runtime inventory callable identity mismatch"
    ):
        mutation_runner._prepare_runtime_import_cache()


def test_runtime_import_cache_rejects_pruned_site_packages_authority(
    monkeypatch,
) -> None:
    root = mutation_runner._SOURCE_IDENTITY_ANCHORS["runtime_import_roots"][0]
    separator = mutation_runner._SOURCE_IDENTITY_ANCHORS["runtime_path_separator"]
    path = separator.join((root.rstrip(separator), "site-packages", "judge.py"))
    poisoned = (
        ((path, 0, canonical.digest_bytes(b"")),),
        (),
        (path,),
        1,
        0,
    )
    monkeypatch.setattr(candidate_protocol, "_RUNTIME_IMPORT_CACHE", poisoned)

    with pytest.raises(ProtocolViolation, match="pruned import tree"):
        mutation_runner._runtime_import_cache_contract(
            candidate_protocol=candidate_protocol
        )


def test_preexisting_runtime_cache_must_match_clean_rebuild(monkeypatch) -> None:
    monkeypatch.setattr(
        candidate_protocol,
        "_RUNTIME_IMPORT_CACHE",
        ((), (), (), 0, 0),
    )

    with pytest.raises(ProtocolViolation, match="did not match clean rebuild"):
        mutation_runner._prepare_runtime_import_cache()


def test_preseeded_cache_and_matching_verified_digest_cannot_skip_clean_rebuild(
    monkeypatch,
) -> None:
    mutation_runner._prepare_runtime_import_cache()
    legitimate = candidate_protocol._RUNTIME_IMPORT_CACHE
    assert type(legitimate) is tuple and len(legitimate) == 5
    entries, absent_paths, allowed_paths, actual_files, total_bytes = legitimate
    approved_archives = {
        candidate_protocol._normalized_file_path(path)
        for path in candidate_protocol._approved_runtime_zip_paths()
    }
    removed_index = next(
        index
        for index, (path, _size, _digest) in enumerate(entries)
        if path not in approved_archives and path not in absent_paths
    )
    removed_path, removed_size, _removed_digest = entries[removed_index]
    poisoned = (
        entries[:removed_index] + entries[removed_index + 1 :],
        absent_paths,
        tuple(path for path in allowed_paths if path != removed_path),
        actual_files - 1,
        total_bytes - removed_size,
    )
    monkeypatch.setattr(candidate_protocol, "_RUNTIME_IMPORT_CACHE", poisoned)
    poison_contract = mutation_runner._runtime_import_cache_contract(
        candidate_protocol=candidate_protocol
    )
    # This was the old provenance bypass: both mutable globals agreed on the
    # same incomplete cache, so no clean inventory was ever rebuilt.
    monkeypatch.setattr(
        mutation_runner,
        "_VERIFIED_RUNTIME_IMPORT_CACHE_DIGEST",
        poison_contract["cache_digest"],
        raising=False,
    )

    with pytest.raises(ProtocolViolation, match="did not match clean rebuild"):
        mutation_runner._prepare_runtime_import_cache()


def test_runner_records_harness_exceptions_and_incomplete_controls_as_crashed(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()
    mutant_case = mutation_runner.PORTABLE_MUTATION_CASES[0]
    specificity_case = mutation_runner.PORTABLE_SPECIFICITY_CASES[0]
    incomplete = compliance.ComplianceFinding(
        gate="candidate-worker-initialize",
        verdict=ComplianceVerdict.INCOMPLETE,
        failure_code="UCM-E003-HARNESS_INCOMPLETE",
        detail="synthetic harness failure",
    )

    def evaluator(entrypoint, **kwargs):
        del kwargs
        if entrypoint.qualname == mutant_case.control_class_name:
            raise RuntimeError("synthetic evaluator crash")
        return compliance.ComplianceReport(
            candidate=f"{entrypoint.module}:{entrypoint.qualname}",
            operational_state_closure=ComplianceVerdict.INCOMPLETE,
            semantic_unity=ComplianceVerdict.INCOMPLETE,
            isolation_completeness=ComplianceVerdict.INCOMPLETE,
            isolation_assurance="test",
            findings=(incomplete,),
            **_binding_kwargs(),
        )

    monkeypatch.setattr(compliance, "evaluate_candidate_compliance", evaluator)
    monkeypatch.setattr(mutation_runner, "evaluate_candidate_compliance", evaluator)
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_MUTATION_CASES", (mutant_case,)
    )
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_SPECIFICITY_CASES", (specificity_case,)
    )
    bundle = run_portable_mutation_evidence(
        run_id="harness-exceptions-67",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=67,
    )
    rows = bundle.observations

    assert [row.outcome for row in rows] == [
        mutation_matrix.ObservationOutcome.CRASHED,
        mutation_matrix.ObservationOutcome.CRASHED,
    ]
    assert all(row.actual_failure_code is None for row in rows)
    assert all(row.decisive_record_digest is None for row in rows)
    by_kind = {record.observation.subject_kind: record for record in bundle.records}
    mutant_record = by_kind[mutation_matrix.SubjectKind.MUTANT]
    control_record = by_kind[mutation_matrix.SubjectKind.SPECIFICITY_CONTROL]
    assert mutant_record.report_transcript_digest is None
    assert _blob_payload(
        bundle, mutant_record.pre_source_witness_digest
    ) == _blob_payload(bundle, mutant_record.post_source_witness_digest)
    assert "candidate-evaluation" in {
        item["stage"]
        for item in _blob_payload(
            bundle, mutant_record.error_transcript_digest
        )["errors"]
    }
    assert control_record.report_transcript_digest is not None
    assert "compliance-report" in {
        item["stage"]
        for item in _blob_payload(
            bundle, control_record.error_transcript_digest
        )["errors"]
    }
    assert all(
        _blob_payload(bundle, record.decision_record_digest)["derived_outcome"]
        == "crashed"
        for record in bundle.records
    )


def test_evaluator_none_is_a_serializable_zero_request_crash(monkeypatch) -> None:
    history, diagnosis, rollout, delta = inputs()
    mutant_case = mutation_runner.PORTABLE_MUTATION_CASES[0]
    binding = _binding_kwargs()

    def prepared_cache():
        return {"protocol": "test-runtime-cache", "cache_digest": CATALOG}

    def witness(control_class_name, semantic_probes, **kwargs):
        execution_seed = kwargs["execution_seed"]
        entrypoint = mutation_runner.control_entrypoint(control_class_name)
        return {
            "protocol": "test-source-witness",
            "control": control_class_name,
            "expected_candidate": f"{entrypoint.module}:{entrypoint.qualname}",
            "execution_seed": execution_seed,
            "enabled_semantic_probes": sorted(semantic_probes),
            "expected_live_execution_binding": dict(binding),
        }

    def evaluator(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr(
        mutation_runner, "_prepare_runtime_import_cache", prepared_cache
    )
    monkeypatch.setattr(mutation_runner, "_source_binding_witness", witness)
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator
    )
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_MUTATION_CASES", (mutant_case,)
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_SPECIFICITY_CASES", ())

    bundle = run_portable_mutation_evidence(
        run_id="evaluator-none-zero-request-72",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=72,
    )

    assert len(bundle.records) == 1
    record = bundle.records[0]
    assert record.observation.outcome is mutation_matrix.ObservationOutcome.CRASHED
    assert record.report_transcript_digest is None
    error = _blob_payload(bundle, record.error_transcript_digest)
    assert error["status"] == "error"
    assert any(
        item["stage"] == "candidate-evaluation"
        and "returned no report" in item["message"]
        for item in error["errors"]
    )
    context = json.loads(
        bundle.blob_bytes(bundle.execution_context_digest).decode("utf-8")
    )
    decision = _blob_payload(bundle, record.decision_record_digest)
    assert decision["input_preimage_digest"] == context["input_preimage_digest"]
    assert decision["invocation_transcript_digest"] == canonical.digest_json([])
    assert mutation_evidence.MutationEvidenceBundle.from_canonical_bytes(
        bundle.canonical_bytes()
    ) == bundle


def test_empty_request_report_is_retained_but_cannot_be_decisive(monkeypatch) -> None:
    history, diagnosis, rollout, delta = inputs()
    specificity_case = mutation_runner.PORTABLE_SPECIFICITY_CASES[0]
    binding = _binding_kwargs()

    def prepared_cache():
        return {"protocol": "test-runtime-cache", "cache_digest": CATALOG}

    def witness(control_class_name, semantic_probes, **kwargs):
        execution_seed = kwargs["execution_seed"]
        entrypoint = mutation_runner.control_entrypoint(control_class_name)
        return {
            "protocol": "test-source-witness",
            "control": control_class_name,
            "expected_candidate": f"{entrypoint.module}:{entrypoint.qualname}",
            "execution_seed": execution_seed,
            "enabled_semantic_probes": sorted(semantic_probes),
            "expected_live_execution_binding": dict(binding),
        }

    def evaluator(entrypoint, **kwargs):
        del kwargs
        return compliance.ComplianceReport(
            candidate=f"{entrypoint.module}:{entrypoint.qualname}",
            operational_state_closure=ComplianceVerdict.PASS,
            semantic_unity=ComplianceVerdict.INCOMPLETE,
            isolation_completeness=ComplianceVerdict.INCOMPLETE,
            isolation_assurance="test",
            findings=(),
            head_records=(),
            **binding,
        )

    monkeypatch.setattr(
        mutation_runner, "_prepare_runtime_import_cache", prepared_cache
    )
    monkeypatch.setattr(mutation_runner, "_source_binding_witness", witness)
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", ())
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_SPECIFICITY_CASES", (specificity_case,)
    )

    bundle = run_portable_mutation_evidence(
        run_id="empty-request-report-73",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=73,
    )

    record = bundle.records[0]
    assert record.observation.outcome is mutation_matrix.ObservationOutcome.CRASHED
    assert record.observation.decisive_record_digest is None
    assert record.report_transcript_digest is not None
    report = _blob_payload(bundle, record.report_transcript_digest)
    assert report["request_records"] == []
    assert report["invocation_transcript_digest"] == canonical.digest_json([])
    decision = _blob_payload(bundle, record.decision_record_digest)
    assert decision["invocation_transcript_digest"] == canonical.digest_json([])
    error = _blob_payload(bundle, record.error_transcript_digest)
    assert any(
        item["stage"] == "report-decisive-validation"
        and "cannot prove that candidate execution started" in item["message"]
        for item in error["errors"]
    )


def test_paired_probe_non_object_is_typed_fail_closed(monkeypatch) -> None:
    history, diagnosis, rollout, delta = inputs()
    paired_case = next(
        row
        for row in mutation_runner.PORTABLE_SPECIFICITY_CASES
        if row[0] == "BehaviorEquivalentSerialization"
    )
    binding = _binding_kwargs()

    def prepared_cache():
        return {"protocol": "test-runtime-cache", "cache_digest": CATALOG}

    def witness(control_class_name, semantic_probes, **kwargs):
        execution_seed = kwargs["execution_seed"]
        entrypoint = mutation_runner.control_entrypoint(control_class_name)
        return {
            "protocol": "test-source-witness",
            "control": control_class_name,
            "expected_candidate": f"{entrypoint.module}:{entrypoint.qualname}",
            "execution_seed": execution_seed,
            "enabled_semantic_probes": sorted(semantic_probes),
            "expected_live_execution_binding": dict(binding),
        }

    def evaluator(entrypoint, **kwargs):
        del kwargs
        return compliance.ComplianceReport(
            candidate=f"{entrypoint.module}:{entrypoint.qualname}",
            operational_state_closure=ComplianceVerdict.PASS,
            semantic_unity=ComplianceVerdict.INCOMPLETE,
            isolation_completeness=ComplianceVerdict.INCOMPLETE,
            isolation_assurance="test",
            findings=(),
            head_records=(),
            **binding,
        )

    monkeypatch.setattr(
        mutation_runner, "_prepare_runtime_import_cache", prepared_cache
    )
    monkeypatch.setattr(mutation_runner, "_source_binding_witness", witness)
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator
    )
    monkeypatch.setattr(
        mutation_runner,
        "paired_serialization_equivalence_evidence",
        lambda **kwargs: [kwargs["seed"]],
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_MUTATION_CASES", ())
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_SPECIFICITY_CASES", (paired_case,)
    )

    bundle = run_portable_mutation_evidence(
        run_id="paired-non-object-74",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=74,
    )

    record = bundle.records[0]
    assert record.observation.outcome is mutation_matrix.ObservationOutcome.CRASHED
    assert record.observation.decisive_record_digest is None
    error = _blob_payload(bundle, record.error_transcript_digest)
    paired_errors = [
        item for item in error["errors"] if item["stage"] == "paired-semantic-probe"
    ]
    assert len(paired_errors) == 1
    assert paired_errors[0]["exception_type"].endswith(".ProtocolViolation")
    assert "non-object" in paired_errors[0]["message"]


def test_unrenderable_harness_exception_is_retained_as_typed_error(
    monkeypatch,
) -> None:
    history, diagnosis, rollout, delta = inputs()
    mutant_case = mutation_runner.PORTABLE_MUTATION_CASES[0]
    binding = _binding_kwargs()

    class UnrenderableHarnessError(RuntimeError):
        def __str__(self) -> str:
            raise RuntimeError("exception rendering also failed")

    def prepared_cache():
        return {"protocol": "test-runtime-cache", "cache_digest": CATALOG}

    def witness(control_class_name, semantic_probes, **kwargs):
        execution_seed = kwargs["execution_seed"]
        entrypoint = mutation_runner.control_entrypoint(control_class_name)
        return {
            "protocol": "test-source-witness",
            "control": control_class_name,
            "expected_candidate": f"{entrypoint.module}:{entrypoint.qualname}",
            "execution_seed": execution_seed,
            "enabled_semantic_probes": sorted(semantic_probes),
            "expected_live_execution_binding": dict(binding),
        }

    def evaluator(entrypoint, **kwargs):
        del kwargs
        return compliance.ComplianceReport(
            candidate=f"{entrypoint.module}:{entrypoint.qualname}",
            operational_state_closure=ComplianceVerdict.PASS,
            semantic_unity=ComplianceVerdict.PASS,
            isolation_completeness=ComplianceVerdict.PASS,
            isolation_assurance="test",
            findings=(),
            head_records=(),
            **binding,
        )

    def unrenderable_binding(*args, **kwargs):
        del args, kwargs
        raise UnrenderableHarnessError()

    monkeypatch.setattr(
        mutation_runner, "_prepare_runtime_import_cache", prepared_cache
    )
    monkeypatch.setattr(mutation_runner, "_source_binding_witness", witness)
    monkeypatch.setattr(
        mutation_runner, "evaluate_candidate_compliance", evaluator
    )
    monkeypatch.setattr(
        mutation_runner, "_report_execution_binding", unrenderable_binding
    )
    monkeypatch.setattr(
        mutation_runner, "PORTABLE_MUTATION_CASES", (mutant_case,)
    )
    monkeypatch.setattr(mutation_runner, "PORTABLE_SPECIFICITY_CASES", ())

    bundle = run_portable_mutation_evidence(
        run_id="unrenderable-harness-error-68",
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=68,
    )

    assert len(bundle.records) == 1
    record = bundle.records[0]
    assert record.observation.outcome is mutation_matrix.ObservationOutcome.CRASHED
    assert record.observation.decisive_record_digest is None
    error = _blob_payload(bundle, record.error_transcript_digest)
    binding_errors = [item for item in error["errors"] if item["stage"] == "report-binding"]
    assert len(binding_errors) == 1
    assert binding_errors[0]["exception_type"].endswith(
        ".UnrenderableHarnessError"
    )
    assert binding_errors[0]["message"].startswith(
        "unrenderable exception message: "
    )


def test_runner_rejects_seed_that_protocol_or_lineage_would_reject() -> None:
    history, diagnosis, rollout, delta = inputs()
    with pytest.raises(ProtocolViolation, match="unsigned 64-bit"):
        run_portable_mutation_evidence(
            run_id="invalid-seed-u64",
            history=history,
            diagnosis_query=diagnosis,
            rollout_query=rollout,
            delta=delta,
            seed=2**64,
        )

    profiles = tuple(
        case.semantic_probes for case in mutation_runner.PORTABLE_MUTATION_CASES
    ) + tuple(case[3] for case in mutation_runner.PORTABLE_SPECIFICITY_CASES)
    update_index = next(
        index
        for index, probes in enumerate(profiles)
        if "update_consistency" in probes
    )
    execution_seed = (2**64 - 1) ^ compliance.UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
    base_seed = execution_seed - update_index
    with pytest.raises(ProtocolViolation, match="lineage seeds"):
        run_portable_mutation_evidence(
            run_id="invalid-lineage-seed",
            history=history,
            diagnosis_query=diagnosis,
            rollout_query=rollout,
            delta=delta,
            seed=base_seed,
        )
