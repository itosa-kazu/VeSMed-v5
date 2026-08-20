"""Rank the critical HAV/ALF/cardiac cut against every active single and pair."""
from __future__ import annotations

import itertools
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("VESMED_MAX_COMBO_SIZE", "2")
os.environ.setdefault("VESMED_SCORE_MODE", "grid")
os.environ.setdefault("VESMED_RANKING_PHILOSOPHY", "geometry_first")
os.environ.setdefault("VESMED_EVIDENCE_MODE", "case")
os.environ.setdefault("VESMED_N_CANDIDATE_WORKERS", "8")

import v5_joint_sde_case_test as joint  # noqa: E402


def compact(score: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "candidate": score["candidate"],
        "log_marginal": float(score["log_marginal"]),
        "mean_log_per_axis": float(score["mean_log_per_axis"]),
        "n_axes": int(score["n_axes"]),
    }


def main() -> None:
    case_path = HERE / "staged_cases" / "PMC7005653" / "v5_case_02_PMC7005653_DAY_2.json"
    case = joint.load_case(case_path)
    manifolds = {label: joint.load_manifold(path) for label, path in joint.MANIFOLD_PATHS.items()}
    background = joint.build_background_axes(manifolds, joint.load_master_axes())
    labels = list(manifolds)
    candidates = [(label,) for label in labels] + list(itertools.combinations(labels, 2))
    scores = joint.score_candidates_for_case(case, manifolds, background, candidates)
    scores.sort(key=lambda item: -item["log_marginal"])
    rank_by_name = {score["candidate"]: rank for rank, score in enumerate(scores, 1)}
    probes = [
        "D-ACUTE-HEPATITIS-A+D-ACUTE-LIVER-FAILURE",
        "D-ACUTE-HEPATITIS-A+D-ACUTE-MYOCARDITIS",
        "D-ACUTE-LIVER-FAILURE+D-ACUTE-MYOCARDITIS",
        "D-ACUTE-HEPATITIS-A",
        "D-ACUTE-LIVER-FAILURE",
    ]
    result = {
        "case_file": str(case_path),
        "case_file_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
        "active_manifold_count": len(manifolds),
        "candidate_count": len(candidates),
        "top20": [compact(score, rank) for rank, score in enumerate(scores[:20], 1)],
        "probe_ranks": {name: rank_by_name.get(name) for name in probes},
        "takotsubo_active_manifold_present": "D-TAKOTSUBO-CARDIOMYOPATHY" in manifolds,
    }
    out = HERE / "critical_day2_full_pairs.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
