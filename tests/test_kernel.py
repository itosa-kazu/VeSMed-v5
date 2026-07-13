from __future__ import annotations

from prototype.candidates.causal_state import DynamicModule
from prototype.candidates.rewrite_open import (
    ConclusionTemplate,
    FactPremise,
    GuardOperator,
    NumericGuard,
    RewriteModule,
    RewriteRule,
    TermKind,
)
from prototype.candidates.temporal_ledger import TemporalRuleModule
from prototype.contract import (
    ClockSet,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
)
from prototype.kernel import (
    BridgeTransform,
    BridgedQuery,
    ClinicalKernel,
    EvidenceModelBridge,
    RoutedQuery,
    Subkernel,
)


def var(name: str) -> dict[str, object]:
    return {"op": "var", "value": name}


def op(name: str, *args: object) -> dict[str, object]:
    return {"op": name, "args": list(args)}


def temperature_artifact() -> SourceArtifact:
    return SourceArtifact(
        artifact_id="artifact-thermometer",
        source_id="thermometer",
        semantic_role=SemanticRole.RAW_OBSERVATION,
        concept="temperature",
        scope=Scope("p1", encounter_id="e1"),
        clocks=ClockSet(
            "2026-01-01T08:00:00Z",
            None,
            "2026-01-01T08:00:00Z",
            "2026-01-01T08:05:00Z",
            "2026-01-01T08:05:00Z",
        ),
        value=39.0,
        unit="Cel",
    )


def fever_evidence_module(module_id: str = "fever-evidence") -> TemporalRuleModule:
    return TemporalRuleModule.from_data(
        {
            "module_id": module_id,
            "version": "1",
            "registered_at": "2025-12-01T00:00:00Z",
            "rules": [
                {
                    "rule_id": "temperature-to-fever",
                    "premises": [{"concept": "temperature", "min_value": 38.0, "unit": "Cel"}],
                    "conclusion": {"concept": "fever", "value": True},
                }
            ],
        }
    )


def fever_rewrite_module() -> RewriteModule:
    return RewriteModule(
        "fever-rewrite",
        "1",
        (
            RewriteRule(
                "temperature-to-rewrite-fever",
                (FactPremise("temperature", term_kind=TermKind.QUANTITY, unit="Cel"),),
                ConclusionTemplate("rewrite_fever"),
                guards=(NumericGuard(0, GuardOperator.GE, 38.0),),
            ),
        ),
    )


def fever_state_module() -> DynamicModule:
    p_next = op("add", 0.1, op("mul", 0.8, var("prev__I")))
    p_seen = op("add", 0.1, op("mul", 0.8, var("state__I")))
    return DynamicModule.from_data(
        {
            "kind": "dynamic",
            "module_id": "inflammation",
            "version": "1",
            "step_hours": 1,
            "variables": [
                {"name": "I", "role": "latent", "domain": [0, 1]},
                {"name": "F", "role": "observation", "domain": [0, 1], "concept": "fever_signal"},
            ],
            "initial": [
                {"target": "I", "masses": [{"value": 0, "probability": 0.5}, {"value": 1, "probability": 0.5}]}
            ],
            "transitions": [
                {
                    "target": "I",
                    "masses": [
                        {"value": 0, "probability": op("sub", 1, p_next)},
                        {"value": 1, "probability": p_next},
                    ],
                }
            ],
            "emissions": [
                {
                    "target": "F",
                    "masses": [
                        {"value": 0, "probability": op("sub", 1, p_seen)},
                        {"value": 1, "probability": p_seen},
                    ],
                }
            ],
        }
    )


def bridge() -> EvidenceModelBridge:
    return EvidenceModelBridge(
        bridge_id="fever-to-state",
        version="1",
        registered_at="2025-12-01T00:00:00Z",
        source_concept="fever",
        target_concept="fever_signal",
        transform=BridgeTransform.BOOLEAN_TO_BINARY,
    )


def evidence_query(query_id: str = "q-fever", known: str = "2026-01-01T09:00:00Z") -> QuerySpec:
    return QuerySpec(
        query_id,
        QueryKind.PROJECT,
        "fever",
        "p1",
        known,
        valid_at="2026-01-01T08:30:00Z",
    )


def model_query(query_id: str = "q-state", known: str = "2026-01-01T09:00:00Z") -> QuerySpec:
    return QuerySpec(
        query_id,
        QueryKind.FILTER,
        "inflammation::I",
        "p1",
        known,
        valid_at="2026-01-01T08:30:00Z",
    )


def probability(result: object, value: float) -> float:
    rows = result.value["probability"]  # type: ignore[attr-defined]
    return next(row["probability"] for row in rows if row["value"] == value)


def configured_kernel() -> ClinicalKernel:
    kernel = ClinicalKernel()
    assert kernel.register_module(fever_evidence_module()).status is ResultStatus.OK
    assert kernel.register_module(fever_rewrite_module()).status is ResultStatus.OK
    assert kernel.register_module(fever_state_module()).status is ResultStatus.OK
    assert kernel.register_bridge(bridge()).status is ResultStatus.OK
    assert kernel.ingest(temperature_artifact()).status is ResultStatus.OK
    return kernel


def test_explicit_routes_keep_native_states_and_capability_origins_separate() -> None:
    kernel = configured_kernel()
    evidence = kernel.query(RoutedQuery(Subkernel.EVIDENCE, evidence_query()))
    rewrite = kernel.query(
        RoutedQuery(
            Subkernel.REWRITE_OPEN,
            QuerySpec("q-rewrite", QueryKind.PROJECT, "rewrite_fever", "p1", "2026-01-01T09:00:00Z"),
        )
    )
    assert evidence.status is ResultStatus.OK
    assert rewrite.status is ResultStatus.OK
    assert evidence.native_witness["capability_origin"]["native_state_kind"] == "temporal_evidence_cut"
    assert rewrite.native_witness["capability_origin"]["native_state_kind"] == "typed_rewrite_configuration"
    assert evidence.native_witness["capability_origin"]["universal_patient_state"] is False
    assert evidence.evidence_witness["root_sources"] == ["thermometer"]
    assert rewrite.evidence_witness["root_sources"] == ["thermometer"]


def test_versioned_bridge_runs_native_model_on_fresh_evidence_cut() -> None:
    kernel = configured_kernel()
    result = kernel.query_through_bridge(
        BridgedQuery("fever-to-state", "1", evidence_query(), model_query())
    )
    assert result.status is ResultStatus.OK
    assert probability(result, 1.0) == 0.9
    assert result.native_witness["kernel"] == "finite_dbn"
    assert result.native_witness["bridge_boundary"]["callback"] is False
    assert result.native_witness["capability_origin"]["subkernel"] == "causal_state"
    assert result.evidence_witness["bridge_materialization"]["root_sources"] == ["thermometer"]
    assert result.evidence_witness["bridge_materialization"]["fresh_model_run"] is True
    assert result.versions["bridge"] == "1"
    assert result.versions["kernel"] == ClinicalKernel.VERSION


def test_retraction_blocks_new_bridge_run_instead_of_reusing_stale_model_input() -> None:
    kernel = configured_kernel()
    assert kernel.retract("thermometer", "2026-01-01T10:00:00Z").status is ResultStatus.OK
    blocked = kernel.query_through_bridge(
        BridgedQuery(
            "fever-to-state",
            "1",
            evidence_query("q-fever-after", "2026-01-01T11:00:00Z"),
            model_query("q-state-after", "2026-01-01T11:00:00Z"),
        )
    )
    assert blocked.status is ResultStatus.INSUFFICIENT
    assert blocked.native_witness["causal_kernel_invoked"] is False
    assert blocked.coverage_status == "bridge_blocked_by_upstream_evidence"


def test_new_closed_module_uses_candidate_api_without_core_change() -> None:
    kernel = configured_kernel()
    extra = TemporalRuleModule.from_data(
        {
            "module_id": "review-extension",
            "version": "1",
            "registered_at": "2025-12-02T00:00:00Z",
            "rules": [
                {
                    "rule_id": "fever-to-review",
                    "premises": [{"concept": "fever", "equals": True}],
                    "conclusion": {"concept": "needs_review", "value": True},
                }
            ],
        }
    )
    receipt = kernel.register_module(extra)
    result = kernel.query(
        QuerySpec("q-extension", QueryKind.PROJECT, "needs_review", "p1", "2026-01-01T09:00:00Z")
    )
    assert receipt.status is ResultStatus.OK
    assert result.status is ResultStatus.OK
    assert result.evidence_witness["root_sources"] == ["thermometer"]


def test_closed_boundaries_and_unsupported_semantics_fail_honestly() -> None:
    kernel = configured_kernel()
    callback = kernel.register_module(lambda value: value)
    public_string_model = kernel.register_module(
        {"module_id": "opaque", "family": "state_space", "public_model": {"dynamics": "eval(user_text)"}}
    )
    unsupported = kernel.query(
        RoutedQuery(
            Subkernel.EVIDENCE,
            QuerySpec(
                "q-not-causal",
                QueryKind.COUNTERFACTUAL,
                "fever",
                "p1",
                "2026-01-01T09:00:00Z",
                intervention={"fever": False},
            ),
        )
    )
    missing_bridge = kernel.query_through_bridge(
        BridgedQuery("fever-to-state", "999", evidence_query(), model_query("q-missing-bridge"))
    )
    assert callback.status is ResultStatus.INVALID
    assert public_string_model.status is ResultStatus.UNSUPPORTED
    assert unsupported.status is ResultStatus.UNSUPPORTED
    assert unsupported.capability == "unsupported"
    assert unsupported.native_witness["capability_origin"]["subkernel"] == "evidence"
    assert missing_bridge.status is ResultStatus.OUT_OF_MODEL


def test_candidate_api_clean_rebuild_and_kernel_explanation() -> None:
    kernel = configured_kernel()
    original = kernel.query(evidence_query("q-record"))
    explanation = kernel.explain("q-record")
    rebuilt = kernel.clean_rebuild().query(evidence_query("q-record"))
    assert explanation.status is ResultStatus.OK
    assert explanation.value["status"] == "ok"
    assert original.value == rebuilt.value
    assert original.evidence_witness == rebuilt.evidence_witness
    assert "project" in {kind.value for kind in kernel.manifest.declared_query_capabilities}
