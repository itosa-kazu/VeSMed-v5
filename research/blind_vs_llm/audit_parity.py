"""Print, per test case, what V5 will consume and the risk context, next to the vignette length.

Used for the manual parity/leak audit (PROTOCOL.md section 4). Does not rank.
Usage: python audit_parity.py [CASE_ID ...]   (default: every case in cases/)
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
import v5_joint_sde_case_test as rt  # noqa: E402


def fmt(value):
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def main():
    ids = sys.argv[1:] or sorted(p.stem.replace("v5_case_", "") for p in (HERE / "cases").glob("v5_case_*.json"))
    for case_id in ids:
        path = HERE / "cases" / f"v5_case_{case_id}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        case = rt.load_case(path)
        obs = case.get("observations_by_axis") or {}
        print(f"=== {case_id}  truth={raw.get('expected_manifold')}  consumed={len(obs)}")
        print("  axes: " + "; ".join(f"{a}={fmt(o.get('value', o.get('qualitative_value')))}" for a, o in sorted(obs.items())))
        ctx = raw.get("risk_context") or []
        if ctx:
            print("  risk_context: " + "; ".join(f"{r.get('factor')}={r.get('category')}" for r in ctx if isinstance(r, dict)))


if __name__ == "__main__":
    main()
