"""Decisive ordinary-model counterexamples for one local posterior per process.

This is not a clinical simulation.  It checks whether the frozen wire summaries

    q(Z=active), q(local coordinate), q(local mode)

are sufficient for an active-gated hybrid transition without also retaining
their dependence.  The two compatible worlds in each example intentionally
produce exactly the same serialized summaries.
"""

from __future__ import annotations

import json


def unconditional_summary_counterexample() -> dict:
    # Both worlds have P(active)=1/2, P(decompensated)=1/2 and the same x
    # marginal.  They differ only in the unrepresented Z--mode dependence.
    worlds = {
        "positive_dependence": [
            {"probability": 0.5, "active": True, "mode": "decompensated", "x": 1.0},
            {"probability": 0.5, "active": False, "mode": "compensated", "x": 0.0},
        ],
        "negative_dependence": [
            {"probability": 0.5, "active": True, "mode": "compensated", "x": 0.0},
            {"probability": 0.5, "active": False, "mode": "decompensated", "x": 1.0},
        ],
    }
    drift = {"decompensated": 1.0, "compensated": -1.0}

    summaries = {}
    correct_expected_drift = {}
    for world_id, rows in worlds.items():
        summaries[world_id] = {
            "p_active": sum(row["probability"] for row in rows if row["active"]),
            "p_decompensated": sum(
                row["probability"]
                for row in rows
                if row["mode"] == "decompensated"
            ),
            "x_mean": sum(row["probability"] * row["x"] for row in rows),
            "x_second_moment": sum(
                row["probability"] * row["x"] ** 2 for row in rows
            ),
        }
        correct_expected_drift[world_id] = sum(
            row["probability"]
            * float(row["active"])
            * drift[row["mode"]]
            for row in rows
        )

    p_active = summaries["positive_dependence"]["p_active"]
    p_decomp = summaries["positive_dependence"]["p_decompensated"]
    mean_field_drift = p_active * (
        p_decomp * drift["decompensated"]
        + (1.0 - p_decomp) * drift["compensated"]
    )
    return {
        "wire_summaries": summaries,
        "summaries_identical": (
            summaries["positive_dependence"] == summaries["negative_dependence"]
        ),
        "correct_expected_drift": correct_expected_drift,
        "mean_field_drift_for_both": mean_field_drift,
        "decisive": (
            summaries["positive_dependence"] == summaries["negative_dependence"]
            and correct_expected_drift["positive_dependence"]
            != correct_expected_drift["negative_dependence"]
        ),
    }


def active_conditional_interpretation_counterexample() -> dict:
    # Suppose the single local posterior is instead declared q(mode | active).
    # These worlds then have the same active conditional, but different dormant
    # memory.  A subsequent CARRY entry exposes the missing distinction.
    worlds = {
        "dormant_compensated": {
            "p_active": 0.5,
            "active_mode": "decompensated",
            "inactive_mode": "compensated",
        },
        "dormant_decompensated": {
            "p_active": 0.5,
            "active_mode": "decompensated",
            "inactive_mode": "decompensated",
        },
    }
    visible = {
        world_id: {
            "p_active": row["p_active"],
            "q_mode_given_active": {"decompensated": 1.0, "compensated": 0.0},
        }
        for world_id, row in worlds.items()
    }
    # All dormant mass enters and CARRY preserves its dormant mode.
    post_entry_decomp = {
        world_id: (
            row["p_active"] * float(row["active_mode"] == "decompensated")
            + (1.0 - row["p_active"])
            * float(row["inactive_mode"] == "decompensated")
        )
        for world_id, row in worlds.items()
    }
    return {
        "wire_summaries": visible,
        "summaries_identical": (
            visible["dormant_compensated"] == visible["dormant_decompensated"]
        ),
        "post_carry_entry_p_decompensated": post_entry_decomp,
        "decisive": (
            visible["dormant_compensated"] == visible["dormant_decompensated"]
            and post_entry_decomp["dormant_compensated"]
            != post_entry_decomp["dormant_decompensated"]
        ),
    }


def main() -> None:
    result = {
        "unconditional_local_summary": unconditional_summary_counterexample(),
        "conditional_on_active_summary": active_conditional_interpretation_counterexample(),
    }
    result["all_decisive"] = all(row["decisive"] for row in result.values())
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
