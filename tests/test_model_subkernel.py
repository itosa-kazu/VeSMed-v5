from __future__ import annotations

import copy
import inspect

import pytest

from prototype.benchmark import BenchmarkRunner
from prototype.contract import (
    ClockSet,
    QueryKind,
    QuerySpec,
    Scope,
    SemanticRole,
    SourceArtifact,
)
from prototype.model_subkernel import ExperimentalModelSubkernel
from prototype.reference_models import public_model
from prototype.workloads import load_workloads


NOW = "2026-01-01T12:00:00Z"


def register(candidate: ExperimentalModelSubkernel, model: dict) -> object:
    return candidate.register_module(
        {
            "module_id": "public-model",
            "family": model["model_kind"],
            "public_model": copy.deepcopy(model),
        }
    )


def query(
    kind: QueryKind,
    target: str,
    *,
    task: str | None = None,
    intervention: dict | None = None,
    valid_at: str = "2026-01-01T08:00:00Z",
    as_known_at: str = NOW,
    horizon_hours: float | None = None,
) -> QuerySpec:
    return QuerySpec(
        query_id="client-request",
        kind=kind,
        target=target,
        subject_id="P1",
        as_known_at=as_known_at,
        valid_at=valid_at,
        task=task,
        intervention=intervention,
        horizon_hours=horizon_hours,
    )


def observation(source_id: str, value: float, hour: int) -> SourceArtifact:
    timestamp = f"2026-01-01T{hour:02d}:00:00Z"
    return SourceArtifact(
        artifact_id=source_id,
        source_id=source_id,
        semantic_role=SemanticRole.RAW_OBSERVATION,
        concept="mean_arterial_pressure",
        scope=Scope(subject_id="P1", encounter_id="E1"),
        clocks=ClockSet(
            effective_start=timestamp,
            effective_end=None,
            collected_at=timestamp,
            available_at=timestamp,
            recorded_at=timestamp,
        ),
        value=value,
        unit="mmHg",
        context={"performed_support_U": 1.0 if 4 <= hour < 12 else 0.0},
    )


def test_all_e_panel_models_execute_against_runner_without_hidden_judging_data() -> None:
    workloads = {key: value for key, value in load_workloads().items() if key.startswith("E")}
    runs = BenchmarkRunner(ExperimentalModelSubkernel).run_panel(workloads)
    assert set(runs) == {f"E{index:02d}" for index in range(1, 9)}
    assert all(not run.harness_errors for run in runs.values())
    assert all(run.verdict.hard == "pass" for run in runs.values())
    assert all(run.verdict.classification == "PASS" for run in runs.values())
    assert all(
        call.result.get("native_witness", {}).get("compiled_ir_hash")
        for run in runs.values()
        for call in run.calls
        if call.op == "query"
    )


def test_source_has_no_runner_model_import_or_identifier_dispatch() -> None:
    source = inspect.getsource(__import__("prototype.model_subkernel", fromlist=["*"]))
    assert "from .reference_models import" not in source
    assert "import reference_models" not in source
    assert "spec.query_id ==" not in source
    assert "workload_id ==" not in source


def test_closed_schema_rejects_callbacks_unknown_fields_and_runner_only_fields() -> None:
    base = public_model("E02")

    candidate = ExperimentalModelSubkernel()
    callback_module = {"module_id": "m", "family": "finite_scm", "public_model": base, "callback": lambda: None}
    callback_result = candidate.register_module(callback_module)
    assert callback_result.status.value == "invalid"
    assert callback_result.validation == "invalid"

    candidate = ExperimentalModelSubkernel()
    unknown = copy.deepcopy(base)
    unknown["magic_bonus"] = 10
    unknown_result = register(candidate, unknown)
    assert unknown_result.status.value == "invalid"
    assert "fields" in unknown_result.diagnostics["reason"]

    candidate = ExperimentalModelSubkernel()
    contaminated = copy.deepcopy(base)
    contaminated["expected"] = 0.325
    contaminated_result = register(candidate, contaminated)
    assert contaminated_result.status.value == "invalid"
    assert "runner-only field forbidden" in contaminated_result.diagnostics["reason"]


def test_e02_is_exact_parameter_driven_conditioning_and_intervention() -> None:
    model = public_model("E02")
    model["P_severe"] = 0.2
    candidate = ExperimentalModelSubkernel()
    registration = register(candidate, model)
    assert registration.status.value == "ok"

    observed = candidate.query(query(QueryKind.CONDITION, "Y_bad", task="T=1"))
    intervened = candidate.query(
        query(QueryKind.INTERVENE, "Y_bad", task="T=1", intervention={"variable": "T", "value": 1})
    )
    posterior_severe = 0.2 * 0.9 / (0.2 * 0.9 + 0.8 * 0.1)
    expected_observed = posterior_severe * 0.60 + (1.0 - posterior_severe) * 0.05
    expected_do = 0.2 * 0.60 + 0.8 * 0.05
    assert observed.value["probability"] == pytest.approx(expected_observed, abs=1e-14)
    assert intervened.value["probability"] == pytest.approx(expected_do, abs=1e-14)
    assert observed.value["estimand"] != intervened.value["estimand"]
    assert observed.computation == intervened.computation == "exact"


def test_e03_aap_shares_abduced_background_but_population_do_uses_prior() -> None:
    model = public_model("E03")
    model["R"]["probabilities"] = [0.3, 0.7]
    candidate = ExperimentalModelSubkernel()
    assert register(candidate, model).status.value == "ok"

    individual = candidate.query(
        query(
            QueryKind.COUNTERFACTUAL,
            "Y",
            task="individual",
            intervention={"variable": "T", "value": 0},
        )
    )
    population = candidate.query(
        query(
            QueryKind.INTERVENE,
            "Y",
            task="population",
            intervention={"variable": "T", "value": 0},
        )
    )
    assert individual.value["mean"] == pytest.approx(1.0)
    assert population.value["mean"] == pytest.approx(0.7)
    assert "share_abduced_exogenous" in individual.assumptions
    assert individual.native_witness["operator"] == "abduction_action_prediction"
    assert population.native_witness["operator"] == "population_truncated_factorization"


def test_composition_uses_every_registered_public_module_parameter() -> None:
    model = public_model("E07")
    model["input"] = -2.0
    model["modules"] = {"renal": {"delta": 0.75}, "drug": {"delta": 2.5}, "infection": {"delta": -0.25}}
    candidate = ExperimentalModelSubkernel()
    assert register(candidate, model).status.value == "ok"
    result = candidate.query(query(QueryKind.CHECK_INVARIANT, "composition_result"))
    assert result.value["result"] == pytest.approx(1.0)
    assert result.value["left_bracket"] == result.value["right_bracket"]
    assert result.value["used_modules"] == ["drug", "infection", "renal"]


def test_feedback_distinguishes_fixed_point_rootless_no_and_many() -> None:
    model = public_model("E08")
    model["contraction"] = "x_next=0.25*x+1.5"
    candidate = ExperimentalModelSubkernel()
    assert register(candidate, model).status.value == "ok"
    fixed = candidate.query(query(QueryKind.CHECK_INVARIANT, "contraction"))
    cycle = candidate.query(query(QueryKind.REACHABILITY, "rootless_support"))
    no_solution = candidate.query(query(QueryKind.CHECK_INVARIANT, "no_solution"))
    non_unique = candidate.query(query(QueryKind.CHECK_INVARIANT, "non_unique"))
    assert fixed.value["value"] == pytest.approx(2.0, abs=1e-10)
    assert cycle.value["claims"] == []
    assert cycle.evidence_witness["root_sources"] == []
    assert no_solution.computation == "no_solution"
    assert non_unique.computation == "multiple_solutions"
    assert no_solution.status.value == non_unique.status.value == "ok"


def test_retraction_clean_rebuild_and_explain_keep_auditable_semantics() -> None:
    candidate = ExperimentalModelSubkernel()
    assert register(candidate, public_model("E01")).status.value == "ok"
    assert candidate.ingest(observation("map-9", 80.0, 9)).status.value == "ok"
    filtered = candidate.query(
        query(
            QueryKind.FILTER,
            "S",
            valid_at="2026-01-01T09:00:00Z",
            as_known_at="2026-01-01T09:00:00Z",
        )
    )
    assert filtered.evidence_witness["root_sources"] == ["map-9"]
    result_id = filtered.native_witness["result_id"]
    explanation = candidate.explain(result_id)
    assert explanation.status.value == "ok"
    assert explanation.value["explained_result_id"] == result_id
    assert explanation.value["evidence_roots"] == ["map-9"]

    assert candidate.retract("map-9", NOW).status.value == "ok"
    rebuilt = candidate.clean_rebuild()
    after = rebuilt.query(
        query(
            QueryKind.FILTER,
            "S",
            valid_at="2026-01-01T09:00:00Z",
            as_known_at="2026-01-01T09:00:00Z",
        )
    )
    assert after.status.value == "ok"
    assert after.evidence_witness["root_sources"] == []
    assert after.versions["model"] == filtered.versions["model"]


def test_unsupported_query_is_typed_and_actionable() -> None:
    candidate = ExperimentalModelSubkernel()
    assert register(candidate, public_model("E07")).status.value == "ok"
    result = candidate.query(query(QueryKind.FORECAST, "composition_result", horizon_hours=1))
    assert result.status.value == "unsupported"
    assert result.capability == "unsupported"
    assert result.coverage_status == "out_of_model"
    assert result.diagnostics["failure_type"] == "unsupported_query"
