"""Summarize diagnose_coverage.py output for dev vs test (exploratory)."""

import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent

for name in ("dev", "test"):
    rows = [json.loads(l) for l in (HERE / name / f"coverage_{name}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    share = [r["n_explained_by_truth"] / r["n_axes"] for r in rows if r["n_axes"]]
    z_own = [r["mean_z2_truth_axes"] for r in rows if r["mean_z2_truth_axes"] is not None]
    z_bg = [r["mean_z2_background_axes"] for r in rows if r["mean_z2_background_axes"] is not None]
    print(f"{name}: n={len(rows)}  median share of axes explained by the true disease={st.median(share):.2f}  "
          f"median mean-z2 on those axes={st.median(z_own):.1f}  on background axes={st.median(z_bg):.1f}")
    if name == "test":
        for r in rows:
            worst = ", ".join(f"{w['axis']} z={w['z']}" for w in r["worst_background_axes"][:3])
            print(f"  {r['truth']}: {r['n_explained_by_truth']}/{r['n_axes']} own; own z2={r['mean_z2_truth_axes']} bg z2={r['mean_z2_background_axes']} | worst bg: {worst}")
