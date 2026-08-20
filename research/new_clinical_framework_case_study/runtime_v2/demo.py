"""Run the case-blind neutral Runtime v2 fixture.

Usage from the case-study directory:

    python -m runtime_v2.demo
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .engine import RuntimeV2
from .io import load_events_json


ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"
EVENTS_PATH = ROOT / "examples" / "neutral_events.json"


def run_demo() -> dict[str, Any]:
    runtime = RuntimeV2.from_json(MODEL_PATH)
    events = load_events_json(EVENTS_PATH)
    state = runtime.initialize(events, cut=0)
    cuts: list[dict[str, Any]] = []
    for cut in (0, 1, 2, 4, 5):
        if cut:
            state = runtime.update(state, events, advance_to=cut)
        diagnosis = runtime.diagnose(state)
        forecast = runtime.forecast(state, horizon=2)
        plan = runtime.plan(
            state,
            [
                {"policy_id": "NO_NEW_ACTION", "start_actions": []},
                {
                    "policy_id": "START_ACTION_REDUCE_A",
                    "start_actions": [{"action_id": "ACTION_REDUCE_A", "dose": 1.0}],
                },
            ],
            horizon=2,
        )
        cuts.append(
            {
                "cut": cut,
                "state_hash": state.state_hash,
                "activation_marginals": diagnosis["process_activation_marginals"],
                "local_modes": diagnosis["per_process_modes"],
                "epistemic": diagnosis["epistemic"],
                "active_action_instances": state.to_dict()["action_memory"]["instances"],
                "natural_expected_burden": forecast["expected_coordinate_burden"],
                "selected_policy_id": plan["selected_policy_id"],
            }
        )
    return {
        "model_id": runtime.spec["model_id"],
        "model_digest": runtime.model_digest,
        "status": "STRUCTURAL_DEMO_ONLY_NOT_CLINICAL_VALIDATION",
        "cuts": cuts,
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, sort_keys=True, indent=2))
