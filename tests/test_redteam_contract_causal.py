from __future__ import annotations

import math

import pytest

from prototype.candidates.causal_state import CausalStateCandidate, DynamicModule
from prototype.contract import (
    CapabilityResult,
    ClockSet,
    ContractError,
    InfoState,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
    validate_json_like,
)
from prototype.ir import Expr


def _op(name: str, *args: object) -> dict[str, object]:
    return {"op": name, "args": list(args)}


def _var(name: str) -> dict[str, object]:
    return {"op": "var", "value": name}


def _module(*, unit: str | None = None, action: bool = False) -> DynamicModule:
    variables: list[dict[str, object]] = [
        {"name": "S", "role": "latent", "domain": [0, 1]},
        {"name": "M", "role": "observation", "domain": [0, 1], "concept": "reading", "unit": unit},
    ]
    if action:
        variables.append(
            {"name": "U", "role": "action", "domain": [0, 1], "concept": "drug", "default": 0}
        )
    p1 = _op(
        "add",
        0.1,
        _op("mul", 0.8, _var("state__S")),
    )
    return DynamicModule.from_data(
        {
            "kind": "dynamic",
            "module_id": "m",
            "version": "1",
            "variables": variables,
            "initial": [{"target": "S", "masses": [{"value": 0, "probability": 0.5}, {"value": 1, "probability": 0.5}]}],
            "transitions": [{"target": "S", "masses": [{"value": 0, "probability": _op("sub", 1, _var("prev__S"))}, {"value": 1, "probability": _var("prev__S")}]}],
            "emissions": [{"target": "M", "masses": [{"value": 0, "probability": _op("sub", 1, p1)}, {"value": 1, "probability": p1}]}],
        }
    )


def _artifact(
    artifact_id: str,
    source_id: str,
    value: object,
    *,
    role: SemanticRole = SemanticRole.RAW_OBSERVATION,
    concept: str = "reading",
    start: str = "2026-01-01T00:00:00Z",
    end: str | None = None,
    expires: str | None = None,
    unit: str | None = None,
    raw_payload: object | None = None,
) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=artifact_id,
        source_id=source_id,
        semantic_role=role,
        concept=concept,
        scope=Scope("p1"),
        clocks=ClockSet(start, end, start, "2025-12-31T23:00:00Z", "2025-12-31T23:00:00Z", expires),
        value=value,
        unit=unit,
        raw_payload={} if raw_payload is None else raw_payload,  # type: ignore[arg-type]
    )


def _query(**changes: object) -> QuerySpec:
    values: dict[str, object] = {
        "query_id": "q",
        "kind": QueryKind.FILTER,
        "target": "m::S",
        "subject_id": "p1",
        "as_known_at": "2026-01-01T01:00:00Z",
    }
    values.update(changes)
    return QuerySpec(**values)  # type: ignore[arg-type]


def _p1(result: CapabilityResult) -> float:
    return next(row["probability"] for row in result.value["probability"] if row["value"] == 1.0)


def test_closed_input_gate_rejects_before_user_copy_hooks() -> None:
    called = False

    class Bomb:
        def __deepcopy__(self, memo: object) -> object:  # pragma: no cover - must not run
            nonlocal called
            called = True
            raise AssertionError("hostile deepcopy ran")

    bad = _artifact("a", "s", 1, raw_payload={"bomb": Bomb()})
    result = CausalStateCandidate().ingest(bad)
    assert result.status is ResultStatus.INVALID
    assert called is False


def test_exact_json_budget_nonfinite_cycle_and_result_axes() -> None:
    with pytest.raises(ContractError, match="有限"):
        validate_json_like(math.nan)
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(ContractError, match="循环"):
        validate_json_like(cyclic)
    with pytest.raises(ContractError, match="矛盾"):
        CapabilityResult(ResultStatus.OK, validation="invalid")
    with pytest.raises(ContractError, match="capability=unsupported"):
        CapabilityResult(ResultStatus.UNSUPPORTED)


def test_wrong_runtime_enums_and_expr_subclasses_are_typed_invalid() -> None:
    bad_artifact = _artifact("a", "s", 1)
    object.__setattr__(bad_artifact, "semantic_role", "raw_observation")
    assert CausalStateCandidate().ingest(bad_artifact).status is ResultStatus.INVALID

    engine = CausalStateCandidate()
    bad_query = _query()
    object.__setattr__(bad_query, "kind", "filter")
    assert engine.query(bad_query).status is ResultStatus.INVALID

    class EvilExpr(Expr):
        pass

    evil = object.__new__(EvilExpr)
    object.__setattr__(evil, "op", "const")
    object.__setattr__(evil, "args", ())
    object.__setattr__(evil, "value", 1.0)
    with pytest.raises(ContractError, match="exact Expr"):
        Expr("neg", (evil,))  # type: ignore[arg-type]


def test_valid_time_defaults_to_cut_and_uses_half_open_end_and_expiry() -> None:
    engine = CausalStateCandidate()
    engine.register_module(_module())
    engine.ingest(_artifact("future", "future", 1, start="2026-01-02T00:00:00Z"))
    before = engine.query(_query())
    assert _p1(before) == 0.5
    assert before.time_cut["valid_at"] == "2026-01-01T01:00:00Z"
    assert before.time_cut["valid_at_defaulted_to_as_known_at"] is True

    ended = CausalStateCandidate()
    ended.register_module(_module())
    ended.ingest(_artifact("ended", "ended", 1, end="2026-01-01T01:00:00Z"))
    assert _p1(ended.query(_query())) == 0.5

    expired = CausalStateCandidate()
    expired.register_module(_module())
    expired.ingest(_artifact("expired", "expired", 1, expires="2026-01-01T01:00:00Z"))
    assert _p1(expired.query(_query())) == 0.5


def test_source_and_artifact_identity_are_idempotent_or_explicit_conflict() -> None:
    engine = CausalStateCandidate()
    first = _artifact("a1", "stable-source", 1)
    alias = _artifact("a2", "stable-source", 1)
    changed = _artifact("a3", "stable-source", 0)
    assert engine.ingest(first).status is ResultStatus.OUT_OF_MODEL
    duplicate = engine.ingest(alias)
    assert duplicate.status is ResultStatus.OK and duplicate.value["idempotent"] is True
    assert engine.ingest(changed).status is ResultStatus.CONFLICTING
    collision = _artifact("a1", "other-source", 0)
    assert engine.ingest(collision).status is ResultStatus.CONFLICTING


def test_conflicting_same_instant_actions_do_not_last_write() -> None:
    engine = CausalStateCandidate()
    engine.register_module(_module(action=True))
    engine.ingest(_artifact("u0", "u0", 0, role=SemanticRole.PERFORMED_INTERVENTION, concept="drug"))
    engine.ingest(_artifact("u1", "u1", 1, role=SemanticRole.PERFORMED_INTERVENTION, concept="drug"))
    result = engine.query(_query())
    assert result.status is ResultStatus.CONFLICTING
    assert "last-write" in result.diagnostics["error"]


def test_required_unknown_unit_and_unconsumed_controls_fail_closed() -> None:
    engine = CausalStateCandidate()
    engine.register_module(_module(unit="mmHg"))
    engine.ingest(_artifact("a", "s", 1, unit=None))
    assert engine.query(_query()).status is ResultStatus.OUT_OF_MODEL

    assert engine.query(_query(query_id="k", knowledge_version="knowledge-v2")).status is ResultStatus.UNSUPPORTED
    assert engine.query(_query(query_id="t", task="diagnosis")).status is ResultStatus.UNSUPPORTED
    assert engine.query(_query(query_id="g", requested_guarantees=("raw_roundtrip",))).status is ResultStatus.UNSUPPORTED

