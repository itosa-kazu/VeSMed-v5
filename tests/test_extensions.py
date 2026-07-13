from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prototype.contract import (
    ClockSet,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
)
from prototype.kernel import ClinicalKernel, RoutedQuery, Subkernel


ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = ROOT / "examples" / "extensions"

DISEASE_FILE = EXTENSIONS / "disease_acute_kidney_injury_architecture_toy.json"
INTERVENTION_FILE = EXTENSIONS / "intervention_norepinephrine_architecture_toy.json"
TASK_FILE = EXTENSIONS / "task_projection_renal_safety_review.json"
TEST_METHOD_FILE = EXTENSIONS / "test_method_cystatin_c_architecture_toy.json"


def load_module(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def artifact(
    source_id: str,
    concept: str,
    value: Any,
    role: SemanticRole,
    *,
    unit: str | None = None,
) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=f"artifact-{source_id}",
        source_id=source_id,
        semantic_role=role,
        concept=concept,
        scope=Scope("extension-patient", encounter_id="extension-encounter"),
        clocks=ClockSet(
            "2026-01-01T08:00:00Z",
            None,
            "2026-01-01T08:00:00Z",
            "2026-01-01T08:05:00Z",
            "2026-01-01T08:05:00Z",
        ),
        value=value,
        unit=unit,
    )


def probability(result: Any, value: float) -> float:
    return next(
        row["probability"]
        for row in result.value["probability"]
        if row["value"] == value
    )


def evidence_semantics(result: Any) -> dict[str, Any]:
    """The stable evidence answer, excluding the auditable registry version set.

    Adding a module is expected to change ``result.versions.modules`` because the
    registry cut really changed.  It must not change an unrelated old claim,
    root, value, status or time cut.
    """

    return {
        "status": result.status.value,
        "capability": result.capability,
        "epistemic": result.epistemic,
        "coverage_status": result.coverage_status,
        "value_kind": result.value_kind,
        "value": result.value,
        "time_cut": result.time_cut,
        "evidence_witness": result.evidence_witness,
    }


def model_semantics(result: Any) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "capability": result.capability,
        "coverage_status": result.coverage_status,
        "identification": result.identification,
        "value_kind": result.value_kind,
        "value": result.value,
        "evidence_witness": result.evidence_witness,
        "native_kernel": result.native_witness.get("kernel"),
    }


def baseline_query() -> QuerySpec:
    return QuerySpec(
        "extension-baseline",
        QueryKind.PROJECT,
        "*",
        "extension-patient",
        "2026-01-02T00:00:00Z",
    )


def disease_query() -> RoutedQuery:
    return RoutedQuery(
        Subkernel.CAUSAL_STATE,
        QuerySpec(
            "extension-disease-query",
            QueryKind.FILTER,
            "disease-acute-kidney-injury-architecture-toy::AKI",
            "extension-patient",
            "2026-01-02T00:00:00Z",
            model_version="1.0.0",
            requested_guarantees=("solver_diagnostics",),
        ),
    )


def test_four_json_packages_register_through_the_public_typed_api() -> None:
    kernel = ClinicalKernel()
    expected_routes = {
        DISEASE_FILE: "causal_state",
        INTERVENTION_FILE: "causal_state",
        TASK_FILE: "evidence",
        TEST_METHOD_FILE: "evidence",
    }

    for path, expected_route in expected_routes.items():
        payload = load_module(path)
        receipt = kernel.register_module(payload)
        assert receipt.status is ResultStatus.OK, receipt.to_dict()
        assert receipt.native_witness["capability_origin"]["subkernel"] == expected_route
        assert receipt.native_witness["closed_ir"] is True


def test_extension_blast_radius_is_local_and_old_answers_do_not_change() -> None:
    kernel = ClinicalKernel()
    for item in (
        artifact("creatinine", "serum_creatinine", 2.1, SemanticRole.RAW_OBSERVATION, unit="mg/dL"),
        artifact("fatigue", "fatigue_presence", True, SemanticRole.SUBJECT_STATEMENT),
        artifact(
            "planned-nephrotoxin",
            "nephrotoxic_medication_exposure",
            True,
            SemanticRole.PLAN,
        ),
    ):
        assert kernel.ingest(item).status is ResultStatus.OK

    old_evidence = kernel.query(baseline_query())
    old_evidence_semantics = evidence_semantics(old_evidence)

    disease_receipt = kernel.register_module(load_module(DISEASE_FILE))
    assert disease_receipt.status is ResultStatus.OK
    disease_before_other_extension = kernel.query(disease_query())
    assert disease_before_other_extension.status is ResultStatus.OK
    assert probability(disease_before_other_extension, 1.0) == 0.2
    assert evidence_semantics(kernel.query(baseline_query())) == old_evidence_semantics

    intervention_receipt = kernel.register_module(load_module(INTERVENTION_FILE))
    assert intervention_receipt.status is ResultStatus.OK
    # Registering a distinct intervention module does not perturb the existing
    # disease coordinate when the caller names the module explicitly.
    assert model_semantics(kernel.query(disease_query())) == model_semantics(
        disease_before_other_extension
    )
    assert evidence_semantics(kernel.query(baseline_query())) == old_evidence_semantics

    do_result = kernel.query(
        RoutedQuery(
            Subkernel.CAUSAL_STATE,
            QuerySpec(
                "extension-intervention-query",
                QueryKind.INTERVENE,
                "intervention-norepinephrine-architecture-toy::MAP_RESPONSE",
                "extension-patient",
                "2026-01-02T00:00:00Z",
                task="population",
                model_version="1.0.0",
                intervention={"NOREPINEPHRINE": 1},
                requested_guarantees=("solver_diagnostics",),
            ),
        )
    )
    assert do_result.status is ResultStatus.OK
    assert probability(do_result, 1.0) == 0.4
    assert do_result.value["query_semantics"] == "population_do_intervention"

    task_receipt = kernel.register_module(load_module(TASK_FILE))
    assert task_receipt.status is ResultStatus.OK
    after_task = kernel.query(baseline_query())
    assert evidence_semantics(after_task) == old_evidence_semantics
    # The module registry version is allowed—and required—to reveal the new
    # extension even though the unrelated answer is semantically unchanged.
    assert after_task.versions["modules"] == {
        "task-projection-renal-safety-review": "1.0.0"
    }

    projected = kernel.query(
        QuerySpec(
            "extension-task-query",
            QueryKind.PROJECT,
            "*",
            "extension-patient",
            "2026-01-02T00:00:00Z",
            task="renal_safety_review_v1",
        )
    )
    assert projected.status is ResultStatus.OK
    claims = projected.value["claims"]
    assert [(claim["concept"], claim["semantic_role"]) for claim in claims] == [
        ("serum_creatinine", "raw_observation")
    ]


def test_new_test_method_maps_only_matching_method_and_preserves_one_root() -> None:
    kernel = ClinicalKernel()
    receipt = kernel.register_module(load_module(TEST_METHOD_FILE))
    assert receipt.status is ResultStatus.OK

    matching = artifact(
        "cystatin-c-method-root",
        "raw_cystatin_c_measurement",
        1.2,
        SemanticRole.RAW_OBSERVATION,
        unit="mg/L",
    )
    # SourceArtifact is immutable; construct the method-qualified variant
    # explicitly rather than smuggling method identity into the concept name.
    matching = SourceArtifact(
        artifact_id=matching.artifact_id,
        source_id=matching.source_id,
        semantic_role=matching.semantic_role,
        concept=matching.concept,
        scope=matching.scope,
        clocks=matching.clocks,
        information_state=matching.information_state,
        value=matching.value,
        unit=matching.unit,
        method="particle_enhanced_turbidimetric_assay",
    )
    nonmatching = SourceArtifact(
        artifact_id="artifact-cystatin-c-other-root",
        source_id="cystatin-c-other-root",
        semantic_role=SemanticRole.RAW_OBSERVATION,
        concept="raw_cystatin_c_measurement",
        scope=matching.scope,
        clocks=matching.clocks,
        information_state=matching.information_state,
        value=9.9,
        unit="mg/L",
        method="different_assay_method",
    )
    assert kernel.ingest(matching).status is ResultStatus.OK
    assert kernel.ingest(nonmatching).status is ResultStatus.OK

    result = kernel.query(
        RoutedQuery(
            Subkernel.EVIDENCE,
            QuerySpec(
                "extension-test-method-query",
                QueryKind.PROJECT,
                "serum_cystatin_c",
                "extension-patient",
                "2026-01-02T00:00:00Z",
            ),
        )
    )
    assert result.status is ResultStatus.OK
    claims = result.value["claims"]
    assert len(claims) == 1
    assert claims[0]["value"] == 1.2
    assert claims[0]["unit"] == "mg/L"
    assert claims[0]["root_sources"] == ["cystatin-c-method-root"]


def test_measurable_footprint_has_no_extension_specific_core_branch() -> None:
    disease = load_module(DISEASE_FILE)
    intervention = load_module(INTERVENTION_FILE)
    task = load_module(TASK_FILE)
    test_method = load_module(TEST_METHOD_FILE)

    # Primitive/authoring footprint: finite and directly countable from each
    # closed package, rather than hidden in new interpreter branches.
    assert {
        "disease_variables": len(disease["variables"]),
        "disease_probability_blocks": sum(
            len(disease[name]) for name in ("initial", "transitions", "emissions")
        ),
        "intervention_variables": len(intervention["variables"]),
        "intervention_equations": len(intervention["equations"]),
        "new_task_projections": len(task["projections"]),
        "new_test_method_rules": len(test_method["rules"]),
    } == {
        "disease_variables": 2,
        "disease_probability_blocks": 3,
        "intervention_variables": 3,
        "intervention_equations": 2,
        "new_task_projections": 1,
        "new_test_method_rules": 1,
    }

    # Zero extension identifiers in the reusable runtime is a mechanically
    # checkable proxy for zero extension-specific if/dispatch branches.
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "prototype").rglob("*.py"))
    )
    for module_id in (
        disease["module_id"],
        intervention["module_id"],
        task["module_id"],
        test_method["module_id"],
    ):
        assert module_id not in runtime_text
