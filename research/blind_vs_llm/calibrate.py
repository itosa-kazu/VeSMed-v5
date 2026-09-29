"""Fix the S1 abstention threshold tau from the development set (existing active cases).

Rule (PROTOCOL.md section 5): among single-truth dev cases whose full-atlas
top-1 is the true leaf, tau = 95th percentile of the top-1 fit_mean_z2.
Also reports how S0/S1 would have behaved on the dev set, for information only.
"""

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DEV = HERE / "dev" / "dev_results.jsonl"
OUT = HERE / "frozen" / "threshold.json"
S0_DELTA = 2.3


def main():
    rows = [json.loads(line) for line in DEV.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = [r for r in rows if r.get("error")]
    rows = [r for r in rows if not r.get("error") and len(r.get("truth") or []) == 1 and r.get("top10")]
    present = [r for r in rows if r["condition"] == "present"]
    removed = [r for r in rows if r["condition"] == "removed"]

    correct = [r for r in present if r["top10"][0]["disease_id"] == r["truth"][0]]
    fits = np.array([r["top10"][0]["fit_mean_z2"] for r in correct if r["top10"][0]["fit_mean_z2"] is not None])
    tau = float(np.percentile(fits, 95))

    def s0(r):
        return r["top10"][0]["delta_to_health"] is not None and r["top10"][0]["delta_to_health"] <= S0_DELTA

    def s1(r):
        return r["top10"][0]["fit_mean_z2"] is not None and r["top10"][0]["fit_mean_z2"] > tau

    removed_fits = np.array([r["top10"][0]["fit_mean_z2"] for r in removed if r["top10"][0]["fit_mean_z2"] is not None])
    summary = {
        "rule": "95th percentile of top-1 fit_mean_z2 over dev cases whose full-atlas top-1 is the true leaf",
        "tau": round(tau, 4),
        "dev_rows_errors": len(errors),
        "dev_present_cases": len(present),
        "dev_present_top1_correct": len(correct),
        "dev_fit_correct_quantiles": {q: round(float(np.percentile(fits, q)), 3) for q in (5, 25, 50, 75, 95)},
        "dev_fit_removed_quantiles": {q: round(float(np.percentile(removed_fits, q)), 3) for q in (5, 25, 50, 75, 95)},
        "info_only_dev_behaviour": {
            "S0_abstain_present": sum(map(s0, present)),
            "S0_abstain_removed": sum(map(s0, removed)),
            "S1_abstain_present": sum(map(s1, present)),
            "S1_abstain_removed": sum(map(s1, removed)),
            "n_present": len(present),
            "n_removed": len(removed),
        },
    }
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
