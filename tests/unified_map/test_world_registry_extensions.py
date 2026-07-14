from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

import prototype.unified_map.world_registry as world_registry_module
from prototype.unified_map.candidate_protocol import ResultStatus
from prototype.unified_map.canonical import ProtocolViolation, digest_bytes, digest_json
from prototype.unified_map.extensions import (
    ExtensionFirstQueryResult,
    ExtensionVerdict,
    FirstQueryTranscript,
    candidate_tree_digest,
)
from prototype.unified_map.state import StateClass, StatePayload, seal_state
from prototype.unified_map.world_registry import (
    EXTENSION_WORLD_REGISTRY,
    ExtensionInitializationReceipt,
    ExtensionPortableQueryEvidence,
    ExtensionRegistrySession,
    MaterializationStatus,
    materialize_world_split,
)
from prototype.unified_map.worlds.base import WorldSplit


_MARKERS = {
    "W16": (b"obs_2", b"p_result_1_given_C1", b"CHECK-EXTENSION-POST-SEAL-ONLY"),
    "W17": (b'"A2"', b"effect_C1", b"TREATMENT-EXTENSION-POST-SEAL-ONLY"),
}


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def _session(
    tmp_path: Path,
    world_slot: str,
    *,
    count: int | None = 2,
    split: WorldSplit = WorldSplit.SEALED_TEST,
) -> tuple[ExtensionRegistrySession, Path, Path, Path, str]:
    candidate_output = tmp_path / f"candidate-{world_slot.lower()}"
    judge_output = tmp_path / f"judge-{world_slot.lower()}"
    candidate_code = tmp_path / f"code-{world_slot.lower()}"
    candidate_code.mkdir(parents=True)
    (candidate_code / "candidate.py").write_text(
        "def head(state, query):\n    return {'status': 'scope_insufficient'}\n",
        encoding="utf-8",
    )
    scope = digest_json({"world": world_slot, "stage": "S0", "scope": "primary"})
    session = ExtensionRegistrySession(
        world_slot=world_slot,
        split=split,
        generator_seed=160017,
        alias_secret=(world_slot.encode("ascii") * 16)[:32],
        primary_scope_digest=scope,
        candidate_output_root=candidate_output,
        judge_output_root=judge_output,
        episode_limit=count,
    )
    return session, candidate_output, judge_output, candidate_code, scope


def _external_candidate_states(
    session: ExtensionRegistrySession,
    candidate_code: Path,
    scope: str,
    *,
    model: bytes = b"candidate-model-v1",
) -> dict[str, object]:
    bundle_digest = candidate_tree_digest(candidate_code)
    model_digest = digest_bytes(model)
    states = {}
    for row in _jsonl(session.primary.candidate_path):
        history = row["public_history"]
        payload = StatePayload.from_json(
            {
                "as_of_available_at": history["as_of_available_at"],
                "event_count": len(history["events"]),
                "visible_values": [
                    event["payload"].get("value")
                    for event in history["events"]
                    if "value" in event["payload"]
                ],
            },
            schema_version="external-candidate-state/1",
            state_class=StateClass.DYNAMIC_SHARED,
        )
        states[row["record_id"]] = seal_state(
            payload,
            candidate_bundle_digest=bundle_digest,
            model_digest=model_digest,
            scope_digest=scope,
            catalog_digest=history["catalog_digest"],
            as_of_available_at=history["as_of_available_at"],
            operation="initialize",
        )
    return states


def _typed_initialization_receipts(
    session: ExtensionRegistrySession, states: dict[str, object]
) -> dict[str, object]:
    histories = {
        row["record_id"]: row["public_history"]
        for row in _jsonl(session.primary.candidate_path)
    }
    receipts = {}
    for ordinal, (record_id, state) in enumerate(sorted(states.items())):
        record = state.record
        payload = state.candidate_input.payload
        history = histories[record_id]
        receipts[record_id] = ExtensionInitializationReceipt(
            record_id=record_id,
            state_hash=record.state_hash,
            candidate_bundle_digest=record.candidate_bundle_digest,
            model_digest=record.model_digest,
            catalog_digest=record.catalog_digest,
            scope_digest=record.scope_digest,
            request_digest=digest_json(
                {
                    "protocol": "ucm-extension-initialize-request/1",
                    "operation": "initialize",
                    "record_id": record_id,
                    "public_history_digest": digest_json(history),
                    "candidate_bundle_digest": record.candidate_bundle_digest,
                    "model_digest": record.model_digest,
                    "catalog_digest": record.catalog_digest,
                    "scope_digest": record.scope_digest,
                    "as_of_available_at": record.as_of_available_at,
                }
            ),
            response_digest=digest_json(
                {
                    "protocol": "ucm-extension-initialize-response/1",
                    "operation": "initialize",
                    "record_id": record_id,
                    "state_hash": record.state_hash,
                    "state_id": record.state_id,
                    "payload_digest": digest_bytes(payload.payload),
                    "payload_size_bytes": len(payload.payload),
                    "payload_codec": payload.codec,
                    "payload_schema_version": payload.schema_version,
                    "state_class": payload.state_class.value,
                }
            ),
            isolation="fresh-python-process-audit-v1",
            worker_pid=10_000 + ordinal,
        )
    return receipts


@pytest.mark.parametrize("world_slot", ("W16", "W17"))
def test_generic_unrevealed_materializer_is_typed_incomplete_and_never_calls_extension_probes(
    tmp_path: Path, world_slot: str
) -> None:
    result = materialize_world_split(
        world_slot,
        "primary",
        WorldSplit.SEALED_TEST,
        91,
        tmp_path / world_slot,
        alias_secret=b"g" * 32,
        episode_limit=1,
        probe_limit=1,
    )
    assert result.status is MaterializationStatus.INCOMPLETE
    assert result.probe_record_count == 0
    assert any(blocker.interface == "two_stage_extension" for blocker in result.blockers)
    with pytest.raises(ProtocolViolation, match="derived from its blocker set"):
        replace(result, status=MaterializationStatus.COMPLETE)
    object.__setattr__(result, "status", MaterializationStatus.COMPLETE)
    assert result.to_wire()["status"] == MaterializationStatus.INCOMPLETE.value
    public_bytes = result.candidate_path.read_bytes()
    for marker in _MARKERS[world_slot]:
        assert marker not in public_bytes


@pytest.mark.parametrize("world_slot", ("W16", "W17"))
@pytest.mark.parametrize("split", (WorldSplit.TRAIN, WorldSplit.VALIDATION))
def test_generic_full_non_test_extension_split_cannot_masquerade_as_complete(
    tmp_path: Path, world_slot: str, split: WorldSplit
) -> None:
    result = materialize_world_split(
        world_slot,
        "primary",
        split,
        92,
        tmp_path / f"{world_slot}-{split.value}",
        alias_secret=b"n" * 32,
    )
    assert result.population_count == (
        4096 if split is WorldSplit.TRAIN else 1024
    )
    assert result.status is MaterializationStatus.INCOMPLETE
    assert result.probe_record_count == 0
    assert any(blocker.interface == "two_stage_extension" for blocker in result.blockers)
    assert not any(blocker.interface == "split_size" for blocker in result.blockers)


def test_generic_materialization_without_blockers_remains_complete_and_derived(
    tmp_path: Path,
) -> None:
    result = materialize_world_split(
        "W01",
        "primary",
        WorldSplit.TRAIN,
        101,
        tmp_path / "w01-train",
        alias_secret=b"c" * 32,
    )
    assert result.blockers == ()
    assert result.status is MaterializationStatus.COMPLETE
    assert result.to_wire()["status"] == MaterializationStatus.COMPLETE.value
    with pytest.raises(ProtocolViolation, match="derived from its blocker set"):
        replace(result, status=MaterializationStatus.INCOMPLETE)
    object.__setattr__(result, "status", MaterializationStatus.INCOMPLETE)
    assert result.to_wire()["status"] == MaterializationStatus.COMPLETE.value


@pytest.mark.parametrize("split", (WorldSplit.TRAIN, WorldSplit.VALIDATION))
def test_extension_session_never_invokes_sealed_probe_fixture_for_non_test_split(
    tmp_path: Path, split: WorldSplit, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fixture = world_registry_module._instantiate_extension_fixture

    def tiny_fixture(world_slot: str):
        panel, custody, world = real_fixture(world_slot)
        # Keep this sequencing test small while preserving the exact session
        # code path and a non-truncated declared S0 cohort.
        world.population_size = lambda requested_split: 1
        panel = replace(
            panel,
            split_sizes=tuple((item, 1) for item in WorldSplit),
        )
        return panel, custody, world

    monkeypatch.setattr(
        world_registry_module, "_instantiate_extension_fixture", tiny_fixture
    )
    session, _, _, candidate_code, scope = _session(
        tmp_path / split.value, "W16", count=None, split=split
    )
    states = _external_candidate_states(session, candidate_code, scope)
    seal = session.seal_primary(
        candidate_root=candidate_code,
        model_artifact=b"candidate-model-v1",
        states_by_record_id=states,
        initialization_receipts_by_record_id=_typed_initialization_receipts(
            session, states
        ),
    )
    assert seal.structural_status is MaterializationStatus.COMPLETE
    session.reveal_extension_catalog()
    record_id = next(iter(states))
    session.first_query_portable_callback(
        record_id=record_id,
        query={"kind": "non-test-extension-query"},
        invoke=lambda request: ExtensionFirstQueryResult(
            ResultStatus.SCOPE_INSUFFICIENT
        ),
    )
    activated = session._activated_world
    assert activated is not None
    monkeypatch.setattr(
        activated,
        "pre_result_alias_pair",
        lambda seed: pytest.fail("SEALED_TEST probe called for non-test split"),
    )
    monkeypatch.setattr(
        activated,
        "extension_result_pair",
        lambda seed: pytest.fail("SEALED_TEST probe called for non-test split"),
    )
    result = session.materialize_extension(episode_limit=1)
    assert result.status is MaterializationStatus.INCOMPLETE
    assert result.probe_record_count == 0
    manifest = json.loads(result.candidate_manifest_path.read_text("utf-8"))
    assert manifest["declared_extension_pair_count"] == 0


@pytest.mark.parametrize("world_slot", tuple(EXTENSION_WORLD_REGISTRY))
def test_primary_session_exposes_only_opaque_commitment_and_keeps_roots_disjoint(
    tmp_path: Path, world_slot: str
) -> None:
    session, candidate_output, judge_output, _, _ = _session(tmp_path, world_slot)
    assert candidate_output.resolve() not in judge_output.resolve().parents
    assert judge_output.resolve() not in candidate_output.resolve().parents
    assert session.primary.status is MaterializationStatus.INCOMPLETE
    assert {path.name for path in candidate_output.iterdir()} == {
        "extension-commitment.json",
        "primary-public.jsonl",
    }
    assert {path.name for path in judge_output.iterdir()} == {
        "primary-materialization-status.json",
        "primary-private.jsonl",
    }
    candidate_wire = b"".join(path.read_bytes() for path in candidate_output.iterdir())
    assert b"world_id" not in candidate_wire
    assert b"generator_seed" not in candidate_wire
    assert b"hidden_state" not in candidate_wire
    assert b"oracle_anchor" not in candidate_wire
    assert b"encryption_key" not in candidate_wire
    assert b"hiding_nonce" not in candidate_wire
    for marker in _MARKERS[world_slot]:
        assert marker not in candidate_wire

    early = session.materialize_extension(episode_limit=1)
    assert early.status is MaterializationStatus.INCOMPLETE
    assert early.candidate_path is None
    assert not (candidate_output / "extension-public.jsonl").exists()


def test_extension_session_rejects_nested_candidate_and_judge_roots(tmp_path: Path) -> None:
    with pytest.raises(ProtocolViolation, match="physically disjoint"):
        ExtensionRegistrySession(
            world_slot="W16",
            split=WorldSplit.SEALED_TEST,
            generator_seed=1,
            alias_secret=b"x" * 32,
            primary_scope_digest=digest_json({"scope": "S0"}),
            candidate_output_root=tmp_path / "shared",
            judge_output_root=tmp_path / "shared" / "judge",
            episode_limit=1,
        )


def test_extension_global_status_is_constructor_and_serialization_fail_closed(
    tmp_path: Path,
) -> None:
    session, _, _, candidate_code, _ = _session(tmp_path, "W16")
    primary = session.primary
    seal = session.seal_primary(
        candidate_root=candidate_code,
        model_artifact=b"candidate-model-v1",
        states_by_record_id={},
    )
    materialization = session.materialize_extension()
    transcript = FirstQueryTranscript(
        request_digest=digest_json({"request": 1}),
        primary_state_hash=digest_json({"state": 1}),
        state_snapshot_before=digest_json({"snapshot": 1}),
        state_snapshot_after=digest_json({"snapshot": 1}),
        status=ResultStatus.SCOPE_INSUFFICIENT,
        verdict=ExtensionVerdict.HONEST_LIMIT,
        max_numeric_error=None,
    )
    portable = ExtensionPortableQueryEvidence(
        MaterializationStatus.INCOMPLETE,
        "r-status-hardening",
        transcript,
    )
    artifacts = (primary, seal, portable, materialization)
    for artifact in artifacts:
        with pytest.raises(ProtocolViolation, match="INCOMPLETE|COMPLETE"):
            replace(artifact, status=MaterializationStatus.COMPLETE)

    # Frozen dataclasses can still be corrupted through object.__setattr__ by
    # hostile in-process code.  Wire serialization must never trust that field.
    for artifact in artifacts:
        object.__setattr__(artifact, "status", MaterializationStatus.COMPLETE)
        assert artifact.to_wire()["status"] == MaterializationStatus.INCOMPLETE.value

    object.__setattr__(portable, "query_contract_verified", True)
    object.__setattr__(portable, "state_only_closure_verified", True)
    object.__setattr__(portable, "execution_assurance", "forged-fresh-process")
    portable_wire = portable.to_wire()
    assert portable_wire["query_contract_verified"] is False
    assert portable_wire["state_only_closure_verified"] is False
    assert portable_wire["execution_assurance"] == "portable-callback"

    object.__setattr__(materialization, "extension_evaluation_complete", True)
    object.__setattr__(materialization, "query_contract_verified", True)
    object.__setattr__(materialization, "execution_assurance", "forged-isolated")
    materialization_wire = materialization.to_wire()
    assert materialization_wire["extension_evaluation_complete"] is False
    assert materialization_wire["query_contract_verified"] is False
    assert materialization_wire["execution_assurance"] == "portable-callback"
    for wire in (primary.to_wire(), materialization_wire):
        assert wire["freeze_grade_evidence"] is False
        assert wire["benchmark_freeze_eligible"] is False


def test_exact_external_seal_then_state_only_wire_remains_non_freeze_grade(
    tmp_path: Path,
) -> None:
    world_slot = "W17"
    session, candidate_output, judge_output, candidate_code, scope = _session(
        tmp_path, world_slot, count=None
    )
    primary_candidate_digest = session.primary.candidate_digest
    primary_judge_digest = session.primary.judge_digest
    model = b"candidate-model-v1"
    states = _external_candidate_states(session, candidate_code, scope, model=model)
    seal = session.seal_primary(
        candidate_root=candidate_code,
        model_artifact=model,
        states_by_record_id=states,
        initialization_receipts_by_record_id=_typed_initialization_receipts(
            session, states
        ),
    )
    assert seal.status is MaterializationStatus.INCOMPLETE
    assert seal.structural_status is MaterializationStatus.COMPLETE
    assert seal.blockers[0].interface == "initialization_receipt_provenance"
    assert {binding.record_id for binding in seal.bindings} == set(states)
    assert all(binding.scope_digest == scope for binding in seal.bindings)
    for binding in seal.bindings:
        state = states[binding.record_id]
        assert binding.candidate_bundle_digest == state.record.candidate_bundle_digest
        assert binding.model_digest == state.record.model_digest
        assert binding.catalog_digest == state.record.catalog_digest
        assert bytes.fromhex(binding.payload_hex) == state.candidate_input.payload.payload

    with pytest.raises(ProtocolViolation, match="post-seal reveal"):
        session.first_query_portable_callback(
            record_id=sorted(states)[0],
            query={"kind": "extension_rollout", "horizon": 4},
            invoke=lambda request: ExtensionFirstQueryResult(
                ResultStatus.SCOPE_INSUFFICIENT
            ),
        )

    reveal = session.reveal_extension_catalog()
    assert reveal.primary_binding_set_digest == seal.binding_set_digest
    assert (candidate_output / "extension-reveal.json").exists()
    reveal_wire = json.loads((candidate_output / "extension-reveal.json").read_text("utf-8"))
    assert "public_history" not in json.dumps(reveal_wire, sort_keys=True).lower()
    assert "patient" not in json.dumps(reveal_wire, sort_keys=True).lower()
    assert not (candidate_output / "extension-public.jsonl").exists()
    before_first_query = session.materialize_extension(episode_limit=3, probe_limit=2)
    assert before_first_query.status is MaterializationStatus.INCOMPLETE
    assert before_first_query.blockers[0].interface == "first_query_cohort"
    assert not (candidate_output / "extension-public.jsonl").exists()

    observed_wires: list[dict[str, object]] = []

    def candidate_head(request):
        assert not (candidate_output / "extension-public.jsonl").exists()
        # Deliberately violate process closure: a portable in-process callback
        # can read judge-private S0 files through its Python closure.  The raw
        # outcome may look numerically correct, but must never become
        # freeze-grade state-only evidence.
        assert (judge_output / "primary-private.jsonl").read_bytes()
        wire = request.to_wire()
        observed_wires.append(wire)
        encoded = json.dumps(wire, sort_keys=True).lower()
        assert "history" not in encoded
        assert "events" not in encoded
        assert "generator_seed" not in encoded
        assert "hidden_state" not in encoded
        assert set(wire) == {
            "protocol",
            "state",
            "state_hash",
            "extension_pack_digest",
            "extension_pack",
            "query",
        }
        return ExtensionFirstQueryResult(ResultStatus.OK, {"value": 1.0})

    for ordinal, record_id in enumerate(sorted(states)):
        evidence = session.first_query_portable_callback(
            record_id=record_id,
            query={"kind": "caller-chosen-arbitrary-query", "horizon": 999},
            invoke=candidate_head,
            expected_prediction=None if ordinal == 0 else {"value": 1.0},
        )
        assert evidence.status is MaterializationStatus.INCOMPLETE
        assert evidence.query_contract_verified is False
        assert evidence.state_only_closure_verified is False
        transcript = evidence.transcript
        assert transcript.verdict is (
            ExtensionVerdict.UNSCORED_OK if ordinal == 0 else ExtensionVerdict.PASS
        )
        assert transcript.primary_state_hash == states[record_id].record.state_hash
        assert transcript.state_snapshot_before == transcript.state_snapshot_after
    assert len(observed_wires) == len(states)
    assert not (candidate_output / "extension-public.jsonl").exists()
    first_record = sorted(states)[0]
    first_query_rows = _jsonl(judge_output / "first-query-private.jsonl")
    assert len(first_query_rows) == len(states)
    first_raw = next(row for row in first_query_rows if row["record_id"] == first_record)
    assert first_raw["execution_assurance"] == "portable-callback"
    assert first_raw["query_contract_verified"] is False
    assert first_raw["state_only_closure_verified"] is False
    assert first_raw["freeze_grade_evidence"] is False
    assert first_raw["outcome"]["expected_prediction_supplied"] is False
    assert first_raw["outcome"]["verdict"] == "UNSCORED_OK"

    extension = session.materialize_extension()
    # Corpus/order can be complete while evaluation evidence remains typed
    # INCOMPLETE because query contract and process isolation are not proven.
    assert extension.status is MaterializationStatus.INCOMPLETE
    assert extension.corpus_status is MaterializationStatus.COMPLETE
    assert extension.evidence_scope == "ordering-and-corpus-only"
    assert extension.ordering_complete is True
    assert extension.extension_evaluation_complete is False
    assert extension.query_contract_verified is False
    assert extension.execution_assurance == "portable-callback"
    assert any(blocker.interface == "first_query_contract" for blocker in extension.blockers)
    assert any(
        blocker.interface == "first_query_execution_assurance"
        for blocker in extension.blockers
    )
    assert any(
        blocker.interface == "initialization_receipt_provenance"
        for blocker in extension.blockers
    )
    assert any(
        blocker.interface == "extension_source_hiding"
        for blocker in extension.blockers
    )
    assert any(
        blocker.interface == "atomic_extension_publish"
        for blocker in extension.blockers
    )
    assert extension.population_count == 512
    assert extension.probe_record_count == 512
    assert extension.candidate_path == candidate_output / "extension-public.jsonl"
    assert extension.judge_path == judge_output / "extension-private.jsonl"
    assert session.primary.candidate_digest == primary_candidate_digest
    assert session.primary.judge_digest == primary_judge_digest
    assert digest_bytes(session.primary.candidate_path.read_bytes()) == primary_candidate_digest
    assert digest_bytes(session.primary.judge_path.read_bytes()) == primary_judge_digest

    public = _jsonl(extension.candidate_path)
    private = _jsonl(extension.judge_path)
    assert [row["record_id"] for row in public] == [row["record_id"] for row in private]
    for candidate_row, judge_row in zip(public, private, strict=True):
        assert candidate_row["scope_digest"] == judge_row["record_scope_digest"]
        assert digest_json(candidate_row["public_history"]) == judge_row[
            "public_history_digest"
        ]
        assert "hidden_state_at_cut" not in candidate_row
        assert "oracle_anchor" not in candidate_row
        assert "generator_seed" not in candidate_row
    manifest = json.loads(extension.candidate_manifest_path.read_text("utf-8"))
    assert "world_id" not in manifest
    assert "encryption_key_hex" not in manifest
    assert "hiding_nonce_hex" not in manifest
    assert manifest["primary_binding_set_digest"] == seal.binding_set_digest
    assert manifest["extension_scope_digest"] == extension.extension_scope_digest
    assert manifest["evidence_scope"] == "ordering-and-corpus-only"
    assert manifest["ordering_complete"] is True
    assert manifest["query_contract_verified"] is False
    assert manifest["state_only_closure_verified"] is False
    assert manifest["extension_evaluation_complete"] is False
    assert any(
        marker in (candidate_output / "extension-reveal.json").read_bytes()
        for marker in _MARKERS[world_slot]
    )


def test_truncated_primary_is_typed_incomplete_and_can_never_reveal_or_publish_s1(
    tmp_path: Path,
) -> None:
    first, candidate_output, _, candidate_code, scope = _session(
        tmp_path / "missing", "W16"
    )
    states = _external_candidate_states(first, candidate_code, scope)
    states.pop(next(iter(states)))
    missing = first.seal_primary(
        candidate_root=candidate_code,
        model_artifact=b"candidate-model-v1",
        states_by_record_id=states,
    )
    assert missing.status is MaterializationStatus.INCOMPLETE
    assert missing.blockers[0].interface == "primary_corpus"
    with pytest.raises(ProtocolViolation, match="requires exact candidate"):
        first.reveal_extension_catalog()
    blocked = first.materialize_extension(episode_limit=1)
    assert blocked.status is MaterializationStatus.INCOMPLETE
    assert not (candidate_output / "extension-public.jsonl").exists()

    assert not (candidate_output / "extension-reveal.json").exists()


def test_full_primary_without_external_initialize_receipts_cannot_seal_or_reveal(
    tmp_path: Path,
) -> None:
    session, candidate_output, _, candidate_code, scope = _session(
        tmp_path, "W16", count=None
    )
    states = _external_candidate_states(session, candidate_code, scope)
    result = session.seal_primary(
        candidate_root=candidate_code,
        model_artifact=b"candidate-model-v1",
        states_by_record_id=states,
    )
    assert result.status is MaterializationStatus.INCOMPLETE
    assert result.structural_status is MaterializationStatus.INCOMPLETE
    assert result.blockers[0].interface == "initialization_execution_receipt"
    with pytest.raises(ProtocolViolation, match="requires exact candidate"):
        session.reveal_extension_catalog()
    assert not (candidate_output / "extension-reveal.json").exists()
    assert not (candidate_output / "extension-public.jsonl").exists()


@pytest.mark.parametrize(
    ("attack", "detail"),
    (
        ("state_hash", "state hash"),
        ("payload_size", "payload_size"),
        ("receipt_request", "request digest"),
    ),
)
def test_forged_initialize_state_or_echo_receipt_never_structurally_seals(
    tmp_path: Path, attack: str, detail: str
) -> None:
    session, candidate_output, _, candidate_code, scope = _session(
        tmp_path / attack, "W16", count=None
    )
    states = _external_candidate_states(session, candidate_code, scope)
    target = sorted(states)[0]
    if attack == "state_hash":
        fake_hash = "sha256:" + "0" * 64
        forged_record = replace(
            states[target].record,
            state_hash=fake_hash,
            state_id="ucm-state:" + fake_hash[7:23],
        )
        states[target] = replace(states[target], record=forged_record)
    elif attack == "payload_size":
        forged_record = replace(
            states[target].record,
            payload_size_bytes=states[target].record.payload_size_bytes + 1,
        )
        states[target] = replace(states[target], record=forged_record)
    receipts = _typed_initialization_receipts(session, states)
    if attack == "receipt_request":
        receipts[target] = replace(
            receipts[target], request_digest=digest_json({"forged": True})
        )

    result = session.seal_primary(
        candidate_root=candidate_code,
        model_artifact=b"candidate-model-v1",
        states_by_record_id=states,
        initialization_receipts_by_record_id=receipts,
    )
    assert result.status is MaterializationStatus.INCOMPLETE
    assert result.structural_status is MaterializationStatus.INCOMPLETE
    assert detail in result.blockers[0].detail
    with pytest.raises(ProtocolViolation, match="requires exact candidate"):
        session.reveal_extension_catalog()
    assert not (candidate_output / "extension-reveal.json").exists()


def test_pre_reveal_s0_closure_rehash_blocks_all_primary_artifact_tamper(
    tmp_path: Path,
) -> None:
    session, candidate_output, judge_output, candidate_code, scope = _session(
        tmp_path, "W17", count=None
    )
    states = _external_candidate_states(session, candidate_code, scope)
    seal = session.seal_primary(
        candidate_root=candidate_code,
        model_artifact=b"candidate-model-v1",
        states_by_record_id=states,
        initialization_receipts_by_record_id=_typed_initialization_receipts(
            session, states
        ),
    )
    assert seal.structural_status is MaterializationStatus.COMPLETE
    paths = (
        session.primary.candidate_path,
        session.primary.judge_path,
        session.primary.candidate_commitment_path,
        judge_output / "primary-materialization-status.json",
        judge_output / "primary-seal-result.json",
    )
    for path in paths:
        original = path.read_bytes()
        path.write_bytes(original + b"tamper-before-reveal")
        with pytest.raises(ProtocolViolation, match="pre-reveal.*changed"):
            session.reveal_extension_catalog()
        assert not (candidate_output / "extension-reveal.json").exists()
        assert not (candidate_output / "extension-public.jsonl").exists()
        path.write_bytes(original)

    # Failed closure audits do not consume the append-only reveal slot.
    session.reveal_extension_catalog()
    assert (candidate_output / "extension-reveal.json").is_file()


def test_post_query_closure_rehash_blocks_every_primary_artifact_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, candidate_output, judge_output, candidate_code, scope = _session(
        tmp_path, "W16", count=None
    )
    states = _external_candidate_states(session, candidate_code, scope)
    seal = session.seal_primary(
        candidate_root=candidate_code,
        model_artifact=b"candidate-model-v1",
        states_by_record_id=states,
        initialization_receipts_by_record_id=_typed_initialization_receipts(
            session, states
        ),
    )
    assert seal.structural_status is MaterializationStatus.COMPLETE
    session.reveal_extension_catalog()
    for record_id in sorted(states):
        session.first_query_portable_callback(
            record_id=record_id,
            query={"kind": "arbitrary"},
            invoke=lambda request: ExtensionFirstQueryResult(
                ResultStatus.SCOPE_INSUFFICIENT
            ),
        )

    paths = (
        candidate_code / "candidate.py",
        session.primary.candidate_path,
        session.primary.candidate_commitment_path,
        session.primary.judge_path,
        judge_output / "primary-seal-result.json",
        candidate_output / "extension-reveal.json",
    )
    for path in paths:
        original = path.read_bytes()
        path.write_bytes(original + b"tamper")
        with pytest.raises(ProtocolViolation, match="changed"):
            session.materialize_extension()
        assert not (candidate_output / "extension-public.jsonl").exists()
        path.write_bytes(original)
    first_query_path = judge_output / "first-query-private.jsonl"
    original = first_query_path.read_bytes()
    first_query_path.write_bytes(original + b"tamper")
    with pytest.raises(ProtocolViolation, match="first-query judge receipt changed"):
        session.materialize_extension()
    assert not (candidate_output / "extension-public.jsonl").exists()
    first_query_path.write_bytes(original)

    world = session._activated_world
    assert world is not None
    extension_public = candidate_output / "extension-public.jsonl"
    extension_private = judge_output / "extension-private.jsonl"
    with monkeypatch.context() as patch:
        patch.setattr(
            world,
            "generate_extension_episode",
            lambda split, seed, index: world.generate_episode(
                WorldSplit.TRAIN, seed, index
            ),
        )
        with pytest.raises(ProtocolViolation, match="population episode contradicts"):
            session.materialize_extension(episode_limit=1, probe_limit=0)
        assert extension_public.read_bytes() == b""
        assert extension_private.read_bytes() == b""
    extension_public.unlink()
    extension_private.unlink()

    with monkeypatch.context() as patch:
        patch.setattr(
            world,
            "pre_result_alias_pair",
            lambda seed: (
                world.generate_episode(WorldSplit.TRAIN, seed, 0),
                world.generate_episode(WorldSplit.TRAIN, seed, 1),
            ),
        )
        with pytest.raises(ProtocolViolation, match="probe episode contradicts"):
            session.materialize_extension(episode_limit=0, probe_limit=1)
        assert extension_public.read_bytes() == b""
        assert extension_private.read_bytes() == b""


def test_preseal_plaintext_in_candidate_bundle_and_postseal_tamper_both_fail_closed(
    tmp_path: Path,
) -> None:
    leaked, candidate_output, _, candidate_code, scope = _session(
        tmp_path / "leak", "W16", count=None
    )
    (candidate_code / "leak.txt").write_bytes(b"p_result_1_given_C1")
    states = _external_candidate_states(leaked, candidate_code, scope)
    rejected = leaked.seal_primary(
        candidate_root=candidate_code,
        model_artifact=b"candidate-model-v1",
        states_by_record_id=states,
        initialization_receipts_by_record_id=_typed_initialization_receipts(
            leaked, states
        ),
    )
    assert rejected.status is MaterializationStatus.INCOMPLETE
    assert "clear extension marker" in rejected.blockers[0].detail
    assert not (candidate_output / "extension-public.jsonl").exists()

    tampered, _, _, candidate_code, scope = _session(
        tmp_path / "tamper", "W17", count=None
    )
    states = _external_candidate_states(tampered, candidate_code, scope)
    assert (
        tampered.seal_primary(
            candidate_root=candidate_code,
            model_artifact=b"candidate-model-v1",
            states_by_record_id=states,
            initialization_receipts_by_record_id=_typed_initialization_receipts(
                tampered, states
            ),
        ).structural_status
        is MaterializationStatus.COMPLETE
    )
    (candidate_code / "candidate.py").write_text("# changed after seal\n", encoding="utf-8")
    with pytest.raises(ProtocolViolation, match="candidate bundle changed"):
        tampered.reveal_extension_catalog()


def test_measured_history_migration_is_available_only_after_scope_insufficient(
    tmp_path: Path,
) -> None:
    session, _, judge_output, candidate_code, scope = _session(
        tmp_path, "W17", count=None
    )
    states = _external_candidate_states(session, candidate_code, scope)
    assert (
        session.seal_primary(
            candidate_root=candidate_code,
            model_artifact=b"candidate-model-v1",
            states_by_record_id=states,
            initialization_receipts_by_record_id=_typed_initialization_receipts(
                session, states
            ),
        ).structural_status
        is MaterializationStatus.COMPLETE
    )
    session.reveal_extension_catalog()
    record_id = next(iter(states))

    def migrate(history, reveal):
        return StatePayload.from_json(
            {"history_digest": history.digest, "extension_pack": reveal.pack_digest},
            schema_version="explicit-migration/1",
            state_class=StateClass.DYNAMIC_SHARED,
        )

    with pytest.raises(ProtocolViolation, match="only after scope_insufficient"):
        session.authorize_migration(record_id=record_id, migrate=migrate)

    session.first_query_portable_callback(
        record_id=record_id,
        query={"kind": "rollout", "action_id": "A2", "horizon": 4},
        invoke=lambda request: ExtensionFirstQueryResult(
            ResultStatus.SCOPE_INSUFFICIENT
        ),
    )
    materialized = session.materialize_extension(episode_limit=1, probe_limit=0)
    assert materialized.status is MaterializationStatus.INCOMPLETE
    assert materialized.population_count == 0
    assert materialized.ordering_complete is False
    assert materialized.blockers[0].interface == "first_query_cohort"
    outcome = session.authorize_migration(
        record_id=record_id,
        migrate=migrate,
        training_examples=(b"row-1", b"row-2"),
    )
    assert outcome.migrated_state.record.operation == "replay"
    assert outcome.migrated_state.record.parent_state_hash == states[record_id].record.state_hash
    assert outcome.cost.replay_history_bytes > 0
    assert outcome.cost.training_examples == 2
    assert outcome.cost.training_bytes == 10
    assert outcome.s0_snapshot_before == outcome.s0_snapshot_after
    assert (judge_output / f"migration-{record_id}.json").exists()
