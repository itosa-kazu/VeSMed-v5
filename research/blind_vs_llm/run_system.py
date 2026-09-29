"""Run the unmodified V5 geometry-first ranking on cases, with the true leaf present or removed.

For every (case, condition) it records the top-10 leaves, the rank of the true
leaf, the illness delta against the health reference, and a fit statistic for
the top-ranked leaf:

    fit = mean over scored axes of z^2, z = (observed - expected) / sigma,

taken at that leaf's best latent time (the runtime's own residuals, diagonal
only). It answers "how far, on average, does the patient sit from what this
disease expects", which the runtime itself never turns into a decision.

Usage:
  python run_system.py --cases <file-or-dir> [...] --out results.jsonl
                       [--conditions present,removed] [--workers 8]
"""

import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("VESMED_SCORE_MODE", "grid")
os.environ.setdefault("VESMED_TIME_GRID_N", "21")
os.environ.setdefault("VESMED_MAX_COMBO_SIZE", "1")
os.environ.setdefault("VESMED_N_CANDIDATE_WORKERS", "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import v5_joint_sde_case_test as rt  # noqa: E402

_ALL_MANIFOLDS = None
_MASTER_AXES = None


def all_manifolds():
    global _ALL_MANIFOLDS, _MASTER_AXES
    if _ALL_MANIFOLDS is None:
        _ALL_MANIFOLDS = {label: rt.load_manifold(path) for label, path in rt.MANIFOLD_PATHS.items()}
        _MASTER_AXES = rt.load_master_axes()
    return _ALL_MANIFOLDS, _MASTER_AXES


def fit_statistic(score):
    best = score.get("best") or {}
    xs, mus, sigmas, meta = best.get("x") or [], best.get("mu") or [], best.get("sigmas") or [], best.get("meta") or []
    residuals = []
    for x, mu, sigma, info in zip(xs, mus, sigmas, meta):
        if sigma is None or not sigma > 0:
            continue
        z = (float(x) - float(mu)) / float(sigma)
        residuals.append({"axis_id": info[0], "z": round(z, 3), "via": str(info[4])})
    if not residuals:
        return None, []
    fit = sum(r["z"] ** 2 for r in residuals) / len(residuals)
    residuals.sort(key=lambda r: -abs(r["z"]))
    return fit, residuals[:5]


def run_one(case_path, condition):
    manifolds_all, master_axes = all_manifolds()
    case = rt.load_case(Path(case_path))
    truth = rt.expected_tuple(case)
    removed = tuple(truth) if condition == "removed" else tuple()
    manifolds = {k: v for k, v in manifolds_all.items() if k not in removed}
    background_axes = rt.build_background_axes(manifolds, master_axes)

    scores = []
    for disease_id in manifolds:
        cand = (disease_id,)
        if not rt.candidate_allowed_for_case(case, cand, manifolds):
            continue
        score = rt.score_candidate(case, cand, manifolds, background_axes)
        if score is not None:
            scores.append(score)
    scores.sort(key=lambda s: -s["log_marginal"])
    health = rt.score_health_reference(case, manifolds, background_axes)
    health_logp = health["log_marginal"] if health else None

    top = []
    for rank, score in enumerate(scores[:10], start=1):
        fit, residuals = fit_statistic(score)
        top.append({
            "rank": rank,
            "disease_id": score["candidate"],
            "log_marginal": round(score["log_marginal"], 3),
            "delta_to_health": None if health_logp is None else round(score["log_marginal"] - health_logp, 3),
            "fit_mean_z2": None if fit is None else round(fit, 4),
            "top_residuals": residuals if rank == 1 else None,
        })
    ranked_ids = [s["candidate"] for s in scores]
    truth_rank = None
    if truth and not removed and truth[0] in ranked_ids:
        truth_rank = ranked_ids.index(truth[0]) + 1
    return {
        "case_id": case.get("case_id"),
        "case_path": str(case_path),
        "truth": list(truth),
        "condition": condition,
        "n_candidates": len(scores),
        "n_observed_axes": len(case.get("observations_by_axis") or {}),
        "truth_rank": truth_rank,
        "health_log_marginal": None if health_logp is None else round(health_logp, 3),
        "top10": top,
    }


def _task(args):
    case_path, condition = args
    try:
        return run_one(case_path, condition)
    except Exception as exc:  # keep the batch alive; the failure is recorded, not hidden
        return {"case_path": str(case_path), "condition": condition, "error": f"{type(exc).__name__}: {exc}"}


def expand_cases(items):
    paths = []
    for item in items:
        p = Path(item)
        paths.extend(sorted(p.glob("*.json")) if p.is_dir() else [p])
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--conditions", default="present,removed")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()

    tasks = [(str(p), c) for p in expand_cases(args.cases) for c in args.conditions.split(",")]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    with out.open("w", encoding="utf-8") as fh:
        if args.workers <= 1:
            results = map(_task, tasks)
        else:
            pool = ProcessPoolExecutor(max_workers=args.workers)
            results = (f.result() for f in as_completed([pool.submit(_task, t) for t in tasks]))
        for result in results:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            fh.flush()
            done += 1
            status = result.get("error") or f"top1={result['top10'][0]['disease_id'] if result.get('top10') else None}"
            print(f"[{done}/{len(tasks)}] {Path(result['case_path']).name} {result['condition']}: {status}", flush=True)


if __name__ == "__main__":
    main()
