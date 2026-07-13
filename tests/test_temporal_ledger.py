from __future__ import annotations

from prototype.candidates.temporal_ledger import TemporalEvidenceLedger, TemporalRuleModule
from prototype.contract import (
    ClockSet,
    InfoState,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
)


def artifact(
    source_id: str,
    concept: str,
    value: object,
    *,
    available: str = "2026-01-01T08:05:00+00:00",
    role: SemanticRole = SemanticRole.RAW_OBSERVATION,
    state: InfoState = InfoState.PRESENT,
    subject: str = "p1",
    unit: str | None = None,
) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=f"artifact-{source_id}",
        source_id=source_id,
        semantic_role=role,
        concept=concept,
        scope=Scope(subject),
        clocks=ClockSet(
            effective_start="2026-01-01T08:00:00+00:00",
            effective_end=None,
            collected_at="2026-01-01T08:00:00+00:00",
            available_at=available,
            recorded_at=available,
            expires_at=None,
        ),
        information_state=state,
        value=value,
        unit=unit,
        raw_payload={"original": value},
    )


def query(engine: TemporalEvidenceLedger, target: str, at: str) -> object:
    return engine.query(
        QuerySpec(
            query_id=f"q-{target}-{at}",
            kind=QueryKind.PROJECT,
            target=target,
            subject_id="p1",
            as_known_at=at,
            valid_at="2026-01-01T08:30:00+00:00",
        )
    )


def fever_module() -> TemporalRuleModule:
    return TemporalRuleModule.from_data(
        {
            "module_id": "fever-rules",
            "version": "1",
            "registered_at": "2025-12-01T00:00:00Z",
            "rules": [
                {
                    "rule_id": "temperature-to-fever",
                    "premises": [{"concept": "temperature", "min_value": 38.0, "unit": "Cel"}],
                    "conclusion": {"concept": "fever", "value": True},
                },
                {
                    "rule_id": "fever-to-high-fever",
                    "premises": [{"concept": "temperature", "min_value": 39.0, "unit": "Cel"}],
                    "conclusion": {"concept": "high_fever", "value": True},
                },
            ],
        }
    )


def test_future_result_is_not_visible_at_past_cut() -> None:
    engine = TemporalEvidenceLedger()
    engine.ingest(artifact("lab-1", "temperature", 39.2, available="2026-01-01T12:00:00+00:00", unit="Cel"))
    before = query(engine, "temperature", "2026-01-01T09:00:00+00:00")
    after = query(engine, "temperature", "2026-01-01T13:00:00+00:00")
    assert before.status is ResultStatus.INSUFFICIENT
    assert after.status is ResultStatus.OK
    assert after.evidence_witness["root_sources"] == ["lab-1"]


def test_duplicate_delivery_and_three_derivations_keep_one_root() -> None:
    engine = TemporalEvidenceLedger()
    raw = artifact("thermometer-1", "temperature", 39.2, unit="Cel")
    assert engine.ingest(raw).value["idempotent"] is False
    assert engine.ingest(raw).value["idempotent"] is True
    engine.register_module(fever_module())
    fever = query(engine, "fever", "2026-01-01T09:00:00+00:00")
    high = query(engine, "high_fever", "2026-01-01T09:00:00+00:00")
    assert fever.evidence_witness["root_sources"] == ["thermometer-1"]
    assert high.evidence_witness["root_sources"] == ["thermometer-1"]


def test_retraction_invalidates_dependents_and_matches_clean_rebuild() -> None:
    engine = TemporalEvidenceLedger()
    engine.ingest(artifact("thermometer-1", "temperature", 39.2, unit="Cel"))
    engine.register_module(fever_module())
    assert query(engine, "fever", "2026-01-01T09:00:00+00:00").status is ResultStatus.OK
    engine.retract("thermometer-1", "2026-01-01T10:00:00+00:00")
    incremental = query(engine, "fever", "2026-01-01T11:00:00+00:00")
    rebuilt = query(engine.clean_rebuild(), "fever", "2026-01-01T11:00:00+00:00")
    assert incremental.status is ResultStatus.INSUFFICIENT
    assert incremental.to_dict() == rebuilt.to_dict()


def test_conflict_is_local_and_plan_is_not_performed() -> None:
    engine = TemporalEvidenceLedger()
    engine.ingest(artifact("note-a", "oxygen_support", "high_flow"))
    engine.ingest(artifact("note-b", "oxygen_support", "room_air", state=InfoState.ABSENT))
    conflict = query(engine, "oxygen_support", "2026-01-01T09:00:00+00:00")
    assert conflict.status is ResultStatus.CONFLICTING

    engine.ingest(artifact("order-1", "norepinephrine", "start", role=SemanticRole.PLAN))
    planned = query(engine, "norepinephrine", "2026-01-01T09:00:00+00:00")
    roles = {claim["semantic_role"] for claim in planned.value["claims"]}
    assert roles == {SemanticRole.PLAN.value}


def test_dynamic_query_is_honestly_unsupported_without_mutation() -> None:
    engine = TemporalEvidenceLedger()
    engine.ingest(artifact("lab-1", "temperature", 39.0, unit="Cel"))
    before = query(engine, "temperature", "2026-01-01T09:00:00+00:00").to_dict()
    result = engine.query(
        QuerySpec(
            query_id="forecast",
            kind=QueryKind.FORECAST,
            target="temperature",
            subject_id="p1",
            as_known_at="2026-01-01T09:00:00+00:00",
            horizon_hours=24,
        )
    )
    after = query(engine, "temperature", "2026-01-01T09:00:00+00:00").to_dict()
    assert result.status is ResultStatus.UNSUPPORTED
    assert result.capability == "unsupported"
    assert before == after
