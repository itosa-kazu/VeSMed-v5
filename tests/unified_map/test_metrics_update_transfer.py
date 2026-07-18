from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_bytes
from prototype.unified_map.metrics_update_transfer import (
    EvaluationGrain,
    InformationKind,
    NovelReadoutCard,
    NovelReadoutEvaluation,
    NovelReadoutScorePoint,
    NoveltyRelation,
    OracleScoreChangeObservation,
    OriginalYMembershipBasis,
    QueryOrderObservation,
    ReadoutInput,
    ReadoutKind,
    RuntimeStateIdentity,
    ScoreDirection,
    Task,
    UpdateIdentityObservation,
    sealed_state_novel_readout_transfer,
    update_consistency,
)
from prototype.unified_map.state import StateClass, StatePayload, seal_state
from prototype.unified_map.true_state_probe import W01TrueStateUpperBoundProbe
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w01 import W01World


def _digest(label: str) -> str:
    return digest_bytes(label.encode("utf-8"))


def _grain(
    case_id: str,
    *,
    task: Task = Task.RECURSIVE_UPDATE,
    horizon: str = "horizon-na",
    policy: str = "policy-na",
) -> EvaluationGrain:
    return EvaluationGrain(
        world_id="W01",
        case_id=case_id,
        cut_id="cut-02",
        task=task,
        replicate_id="replicate-003",
        horizon_id=horizon,
        policy_id=policy,
    )


def _runtime_state_from_json(
    representation: object,
    *,
    scope: str = "m15-scope",
) -> RuntimeStateIdentity:
    payload = StatePayload.from_json(
        representation,
        schema_version="ucm-m15-test-state/1",
        state_class=StateClass.DYNAMIC_SHARED,
    )
    return RuntimeStateIdentity.from_sealed_state(
        seal_state(
            payload,
            candidate_bundle_digest=_digest("m15-candidate-bundle"),
            model_digest=_digest("m15-model"),
            scope_digest=_digest(scope),
            catalog_digest=_digest("m15-catalog"),
            as_of_available_at=2,
            operation="initialize",
            state_instance_id="m15-test-instance",
        )
    )


def _update(
    case_id: str,
    *,
    replay_value: object | None = None,
    batch: dict | None = None,
    sequential: dict | None = None,
) -> UpdateIdentityObservation:
    incremental_value = {"z": 1}
    replay = incremental_value if replay_value is None else replay_value
    return UpdateIdentityObservation(
        grain=_grain(case_id),
        information_kind=InformationKind.INFORMATIVE_OBSERVATION,
        incremental_state=_runtime_state_from_json(incremental_value),
        replay_state=_runtime_state_from_json(replay),
        batch_behavior={"diagnosis": [0.2, 0.8]} if batch is None else batch,
        sequential_behavior=(
            {"diagnosis": [0.2, 0.8]} if sequential is None else sequential
        ),
    )


def _query(case_id: str, *, impure: bool = False) -> QueryOrderObservation:
    start = _runtime_state_from_json({"case": case_id})
    mutated = _runtime_state_from_json({"mutated": True})
    return QueryOrderObservation(
        grain=_grain(case_id),
        first_order=("diagnosis", "rollout"),
        second_order=("rollout", "diagnosis"),
        first_pre_state=start,
        first_post_state=mutated if impure else start,
        second_pre_state=start,
        second_post_state=start,
        first_outputs_by_query={"diagnosis": [0.7, 0.3], "rollout": {"y": 2}},
        # Reversed insertion order is semantically and canonically identical.
        second_outputs_by_query={"rollout": {"y": 2}, "diagnosis": [0.7, 0.3]},
    )


def _score(
    case_id: str,
    *,
    information: InformationKind,
    readout: ReadoutKind,
    before: int | float,
    after: int | float,
    task: Task,
) -> OracleScoreChangeObservation:
    return OracleScoreChangeObservation(
        grain=_grain(case_id, task=task, horizon="h-4", policy="policy-A"),
        information_kind=information,
        readout_kind=readout,
        score_direction=ScoreDirection.MINIMIZE,
        candidate_before=before,
        candidate_after=after,
        oracle_before=0,
        oracle_after=0,
    )


def _m15_fixture() -> tuple[
    tuple[UpdateIdentityObservation, ...],
    tuple[QueryOrderObservation, ...],
    tuple[OracleScoreChangeObservation, ...],
]:
    updates = (
        _update("case-a"),
        _update(
            "case-b",
            replay_value={"z": 2},
            sequential={"diagnosis": [0.3, 0.7]},
        ),
    )
    queries = (_query("case-a"), _query("case-b", impure=True))
    scores = (
        _score(
            "case-a",
            information=InformationKind.INFORMATIVE_OBSERVATION,
            readout=ReadoutKind.DIAGNOSIS,
            before=2,
            after=1,
            task=Task.DIAGNOSIS,
        ),
        _score(
            "case-b",
            information=InformationKind.INFORMATIVE_OBSERVATION,
            readout=ReadoutKind.DIAGNOSIS,
            before=1,
            after=2,
            task=Task.DIAGNOSIS,
        ),
        _score(
            "case-c",
            information=InformationKind.INFORMATIVE_TREATMENT_RESPONSE,
            readout=ReadoutKind.ROLLOUT,
            before=4,
            after=1,
            task=Task.INTERVENTION_FORECAST,
        ),
        _score(
            "case-d",
            information=InformationKind.NO_INFORMATION_CONTROL,
            readout=ReadoutKind.ROLLOUT,
            before=1,
            after=5,
            task=Task.NATURAL_FORECAST,
        ),
    )
    return updates, queries, scores


def test_m15_exact_rates_hard_facts_and_manual_directional_arithmetic() -> None:
    result = update_consistency(*_m15_fixture())
    wire = result.to_wire()

    assert wire["benchmark_status"] == "PRE-FREEZE"
    assert wire["evidence_qualification"] == "runtime_only"
    assert wire["authority_claim"] == "not_claimed"
    assert wire["freeze_authority_status"] == "not_claimed"
    assert wire["cross_metric_aggregate_score"] == "forbidden"
    assert wire["cross_submetric_aggregate_score"] == "forbidden"
    assert wire["metric_target_closure"] == "not_implemented_unbound"
    assert wire["input_evidence"] == "caller_asserted_unbound"
    assert wire["expected_registry_binding"] == "absent"
    assert wire["coverage_complete"] is False
    assert wire["hard_gate_evidence_eligible"] is False
    assert wire["coverage_diagnostics"]["coverage_mismatch"] is True
    assert wire["coverage_diagnostics"]["provided_grain_sets_aligned"] is False

    identity = wire["incremental_replay_exact_identity"]
    assert identity["exact_match_numerator"] == 1
    assert identity["exact_denominator_rows"] == 2
    assert identity["exact_match_rate"] == 0.5
    assert identity["rows"][1]["hash_match"] is False
    assert identity["rows"][1]["payload_bytes_match"] is False
    assert identity["rate_qualification"] == "provided_exposure_only"
    assert identity["hard_gate_evidence_eligible"] is False
    assert len(identity["provided_exposure_mismatch_facts"]) == 1
    identity_fact = identity["provided_exposure_mismatch_facts"][0]
    assert identity_fact["hard_fact"] == "incremental_replay_state_mismatch"
    assert identity_fact["case_id"] == "case-b"
    assert identity_fact["hash_match"] is False
    assert identity_fact["payload_bytes_match"] is False
    assert (
        identity_fact["incremental_payload_bytes_digest"]
        != identity_fact["replay_payload_bytes_digest"]
    )
    assert identity_fact["incremental_state_hash_preimage"]["state_class"] == (
        "dynamic_shared_state"
    )

    behavioral = wire["batch_sequential_behavioral_identity"]
    assert behavioral["behavioral_match_numerator"] == 1
    assert behavioral["exact_denominator_rows"] == 2
    assert behavioral["behavioral_match_rate"] == 0.5
    assert len(behavioral["provided_exposure_mismatch_facts"]) == 1

    purity = wire["query_order_purity"]
    assert purity["pure_numerator"] == 1
    assert purity["exact_denominator_rows"] == 2
    assert purity["purity_rate"] == 0.5
    assert purity["rows"][0]["outputs_by_query_match"] is True
    assert len(purity["provided_exposure_mismatch_facts"]) == 1

    groups = wire["oracle_relative_directional_changes"]
    informative_diagnosis = next(
        group
        for group in groups
        if group["information_kind"] == "informative_observation"
    )
    assert informative_diagnosis["exact_denominator_rows"] == 2
    assert informative_diagnosis["toward_oracle_count"] == 1
    assert informative_diagnosis["away_from_oracle_count"] == 1
    assert informative_diagnosis["mean_oracle_relative_gap_improvement"] == 0.0
    assert informative_diagnosis["aggregate_movement"] == "unchanged"
    assert all(
        row["individual_improvement_gate"] == "not_applied"
        for row in informative_diagnosis["rows"]
    )
    no_information = next(
        group
        for group in groups
        if group["information_kind"] == "no_information_control"
    )
    assert no_information["mean_oracle_relative_gap_improvement"] == -4.0
    assert no_information["improvement_requirement"] == "none"
    assert no_information["rows"][0]["individual_improvement_gate"] == "none"

    # Every decisive row retains the full world/case/cut/task/replicate/horizon/policy grain.
    for section_name in (
        "incremental_replay_exact_identity",
        "batch_sequential_behavioral_identity",
        "query_order_purity",
    ):
        for row in wire[section_name]["rows"]:
            assert {
                "world_id",
                "case_id",
                "cut_id",
                "task",
                "replicate_id",
                "horizon_id",
                "policy_id",
            } <= set(row)


def test_m15_is_deterministic_under_input_and_object_key_permutation() -> None:
    updates, queries, scores = _m15_fixture()
    permuted_update = UpdateIdentityObservation(
        grain=updates[0].grain,
        information_kind=updates[0].information_kind,
        incremental_state=updates[0].incremental_state,
        replay_state=updates[0].replay_state,
        batch_behavior={"diagnosis": [0.2, 0.8]},
        sequential_behavior={"diagnosis": [0.2, 0.8]},
    )
    permuted_updates = (updates[1], permuted_update)
    assert (
        update_consistency(updates, queries, scores).canonical_bytes
        == update_consistency(
            permuted_updates, tuple(reversed(queries)), tuple(reversed(scores))
        ).canonical_bytes
    )


def test_m15_accepts_a_real_w01_runtime_state_record_and_separates_digests() -> None:
    world = W01World()
    probe = W01TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 92001, 7)
    sealed = probe.initialize_private(episode)
    runtime_identity = RuntimeStateIdentity.from_sealed_state(sealed)

    assert runtime_identity.state_hash == sealed.record.state_hash
    assert runtime_identity.payload_bytes_digest == digest_bytes(
        sealed.candidate_input.payload.payload
    )
    # Runtime identity is a full domain-separated preimage digest, not bare SHA(payload).
    assert runtime_identity.state_hash != runtime_identity.payload_bytes_digest

    observation = UpdateIdentityObservation(
        grain=_grain("real-w01-state"),
        information_kind=InformationKind.INFORMATIVE_OBSERVATION,
        incremental_state=runtime_identity,
        replay_state=RuntimeStateIdentity.from_sealed_state(sealed),
        batch_behavior={"diagnosis": [0.2, 0.8]},
        sequential_behavior={"diagnosis": [0.2, 0.8]},
    )
    score = OracleScoreChangeObservation(
        grain=observation.grain,
        information_kind=InformationKind.INFORMATIVE_OBSERVATION,
        readout_kind=ReadoutKind.DIAGNOSIS,
        score_direction=ScoreDirection.MINIMIZE,
        candidate_before=2,
        candidate_after=1,
        oracle_before=0,
        oracle_after=0,
    )
    query = QueryOrderObservation(
        grain=observation.grain,
        first_order=("diagnosis", "rollout"),
        second_order=("rollout", "diagnosis"),
        first_pre_state=runtime_identity,
        first_post_state=runtime_identity,
        second_pre_state=runtime_identity,
        second_post_state=runtime_identity,
        first_outputs_by_query={"diagnosis": [0.7, 0.3], "rollout": {"y": 2}},
        second_outputs_by_query={"rollout": {"y": 2}, "diagnosis": [0.7, 0.3]},
    )
    wire = update_consistency((observation,), (query,), (score,)).to_wire()
    identity_row = wire["incremental_replay_exact_identity"]["rows"][0]
    assert identity_row["incremental_state_hash"] == sealed.record.state_hash
    assert identity_row["incremental_payload_bytes_digest"] == digest_bytes(
        sealed.candidate_input.payload.payload
    )
    assert wire["input_evidence"] == "caller_asserted_unbound"
    assert wire["coverage_complete"] is False
    assert wire["hard_gate_evidence_eligible"] is False


def test_m15_runtime_state_identity_fails_closed_on_metadata_payload_or_hash_tamper() -> (
    None
):
    base = _runtime_state_from_json({"z": 1})

    with pytest.raises(ProtocolViolation, match="complete compute_state_hash preimage"):
        RuntimeStateIdentity(
            record=replace(
                base.record,
                as_of_available_at=base.record.as_of_available_at + 1,
            ),
            payload=base.payload,
        )

    with pytest.raises(ProtocolViolation, match="complete compute_state_hash preimage"):
        RuntimeStateIdentity(
            record=base.record,
            payload=StatePayload.from_json(
                {"z": 2},
                schema_version=base.payload.schema_version,
                state_class=base.payload.state_class,
            ),
        )

    with pytest.raises(ProtocolViolation, match="complete compute_state_hash preimage"):
        RuntimeStateIdentity(
            record=replace(base.record, state_hash=_digest("forged-state-hash")),
            payload=base.payload,
        )


def test_m15_dropped_rows_can_never_self_certify_complete_coverage() -> None:
    update = _update("only-provided-row")
    query = _query("only-provided-row")
    score = _score(
        "only-provided-row",
        information=InformationKind.INFORMATIVE_OBSERVATION,
        readout=ReadoutKind.DIAGNOSIS,
        before=2,
        after=1,
        task=Task.RECURSIVE_UPDATE,
    )
    # Match the exact horizon/policy fields so all three caller-provided sets align.
    score = OracleScoreChangeObservation(
        grain=update.grain,
        information_kind=score.information_kind,
        readout_kind=score.readout_kind,
        score_direction=score.score_direction,
        candidate_before=score.candidate_before,
        candidate_after=score.candidate_after,
        oracle_before=score.oracle_before,
        oracle_after=score.oracle_after,
    )
    wire = update_consistency((update,), (query,), (score,)).to_wire()
    assert wire["coverage_diagnostics"]["provided_grain_sets_aligned"] is True
    assert wire["coverage_diagnostics"]["coverage_mismatch"] is False
    assert wire["coverage_complete"] is False
    assert wire["expected_registry_binding"] == "absent"
    assert wire["hard_gate_evidence_eligible"] is False


def test_m15_fails_closed_on_wrong_types_duplicates_nonfinite_and_bad_queries() -> None:
    updates, queries, scores = _m15_fixture()
    with pytest.raises(ProtocolViolation, match="updates must be a non-empty tuple"):
        update_consistency(list(updates), queries, scores)  # type: ignore[arg-type]
    with pytest.raises(ProtocolViolation, match="duplicate exact evaluation grain"):
        update_consistency((updates[0], updates[0]), queries, scores)
    with pytest.raises(ProtocolViolation, match="exact finite number"):
        OracleScoreChangeObservation(
            grain=_grain("bad"),
            information_kind=InformationKind.INFORMATIVE_OBSERVATION,
            readout_kind=ReadoutKind.DIAGNOSIS,
            score_direction=ScoreDirection.MINIMIZE,
            candidate_before=False,
            candidate_after=1,
            oracle_before=0,
            oracle_after=0,
        )
    with pytest.raises(ProtocolViolation, match="exact finite number"):
        OracleScoreChangeObservation(
            grain=_grain("bad"),
            information_kind=InformationKind.INFORMATIVE_OBSERVATION,
            readout_kind=ReadoutKind.DIAGNOSIS,
            score_direction=ScoreDirection.MINIMIZE,
            candidate_before=float("nan"),
            candidate_after=1,
            oracle_before=0,
            oracle_after=0,
        )
    with pytest.raises(ProtocolViolation, match="distinct permutations"):
        state = _runtime_state_from_json({"state": "unchanged"})
        QueryOrderObservation(
            grain=_grain("bad-query"),
            first_order=("a", "b"),
            second_order=("a", "b"),
            first_pre_state=state,
            first_post_state=state,
            second_pre_state=state,
            second_post_state=state,
            first_outputs_by_query={"a": 1, "b": 2},
            second_outputs_by_query={"a": 1, "b": 2},
        )

    with pytest.raises(ProtocolViolation, match="canonical JSON"):
        _update("huge-json-integer", batch={"x": 10**10000})

    with pytest.raises(ProtocolViolation, match="typed RuntimeStateIdentity"):
        good_query = _query("wrong-query-state-type")
        QueryOrderObservation(
            grain=good_query.grain,
            first_order=good_query.first_order,
            second_order=good_query.second_order,
            first_pre_state=object(),  # type: ignore[arg-type]
            first_post_state=good_query.first_post_state,
            second_pre_state=good_query.second_pre_state,
            second_post_state=good_query.second_post_state,
            first_outputs_by_query=good_query.first_outputs_by_query,
            second_outputs_by_query=good_query.second_outputs_by_query,
        )


def _card(
    readout_id: str,
    *,
    in_original_y: bool = True,
    novelty: NoveltyRelation = NoveltyRelation.GENUINELY_NEW_SEMANTIC_READOUT,
    inputs: tuple[ReadoutInput, ...] = (
        ReadoutInput.SEALED_STATE,
        ReadoutInput.NEW_LABEL,
    ),
    build_worker: str = "candidate-builder",
    readout_worker: str = "independent-readout-worker",
    history_worker: str = "history-worker",
    before_digest: str | None = None,
    after_digest: str | None = None,
    sealed_before_reveal: bool = True,
    target: int | float = 0.3,
) -> NovelReadoutCard:
    base = _digest("sealed-base") if before_digest is None else before_digest
    return NovelReadoutCard(
        readout_id=readout_id,
        candidate_seal_digest=_digest("candidate-seal"),
        source_scope_digest=_digest("source-scope"),
        target_scope_digest=_digest("target-scope"),
        candidate_build_worker_id=build_worker,
        readout_worker_id=readout_worker,
        history_baseline_worker_id=history_worker,
        candidate_sealed_before_target_reveal=sealed_before_reveal,
        candidate_base_digest_before=base,
        candidate_base_digest_after=base if after_digest is None else after_digest,
        readout_inputs=inputs,
        history_baseline_inputs=(ReadoutInput.RAW_HISTORY, ReadoutInput.NEW_LABEL),
        novelty_relation=novelty,
        novelty_basis_digest=_digest(f"novelty-{readout_id}"),
        in_original_y=in_original_y,
        original_y_membership_basis=(
            OriginalYMembershipBasis.EXACT_ORIGINAL_Y_SEMANTIC_MEMBER
            if in_original_y
            else OriginalYMembershipBasis.TARGET_SCOPE_EXTENSION_OUTSIDE_ORIGINAL_Y
        ),
        original_y_membership_evidence_digest=_digest(f"membership-{readout_id}"),
        score_direction=ScoreDirection.MINIMIZE,
        sample_efficiency_target_score=target,
    )


def _evaluation(
    readout_id: str,
    *,
    card: NovelReadoutCard | None = None,
    scores: tuple[tuple[int, int | float, int | float], ...] = (
        (10, 0.6, 0.5),
        (20, 0.25, 0.2),
    ),
) -> NovelReadoutEvaluation:
    return NovelReadoutEvaluation(
        card=_card(readout_id) if card is None else card,
        points=tuple(
            NovelReadoutScorePoint(
                train_examples=examples,
                state_only_score=state_score,
                history_baseline_score=history_score,
            )
            for examples, state_score, history_score in scores
        ),
    )


def test_m16_plausible_self_assertions_remain_unverified_and_formally_unavailable() -> (
    None
):
    result = sealed_state_novel_readout_transfer((_evaluation("readout-a"),))
    wire = result.to_wire()
    row = wire["readouts"][0]

    assert wire["benchmark_status"] == "PRE-FREEZE"
    assert wire["evidence_qualification"] == "runtime_only"
    assert wire["authority_claim"] == "not_claimed"
    assert wire["freeze_authority_status"] == "not_claimed"
    assert wire["cross_metric_aggregate_score"] == "forbidden"
    assert wire["cross_readout_aggregate_score"] == "forbidden"
    assert wire["metric_target_closure"] == "not_implemented_unbound"
    assert wire["input_evidence"] == "caller_asserted_unbound"
    assert wire["evidence_status"] == "unverified_caller_assertions"
    assert wire["coverage_complete"] is False
    assert wire["freeze_gate_eligible"] is False
    assert wire["formal_novel_readout_exact_denominator"] == {
        "status": "unavailable_unbound_evidence",
        "value": None,
    }
    assert wire["provided_protocol_shape_candidate_count"] == 1
    assert row["candidate_seal_digest"] == _digest("candidate-seal")
    assert row["source_scope_digest"] == _digest("source-scope")
    assert row["target_scope_digest"] == _digest("target-scope")
    assert row["candidate_base_digest_strings_equal"] is True
    assert row["readout_worker_id_distinct_from_candidate_builder"] is True
    assert row["history_worker_id_distinct_from_candidate_and_readout"] is True
    assert row["readout_inputs"] == ["new_label", "sealed_state"]
    assert row["state_only_input_contract_satisfied"] is True
    assert row["history_baseline_inputs"] == ["new_label", "raw_history"]
    assert row["history_baseline_input_contract_satisfied"] is True
    assert row["caller_asserted_input_shape_includes_raw_history"] is False
    assert row["protocol_shape_candidate"] is True
    assert row["freeze_gate_eligible"] is False
    assert row["formal_novel_readout_eligibility"] == {
        "status": "unavailable_unbound_evidence",
        "value": None,
    }
    assert row["postseal_new_readout_score"] == 0.25
    assert row["postseal_new_readout_sample_efficiency"] == {
        "status": "defined",
        "train_examples_to_target": 20,
        "target_score": 0.3,
        "score_direction": "minimize",
        "exact_denominator_curve_points": 2,
    }
    assert row["history_baseline_sample_efficiency"]["train_examples_to_target"] == 20
    assert row["postseal_history_baseline_gap"] == pytest.approx(-0.05)
    assert row["exact_denominator_curve_points"] == 2
    assert row["protocol_shape_violation_facts"] == []
    assert (
        row["original_scope_sufficiency_disposition"] == "inconclusive_unbound_evidence"
    )
    assert row["formal_original_scope_falsification"] == {
        "status": "unavailable_unbound_evidence",
        "value": None,
    }


def test_m16_maximize_direction_reverses_target_and_history_gap_orientation() -> None:
    base = _card("maximize", target=0.7)
    values = {field: getattr(base, field) for field in base.__dataclass_fields__}
    values["score_direction"] = ScoreDirection.MAXIMIZE
    card = NovelReadoutCard(**values)
    row = sealed_state_novel_readout_transfer(
        (
            _evaluation(
                "maximize",
                card=card,
                scores=((10, 0.5, 0.6), (20, 0.8, 0.7)),
            ),
        )
    ).to_wire()["readouts"][0]
    assert (
        row["postseal_new_readout_sample_efficiency"]["train_examples_to_target"] == 20
    )
    assert row["postseal_history_baseline_gap"] == pytest.approx(0.1)


def test_m16_original_y_and_score_assertions_cannot_self_issue_falsification() -> None:
    unreadable_scores = ((10, 0.9, 0.2), (20, 0.8, 0.1))
    inside = _evaluation("inside", scores=unreadable_scores)
    outside = _evaluation(
        "outside",
        card=_card("outside", in_original_y=False),
        scores=unreadable_scores,
    )
    rows = sealed_state_novel_readout_transfer((outside, inside)).to_wire()["readouts"]
    by_id = {row["readout_id"]: row for row in rows}

    assert by_id["inside"]["postseal_new_readout_sample_efficiency"] == {
        "status": "undefined_target_not_reached",
        "train_examples_to_target": None,
        "target_score": 0.3,
        "score_direction": "minimize",
        "exact_denominator_curve_points": 2,
    }
    for readout_id in ("inside", "outside"):
        assert (
            by_id[readout_id]["original_scope_sufficiency_disposition"]
            == "inconclusive_unbound_evidence"
        )
        assert by_id[readout_id]["formal_original_scope_falsification"] == {
            "status": "unavailable_unbound_evidence",
            "value": None,
        }


def test_m16_original_scope_is_inconclusive_when_even_history_cannot_read_target() -> (
    None
):
    row = sealed_state_novel_readout_transfer(
        (
            _evaluation(
                "both-unreadable",
                scores=((10, 0.9, 0.8), (20, 0.7, 0.6)),
            ),
        )
    ).to_wire()["readouts"][0]
    assert (
        row["original_scope_sufficiency_disposition"] == "inconclusive_unbound_evidence"
    )


@pytest.mark.parametrize(
    ("relation", "expected_fact"),
    [
        (NoveltyRelation.EXISTING_OUTPUT, "not_novel:existing_output"),
        (NoveltyRelation.RENAME, "not_novel:rename"),
        (
            NoveltyRelation.DETERMINISTIC_PROJECTION,
            "not_novel:deterministic_projection",
        ),
    ],
)
def test_m16_existing_output_rename_and_projection_never_count_as_novel(
    relation: NoveltyRelation, expected_fact: str
) -> None:
    evaluation = _evaluation(
        relation.value,
        card=_card(relation.value, novelty=relation),
    )
    wire = sealed_state_novel_readout_transfer((evaluation,)).to_wire()
    row = wire["readouts"][0]
    assert wire["formal_novel_readout_exact_denominator"]["value"] is None
    assert row["protocol_shape_candidate"] is False
    assert expected_fact in row["protocol_shape_violation_facts"]
    assert (
        row["original_scope_sufficiency_disposition"] == "inconclusive_unbound_evidence"
    )


def test_m16_reports_history_base_seal_and_worker_hard_violations() -> None:
    card = _card(
        "violations",
        inputs=(
            ReadoutInput.SEALED_STATE,
            ReadoutInput.NEW_LABEL,
            ReadoutInput.RAW_HISTORY,
        ),
        readout_worker="candidate-builder",
        after_digest=_digest("changed-base"),
        sealed_before_reveal=False,
    )
    row = sealed_state_novel_readout_transfer(
        (_evaluation("violations", card=card),)
    ).to_wire()["readouts"][0]
    assert row["protocol_shape_candidate"] is False
    assert row["caller_asserted_input_shape_includes_raw_history"] is True
    assert row["candidate_base_digest_strings_equal"] is False
    assert row["readout_worker_id_distinct_from_candidate_builder"] is False
    assert set(row["protocol_shape_violation_facts"]) >= {
        "candidate_not_sealed_before_target_reveal",
        "candidate_base_changed_after_seal",
        "readout_worker_not_independent",
        "history_reread_violation",
    }


def test_m16_requires_a_separately_bound_raw_history_baseline_contract() -> None:
    base = _card("bad-history-comparator")
    values = {field: getattr(base, field) for field in base.__dataclass_fields__}
    values["history_baseline_inputs"] = (ReadoutInput.NEW_LABEL,)
    card = NovelReadoutCard(**values)
    row = sealed_state_novel_readout_transfer(
        (_evaluation("bad-history-comparator", card=card),)
    ).to_wire()["readouts"][0]
    assert row["history_baseline_input_contract_satisfied"] is False
    assert (
        "history_baseline_input_contract_violation"
        in row["protocol_shape_violation_facts"]
    )
    assert row["protocol_shape_candidate"] is False


def test_m16_history_baseline_worker_must_be_independent_of_both_workers() -> None:
    card = _card(
        "shared-history-worker",
        history_worker="independent-readout-worker",
    )
    row = sealed_state_novel_readout_transfer(
        (_evaluation("shared-history-worker", card=card),)
    ).to_wire()["readouts"][0]
    assert row["history_worker_id_distinct_from_candidate_and_readout"] is False
    assert (
        "history_baseline_worker_not_independent"
        in row["protocol_shape_violation_facts"]
    )
    assert row["protocol_shape_candidate"] is False


def test_m16_genuinely_new_readout_rejects_identical_source_target_scope() -> None:
    base = _card("same-scope")
    values = {field: getattr(base, field) for field in base.__dataclass_fields__}
    values["target_scope_digest"] = values["source_scope_digest"]
    with pytest.raises(ProtocolViolation, match="requires distinct source"):
        NovelReadoutCard(**values)


def test_m16_is_order_deterministic_and_typed_undefined_is_stable() -> None:
    a = _evaluation("a")
    b = _evaluation(
        "b",
        card=_card("b", in_original_y=False),
        scores=((10, 0.8, 0.7), (20, 0.6, 0.5)),
    )
    assert (
        sealed_state_novel_readout_transfer((a, b)).canonical_bytes
        == sealed_state_novel_readout_transfer((b, a)).canonical_bytes
    )


def test_m16_fails_closed_on_membership_bool_nonfinite_duplicates_and_overflow() -> (
    None
):
    base = _card("base")
    contradictory = copy.copy(base)
    object.__setattr__(contradictory, "in_original_y", False)
    with pytest.raises(ProtocolViolation, match="contradicts"):
        NovelReadoutCard(
            **{
                field: getattr(contradictory, field)
                for field in contradictory.__dataclass_fields__
            }
        )

    with pytest.raises(ProtocolViolation, match="exact boolean"):
        values = {field: getattr(base, field) for field in base.__dataclass_fields__}
        values["candidate_sealed_before_target_reveal"] = 1
        NovelReadoutCard(**values)

    with pytest.raises(ProtocolViolation, match="exact finite number"):
        NovelReadoutScorePoint(
            train_examples=1,
            state_only_score=float("inf"),
            history_baseline_score=0,
        )
    with pytest.raises(ProtocolViolation, match="strictly increasing"):
        NovelReadoutEvaluation(
            card=base,
            points=(
                NovelReadoutScorePoint(20, 0.2, 0.2),
                NovelReadoutScorePoint(10, 0.1, 0.1),
            ),
        )
    with pytest.raises(ProtocolViolation, match="duplicate readout_id"):
        evaluation = _evaluation("duplicate")
        sealed_state_novel_readout_transfer((evaluation, evaluation))
    with pytest.raises(ProtocolViolation, match="derived arithmetic is non-finite"):
        overflow = _evaluation(
            "overflow",
            card=_card("overflow", target=0),
            scores=((1, -1.0e308, 1.0e308),),
        )
        sealed_state_novel_readout_transfer((overflow,))


def test_m16_rejects_lists_and_duplicate_or_untyped_inputs() -> None:
    with pytest.raises(
        ProtocolViolation, match="evaluations must be a non-empty tuple"
    ):
        sealed_state_novel_readout_transfer([_evaluation("a")])  # type: ignore[arg-type]
    with pytest.raises(ProtocolViolation, match="inputs contains duplicates"):
        _card(
            "duplicate-input",
            inputs=(ReadoutInput.SEALED_STATE, ReadoutInput.SEALED_STATE),
        )
    with pytest.raises(ProtocolViolation, match="typed ReadoutInput"):
        _card("untyped-input", inputs=("sealed_state", "new_label"))  # type: ignore[arg-type]
