"""Five small, auditable demonstrations of the K0 reference kernel.

Run with::

    python -m prototype.demo
"""

from __future__ import annotations

import json
from typing import Any

from .candidates.causal_state import DynamicModule
from .candidates.rewrite_open import (
    ConclusionTemplate,
    FactPremise,
    GuardOperator,
    NumericGuard,
    RewriteModule,
    RewriteRule,
    TermKind,
)
from .candidates.temporal_ledger import TemporalRuleModule
from .contract import ClockSet, QueryKind, QuerySpec, Scope, SemanticRole, SourceArtifact
from .kernel import (
    BridgeTransform,
    BridgedQuery,
    ClinicalKernel,
    EvidenceModelBridge,
    RoutedQuery,
    Subkernel,
)


def _var(name: str) -> dict[str, object]:
    return {"op": "var", "value": name}


def _op(name: str, *args: object) -> dict[str, object]:
    return {"op": name, "args": list(args)}


def _evidence_module() -> TemporalRuleModule:
    return TemporalRuleModule.from_data(
        {
            "module_id": "fever-evidence",
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


def _rewrite_module() -> RewriteModule:
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


def _state_module() -> DynamicModule:
    p_next = _op("add", 0.1, _op("mul", 0.8, _var("prev__I")))
    p_seen = _op("add", 0.1, _op("mul", 0.8, _var("state__I")))
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
                        {"value": 0, "probability": _op("sub", 1, p_next)},
                        {"value": 1, "probability": p_next},
                    ],
                }
            ],
            "emissions": [
                {
                    "target": "F",
                    "masses": [
                        {"value": 0, "probability": _op("sub", 1, p_seen)},
                        {"value": 1, "probability": p_seen},
                    ],
                }
            ],
        }
    )


def _artifact() -> SourceArtifact:
    return SourceArtifact(
        artifact_id="artifact-thermometer",
        source_id="thermometer",
        semantic_role=SemanticRole.RAW_OBSERVATION,
        concept="temperature",
        scope=Scope("patient-demo", encounter_id="encounter-demo"),
        clocks=ClockSet(
            "2026-01-01T08:00:00Z",
            None,
            "2026-01-01T08:00:00Z",
            "2026-01-01T08:05:00Z",
            "2026-01-01T08:05:00Z",
        ),
        value=39.0,
        unit="Cel",
        raw_payload={"source_text": "temperature 39.0 Cel"},
    )


def _hypothesis_artifact() -> SourceArtifact:
    """A typed, deliberately content-neutral hypothesis for projection demos.

    ``candidate-H`` is an opaque demonstration token.  The demo does not claim
    that the temperature observation supports it, nor that it is clinically
    correct.  Its only purpose is to make the role partition visible.
    """

    return SourceArtifact(
        artifact_id="artifact-hypothesis",
        source_id="hypothesis-record",
        semantic_role=SemanticRole.HYPOTHESIS,
        concept="review_hypothesis",
        scope=Scope("patient-demo", encounter_id="encounter-demo"),
        clocks=ClockSet(
            "2026-01-01T08:10:00Z",
            None,
            None,
            "2026-01-01T08:20:00Z",
            "2026-01-01T08:20:00Z",
        ),
        value="candidate-H",
        context={"demonstration_only": True, "asserted_clinical_truth": False},
        raw_payload={"source_text": "opaque hypothesis token candidate-H"},
    )


def _performed_exposure_artifact() -> SourceArtifact:
    """A role-qualified performed-event token with no effect semantics."""

    return SourceArtifact(
        artifact_id="artifact-exposure",
        source_id="performed-exposure-record",
        semantic_role=SemanticRole.PERFORMED_INTERVENTION,
        concept="recorded_exposure",
        scope=Scope("patient-demo", encounter_id="encounter-demo"),
        clocks=ClockSet(
            "2026-01-01T08:12:00Z",
            None,
            None,
            "2026-01-01T08:13:00Z",
            "2026-01-01T08:13:00Z",
        ),
        value="exposure-X",
        context={"demonstration_only": True, "effect_claimed": False},
        raw_payload={"source_text": "opaque performed exposure token exposure-X"},
    )


def _late_artifact() -> SourceArtifact:
    """An observation whose event time predates its availability time."""

    return SourceArtifact(
        artifact_id="artifact-late-measurement",
        source_id="late-measurement-record",
        semantic_role=SemanticRole.RAW_OBSERVATION,
        concept="late_arriving_measurement",
        scope=Scope("patient-demo", encounter_id="encounter-demo"),
        clocks=ClockSet(
            "2026-01-01T08:15:00Z",
            None,
            "2026-01-01T08:15:00Z",
            "2026-01-01T10:00:00Z",
            "2026-01-01T10:00:00Z",
        ),
        value=1.0,
        unit="arb",
        context={"demonstration_only": True},
        raw_payload={"source_text": "late_arriving_measurement=1.0 arb"},
    )


def _short(result: Any) -> dict[str, Any]:
    origin = result.native_witness.get("capability_origin", {})
    return {
        "status": result.status.value,
        "capability": result.capability,
        "value_kind": result.value_kind,
        "value": result.value,
        "origin": origin,
        "versions": result.versions,
        "time_cut": result.time_cut,
        "coverage": result.coverage,
        "evidence_witness": result.evidence_witness,
        "diagnostics": result.diagnostics,
    }


def _claim_roles(result: Any) -> dict[str, list[str]]:
    """Compact role/concept audit view for a temporal task projection."""

    claims = result.value.get("claims", []) if isinstance(result.value, dict) else []
    return {
        "concepts": sorted({str(claim["concept"]) for claim in claims}),
        "semantic_roles": sorted({str(claim["semantic_role"]) for claim in claims}),
    }


def run_demo() -> dict[str, Any]:
    kernel = ClinicalKernel()
    kernel.register_module(_evidence_module())
    kernel.register_module(_rewrite_module())
    kernel.register_module(_state_module())
    kernel.register_bridge(
        EvidenceModelBridge(
            bridge_id="fever-to-state",
            version="1",
            registered_at="2025-12-01T00:00:00Z",
            source_concept="fever",
            target_concept="fever_signal",
            transform=BridgeTransform.BOOLEAN_TO_BINARY,
        )
    )
    ingest = kernel.ingest(_artifact())
    hypothesis_ingest = kernel.ingest(_hypothesis_artifact())
    exposure_ingest = kernel.ingest(_performed_exposure_artifact())
    late_ingest = kernel.ingest(_late_artifact())

    evidence_spec = QuerySpec(
        "demo-evidence",
        QueryKind.PROJECT,
        "fever",
        "patient-demo",
        "2026-01-01T09:00:00Z",
        valid_at="2026-01-01T08:30:00Z",
    )
    model_spec = QuerySpec(
        "demo-causal-coordinate",
        QueryKind.FILTER,
        "inflammation::I",
        "patient-demo",
        "2026-01-01T09:00:00Z",
        valid_at="2026-01-01T08:30:00Z",
    )
    evidence = kernel.query(RoutedQuery(Subkernel.EVIDENCE, evidence_spec))
    rewrite = kernel.query(
        RoutedQuery(
            Subkernel.REWRITE_OPEN,
            QuerySpec(
                "demo-rewrite",
                QueryKind.PROJECT,
                "rewrite_fever",
                "patient-demo",
                "2026-01-01T09:00:00Z",
            ),
        )
    )
    causal = kernel.query_through_bridge(
        BridgedQuery("fever-to-state", "1", evidence_spec, model_spec)
    )

    # Two read-only task projections over the same evidence store, target,
    # subject, event-time point and knowledge cut.  Only ``task`` (and the
    # receipt id) differs.  The diagnosis projection is allowed to surface a
    # typed HYPOTHESIS; medication_safety deliberately excludes that role.
    shared_projection_contract = {
        "kind": QueryKind.PROJECT.value,
        "target": "*",
        "subject_id": "patient-demo",
        "as_known_at": "2026-01-01T09:00:00Z",
        "valid_at": "2026-01-01T08:30:00Z",
        "knowledge_version": "knowledge-v1",
    }
    source_before = kernel.query(
        RoutedQuery(
            Subkernel.EVIDENCE,
            QuerySpec(
                "demo-projection-source-before",
                QueryKind.PROJECT,
                "*",
                "patient-demo",
                "2026-01-01T09:00:00Z",
                valid_at="2026-01-01T08:30:00Z",
                task="audit",
            ),
        )
    )
    diagnosis_projection = kernel.query(
        RoutedQuery(
            Subkernel.EVIDENCE,
            QuerySpec(
                "demo-diagnosis-projection",
                QueryKind.PROJECT,
                "*",
                "patient-demo",
                "2026-01-01T09:00:00Z",
                valid_at="2026-01-01T08:30:00Z",
                task="diagnosis",
            ),
        )
    )
    medication_safety_projection = kernel.query(
        RoutedQuery(
            Subkernel.EVIDENCE,
            QuerySpec(
                "demo-medication-safety-projection",
                QueryKind.PROJECT,
                "*",
                "patient-demo",
                "2026-01-01T09:00:00Z",
                valid_at="2026-01-01T08:30:00Z",
                task="medication_safety",
            ),
        )
    )
    source_after = kernel.query(
        RoutedQuery(
            Subkernel.EVIDENCE,
            QuerySpec(
                "demo-projection-source-after",
                QueryKind.PROJECT,
                "*",
                "patient-demo",
                "2026-01-01T09:00:00Z",
                valid_at="2026-01-01T08:30:00Z",
                task="audit",
            ),
        )
    )

    # The late observation has an event time of 08:15 but is not available or
    # recorded until 10:00.  An as-known-at cut at 09:00 must not see it; an
    # otherwise identical cut at 11:00 may see it.
    late_before = kernel.query(
        RoutedQuery(
            Subkernel.EVIDENCE,
            QuerySpec(
                "demo-late-before",
                QueryKind.PROJECT,
                "late_arriving_measurement",
                "patient-demo",
                "2026-01-01T09:00:00Z",
                valid_at="2026-01-01T08:30:00Z",
                task="observation",
            ),
        )
    )
    late_after = kernel.query(
        RoutedQuery(
            Subkernel.EVIDENCE,
            QuerySpec(
                "demo-late-after",
                QueryKind.PROJECT,
                "late_arriving_measurement",
                "patient-demo",
                "2026-01-01T11:00:00Z",
                valid_at="2026-01-01T08:30:00Z",
                task="observation",
            ),
        )
    )

    # Extension: a new closed rule module is registered; no kernel code changes.
    extension_receipt = kernel.register_module(
        TemporalRuleModule.from_data(
            {
                "module_id": "review-extension",
                "version": "1",
                "registered_at": "2025-12-02T00:00:00Z",
                "rules": [
                    {
                        "rule_id": "fever-to-review",
                        "premises": [{"concept": "fever", "equals": True}],
                        "conclusion": {"concept": "needs_clinician_review", "value": True},
                    }
                ],
            }
        )
    )
    extension_result = kernel.query(
        QuerySpec(
            "demo-extension",
            QueryKind.PROJECT,
            "needs_clinician_review",
            "patient-demo",
            "2026-01-01T09:00:00Z",
        )
    )

    # Refusal: a DBN filter/forecast is not silently relabelled as a same-patient
    # counterfactual.  The native state kernel returns UNSUPPORTED.
    unsupported = kernel.query_through_bridge(
        BridgedQuery(
            "fever-to-state",
            "1",
            QuerySpec(
                "demo-evidence-for-refusal",
                QueryKind.PROJECT,
                "fever",
                "patient-demo",
                "2026-01-01T09:00:00Z",
                valid_at="2026-01-01T08:30:00Z",
            ),
            QuerySpec(
                "demo-refusal",
                QueryKind.COUNTERFACTUAL,
                "inflammation::I",
                "patient-demo",
                "2026-01-01T09:00:00Z",
                intervention={"I": 0},
            ),
        )
    )

    return {
        "demo_1_raw_to_distinct_coordinates": {
            "ingest": _short(ingest),
            "evidence_coordinate": _short(evidence),
            "rewrite_coordinate": _short(rewrite),
            "causal_state_coordinate": _short(causal),
            "note": "These are linked coordinates with different native semantics, not one PatientState.",
        },
        "demo_2_read_only_task_projections": {
            "shared_artifact_ingests": {
                "hypothesis": _short(hypothesis_ingest),
                "performed_exposure": _short(exposure_ingest),
                "late_measurement": _short(late_ingest),
            },
            "shared_query_contract_except_task_and_query_id": shared_projection_contract,
            "diagnosis": {
                "task": "diagnosis",
                "result": _short(diagnosis_projection),
                "claim_partition": _claim_roles(diagnosis_projection),
            },
            "medication_safety": {
                "task": "medication_safety",
                "result": _short(medication_safety_projection),
                "claim_partition": _claim_roles(medication_safety_projection),
            },
            "source_of_record_unchanged": source_before.value == source_after.value,
            "note": (
                "The opaque hypothesis/exposure tokens assert no medical effect. "
                "The task views differ only by a registered semantic-role projection; "
                "this is role eligibility, not a clinical relevance classifier."
            ),
        },
        "demo_3_late_evidence_and_time_cut": {
            "event_time": "2026-01-01T08:15:00Z",
            "available_and_recorded_at": "2026-01-01T10:00:00Z",
            "as_known_at_09_00": _short(late_before),
            "as_known_at_11_00": _short(late_after),
            "note": "The later cut sees the same stored artifact; the earlier cut remains historically blind.",
        },
        "demo_4_extension_without_core_change": {
            "registration": _short(extension_receipt),
            "result": _short(extension_result),
        },
        "demo_5_honest_refusal": _short(unsupported),
    }


def main() -> None:
    print(json.dumps(run_demo(), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
