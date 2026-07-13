from __future__ import annotations

from prototype.candidates.rewrite_open import (
    ActionPhase,
    ActionPremise,
    ComponentFamily,
    CompositionSpec,
    ConclusionTemplate,
    FactPremise,
    GuardOperator,
    NumericGuard,
    OpenComponent,
    OwnershipKind,
    Port,
    PortDirection,
    PortRef,
    PortRole,
    Polarity,
    ProvenancePolicy,
    RewriteModule,
    RewriteOpenCandidate,
    RewriteRule,
    RuleOutputSemantics,
    ScopeBinding,
    TermKind,
    TimeBasis,
    UncertaintySemantics,
    Wire,
)
from prototype.contract import (
    ClockSet,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
)


def art(source: str, concept: str, value: object, role: SemanticRole = SemanticRole.RAW_OBSERVATION, unit: str | None = None) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=source,
        source_id=source,
        semantic_role=role,
        concept=concept,
        scope=Scope("p1"),
        clocks=ClockSet(
            "2026-01-01T08:00:00Z",
            None,
            "2026-01-01T08:00:00Z",
            "2026-01-01T08:01:00Z",
            "2026-01-01T08:01:00Z",
        ),
        value=value,
        unit=unit,
    )


def q(engine: RewriteOpenCandidate, target: str, at: str = "2026-01-01T09:00:00Z") -> object:
    return engine.query(QuerySpec(f"q-{target}", QueryKind.PROJECT, target, "p1", at, valid_at="2026-01-01T08:30:00Z"))


def fever_module() -> RewriteModule:
    return RewriteModule(
        "fever",
        "1",
        (
            RewriteRule(
                "temperature-to-fever",
                (FactPremise("temperature", term_kind=TermKind.QUANTITY, unit="Cel"),),
                ConclusionTemplate("fever"),
                guards=(NumericGuard(0, GuardOperator.GE, 38.0),),
            ),
        ),
    )


def test_grounded_rewrite_keeps_root_and_retraction_matches_rebuild() -> None:
    engine = RewriteOpenCandidate()
    engine.register_module(fever_module())
    engine.ingest(art("thermometer", "temperature", 39.0, unit="Cel"))
    before = q(engine, "fever")
    assert before.status is ResultStatus.OK
    assert before.value["claims"][0]["root_sources"] == ["thermometer"]
    engine.retract("thermometer", "2026-01-01T10:00:00Z")
    incremental = q(engine, "fever", "2026-01-01T11:00:00Z")
    rebuilt = q(engine.clean_rebuild(), "fever", "2026-01-01T11:00:00Z")
    assert incremental.status is ResultStatus.INSUFFICIENT
    # Rebuild origin/excluded-history diagnostics may differ; the semantic result
    # and actual witnesses must be equal.
    assert incremental.value == rebuilt.value
    assert incremental.evidence_witness == rebuilt.evidence_witness
    assert incremental.native_witness == rebuilt.native_witness


def test_rootless_epistemic_cycle_cannot_create_support() -> None:
    cycle = RewriteModule(
        "cycle",
        "1",
        (
            RewriteRule("a-to-b", (FactPremise("a"),), ConclusionTemplate("b")),
            RewriteRule("b-to-a", (FactPremise("b"),), ConclusionTemplate("a")),
        ),
    )
    engine = RewriteOpenCandidate()
    receipt = engine.register_module(cycle)
    assert receipt.status is ResultStatus.OK
    assert q(engine, "a").status is ResultStatus.INSUFFICIENT
    engine.ingest(art("root-a", "a", True))
    derived = q(engine, "b")
    assert derived.status is ResultStatus.OK
    assert derived.value["claims"][0]["root_sources"] == ["root-a"]


def test_plan_cannot_trigger_state_effect_but_performed_action_can() -> None:
    module = RewriteModule(
        "drug-effect",
        "1",
        (
            RewriteRule(
                "performed-antipyretic",
                (ActionPremise("antipyretic", phases=(ActionPhase.PERFORMED,)),),
                ConclusionTemplate("temperature_observation_suppressed"),
                output_semantics=RuleOutputSemantics.OBSERVATION_EFFECT,
            ),
        ),
    )
    planned = RewriteOpenCandidate()
    planned.register_module(module)
    planned.ingest(art("plan", "antipyretic", "planned", SemanticRole.PLAN))
    assert q(planned, "temperature_observation_suppressed").status is ResultStatus.INSUFFICIENT

    performed = RewriteOpenCandidate()
    performed.register_module(module)
    performed.ingest(art("dose", "antipyretic", "performed", SemanticRole.PERFORMED_INTERVENTION))
    result = q(performed, "temperature_observation_suppressed")
    assert result.status is ResultStatus.OK
    assert result.value["claims"][0]["root_sources"] == ["dose"]


def port(port_id: str, direction: PortDirection, unit: str) -> Port:
    return Port(
        port_id=port_id,
        direction=direction,
        role=PortRole.OBSERVATION,
        concept="creatinine",
        scope_binding=ScopeBinding.SAME_SUBJECT,
        unit=unit,
        time_basis=TimeBasis.EFFECTIVE,
        ownership=OwnershipKind.NONE,
        owner_id=None,
        uncertainty=UncertaintySemantics.FOUR_VALUED_EVIDENCE,
        provenance=ProvenancePolicy.PRESERVE_ROOTS,
    )


def test_typed_wiring_rejects_unit_mismatch_before_execution() -> None:
    engine = RewriteOpenCandidate()
    source = OpenComponent("lab", "1", ComponentFamily.EVIDENCE, output_ports=(port("out", PortDirection.OUTPUT, "mg/dL"),))
    target = OpenComponent("model", "1", ComponentFamily.REWRITE, input_ports=(port("in", PortDirection.INPUT, "umol/L"),))
    engine.register_module(source)
    engine.register_module(target)
    result = engine.compose(
        CompositionSpec("bad", ("lab", "model"), (Wire(PortRef("lab", "out"), PortRef("model", "in")),))
    )
    assert result.status is ResultStatus.INVALID
    assert "unit" in str(result.diagnostics).lower()


def test_probabilistic_queries_are_honestly_unsupported() -> None:
    engine = RewriteOpenCandidate()
    result = engine.query(QuerySpec("f", QueryKind.FORECAST, "fever", "p1", "2026-01-01T09:00:00Z", horizon_hours=24))
    assert result.status is ResultStatus.UNSUPPORTED
    assert result.capability == "unsupported"
