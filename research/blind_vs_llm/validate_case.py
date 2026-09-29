"""Check that a new case JSON loads and show which evidence the runtime will consume.

This does not rank anything. It prints the rankable axes the loader extracts,
and flags axis ids that are not in the case axis registry.

Usage: python validate_case.py <case.json>
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import v5_joint_sde_case_test as rt  # noqa: E402

REGISTRY = Path(__file__).resolve().parent / "frozen" / "case_axis_registry.json"


def main():
    path = Path(sys.argv[1])
    raw = json.loads(path.read_text(encoding="utf-8"))
    case = rt.load_case(path)
    known = {a["axis_id"] for a in json.loads(REGISTRY.read_text(encoding="utf-8"))["axes"]}
    obs = case.get("observations_by_axis") or {}
    print(f"case_id={case.get('case_id')} expected={raw.get('expected_manifold')} consumed_axes={len(obs)}")
    for axis_id, item in sorted(obs.items()):
        flag = "" if axis_id in known else "   <-- not in registry (pending axis)"
        value = item.get("value", item.get("qualitative_value"))
        print(f"  {axis_id} = {value} {item.get('unit') or ''} (day {item.get('day', item.get('time_days'))}){flag}")
    for key in ("source_pmcid", "source_pmid", "source_url", "disease_label_per_paper", "expected_manifold"):
        if not raw.get(key):
            print(f"MISSING top-level field: {key}")


if __name__ == "__main__":
    main()
