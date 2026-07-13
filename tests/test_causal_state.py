from __future__ import annotations

from prototype.candidates.causal_state import CausalStateCandidate, DynamicModule, FiniteSCMModule
from prototype.contract import (
    ClockSet,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
    Track,
)


def var(name: str) -> dict[str, object]:
    return {"op": "var", "value": name}


def op(name: str, *args: object) -> dict[str, object]:
    return {"op": name, "args": list(args)}


def art(
    source: str,
    role: SemanticRole,
    concept: str,
    value: object,
    *,
    effective: str = "2026-01-01T00:00:00Z",
    available: str = "2026-01-01T00:00:00Z",
) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=source,
        source_id=source,
        semantic_role=role,
        concept=concept,
        scope=Scope("p1"),
        clocks=ClockSet(effective, None, effective, available, available),
        value=value,
    )


def response_scm() -> FiniteSCMModule:
    # R is the same patient's latent response type. Factual T=1,Y=2 identifies R=1.
    y_expr = op(
        "add",
        op("mul", var("R"), op("add", 1, var("T"))),
        op("mul", op("sub", 1, var("R")), op("neg", var("T"))),
    )
    return FiniteSCMModule.from_data(
        {
            "kind": "finite_scm",
            "module_id": "response",
            "version": "1",
            "variables": [
                {"name": "R", "role": "exogenous", "domain": [0, 1]},
                {
                    "name": "T",
                    "role": "action",
                    "domain": [0, 1],
                    "concept": "treatment",
                    "intervenable": True,
                },
                {"name": "Y", "role": "outcome", "domain": [-1, 0, 1, 2], "concept": "outcome"},
            ],
            "exogenous_distributions": [
                {
                    "target": "R",
                    "masses": [
                        {"value": 0, "probability": 0.5},
                        {"value": 1, "probability": 0.5},
                    ],
                }
            ],
            "equations": [
                {"target": "T", "expression": 1},
                {"target": "Y", "expression": y_expr},
            ],
        }
    )


def masked_state_module() -> DynamicModule:
    p_impaired = op(
        "clamp",
        op("sub", op("add", 0.1, op("mul", 0.8, var("prev__S"))), op("mul", 0.3, var("action__U"))),
        0,
        1,
    )
    p_normal_map = op(
        "clamp",
        op(
            "add",
            0.2,
            op("add", op("mul", 0.7, op("sub", 1, var("state__S"))), op("mul", 0.7, var("action__U"))),
        ),
        0,
        1,
    )
    return DynamicModule.from_data(
        {
            "kind": "dynamic",
            "module_id": "perfusion",
            "version": "1",
            "step_hours": 1,
            "variables": [
                {"name": "S", "role": "latent", "domain": [0, 1]},
                {"name": "M", "role": "observation", "domain": [0, 1], "concept": "map_normal"},
                {
                    "name": "U",
                    "role": "action",
                    "domain": [0, 1],
                    "concept": "norepinephrine",
                    "default": 0,
                },
            ],
            "initial": [
                {
                    "target": "S",
                    "masses": [{"value": 0, "probability": 0.2}, {"value": 1, "probability": 0.8}],
                }
            ],
            "transitions": [
                {
                    "target": "S",
                    "masses": [
                        {"value": 0, "probability": op("sub", 1, p_impaired)},
                        {"value": 1, "probability": p_impaired},
                    ],
                }
            ],
            "emissions": [
                {
                    "target": "M",
                    "masses": [
                        {"value": 0, "probability": op("sub", 1, p_normal_map)},
                        {"value": 1, "probability": p_normal_map},
                    ],
                }
            ],
        }
    )


def probability(result: object, value: float) -> float:
    rows = result.value["probability"]  # type: ignore[attr-defined]
    return next(row["probability"] for row in rows if row["value"] == value)


def test_same_patient_counterfactual_is_not_population_do() -> None:
    engine = CausalStateCandidate()
    engine.register_module(response_scm())
    engine.ingest(art("t", SemanticRole.PERFORMED_INTERVENTION, "treatment", 1))
    engine.ingest(art("y", SemanticRole.RAW_OBSERVATION, "outcome", 2))
    common = dict(target="response::Y", subject_id="p1", as_known_at="2026-01-02T00:00:00Z", intervention={"T": 0})
    cf = engine.query(QuerySpec("cf", QueryKind.COUNTERFACTUAL, **common))
    pop = engine.query(QuerySpec("do", QueryKind.INTERVENE, **common))
    assert probability(cf, 1.0) == 1.0
    assert probability(pop, 1.0) == 0.5
    assert cf.identification.startswith("identified")
    assert cf.value["query_semantics"] == "same_patient_abduction_action_prediction"


def test_state_and_observation_channel_are_separate() -> None:
    engine = CausalStateCandidate()
    engine.register_module(masked_state_module())
    engine.ingest(art("u", SemanticRole.PERFORMED_INTERVENTION, "norepinephrine", 1))
    engine.ingest(art("m", SemanticRole.RAW_OBSERVATION, "map_normal", 1))
    result = engine.query(
        QuerySpec("filter", QueryKind.FILTER, "perfusion::S", "p1", "2026-01-02T00:00:00Z")
    )
    # A supported normal reading does not collapse latent impairment to zero.
    assert 0.0 < probability(result, 1.0) < 1.0
    assert result.native_witness["kernel"] == "finite_dbn"


def test_planned_action_is_not_consumed_as_performed() -> None:
    engine = CausalStateCandidate()
    engine.register_module(masked_state_module())
    engine.ingest(art("plan", SemanticRole.PLAN, "norepinephrine", 1))
    engine.ingest(art("m", SemanticRole.RAW_OBSERVATION, "map_normal", 1))
    planned = engine.query(QuerySpec("p", QueryKind.FILTER, "perfusion::S", "p1", "2026-01-02T00:00:00Z"))

    control = CausalStateCandidate()
    control.register_module(masked_state_module())
    control.ingest(art("m", SemanticRole.RAW_OBSERVATION, "map_normal", 1))
    absent = control.query(QuerySpec("p", QueryKind.FILTER, "perfusion::S", "p1", "2026-01-02T00:00:00Z"))
    assert planned.value["probability"] == absent.value["probability"]


def test_native_retraction_is_honestly_unsupported_but_companion_replays_cut() -> None:
    native = CausalStateCandidate(Track.NATIVE)
    native.ingest(art("m", SemanticRole.RAW_OBSERVATION, "map_normal", 1))
    assert native.retract("m", "2026-01-02T00:00:00Z").status is ResultStatus.UNSUPPORTED

    companion = CausalStateCandidate(Track.COMPANION)
    companion.register_module(masked_state_module())
    companion.ingest(art("m", SemanticRole.RAW_OBSERVATION, "map_normal", 1))
    companion.retract("m", "2026-01-02T00:00:00Z")
    after = companion.query(
        QuerySpec("after", QueryKind.FILTER, "perfusion::S", "p1", "2026-01-03T00:00:00Z")
    )
    # No observation remains; exact result is the prior, and capability origin is companion.
    assert probability(after, 1.0) == 0.8
    assert after.time_cut["adapter"] == "append_only_transaction_cut_adapter"

