from __future__ import annotations

from dataclasses import replace

import pytest

from prototype.unified_map.candidate_protocol import ResultStatus
from prototype.unified_map.canonical import digest_json
from prototype.unified_map.evaluator import (
    CandidateGateStatus,
    EvaluationCohort,
    EvaluationManifest,
    EvaluationTask,
    EvidenceStatus,
    ExpectedEvaluationCell,
    ExpectedPairCell,
    IdentificationKind,
    OODAttribution,
    PairThresholds,
    RawEvaluationRecord,
    RawPairRecord,
    W19SafetyDeclaration,
    evaluate_records,
)
from prototype.unified_map.metrics import InformationRelation, PairProbe


EMPTY_DIGEST = digest_json({})


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
) -> ExpectedEvaluationCell:
    return ExpectedEvaluationCell(
        record_id,
        world,
        panel,
        episode or f"episode-{record_id}",
        cohort,
        task,
        tail,
        ood,
        identification,
        unsafe,
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
        cell.record_id,
        cell.world_slot,
        cell.panel_id,
        cell.episode_alias,
        cell.cohort,
        cell.task,
        status,
        EMPTY_DIGEST,
        EMPTY_DIGEST,
        EMPTY_DIGEST,
        EMPTY_DIGEST,
        candidate_raw,
        digest_json(candidate_raw),
        oracle_raw,
        digest_json(oracle_raw),
        (1.0 if cell.cohort is EvaluationCohort.POPULATION else 0.0)
        if weight is None
        else weight,
        loss,
        confidence,
        unknown,
        max_known,
        chosen,
        action_ids,
        predicted,
        oracle,
        all_catastrophic,
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
        pair_id,
        "W04",
        "primary",
        probe,
        weight,
        {},
        EMPTY_DIGEST,
        {},
        EMPTY_DIGEST,
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
    report = evaluate_records(records, (), EvaluationManifest((first, second)))
    assert report.evidence_status is EvidenceStatus.COMPLETE
    assert report.candidate_gate_status is CandidateGateStatus.NO_HARD_FAILURE_OBSERVED
    assert report.headline[0].denominator == 2
    assert report.headline[0].scored_count == 1
    assert report.headline[0].abstain_count == 1
    assert report.headline[0].mean_loss == pytest.approx(0.25)


def test_missing_raw_cell_is_typed_incomplete_not_a_pass() -> None:
    first = _cell("r1")
    missing = _cell("r-missing")
    report = evaluate_records(
        (_record(first),), (), EvaluationManifest((first, missing))
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
        (malicious,), (), EvaluationManifest((probe_cell,))
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
    manifest = EvaluationManifest(
        (base,),
        (
            ExpectedPairCell("danger", "W04", "primary", thresholds),
            ExpectedPairCell("split", "W04", "primary", thresholds),
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
    expected = ExpectedPairCell("required", "W04", "primary", thresholds)
    missing_report = evaluate_records(
        (_record(base),), (), EvaluationManifest((base,), (expected,))
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
        (_record(base),), (row,), EvaluationManifest((base,), (expected,))
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
        rows, (), EvaluationManifest((known, attributable, irreducible))
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
        EvaluationManifest((known, attributable)),
    )
    assert report.candidate_gate_status is CandidateGateStatus.HARD_FAILURE
    assert any(issue.code == "UCM-F017-OOD_FORCED_MATCH" for issue in report.failures)


def _w19_manifest(*cells: ExpectedEvaluationCell) -> EvaluationManifest:
    aliases = tuple(sorted({cell.episode_alias for cell in cells if cell.tail_member}))
    declaration = W19SafetyDeclaration(
        aliases,
        W19SafetyDeclaration.compute_digest(aliases),
        "A1",
        10.0,
    )
    return EvaluationManifest(tuple(cells), w19_safety=declaration)


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
    report = evaluate_records((row,), (), EvaluationManifest((cell,)))
    assert report.evidence_status is EvidenceStatus.INCOMPLETE
    assert any(issue.code == "UCM-F023-RESULT_EVIDENCE_LOSS" for issue in report.blockers)
