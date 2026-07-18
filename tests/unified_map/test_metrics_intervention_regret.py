from __future__ import annotations

import dataclasses
import math

import pytest

from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.metrics_intervention_regret import (
    CoverageDisposition,
    EffectIdentification,
    GaussianTrajectoryCase,
    IdentifiedSetCase,
    Interval,
    PartialIdentificationCase,
    PolicyHorizonExposure,
    RegretCase,
    RegretDisposition,
    SetClaimKind,
    TreatmentEffectCase,
    UndefinedReason,
    identified_set_metrics,
    intervention_trajectory_metrics,
    partial_identification_regret,
    point_identified_regret,
    policy_horizon_coverage,
    runtime_status,
    treatment_effect_metrics,
)


def test_runtime_is_explicitly_pre_freeze_unbound_and_has_no_total_score() -> None:
    assert runtime_status() == {
        "schema": "ucm-pre-freeze-m03-m04-runtime/1",
        "benchmark_status": "PRE-FREEZE",
        "artifact_role": "runtime_only",
        "freeze_authority": "not_claimed",
        "official_evaluator_binding": "not_bound",
        "utility_direction": "larger_is_better",
        "single_aggregate_score": "forbidden",
    }
    result_fields = {
        item.name
        for item in dataclasses.fields(
            point_identified_regret(
                (
                    RegretCase(
                        "one",
                        "W01",
                        ("A", "B"),
                        (1.0, 0.0),
                        (1.0, 0.0),
                        ("A", "B"),
                        0.0,
                        1.0,
                    ),
                )
            )
        )
    }
    assert "total_score" not in result_fields


def test_gaussian_intervention_trajectory_errors_are_hand_calculable() -> None:
    result = intervention_trajectory_metrics(
        (
            GaussianTrajectoryCase(
                "case-1",
                "A1",
                "H2",
                (1.0, 3.0),
                (1.0, 2.0),
                (0.0, 1.0),
                (1.0, 2.0),
            ),
        )
    )
    expected_nll = (
        0.5 * math.log(2.0 * math.pi) + 0.5 + 0.5 * math.log(8.0 * math.pi) + 0.5
    ) / 2.0
    assert result.case_count == 1
    assert result.scalar_exposure == 2
    assert result.gaussian_nll == pytest.approx(expected_nll)
    assert result.mean_absolute_error == 1.5
    assert result.root_mean_squared_error == pytest.approx(math.sqrt(2.5))
    assert result.oracle_scale_normalized_mae == 1.0
    assert result.oracle_scale_normalized_rmse == 1.0


def test_effect_error_sign_and_pehe_use_only_unit_identified_rows() -> None:
    result = treatment_effect_metrics(
        (
            TreatmentEffectCase(
                "distribution", 1.0, -1.0, EffectIdentification.DISTRIBUTION
            ),
            TreatmentEffectCase("unit-1", 3.0, 1.0, EffectIdentification.UNIT),
            TreatmentEffectCase("unit-2", -1.0, -1.0, EffectIdentification.UNIT),
        ),
        effect_sign_tolerance=0.1,
    )
    assert result.mean_absolute_effect_error == pytest.approx(4.0 / 3.0)
    assert result.root_mean_squared_effect_error == pytest.approx(math.sqrt(8.0 / 3.0))
    assert result.effect_sign_error_count == 1
    assert result.effect_sign_error_rate == pytest.approx(1.0 / 3.0)
    assert result.pehe.exposure == 2
    assert result.pehe.value == pytest.approx(math.sqrt(2.0))
    assert result.pehe.undefined_reason is None

    no_unit = treatment_effect_metrics(
        (
            TreatmentEffectCase(
                "distribution", 0.0, 0.0, EffectIdentification.DISTRIBUTION
            ),
        ),
        effect_sign_tolerance=0.0,
    )
    assert no_unit.pehe.value is None
    assert no_unit.pehe.exposure == 0
    assert no_unit.pehe.undefined_reason is UndefinedReason.NO_UNIT_IDENTIFIED_EXPOSURE


def test_policy_horizon_coverage_keeps_abstention_and_failures_in_denominator() -> None:
    rows = (
        PolicyHorizonExposure(
            "r1", "W01", "case-1", "cut-1", "A0", "H1", CoverageDisposition.POINT_SCORED
        ),
        PolicyHorizonExposure(
            "r2", "W01", "case-2", "cut-1", "A0", "H1", CoverageDisposition.SET_SCORED
        ),
        PolicyHorizonExposure(
            "r3",
            "W01",
            "case-1",
            "cut-1",
            "A1",
            "H1",
            CoverageDisposition.TYPED_ABSTENTION,
        ),
        PolicyHorizonExposure(
            "r4", "W01", "case-1", "cut-1", "A1", "H2", CoverageDisposition.MISSING
        ),
    )
    result = policy_horizon_coverage(rows)
    assert result.required_exposure == 4
    assert result.responded_exposure == 3
    assert result.scored_exposure == 2
    assert result.typed_abstention_exposure == 1
    assert result.response_coverage == 0.75
    assert result.scored_coverage == 0.5
    with pytest.raises(ProtocolViolation, match="record_id values must be unique"):
        policy_horizon_coverage((rows[0], rows[0]))
    with pytest.raises(ProtocolViolation, match="required coverage cells"):
        policy_horizon_coverage(
            (rows[0], dataclasses.replace(rows[0], record_id="r1-resigned"))
        )


def test_identified_set_metrics_do_not_score_abstention_as_a_point() -> None:
    result = identified_set_metrics(
        (
            IdentifiedSetCase(
                "honest-set",
                Interval(-1.0, 1.0),
                SetClaimKind.IDENTIFIED_SET,
                Interval(-1.5, 1.25),
                ("A0", "A1"),
                ("A0", "A1"),
            ),
            IdentifiedSetCase(
                "false-point",
                Interval(-1.0, 1.0),
                SetClaimKind.POINT,
                Interval(0.2, 0.2),
                ("A0", "A1"),
                ("A1",),
            ),
            IdentifiedSetCase(
                "abstain",
                Interval(-2.0, 2.0),
                SetClaimKind.TYPED_ABSTENTION,
                None,
            ),
        ),
        tolerance=0.0,
    )
    assert result.required_exposure == 3
    assert result.set_claim_exposure == 2
    assert result.abstention_exposure == 1
    assert result.set_claim_rate == pytest.approx(2.0 / 3.0)
    assert result.oracle_set_coverage.value == 0.5
    assert result.mean_candidate_set_width.value == 1.375
    assert result.mean_hausdorff_error.value == 0.85
    assert result.mean_set_bound_error.value == pytest.approx(0.6875)
    assert result.certainty_claim_exposure == 1
    assert result.false_certainty_count == 1
    assert result.false_certainty_rate.value == 1.0
    assert result.rows[2].oracle_covered is None
    assert result.rows[2].false_certainty is False


def test_hci_covering_cross_zero_oracle_set_is_not_false_certainty() -> None:
    result = identified_set_metrics(
        (
            IdentifiedSetCase(
                "honest-hci",
                Interval(-1.0, 1.0),
                SetClaimKind.HIGH_CONFIDENCE_INTERVAL,
                Interval(-1.25, 1.25),
                ("A0", "A1"),
                ("A0", "A1"),
            ),
        ),
        tolerance=0.0,
    )
    assert result.rows[0].oracle_covered is True
    assert result.rows[0].false_certainty is False
    assert result.false_certainty_rate.value == 0.0


def _regret_case(
    case_id: str,
    predicted: tuple[float, ...],
    oracle: tuple[float, ...],
    *,
    world: str = "W01",
    tail: bool = False,
    actions: tuple[str, ...] = ("A", "B", "C"),
    tie: tuple[str, ...] = ("B", "A", "C"),
    catastrophic: tuple[str, ...] = ("B",),
) -> RegretCase:
    return RegretCase(
        case_id,
        world,
        actions,
        predicted,
        oracle,
        tie,
        0.1,
        1.5,
        catastrophic,
        tail,
    )


def test_point_regret_has_raw_normalized_tail_and_exact_tie_semantics() -> None:
    result = point_identified_regret(
        (
            _regret_case("common", (0.0, 4.0, 1.0), (10.0, 8.0, 0.0)),
            _regret_case(
                "tail",
                (0.0, 5.0, 1.0),
                (20.0, 0.0, -5.0),
                world="W19",
                tail=True,
            ),
            _regret_case("zero-range", (1.0, 1.05, 0.0), (2.0, 2.0, 2.0)),
        )
    )
    assert result.disposition is RegretDisposition.POINT_IDENTIFIED_PRIMARY
    assert [row.selected_action_id for row in result.rows] == ["B", "B", "B"]
    assert [row.raw_regret for row in result.rows] == [2.0, 20.0, 0.0]
    assert result.rows[0].normalized_regret == 0.2
    assert result.rows[2].normalized_regret is None
    assert (
        result.rows[2].normalized_regret_undefined_reason
        is UndefinedReason.ZERO_ORACLE_UTILITY_RANGE
    )
    assert result.full_population.raw.mean == pytest.approx(22.0 / 3.0)
    assert result.full_population.raw.median == 2.0
    assert result.full_population.raw.p95 == pytest.approx(18.2)
    assert result.full_population.raw.maximum == 20.0
    assert result.full_population.raw.cvar95 == 20.0
    assert result.full_population.normalized_exposure == 2
    assert result.full_population.normalized_undefined_exposure == 1
    assert result.full_population.catastrophic_action_count == 2
    assert result.full_population.catastrophic_action_rate == pytest.approx(2 / 3)
    assert result.w19_tail is not None
    assert result.w19_tail.exposure == 1
    assert result.w19_tail.raw.mean == 20.0
    assert result.w19_tail.catastrophic_action_rate == 1.0


@pytest.mark.parametrize("shift", [-100.0, 0.0, 17.5])
@pytest.mark.parametrize("scale", [0.25, 1.0, 8.0])
def test_regret_translation_and_positive_scale_properties(
    shift: float, scale: float
) -> None:
    baseline = _regret_case("base", (0.0, 3.0, 1.0), (9.0, 4.0, -1.0))
    transformed = _regret_case(
        "transformed",
        tuple(scale * value + shift for value in baseline.predicted_utilities),
        tuple(scale * value + shift for value in baseline.oracle_utilities),
    )
    base_row = point_identified_regret((baseline,)).rows[0]
    transformed_row = point_identified_regret((transformed,)).rows[0]
    assert transformed_row.selected_action_id == base_row.selected_action_id
    assert transformed_row.raw_regret == pytest.approx(scale * base_row.raw_regret)
    assert transformed_row.normalized_regret == pytest.approx(
        base_row.normalized_regret
    )


def test_partial_identification_uses_set_optima_and_robust_regret_not_point() -> None:
    result = partial_identification_regret(
        (
            PartialIdentificationCase(
                case_id="ambiguous",
                world_slot="W15B",
                action_ids=("A", "B"),
                candidate_utility_sets=(Interval(0.0, 2.0), Interval(0.0, 3.0)),
                compatible_oracle_utilities=((2.0, 0.0), (0.0, 3.0)),
                tie_break_action_ids=("B", "A"),
                optimal_action_tolerance=0.0,
                catastrophic_margin=1.0,
                catastrophic_action_ids=("B",),
                descriptive_realized_oracle_utilities=(2.0, 0.0),
            ),
            PartialIdentificationCase(
                case_id="tail-all-catastrophic",
                world_slot="W19",
                action_ids=("A", "B"),
                candidate_utility_sets=(Interval(1.0, 1.0), Interval(0.0, 0.0)),
                compatible_oracle_utilities=((0.0, 3.0), (1.0, 4.0)),
                tie_break_action_ids=("A", "B"),
                optimal_action_tolerance=0.0,
                catastrophic_margin=2.0,
                catastrophic_action_ids=("A",),
                claim_kind=SetClaimKind.POINT,
                w19_tail_member=True,
            ),
        )
    )
    assert result.disposition is RegretDisposition.PARTIAL_IDENTIFICATION_ROBUST_PRIMARY
    ambiguous, tail = result.rows
    assert ambiguous.selected_action_id == "B"
    assert ambiguous.oracle_set_valued_optimal_action_ids == ("A", "B")
    assert ambiguous.uniformly_dominated_action_ids == ()
    assert ambiguous.robust_regret_by_action == (("A", 3.0), ("B", 2.0))
    assert ambiguous.selected_oracle_robust_regret_interval == Interval(0.0, 2.0)
    assert ambiguous.selected_oracle_robust_regret_bound == 2.0
    assert ambiguous.all_compatible_catastrophic is False
    assert ambiguous.descriptive_realization_regret == 2.0
    assert ambiguous.point_regret_primary is None
    assert tail.oracle_set_valued_optimal_action_ids == ("B",)
    assert tail.uniformly_dominated_action_ids == ("A",)
    assert tail.selected_oracle_robust_regret_interval == Interval(3.0, 3.0)
    assert tail.all_compatible_catastrophic is True
    assert tail.false_certainty is True
    assert result.all_compatible_catastrophic_count == 1
    assert result.false_certainty_exposure == 1
    assert result.false_certainty_count == 1
    assert result.false_certainty_rate.value == 1.0
    assert result.w19_tail_robust_regret_bound_summary is not None
    assert result.w19_tail_robust_regret_bound_summary.mean == 3.0


def test_partial_hci_covering_all_models_and_actions_is_not_false_certainty() -> None:
    result = partial_identification_regret(
        (
            PartialIdentificationCase(
                case_id="honest-hci",
                world_slot="W15B",
                action_ids=("A", "B"),
                candidate_utility_sets=(Interval(0.0, 1.0), Interval(0.0, 1.0)),
                compatible_oracle_utilities=((1.0, 0.0), (0.0, 1.0)),
                tie_break_action_ids=("A", "B"),
                optimal_action_tolerance=0.0,
                catastrophic_margin=1.0,
                claim_kind=SetClaimKind.HIGH_CONFIDENCE_INTERVAL,
            ),
        )
    )
    assert result.rows[0].oracle_set_valued_optimal_action_ids == ("A", "B")
    assert result.rows[0].false_certainty is False
    assert result.false_certainty_exposure == 1
    assert result.false_certainty_rate.value == 0.0


@pytest.mark.parametrize(
    ("call", "pattern"),
    [
        (
            lambda: intervention_trajectory_metrics(
                (
                    GaussianTrajectoryCase(
                        "bad", "A", "H", (True,), (1.0,), (0.0,), (1.0,)
                    ),
                )
            ),
            "exact finite number",
        ),
        (
            lambda: treatment_effect_metrics(
                (TreatmentEffectCase("bad", math.nan, 0.0, EffectIdentification.UNIT),),
                effect_sign_tolerance=0.0,
            ),
            "exact finite number",
        ),
        (
            lambda: treatment_effect_metrics(
                (
                    TreatmentEffectCase(
                        "huge-int", 10**400, 0.0, EffectIdentification.UNIT
                    ),
                ),
                effect_sign_tolerance=0.0,
            ),
            "exact finite number",
        ),
        (
            lambda: treatment_effect_metrics(
                (
                    TreatmentEffectCase(
                        "overflowing-difference",
                        1e308,
                        -1e308,
                        EffectIdentification.UNIT,
                    ),
                ),
                effect_sign_tolerance=0.0,
            ),
            "became non-finite",
        ),
        (
            lambda: identified_set_metrics(
                (
                    IdentifiedSetCase(
                        "bad",
                        Interval(-1.0, 1.0),
                        SetClaimKind.POINT,
                        Interval(0.0, 1.0),
                    ),
                ),
                tolerance=0.0,
            ),
            "zero-width",
        ),
        (
            lambda: identified_set_metrics(
                (
                    IdentifiedSetCase(
                        "overflowing-width",
                        Interval(-1.0, 1.0),
                        SetClaimKind.IDENTIFIED_SET,
                        Interval(-1e308, 1e308),
                    ),
                ),
                tolerance=0.0,
            ),
            "candidate set width became non-finite",
        ),
        (
            lambda: point_identified_regret(
                (_regret_case("bad", (True, 0.0, 0.0), (1.0, 0.0, -1.0)),)
            ),
            "exact finite number",
        ),
        (
            lambda: point_identified_regret(
                (
                    _regret_case(
                        "overflowing-regret",
                        (1.0, 0.0, -1.0),
                        (1e308, -1e308, 0.0),
                    ),
                )
            ),
            "became non-finite",
        ),
        (
            lambda: partial_identification_regret(
                (
                    PartialIdentificationCase(
                        "bad",
                        "W15B",
                        ("A", "B"),
                        (Interval(0.0, 1.0), Interval(0.0, 1.0)),
                        ((1.0, 0.0), (math.inf, 1.0)),
                        ("A", "B"),
                        0.0,
                        1.0,
                    ),
                )
            ),
            "exact finite number",
        ),
    ],
)
def test_m03_m04_reject_bool_nan_infinity_and_false_point_claims(
    call, pattern: str
) -> None:
    with pytest.raises(ProtocolViolation, match=pattern):
        call()


def test_partial_identification_rejects_single_model_and_non_w19_tail() -> None:
    base = PartialIdentificationCase(
        "bad",
        "W15B",
        ("A", "B"),
        (Interval(0.0, 1.0), Interval(0.0, 1.0)),
        ((1.0, 0.0),),
        ("A", "B"),
        0.0,
        1.0,
    )
    with pytest.raises(ProtocolViolation, match="at least two models"):
        partial_identification_regret((base,))
    with pytest.raises(ProtocolViolation, match="only W19"):
        partial_identification_regret(
            (
                dataclasses.replace(
                    base,
                    compatible_oracle_utilities=((1.0, 0.0), (0.0, 1.0)),
                    w19_tail_member=True,
                ),
            )
        )
