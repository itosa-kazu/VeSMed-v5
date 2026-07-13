from __future__ import annotations

from prototype.bridge_mutation_gate import (
    MUTANT_IDS,
    _baseline_report,
    apply_known_bad_mutant,
    evaluate_report,
    self_test,
)


def test_known_good_external_report_passes_all_twelve_hard_gates() -> None:
    result = evaluate_report(_baseline_report())
    assert result["passed"] is True
    assert result["essential_mutants"] == 12
    assert result["killed_or_rejected"] == 12


def test_each_known_bad_mutant_is_killed_by_its_named_gate() -> None:
    baseline = _baseline_report()
    for mutant_id in MUTANT_IDS:
        result = evaluate_report(apply_known_bad_mutant(baseline, mutant_id))
        assert result["passed"] is False
        assert mutant_id in result["failed_gates"]


def test_pre_freeze_self_test_matches_public_protocol_oracles() -> None:
    result = self_test()
    assert result["essential_mutants"] == 12
    assert result["essential_mutants_killed"] == 12
    assert result["hmm_oracle"] == {
        "filter_x0_y0_0": 0.2,
        "smooth_x0_y0_0_y1_1": 0.4157303370786517,
        "smooth_x0_y0_0_y1_0": 0.08074534161490683,
    }
    assert result["e02_oracle"] == {
        "condition_bad_t1": 0.545,
        "population_do_bad_t1": 0.325,
    }
