"""Exploratory (post hoc, not part of the pre-registered verdict).

For each case, score only the true leaf and ask: of the axes that entered the
likelihood, how many did the true disease itself explain, and how many fell back
to the background/health reference? Compare old (dev) cases with new (test) cases.

Usage: python diagnose_coverage.py <case_dir> <out.jsonl>
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("VESMED_SCORE_MODE", "grid")
os.environ.setdefault("VESMED_TIME_GRID_N", "21")
os.environ.setdefault("VESMED_MAX_COMBO_SIZE", "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import v5_joint_sde_case_test as rt  # noqa: E402


def main():
    case_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    manifolds = {label: rt.load_manifold(path) for label, path in rt.MANIFOLD_PATHS.items()}
    background_axes = rt.build_background_axes(manifolds, rt.load_master_axes())
    with out_path.open("w", encoding="utf-8") as fh:
        for path in sorted(case_dir.glob("v5_case_*.json")):
            case = rt.load_case(path)
            truth = rt.expected_tuple(case)
            if len(truth) != 1 or truth[0] not in manifolds:
                continue
            score = rt.score_candidate(case, truth, manifolds, background_axes)
            if score is None:
                continue
            best = score["best"]
            rows = []
            for x, mu, sigma, meta in zip(best["x"], best["mu"], best["sigmas"], best["meta"]):
                z = (x - mu) / sigma if sigma else 0.0
                rows.append({"axis": meta[0], "via_truth": str(meta[4]).startswith(truth[0]), "z": round(z, 2)})
            own = [r for r in rows if r["via_truth"]]
            other = [r for r in rows if not r["via_truth"]]
            rec = {
                "case_id": case.get("case_id"),
                "truth": truth[0],
                "n_axes": len(rows),
                "n_explained_by_truth": len(own),
                "mean_z2_truth_axes": round(sum(r["z"] ** 2 for r in own) / len(own), 2) if own else None,
                "mean_z2_background_axes": round(sum(r["z"] ** 2 for r in other) / len(other), 2) if other else None,
                "worst_background_axes": sorted(other, key=lambda r: -abs(r["z"]))[:4],
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
