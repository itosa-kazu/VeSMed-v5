"""Give every (case, condition) prompt an opaque label so no agent-visible text carries the case id.

Main-analysis cases come first (labels M01..M20), appendix cases after (labels A01..A16),
each block shuffled with a fixed seed. Writes llm/assignment.json.
"""

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20260929


def main():
    order = json.loads((HERE / "frozen" / "leaf_order.json").read_text(encoding="utf-8"))["order"]
    cases = {}
    for path in (HERE / "cases").glob("v5_case_*.json"):
        case = json.loads(path.read_text(encoding="utf-8"))
        cases[case["expected_manifold"]] = path.stem.replace("v5_case_", "")
    accepted = [cases[d] for d in order if d in cases]
    main_ids, appendix_ids = accepted[:10], accepted[10:]
    assignment = {}
    for prefix, ids in (("M", main_ids), ("A", appendix_ids)):
        items = [(cid, cond) for cid in ids for cond in ("present", "removed")]
        random.Random(SEED + len(prefix + str(len(ids)))).shuffle(items)
        for i, (cid, cond) in enumerate(items, start=1):
            assignment[f"{prefix}{i:02d}"] = {"case_id": cid, "condition": cond, "block": "main" if prefix == "M" else "appendix"}
    out = HERE / "llm" / "assignment.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(assignment, indent=2), encoding="utf-8")
    print("main:", main_ids)
    print("appendix:", appendix_ids)
    print(f"{len(assignment)} labels written")


if __name__ == "__main__":
    main()
