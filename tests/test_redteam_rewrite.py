from __future__ import annotations

import json

import pytest

from prototype.candidates.rewrite_open import (
    ActionPhase,
    ActionPremise,
    ConclusionMode,
    ConclusionTemplate,
    RewriteModule,
    RewriteOpenCandidate,
    RewriteRule,
    RuleOutputSemantics,
)
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
    role: SemanticRole = SemanticRole.RAW_OBSERVATION,
    state: InfoState = InfoState.PRESENT,
    effective_start: str = "2026-01-01T08:00:00Z",
    effective_end: str | None = None,
    available_at: str = "2026-01-01T08:01:00Z",
    recorded_at: str = "2026-01-01T08:01:00Z",
    unit: str | None = None,
    context: dict[str, object] | None = None,
    raw_payload: dict[str, object] | None = None,
    supersedes: str | None = None,
) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=f"artifact-{source_id}",
        source_id=source_id,
        semantic_role=role,
        concept=concept,
        scope=Scope("p1"),
        clocks=ClockSet(
            effective_start,
            effective_end,
            effective_start,
            available_at,
            recorded_at,
        ),
        information_state=state,
        value=value,
        unit=unit,
        context={} if context is None else context,
        raw_payload={} if raw_payload is None else raw_payload,
        supersedes=supersedes,
    )


def query(
    engine: RewriteOpenCandidate,
    target: str,
    *,
    query_id: str = "q",
    known: str = "2026-01-01T12:00:00Z",
    valid: str = "2026-01-01T08:30:00Z",
    knowledge_version: str = "knowledge-v1",
    model_version: str | None = None,
    task: str | None = None,
    guarantees: tuple[str, ...] = (),
) -> object:
    return engine.query(
        QuerySpec(
            query_id,
            QueryKind.PROJECT,
            target,
            "p1",
            known,
            valid_at=valid,
            knowledge_version=knowledge_version,
            model_version=model_version,
            task=task,
            requested_guarantees=guarantees,
        )
    )


def effect_module() -> RewriteModule:
    return RewriteModule(
        "effect",
        "1",
        (
            RewriteRule(
                "performed-to-effect",
                (ActionPremise("drug", phases=(ActionPhase.PERFORMED,)),),
                ConclusionTemplate("drug_effect"),
                output_semantics=RuleOutputSemantics.STATE_EFFECT,
            ),
        ),
    )


@pytest.mark.parametrize(
    "masked",
    [
        artifact(
            "masked-state",
            "sensitive_note",
            "DO-NOT-DISCLOSE-SOURCE-TEXT",
            state=InfoState.MASKED,
            raw_payload={"source_text": "DO-NOT-DISCLOSE-RAW"},
        ),
        artifact(
            "masked-role",
            "sensitive_note",
            "DO-NOT-DISCLOSE-SOURCE-TEXT",
            role=SemanticRole.MASKED_ARTIFACT,
            raw_payload={"source_text": "DO-NOT-DISCLOSE-RAW"},
        ),
        artifact(
            "withheld-policy",
            "sensitive_note",
            "DO-NOT-DISCLOSE-SOURCE-TEXT",
            context={"withheld": True},
            raw_payload={"source_text": "DO-NOT-DISCLOSE-RAW"},
        ),
    ],
)
def test_masked_or_withheld_source_bytes_never_enter_witness(masked: SourceArtifact) -> None:
    engine = RewriteOpenCandidate()
    receipt = engine.ingest(masked)
    assert receipt.status is ResultStatus.OK
    result = query(engine, "sensitive_note")
    serialized = json.dumps(
        {"receipt": receipt.to_dict(), "query": result.to_dict()},
        sort_keys=True,
    )
    assert "DO-NOT-DISCLOSE-SOURCE-TEXT" not in serialized
    assert "DO-NOT-DISCLOSE-RAW" not in serialized
    assert "raw_payload\"" not in serialized
    assert result.value["claims"][0]["term"]["information_state"] == "masked"


def test_preflight_rejects_nonexact_json_before_deepcopy_and_nested_callables() -> None:
    copied = False

    class BombDict(dict):
        def __deepcopy__(self, memo: object) -> object:  # pragma: no cover - must not run
            nonlocal copied
            copied = True
            raise AssertionError("attacker-controlled deepcopy executed")

    bad = artifact("bomb", "x", True, raw_payload={"x": 1})
    object.__setattr__(bad, "raw_payload", BombDict({"x": 1}))
    engine = RewriteOpenCandidate()
    result = engine.ingest(bad)
    assert result.status is ResultStatus.INVALID
    assert copied is False

    nested_callback = artifact("callback", "x", True)
    object.__setattr__(
        nested_callback,
        "raw_payload",
        {"nested": {"callback": lambda: None}},
    )
    result = engine.ingest(nested_callback)
    assert result.status is ResultStatus.INVALID
    assert result.diagnostics["quarantined"] is True


def test_nested_callable_and_corrupted_enum_in_closed_module_are_rejected() -> None:
    callback_conclusion = ConclusionTemplate(
        "derived",
        mode=ConclusionMode.TEXT,
        text=lambda: "foreign code",  # type: ignore[arg-type]
    )
    module = RewriteModule(
        "bad-callback",
        "1",
        (RewriteRule("r", (ActionPremise("drug"),), callback_conclusion),),
    )
    engine = RewriteOpenCandidate()
    assert engine.register_module(module).status is ResultStatus.INVALID

    corrupt = ConclusionTemplate("derived")
    object.__setattr__(corrupt, "mode", "presence")
    corrupt_module = RewriteModule(
        "bad-enum",
        "1",
        (RewriteRule("r", (ActionPremise("drug"),), corrupt),),
    )
    assert engine.register_module(corrupt_module).status is ResultStatus.INVALID


def test_clean_rebuild_preserves_artifact_and_tombstone_history() -> None:
    engine = RewriteOpenCandidate()
    assert engine.ingest(artifact("root", "finding", True)).status is ResultStatus.OK
    predated = engine.retract("root", "2026-01-01T07:59:00Z")
    assert predated.status is ResultStatus.INVALID
    assert query(engine, "finding", known="2026-01-01T09:00:00Z").status is ResultStatus.OK

    assert engine.retract("root", "2026-01-01T10:00:00Z").status is ResultStatus.OK
    rebuilt = engine.clean_rebuild()
    assert query(engine, "finding", query_id="old-a", known="2026-01-01T09:00:00Z").status is ResultStatus.OK
    assert query(rebuilt, "finding", query_id="old-b", known="2026-01-01T09:00:00Z").status is ResultStatus.OK
    assert query(engine, "finding", query_id="new-a", known="2026-01-01T11:00:00Z").status is ResultStatus.INSUFFICIENT
    assert query(rebuilt, "finding", query_id="new-b", known="2026-01-01T11:00:00Z").status is ResultStatus.INSUFFICIENT


def test_clean_rebuild_preserves_pre_correction_cut() -> None:
    engine = RewriteOpenCandidate()
    engine.ingest(artifact("original", "temperature", 38.0, unit="Cel"))
    engine.ingest(
        artifact(
            "correction",
            "temperature",
            37.0,
            unit="Cel",
            available_at="2026-01-01T10:00:00Z",
            recorded_at="2026-01-01T10:00:00Z",
            supersedes="original",
        )
    )
    rebuilt = engine.clean_rebuild()
    before = query(rebuilt, "temperature", known="2026-01-01T09:00:00Z")
    after = query(rebuilt, "temperature", known="2026-01-01T11:00:00Z")
    assert before.value["claims"][0]["term"]["magnitude"] == 38.0
    assert after.value["claims"][0]["term"]["magnitude"] == 37.0


def test_only_stop_or_cancel_close_effect_and_invalid_lifecycle_taints_effect_query() -> None:
    later_plan = RewriteOpenCandidate()
    later_plan.register_module(effect_module())
    later_plan.ingest(
        artifact(
            "performed",
            "drug",
            True,
            role=SemanticRole.PERFORMED_INTERVENTION,
            context={"action_id": "a1", "phase": "performed"},
        )
    )
    later_plan.ingest(
        artifact(
            "later-plan",
            "drug",
            True,
            role=SemanticRole.PLAN,
            context={"action_id": "a1", "phase": "planned"},
            effective_start="2026-01-01T09:00:00Z",
            available_at="2026-01-01T09:00:00Z",
            recorded_at="2026-01-01T09:00:00Z",
        )
    )
    result = query(later_plan, "drug_effect", valid="2026-01-01T09:30:00Z")
    assert result.status is ResultStatus.INVALID
    assert result.epistemic == "conflicting"
    # The later plan did not secretly close the historical performed effect.
    assert result.value["claims"]

    for phase, expected in (("stopped", ResultStatus.INSUFFICIENT), ("cancelled", ResultStatus.INSUFFICIENT)):
        closed = RewriteOpenCandidate()
        closed.register_module(effect_module())
        closed.ingest(
            artifact(
                f"performed-{phase}",
                "drug",
                True,
                role=SemanticRole.PERFORMED_INTERVENTION,
                context={"action_id": "a1", "phase": "performed"},
            )
        )
        closed.ingest(
            artifact(
                phase,
                "drug",
                True,
                role=SemanticRole.STOPPED_INTERVENTION,
                context={"action_id": "a1", "phase": phase},
                effective_start="2026-01-01T09:00:00Z",
                available_at="2026-01-01T09:00:00Z",
                recorded_at="2026-01-01T09:00:00Z",
            )
        )
        assert query(closed, "drug_effect", valid="2026-01-01T09:30:00Z").status is expected


def test_same_coordinate_different_values_are_explicit_conflict() -> None:
    engine = RewriteOpenCandidate()
    engine.ingest(artifact("lab-a", "temperature", 38.0, unit="Cel"))
    engine.ingest(artifact("lab-b", "temperature", 39.0, unit="Cel"))
    result = query(engine, "temperature")
    assert result.status is ResultStatus.CONFLICTING
    assert result.value["conflicts"][0]["conflict_type"] == "same_coordinate_value_disagreement"
    assert len(result.value["conflicts"][0]["variants"]) == 2

    longitudinal = RewriteOpenCandidate()
    longitudinal.ingest(artifact("early", "temperature", 38.0, unit="Cel"))
    longitudinal.ingest(
        artifact(
            "later",
            "temperature",
            39.0,
            unit="Cel",
            effective_start="2026-01-01T08:15:00Z",
            available_at="2026-01-01T08:16:00Z",
            recorded_at="2026-01-01T08:16:00Z",
        )
    )
    assert query(longitudinal, "temperature").status is ResultStatus.OK


def test_effective_end_is_half_open_for_facts_and_effect_tokens() -> None:
    engine = RewriteOpenCandidate()
    engine.ingest(
        artifact(
            "finite",
            "finding",
            True,
            effective_end="2026-01-01T09:00:00Z",
        )
    )
    assert query(engine, "finding", valid="2026-01-01T08:59:59Z").status is ResultStatus.OK
    assert query(engine, "finding", valid="2026-01-01T09:00:00Z").status is ResultStatus.INSUFFICIENT

    action = RewriteOpenCandidate()
    action.register_module(effect_module())
    action.ingest(
        artifact(
            "finite-action",
            "drug",
            True,
            role=SemanticRole.PERFORMED_INTERVENTION,
            context={"action_id": "a1", "phase": "performed"},
            effective_end="2026-01-01T09:00:00Z",
        )
    )
    assert query(action, "drug_effect", valid="2026-01-01T08:59:59Z").status is ResultStatus.OK
    assert query(action, "drug_effect", valid="2026-01-01T09:00:00Z").status is ResultStatus.INSUFFICIENT


@pytest.mark.parametrize(
    ("kwargs", "diagnostic_key"),
    [
        ({"knowledge_version": "knowledge-does-not-exist"}, "knowledge_version"),
        ({"model_version": "model-does-not-exist"}, "model_version"),
        ({"task": "unregistered-task"}, "task"),
        ({"guarantees": ("unimplemented-guarantee",)}, "requested_guarantees"),
    ],
)
def test_unknown_query_controls_are_typed_unsupported(
    kwargs: dict[str, object], diagnostic_key: str
) -> None:
    result = query(RewriteOpenCandidate(), "x", **kwargs)
    assert result.status is ResultStatus.UNSUPPORTED
    assert result.capability == "unsupported"
    assert result.coverage_status == "partial"
    assert diagnostic_key in result.diagnostics["unsupported_controls"]


def test_wrong_enum_inputs_return_typed_invalid_instead_of_crashing() -> None:
    engine = RewriteOpenCandidate()
    bad_query = QuerySpec(
        "bad-query",
        QueryKind.PROJECT,
        "x",
        "p1",
        "2026-01-01T09:00:00Z",
    )
    object.__setattr__(bad_query, "kind", "project")
    assert engine.query(bad_query).status is ResultStatus.INVALID

    bad_artifact = artifact("bad-role", "x", True)
    object.__setattr__(bad_artifact, "semantic_role", "raw_observation")
    assert engine.ingest(bad_artifact).status is ResultStatus.INVALID
