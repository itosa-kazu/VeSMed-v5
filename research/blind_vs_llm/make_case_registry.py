"""Build the axis registry handed to case-structuring agents.

Only observable, diagnosis-neutral axes are kept: no latent mechanisms, no
hazards, no disease-suffixed axes, and no `seen_in` provenance, so the agent
cannot see which disease owns which axis.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "frozen" / "case_axis_registry.json"
DROP_CATEGORIES = {"latent_mechanism", "derived_hazard", "event_hazard"}


def main():
    axes = json.loads((ROOT / "master_axes.json").read_text(encoding="utf-8"))["axes"]
    kept = []
    for a in axes:
        axis_id = a.get("axis_id") or ""
        if a.get("category") in DROP_CATEGORIES or "_in_D-" in axis_id or axis_id.startswith("M_") or "_hazard" in axis_id:
            continue
        kept.append({
            "axis_id": axis_id,
            "category": a.get("category"),
            "unit": a.get("unit"),
            "log_scale": a.get("log_scale"),
            "axis_role": a.get("axis_role"),
            "parent_axis_id": a.get("parent_axis_id"),
        })
    kept.sort(key=lambda a: a["axis_id"])
    OUT.write_text(json.dumps({"note": "naming registry only, not a checklist", "axes": kept}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"kept {len(kept)} of {len(axes)} axes -> {OUT}")


if __name__ == "__main__":
    main()
