from __future__ import annotations

import pytest

from prototype.contract import (
    ClockSet,
    ContractError,
    InfoState,
    QueryKind,
    QuerySpec,
    Scope,
    SemanticRole,
    SourceArtifact,
)
from prototype.ir import Expr


def clocks(**changes: str | None) -> ClockSet:
    values: dict[str, str | None] = {
        "effective_start": "2026-01-01T08:00:00+00:00",
        "effective_end": None,
        "collected_at": "2026-01-01T08:00:00+00:00",
        "available_at": "2026-01-01T12:00:00+00:00",
        "recorded_at": "2026-01-01T12:01:00+00:00",
        "expires_at": None,
    }
    values.update(changes)
    return ClockSet(**values)  # type: ignore[arg-type]


def test_clock_roles_are_validated_not_guessed() -> None:
    with pytest.raises(ContractError, match="时区"):
        clocks(available_at="2026-01-01T12:00:00")
    with pytest.raises(ContractError, match="recorded_at"):
        clocks(recorded_at="2026-01-01T11:00:00+00:00")


def test_present_observation_requires_a_value_but_not_tested_does_not() -> None:
    base = dict(
        artifact_id="a1",
        source_id="s1",
        semantic_role=SemanticRole.RAW_OBSERVATION,
        concept="culture",
        scope=Scope("p1", specimen_id="sp1"),
        clocks=clocks(),
    )
    with pytest.raises(ContractError, match="value"):
        SourceArtifact(**base)
    artifact = SourceArtifact(**base, information_state=InfoState.NOT_TESTED)
    assert artifact.information_state is InfoState.NOT_TESTED


def test_plan_cannot_smuggle_performed_effect() -> None:
    with pytest.raises(ContractError, match="performed"):
        SourceArtifact(
            artifact_id="a2",
            source_id="s2",
            semantic_role=SemanticRole.PLAN,
            concept="norepinephrine",
            scope=Scope("p1"),
            clocks=clocks(),
            value="start",
            context={"performed": True},
        )


def test_closed_expression_ir_rejects_callbacks_and_unknown_opcodes() -> None:
    with pytest.raises(ContractError, match="未知 expression opcode"):
        Expr.from_data({"op": "python_eval", "value": "oracle()"})
    expr = Expr.from_data(
        {
            "op": "add",
            "args": [
                {"op": "var", "value": "x"},
                {"op": "mul", "args": [2, {"op": "var", "value": "u"}]},
            ],
        }
    )
    assert expr.evaluate({"x": 3.0, "u": 4.0}) == 11.0
    assert expr.node_count() == 5


def test_query_kinds_do_not_collapse_condition_and_intervention() -> None:
    common = dict(
        query_id="q",
        target="outcome",
        subject_id="p1",
        as_known_at="2026-01-01T12:00:00+00:00",
    )
    condition = QuerySpec(kind=QueryKind.CONDITION, **common)
    assert condition.intervention is None
    with pytest.raises(ContractError, match="intervention"):
        QuerySpec(kind=QueryKind.INTERVENE, **common)

