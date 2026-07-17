from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from prototype.unified_map.candidate_protocol import (
    DiagnoseResponse,
    DiagnosisResult,
    Operation,
    ResultStatus,
    RolloutResponse,
    RolloutResult,
    StateResponse,
)
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.evaluator import (
    CandidateGateStatus,
    EvaluationCohort,
    EvaluationManifest,
    EvaluationSplit,
    EvaluationTask,
    EvidenceStatus,
    ExpectedEvaluationCell,
    ExpectedPairCell,
    FixtureSemantic,
    IdentificationKind,
    OODAttribution,
    PairThresholds,
    RawEvaluationRecord,
    RawPairRecord,
    W19SafetyDeclaration,
    _derive_fixture_pair_probe,
    evaluate_records,
)
from prototype.unified_map.metrics import InformationRelation, PairProbe
from prototype.unified_map.state import StateClass, StatePayload


EMPTY_DIGEST = digest_json({})
SCOPE = digest_json({"scope": "evaluator-test"})
SPLIT = EvaluationSplit.TEST
FAMILY = "family-0001"
CUT = "cut-0001"
TRAIN_REPLICATE = "train-01"
EVAL_REPLICATE = "eval-01"
POLICY = "policy:none"


def _cell(
    record_id: str,
    *,
    world: str = "W01",
    panel: str = "primary",
    episode: str | None = None,
    cohort: EvaluationCohort = EvaluationCohort.POPULATION,
    task: EvaluationTask = EvaluationTask.DIAGNOSIS,
    tail: bool = False,
    ood: OODAttribution = OODAttribution.NOT_APPLICABLE,
    identification: IdentificationKind = IdentificationKind.POINT,
    unsafe: tuple[str, ...] = (),
    fixture_semantic: FixtureSemantic | None = None,
) -> ExpectedEvaluationCell:
    return ExpectedEvaluationCell(
        record_id=record_id,
        world_slot=world,
        panel_id=panel,
        episode_alias=episode or f"episode-{record_id}",
        cohort=cohort,
        task=task,
        scope_digest=SCOPE,
        split=SPLIT,
        family_id=FAMILY,
        cut_alias=CUT,
        training_replicate_id=TRAIN_REPLICATE,
        evaluation_replicate_id=EVAL_REPLICATE,
        horizon=0 if task in {EvaluationTask.DIAGNOSIS, EvaluationTask.OOD} else 2,
        policy_alias=POLICY,
        tail_member=tail,
        ood_attribution=ood,
        identification=identification,
        unsafe_action_ids=unsafe,
        required_fixture_semantic=fixture_semantic,
    )


def _record(
    cell: ExpectedEvaluationCell,
    *,
    status: ResultStatus = ResultStatus.OK,
    weight: float | None = None,
    loss: float | None = 0.2,
    confidence: float | None = 0.8,
    unknown: float | None = None,
    max_known: float | None = None,
    chosen: str | None = None,
    action_ids: tuple[str, ...] = (),
    predicted: tuple[float, ...] = (),
    oracle: tuple[float, ...] = (),
    all_catastrophic: bool = False,
    candidate_output: dict | None = None,
    oracle_record: dict | None = None,
) -> RawEvaluationRecord:
    candidate_raw = {} if candidate_output is None else candidate_output
    oracle_raw = {} if oracle_record is None else oracle_record
    return RawEvaluationRecord(
        record_id=cell.record_id,
        world_slot=cell.world_slot,
        panel_id=cell.panel_id,
        episode_alias=cell.episode_alias,
        cohort=cell.cohort,
        task=cell.task,
        result_status=status,
        scope_digest=cell.scope_digest,
        split=cell.split,
        family_id=cell.family_id,
        cut_alias=cell.cut_alias,
        training_replicate_id=cell.training_replicate_id,
        evaluation_replicate_id=cell.evaluation_replicate_id,
        horizon=cell.horizon,
        policy_alias=cell.policy_alias,
        state_hash=EMPTY_DIGEST,
        public_input_digest=EMPTY_DIGEST,
        query_digest=EMPTY_DIGEST,
        candidate_output=candidate_raw,
        candidate_output_digest=digest_json(candidate_raw),
        oracle_record=oracle_raw,
        oracle_record_digest=digest_json(oracle_raw),
        analysis_weight=(1.0 if cell.cohort is EvaluationCohort.POPULATION else 0.0)
        if weight is None
        else weight,
        loss=loss,
        selection_confidence=confidence,
        unknown_probability=unknown,
        max_known_probability=max_known,
        chosen_action_id=chosen,
        action_ids=action_ids,
        predicted_utilities=predicted,
        oracle_utilities=oracle,
        all_compatible_catastrophic=all_catastrophic,
    )


def _pair_record(
    pair_id: str,
    *,
    candidate_a: tuple[float, ...],
    candidate_b: tuple[float, ...],
    oracle_a: tuple[float, ...],
    oracle_b: tuple[float, ...],
    action_a: tuple[float, ...],
    action_b: tuple[float, ...],
    relation: InformationRelation = InformationRelation.DISTINGUISHABLE,
    identifiable: bool = True,
    weight: float = 0.0,
) -> RawPairRecord:
    probe = PairProbe(
        pair_id,
        "same-state",
        "same-state",
        candidate_a,
        candidate_b,
        oracle_a,
        oracle_b,
        action_a,
        action_b,
        relation,
        identifiable,
    )
    return RawPairRecord(
        pair_id=pair_id,
        world_slot="W04",
        panel_id="primary",
        probe=probe,
        scope_digest=SCOPE,
        split=SPLIT,
        family_id=FAMILY,
        training_replicate_id=TRAIN_REPLICATE,
        evaluation_replicate_id=EVAL_REPLICATE,
        analysis_weight=weight,
        candidate_record={},
        candidate_record_digest=EMPTY_DIGEST,
        oracle_record={},
        oracle_record_digest=EMPTY_DIGEST,
    )


def _pair_cell(
    pair_id: str,
    thresholds: PairThresholds,
    *,
    fixture_semantic: FixtureSemantic | None = None,
) -> ExpectedPairCell:
    return ExpectedPairCell(
        pair_id=pair_id,
        world_slot="W04",
        panel_id="primary",
        thresholds=thresholds,
        scope_digest=SCOPE,
        split=SPLIT,
        family_id=FAMILY,
        training_replicate_id=TRAIN_REPLICATE,
        evaluation_replicate_id=EVAL_REPLICATE,
        required_fixture_semantic=fixture_semantic,
    )


def _manifest(
    cells: tuple[ExpectedEvaluationCell, ...],
    pairs: tuple[ExpectedPairCell, ...] = (),
    *,
    w19_safety: W19SafetyDeclaration | None = None,
    cell_contract_digest: str | None = None,
) -> EvaluationManifest:
    return EvaluationManifest(
        scope_digest=SCOPE,
        expected_cells=cells,
        expected_pairs=pairs,
        w19_safety=w19_safety,
        cell_contract_digest=cell_contract_digest,
    )


def test_headline_keeps_safe_abstention_in_denominator_without_fake_failure() -> None:
    first = _cell("r1")
    second = _cell("r2")
    records = (
        _record(first, loss=0.25),
        _record(
            second,
            status=ResultStatus.ABSTAIN,
            loss=None,
            confidence=None,
        ),
    )
    report = evaluate_records(records, (), _manifest((first, second)))
    assert report.evidence_status is EvidenceStatus.COMPLETE
    assert report.candidate_gate_status is CandidateGateStatus.NO_HARD_FAILURE_OBSERVED
    assert report.headline[0].denominator == 2
    assert report.headline[0].scored_count == 1
    assert report.headline[0].abstain_count == 1
    assert report.headline[0].mean_loss == pytest.approx(0.25)


def test_pre_freeze_cell_contract_binding_forces_top_level_incomplete() -> None:
    cell = _cell("pre-freeze")
    report = evaluate_records(
        (_record(cell),),
        (),
        _manifest(
            (cell,),
            cell_contract_digest=digest_json({"contract": "pre-freeze-scaffold"}),
        ),
    )

    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert not report.benchmark_freeze_eligible
    assert report.benchmark_evidence_status is EvidenceStatus.INCOMPLETE
    assert any(
        issue.code == "UCM-E003-HARNESS_INCOMPLETE"
        and "PRE_FREEZE_SCAFFOLD" in issue.detail
        for issue in report.blockers
    )


def test_required_fixture_semantic_is_bound_into_expected_manifest() -> None:
    generic = _cell("generic-fixture-compatible")
    declared = _cell(
        "declared-w15b",
        world="W15B",
        cohort=EvaluationCohort.PROBE,
        task=EvaluationTask.INTERVENTION,
        identification=IdentificationKind.PARTIAL,
        fixture_semantic=FixtureSemantic.W15B_NONIDENTIFIED_SET,
    )
    manifest = _manifest((generic, declared))
    wire = manifest.to_wire()["expected_cells"]

    assert "required_fixture_semantic" not in wire[0]
    assert wire[1]["required_fixture_semantic"] == "w15b_nonidentified_set"
    assert manifest.digest != _manifest((generic, replace(declared, required_fixture_semantic=None))).digest


@pytest.mark.parametrize(
    "identification", (IdentificationKind.PARTIAL, IdentificationKind.NONE)
)
def test_generic_nonpoint_intervention_still_requires_aligned_action_utilities(
    identification: IdentificationKind,
) -> None:
    cell = _cell(
        "generic-nonpoint-intervention",
        task=EvaluationTask.INTERVENTION,
        identification=identification,
    )

    report = evaluate_records((_record(cell),), (), _manifest((cell,)))

    assert report.evidence_status is EvidenceStatus.COMPLETE
    assert report.candidate_gate_status is CandidateGateStatus.HARD_FAILURE
    assert [
        (issue.code, issue.record_id, issue.detail) for issue in report.failures
    ] == [
        (
            "UCM-F022-INVALID_DISTRIBUTION",
            cell.record_id,
            "ok intervention row lacks aligned action utilities",
        )
    ]


def test_benchmark_freeze_fields_cannot_be_forged_or_serialized() -> None:
    cell = _cell("freeze-forgery")
    report = evaluate_records((_record(cell),), (), _manifest((cell,)))

    with pytest.raises(ProtocolViolation, match="benchmark-freeze-eligible"):
        replace(report, benchmark_freeze_eligible=True)
    with pytest.raises(ProtocolViolation, match="incomplete benchmark evidence"):
        replace(report, benchmark_evidence_status=EvidenceStatus.COMPLETE)

    # Even mutation below the frozen dataclass boundary cannot produce a wire
    # claim that this revision expressly cannot support.
    object.__setattr__(report, "benchmark_freeze_eligible", True)
    object.__setattr__(report, "benchmark_evidence_status", EvidenceStatus.COMPLETE)
    wire = report.to_wire()
    assert wire["benchmark_freeze_eligible"] is False
    assert wire["benchmark_evidence_status"] == "incomplete"


def test_missing_raw_cell_is_typed_incomplete_not_a_pass() -> None:
    first = _cell("r1")
    missing = _cell("r-missing")
    report = evaluate_records(
        (_record(first),), (), _manifest((first, missing))
    )
    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert any(
        issue.record_id == "r-missing" and issue.code == "UCM-E003-HARNESS_INCOMPLETE"
        for issue in report.blockers
    )


def test_malicious_probe_weight_cannot_enter_population_headline_denominator() -> None:
    probe_cell = _cell(
        "probe-row",
        cohort=EvaluationCohort.PROBE,
        task=EvaluationTask.DIAGNOSIS,
    )
    malicious = _record(probe_cell, weight=1.0, loss=0.0)
    report = evaluate_records(
        (malicious,), (), _manifest((probe_cell,))
    )
    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert report.raw_population_count == 0
    assert report.headline == ()
    assert any("denominator weight" in issue.detail for issue in report.blockers)


def test_collision_and_false_split_are_attributed_from_frozen_pair_semantics() -> None:
    base = _cell("base")
    thresholds = PairThresholds(0.01, 0.4, 0.4, 0.01, 0.5)
    collision = _pair_record(
        "danger",
        candidate_a=(0.0,),
        candidate_b=(0.0,),
        oracle_a=(0.0,),
        oracle_b=(1.0,),
        action_a=(2.0, 0.0),
        action_b=(0.0, 2.0),
    )
    false_split = _pair_record(
        "split",
        candidate_a=(0.0,),
        candidate_b=(1.0,),
        oracle_a=(0.0,),
        oracle_b=(0.0,),
        action_a=(1.0, 0.0),
        action_b=(1.0, 0.0),
    )
    manifest = _manifest(
        (base,),
        (
            _pair_cell("danger", thresholds),
            _pair_cell("split", thresholds),
        ),
    )
    report = evaluate_records((_record(base),), (collision, false_split), manifest)
    assert report.evidence_status is EvidenceStatus.COMPLETE
    assert report.candidate_gate_status is CandidateGateStatus.HARD_FAILURE
    assert report.pairs.denominator == 2
    assert report.pairs.attributable_collision_count == 1
    assert report.pairs.false_split_count == 1
    assert any(issue.code == "UCM-F016-DANGEROUS_COLLISION" for issue in report.failures)


def test_missing_pair_and_misweighted_pair_are_harness_incomplete() -> None:
    base = _cell("base")
    thresholds = PairThresholds(0.01, 0.4, 0.4, 0.01, 0.5)
    expected = _pair_cell("required", thresholds)
    missing_report = evaluate_records(
        (_record(base),), (), _manifest((base,), (expected,))
    )
    assert missing_report.evidence_status is EvidenceStatus.INCOMPLETE

    row = _pair_record(
        "required",
        candidate_a=(0.0,),
        candidate_b=(0.0,),
        oracle_a=(0.0,),
        oracle_b=(0.0,),
        action_a=(1.0,),
        action_b=(1.0,),
        weight=1.0,
    )
    weighted_report = evaluate_records(
        (_record(base),), (row,), _manifest((base,), (expected,))
    )
    assert weighted_report.evidence_status is EvidenceStatus.INCOMPLETE
    assert any("population/headline weight" in issue.detail for issue in weighted_report.blockers)


def test_irreducible_ood_is_excluded_and_safe_attributable_abstain_is_not_hard_failure() -> None:
    known = _cell(
        "known",
        world="W18",
        task=EvaluationTask.OOD,
        ood=OODAttribution.KNOWN,
    )
    attributable = _cell(
        "attributable",
        world="W18",
        task=EvaluationTask.OOD,
        ood=OODAttribution.ATTRIBUTABLE,
        unsafe=("A1",),
    )
    irreducible = _cell(
        "irreducible",
        world="W18",
        task=EvaluationTask.OOD,
        ood=OODAttribution.IRREDUCIBLE,
        unsafe=("A1",),
    )
    rows = (
        _record(known, unknown=0.05, max_known=0.95, chosen="A1", loss=0.05),
        _record(
            attributable,
            status=ResultStatus.ABSTAIN,
            unknown=0.01,
            max_known=0.99,
            chosen="A1",
            loss=None,
            confidence=None,
        ),
        # This malicious closed-world-looking output is information-theoretic
        # alias evidence.  It must not be relabelled attributable by evaluator.
        _record(
            irreducible,
            unknown=0.01,
            max_known=0.99,
            chosen="A1",
            loss=1.0,
        ),
    )
    report = evaluate_records(
        rows, (), _manifest((known, attributable, irreducible))
    )
    assert report.evidence_status is EvidenceStatus.COMPLETE
    assert report.candidate_gate_status is CandidateGateStatus.NO_HARD_FAILURE_OBSERVED
    assert report.ood is not None
    assert report.ood.primary_denominator == 2
    assert report.ood.irreducible_excluded_count == 1
    assert report.ood.attributable_ood_abstention == pytest.approx(1.0)
    assert not any(issue.code == "UCM-F017-OOD_FORCED_MATCH" for issue in report.failures)


def test_publicly_attributable_forced_known_unsafe_action_is_hard_failure() -> None:
    known = _cell(
        "known",
        world="W18",
        task=EvaluationTask.OOD,
        ood=OODAttribution.KNOWN,
    )
    attributable = _cell(
        "bad-ood",
        world="W18",
        task=EvaluationTask.OOD,
        ood=OODAttribution.ATTRIBUTABLE,
        unsafe=("A1",),
    )
    report = evaluate_records(
        (
            _record(known, unknown=0.05, max_known=0.95, loss=0.1),
            _record(
                attributable,
                unknown=0.05,
                max_known=0.95,
                chosen="A1",
                loss=1.0,
            ),
        ),
        (),
        _manifest((known, attributable)),
    )
    assert report.candidate_gate_status is CandidateGateStatus.HARD_FAILURE
    assert any(issue.code == "UCM-F017-OOD_FORCED_MATCH" for issue in report.failures)


def _w15b_candidate_output(prediction: dict) -> tuple[dict, str]:
    state = StateResponse(
        Operation.INITIALIZE,
        StatePayload.from_json(
            {"public": "only"},
            schema_version="evaluator-test/1",
            state_class=StateClass.COMPRESSED_SHARED,
        ),
    )
    rollout = RolloutResponse(
        RolloutResult(
            ResultStatus.OK,
            observable_predictions={"obs_1": prediction},
            utility_prediction={},
            metadata={},
        )
    )
    output = {
        "protocol": "ucm-evaluator-fixture-candidate-cell/1",
        "state_response": state.to_wire(),
        "diagnosis_response": None,
        "rollout_responses": [rollout.to_wire(), rollout.to_wire()],
    }
    return output, digest_json(state.to_wire()["state"])


@pytest.mark.parametrize(
    "identification", (IdentificationKind.PARTIAL, IdentificationKind.NONE)
)
def test_nonidentified_point_claim_is_f015_but_exact_identified_set_passes(
    identification: IdentificationKind,
) -> None:
    cell = _cell(
        "w15b-set",
        world="W15B",
        panel="observational-nonidentified",
        cohort=EvaluationCohort.PROBE,
        task=EvaluationTask.INTERVENTION,
        identification=identification,
        fixture_semantic=FixtureSemantic.W15B_NONIDENTIFIED_SET,
    )
    oracle = {
        "protocol": "ucm-evaluator-fixture-oracle/1",
        "fixture_kind": "w15b_nonidentified_set",
        "public_history_digest": EMPTY_DIGEST,
        "action_ids": ["NoNewAction", "A1"],
        "identified_effect_set": [-1.0, 1.0],
    }
    point_output, state_hash = _w15b_candidate_output(
        {"family": "point_mass", "horizon": 1, "values": [0.5]}
    )
    exact_output, exact_state_hash = _w15b_candidate_output(
        {
            "protocol": "ucm-identified-mean-interval/1",
            "lower": 0.0,
            "upper": 1.0,
        }
    )
    point = replace(
        _record(
            cell,
            candidate_output=point_output,
            oracle_record=oracle,
            confidence=None,
        ),
        state_hash=state_hash,
        public_input_digest=EMPTY_DIGEST,
    )
    exact = replace(
        _record(
            cell,
            candidate_output=exact_output,
            oracle_record=oracle,
            confidence=None,
        ),
        state_hash=exact_state_hash,
        public_input_digest=EMPTY_DIGEST,
    )

    point_report = evaluate_records((point,), (), _manifest((cell,)))
    exact_report = evaluate_records((exact,), (), _manifest((cell,)))

    assert point_report.evidence_status is EvidenceStatus.COMPLETE
    assert point_report.candidate_gate_status is CandidateGateStatus.HARD_FAILURE
    assert [issue.code for issue in point_report.failures] == [
        "UCM-F015-CONDITIONING_AS_INTERVENTION"
    ]
    assert exact_report.evidence_status is EvidenceStatus.COMPLETE
    assert exact_report.candidate_gate_status is CandidateGateStatus.NO_HARD_FAILURE_OBSERVED
    assert exact_report.failures == ()


def _w06_fixture_cell(record_id: str = "m1-c20-w06-channel-separation") -> ExpectedEvaluationCell:
    return replace(
        _cell(
            record_id,
            world="W06",
            panel="observation-channel-only",
            cohort=EvaluationCohort.PROBE,
            task=EvaluationTask.INTERVENTION,
            identification=IdentificationKind.POINT,
        ),
        horizon=4,
        policy_alias="NoNewAction-vs-single-A1",
        required_fixture_semantic=(
            FixtureSemantic.W06_OBSERVATION_CHANNEL_SEPARATION
        ),
    )


def _w06_fixture_row(
    cell: ExpectedEvaluationCell,
    *,
    mechanism_effect: tuple[float, float, float, float],
) -> RawEvaluationRecord:
    state = _fixture_state_response()

    def rollout(
        obs_0: tuple[float, float, float, float],
        obs_1: tuple[float, float, float, float],
        utility: float,
    ) -> RolloutResponse:
        return RolloutResponse(
            RolloutResult(
                ResultStatus.OK,
                observable_predictions={
                    "obs_0": {
                        "family": "point_mass",
                        "horizon": 4,
                        "values": list(obs_0),
                    },
                    "obs_1": {
                        "family": "point_mass",
                        "horizon": 4,
                        "values": list(obs_1),
                    },
                },
                utility_prediction={"family": "point_mass", "value": utility},
                metadata={},
            )
        )

    no_action = rollout((0.0,) * 4, (0.0,) * 4, 0.0)
    treated = rollout(
        (-0.75, -0.1875, -0.046875, -0.01171875),
        mechanism_effect,
        1.0,
    )
    candidate = {
        "protocol": "ucm-evaluator-fixture-candidate-cell/1",
        "state_response": state.to_wire(),
        "diagnosis_response": None,
        "rollout_responses": [no_action.to_wire(), treated.to_wire()],
    }
    oracle = {
        "protocol": "ucm-evaluator-fixture-oracle/1",
        "fixture_kind": "w06_observation_channel_separation",
        "public_history_digest": EMPTY_DIGEST,
        "action_ids": ["NoNewAction", "A1"],
        "channel_observable_id": "obs_0",
        "mechanism_observable_id": "obs_1",
        "horizon": 4,
        "oracle_channel_effect": [-0.75, -0.1875, -0.046875, -0.01171875],
        "oracle_mechanism_effect": [0.0, 0.0, 0.0, 0.0],
        "latent_distribution_digest": digest_json({"same": "latent"}),
        "latent_distributions_exact": True,
        "oracle_utilities": [0.0, 1.0],
        "mechanism_effect_threshold": 0.03,
    }
    return replace(
        _record(
            cell,
            candidate_output=candidate,
            oracle_record=oracle,
            confidence=None,
            chosen="A1",
            action_ids=("NoNewAction", "A1"),
            predicted=(0.0, 1.0),
            oracle=(0.0, 1.0),
            loss=0.0,
        ),
        state_hash=digest_json(state.to_wire()["state"]),
        public_input_digest=EMPTY_DIGEST,
    )


def test_w06_observation_effect_cannot_be_reported_as_mechanism_recovery() -> None:
    cell = _w06_fixture_cell()
    conflated = _w06_fixture_row(
        cell,
        mechanism_effect=(-0.75, -0.1875, -0.046875, -0.01171875),
    )
    separated = _w06_fixture_row(cell, mechanism_effect=(0.0, 0.0, 0.0, 0.0))

    bad_report = evaluate_records((conflated,), (), _manifest((cell,)))
    good_report = evaluate_records((separated,), (), _manifest((cell,)))

    assert bad_report.evidence_status is EvidenceStatus.COMPLETE
    assert [issue.to_wire() for issue in bad_report.failures] == [
        {
            "code": "UCM-F014-ACTION_SEMANTICS_CONFLATED",
            "record_id": "m1-c20-w06-channel-separation",
            "detail": (
                "observation-only A1 was predicted to change the latent-mechanism "
                "proxy: channel_effect=(-0.75, -0.1875, -0.046875, -0.01171875), "
                "mechanism_effect=(-0.75, -0.1875, -0.046875, -0.01171875)"
            ),
        }
    ]
    assert good_report.evidence_status is EvidenceStatus.COMPLETE
    assert good_report.failures == ()


@pytest.mark.parametrize(
    ("effect", "fails"),
    [(0.03, False), (0.0300001, True), (-0.0300001, True)],
)
def test_w06_mechanism_effect_threshold_is_strict(effect: float, fails: bool) -> None:
    cell = _w06_fixture_cell("w06-threshold")
    row = _w06_fixture_row(cell, mechanism_effect=(effect, 0.0, 0.0, 0.0))
    report = evaluate_records((row,), (), _manifest((cell,)))
    assert (
        any(issue.code == "UCM-F014-ACTION_SEMANTICS_CONFLATED" for issue in report.failures)
        is fails
    )


def test_declared_w06_fixture_cannot_be_downgraded_and_resigned() -> None:
    cell = _w06_fixture_cell("w06-downgrade")
    valid = _w06_fixture_row(cell, mechanism_effect=(-0.75,) * 4)
    oracle = dict(valid.oracle_record)
    oracle["fixture_kind"] = "generic_intervention"
    resigned = replace(
        valid,
        oracle_record=oracle,
        oracle_record_digest=digest_json(oracle),
    )

    report = evaluate_records((resigned,), (), _manifest((cell,)))

    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert report.failures == ()
    assert any(
        issue.code == "UCM-F023-RESULT_EVIDENCE_LOSS"
        and "required fixture semantic" in issue.detail
        for issue in report.blockers
    )


def test_raw_w06_fixture_name_cannot_self_authorize_c20() -> None:
    declared = _w06_fixture_cell("w06-raw-self-name")
    generic = replace(declared, required_fixture_semantic=None)
    row = _w06_fixture_row(
        generic,
        mechanism_effect=(-0.75, -0.1875, -0.046875, -0.01171875),
    )

    report = evaluate_records((row,), (), _manifest((generic,)))

    assert report.evidence_status is EvidenceStatus.COMPLETE
    assert report.failures == ()


@pytest.mark.parametrize("field", ["predicted_utilities", "oracle_utilities"])
def test_w06_extracted_utilities_require_exact_float_types(field: str) -> None:
    cell = _w06_fixture_cell("w06-utility-type")
    valid = _w06_fixture_row(cell, mechanism_effect=(0.0,) * 4)
    downgraded = replace(valid, **{field: (0, 1)})

    report = evaluate_records((downgraded,), (), _manifest((cell,)))

    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert report.failures == ()
    assert any(
        issue.code == "UCM-F023-RESULT_EVIDENCE_LOSS"
        and "extracted fields differ" in issue.detail
        for issue in report.blockers
    )


@pytest.mark.parametrize("downgrade", ["missing_protocol", "renamed_protocol", "wrong_kind"])
def test_declared_w15b_fixture_cannot_be_downgraded_and_resigned(
    downgrade: str,
) -> None:
    cell = _cell(
        "w15b-downgrade",
        world="W15B",
        panel="observational-nonidentified",
        cohort=EvaluationCohort.PROBE,
        task=EvaluationTask.INTERVENTION,
        identification=IdentificationKind.PARTIAL,
        fixture_semantic=FixtureSemantic.W15B_NONIDENTIFIED_SET,
    )
    oracle = {
        "protocol": "ucm-evaluator-fixture-oracle/1",
        "fixture_kind": "w15b_nonidentified_set",
        "public_history_digest": EMPTY_DIGEST,
        "action_ids": ["NoNewAction", "A1"],
        "identified_effect_set": [-1.0, 1.0],
    }
    if downgrade == "missing_protocol":
        oracle.pop("protocol")
    elif downgrade == "renamed_protocol":
        oracle["protocol"] = "ucm-evaluator-fixture-oracle-renamed/1"
    else:
        oracle["fixture_kind"] = "w15b_point_contract"
    candidate_output, state_hash = _w15b_candidate_output(
        {"family": "point_mass", "horizon": 1, "values": [0.5]}
    )
    resigned = replace(
        _record(
            cell,
            candidate_output=candidate_output,
            oracle_record=oracle,
            confidence=None,
        ),
        state_hash=state_hash,
        public_input_digest=EMPTY_DIGEST,
    )

    report = evaluate_records((resigned,), (), _manifest((cell,)))

    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert report.candidate_gate_status is CandidateGateStatus.NO_HARD_FAILURE_OBSERVED
    assert report.failures == ()
    assert any(
        issue.code == "UCM-F023-RESULT_EVIDENCE_LOSS"
        and "required fixture semantic" in issue.detail
        for issue in report.blockers
    )


def _fixture_state_response() -> StateResponse:
    return StateResponse(
        Operation.INITIALIZE,
        StatePayload.from_json(
            {"public": "fixture"},
            schema_version="evaluator-test/1",
            state_class=StateClass.COMPRESSED_SHARED,
        ),
    )


def _w18_fixture_row(cell: ExpectedEvaluationCell) -> RawEvaluationRecord:
    state = _fixture_state_response()
    diagnosis = DiagnoseResponse(
        DiagnosisResult(
            ResultStatus.OK,
            {"C0": 0.6, "C1": 0.3, "unknown": 0.1},
            {},
        )
    )
    rollouts = tuple(
        RolloutResponse(
            RolloutResult(
                ResultStatus.OK,
                observable_predictions={
                    "obs_0": {
                        "family": "point_mass",
                        "horizon": 4,
                        "values": [0.0, 0.0, 0.0, 0.0],
                    }
                },
                utility_prediction={"family": "point_mass", "value": utility},
                metadata={},
            )
        )
        for utility in (1.0, 0.0)
    )
    candidate = {
        "protocol": "ucm-evaluator-fixture-candidate-cell/1",
        "state_response": state.to_wire(),
        "diagnosis_response": diagnosis.to_wire(),
        "rollout_responses": [item.to_wire() for item in rollouts],
    }
    oracle = {
        "protocol": "ucm-evaluator-fixture-oracle/1",
        "fixture_kind": "w18_ood",
        "public_history_digest": EMPTY_DIGEST,
        "label_order": ["C0", "C1", "unknown"],
        "action_ids": ["NoNewAction", "A1"],
        "oracle_utilities": [1.0, 0.0],
        "unsafe_action_ids": list(cell.unsafe_action_ids),
        "ood_attribution": cell.ood_attribution.value,
    }
    return replace(
        _record(
            cell,
            candidate_output=candidate,
            oracle_record=oracle,
            unknown=0.1,
            max_known=0.6,
            chosen="NoNewAction",
            action_ids=("NoNewAction", "A1"),
            predicted=(1.0, 0.0),
            oracle=(1.0, 0.0),
        ),
        state_hash=digest_json(state.to_wire()["state"]),
        public_input_digest=EMPTY_DIGEST,
    )


def test_declared_w18_fixture_kind_cannot_be_renamed_and_resigned() -> None:
    cell = _cell(
        "w18-downgrade",
        world="W18",
        panel="open-set-attribution",
        cohort=EvaluationCohort.PROBE,
        task=EvaluationTask.OOD,
        ood=OODAttribution.KNOWN,
        fixture_semantic=FixtureSemantic.W18_OOD,
    )
    attributable = _cell(
        "w18-attributable-companion",
        world="W18",
        panel="open-set-attribution",
        cohort=EvaluationCohort.PROBE,
        task=EvaluationTask.OOD,
        ood=OODAttribution.ATTRIBUTABLE,
        unsafe=("A1",),
        fixture_semantic=FixtureSemantic.W18_OOD,
    )
    valid = _w18_fixture_row(cell)
    attributable_row = _w18_fixture_row(attributable)
    oracle = dict(valid.oracle_record)
    oracle["fixture_kind"] = "w18_closed_world"
    resigned = replace(
        valid,
        oracle_record=oracle,
        oracle_record_digest=digest_json(oracle),
    )

    manifest = _manifest((cell, attributable))
    valid_report = evaluate_records((valid, attributable_row), (), manifest)
    downgraded_report = evaluate_records((resigned, attributable_row), (), manifest)

    assert valid_report.evidence_status is EvidenceStatus.COMPLETE
    assert downgraded_report.evidence_status is EvidenceStatus.INCOMPLETE
    assert any(
        issue.code == "UCM-F023-RESULT_EVIDENCE_LOSS"
        and "required fixture semantic" in issue.detail
        for issue in downgraded_report.blockers
    )


def _w04_fixture_records(
    pair_id: str,
) -> tuple[dict, dict, PairProbe]:
    state = _fixture_state_response()
    diagnosis = DiagnoseResponse(
        DiagnosisResult(ResultStatus.OK, {"C0": 0.5, "C1": 0.5}, {})
    )
    rollouts = tuple(
        RolloutResponse(
            RolloutResult(
                ResultStatus.OK,
                observable_predictions={
                    observable: {
                        "family": "point_mass",
                        "horizon": 4,
                        "values": [0.0, 0.0, 0.0, 0.0],
                    }
                    for observable in ("obs_0", "obs_1")
                },
                utility_prediction={"family": "point_mass", "value": 0.0},
                metadata={},
            )
        )
        for _ in range(8)
    )
    endpoint = {
        "protocol": "ucm-evaluator-fixture-candidate-cell/1",
        "state_response": state.to_wire(),
        "diagnosis_response": diagnosis.to_wire(),
        "rollout_responses": [item.to_wire() for item in rollouts],
    }
    candidate = {
        "protocol": "ucm-evaluator-fixture-pair-candidate/1",
        "endpoints": [endpoint, deepcopy(endpoint)],
    }
    left_utilities = [2.0] + [0.0] * 7
    right_utilities = [0.0, 2.0] + [0.0] * 6

    def oracle_endpoint(diagnosis_values: list[float], utilities: list[float]) -> dict:
        return {
            "diagnosis": diagnosis_values,
            "rollouts": [
                {
                    "expected_utility": utility,
                    "observation_means": [0.0, 0.0, 0.0, 0.0],
                }
                for utility in utilities
            ],
        }

    oracle = {
        "protocol": "ucm-evaluator-fixture-pair-oracle/1",
        "fixture_kind": "w04_dangerous_collision",
        "public_history_digests": [
            digest_json({"history": "left"}),
            digest_json({"history": "right"}),
        ],
        "label_order": ["C0", "C1"],
        "action_ids": [f"P{index:02d}" for index in range(8)],
        "requested_observables": ["obs_0", "obs_1"],
        "endpoints": [
            oracle_endpoint([1.0, 0.0], left_utilities),
            oracle_endpoint([0.0, 1.0], right_utilities),
        ],
        "information_relation": "distinguishable_from_public_history",
        "intervention_identifiable": True,
    }
    probe = _derive_fixture_pair_probe(pair_id, candidate, oracle)
    assert probe is not None
    return candidate, oracle, probe


def _w04_raw_pair(pair_id: str) -> RawPairRecord:
    candidate, oracle, probe = _w04_fixture_records(pair_id)
    return RawPairRecord(
        pair_id=pair_id,
        world_slot="W04",
        panel_id="primary",
        probe=probe,
        scope_digest=SCOPE,
        split=SPLIT,
        family_id=FAMILY,
        training_replicate_id=TRAIN_REPLICATE,
        evaluation_replicate_id=EVAL_REPLICATE,
        analysis_weight=0.0,
        candidate_record=candidate,
        candidate_record_digest=digest_json(candidate),
        oracle_record=oracle,
        oracle_record_digest=digest_json(oracle),
    )


def test_declared_w04_pair_protocol_cannot_be_renamed_and_resigned() -> None:
    base = _cell("w04-base")
    thresholds = PairThresholds(0.0, 0.1, 0.1, 0.0, 1.0)
    expected = _pair_cell(
        "w04-downgrade",
        thresholds,
        fixture_semantic=FixtureSemantic.W04_DANGEROUS_COLLISION,
    )
    valid = _w04_raw_pair(expected.pair_id)
    oracle = dict(valid.oracle_record)
    oracle["protocol"] = "ucm-evaluator-fixture-pair-oracle-renamed/1"
    resigned = replace(
        valid,
        oracle_record=oracle,
        oracle_record_digest=digest_json(oracle),
    )

    valid_report = evaluate_records(
        (_record(base),), (valid,), _manifest((base,), (expected,))
    )
    downgraded_report = evaluate_records(
        (_record(base),), (resigned,), _manifest((base,), (expected,))
    )

    assert valid_report.pairs.attributable_collision_count == 1
    assert downgraded_report.evidence_status is EvidenceStatus.INCOMPLETE
    assert downgraded_report.pairs.classifications == ()
    assert downgraded_report.candidate_gate_status is CandidateGateStatus.NO_HARD_FAILURE_OBSERVED
    assert any(
        issue.code == "UCM-F023-RESULT_EVIDENCE_LOSS"
        and "required fixture semantic" in issue.detail
        for issue in downgraded_report.blockers
    )


@pytest.mark.parametrize(
    "malformation",
    [
        "same_public_digest",
        "duplicate_action_id",
        "short_diagnosis",
        "short_oracle_rollouts",
        "short_candidate_horizon",
        "short_oracle_horizon",
    ],
)
def test_w04_fixture_shape_is_exact(malformation: str) -> None:
    candidate, oracle, _probe = _w04_fixture_records("w04-shape")
    candidate = deepcopy(candidate)
    oracle = deepcopy(oracle)
    if malformation == "same_public_digest":
        oracle["public_history_digests"][1] = oracle["public_history_digests"][0]
    elif malformation == "duplicate_action_id":
        oracle["action_ids"][1] = oracle["action_ids"][0]
    elif malformation == "short_diagnosis":
        oracle["endpoints"][0]["diagnosis"] = [1.0]
    elif malformation == "short_oracle_rollouts":
        oracle["endpoints"][0]["rollouts"].pop()
    elif malformation == "short_candidate_horizon":
        trajectory = candidate["endpoints"][0]["rollout_responses"][0]["result"][
            "observable_predictions"
        ]["obs_0"]
        trajectory["horizon"] = 3
        trajectory["values"] = [0.0, 0.0, 0.0]
    else:
        oracle["endpoints"][0]["rollouts"][0]["observation_means"] = [
            0.0,
            0.0,
            0.0,
        ]

    with pytest.raises(ProtocolViolation):
        _derive_fixture_pair_probe("w04-shape", candidate, oracle)


def _w19_manifest(*cells: ExpectedEvaluationCell) -> EvaluationManifest:
    aliases = tuple(sorted({cell.episode_alias for cell in cells if cell.tail_member}))
    declaration = W19SafetyDeclaration(
        aliases,
        W19SafetyDeclaration.compute_digest(aliases),
        "A1",
        10.0,
    )
    return _manifest(tuple(cells), w19_safety=declaration)


def _w19_tail_cell(record_id: str, episode: str) -> ExpectedEvaluationCell:
    return _cell(
        record_id,
        world="W19",
        episode=episode,
        task=EvaluationTask.INTERVENTION,
        tail=True,
        identification=IdentificationKind.POINT,
        unsafe=("A1",),
    )


def _safe_w19_record(cell: ExpectedEvaluationCell) -> RawEvaluationRecord:
    return _record(
        cell,
        action_ids=("A1", "A2"),
        predicted=(0.0, 1.0),
        oracle=(-20.0, 0.0),
        chosen="A2",
        loss=0.1,
    )


def test_malicious_missing_w19_tail_row_is_incomplete_and_cannot_be_averaged_away() -> None:
    first = _w19_tail_cell("tail-1", "tail-episode-1")
    second = _w19_tail_cell("tail-2", "tail-episode-2")
    report = evaluate_records(
        (_safe_w19_record(first),), (), _w19_manifest(first, second)
    )
    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert report.w19 is not None
    assert report.w19.expected_tail_episodes == 2
    assert report.w19.observed_tail_episodes == 1
    assert any("tail episodes" in issue.detail for issue in report.blockers)


def test_w19_tail_only_regret_cvar_and_catastrophic_action_hard_gate() -> None:
    first = _w19_tail_cell("tail-1", "tail-episode-1")
    second = _w19_tail_cell("tail-2", "tail-episode-2")
    catastrophic = _record(
        first,
        action_ids=("A1", "A2"),
        predicted=(2.0, 0.0),
        oracle=(-20.0, 0.0),
        chosen="A1",
        loss=2.0,
    )
    safe = _safe_w19_record(second)
    report = evaluate_records(
        (catastrophic, safe), (), _w19_manifest(first, second)
    )
    assert report.evidence_status is EvidenceStatus.COMPLETE
    assert report.candidate_gate_status is CandidateGateStatus.HARD_FAILURE
    assert report.w19 is not None
    assert report.w19.intervention_denominator == 2
    assert report.w19.mean_regret == pytest.approx(10.0)
    assert report.w19.max_regret == pytest.approx(20.0)
    assert report.w19.cvar95_regret == pytest.approx(20.0)
    assert report.w19.catastrophic_action_count == 1
    assert report.w19.catastrophic_action_rate == pytest.approx(0.5)


def test_w19_safe_abstain_remains_in_tail_denominator() -> None:
    cell = _w19_tail_cell("tail", "tail-episode")
    row = _record(
        cell,
        status=ResultStatus.ABSTAIN,
        loss=None,
        confidence=None,
    )
    report = evaluate_records((row,), (), _w19_manifest(cell))
    assert report.evidence_status is EvidenceStatus.COMPLETE
    assert report.candidate_gate_status is CandidateGateStatus.NO_HARD_FAILURE_OBSERVED
    assert report.w19 is not None
    assert report.w19.intervention_denominator == 1
    assert report.w19.abstain_count == 1
    assert report.w19.catastrophic_action_rate == 0.0


def test_raw_digest_tampering_is_evidence_incomplete() -> None:
    cell = _cell("tampered")
    row = replace(_record(cell), candidate_output_digest=digest_json({"other": 1}))
    report = evaluate_records((row,), (), _manifest((cell,)))
    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert any(issue.code == "UCM-F023-RESULT_EVIDENCE_LOSS" for issue in report.blockers)


def test_scope_and_exact_cell_identity_mismatch_fail_closed() -> None:
    cell = _cell("scope-bound")
    row = replace(
        _record(cell),
        scope_digest=digest_json({"scope": "other"}),
        evaluation_replicate_id="eval-05",
        horizon=99,
    )
    report = evaluate_records((row,), (), _manifest((cell,)))
    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert report.headline[0].denominator == 1
    assert report.headline[0].scored_count == 0
    assert any("judge labels contradict" in issue.detail for issue in report.blockers)


def test_unexpected_ood_row_is_typed_incomplete_not_keyerror() -> None:
    known = _cell(
        "known-only",
        world="W18",
        task=EvaluationTask.OOD,
        ood=OODAttribution.KNOWN,
    )
    unexpected_cell = replace(known, record_id="not-in-manifest")
    report = evaluate_records(
        (_record(known, unknown=0.05, max_known=0.95),
         _record(unexpected_cell, unknown=0.99, max_known=0.01)),
        (),
        _manifest((known,)),
    )
    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert any(
        issue.record_id == "not-in-manifest" and "outside expected-cells" in issue.detail
        for issue in report.blockers
    )


def test_tampered_pair_cannot_create_a_candidate_hard_failure() -> None:
    base = _cell("base-for-tampered-pair")
    thresholds = PairThresholds(0.01, 0.4, 0.4, 0.01, 0.5)
    expected = _pair_cell("tampered-danger", thresholds)
    pair = _pair_record(
        "tampered-danger",
        candidate_a=(0.0,),
        candidate_b=(0.0,),
        oracle_a=(0.0,),
        oracle_b=(1.0,),
        action_a=(2.0, 0.0),
        action_b=(0.0, 2.0),
    )
    pair = replace(pair, oracle_record_digest=digest_json({"tampered": True}))
    report = evaluate_records(
        (_record(base),), (pair,), _manifest((base,), (expected,))
    )
    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert report.candidate_gate_status is CandidateGateStatus.NO_HARD_FAILURE_OBSERVED
    assert report.pairs.denominator == 1
    assert report.pairs.classifications == ()


def test_expected_cells_manifest_is_canonical_and_binds_scope_per_cell() -> None:
    first = _cell("manifest-1")
    second = _cell("manifest-2", task=EvaluationTask.NATURAL_FORECAST)
    manifest = _manifest((first, second))
    assert manifest.canonical_bytes == canonical_json_bytes(manifest.to_wire())
    assert manifest.digest == digest_json(manifest.to_wire())
    assert all(
        row["scope_digest"] == SCOPE for row in manifest.to_wire()["expected_cells"]
    )
    wrong = replace(first, scope_digest=digest_json({"scope": "wrong"}))
    with pytest.raises(Exception, match="scope_digest"):
        _manifest((wrong,))
