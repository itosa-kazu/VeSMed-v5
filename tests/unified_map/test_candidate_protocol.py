from __future__ import annotations

import ast
from dataclasses import replace
import json
import inspect
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time

import pytest

import prototype.unified_map.candidate_protocol as candidate_protocol
import prototype.unified_map.compliance as compliance
from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.candidate_protocol import (
    CandidateEntrypoint,
    DiagnoseRequest,
    DiagnoseResponse,
    FreshProcessExecutor,
    InProcessExecutor,
    InitializeRequest,
    MAX_AUDIT_EVENTS,
    MAX_CAPTURED_STREAM_BYTES,
    Operation,
    ResultStatus,
    RolloutRequest,
    RolloutResponse,
    SequentialProcessExecutor,
    StateResponse,
    UpdateRequest,
    WorkerInvocationError,
    assert_shared_state_fanout,
    invoke_diagnose,
    invoke_rollout,
    request_from_wire,
    response_from_wire,
)
from prototype.unified_map.compliance import (
    ComplianceVerdict,
    HonestSeededControl,
    QueryMutatorControl,
    control_entrypoint,
    evaluate_candidate_compliance,
)
from prototype.unified_map.schema import (
    ActionPlan,
    CandidateVisibleEvent,
    DiagnosisQuery,
    EventKind,
    PlanKind,
    RolloutQuery,
    VisibleDelta,
    VisibleHistory,
)
from prototype.unified_map.state import CandidateStateInput, seal_state


CATALOG = "sha256:" + "1" * 64
UTILITY = "sha256:" + "2" * 64
CANDIDATE = "sha256:" + "3" * 64
MODEL = "sha256:" + "4" * 64
SCOPE = "sha256:" + "5" * 64


def test_result_statuses_match_the_frozen_wire_vocabulary() -> None:
    assert {status.value for status in ResultStatus} == {
        "ok",
        "abstain",
        "scope_insufficient",
        "unsupported",
        "invalid_input",
        "numerical_failure",
    }


def history() -> VisibleHistory:
    return VisibleHistory(
        (
            CandidateVisibleEvent(
                EventKind.OBSERVATION_AVAILABLE,
                occurred_at=0,
                available_at=0,
                event_uid="event-0",
                payload={"signal": 0.8},
            ),
        ),
        as_of_available_at=0,
        catalog_digest=CATALOG,
    )


def diagnosis_query() -> DiagnosisQuery:
    return DiagnosisQuery(("class.a", "class.b"))


def rollout_query() -> RolloutQuery:
    return RolloutQuery(
        horizon=2,
        plan=ActionPlan(PlanKind.NO_NEW_ACTION),
        requested_observables=("observable.x",),
        utility_digest=UTILITY,
    )


def test_operation_envelopes_are_exact_and_state_producers_are_task_blind() -> None:
    init = InitializeRequest(history(), 7)
    init_wire = init.to_wire()
    assert set(init_wire) == {"protocol", "operation", "seed", "history"}
    assert "query" not in init_wire and "task" not in init_wire
    assert request_from_wire(init_wire) == init

    state = HonestSeededControl().initialize(history(), inference_seed=7)
    update = UpdateRequest(
        CandidateStateInput(state), VisibleDelta(advance_to=1), seed=8
    )
    update_wire = update.to_wire()
    assert set(update_wire) == {"protocol", "operation", "seed", "state", "delta"}
    assert "history" not in update_wire and "query" not in update_wire
    assert request_from_wire(update_wire) == update

    smuggled = dict(init_wire)
    smuggled["query"] = diagnosis_query().to_wire()
    with pytest.raises(ProtocolViolation, match="extra=.*query"):
        request_from_wire(smuggled)


@pytest.mark.parametrize("seed", [None, True, -1, 2**64])
def test_all_operations_require_an_explicit_uint64_seed(seed: object) -> None:
    with pytest.raises(ProtocolViolation, match="seed"):
        InitializeRequest(history(), seed)  # type: ignore[arg-type]


def test_head_response_schema_cannot_return_new_patient_state() -> None:
    bad = {
        "protocol": "ucm-candidate-response/1",
        "operation": "diagnose",
        "result": {
            "status": "ok",
            "probabilities": {"class.a": 0.5, "class.b": 0.5},
            "metadata": {"state_payload": "second-state"},
        },
    }
    with pytest.raises(ProtocolViolation, match="cannot return patient state"):
        response_from_wire(bad)


def test_inprocess_heads_are_pure_and_record_one_harness_state_hash() -> None:
    payload = HonestSeededControl().initialize(history(), inference_seed=9)
    sealed = seal_state(
        payload,
        candidate_bundle_digest=CANDIDATE,
        model_digest=MODEL,
        scope_digest=SCOPE,
        catalog_digest=CATALOG,
        as_of_available_at=0,
        operation="initialize",
        state_instance_id="protocol-test",
    )
    before = sealed.candidate_input.payload.payload
    executor = InProcessExecutor(HonestSeededControl())
    diagnose = invoke_diagnose(executor, sealed, diagnosis_query(), seed=11)
    rollout = invoke_rollout(executor, sealed, rollout_query(), seed=12)

    assert type(diagnose.outcome.response) is DiagnoseResponse
    assert assert_shared_state_fanout((diagnose, rollout)) == sealed.record.state_hash
    assert diagnose.record.consumed_state_hash == rollout.record.consumed_state_hash
    assert sealed.candidate_input.payload.payload == before


def test_shared_state_fanout_mismatch_is_harness_protocol_violation() -> None:
    payload = HonestSeededControl().initialize(history(), inference_seed=13)
    sealed = seal_state(
        payload,
        candidate_bundle_digest=CANDIDATE,
        model_digest=MODEL,
        scope_digest=SCOPE,
        catalog_digest=CATALOG,
        as_of_available_at=0,
        operation="initialize",
        state_instance_id="fanout-mismatch-test",
    )
    executor = InProcessExecutor(HonestSeededControl())
    diagnose = invoke_diagnose(executor, sealed, diagnosis_query(), seed=14)
    rollout = invoke_rollout(executor, sealed, rollout_query(), seed=15)
    forged_rollout = replace(
        rollout,
        record=replace(
            rollout.record,
            consumed_state_hash="sha256:" + "f" * 64,
        ),
    )

    with pytest.raises(
        ProtocolViolation, match="harness-owned head records consumed different"
    ) as captured:
        assert_shared_state_fanout((diagnose, forged_rollout))

    assert not isinstance(captured.value, candidate_protocol.CandidateCallViolation)


def test_compliance_maps_shared_state_fanout_protocol_violation_to_e003() -> None:
    error = ProtocolViolation(
        "harness-owned head records consumed different sealed states"
    )

    finding = compliance._failure_from_exception(error, "C01/C16-head-purity")

    assert finding.verdict is ComplianceVerdict.INCOMPLETE
    assert finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert finding.evidence == {"exception_type": "ProtocolViolation"}


def test_wrong_top_level_candidate_return_is_typed_f008() -> None:
    class WrongReturnControl(HonestSeededControl):
        def initialize(self, history: VisibleHistory, *, inference_seed: int) -> object:
            del history, inference_seed
            return {"not": "StatePayload"}

    with pytest.raises(candidate_protocol.CandidateCallViolation) as captured:
        InProcessExecutor(WrongReturnControl()).invoke(
            InitializeRequest(history(), seed=2100)
        )

    assert captured.value.failure_code == "UCM-F008-STATE_NOT_CLOSED"
    assert "expected StatePayload" in str(captured.value)


def test_dispatch_detects_candidate_mutation_of_query() -> None:
    state = HonestSeededControl().initialize(history(), inference_seed=3)
    executor = InProcessExecutor(QueryMutatorControl())
    request = RolloutRequest(CandidateStateInput(state), rollout_query(), seed=4)
    with pytest.raises(ProtocolViolation, match="mutated"):
        executor.invoke(request)


def test_fresh_executor_rehydrates_state_without_initializer_process() -> None:
    executor = FreshProcessExecutor(control_entrypoint("HonestSeededControl"))
    initialized = executor.invoke(InitializeRequest(history(), seed=21))
    assert type(initialized.response) is StateResponse
    diagnosed = executor.invoke(
        DiagnoseRequest(
            CandidateStateInput(initialized.response.state),
            diagnosis_query(),
            seed=22,
        )
    )
    rolled = executor.invoke(
        RolloutRequest(
            CandidateStateInput(initialized.response.state),
            rollout_query(),
            seed=23,
        )
    )
    assert type(diagnosed.response) is DiagnoseResponse
    assert diagnosed.worker_pid != rolled.worker_pid
    assert diagnosed.isolation == "fresh-python-process-audit-v2"
    assert diagnosed.audit_events == ()


def test_fresh_executor_rejects_noncanonical_complete_worker_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = StateResponse(
        Operation.INITIALIZE,
        HonestSeededControl().initialize(history(), inference_seed=2101),
    )

    def fake_worker(_command, **kwargs):  # type: ignore[no-untyped-def]
        envelope = {
            "protocol": candidate_protocol.WORKER_PROTOCOL,
            "ok": True,
            "failure_origin": None,
            "response": response.to_wire(),
            "audit_events": [],
            "audit_overflow": False,
            "captured_stdout": "",
            "captured_stderr": "",
            "worker_pid": 12345,
            "worker_cwd_isolated": True,
            **kwargs["binding_fields"],
        }
        return candidate_protocol._BoundedCompletedProcess(
            returncode=0,
            stdout=(json.dumps(envelope, indent=2) + "\n").encode("utf-8"),
            stdout_overflow=False,
            stderr=b"",
            stderr_overflow=False,
            prepared_attested=True,
            request_fully_sent=True,
        )

    monkeypatch.setattr(
        candidate_protocol, "_run_fresh_process_bounded", fake_worker
    )
    with pytest.raises(WorkerInvocationError, match="malformed envelope") as captured:
        FreshProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=20.0
        ).invoke(InitializeRequest(history(), seed=2101))
    assert captured.value.failure_origin == "harness"


def test_fresh_executor_rejects_forged_harness_origin_with_candidate_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_worker(_command, **kwargs):  # type: ignore[no-untyped-def]
        envelope = {
            "protocol": candidate_protocol.WORKER_PROTOCOL,
            "ok": False,
            "failure_origin": "harness",
            "error": {
                "failure_code": "UCM-F008-STATE_NOT_CLOSED",
                "type": "ProtocolViolation",
                "message": "forged pair",
            },
            "audit_events": [],
            "audit_overflow": False,
            "captured_stdout": "",
            "captured_stderr": "",
            "worker_pid": 12346,
            **kwargs["binding_fields"],
        }
        return candidate_protocol._BoundedCompletedProcess(
            returncode=2,
            stdout=candidate_protocol.canonical_json_bytes(envelope),
            stdout_overflow=False,
            stderr=b"",
            stderr_overflow=False,
            prepared_attested=True,
            request_fully_sent=True,
        )

    monkeypatch.setattr(
        candidate_protocol, "_run_fresh_process_bounded", fake_worker
    )
    with pytest.raises(WorkerInvocationError) as captured:
        FreshProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=20.0
        ).invoke(InitializeRequest(history(), seed=2102))
    assert captured.value.failure_origin == "harness"
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"


@pytest.mark.parametrize("worker_pid", [None, True, False, 0, -1, 1.0, "1"])
def test_worker_pid_requires_a_positive_exact_integer(worker_pid: object) -> None:
    with pytest.raises(ProtocolViolation, match="positive exact integer"):
        candidate_protocol._positive_worker_pid(worker_pid, "worker_pid")


def test_fresh_success_rejects_non_exact_worker_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = StateResponse(
        Operation.INITIALIZE,
        HonestSeededControl().initialize(history(), inference_seed=2103),
    )

    def fake_worker(_command, **kwargs):  # type: ignore[no-untyped-def]
        envelope = {
            "protocol": candidate_protocol.WORKER_PROTOCOL,
            "ok": True,
            "failure_origin": None,
            "response": response.to_wire(),
            "audit_events": [],
            "audit_overflow": False,
            "captured_stdout": "",
            "captured_stderr": "",
            "worker_pid": True,
            "worker_cwd_isolated": True,
            **kwargs["binding_fields"],
        }
        return candidate_protocol._BoundedCompletedProcess(
            returncode=0,
            stdout=candidate_protocol.canonical_json_bytes(envelope),
            stdout_overflow=False,
            stderr=b"",
            stderr_overflow=False,
            prepared_attested=True,
            request_fully_sent=True,
        )

    monkeypatch.setattr(
        candidate_protocol, "_run_fresh_process_bounded", fake_worker
    )
    with pytest.raises(WorkerInvocationError, match="malformed worker_pid") as captured:
        FreshProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=20.0
        ).invoke(InitializeRequest(history(), seed=2103))

    assert captured.value.failure_origin == "harness"
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"


def test_fresh_success_cannot_cross_total_deadline_during_response_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = StateResponse(
        Operation.INITIALIZE,
        HonestSeededControl().initialize(history(), inference_seed=2104),
    )

    def fake_worker(_command, **kwargs):  # type: ignore[no-untyped-def]
        envelope = {
            "protocol": candidate_protocol.WORKER_PROTOCOL,
            "ok": True,
            "failure_origin": None,
            "response": response.to_wire(),
            "audit_events": [],
            "audit_overflow": False,
            "captured_stdout": "",
            "captured_stderr": "",
            "worker_pid": 12347,
            "worker_cwd_isolated": True,
            **kwargs["binding_fields"],
        }
        return candidate_protocol._BoundedCompletedProcess(
            returncode=0,
            stdout=candidate_protocol.canonical_json_bytes(envelope),
            stdout_overflow=False,
            stderr=b"",
            stderr_overflow=False,
            prepared_attested=True,
            request_fully_sent=True,
        )

    def expired(_deadline: float) -> None:
        raise candidate_protocol._PreparationTimeout("forced deadline expiry")

    monkeypatch.setattr(
        candidate_protocol, "_run_fresh_process_bounded", fake_worker
    )
    monkeypatch.setattr(
        candidate_protocol, "_check_fresh_completion_deadline", expired
    )
    started = time.monotonic()
    with pytest.raises(WorkerInvocationError, match="overall deadline") as captured:
        FreshProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=20.0
        ).invoke(InitializeRequest(history(), seed=2104))
    elapsed = time.monotonic() - started

    assert captured.value.failure_origin == "harness"
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert elapsed < 20.0


@pytest.mark.parametrize(
    ("stream_name", "prepared_attested", "request_fully_sent"),
    [("stdout", False, False), ("stderr", True, True)],
)
def test_fresh_unknown_external_pipe_overflow_is_harness_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    stream_name: str,
    prepared_attested: bool,
    request_fully_sent: bool,
) -> None:
    def fake_worker(_command, **_kwargs):  # type: ignore[no-untyped-def]
        return candidate_protocol._BoundedCompletedProcess(
            returncode=0,
            stdout=b"unknown-external-output" if stream_name == "stdout" else b"",
            stdout_overflow=stream_name == "stdout",
            stderr=b"unknown-external-output" if stream_name == "stderr" else b"",
            stderr_overflow=stream_name == "stderr",
            prepared_attested=prepared_attested,
            request_fully_sent=request_fully_sent,
        )

    monkeypatch.setattr(
        candidate_protocol, "_run_fresh_process_bounded", fake_worker
    )
    with pytest.raises(WorkerInvocationError, match="oversized") as captured:
        FreshProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=20.0
        ).invoke(InitializeRequest(history(), seed=2105))

    assert captured.value.failure_origin == "harness"
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"


def test_sequential_cleanup_reuses_one_absolute_grace_deadline(
) -> None:
    started = time.monotonic()
    first = candidate_protocol._begin_cleanup_deadline(None)
    time.sleep(0.01)
    reused = candidate_protocol._begin_cleanup_deadline(first)
    elapsed = time.monotonic() - started

    assert reused == first
    assert 0.01 <= elapsed < candidate_protocol.WORKER_CLEANUP_GRACE_SECONDS
    source = inspect.getsource(SequentialProcessExecutor.invoke_sequence)
    assert source.count("cleanup_deadline = begin_cleanup()") == 2


def test_harness_worker_errors_never_use_candidate_failure_codes() -> None:
    with pytest.raises(ProtocolViolation, match="harness failures"):
        WorkerInvocationError(
            "invalid pair",
            failure_code="UCM-F008-STATE_NOT_CLOSED",
            failure_origin="harness",
        )
    tree = ast.parse(
        Path(candidate_protocol.__file__).read_text(encoding="utf-8")
    )
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "WorkerInvocationError"
        ):
            continue
        keywords = {row.arg: row.value for row in node.keywords if row.arg}
        origin = keywords.get("failure_origin")
        code = keywords.get("failure_code")
        if (
            isinstance(origin, ast.Constant)
            and origin.value == "harness"
            and isinstance(code, ast.Constant)
        ):
            assert code.value == "UCM-E003-HARNESS_INCOMPLETE"


def test_sequential_executor_uses_one_bounded_child_for_frozen_requests() -> None:
    payload = HonestSeededControl().initialize(history(), inference_seed=31)
    requests = (
        InitializeRequest(history(), seed=31),
        DiagnoseRequest(
            CandidateStateInput(payload), diagnosis_query(), seed=32
        ),
        RolloutRequest(CandidateStateInput(payload), rollout_query(), seed=33),
    )
    outcomes = SequentialProcessExecutor(
        control_entrypoint("HonestSeededControl"), timeout_seconds=10.0
    ).invoke_sequence(requests)
    assert len(outcomes) == 3
    assert len({outcome.worker_pid for outcome in outcomes}) == 1
    assert all(
        outcome.isolation == "sequential-python-process-audit-v3"
        for outcome in outcomes
    )
    assert [type(outcome.response) for outcome in outcomes] == [
        StateResponse,
        DiagnoseResponse,
        RolloutResponse,
    ]


def test_prepared_marker_is_retired_before_any_candidate_delivery() -> None:
    fresh_source = inspect.getsource(candidate_protocol._run_fresh_process_bounded)
    fresh_unlink = fresh_source.index("prepared_marker_path.unlink()")
    assert fresh_source.rfind("marker_matches()") < fresh_unlink
    assert fresh_unlink < fresh_source.index("def write_request", fresh_unlink)

    sequential_source = inspect.getsource(
        candidate_protocol.SequentialProcessExecutor.invoke_sequence
    )
    sequential_unlink = sequential_source.index("prepared_marker_path.unlink()")
    assert sequential_source.rfind("marker_matches()") < sequential_unlink
    assert sequential_unlink < sequential_source.index(
        "candidate_delivery_active = True", sequential_unlink
    )
    for worker in (
        candidate_protocol._worker_main,
        candidate_protocol._session_worker_main,
    ):
        source = inspect.getsource(worker)
        retired = source.index('sys.argv[9] = "<retired-prepared-marker>"')
        assert retired < source.index("_load_candidate(")
    assert "worker_args =" not in candidate_protocol._UNIFIED_WORKER_BOOTSTRAP


def test_sequential_executor_times_out_infinite_candidate() -> None:
    executor = SequentialProcessExecutor(
        control_entrypoint("InfiniteLoopControl"), timeout_seconds=0.25
    )
    with pytest.raises(WorkerInvocationError, match="timed out") as captured:
        executor.invoke_sequence((InitializeRequest(history(), seed=41),))
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert captured.value.failure_origin == "harness"


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_process_executors_contain_child_exit_as_harness_incomplete(
    executor_kind: str,
) -> None:
    parent_pid = os.getpid()
    entrypoint = control_entrypoint("ExitProcessControl")
    executor = (
        FreshProcessExecutor(entrypoint, timeout_seconds=20.0)
        if executor_kind == "fresh"
        else SequentialProcessExecutor(entrypoint, timeout_seconds=20.0)
    )
    with pytest.raises(WorkerInvocationError, match="malformed envelope") as captured:
        if executor_kind == "fresh":
            executor.invoke(InitializeRequest(history(), seed=42))
        else:
            executor.invoke_sequence((InitializeRequest(history(), seed=42),))
    assert captured.value.failure_origin == "harness"
    assert captured.value.returncode == 91
    assert os.getpid() == parent_pid


def test_sequential_executor_denies_parent_tamper() -> None:
    parent_pid = os.getpid()
    executor = SequentialProcessExecutor(
        control_entrypoint("ParentTamperControl"), timeout_seconds=20.0
    )
    with pytest.raises(WorkerInvocationError) as captured:
        executor.invoke_sequence((InitializeRequest(history(), seed=43),))
    assert os.getpid() == parent_pid
    assert any(
        event.get("event") == "os.kill" for event in captured.value.audit_events
    )


def _write_candidate_module(tmp_path: Path, source: str) -> CandidateEntrypoint:
    module_path = tmp_path / "candidate_fixture.py"
    module_path.write_text(textwrap.dedent(source), encoding="utf-8")
    return CandidateEntrypoint(tmp_path, "candidate_fixture", "Candidate")


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_wrong_top_level_worker_return_is_candidate_f008_and_compliance_fail(
    tmp_path: Path, executor_kind: str
) -> None:
    entrypoint = _write_candidate_module(
        tmp_path,
        """
        class Candidate:
            def initialize(self, history, *, inference_seed):
                del history, inference_seed
                return {"not": "StatePayload"}
        """,
    )
    executor = (
        FreshProcessExecutor(entrypoint, timeout_seconds=20.0)
        if executor_kind == "fresh"
        else SequentialProcessExecutor(entrypoint, timeout_seconds=20.0)
    )

    with pytest.raises(WorkerInvocationError, match="expected StatePayload") as captured:
        if executor_kind == "fresh":
            executor.invoke(InitializeRequest(history(), seed=49))
        else:
            executor.invoke_sequence((InitializeRequest(history(), seed=49),))

    assert captured.value.failure_origin == "candidate"
    assert captured.value.failure_code == "UCM-F008-STATE_NOT_CLOSED"
    finding = compliance._failure_from_worker(
        captured.value, "candidate-output-validation"
    )
    assert finding.verdict is ComplianceVerdict.FAIL
    assert finding.failure_code == "UCM-F008-STATE_NOT_CLOSED"


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_post_import_inventory_helper_fault_is_harness_incomplete(
    monkeypatch: pytest.MonkeyPatch, executor_kind: str
) -> None:
    candidate_protocol._runtime_import_read_allowlist(
        deadline=time.monotonic() + 20.0
    )
    marker = 'if sys.argv[6] == "fresh":'
    injection = """
_ucm_post_import_fault_enabled = False
_ucm_real_runtime_verifier = (
    _ucm_candidate_protocol._verify_worker_runtime_inventory_bytes
)
def _ucm_faulting_runtime_verifier(*args, **kwargs):
    if _ucm_post_import_fault_enabled:
        raise RuntimeError("post-import inventory helper fault")
    return _ucm_real_runtime_verifier(*args, **kwargs)
_ucm_real_load_candidate = _ucm_candidate_protocol._load_candidate
def _ucm_load_candidate_then_fault(*args, **kwargs):
    global _ucm_post_import_fault_enabled
    loaded = _ucm_real_load_candidate(*args, **kwargs)
    _ucm_post_import_fault_enabled = True
    return loaded
_ucm_candidate_protocol._verify_worker_runtime_inventory_bytes = (
    _ucm_faulting_runtime_verifier
)
_ucm_candidate_protocol._load_candidate = _ucm_load_candidate_then_fault
"""
    bootstrap = candidate_protocol._UNIFIED_WORKER_BOOTSTRAP.replace(
        marker, injection + "\n" + marker, 1
    )
    assert bootstrap != candidate_protocol._UNIFIED_WORKER_BOOTSTRAP
    monkeypatch.setattr(candidate_protocol, "_UNIFIED_WORKER_BOOTSTRAP", bootstrap)
    entrypoint = control_entrypoint("HonestSeededControl")
    executor = (
        FreshProcessExecutor(entrypoint, timeout_seconds=20.0)
        if executor_kind == "fresh"
        else SequentialProcessExecutor(entrypoint, timeout_seconds=20.0)
    )

    with pytest.raises(
        WorkerInvocationError, match="post-import inventory helper fault"
    ) as captured:
        if executor_kind == "fresh":
            executor.invoke(InitializeRequest(history(), seed=50))
        else:
            executor.invoke_sequence((InitializeRequest(history(), seed=50),))

    assert captured.value.failure_origin == "harness"
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"


@pytest.mark.parametrize(
    ("source", "event"),
    [
        (
            """
            import os
            import signal
            os.kill(os.getppid(), signal.SIGTERM)
            class Candidate:
                pass
            """,
            "os.kill",
        ),
        (
            """
            import socket
            socket.socket()
            class Candidate:
                pass
            """,
            "socket.__new__",
        ),
    ],
)
def test_candidate_import_runs_inside_audit_boundary(
    tmp_path: Path, source: str, event: str
) -> None:
    parent_pid = os.getpid()
    executor = SequentialProcessExecutor(
        _write_candidate_module(tmp_path, source), timeout_seconds=20.0
    )
    with pytest.raises(WorkerInvocationError) as captured:
        executor.invoke_sequence((InitializeRequest(history(), seed=51),))
    assert os.getpid() == parent_pid
    assert any(row.get("event") == event for row in captured.value.audit_events)


def test_fresh_worker_import_is_also_inside_audit_boundary(
    tmp_path: Path,
) -> None:
    parent_pid = os.getpid()
    entrypoint = _write_candidate_module(
        tmp_path,
        """
        import os
        import signal
        os.kill(os.getppid(), signal.SIGTERM)
        class Candidate:
            pass
        """,
    )
    with pytest.raises(WorkerInvocationError) as captured:
        FreshProcessExecutor(entrypoint, timeout_seconds=20.0).invoke(
            InitializeRequest(history(), seed=511)
        )
    assert os.getpid() == parent_pid
    assert any(
        row.get("event") == "os.kill"
        for row in captured.value.audit_events
    )


def test_candidate_constructor_cannot_read_outside_import_allowlist(
    tmp_path: Path,
) -> None:
    secret = tmp_path.parent / "ucm-constructor-secret.txt"
    secret.write_text("not candidate import data", encoding="utf-8")
    source = f"""
    class Candidate:
        def __init__(self):
            with open({str(secret)!r}, "r", encoding="utf-8") as stream:
                stream.read()
    """
    executor = SequentialProcessExecutor(
        _write_candidate_module(tmp_path, source), timeout_seconds=20.0
    )
    with pytest.raises(WorkerInvocationError) as captured:
        executor.invoke_sequence((InitializeRequest(history(), seed=52),))
    assert any(
        row.get("event") == "open" for row in captured.value.audit_events
    )


def test_candidate_constructor_file_write_side_effect_is_denied(
    tmp_path: Path,
) -> None:
    written = tmp_path.parent / "ucm-constructor-side-effect.txt"
    source = f"""
    class Candidate:
        def __init__(self):
            with open({str(written)!r}, "w", encoding="utf-8") as stream:
                stream.write("escaped")
    """
    executor = SequentialProcessExecutor(
        _write_candidate_module(tmp_path, source), timeout_seconds=20.0
    )
    with pytest.raises(WorkerInvocationError) as captured:
        executor.invoke_sequence((InitializeRequest(history(), seed=521),))
    assert any(
        row.get("event") == "open" for row in captured.value.audit_events
    )
    assert not written.exists()


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
@pytest.mark.parametrize("attempt", ["open", "os_kill"])
def test_catching_denied_audit_exception_cannot_turn_attempt_into_success(
    tmp_path: Path,
    executor_kind: str,
    attempt: str,
) -> None:
    secret = tmp_path.parent / "ucm-caught-audit-secret.txt"
    secret.write_text("denied", encoding="utf-8")
    if attempt == "open":
        attempted_operation = f'open({str(secret)!r}, "r", encoding="utf-8")'
        expected_event = "open"
    else:
        attempted_operation = "os.kill(os.getppid(), signal.SIGTERM)"
        expected_event = "os.kill"
    entrypoint = _write_candidate_module(
        tmp_path,
        f"""
        import os
        import signal
        from prototype.unified_map.state import StateClass, StatePayload

        class Candidate:
            def initialize(self, history, *, inference_seed):
                try:
                    {attempted_operation}
                except PermissionError:
                    pass
                return StatePayload.from_json(
                    {{"returned_after_denial": True}},
                    schema_version="caught-audit/1",
                    state_class=StateClass.COMPRESSED_SHARED,
                )
        """,
    )
    request = InitializeRequest(history(), seed=522)
    with pytest.raises(WorkerInvocationError) as captured:
        if executor_kind == "fresh":
            FreshProcessExecutor(entrypoint, timeout_seconds=20.0).invoke(request)
        else:
            SequentialProcessExecutor(
                entrypoint, timeout_seconds=20.0
            ).invoke_sequence((request,))
    assert any(
        row.get("event") == expected_event
        for row in captured.value.audit_events
    )


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_denied_audit_evidence_is_bounded_and_reports_overflow(
    tmp_path: Path,
    executor_kind: str,
) -> None:
    secret = tmp_path.parent / "ucm-audit-flood-secret.txt"
    secret.write_text("denied", encoding="utf-8")
    entrypoint = _write_candidate_module(
        tmp_path,
        f"""
        from prototype.unified_map.state import StateClass, StatePayload

        class Candidate:
            def initialize(self, history, *, inference_seed):
                for _ in range({MAX_AUDIT_EVENTS + 17}):
                    try:
                        open({str(secret)!r}, "rb")
                    except PermissionError:
                        pass
                return StatePayload.from_json(
                    {{"returned_after_flood": True}},
                    schema_version="audit-flood/1",
                    state_class=StateClass.COMPRESSED_SHARED,
                )
        """,
    )
    request = InitializeRequest(history(), seed=523)
    with pytest.raises(WorkerInvocationError) as captured:
        if executor_kind == "fresh":
            FreshProcessExecutor(entrypoint, timeout_seconds=20.0).invoke(request)
        else:
            SequentialProcessExecutor(
                entrypoint, timeout_seconds=20.0
            ).invoke_sequence((request,))
    assert len(captured.value.audit_events) == MAX_AUDIT_EVENTS
    assert captured.value.audit_overflow is True


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
@pytest.mark.parametrize("stream_name", ["stdout", "stderr"])
def test_candidate_text_capture_is_bounded_and_overflow_fails_closed(
    tmp_path: Path,
    executor_kind: str,
    stream_name: str,
) -> None:
    write_statement = (
        f'print("x" * {MAX_CAPTURED_STREAM_BYTES + 1})'
        if stream_name == "stdout"
        else (
            f'sys.stderr.write("x" * {MAX_CAPTURED_STREAM_BYTES + 1})'
        )
    )
    entrypoint = _write_candidate_module(
        tmp_path,
        f"""
        import sys
        from prototype.unified_map.state import StateClass, StatePayload

        class Candidate:
            def initialize(self, history, *, inference_seed):
                {write_statement}
                return StatePayload.from_json(
                    {{"returned_after_output": True}},
                    schema_version="stream-overflow/1",
                    state_class=StateClass.COMPRESSED_SHARED,
                )
        """,
    )
    request = InitializeRequest(history(), seed=524)
    with pytest.raises(WorkerInvocationError) as captured:
        if executor_kind == "fresh":
            FreshProcessExecutor(entrypoint, timeout_seconds=20.0).invoke(request)
        else:
            SequentialProcessExecutor(
                entrypoint, timeout_seconds=20.0
            ).invoke_sequence((request,))
    assert captured.value.failure_code == "UCM-F008-STATE_NOT_CLOSED"
    assert captured.value.failure_origin == "candidate"
    assert len(captured.value.captured_stdout.encode("utf-8")) <= (
        MAX_CAPTURED_STREAM_BYTES
    )
    assert len(captured.value.captured_stderr.encode("utf-8")) <= (
        MAX_CAPTURED_STREAM_BYTES
    )


def test_transient_python_audit_hook_code_tamper_is_real_incomplete_boundary() -> None:
    entrypoint = control_entrypoint("HarnessTamperControl")
    outcome = FreshProcessExecutor(entrypoint, timeout_seconds=20.0).invoke(
        InitializeRequest(history(), seed=525)
    )
    assert type(outcome.response) is StateResponse
    state = json.loads(outcome.response.state.payload.decode("utf-8"))
    assert state["harness_audit_bypass_observed"] is True
    assert outcome.audit_events == ()

    report = evaluate_candidate_compliance(
        entrypoint,
        history=history(),
        diagnosis_query=diagnosis_query(),
        rollout_query=rollout_query(),
        delta=None,
        seed=526,
    )
    assert report.isolation_completeness is ComplianceVerdict.INCOMPLETE
    boundary = next(
        finding
        for finding in report.findings
        if finding.failure_code == "UCM-E002-ISOLATION_INCOMPLETE"
    )
    assert "not freeze-grade isolation" in boundary.detail


def test_interactive_sequence_hides_future_request_from_candidate_frames(
    tmp_path: Path,
) -> None:
    marker = "UCM-FUTURE-FRAME-MARKER-7F4A"
    entrypoint = _write_candidate_module(
        tmp_path,
        f"""
        import sys
        from prototype.unified_map.candidate_protocol import DiagnosisResult, ResultStatus
        from prototype.unified_map.state import StateClass, StatePayload

        class Candidate:
            def initialize(self, history, *, inference_seed):
                return StatePayload.from_json(
                    {{"ok": True}},
                    schema_version="frame-probe/1",
                    state_class=StateClass.COMPRESSED_SHARED,
                )

            def diagnose(self, state, query, *, query_seed):
                seen = False
                frame = sys._getframe(1)
                while frame is not None:
                    for value in tuple(frame.f_locals.values()):
                        try:
                            if {marker!r} in repr(value):
                                seen = True
                        except Exception:
                            pass
                    frame = frame.f_back
                labels = query.label_catalog
                return DiagnosisResult(
                    ResultStatus.OK,
                    {{labels[0]: 0.9 if seen else 0.5,
                      labels[1]: 0.1 if seen else 0.5}},
                    {{"future_seen_in_frames": seen}},
                )
        """,
    )
    payload = HonestSeededControl().initialize(history(), inference_seed=53)
    future_history = VisibleHistory(
        (
            CandidateVisibleEvent(
                EventKind.OBSERVATION_AVAILABLE,
                occurred_at=0,
                available_at=0,
                event_uid="future-frame-event",
                payload={"marker": marker},
            ),
        ),
        as_of_available_at=0,
        catalog_digest=CATALOG,
    )
    outcomes = SequentialProcessExecutor(
        entrypoint, timeout_seconds=20.0
    ).invoke_sequence(
        (
            DiagnoseRequest(
                CandidateStateInput(payload), diagnosis_query(), seed=53
            ),
            InitializeRequest(future_history, seed=54),
        )
    )
    first = outcomes[0].response
    assert type(first) is DiagnoseResponse
    assert first.result.metadata["future_seen_in_frames"] is False
    assert first.result.probabilities == {"class.a": 0.5, "class.b": 0.5}


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
@pytest.mark.parametrize("fd", [1, 2])
def test_candidate_raw_fd_output_is_isolated_from_protocol_and_captured(
    tmp_path: Path, executor_kind: str, fd: int
) -> None:
    entrypoint = _write_candidate_module(
        tmp_path,
        f"""
        import os
        os.write({fd}, b"import-fd-marker\\n")
        from prototype.unified_map.state import StateClass, StatePayload
        class Candidate:
            def __init__(self):
                os.write({fd}, b"constructor-fd-marker\\n")

            def initialize(self, history, *, inference_seed):
                os.write({fd}, b"call-fd-marker\\n")
                return StatePayload.from_json(
                    {{"ok": True}},
                    schema_version="extra-output/1",
                    state_class=StateClass.COMPRESSED_SHARED,
                )
        """,
    )
    request = InitializeRequest(history(), seed=55)
    if executor_kind == "fresh":
        outcome = FreshProcessExecutor(
            entrypoint, timeout_seconds=20.0
        ).invoke(request)
    else:
        outcome = SequentialProcessExecutor(
            entrypoint, timeout_seconds=20.0
        ).invoke_sequence((request,))[0]
    assert type(outcome.response) is StateResponse
    captured = outcome.captured_stdout if fd == 1 else outcome.captured_stderr
    assert "import-fd-marker" in captured
    assert "constructor-fd-marker" in captured
    assert "call-fd-marker" in captured
    assert (
        outcome.captured_stderr if fd == 1 else outcome.captured_stdout
    ) == ""


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
@pytest.mark.parametrize("stream_fd", [1, 2])
@pytest.mark.parametrize("phase", ["import", "constructor", "call"])
def test_candidate_raw_fd_overflow_fails_closed_with_bounded_parent_evidence(
    tmp_path: Path,
    executor_kind: str,
    stream_fd: int,
    phase: str,
) -> None:
    raw_write = (
        f'os.write({stream_fd}, b"x" * ({MAX_CAPTURED_STREAM_BYTES} + 1))'
    )
    import_write = raw_write if phase == "import" else "pass"
    constructor_write = raw_write if phase == "constructor" else "pass"
    call_write = raw_write if phase == "call" else "pass"
    entrypoint = _write_candidate_module(
        tmp_path,
        f"""
        import os
        {import_write}
        from prototype.unified_map.state import StateClass, StatePayload

        class Candidate:
            def __init__(self):
                {constructor_write}

            def initialize(self, history, *, inference_seed):
                {call_write}
                return StatePayload.from_json(
                    {{"ok": True}},
                    schema_version="raw-fd-overflow/1",
                    state_class=StateClass.COMPRESSED_SHARED,
                )
        """,
    )
    request = InitializeRequest(history(), seed=551)
    with pytest.raises(WorkerInvocationError) as captured:
        if executor_kind == "fresh":
            FreshProcessExecutor(entrypoint, timeout_seconds=20.0).invoke(request)
        else:
            SequentialProcessExecutor(
                entrypoint, timeout_seconds=20.0
            ).invoke_sequence((request,))
    assert captured.value.failure_code == "UCM-F008-STATE_NOT_CLOSED"
    assert captured.value.failure_origin == "candidate"
    assert len(captured.value.captured_stdout.encode("utf-8")) <= (
        MAX_CAPTURED_STREAM_BYTES
    )
    assert len(captured.value.captured_stderr.encode("utf-8")) <= (
        MAX_CAPTURED_STREAM_BYTES
    )


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_python_and_raw_fd_output_share_one_aggregate_stream_budget(
    tmp_path: Path, executor_kind: str
) -> None:
    python_bytes = MAX_CAPTURED_STREAM_BYTES // 2 + 1
    raw_bytes = MAX_CAPTURED_STREAM_BYTES - python_bytes + 1
    entrypoint = _write_candidate_module(
        tmp_path,
        f"""
        import os
        import sys
        from prototype.unified_map.state import StateClass, StatePayload

        class Candidate:
            def initialize(self, history, *, inference_seed):
                sys.stdout.write("p" * {python_bytes})
                os.write(1, b"r" * {raw_bytes})
                return StatePayload.from_json(
                    {{"ok": True}},
                    schema_version="aggregate-output-budget/1",
                    state_class=StateClass.COMPRESSED_SHARED,
                )
        """,
    )
    request = InitializeRequest(history(), seed=552)
    with pytest.raises(WorkerInvocationError) as captured:
        if executor_kind == "fresh":
            FreshProcessExecutor(entrypoint, timeout_seconds=20.0).invoke(request)
        else:
            SequentialProcessExecutor(
                entrypoint, timeout_seconds=20.0
            ).invoke_sequence((request,))
    assert captured.value.failure_code == "UCM-F008-STATE_NOT_CLOSED"
    assert captured.value.failure_origin == "candidate"
    assert len(captured.value.captured_stdout.encode("utf-8")) <= (
        MAX_CAPTURED_STREAM_BYTES
    )


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_parent_rejects_oversized_request_frame_before_spawning(
    monkeypatch: pytest.MonkeyPatch, executor_kind: str
) -> None:
    monkeypatch.setattr(candidate_protocol, "MAX_SESSION_FRAME_BYTES", 32)
    request = InitializeRequest(history(), seed=553)
    executor = (
        FreshProcessExecutor(control_entrypoint("HonestSeededControl"))
        if executor_kind == "fresh"
        else SequentialProcessExecutor(
            control_entrypoint("HonestSeededControl")
        )
    )
    with pytest.raises(ProtocolViolation, match="request frame is too large"):
        if executor_kind == "fresh":
            executor.invoke(request)
        else:
            executor.invoke_sequence((request,))


def test_entrypoint_rejects_non_identifier_target(tmp_path: Path) -> None:
    with pytest.raises(ProtocolViolation, match="dotted identifiers"):
        CandidateEntrypoint(tmp_path, "candidate;import os", "Factory")


@pytest.mark.parametrize(
    "executor_type", [FreshProcessExecutor, SequentialProcessExecutor]
)
@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -float("inf")])
def test_process_executors_reject_nonfinite_timeouts(
    executor_type: type[object], timeout: float
) -> None:
    with pytest.raises(ProtocolViolation, match="finite positive"):
        executor_type(  # type: ignore[call-arg]
            control_entrypoint("HonestSeededControl"), timeout_seconds=timeout
        )


def test_rollout_rejects_unrequested_extra_observable() -> None:
    class ExtraObservableControl(HonestSeededControl):
        def rollout(self, state, query, *, query_seed):  # type: ignore[no-untyped-def]
            result = super().rollout(state, query, query_seed=query_seed)
            result.observable_predictions["observable.unrequested"] = {"mean": 0.0}
            return result

    payload = HonestSeededControl().initialize(history(), inference_seed=61)
    request = RolloutRequest(
        CandidateStateInput(payload), rollout_query(), seed=62
    )
    with pytest.raises(
        ProtocolViolation, match="observable keys do not equal"
    ):
        InProcessExecutor(ExtraObservableControl()).invoke(request)


def test_denied_head_classification_uses_only_file_open_events() -> None:
    payload = HonestSeededControl().initialize(history(), inference_seed=63)
    request = DiagnoseRequest(
        CandidateStateInput(payload), diagnosis_query(), seed=64
    )
    assert candidate_protocol._classify_denied_audit(
        [{"event": "os.kill", "args": ["history future oracle"]}], request
    ) == "UCM-F008-STATE_NOT_CLOSED"
    assert candidate_protocol._classify_denied_audit(
        [{"event": "open", "args": ["'private-history.json'", "'r'"]}],
        request,
    ) == "UCM-F004-HEAD_HISTORY_ACCESS"
    assert candidate_protocol._classify_denied_audit(
        [{"event": "open", "args": ["'actual-future.json'", "'r'"]}],
        request,
    ) == "UCM-F001-FUTURE_LEAK"


@pytest.mark.parametrize(
    ("mode", "flags"),
    [
        ("r+", None),
        ("rb+", None),
        ("w+b", None),
        ("a+b", None),
        ("x+b", None),
        (None, os.O_WRONLY),
        (None, os.O_RDWR),
        (None, os.O_APPEND | os.O_CREAT),
        (None, os.O_TRUNC | os.O_RDWR),
        (None, getattr(os, "O_EXCL", 0) | os.O_WRONLY),
    ],
)
def test_model_open_write_shapes_are_structured_as_mutation(
    tmp_path: Path, mode: str | None, flags: int | None
) -> None:
    boundary = candidate_protocol._CandidateAuditBoundary(frozenset())
    model_path = str(tmp_path / "bound-model.weights")
    with pytest.raises(PermissionError):
        boundary("open", (model_path, mode, flags))
    assert boundary.audit_events[-1]["write_requested"] is True
    assert candidate_protocol._classify_denied_audit(
        boundary.audit_events, None
    ) == "UCM-F009-MODEL_MUTATION"


def test_inprocess_stdout_is_bounded_and_fails_closed() -> None:
    class LoudControl(HonestSeededControl):
        def initialize(self, history, *, inference_seed):  # type: ignore[no-untyped-def]
            print("x" * (MAX_CAPTURED_STREAM_BYTES + 1), end="")
            return super().initialize(history, inference_seed=inference_seed)

    with pytest.raises(candidate_protocol.CandidateCallViolation) as captured:
        InProcessExecutor(LoudControl()).invoke(
            InitializeRequest(history(), seed=65)
        )
    assert captured.value.failure_code == "UCM-F008-STATE_NOT_CLOSED"


def test_candidate_and_explicit_model_byte_digests_are_content_bound(
    tmp_path: Path,
) -> None:
    module = tmp_path / "candidate_fixture.py"
    model = tmp_path / "model.config"
    module.write_text("class Candidate:\n    pass\n", encoding="utf-8")
    model.write_text("version=1\n", encoding="utf-8")

    def prepare() -> candidate_protocol._PreparedImportInventory:
        work = tmp_path.parent / f"work-{time.monotonic_ns()}"
        work.mkdir()
        return candidate_protocol._write_import_allowlist_manifest(
            work,
            CandidateEntrypoint(
                tmp_path,
                "candidate_fixture",
                "Candidate",
                model_relative_paths=("model.config",),
            ),
            deadline=time.monotonic() + 20.0,
        )

    first = prepare()
    assert first.module_origin == "candidate_fixture.py"
    module.write_text("class Candidate:\n    marker = 2\n", encoding="utf-8")
    second = prepare()
    assert second.candidate_bundle_digest != first.candidate_bundle_digest
    assert second.candidate_model_digest == first.candidate_model_digest
    model.write_text("version=2\n", encoding="utf-8")
    third = prepare()
    assert third.candidate_model_digest != second.candidate_model_digest
    assert third.module_origin == first.module_origin


def test_response_preflight_freezes_wire_before_canonical_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = {"metadata": {"value": "small"}}
    canonical = candidate_protocol.canonical_json_bytes

    def racing_canonical(value: object) -> bytes:
        wire["metadata"]["value"] = "z" * 100_000
        return canonical(value)

    monkeypatch.setattr(candidate_protocol, "canonical_json_bytes", racing_canonical)
    encoded = candidate_protocol._canonical_bounded_response_frame(wire)
    assert json.loads(encoded)["metadata"]["value"] == "small"


def test_state_serialization_uses_one_bounded_raw_byte_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = HonestSeededControl().initialize(history(), inference_seed=66)
    original_raw = payload.payload
    encode = candidate_protocol.base64.b64encode

    def racing_encode(raw: bytes) -> bytes:
        object.__setattr__(payload, "payload", b"z" * 10_000)
        return encode(raw)

    monkeypatch.setattr(candidate_protocol.base64, "b64encode", racing_encode)
    wire = candidate_protocol.state_payload_to_wire(payload)
    assert candidate_protocol.base64.b64decode(wire["payload_b64"]) == original_raw


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_external_candidate_can_import_bound_stdlib_module(
    tmp_path: Path, executor_kind: str
) -> None:
    entrypoint = _write_candidate_module(
        tmp_path,
        """
        from fractions import Fraction
        from prototype.unified_map.state import StateClass, StatePayload
        class Candidate:
            def initialize(self, history, *, inference_seed):
                return StatePayload.from_json(
                    {"fraction": str(Fraction(1, 3))},
                    schema_version="stdlib-import/1",
                    state_class=StateClass.COMPRESSED_SHARED,
                )
        """,
    )
    request = InitializeRequest(history(), seed=67)
    if executor_kind == "fresh":
        outcome = FreshProcessExecutor(entrypoint, timeout_seconds=10.0).invoke(request)
    else:
        outcome = SequentialProcessExecutor(
            entrypoint, timeout_seconds=10.0
        ).invoke_sequence((request,))[0]
    assert type(outcome.response) is StateResponse
    assert outcome.module_origin == "candidate_fixture.py"
    assert outcome.import_inventory_digest is not None
    assert outcome.candidate_bundle_digest is not None
    assert outcome.candidate_model_digest is not None


def test_sequential_aggregate_budget_counts_result_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = InitializeRequest(history(), seed=68)
    request_frame = candidate_protocol.canonical_json_bytes(
        {
            "protocol": candidate_protocol.SESSION_REQUEST_PROTOCOL,
            "type": "request",
            "index": 0,
            "request": request.to_wire(),
        }
    )
    parse = candidate_protocol._parse_canonical_session_frame

    def tighten_after_ready(line: bytes) -> dict[str, object]:
        value = parse(line)
        if value.get("type") == "ready":
            monkeypatch.setattr(
                candidate_protocol,
                "MAX_SEQUENTIAL_AGGREGATE_BYTES",
                len(line) + len(request_frame),
            )
        return value

    monkeypatch.setattr(
        candidate_protocol, "_parse_canonical_session_frame", tighten_after_ready
    )
    with pytest.raises(WorkerInvocationError) as captured:
        SequentialProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=10.0
        ).invoke_sequence((request,))
    assert captured.value.failure_origin == "harness"


def test_runtime_allowlist_is_exactly_covered_by_present_or_absent_inventory(
    tmp_path: Path,
) -> None:
    entrypoint = _write_candidate_module(
        tmp_path,
        """
        class Candidate:
            pass
        """,
    )
    work = tmp_path.parent / f"manifest-{time.monotonic_ns()}"
    work.mkdir()
    prepared = candidate_protocol._write_import_allowlist_manifest(
        work, entrypoint, deadline=time.monotonic() + 20.0
    )
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    present = {row["path"] for row in manifest["runtime_entries"]}
    absent = set(manifest["runtime_absent_paths"])
    assert set(manifest["runtime_allowed_files"]) == present | absent
    assert present.isdisjoint(absent)
    assert manifest["runtime_binding_kind"] == (
        "stdlib-exact-source-binary-bytes+isolated-prefix-absent-cache-probes"
    )
    pycache_prefix = (prepared.manifest_path.parent / "pycache-prefix").resolve()
    assert absent
    assert all(path.startswith("__ucm_private_pycache__/") for path in absent)
    assert all(Path(path).suffix.lower() != ".pyc" for path in present)
    expected_absent = {
        candidate_protocol._source_cache_logical_identity(
            Path(row["path"]), "test-runtime"
        )
        for row in manifest["runtime_entries"]
        if Path(row["path"]).suffix.lower() == ".py"
    }
    assert absent == expected_absent
    parsed = candidate_protocol._read_import_allowlist_manifest(
        str(prepared.manifest_path),
        str(prepared.worker_bundle_root),
        str(prepared.worker_harness_root),
    )
    assert parsed.runtime_absent_paths
    assert all(
        Path(path).resolve().is_relative_to(pycache_prefix)
        for path in parsed.runtime_absent_paths
    )
    assert all(
        set(row) == {"path", "size_bytes", "sha256"}
        for row in manifest["runtime_entries"]
    )


def test_worker_cached_module_path_is_inside_private_pycache_prefix(
    tmp_path: Path,
) -> None:
    prefix = (tmp_path / "worker-cache").resolve()
    probe = subprocess.run(
        [
            candidate_protocol._approved_python_executable(None),
            "-I",
            "-S",
            "-B",
            "-X",
            f"pycache_prefix={prefix}",
            "-c",
            (
                "import json,sys;"
                "print(sys.pycache_prefix);"
                "print(json.__cached__)"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20.0,
    )
    reported_prefix, cached_path = probe.stdout.splitlines()
    assert Path(reported_prefix).resolve() == prefix
    assert Path(cached_path).resolve().is_relative_to(prefix)


def test_non_b_parent_cache_writes_cannot_change_worker_runtime_authority(
    tmp_path: Path,
) -> None:
    parent_prefix = (tmp_path / "parent-cache").resolve()
    script = textwrap.dedent(
        f"""
        import json
        import sys
        assert sys.flags.dont_write_bytecode == 0
        sys.pycache_prefix = {str(parent_prefix)!r}
        from prototype.unified_map.candidate_protocol import (
            FreshProcessExecutor, InitializeRequest, StateResponse
        )
        from prototype.unified_map.compliance import control_entrypoint
        from prototype.unified_map.schema import (
            CandidateVisibleEvent, EventKind, VisibleHistory
        )
        visible = VisibleHistory(
            (CandidateVisibleEvent(
                EventKind.OBSERVATION_AVAILABLE,
                occurred_at=0,
                available_at=0,
                event_uid="event-0",
                payload={{"signal": 0.8}},
            ),),
            as_of_available_at=0,
            catalog_digest="sha256:" + "1" * 64,
        )
        outcome = FreshProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=20.0
        ).invoke(InitializeRequest(visible, seed=6801))
        assert type(outcome.response) is StateResponse
        print(json.dumps({{"ok": True}}, sort_keys=True))
        """
    )
    completed = subprocess.run(
        [candidate_protocol._approved_python_executable(None), "-c", script],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == '{"ok": true}'
    assert any(parent_prefix.rglob("*.pyc"))


def test_private_cache_paths_do_not_drift_cross_execution_bindings(
    tmp_path: Path,
) -> None:
    entrypoint = control_entrypoint("HonestSeededControl")
    prepared_rows = []
    for index in range(2):
        work = tmp_path / f"prepared-{index}"
        work.mkdir()
        prepared_rows.append(
            candidate_protocol._write_import_allowlist_manifest(
                work, entrypoint, deadline=time.monotonic() + 20.0
            )
        )
    prepared_bindings = {
        (
            row.import_inventory_digest,
            row.harness_bundle_digest,
            row.candidate_bundle_digest,
            row.candidate_model_digest,
            row.module_origin,
        )
        for row in prepared_rows
    }
    assert len(prepared_bindings) == 1

    outcomes = [
        FreshProcessExecutor(entrypoint, timeout_seconds=20.0).invoke(
            InitializeRequest(history(), seed=6810)
        )
        for _ in range(2)
    ]
    execution_bindings = {
        (
            row.import_inventory_digest,
            row.harness_bundle_digest,
            row.candidate_bundle_digest,
            row.candidate_model_digest,
            row.module_origin,
        )
        for row in outcomes
    }
    assert len(execution_bindings) == 1


def test_manifest_mode_is_bound_into_import_inventory_digest(
    tmp_path: Path,
) -> None:
    entrypoint = _write_candidate_module(tmp_path, "class Candidate:\n    pass\n")
    work = tmp_path.parent / f"mode-{time.monotonic_ns()}"
    work.mkdir()
    prepared = candidate_protocol._write_import_allowlist_manifest(
        work, entrypoint, deadline=time.monotonic() + 20.0
    )
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert manifest["mode"] == "snapshot"
    manifest["mode"] = "live-harness-verified"
    prepared.manifest_path.write_bytes(
        candidate_protocol.canonical_json_bytes(manifest)
    )
    with pytest.raises(ProtocolViolation, match="unknown import inventory mode"):
        candidate_protocol._read_import_allowlist_manifest(
            str(prepared.manifest_path), str(prepared.worker_bundle_root)
        )


def test_candidate_cache_absence_is_bound_and_verified(tmp_path: Path) -> None:
    entrypoint = _write_candidate_module(tmp_path, "class Candidate:\n    pass\n")
    work = tmp_path.parent / f"absence-{time.monotonic_ns()}"
    work.mkdir()
    prepared = candidate_protocol._write_import_allowlist_manifest(
        work, entrypoint, deadline=time.monotonic() + 20.0
    )
    inventory = candidate_protocol._read_import_allowlist_manifest(
        str(prepared.manifest_path), str(prepared.worker_bundle_root)
    )
    assert inventory.candidate_absent_paths
    logical_cache = inventory.candidate_absent_paths[0]
    source_relative = next(
        entry.relative_path
        for entry in inventory.entries
        if entry.relative_path.endswith(".py")
        and candidate_protocol._source_cache_relative_path(
            prepared.worker_bundle_root, entry.relative_path, "candidate"
        )
        == logical_cache
    )
    appeared = candidate_protocol._source_cache_path_under_prefix(
        inventory.pycache_prefix,
        prepared.worker_bundle_root / source_relative,
        "candidate",
    )
    appeared.parent.mkdir(parents=True, exist_ok=True)
    appeared.write_bytes(b"unbound-cache")
    with pytest.raises(ProtocolViolation, match="bound-absent candidate cache"):
        candidate_protocol._verify_worker_inventory_bytes(
            inventory, prepared.worker_bundle_root
        )


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_pre_ready_timeout_is_harness_origin(
    monkeypatch: pytest.MonkeyPatch, executor_kind: str
) -> None:
    candidate_protocol._runtime_import_read_allowlist(
        deadline=time.monotonic() + 20.0
    )
    if executor_kind == "fresh":
        monkeypatch.setattr(
            candidate_protocol,
            "_UNIFIED_WORKER_BOOTSTRAP",
            "import time; time.sleep(30)",
        )
        executor = FreshProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=5.0
        )
        invoke = lambda: executor.invoke(InitializeRequest(history(), seed=69))
    else:
        monkeypatch.setattr(
            candidate_protocol,
            "_UNIFIED_WORKER_BOOTSTRAP",
            "import time; time.sleep(30)",
        )
        executor = SequentialProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=5.0
        )
        invoke = lambda: executor.invoke_sequence(
            (InitializeRequest(history(), seed=69),)
        )
    started = time.monotonic()
    with pytest.raises(WorkerInvocationError, match="timed out") as captured:
        invoke()
    elapsed = time.monotonic() - started
    assert captured.value.failure_origin == "harness"
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert captured.value.import_inventory_digest is not None
    assert elapsed <= (
        5.0 + candidate_protocol.WORKER_CLEANUP_GRACE_SECONDS + 1.5
    )


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_inflight_worker_timeout_is_ambiguous_harness_incomplete(
    executor_kind: str,
) -> None:
    candidate_protocol._runtime_import_read_allowlist(
        deadline=time.monotonic() + 20.0
    )
    if executor_kind == "fresh":
        executor = FreshProcessExecutor(
            control_entrypoint("InfiniteLoopControl"), timeout_seconds=6.0
        )
        invoke = lambda: executor.invoke(InitializeRequest(history(), seed=70))
    else:
        executor = SequentialProcessExecutor(
            control_entrypoint("InfiniteLoopControl"), timeout_seconds=6.0
        )
        invoke = lambda: executor.invoke_sequence(
            (InitializeRequest(history(), seed=70),)
        )
    with pytest.raises(WorkerInvocationError, match="timed out") as captured:
        invoke()
    assert captured.value.failure_origin == "harness"
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert captured.value.import_inventory_digest is not None
    assert captured.value.module_origin == "prototype/unified_map/compliance.py"


@pytest.mark.parametrize("executor_kind", ["fresh", "sequential"])
def test_framework_finalization_timeout_is_harness_incomplete(
    monkeypatch: pytest.MonkeyPatch, executor_kind: str
) -> None:
    candidate_protocol._runtime_import_read_allowlist(
        deadline=time.monotonic() + 20.0
    )
    marker = 'if sys.argv[6] == "fresh":'
    injection = """
import time as _ucm_test_time
_ucm_original_dispatch = _ucm_candidate_protocol._dispatch_candidate
def _ucm_delayed_harness_dispatch(*args, **kwargs):
    result = _ucm_original_dispatch(*args, **kwargs)
    _ucm_test_time.sleep(30)
    return result
_ucm_candidate_protocol._dispatch_candidate = _ucm_delayed_harness_dispatch
"""
    bootstrap = candidate_protocol._UNIFIED_WORKER_BOOTSTRAP.replace(
        marker, injection + "\n" + marker, 1
    )
    assert bootstrap != candidate_protocol._UNIFIED_WORKER_BOOTSTRAP
    monkeypatch.setattr(candidate_protocol, "_UNIFIED_WORKER_BOOTSTRAP", bootstrap)
    entrypoint = control_entrypoint("HonestSeededControl")
    request = InitializeRequest(history(), seed=7010)
    executor = (
        FreshProcessExecutor(entrypoint, timeout_seconds=20.0)
        if executor_kind == "fresh"
        else SequentialProcessExecutor(entrypoint, timeout_seconds=20.0)
    )
    with pytest.raises(WorkerInvocationError, match="unprovable") as captured:
        if executor_kind == "fresh":
            executor.invoke(request)
        else:
            executor.invoke_sequence((request,))
    assert captured.value.failure_origin == "harness"
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"


def test_head_record_propagates_exact_candidate_bindings() -> None:
    payload = HonestSeededControl().initialize(history(), inference_seed=71)
    sealed = seal_state(
        payload,
        candidate_bundle_digest=CANDIDATE,
        model_digest=MODEL,
        scope_digest=SCOPE,
        catalog_digest=CATALOG,
        as_of_available_at=0,
        operation="initialize",
        state_instance_id="binding-propagation",
    )
    result = HonestSeededControl().diagnose(
        sealed.candidate_input, diagnosis_query(), query_seed=72
    )
    outcome = candidate_protocol.InvocationOutcome(
        response=DiagnoseResponse(result),
        request_digest=SCOPE,
        response_digest=CATALOG,
        isolation="test-bound",
        import_inventory_digest=UTILITY,
        harness_bundle_digest=SCOPE,
        candidate_bundle_digest=CANDIDATE,
        candidate_model_digest=MODEL,
        module_origin="candidate/package.py",
    )

    class BoundExecutor:
        def invoke(self, request):  # type: ignore[no-untyped-def]
            return outcome

    execution = invoke_diagnose(
        BoundExecutor(), sealed, diagnosis_query(), seed=72
    )
    wire = execution.record.to_wire()
    assert wire["import_inventory_digest"] == UTILITY
    assert wire["harness_bundle_digest"] == SCOPE
    assert wire["candidate_bundle_digest"] == CANDIDATE
    assert wire["candidate_model_digest"] == MODEL
    assert wire["module_origin"] == "candidate/package.py"


@pytest.mark.parametrize("operation", ["diagnose", "rollout"])
@pytest.mark.parametrize("binding_case", ["mismatch", "partial", "external-null"])
def test_head_readout_closes_candidate_model_binding_to_sealed_state(
    operation: str, binding_case: str
) -> None:
    candidate = HonestSeededControl()
    payload = candidate.initialize(history(), inference_seed=7200)
    sealed = seal_state(
        payload,
        candidate_bundle_digest=CANDIDATE,
        model_digest=MODEL,
        scope_digest=SCOPE,
        catalog_digest=CATALOG,
        as_of_available_at=0,
        operation="initialize",
        state_instance_id="head-binding-negative",
    )
    if operation == "diagnose":
        response = DiagnoseResponse(
            candidate.diagnose(
                sealed.candidate_input, diagnosis_query(), query_seed=7201
            )
        )
    else:
        response = RolloutResponse(
            candidate.rollout(
                sealed.candidate_input, rollout_query(), query_seed=7201
            )
        )
    if binding_case == "mismatch":
        candidate_digest, model_digest = "sha256:" + "6" * 64, MODEL
    elif binding_case == "partial":
        candidate_digest, model_digest = CANDIDATE, None
    else:
        candidate_digest, model_digest = None, None
    outcome = candidate_protocol.InvocationOutcome(
        response=response,
        request_digest=SCOPE,
        response_digest=CATALOG,
        isolation="fresh-python-process-audit-v2",
        import_inventory_digest=UTILITY,
        harness_bundle_digest=SCOPE,
        candidate_bundle_digest=candidate_digest,
        candidate_model_digest=model_digest,
        module_origin="candidate/package.py",
    )

    class BoundExecutor:
        def invoke(self, request):  # type: ignore[no-untyped-def]
            del request
            return outcome

    invoke = invoke_diagnose if operation == "diagnose" else invoke_rollout
    query = diagnosis_query() if operation == "diagnose" else rollout_query()
    with pytest.raises(ProtocolViolation):
        invoke(BoundExecutor(), sealed, query, seed=7201)


def test_post_dispatch_inventory_verifier_rechecks_runtime_bytes_and_absence(
    tmp_path: Path,
) -> None:
    runtime_file = tmp_path / "runtime.py"
    runtime_file.write_bytes(b"before")
    normalized = candidate_protocol._normalized_file_path(runtime_file)
    inventory = candidate_protocol._WorkerImportInventory(
        allowed_files=frozenset({normalized}),
        runtime_entries=(
            (
                normalized,
                len(b"before"),
                candidate_protocol.digest_bytes(b"before"),
            ),
        ),
        runtime_absent_paths=(),
        pycache_prefix=tmp_path,
        harness_root=tmp_path,
        harness_entries=(),
        harness_absent_paths=(),
        bootstrap_kind="unified",
        bootstrap_sha256=UTILITY,
        approved_interpreter=candidate_protocol._approved_interpreter_wire(),
        mode="snapshot",
        entries=(),
        candidate_absent_paths=(),
        model_entries=(),
        import_inventory_digest=UTILITY,
        harness_bundle_digest=SCOPE,
        candidate_bundle_digest=CANDIDATE,
        candidate_model_digest=MODEL,
        module_origin="candidate.py",
    )
    boundary = candidate_protocol._CandidateAuditBoundary(frozenset({normalized}))
    runtime_file.write_bytes(b"after")
    with pytest.raises(ProtocolViolation, match="runtime bytes changed"):
        boundary.verify_inventory_bytes(inventory, tmp_path)

    absent_file = tmp_path / "missing.pyc"
    absent_normalized = candidate_protocol._normalized_file_path(absent_file)
    absent_inventory = candidate_protocol._WorkerImportInventory(
        allowed_files=frozenset({absent_normalized}),
        runtime_entries=(),
        runtime_absent_paths=(absent_normalized,),
        pycache_prefix=tmp_path,
        harness_root=tmp_path,
        harness_entries=(),
        harness_absent_paths=(),
        bootstrap_kind="unified",
        bootstrap_sha256=UTILITY,
        approved_interpreter=candidate_protocol._approved_interpreter_wire(),
        mode="snapshot",
        entries=(),
        candidate_absent_paths=(),
        model_entries=(),
        import_inventory_digest=UTILITY,
        harness_bundle_digest=SCOPE,
        candidate_bundle_digest=CANDIDATE,
        candidate_model_digest=MODEL,
        module_origin="candidate.py",
    )
    absent_file.write_bytes(b"appeared")
    with pytest.raises(ProtocolViolation, match="bound-absent runtime cache"):
        boundary.verify_inventory_bytes(absent_inventory, tmp_path)


def test_sequential_pre_ready_nonzero_exit_is_harness_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_protocol._runtime_import_read_allowlist(
        deadline=time.monotonic() + 20.0
    )
    monkeypatch.setattr(
        candidate_protocol,
        "_UNIFIED_WORKER_BOOTSTRAP",
        "raise SystemExit(7)",
    )
    with pytest.raises(WorkerInvocationError) as captured:
        SequentialProcessExecutor(
            control_entrypoint("HonestSeededControl"), timeout_seconds=5.0
        ).invoke_sequence((InitializeRequest(history(), seed=73),))
    assert captured.value.failure_origin == "harness"
    assert captured.value.returncode == 7
