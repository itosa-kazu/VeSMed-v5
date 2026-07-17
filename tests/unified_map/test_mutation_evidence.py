from __future__ import annotations

import base64
import json
import os
from copy import deepcopy
from functools import lru_cache

import pytest

from prototype.unified_map import compliance, mutation_evidence
from prototype.unified_map.candidate_protocol import (
    DiagnoseRequest,
    FreshProcessExecutor,
    InitializeRequest,
    RolloutRequest,
    StateResponse,
    UpdateRequest,
)
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
from prototype.unified_map.state import CandidateStateInput


TEST_RUNNER_PROTOCOL = "ucm-portable-mutation-runner/unit-test"
TEST_BASE_SEED = 100
RAW_HISTORY_SEED = TEST_BASE_SEED + 2
EXPLICIT_SEED = TEST_BASE_SEED + 17
BEHAVIOR_SEED = TEST_BASE_SEED + 18
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
EMPTY_HEAD_CASES = (
    (
        "FileHandleState",
        "FileHandleStateControl",
        1,
        "C07",
        "UCM-F008-STATE_NOT_CLOSED",
        "initialize",
    ),
    (
        "RawHistoryHead",
        "RawHistoryHeadControl",
        2,
        "C02",
        "UCM-F004-HEAD_HISTORY_ACCESS",
        "diagnose",
    ),
    (
        "TrainerTargetSmuggler",
        "TrainerTargetSmugglerControl",
        3,
        "C08",
        "UCM-F002-ORACLE_TRUE_STATE_ACCESS",
        "initialize",
    ),
    (
        "QueryReencoder",
        "QueryReencoderControl",
        4,
        "C02",
        "UCM-F004-HEAD_HISTORY_ACCESS",
        "diagnose",
    ),
    (
        "MutableCheckpoint",
        "MutableCheckpointControl",
        5,
        "C06",
        "UCM-F009-MODEL_MUTATION",
        "initialize",
    ),
    (
        "TrueStateReader",
        "TrueStateReaderControl",
        6,
        "C08",
        "UCM-F002-ORACLE_TRUE_STATE_ACCESS",
        "diagnose",
    ),
    (
        "FutureReader",
        "FutureReaderControl",
        7,
        "C08",
        "UCM-F001-FUTURE_LEAK",
        "rollout",
    ),
    (
        "CounterfactualMutator",
        "QueryMutatorControl",
        8,
        "C16",
        "UCM-F012-QUERY_MUTATES_FACT",
        "rollout",
    ),
)
_DEFAULT_PASS_DELTA = object()


def _input_preimage(*, delta: dict[str, object] | None = None) -> dict[str, object]:
    catalog_digest = "sha256:" + "a" * 64
    utility_digest = "sha256:" + "b" * 64
    history = {
        "protocol": "ucm-visible-history/1",
        "as_of_available_at": 10,
        "catalog_digest": catalog_digest,
        "events": [
            {
                "kind": "observation_available",
                "occurred_at": 1,
                "collected_at": 1,
                "available_at": 2,
                "event_uid": "event-a",
                "payload": {"value": 0.4},
            }
        ],
    }
    delta_wire = None
    if delta is not None:
        delta_wire = {
            "protocol": "ucm-visible-delta/1",
            "advance_to": 20,
            "events": [
                {
                    "kind": "observation_available",
                    "occurred_at": 11,
                    "collected_at": 11,
                    "available_at": 12,
                    "event_uid": "event-b",
                    "payload": {"value": 0.8},
                }
            ],
        }
    return {
        "history": history,
        "diagnosis_query": {
            "protocol": "ucm-diagnosis-query/1",
            "label_catalog": ["a", "b"],
        },
        "rollout_query": {
            "protocol": "ucm-rollout-query/1",
            "horizon": 2,
            "plan": {
                "kind": "no_new_action",
                "actions": [],
                "policy_digest": None,
            },
            "requested_observables": ["observable-a"],
            "utility_digest": utility_digest,
        },
        "delta": delta_wire,
    }


def _input_digest(*, delta: bool = False, run_id: str = "mutation-unit-run") -> str:
    return digest_json(
        {
            "protocol": mutation_evidence.MUTATION_INPUT_PREIMAGE_PROTOCOL,
            "run_id": run_id,
            "payload": _input_preimage(delta={} if delta else None),
        }
    )


def _state_wire(marker: str) -> dict[str, object]:
    return {
        "codec": "canonical-json-v1",
        "schema_version": "unit-test/1",
        "state_class": "compressed_shared_state",
        "payload_b64": base64.b64encode(
            canonical_json_bytes({"marker": marker})
        ).decode("ascii"),
    }


def _request_record(
    request_wire: dict[str, object],
    response_wire: dict[str, object],
    *,
    execution_mode: str = "fresh",
) -> dict[str, object]:
    return {
        "operation": request_wire["operation"],
        "seed": request_wire["seed"],
        "execution_mode": execution_mode,
        "executor_protocol": (
            compliance._UNVERIFIED_EXECUTOR_RECEIPT_PROTOCOL
        ),
        "parent_pid": os.getpid(),
        "worker_pid": None,
        "isolation": None,
        "import_inventory_digest": None,
        "harness_bundle_digest": None,
        "candidate_bundle_digest": None,
        "candidate_model_digest": None,
        "module_origin": None,
        "invocation_nonce": "0" * 32,
        "executor_receipt": "sha256:" + "0" * 64,
        "status": "success",
        "request_wire": request_wire,
        "request_digest": digest_json(request_wire),
        "request_fully_sent": True,
        "received_request_digest": digest_json(request_wire),
        "response_wire": response_wire,
        "response_digest": digest_json(response_wire),
        "failure_origin": None,
        "failure_code": None,
}


def _refresh_executor_receipt(record: dict[str, object]) -> None:
    record["executor_receipt"] = compliance._executor_receipt_digest(
        executor_protocol=record["executor_protocol"],
        execution_mode=record["execution_mode"],
        parent_pid=record["parent_pid"],
        worker_pid=record["worker_pid"],
        isolation=record["isolation"],
        import_inventory_digest=record["import_inventory_digest"],
        harness_bundle_digest=record["harness_bundle_digest"],
        candidate_bundle_digest=record["candidate_bundle_digest"],
        candidate_model_digest=record["candidate_model_digest"],
        module_origin=record["module_origin"],
        invocation_nonce=record["invocation_nonce"],
        request_digest=record["request_digest"],
        request_fully_sent=record["request_fully_sent"],
        received_request_digest=record["received_request_digest"],
        response_digest=record["response_digest"],
        status=record["status"],
        failure_origin=record["failure_origin"],
        failure_code=record["failure_code"],
    )


def _refresh_request_record(record: dict[str, object]) -> None:
    record["request_digest"] = digest_json(record["request_wire"])
    if record["request_fully_sent"] is True:
        record["received_request_digest"] = record["request_digest"]
    response_wire = record["response_wire"]
    record["response_digest"] = (
        None if response_wire is None else digest_json(response_wire)
    )
    _refresh_executor_receipt(record)


def _request_transcript(
    *,
    execution_seed: int,
    include_delta: bool,
    full: bool,
    semantic_probes: tuple[str, ...] = (),
    include_passed_suffix: bool = False,
    killed_failure_code: str | None = None,
    control_class_name: str = "",
) -> list[dict[str, object]]:
    empty_head_terminal_operation = {
        "FileHandleStateControl": "initialize",
        "RawHistoryHeadControl": "diagnose",
        "TrainerTargetSmugglerControl": "initialize",
        "QueryReencoderControl": "diagnose",
        "MutableCheckpointControl": "initialize",
        "TrueStateReaderControl": "diagnose",
        "FutureReaderControl": "rollout",
        "QueryMutatorControl": "rollout",
    }.get(control_class_name)

    def finalize_unverified_fixture_records(
        records: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Mark static schema fixtures honestly as non-runtime evidence."""

        for index, record in enumerate(records):
            nonce_preimage = {
                "protocol": "ucm-unit-test-unverified-invocation/1",
                "control": control_class_name,
                "execution_seed": execution_seed,
                "index": index,
            }
            record["invocation_nonce"] = digest_json(nonce_preimage)[7:39]
            _refresh_executor_receipt(record)
        return records

    def candidate_worker_error(
        successful_record: dict[str, object], failure_code: str
    ) -> dict[str, object]:
        record = deepcopy(successful_record)
        record.update(
            {
                "status": "worker_error",
                "response_wire": None,
                "response_digest": None,
                "failure_origin": "candidate",
                "failure_code": failure_code,
            }
        )
        return record

    inputs = _input_preimage(delta={} if include_delta else None)
    state = _state_wire("main")
    next_state = _state_wire("updated")
    init_request = {
        "protocol": "ucm-candidate-request/1",
        "operation": "initialize",
        "seed": execution_seed,
        "history": deepcopy(inputs["history"]),
    }
    init_response = {
        "protocol": "ucm-candidate-response/1",
        "operation": "initialize",
        "state": state,
    }
    rows = [_request_record(init_request, init_response)]
    if (
        not full
        and empty_head_terminal_operation == "initialize"
        and killed_failure_code is not None
    ):
        return finalize_unverified_fixture_records(
            [candidate_worker_error(rows[0], killed_failure_code)]
        )
    if not full and empty_head_terminal_operation is None:
        return finalize_unverified_fixture_records(rows)
    rows.append(_request_record(deepcopy(init_request), deepcopy(init_response)))
    diagnosis_request = {
        "protocol": "ucm-candidate-request/1",
        "operation": "diagnose",
        "seed": execution_seed + 1,
        "state": state,
        "query": deepcopy(inputs["diagnosis_query"]),
    }
    diagnosis_response = {
        "protocol": "ucm-candidate-response/1",
        "operation": "diagnose",
        "result": {
            "status": "ok",
            "probabilities": {"a": 0.5, "b": 0.5},
            "metadata": {},
        },
    }

    def drifted_diagnosis_response() -> dict[str, object]:
        response = deepcopy(diagnosis_response)
        response["result"]["probabilities"] = {"a": 0.75, "b": 0.25}
        return response

    if (
        not full
        and empty_head_terminal_operation == "diagnose"
        and killed_failure_code is not None
    ):
        rows.append(
            candidate_worker_error(
                _request_record(diagnosis_request, diagnosis_response),
                killed_failure_code,
            )
        )
        return finalize_unverified_fixture_records(rows)
    rows.extend(
        [
            _request_record(diagnosis_request, diagnosis_response),
            _request_record(
                deepcopy(diagnosis_request),
                (
                    drifted_diagnosis_response()
                    if killed_failure_code == "UCM-F020-NONREPRODUCIBLE"
                    else deepcopy(diagnosis_response)
                ),
            ),
        ]
    )
    rollout_request = {
        "protocol": "ucm-candidate-request/1",
        "operation": "rollout",
        "seed": execution_seed + 2,
        "state": state,
        "query": deepcopy(inputs["rollout_query"]),
    }
    rollout_response = {
        "protocol": "ucm-candidate-response/1",
        "operation": "rollout",
        "result": {
            "status": "ok",
            "observable_predictions": {"observable-a": {"mean": 0.5}},
            "utility_prediction": {},
            "metadata": {},
        },
    }
    if (
        not full
        and empty_head_terminal_operation == "rollout"
        and killed_failure_code is not None
    ):
        rows.append(
            candidate_worker_error(
                _request_record(rollout_request, rollout_response),
                killed_failure_code,
            )
        )
        return finalize_unverified_fixture_records(rows)
    rows.extend(
        [
            _request_record(rollout_request, rollout_response),
            _request_record(deepcopy(rollout_request), deepcopy(rollout_response)),
        ]
    )
    if include_delta:
        update_request = {
            "protocol": "ucm-candidate-request/1",
            "operation": "update",
            "seed": execution_seed + 3,
            "state": state,
            "delta": deepcopy(inputs["delta"]),
        }
        update_response = {
            "protocol": "ucm-candidate-response/1",
            "operation": "update",
            "state": next_state,
        }
        rows.extend(
            [
                _request_record(update_request, update_response),
                _request_record(deepcopy(update_request), deepcopy(update_response)),
            ]
        )
    emit_update_consistency = (
        "update_consistency" in semantic_probes
        and (
            include_passed_suffix
            or killed_failure_code == "UCM-F019-UPDATE_INCONSISTENT"
        )
    )
    emit_warm_future = (
        "warm_future_old_cut" in semantic_probes
        and (
            include_passed_suffix
            or killed_failure_code == "UCM-F001-FUTURE_LEAK"
        )
    )
    emit_warm_cold = include_passed_suffix or killed_failure_code in {
        "UCM-F006-HIDDEN_PATIENT_CACHE",
        "UCM-F001-FUTURE_LEAK",
        "UCM-F019-UPDATE_INCONSISTENT",
    }
    if not (emit_update_consistency or emit_warm_future or emit_warm_cold):
        return finalize_unverified_fixture_records(rows)

    merged_history = None
    if include_delta:
        merged_history = deepcopy(inputs["history"])
        merged_history["as_of_available_at"] = inputs["delta"]["advance_to"]
        merged_history["events"] = [
            *deepcopy(inputs["history"]["events"]),
            *deepcopy(inputs["delta"]["events"]),
        ]

    def state_response(operation: str, state_wire: dict[str, object]) -> dict[str, object]:
        return {
            "protocol": "ucm-candidate-response/1",
            "operation": operation,
            "state": state_wire,
        }

    def initialize(
        history_wire: dict[str, object],
        seed: int,
        marker: str,
        *,
        mode: str,
        produced: dict[str, object] | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        produced = _state_wire(marker) if produced is None else deepcopy(produced)
        return (
            _request_record(
                {
                    "protocol": "ucm-candidate-request/1",
                    "operation": "initialize",
                    "seed": seed,
                    "history": deepcopy(history_wire),
                },
                state_response("initialize", produced),
                execution_mode=mode,
            ),
            produced,
        )

    def update(
        consumed: dict[str, object],
        seed: int,
        marker: str,
        *,
        mode: str,
        produced: dict[str, object] | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        produced = _state_wire(marker) if produced is None else deepcopy(produced)
        return (
            _request_record(
                {
                    "protocol": "ucm-candidate-request/1",
                    "operation": "update",
                    "seed": seed,
                    "state": consumed,
                    "delta": deepcopy(inputs["delta"]),
                },
                state_response("update", produced),
                execution_mode=mode,
            ),
            produced,
        )

    def heads(
        consumed: dict[str, object],
        seed: int,
        *,
        mode: str,
        diagnosis_wire: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        diagnosis_request = {
            "protocol": "ucm-candidate-request/1",
            "operation": "diagnose",
            "seed": seed + 1,
            "state": consumed,
            "query": deepcopy(inputs["diagnosis_query"]),
        }
        rollout_request = {
            "protocol": "ucm-candidate-request/1",
            "operation": "rollout",
            "seed": seed + 2,
            "state": consumed,
            "query": deepcopy(inputs["rollout_query"]),
        }
        return [
            _request_record(
                diagnosis_request,
                deepcopy(
                    diagnosis_response
                    if diagnosis_wire is None
                    else diagnosis_wire
                ),
                execution_mode=mode,
            ),
            _request_record(
                rollout_request,
                deepcopy(rollout_response),
                execution_mode=mode,
            ),
        ]

    if emit_update_consistency and merged_history is not None:
        lineage_seed = (
            execution_seed ^ mutation_evidence.UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
        )
        lineage_init, lineage_state = initialize(
            inputs["history"], lineage_seed, "lineage-initial", mode="fresh"
        )
        incremental, incremental_state = update(
            lineage_state, lineage_seed, "lineage-incremental", mode="fresh"
        )
        replay, replay_state = initialize(
            merged_history, lineage_seed, "lineage-replay", mode="fresh"
        )
        duplicate, duplicate_state = update(
            incremental_state, lineage_seed, "lineage-duplicate", mode="fresh"
        )
        replay_diagnosis = None
        duplicate_diagnosis = None
        if killed_failure_code == "UCM-F019-UPDATE_INCONSISTENT":
            if control_class_name == "DoubleCountEventControl":
                duplicate_diagnosis = drifted_diagnosis_response()
            else:
                replay_diagnosis = drifted_diagnosis_response()
        rows.extend(
            [
                lineage_init,
                incremental,
                replay,
                duplicate,
                *heads(incremental_state, lineage_seed, mode="fresh"),
                *heads(
                    replay_state,
                    lineage_seed,
                    mode="fresh",
                    diagnosis_wire=replay_diagnosis,
                ),
                *heads(
                    duplicate_state,
                    lineage_seed,
                    mode="fresh",
                    diagnosis_wire=duplicate_diagnosis,
                ),
            ]
        )
    if emit_warm_future and merged_history is not None:
        warm_later, _ = initialize(
            merged_history, execution_seed, "warm-later", mode="sequential"
        )
        warm_input, _ = initialize(
            inputs["history"],
            execution_seed,
            "warm-input",
            mode="sequential",
            produced=state,
        )
        warm_update, _ = update(
            state,
            execution_seed + 3,
            "warm-update",
            mode="sequential",
            produced=next_state,
        )
        rows.extend(
            [
                warm_later,
                *heads(
                    state,
                    execution_seed,
                    mode="sequential",
                    diagnosis_wire=(
                        drifted_diagnosis_response()
                        if killed_failure_code == "UCM-F001-FUTURE_LEAK"
                        else None
                    ),
                ),
                warm_input,
                warm_update,
                *heads(state, execution_seed, mode="sequential"),
            ]
        )
    if emit_warm_cold:
        warm_init, _ = initialize(
            inputs["history"],
            execution_seed,
            "warm-cold",
            mode="sequential",
            produced=(
                _state_wire("global-second")
                if killed_failure_code == "UCM-F006-HIDDEN_PATIENT_CACHE"
                else state
            ),
        )
        rows.extend(
            [warm_init, *heads(state, execution_seed, mode="sequential")]
        )
    return finalize_unverified_fixture_records(rows)


def _scored_projection(response_wire: dict[str, object]) -> dict[str, object]:
    operation = response_wire["operation"]
    result = response_wire["result"]
    assert type(result) is dict
    if operation == "diagnose":
        return {
            "operation": "diagnose",
            "status": result["status"],
            "probabilities": deepcopy(result["probabilities"]),
        }
    assert operation == "rollout"
    return {
        "operation": "rollout",
        "status": result["status"],
        "observable_predictions": deepcopy(result["observable_predictions"]),
        "utility_prediction": deepcopy(result["utility_prediction"]),
    }


def _head_behavior_from_records(
    records: list[dict[str, object]], diagnosis_index: int, rollout_index: int
) -> dict[str, object]:
    diagnosis = records[diagnosis_index]["response_wire"]
    rollout = records[rollout_index]["response_wire"]
    assert type(diagnosis) is dict and type(rollout) is dict
    return {
        "diagnosis": _scored_projection(diagnosis),
        "rollout": _scored_projection(rollout),
    }


def _actual_probe_finding_evidence(
    records: list[dict[str, object]],
    *,
    include_delta: bool,
    failure_code: str,
) -> dict[str, object]:
    main_length = 8 if include_delta else 6
    if failure_code == "UCM-F019-UPDATE_INCONSISTENT":
        incremental = _head_behavior_from_records(
            records, main_length + 4, main_length + 5
        )
        replay = _head_behavior_from_records(
            records, main_length + 6, main_length + 7
        )
        duplicate = _head_behavior_from_records(
            records, main_length + 8, main_length + 9
        )
        return {
            "incremental_behavior_digest": digest_json(incremental),
            "replay_behavior_digest": digest_json(replay),
            "duplicate_behavior_digest": digest_json(duplicate),
            "incremental_equals_replay": incremental == replay,
            "duplicate_event_is_idempotent": incremental == duplicate,
        }
    if failure_code == "UCM-F001-FUTURE_LEAK":
        before = _head_behavior_from_records(records, 2, 4)
        before_raw = {
            "diagnosis": records[2]["response_wire"],
            "rollout": records[4]["response_wire"],
        }
        after_initialize = _head_behavior_from_records(
            records, main_length + 1, main_length + 2
        )
        after_initialize_raw = {
            "diagnosis": records[main_length + 1]["response_wire"],
            "rollout": records[main_length + 2]["response_wire"],
        }
        after_update = _head_behavior_from_records(
            records, main_length + 5, main_length + 6
        )
        after_update_raw = {
            "diagnosis": records[main_length + 5]["response_wire"],
            "rollout": records[main_length + 6]["response_wire"],
        }
        return {
            "before_behavior_digest": digest_json(before),
            "before_raw_wire_digest": digest_json(before_raw),
            "after_initialize_later_digest": digest_json(after_initialize),
            "after_initialize_later_raw_wire_digest": digest_json(
                after_initialize_raw
            ),
            "after_update_old_delta_digest": digest_json(after_update),
            "after_update_old_delta_raw_wire_digest": digest_json(
                after_update_raw
            ),
            "initialize_later_stable": before == after_initialize,
            "update_old_delta_stable": before == after_update,
            "initialize_later_raw_exact": before_raw == after_initialize_raw,
            "update_old_delta_raw_exact": before_raw == after_update_raw,
        }
    return {}


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
        "protocol": "ucm-portable-semantic-probes/5",
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
    input_preimage: dict[str, object] | None = None,
) -> MutationEvidenceBuilder:
    return MutationEvidenceBuilder(
        run_id="mutation-unit-run",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=(
            _input_preimage(delta=delta)
            if input_preimage is None
            else input_preimage
        ),
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
        "protocol": "ucm-portable-control-source-binding/18",
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
        "semantic_probe_contract": "ucm-portable-semantic-probes/5",
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
    include_delta: bool = False,
    input_preimage_digest: str | None = None,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    effective_include_delta = include_delta or (
        outcome == "passed"
        and bool(
            {"update_consistency", "warm_future_old_cut"}.intersection(
                semantic_probes
            )
        )
    )
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
    bound_input_digest = (
        _input_digest(delta=effective_include_delta)
        if input_preimage_digest is None
        else input_preimage_digest
    )
    request_records = _request_transcript(
        execution_seed=execution_seed,
        include_delta=effective_include_delta,
        full=control_class_name in REPLAY_HEAD_CONTROLS,
        semantic_probes=semantic_probes,
        include_passed_suffix=outcome == "passed",
        killed_failure_code=(
            expected_failure_code if outcome == "killed" else None
        ),
        control_class_name=control_class_name,
    )
    if (
        outcome == "killed"
        and effective_include_delta
        and expected_failure_code
        in {
            "UCM-F019-UPDATE_INCONSISTENT",
            "UCM-F001-FUTURE_LEAK",
        }
    ):
        actual_evidence = _actual_probe_finding_evidence(
            request_records,
            include_delta=effective_include_delta,
            failure_code=expected_failure_code,
        )
        for finding in report_findings:
            if finding.get("failure_code") == expected_failure_code:
                existing_evidence = finding.get("evidence")
                finding["evidence"] = {
                    **(
                        existing_evidence
                        if type(existing_evidence) is dict
                        else {}
                    ),
                    **actual_evidence,
                }
    invocation_transcript_digest = digest_json(request_records)
    head_request_records = [
        row
        for row in request_records
        if row["operation"] in {"diagnose", "rollout"}
        and row["execution_mode"] == "fresh"
        and row["seed"] in {execution_seed + 1, execution_seed + 2}
    ]
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
                "operation": row["operation"],
                "request_digest": row["request_digest"],
                "response_digest": row["response_digest"],
                "seed": row["seed"],
            }
            for row in head_request_records
        ],
        "paired_semantic_equivalence": paired_semantic_equivalence,
        "input_preimage_digest": bound_input_digest,
        "invocation_transcript_digest": invocation_transcript_digest,
        "request_records": request_records,
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
        "input_preimage_digest": bound_input_digest,
        "invocation_transcript_digest": invocation_transcript_digest,
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
        "input_preimage_digest": bound_input_digest,
        "invocation_transcript_digest": invocation_transcript_digest,
    }
    if outcome == "killed":
        decisive["finding"] = report_findings[0]
    else:
        decisive["classification"] = classification
    return pre, post, source, report, decision, decisive


def _bundle() -> MutationEvidenceBundle:
    builder = _builder(delta={})
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
        include_delta=True,
        input_preimage_digest=builder.input_preimage_digest,
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
        include_delta=True,
        input_preimage_digest=builder.input_preimage_digest,
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
            "input_preimage_digest": builder.input_preimage_digest,
            "invocation_transcript_digest": digest_json([]),
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


def test_crashed_record_can_retain_a_strict_partial_request_transcript() -> None:
    builder = _builder(delta={})
    pre, post, source, report, decision, _ = _decisive_raw(
        binding_digit="4",
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
    report["request_records"] = report["request_records"][:1]
    report["head_records"] = []
    report["invocation_transcript_digest"] = digest_json(report["request_records"])
    decision.update(
        {
            "derived_outcome": "crashed",
            "probe_incomplete": True,
            "report_processing_complete": False,
            "invocation_transcript_digest": report["invocation_transcript_digest"],
        }
    )
    builder.add_record(
        subject_id="ExplicitSeedStochasticState",
        subject_kind=SubjectKind.SPECIFICITY_CONTROL,
        execution_seed=EXPLICIT_SEED,
        outcome=ObservationOutcome.CRASHED,
        actual_gate=None,
        actual_failure_code=None,
        classification="ordinary_candidate",
        pre_source_witness=pre,
        post_source_witness=post,
        source_record=source,
        report_transcript=report,
        error_transcript=_error_transcript(
            [
                {
                    "stage": "candidate-execution",
                    "exception_type": "builtins.RuntimeError",
                    "message": "partial execution retained",
                }
            ]
        ),
        decision_record=decision,
        decisive_record=None,
    )
    bundle = builder.finalize()
    assert bundle.observations[0].outcome is ObservationOutcome.CRASHED


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
    delta: dict[str, object] | None = None,
    semantic_probes: tuple[str, ...] = (),
    input_preimage: dict[str, object] | None = None,
) -> MutationEvidenceBuilder:
    builder = _builder(
        delta=delta,
        execution_context=execution_context,
        input_preimage=input_preimage,
    )
    base_pre, base_post, _, base_report, base_decision, _ = _decisive_raw(
        binding_digit="3",
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": f"{actual_gate}-unit-test",
                "verdict": "fail",
                "failure_code": actual_failure_code,
                "detail": "unit-test decisive failure",
                "evidence": {"probe": "unit-test"},
            }
        ],
        failure_codes=[actual_failure_code],
        decision_kind="mutant_kill",
        expected_gate=actual_gate,
        expected_failure_code=actual_failure_code,
        include_delta=delta is not None,
        input_preimage_digest=builder.input_preimage_digest,
        semantic_probes=semantic_probes,
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
        "input_preimage_digest": (
            report_payload.get("input_preimage_digest")
            if type(report_payload) is dict
            else None
        ),
        "invocation_transcript_digest": (
            report_payload.get("invocation_transcript_digest")
            if type(report_payload) is dict
            else None
        ),
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
    delta: dict[str, object] | None | object = _DEFAULT_PASS_DELTA,
    execution_context: dict[str, object] | None = None,
    input_preimage: dict[str, object] | None = None,
) -> MutationEvidenceBuilder:
    effective_delta = {} if delta is _DEFAULT_PASS_DELTA else delta
    assert effective_delta is None or type(effective_delta) is dict
    builder = _builder(
        delta=effective_delta,
        execution_context=execution_context,
        input_preimage=input_preimage,
    )
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
        include_delta=effective_delta is not None,
        input_preimage_digest=builder.input_preimage_digest,
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
    request_records = _request_transcript(
        execution_seed=execution_seed,
        include_delta=False,
        full=False,
        killed_failure_code="UCM-F004-HEAD_HISTORY_ACCESS",
        control_class_name="RawHistoryHeadControl",
    )
    invocation_transcript_digest = digest_json(request_records)
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
        "input_preimage_digest": builder.input_preimage_digest,
        "invocation_transcript_digest": invocation_transcript_digest,
        "request_records": request_records,
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
        "input_preimage_digest": builder.input_preimage_digest,
        "invocation_transcript_digest": invocation_transcript_digest,
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
        "input_preimage_digest": builder.input_preimage_digest,
        "invocation_transcript_digest": invocation_transcript_digest,
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
        "NonIdPointEstimate": "replay_ddrr",
        "DangerousMeanCompressor": "replay_ddrr",
        "UnsafeClosedWorld": "replay_ddrr",
    }
    assert [row["head_record_shape"] for row in contract["specificity_cases"]] == [
        "replay_ddrr",
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


@lru_cache(maxsize=None)
def _cached_live_evaluator_transcript(
    control_name: str,
    probe: str,
    seed: int,
) -> tuple[bytes, str | None, str]:
    """Capture real process receipts once for each evaluator test case."""

    wire = _input_preimage(delta={})
    history = mutation_evidence._history_from_wire(wire["history"])
    diagnosis = mutation_evidence._diagnosis_query_from_wire(
        wire["diagnosis_query"]
    )
    rollout = mutation_evidence._rollout_query_from_wire(wire["rollout_query"])
    delta = mutation_evidence._delta_from_wire(wire["delta"])
    entrypoint = compliance.control_entrypoint(control_name)
    collector = compliance._ExecutionBindingCollector()
    fresh = compliance._BindingObservedExecutor(
        FreshProcessExecutor(entrypoint), collector
    )
    first = fresh.invoke(InitializeRequest(history, seed))
    second = fresh.invoke(InitializeRequest(history, seed))
    assert type(first.response) is StateResponse
    assert type(second.response) is StateResponse
    state = CandidateStateInput(first.response.state)
    fresh.invoke(DiagnoseRequest(state, diagnosis, seed + 1))
    fresh.invoke(DiagnoseRequest(state, diagnosis, seed + 1))
    fresh.invoke(RolloutRequest(state, rollout, seed + 2))
    fresh.invoke(RolloutRequest(state, rollout, seed + 2))
    fresh.invoke(UpdateRequest(state, delta, seed + 3))
    fresh.invoke(UpdateRequest(state, delta, seed + 3))
    finding = compliance._execute_evaluator_probe(
        probe=probe,
        entrypoint=entrypoint,
        fresh=fresh,
        bindings=collector,
        seed=seed,
    )
    compliance._invoke_observed_sequence(
        entrypoint,
        (
            InitializeRequest(history, seed),
            DiagnoseRequest(state, diagnosis, seed + 1),
            RolloutRequest(state, rollout, seed + 2),
        ),
        collector,
        timeout_seconds=compliance.PORTABLE_COMPLIANCE_PROBE_TIMEOUT_SECONDS,
    )
    encoded = canonical_json_bytes({"request_records": collector.request_records})
    return encoded, finding.failure_code, finding.verdict.value


def _actual_evaluator_request_transcript(
    control_name: str,
    probe: str,
    seed: int,
) -> tuple[list[dict[str, object]], object, object, object, object, str | None, str]:
    encoded, failure_code, verdict = _cached_live_evaluator_transcript(
        control_name, probe, seed
    )
    records = json.loads(encoded.decode("utf-8"))["request_records"]
    wire = _input_preimage(delta={})
    return (
        records,
        mutation_evidence._history_from_wire(wire["history"]),
        mutation_evidence._diagnosis_query_from_wire(wire["diagnosis_query"]),
        mutation_evidence._rollout_query_from_wire(wire["rollout_query"]),
        mutation_evidence._delta_from_wire(wire["delta"]),
        failure_code,
        verdict,
    )


def test_evaluator_request_suffix_rebuilds_actual_c19_and_rejects_resigned_response() -> None:
    records, history, diagnosis, rollout, delta, failure_code, verdict = (
        _actual_evaluator_request_transcript(
            "NonIdPointEstimateControl", "nonidentified_set", 191
        )
    )
    assert failure_code == "UCM-F015-CONDITIONING_AS_INTERVENTION"
    assert verdict == "fail"
    _, _, evidence = mutation_evidence._validate_request_records(
        records,
        input_preimage_digest=digest_json({"input": "m1-c19"}),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        execution_seed=191,
        expected_subject_id="NonIdPointEstimate",
        expected_failure_code="UCM-F015-CONDITIONING_AS_INTERVENTION",
        expected_semantic_probes=("nonidentified_set",),
        expected_head_record_shape="replay_ddrr",
        observation_outcome=ObservationOutcome.KILLED,
        head_records=[],
    )
    assert evidence["nonidentified_set"]["evaluation_report"]["failures"] == [
        {
            "code": "UCM-F015-CONDITIONING_AS_INTERVENTION",
            "record_id": "m1-c19-w15b",
            "detail": (
                "candidate pointified/narrowed a public-equivalence effect set: "
                "claimed=(0.0, 0.0), oracle=(-1.0, 1.0)"
            ),
        }
    ]

    forged = deepcopy(records)
    forged[10]["response_wire"]["result"]["observable_predictions"]["obs_1"][
        "values"
    ][0] = 0.4
    forged[10]["response_digest"] = digest_json(forged[10]["response_wire"])
    _refresh_executor_receipt(forged[10])
    with pytest.raises(ProtocolViolation, match="code-owned control replay"):
        mutation_evidence._validate_request_records(
            forged,
            input_preimage_digest=digest_json({"input": "m1-c19"}),
            history=history,
            diagnosis_query=diagnosis,
            rollout_query=rollout,
            delta=delta,
            execution_seed=191,
            expected_subject_id="NonIdPointEstimate",
            expected_failure_code="UCM-F015-CONDITIONING_AS_INTERVENTION",
            expected_semantic_probes=("nonidentified_set",),
            expected_head_record_shape="replay_ddrr",
            observation_outcome=ObservationOutcome.KILLED,
            head_records=[],
        )


def _validate_live_c19_records(records: list[dict[str, object]]) -> None:
    wire = _input_preimage(delta={})
    mutation_evidence._validate_request_records(
        records,
        input_preimage_digest=digest_json({"input": "m1-c19-receipt-attack"}),
        history=mutation_evidence._history_from_wire(wire["history"]),
        diagnosis_query=mutation_evidence._diagnosis_query_from_wire(
            wire["diagnosis_query"]
        ),
        rollout_query=mutation_evidence._rollout_query_from_wire(
            wire["rollout_query"]
        ),
        delta=mutation_evidence._delta_from_wire(wire["delta"]),
        execution_seed=191,
        expected_subject_id="NonIdPointEstimate",
        expected_failure_code="UCM-F015-CONDITIONING_AS_INTERVENTION",
        expected_semantic_probes=("nonidentified_set",),
        expected_head_record_shape="replay_ddrr",
        observation_outcome=ObservationOutcome.KILLED,
        head_records=[],
    )


@pytest.mark.parametrize(
    ("attack", "message"),
    [
        ("unverified_downgrade", "exact code-owned fresh/sequential"),
        ("sequential_downgrade", "exact code-owned fresh/sequential"),
        ("wrong_isolation", "fresh success lacks an exact isolated"),
        ("same_pid", "fresh success lacks an exact isolated"),
        ("bad_nonce", "invocation_nonce is invalid"),
        ("bad_receipt", "executor receipt mismatch"),
        ("bool_parent_pid", "parent_pid must be a positive integer"),
        ("duplicate_nonce_resigned", "reused a code-owned invocation nonce"),
        ("binding_splice_resigned", "spliced distinct live execution bindings"),
        ("canonical_bool_response", "code-owned control replay"),
    ],
)
def test_decisive_evaluator_receipts_reject_downgrade_splice_and_type_aliases(
    attack: str,
    message: str,
) -> None:
    records = _actual_evaluator_request_transcript(
        "NonIdPointEstimateControl", "nonidentified_set", 191
    )[0]
    target = records[0]
    if attack in {"unverified_downgrade", "sequential_downgrade"}:
        if attack == "sequential_downgrade":
            target = records[-1]
        target["executor_protocol"] = (
            compliance._UNVERIFIED_EXECUTOR_RECEIPT_PROTOCOL
        )
        target["worker_pid"] = None
        target["isolation"] = None
        for field_name in (
            "candidate_bundle_digest",
            "candidate_model_digest",
            "harness_bundle_digest",
            "import_inventory_digest",
            "module_origin",
        ):
            target[field_name] = None
        _refresh_executor_receipt(target)
    elif attack == "wrong_isolation":
        target["isolation"] = "fresh-python-process-audit-v3"
        _refresh_executor_receipt(target)
    elif attack == "same_pid":
        target["worker_pid"] = target["parent_pid"]
        _refresh_executor_receipt(target)
    elif attack == "bad_nonce":
        target["invocation_nonce"] = "A" * 32
        _refresh_executor_receipt(target)
    elif attack == "bad_receipt":
        target["executor_receipt"] = "sha256:" + "0" * 64
    elif attack == "bool_parent_pid":
        target["parent_pid"] = False
        _refresh_executor_receipt(target)
    elif attack == "duplicate_nonce_resigned":
        records[1]["invocation_nonce"] = records[0]["invocation_nonce"]
        _refresh_executor_receipt(records[1])
    elif attack == "binding_splice_resigned":
        target["candidate_bundle_digest"] = "sha256:" + "9" * 64
        _refresh_executor_receipt(target)
    else:
        evaluator_response = records[10]
        evaluator_response["response_wire"]["result"]["observable_predictions"][
            "obs_1"
        ]["values"][0] = False
        _refresh_request_record(evaluator_response)
    with pytest.raises(ProtocolViolation, match=message):
        _validate_live_c19_records(records)


def test_decisive_evaluator_transcript_rejects_exact_record_splice_and_resign() -> None:
    records = _actual_evaluator_request_transcript(
        "NonIdPointEstimateControl", "nonidentified_set", 191
    )[0]
    records[1] = deepcopy(records[0])
    with pytest.raises(ProtocolViolation, match="invocation nonce|executor receipt"):
        _validate_live_c19_records(records)


@pytest.mark.parametrize(
    ("subject_id", "control_name", "probe", "failure_code", "record_id"),
    [
        (
            "DangerousMeanCompressor",
            "DangerousMeanCompressorControl",
            "dangerous_collision",
            "UCM-F016-DANGEROUS_COLLISION",
            "m1-c24-w04-pair",
        ),
        (
            "UnsafeClosedWorld",
            "UnsafeClosedWorldControl",
            "unsafe_closed_world",
            "UCM-F017-OOD_FORCED_MATCH",
            "m1-c25-w18-attributable",
        ),
    ],
)
def test_evaluator_request_suffix_rebuilds_full_pair_and_attributable_ood(
    subject_id: str,
    control_name: str,
    probe: str,
    failure_code: str,
    record_id: str,
) -> None:
    seed = 211
    (
        records,
        history,
        diagnosis,
        rollout,
        delta,
        actual_failure_code,
        verdict,
    ) = _actual_evaluator_request_transcript(control_name, probe, seed)
    assert actual_failure_code == failure_code
    assert verdict == "fail"

    _, _, evidence = mutation_evidence._validate_request_records(
        records,
        input_preimage_digest=digest_json({"input": probe}),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        execution_seed=seed,
        expected_subject_id=subject_id,
        expected_failure_code=failure_code,
        expected_semantic_probes=(probe,),
        expected_head_record_shape="replay_ddrr",
        observation_outcome=ObservationOutcome.KILLED,
        head_records=[],
    )
    artifact = evidence[probe]
    assert artifact["evaluation_report"]["failures"] == [
        {
            "code": failure_code,
            "record_id": record_id,
            "detail": artifact["evaluation_report"]["failures"][0]["detail"],
        }
    ]
    if probe == "dangerous_collision":
        assert artifact["fixture"]["full_policy_count"] == 8
        assert artifact["evaluation_report"]["pairs"][
            "attributable_collision_count"
        ] == 1
    else:
        assert artifact["evaluation_report"]["ood"][
            "irreducible_excluded_count"
        ] == 1
        assert artifact["evaluation_report"]["ood"]["known_count"] == 2


def test_correct_nonidentified_set_pass_suffix_is_exact_and_not_bare_abstain() -> None:
    seed = 223
    (
        records,
        history,
        diagnosis,
        rollout,
        delta,
        failure_code,
        verdict,
    ) = _actual_evaluator_request_transcript(
        "CorrectNonidentifiedSetControl", "nonidentified_set", seed
    )
    assert failure_code is None
    assert verdict == "pass"

    _, _, evidence = mutation_evidence._validate_request_records(
        records,
        input_preimage_digest=digest_json({"input": "correct-set"}),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        execution_seed=seed,
        expected_subject_id="CorrectNonidentifiedSet",
        expected_failure_code=None,
        expected_semantic_probes=("nonidentified_set",),
        expected_head_record_shape="replay_ddrr",
        observation_outcome=ObservationOutcome.PASSED,
        head_records=[],
    )
    artifact = evidence["nonidentified_set"]
    assert artifact["evaluation_report"]["failures"] == []
    prediction = artifact["raw_records"][0]["candidate_output"][
        "rollout_responses"
    ][0]["result"]["observable_predictions"]["obs_1"]
    assert prediction == {
        "protocol": "ucm-identified-mean-interval/1",
        "lower": 0.0,
        "upper": 1.0,
    }


def test_empty_head_terminal_topology_registry_covers_every_empty_subject() -> None:
    empty_subjects = {
        row[0]
        for row in mutation_evidence._PORTABLE_MUTATION_CONTRACTS
        if row[-1] == "empty"
    }
    assert set(mutation_evidence._EMPTY_HEAD_TERMINAL_REQUEST_TOPOLOGIES) == (
        empty_subjects
    )
    assert {row[0] for row in EMPTY_HEAD_CASES} == empty_subjects
    for topology in mutation_evidence._EMPTY_HEAD_TERMINAL_REQUEST_TOPOLOGIES.values():
        assert topology
        assert topology[-1][2] == "worker_error"
        assert sum(status == "worker_error" for _, _, status in topology) == 1


@pytest.mark.parametrize(
    (
        "subject_id",
        "control_class_name",
        "row_index",
        "gate",
        "failure_code",
        "terminal_operation",
    ),
    EMPTY_HEAD_CASES,
)
def test_every_empty_head_kill_binds_its_exact_live_terminal_topology(
    subject_id: str,
    control_class_name: str,
    row_index: int,
    gate: str,
    failure_code: str,
    terminal_operation: str,
) -> None:
    execution_seed = TEST_BASE_SEED + row_index
    report = _decisive_raw(
        binding_digit="3",
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": f"{gate}-unit-test",
                "verdict": "fail",
                "failure_code": failure_code,
                "detail": "exact empty-head terminal topology",
                "evidence": {},
            }
        ],
        failure_codes=[failure_code],
        decision_kind="mutant_kill",
        expected_gate=gate,
        expected_failure_code=failure_code,
    )[3]
    records = report["request_records"]
    assert type(records) is list
    expected_success_prefix = {
        "initialize": [],
        "diagnose": [
            ("fresh", "initialize", execution_seed, "success", None),
            ("fresh", "initialize", execution_seed, "success", None),
        ],
        "rollout": [
            ("fresh", "initialize", execution_seed, "success", None),
            ("fresh", "initialize", execution_seed, "success", None),
            ("fresh", "diagnose", execution_seed + 1, "success", None),
            ("fresh", "diagnose", execution_seed + 1, "success", None),
        ],
    }[terminal_operation]
    assert [
        (
            row["execution_mode"],
            row["operation"],
            row["seed"],
            row["status"],
            row["failure_code"],
        )
        for row in records
    ] == [
        *expected_success_prefix,
        (
            "fresh",
            terminal_operation,
            execution_seed
            + {"initialize": 0, "diagnose": 1, "rollout": 2}[
                terminal_operation
            ],
            "worker_error",
            failure_code,
        ),
    ]
    assert report["head_records"] == []

    bundle = _invalid_kill_builder(
        subject_id=subject_id,
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        actual_gate=gate,
        actual_failure_code=failure_code,
    ).finalize()
    assert bundle.observations[0].outcome is ObservationOutcome.KILLED


@pytest.mark.parametrize(
    "mutation",
    [
        "old_single_initialize_success",
        "missing_terminal",
        "premature_terminal",
        "post_terminal_call",
        "wrong_operation",
        "wrong_seed",
        "wrong_mode",
        "wrong_status",
        "wrong_code",
    ],
)
def test_empty_head_kill_rejects_nonexact_terminal_topology(mutation: str) -> None:
    report = _decisive_raw(
        binding_digit="3",
        control_class_name="RawHistoryHeadControl",
        execution_seed=RAW_HISTORY_SEED,
        outcome="killed",
        findings=[
            {
                "gate": "C02-unit-test",
                "verdict": "fail",
                "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                "detail": "exact empty-head terminal topology",
                "evidence": {},
            }
        ],
        failure_codes=["UCM-F004-HEAD_HISTORY_ACCESS"],
        decision_kind="mutant_kill",
        expected_gate="C02",
        expected_failure_code="UCM-F004-HEAD_HISTORY_ACCESS",
    )[3]
    exact = deepcopy(report["request_records"])
    assert type(exact) is list and len(exact) == 3

    def as_worker_error(
        record: dict[str, object], failure_code: str
    ) -> dict[str, object]:
        mutated = deepcopy(record)
        mutated.update(
            {
                "status": "worker_error",
                "response_wire": None,
                "response_digest": None,
                "failure_origin": "candidate",
                "failure_code": failure_code,
            }
        )
        return mutated

    if mutation == "old_single_initialize_success":
        records = exact[:1]
    elif mutation == "missing_terminal":
        records = exact[:-1]
    elif mutation == "premature_terminal":
        records = [
            as_worker_error(exact[0], "UCM-F004-HEAD_HISTORY_ACCESS")
        ]
    elif mutation == "post_terminal_call":
        records = [*exact, deepcopy(exact[0])]
    elif mutation == "wrong_operation":
        records = [
            *exact[:2],
            as_worker_error(exact[0], "UCM-F004-HEAD_HISTORY_ACCESS"),
        ]
    elif mutation == "wrong_seed":
        records = exact
        records[-1]["request_wire"]["seed"] = RAW_HISTORY_SEED + 2
        records[-1]["seed"] = RAW_HISTORY_SEED + 2
        _refresh_request_record(records[-1])
    elif mutation == "wrong_mode":
        records = exact
        records[-1]["execution_mode"] = "sequential"
    elif mutation == "wrong_status":
        complete = _request_transcript(
            execution_seed=RAW_HISTORY_SEED,
            include_delta=False,
            full=True,
        )
        records = [*exact[:2], deepcopy(complete[2])]
    else:
        records = exact
        records[-1]["failure_code"] = "UCM-F008-STATE_NOT_CLOSED"

    invocation_digest = digest_json(records)
    invalid = _invalid_kill_builder(
        report={
            "request_records": records,
            "invocation_transcript_digest": invocation_digest,
        },
        decision={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation):
        invalid.finalize()


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

    forged_lineage_wire = _wire(_bundle())
    forged_lineage_wire["base_seed"] = lineage_overflow_base
    with pytest.raises(ProtocolViolation, match="update-consistency lineage seeds"):
        MutationEvidenceBundle.from_canonical_bytes(
            _resign(forged_lineage_wire)
        )


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


def test_builder_exposes_a_read_only_input_preimage_digest() -> None:
    builder = _builder()
    assert builder.input_preimage_digest == _input_digest()
    with pytest.raises(AttributeError):
        builder.input_preimage_digest = "sha256:" + "0" * 64  # type: ignore[misc]


@pytest.mark.parametrize(
    "field_name",
    ["history", "diagnosis_query", "rollout_query", "delta"],
)
def test_input_preimage_requires_exact_typed_wire_round_trips(field_name: str) -> None:
    input_preimage = _input_preimage(delta={} if field_name == "delta" else None)
    target = input_preimage[field_name]
    assert type(target) is dict
    target["unexpected"] = True
    invalid = MutationEvidenceBuilder(
        run_id="mutation-unit-run",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=input_preimage,
        execution_context=_execution_context(),
    )
    with pytest.raises(ProtocolViolation, match="fields mismatch|typed protocol parsing"):
        invalid.finalize()


@pytest.mark.parametrize(
    "changed_field",
    ["history", "diagnosis_query", "rollout_query", "delta"],
)
def test_old_decisive_payload_cannot_be_reenveloped_for_new_inputs(
    changed_field: str,
) -> None:
    changed_input = _input_preimage(delta={})
    if changed_field == "history":
        changed_input["history"]["events"][0]["payload"]["value"] = 0.9
    elif changed_field == "diagnosis_query":
        changed_input["diagnosis_query"]["label_catalog"] = ["a", "c"]
    elif changed_field == "rollout_query":
        changed_input["rollout_query"]["horizon"] = 3
    else:
        changed_input["delta"]["events"][0]["payload"]["value"] = 0.95
    builder = MutationEvidenceBuilder(
        run_id="mutation-unit-run",
        runner_protocol=TEST_RUNNER_PROTOCOL,
        base_seed=TEST_BASE_SEED,
        input_preimage=changed_input,
        execution_context=_execution_context(),
    )
    pre, post, source, report, decision, decisive = _decisive_raw(
        binding_digit="4",
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
        include_delta=True,
    )
    # Simulate an attacker updating every visible digest envelope while
    # retaining the old actual request transcript.
    for payload in (report, decision, decisive):
        payload["input_preimage_digest"] = builder.input_preimage_digest
    decisive["report_transcript_payload_digest"] = digest_json(report)
    decisive["decision_record_payload_digest"] = digest_json(decision)
    builder.add_record(
        subject_id="ExplicitSeedStochasticState",
        subject_kind=SubjectKind.SPECIFICITY_CONTROL,
        execution_seed=EXPLICIT_SEED,
        outcome=ObservationOutcome.PASSED,
        actual_gate=None,
        actual_failure_code=None,
        classification="ordinary_candidate",
        pre_source_witness=pre,
        post_source_witness=post,
        source_record=source,
        report_transcript=report,
        error_transcript=_error_transcript([]),
        decision_record=decision,
        decisive_record=decisive,
    )
    with pytest.raises(
        ProtocolViolation,
        match="differs from input|complete repeated main invocation flow|exact complete fresh main",
    ):
        builder.finalize()


@pytest.mark.parametrize("mutation", ["bad_digest", "extra_wire_key"])
def test_request_transcript_rejects_forged_wire_or_digest(mutation: str) -> None:
    report = _decisive_raw(
        binding_digit="4",
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
    )[3]
    records = deepcopy(report["request_records"])
    if mutation == "bad_digest":
        records[0]["request_digest"] = "sha256:" + "9" * 64
        message = "request digest mismatch"
    else:
        records[0]["request_wire"]["unexpected"] = True
        _refresh_request_record(records[0])
        message = "request fields mismatch"
    invalid = _invalid_pass_builder(report={"request_records": records})
    with pytest.raises(ProtocolViolation, match=message):
        invalid.finalize()


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_request_transcript_records_are_closed(mutation: str) -> None:
    report = _decisive_raw(
        binding_digit="4",
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
    )[3]
    records = deepcopy(report["request_records"])
    if mutation == "missing":
        records[0].pop("request_fully_sent")
    else:
        records[0]["unexpected"] = True
    invalid = _invalid_pass_builder(report={"request_records": records})
    with pytest.raises(ProtocolViolation, match="closed object"):
        invalid.finalize()


def test_request_transcript_rejects_state_and_head_request_splicing() -> None:
    base = _decisive_raw(
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
    state_splice = deepcopy(base["request_records"])
    diagnosis = next(row for row in state_splice if row["operation"] == "diagnose")
    diagnosis["request_wire"]["state"] = _state_wire("spliced")
    _refresh_request_record(diagnosis)
    invalid_state = _invalid_kill_builder(
        subject_id="GlobalSecondState",
        control_class_name="GlobalSecondStateControl",
        execution_seed=TEST_BASE_SEED,
        actual_gate="C04",
        actual_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
        report={
            "request_records": state_splice,
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
    with pytest.raises(ProtocolViolation, match="prior successful StateResponse"):
        invalid_state.finalize()

    head_splice = deepcopy(base["head_records"])
    for head in head_splice[:2]:
        head["request_digest"] = "sha256:" + "9" * 64
    invalid_head = _invalid_kill_builder(
        subject_id="GlobalSecondState",
        control_class_name="GlobalSecondStateControl",
        execution_seed=TEST_BASE_SEED,
        actual_gate="C04",
        actual_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
        report={
            "head_records": head_splice,
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
    with pytest.raises(ProtocolViolation, match="fresh success request record"):
        invalid_head.finalize()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("consumed_state", "one shared consumed state"),
        ("request", "request/state/binding drifted"),
        ("response", "response drift lacks"),
        ("isolation", "isolation protocol mismatch"),
    ],
)
def test_passed_replay_heads_bind_one_state_and_exact_ddrr_pairs(
    mutation: str, message: str
) -> None:
    base = _decisive_raw(
        binding_digit="4",
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
        include_delta=True,
    )[3]
    heads = deepcopy(base["head_records"])
    if mutation == "consumed_state":
        heads[3]["consumed_state_hash"] = "sha256:" + "9" * 64
    elif mutation == "request":
        heads[1]["request_digest"] = "sha256:" + "9" * 64
    elif mutation == "response":
        heads[1]["response_digest"] = "sha256:" + "9" * 64
    else:
        heads[1]["isolation"] = "fresh-python-process-audit-v3"
    invalid = _invalid_pass_builder(delta={}, report={"head_records": heads})
    with pytest.raises(ProtocolViolation, match=message):
        invalid.finalize()


@pytest.mark.parametrize(
    ("status", "patch", "message"),
    [
        ("success", {"response_wire": None, "response_digest": None}, "successful request record is inconsistent"),
        ("worker_error", {"failure_origin": "candidate", "failure_code": "UCM-F008-STATE_NOT_CLOSED"}, "candidate worker error record is inconsistent"),
        ("worker_error", {"request_fully_sent": False, "received_request_digest": None, "response_wire": None, "response_digest": None, "failure_origin": "candidate", "failure_code": "UCM-F008-STATE_NOT_CLOSED"}, "candidate worker error record is inconsistent"),
        ("harness_error", {"request_fully_sent": False, "received_request_digest": None, "response_digest": None, "failure_origin": "harness", "failure_code": "UCM-E003-HARNESS_INCOMPLETE"}, "response wire/digest nullability mismatch"),
    ],
)
def test_request_transcript_status_field_combinations_are_strict(
    status: str, patch: dict[str, object], message: str
) -> None:
    base = _decisive_raw(
        binding_digit="4",
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
    )[3]
    records = deepcopy(base["request_records"])
    records[0]["status"] = status
    records[0].update(patch)
    _refresh_executor_receipt(records[0])
    invalid = _invalid_pass_builder(report={"request_records": records})
    with pytest.raises(ProtocolViolation, match=message):
        invalid.finalize()


@pytest.mark.parametrize(
    ("status", "failure_code", "message"),
    [
        ("harness_error", "UCM-E003-HARNESS_INCOMPLETE", "cannot contain harness_error"),
        ("worker_error", "UCM-F008-STATE_NOT_CLOSED", "code-owned decisive failure code"),
    ],
)
def test_decisive_kill_rejects_harness_or_unrelated_worker_errors(
    status: str, failure_code: str, message: str
) -> None:
    base = _decisive_raw(
        binding_digit="3",
        control_class_name="RawHistoryHeadControl",
        execution_seed=RAW_HISTORY_SEED,
        outcome="killed",
        findings=[
            {
                "gate": "C02-head-history",
                "verdict": "fail",
                "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                "detail": "unit-test decisive failure",
                "evidence": {},
            }
        ],
        failure_codes=["UCM-F004-HEAD_HISTORY_ACCESS"],
        decision_kind="mutant_kill",
    )[3]
    records = deepcopy(base["request_records"])
    terminal = records[-1]
    terminal.update(
        {
            "status": status,
            "response_wire": None,
            "response_digest": None,
            "failure_origin": "harness" if status == "harness_error" else "candidate",
            "failure_code": failure_code,
        }
    )
    if status == "harness_error":
        terminal["request_fully_sent"] = False
        terminal["received_request_digest"] = None
    _refresh_executor_receipt(terminal)
    invocation_digest = digest_json(records)
    invalid = _invalid_kill_builder(
        report={
            "request_records": records,
            "invocation_transcript_digest": invocation_digest,
        },
        decision={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match=message):
        invalid.finalize()


def test_replay_heads_require_distinct_ordered_fresh_success_records() -> None:
    base = _decisive_raw(
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
    records = base["request_records"]
    reduced = [
        deepcopy(next(row for row in records if row["operation"] == operation))
        for operation in ("initialize", "diagnose", "rollout")
    ]
    invocation_digest = digest_json(reduced)
    invalid = _invalid_kill_builder(
        subject_id="GlobalSecondState",
        control_class_name="GlobalSecondStateControl",
        execution_seed=TEST_BASE_SEED,
        actual_gate="C04",
        actual_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
        report={
            "request_records": reduced,
            "invocation_transcript_digest": invocation_digest,
            "findings": [
                {
                    "gate": "C04-update-purity",
                    "verdict": "fail",
                    "failure_code": "UCM-F006-HIDDEN_PATIENT_CACHE",
                }
            ],
            "failure_codes": ["UCM-F006-HIDDEN_PATIENT_CACHE"],
        },
        decision={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(
        ProtocolViolation,
        match="exact code-owned ordered flow|one-to-one.*distinct ordered fresh",
    ):
        invalid.finalize()


def test_passed_main_flow_cannot_be_replaced_by_sequential_probe_records() -> None:
    base = _decisive_raw(
        binding_digit="4",
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
    )[3]
    records = deepcopy(base["request_records"])
    for record in records:
        record["execution_mode"] = "sequential"
        _refresh_executor_receipt(record)
    invocation_digest = digest_json(records)
    invalid = _invalid_pass_builder(
        report={
            "request_records": records,
            "invocation_transcript_digest": invocation_digest,
        },
        decision={"invocation_transcript_digest": invocation_digest},
        decisive={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="attempted main initialize"):
        invalid.finalize()


@pytest.mark.parametrize(
    "mutation",
    ["late_second_initialize", "extra_initialize", "updates_before_heads"],
)
def test_fresh_main_flow_requires_exact_code_owned_order(mutation: str) -> None:
    base = _decisive_raw(
        binding_digit="4",
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
        include_delta=True,
    )[3]
    main = deepcopy(base["request_records"][:8])
    if mutation == "late_second_initialize":
        records = [main[0], *main[2:6], main[1], *main[6:]]
    elif mutation == "extra_initialize":
        records = [*main[:2], deepcopy(main[0]), *main[2:]]
    else:
        records = [*main[:2], *main[6:], *main[2:6]]
    invocation_digest = digest_json(records)
    invalid = _invalid_pass_builder(
        delta={},
        report={
            "request_records": records,
            "invocation_transcript_digest": invocation_digest,
        },
        decision={"invocation_transcript_digest": invocation_digest},
        decisive={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="exact code-owned ordered flow"):
        invalid.finalize()


def test_semantic_or_sequential_record_cannot_interleave_the_physical_main_prefix() -> None:
    base = _decisive_raw(
        binding_digit="4",
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
    )[3]
    records = deepcopy(base["request_records"])
    interleaved = deepcopy(records[0])
    interleaved["execution_mode"] = "sequential"
    interleaved["invocation_nonce"] = "f" * 32
    _refresh_executor_receipt(interleaved)
    records.insert(1, interleaved)
    invocation_digest = digest_json(records)
    invalid = _invalid_pass_builder(
        delta={},
        report={
            "request_records": records,
            "invocation_transcript_digest": invocation_digest,
        },
        decision={"invocation_transcript_digest": invocation_digest},
        decisive={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="physical request_records prefix"):
        invalid.finalize()


def test_second_main_update_must_replay_the_exact_first_update_request() -> None:
    base = _decisive_raw(
        binding_digit="4",
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
        include_delta=True,
    )[3]
    records = deepcopy(base["request_records"])
    # The second main update is a replay of the first request.  Feeding the
    # first update's response state instead manufactures a different chain.
    records[7]["request_wire"]["state"] = deepcopy(
        records[6]["response_wire"]["state"]
    )
    _refresh_request_record(records[7])
    invocation_digest = digest_json(records)
    invalid = _invalid_pass_builder(
        delta={},
        report={
            "request_records": records,
            "invocation_transcript_digest": invocation_digest,
        },
        decision={"invocation_transcript_digest": invocation_digest},
        decisive={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="update replay pair"):
        invalid.finalize()


@pytest.mark.parametrize("mutation", ["delete", "insert", "reorder"])
def test_passed_semantic_suffix_is_exact_and_physically_closed(mutation: str) -> None:
    base = _decisive_raw(
        binding_digit="4",
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
        include_delta=True,
    )[3]
    records = deepcopy(base["request_records"])
    suffix_start = 8
    if mutation == "delete":
        del records[suffix_start + 4]
    elif mutation == "insert":
        records.insert(suffix_start + 4, deepcopy(records[suffix_start + 4]))
    else:
        records[suffix_start + 4], records[suffix_start + 5] = (
            records[suffix_start + 5],
            records[suffix_start + 4],
        )
    invocation_digest = digest_json(records)
    invalid = _invalid_pass_builder(
        delta={},
        report={
            "request_records": records,
            "invocation_transcript_digest": invocation_digest,
        },
        decision={"invocation_transcript_digest": invocation_digest},
        decisive={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="exact invocation shape"):
        invalid.finalize()


def test_replay_kill_cannot_replace_main_updates_with_lineage_delta_coverage() -> None:
    execution_seed = TEST_BASE_SEED + 12
    base = _decisive_raw(
        binding_digit="3",
        control_class_name="ReplayBatchDivergenceControl",
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": "C22-update-consistency",
                "verdict": "fail",
                "failure_code": "UCM-F019-UPDATE_INCONSISTENT",
                "detail": "unit-test decisive failure",
                "evidence": {},
            }
        ],
        failure_codes=["UCM-F019-UPDATE_INCONSISTENT"],
        decision_kind="mutant_kill",
        expected_gate="C22",
        expected_failure_code="UCM-F019-UPDATE_INCONSISTENT",
        semantic_probes=("update_consistency",),
        include_delta=True,
    )[3]
    records = deepcopy(base["request_records"])
    # Retain the complete lineage probe (including its two updates), but drop
    # only the two code-owned main update replays.  Lineage delta coverage is
    # not a substitute for the main execution flow.
    records = [*records[:6], *records[8:]]
    invocation_digest = digest_json(records)
    invalid = _invalid_kill_builder(
        subject_id="ReplayBatchDivergence",
        control_class_name="ReplayBatchDivergenceControl",
        execution_seed=execution_seed,
        actual_gate="C22",
        actual_failure_code="UCM-F019-UPDATE_INCONSISTENT",
        delta={},
        semantic_probes=("update_consistency",),
        report={
            "request_records": records,
            "invocation_transcript_digest": invocation_digest,
            "findings": [
                {
                    "gate": "C22-update-consistency",
                    "verdict": "fail",
                    "failure_code": "UCM-F019-UPDATE_INCONSISTENT",
                }
            ],
            "failure_codes": ["UCM-F019-UPDATE_INCONSISTENT"],
        },
        decision={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="exact complete fresh main flow"):
        invalid.finalize()


@pytest.mark.parametrize(
    (
        "subject_id",
        "control_class_name",
        "row_index",
        "gate",
        "failure_code",
        "semantic_probes",
        "delta",
    ),
    [
        (
            "GlobalSecondState",
            "GlobalSecondStateControl",
            0,
            "C04",
            "UCM-F006-HIDDEN_PATIENT_CACHE",
            (),
            None,
        ),
        (
            "WarmFutureCache",
            "WarmFutureCacheControl",
            11,
            "C23",
            "UCM-F001-FUTURE_LEAK",
            ("warm_future_old_cut",),
            {},
        ),
        (
            "ReplayBatchDivergence",
            "ReplayBatchDivergenceControl",
            12,
            "C22",
            "UCM-F019-UPDATE_INCONSISTENT",
            ("update_consistency",),
            {},
        ),
        (
            "DoubleCountEvent",
            "DoubleCountEventControl",
            13,
            "C22",
            "UCM-F019-UPDATE_INCONSISTENT",
            ("update_consistency",),
            {},
        ),
    ],
)
def test_comparison_kills_bind_the_exact_live_probe_suffix(
    subject_id: str,
    control_class_name: str,
    row_index: int,
    gate: str,
    failure_code: str,
    semantic_probes: tuple[str, ...],
    delta: dict[str, object] | None,
) -> None:
    builder = _invalid_kill_builder(
        subject_id=subject_id,
        control_class_name=control_class_name,
        execution_seed=TEST_BASE_SEED + row_index,
        actual_gate=gate,
        actual_failure_code=failure_code,
        semantic_probes=semantic_probes,
        delta=delta,
    )
    assert builder.finalize().observations[0].outcome is ObservationOutcome.KILLED


@pytest.mark.parametrize(
    (
        "subject_id",
        "control_class_name",
        "row_index",
        "gate",
        "failure_code",
        "semantic_probes",
        "delta",
    ),
    [
        (
            "GlobalSecondState",
            "GlobalSecondStateControl",
            0,
            "C04",
            "UCM-F006-HIDDEN_PATIENT_CACHE",
            (),
            None,
        ),
        (
            "WarmFutureCache",
            "WarmFutureCacheControl",
            11,
            "C23",
            "UCM-F001-FUTURE_LEAK",
            ("warm_future_old_cut",),
            {},
        ),
        (
            "ReplayBatchDivergence",
            "ReplayBatchDivergenceControl",
            12,
            "C22",
            "UCM-F019-UPDATE_INCONSISTENT",
            ("update_consistency",),
            {},
        ),
    ],
)
def test_comparison_kill_cannot_be_decisive_from_main_only(
    subject_id: str,
    control_class_name: str,
    row_index: int,
    gate: str,
    failure_code: str,
    semantic_probes: tuple[str, ...],
    delta: dict[str, object] | None,
) -> None:
    execution_seed = TEST_BASE_SEED + row_index
    base = _decisive_raw(
        binding_digit="3",
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": f"{gate}-comparison",
                "verdict": "fail",
                "failure_code": failure_code,
                "detail": "unit-test decisive comparison",
                "evidence": {},
            }
        ],
        failure_codes=[failure_code],
        decision_kind="mutant_kill",
        expected_gate=gate,
        expected_failure_code=failure_code,
        semantic_probes=semantic_probes,
        include_delta=delta is not None,
    )[3]
    main_length = 8 if delta is not None else 6
    records = deepcopy(base["request_records"][:main_length])
    invocation_digest = digest_json(records)
    report = {
        **base,
        "request_records": records,
        "invocation_transcript_digest": invocation_digest,
    }
    invalid = _invalid_kill_builder(
        subject_id=subject_id,
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        actual_gate=gate,
        actual_failure_code=failure_code,
        semantic_probes=semantic_probes,
        delta=delta,
        report=report,
        decision={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="exact invocation shape"):
        invalid.finalize()


@pytest.mark.parametrize(
    (
        "subject_id",
        "control_class_name",
        "row_index",
        "gate",
        "failure_code",
        "semantic_probes",
    ),
    [
        (
            "WarmFutureCache",
            "WarmFutureCacheControl",
            11,
            "C23",
            "UCM-F001-FUTURE_LEAK",
            ("warm_future_old_cut",),
        ),
        (
            "ReplayBatchDivergence",
            "ReplayBatchDivergenceControl",
            12,
            "C22",
            "UCM-F019-UPDATE_INCONSISTENT",
            ("update_consistency",),
        ),
    ],
)
def test_semantic_kill_suffix_must_retain_final_warm_cold_sequence(
    subject_id: str,
    control_class_name: str,
    row_index: int,
    gate: str,
    failure_code: str,
    semantic_probes: tuple[str, ...],
) -> None:
    execution_seed = TEST_BASE_SEED + row_index
    base = _decisive_raw(
        binding_digit="3",
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": f"{gate}-comparison",
                "verdict": "fail",
                "failure_code": failure_code,
                "detail": "unit-test decisive comparison",
                "evidence": {},
            }
        ],
        failure_codes=[failure_code],
        decision_kind="mutant_kill",
        expected_gate=gate,
        expected_failure_code=failure_code,
        semantic_probes=semantic_probes,
        include_delta=True,
    )[3]
    records = deepcopy(base["request_records"][:-3])
    invocation_digest = digest_json(records)
    report = {
        **base,
        "request_records": records,
        "invocation_transcript_digest": invocation_digest,
    }
    invalid = _invalid_kill_builder(
        subject_id=subject_id,
        control_class_name=control_class_name,
        execution_seed=execution_seed,
        actual_gate=gate,
        actual_failure_code=failure_code,
        semantic_probes=semantic_probes,
        delta={},
        report=report,
        decision={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="exact invocation shape"):
        invalid.finalize()


def test_f006_requires_actual_raw_warm_cold_drift() -> None:
    execution_seed = TEST_BASE_SEED
    base = _decisive_raw(
        binding_digit="3",
        control_class_name="GlobalSecondStateControl",
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": "C04-warm-cold",
                "verdict": "fail",
                "failure_code": "UCM-F006-HIDDEN_PATIENT_CACHE",
                "detail": "unit-test decisive comparison",
                "evidence": {},
            }
        ],
        failure_codes=["UCM-F006-HIDDEN_PATIENT_CACHE"],
        decision_kind="mutant_kill",
        expected_gate="C04",
        expected_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
    )[3]
    records = deepcopy(base["request_records"])
    main_length = 6
    records[main_length]["response_wire"] = deepcopy(records[0]["response_wire"])
    _refresh_request_record(records[main_length])
    invocation_digest = digest_json(records)
    report = {
        **base,
        "request_records": records,
        "invocation_transcript_digest": invocation_digest,
    }
    invalid = _invalid_kill_builder(
        subject_id="GlobalSecondState",
        control_class_name="GlobalSecondStateControl",
        execution_seed=execution_seed,
        actual_gate="C04",
        actual_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
        report=report,
        decision={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="lacks actual warm/fresh raw drift"):
        invalid.finalize()


def test_f019_requires_actual_scored_drift_and_finding_binding() -> None:
    execution_seed = TEST_BASE_SEED + 12
    base = _decisive_raw(
        binding_digit="3",
        control_class_name="ReplayBatchDivergenceControl",
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": "C22-update-consistency",
                "verdict": "fail",
                "failure_code": "UCM-F019-UPDATE_INCONSISTENT",
                "detail": "unit-test decisive comparison",
                "evidence": {},
            }
        ],
        failure_codes=["UCM-F019-UPDATE_INCONSISTENT"],
        decision_kind="mutant_kill",
        expected_gate="C22",
        expected_failure_code="UCM-F019-UPDATE_INCONSISTENT",
        semantic_probes=("update_consistency",),
        include_delta=True,
    )[3]
    no_drift_records = deepcopy(base["request_records"])
    main_length = 8
    no_drift_records[main_length + 6]["response_wire"] = deepcopy(
        no_drift_records[main_length + 4]["response_wire"]
    )
    _refresh_request_record(no_drift_records[main_length + 6])
    no_drift_digest = digest_json(no_drift_records)
    no_drift_report = {
        **base,
        "request_records": no_drift_records,
        "invocation_transcript_digest": no_drift_digest,
    }
    no_drift = _invalid_kill_builder(
        subject_id="ReplayBatchDivergence",
        control_class_name="ReplayBatchDivergenceControl",
        execution_seed=execution_seed,
        actual_gate="C22",
        actual_failure_code="UCM-F019-UPDATE_INCONSISTENT",
        semantic_probes=("update_consistency",),
        delta={},
        report=no_drift_report,
        decision={"invocation_transcript_digest": no_drift_digest},
    )
    with pytest.raises(ProtocolViolation, match="lacks actual scored consistency drift"):
        no_drift.finalize()

    forged_report = deepcopy(base)
    decisive_finding = next(
        finding
        for finding in forged_report["findings"]
        if finding["failure_code"] == "UCM-F019-UPDATE_INCONSISTENT"
    )
    decisive_finding["evidence"]["incremental_equals_replay"] = True
    forged = _invalid_kill_builder(
        subject_id="ReplayBatchDivergence",
        control_class_name="ReplayBatchDivergenceControl",
        execution_seed=execution_seed,
        actual_gate="C22",
        actual_failure_code="UCM-F019-UPDATE_INCONSISTENT",
        semantic_probes=("update_consistency",),
        delta={},
        report=forged_report,
    )
    with pytest.raises(ProtocolViolation, match="finding evidence differs"):
        forged.finalize()


def test_f001_requires_actual_scored_old_cut_drift_and_finding_binding() -> None:
    execution_seed = TEST_BASE_SEED + 11
    base = _decisive_raw(
        binding_digit="3",
        control_class_name="WarmFutureCacheControl",
        execution_seed=execution_seed,
        outcome="killed",
        findings=[
            {
                "gate": "C23-old-cut",
                "verdict": "fail",
                "failure_code": "UCM-F001-FUTURE_LEAK",
                "detail": "unit-test decisive comparison",
                "evidence": {},
            }
        ],
        failure_codes=["UCM-F001-FUTURE_LEAK"],
        decision_kind="mutant_kill",
        expected_gate="C23",
        expected_failure_code="UCM-F001-FUTURE_LEAK",
        semantic_probes=("warm_future_old_cut",),
        include_delta=True,
    )[3]
    metadata_only_records = deepcopy(base["request_records"])
    main_length = 8
    metadata_only_records[main_length + 1]["response_wire"] = deepcopy(
        metadata_only_records[2]["response_wire"]
    )
    metadata_only_records[main_length + 1]["response_wire"]["result"][
        "metadata"
    ] = {"raw-only-drift": True}
    _refresh_request_record(metadata_only_records[main_length + 1])
    metadata_only_digest = digest_json(metadata_only_records)
    metadata_only_report = {
        **base,
        "request_records": metadata_only_records,
        "invocation_transcript_digest": metadata_only_digest,
    }
    metadata_only = _invalid_kill_builder(
        subject_id="WarmFutureCache",
        control_class_name="WarmFutureCacheControl",
        execution_seed=execution_seed,
        actual_gate="C23",
        actual_failure_code="UCM-F001-FUTURE_LEAK",
        semantic_probes=("warm_future_old_cut",),
        delta={},
        report=metadata_only_report,
        decision={"invocation_transcript_digest": metadata_only_digest},
    )
    with pytest.raises(ProtocolViolation, match="lacks actual scored old-cut drift"):
        metadata_only.finalize()

    forged_report = deepcopy(base)
    decisive_finding = next(
        finding
        for finding in forged_report["findings"]
        if finding["failure_code"] == "UCM-F001-FUTURE_LEAK"
    )
    decisive_finding["evidence"]["initialize_later_stable"] = True
    forged = _invalid_kill_builder(
        subject_id="WarmFutureCache",
        control_class_name="WarmFutureCacheControl",
        execution_seed=execution_seed,
        actual_gate="C23",
        actual_failure_code="UCM-F001-FUTURE_LEAK",
        semantic_probes=("warm_future_old_cut",),
        delta={},
        report=forged_report,
    )
    with pytest.raises(ProtocolViolation, match="finding evidence differs"):
        forged.finalize()


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
    request_records = deepcopy(base_report["request_records"])
    diagnosis_rows = [
        row for row in request_records if row["operation"] == "diagnose"
    ]
    assert len(diagnosis_rows) == 2
    diagnosis_rows[1]["response_wire"]["result"]["probabilities"] = {
        "a": 0.6,
        "b": 0.4,
    }
    diagnosis_rows[1]["response_digest"] = digest_json(
        diagnosis_rows[1]["response_wire"]
    )
    _refresh_executor_receipt(diagnosis_rows[1])
    heads[1]["response_digest"] = diagnosis_rows[1]["response_digest"]
    invocation_digest = digest_json(request_records)
    allowed = _invalid_kill_builder(
        subject_id="ImplicitRNGState",
        control_class_name="ImplicitRNGControl",
        execution_seed=execution_seed,
        actual_gate="C30",
        actual_failure_code="UCM-F020-NONREPRODUCIBLE",
        report={
            "head_records": heads,
            "request_records": request_records,
            "invocation_transcript_digest": invocation_digest,
            "findings": [
                {
                    "gate": "C30-reproducibility",
                    "verdict": "fail",
                    "failure_code": "UCM-F020-NONREPRODUCIBLE",
                }
            ],
            "failure_codes": ["UCM-F020-NONREPRODUCIBLE"],
        },
        decision={"invocation_transcript_digest": invocation_digest},
    )
    assert allowed.finalize().observations[0].outcome is ObservationOutcome.KILLED


def test_f020_kill_requires_actual_ddrr_head_pair_response_drift() -> None:
    execution_seed = TEST_BASE_SEED + 9
    base = _decisive_raw(
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
    records = deepcopy(base["request_records"])
    records[3]["response_wire"] = deepcopy(records[2]["response_wire"])
    records[3]["response_digest"] = records[2]["response_digest"]
    _refresh_executor_receipt(records[3])
    heads = deepcopy(base["head_records"])
    heads[1]["response_digest"] = heads[0]["response_digest"]
    invocation_digest = digest_json(records)
    invalid = _invalid_kill_builder(
        subject_id="ImplicitRNGState",
        control_class_name="ImplicitRNGControl",
        execution_seed=execution_seed,
        actual_gate="C30",
        actual_failure_code="UCM-F020-NONREPRODUCIBLE",
        report={
            "head_records": heads,
            "request_records": records,
            "invocation_transcript_digest": invocation_digest,
            "findings": [
                {
                    "gate": "C30-reproducibility",
                    "verdict": "fail",
                    "failure_code": "UCM-F020-NONREPRODUCIBLE",
                }
            ],
            "failure_codes": ["UCM-F020-NONREPRODUCIBLE"],
        },
        decision={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="lacks actual main head replay drift"):
        invalid.finalize()


def test_non_f020_subject_rejects_actual_request_response_drift() -> None:
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
    request_records = deepcopy(base_report["request_records"])
    diagnosis_rows = [
        row for row in request_records if row["operation"] == "diagnose"
    ]
    diagnosis_rows[1]["response_wire"]["result"]["probabilities"] = {
        "a": 0.6,
        "b": 0.4,
    }
    diagnosis_rows[1]["response_digest"] = digest_json(
        diagnosis_rows[1]["response_wire"]
    )
    _refresh_executor_receipt(diagnosis_rows[1])
    heads = deepcopy(base_report["head_records"])
    heads[1]["response_digest"] = diagnosis_rows[1]["response_digest"]
    invocation_digest = digest_json(request_records)
    invalid = _invalid_kill_builder(
        subject_id="GlobalSecondState",
        control_class_name="GlobalSecondStateControl",
        execution_seed=TEST_BASE_SEED,
        actual_gate="C04",
        actual_failure_code="UCM-F006-HIDDEN_PATIENT_CACHE",
        report={
            "head_records": heads,
            "request_records": request_records,
            "invocation_transcript_digest": invocation_digest,
            "findings": [
                {
                    "gate": "C04-update-purity",
                    "verdict": "fail",
                    "failure_code": "UCM-F006-HIDDEN_PATIENT_CACHE",
                }
            ],
            "failure_codes": ["UCM-F006-HIDDEN_PATIENT_CACHE"],
        },
        decision={"invocation_transcript_digest": invocation_digest},
    )
    with pytest.raises(ProtocolViolation, match="outside the code-owned comparison"):
        invalid.finalize()


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


def test_composite_finding_cannot_lend_failure_code_to_actual_gate(
    monkeypatch,
) -> None:
    contracts = list(mutation_evidence._PORTABLE_MUTATION_CONTRACTS)
    row_index = next(
        index
        for index, row in enumerate(contracts)
        if row[0] == "RawHistoryHead"
    )
    row = contracts[row_index]
    # C01 owns only F007.  Mentioning valid lender C02 in the same finding
    # label must not make the code-owned C01/F004 observation decisive.
    contracts[row_index] = (*row[:2], "C01", *row[3:])
    monkeypatch.setattr(
        mutation_evidence, "_PORTABLE_MUTATION_CONTRACTS", tuple(contracts)
    )
    invalid = _invalid_kill_builder(
        actual_gate="C01",
        report={
            "findings": [
                {
                    "gate": "C01/C02-composite-alias",
                    "verdict": "fail",
                    "failure_code": "UCM-F004-HEAD_HISTORY_ACCESS",
                }
            ],
            "failure_codes": ["UCM-F004-HEAD_HISTORY_ACCESS"],
        },
    )
    with pytest.raises(ProtocolViolation, match="directly allow"):
        invalid.finalize()


@pytest.mark.parametrize(
    ("gate", "failure_code"),
    [
        (True, "UCM-F004-HEAD_HISTORY_ACCESS"),
        (1, "UCM-F004-HEAD_HISTORY_ACCESS"),
        ("C02", True),
        ("C02", 1),
    ],
)
def test_direct_gate_failure_membership_is_type_strict(
    gate: object, failure_code: object
) -> None:
    assert not mutation_evidence._direct_gate_allows_failure_code(
        gate, failure_code
    )


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
    no_delta = _invalid_pass_builder(
        subject_id="BehaviorEquivalentSerialization",
        control_class_name="BehaviorEquivalentSerializationControl",
        execution_seed=BEHAVIOR_SEED,
        semantic_probes=("update_consistency",),
        paired_semantic_equivalence=_paired_semantic_evidence(),
        delta=None,
    )
    with pytest.raises(ProtocolViolation, match="mergeable input delta"):
        no_delta.finalize()

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
    (
        "subject_id",
        "control_class_name",
        "row_index",
        "gate",
        "failure_code",
        "semantic_probes",
    ),
    [
        (
            "WarmFutureCache",
            "WarmFutureCacheControl",
            11,
            "C23",
            "UCM-F001-FUTURE_LEAK",
            ("warm_future_old_cut",),
        ),
        (
            "ReplayBatchDivergence",
            "ReplayBatchDivergenceControl",
            12,
            "C22",
            "UCM-F019-UPDATE_INCONSISTENT",
            ("update_consistency",),
        ),
    ],
)
def test_semantic_comparison_kill_requires_a_non_null_mergeable_delta(
    subject_id: str,
    control_class_name: str,
    row_index: int,
    gate: str,
    failure_code: str,
    semantic_probes: tuple[str, ...],
) -> None:
    no_delta = _invalid_kill_builder(
        subject_id=subject_id,
        control_class_name=control_class_name,
        execution_seed=TEST_BASE_SEED + row_index,
        actual_gate=gate,
        actual_failure_code=failure_code,
        semantic_probes=semantic_probes,
        delta=None,
    )
    with pytest.raises(ProtocolViolation, match="mergeable input delta"):
        no_delta.finalize()


@pytest.mark.parametrize("outcome", ["passed", "warm-kill", "update-kill"])
def test_duplicate_event_uid_is_not_a_formally_mergeable_probe_delta(
    outcome: str,
) -> None:
    duplicate = _input_preimage(delta={})
    duplicate["delta"]["events"][0]["event_uid"] = "event-a"
    if outcome == "passed":
        invalid = _invalid_pass_builder(
            delta={},
            input_preimage=duplicate,
        )
    elif outcome == "warm-kill":
        invalid = _invalid_kill_builder(
            subject_id="WarmFutureCache",
            control_class_name="WarmFutureCacheControl",
            execution_seed=TEST_BASE_SEED + 11,
            actual_gate="C23",
            actual_failure_code="UCM-F001-FUTURE_LEAK",
            semantic_probes=("warm_future_old_cut",),
            delta={},
            input_preimage=duplicate,
        )
    else:
        invalid = _invalid_kill_builder(
            subject_id="ReplayBatchDivergence",
            control_class_name="ReplayBatchDivergenceControl",
            execution_seed=TEST_BASE_SEED + 12,
            actual_gate="C22",
            actual_failure_code="UCM-F019-UPDATE_INCONSISTENT",
            semantic_probes=("update_consistency",),
            delta={},
            input_preimage=duplicate,
        )
    with pytest.raises(ProtocolViolation, match="mergeable input delta"):
        invalid.finalize()


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
