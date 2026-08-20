"""Run current V5 diagnosis geometry against longitudinal real-case cuts."""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("VESMED_MAX_COMBO_SIZE", "1")
os.environ.setdefault("VESMED_SCORE_MODE", "grid")
os.environ.setdefault("VESMED_RANKING_PHILOSOPHY", "geometry_first")
os.environ.setdefault("VESMED_EVIDENCE_MODE", "case")
os.environ.setdefault("VESMED_N_CANDIDATE_WORKERS", "1")

import v5_joint_sde_case_test as joint  # noqa: E402


FOCUSED = {
    "PMC10448002": [
        "D-COMPLEMENT-MEDIATED-TMA",
        "D-ANTI-GBM-DISEASE",
        "D-CATASTROPHIC-APS",
        "D-TTP",
        "D-STEC-HUS",
        "D-DIC",
        "D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS",
    ],
    "PMC7005653": [
        "D-ACUTE-HEPATITIS-A",
        "D-ACUTE-LIVER-FAILURE",
        "D-CARDIOGENIC-SHOCK",
        "D-ACUTE-HEART-FAILURE",
        "D-ACUTE-MYOCARDITIS",
        "D-ACUTE-MYOCARDIAL-INFARCTION",
        "D-UNSTABLE-ANGINA",
    ],
}

PAPER_PROCESSES = {
    "PMC10448002": ["D-COMPLEMENT-MEDIATED-TMA"],
    "PMC7005653": [
        "D-ACUTE-HEPATITIS-A",
        "D-ACUTE-LIVER-FAILURE",
        "D-TAKOTSUBO-CARDIOMYOPATHY",
    ],
}

# User-facing labels for the diseases that appear in this fixed two-case
# experiment.  The active JSONs currently carry English names but not a
# canonical Japanese display-name field, so keep the small experiment label
# registry explicit rather than pretending an automatic translation is part of
# the medical ontology.
DISPLAY_NAMES = {
    "D-COMPLEMENT-MEDIATED-TMA": ("補体介在性血栓性微小血管症", "Complement-mediated thrombotic microangiopathy"),
    "D-ANTI-GBM-DISEASE": ("抗糸球体基底膜病", "Anti-glomerular basement membrane disease"),
    "D-ACUTE-HEPATITIS-A": ("急性A型肝炎", "Acute hepatitis A"),
    "D-ACUTE-LIVER-FAILURE": ("急性肝不全", "Acute liver failure"),
    "D-ACUTE-MYOCARDITIS": ("急性心筋炎", "Acute myocarditis"),
    "D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS": ("全身性強皮症腎クリーゼ", "Systemic sclerosis renal crisis"),
    "D-TAKOTSUBO-CARDIOMYOPATHY": ("たこつぼ症候群", "Takotsubo syndrome"),
}


def observation_map_payload(case: dict) -> list[dict]:
    rows = []
    for axis_id, obs in sorted(case["observations_by_axis"].items()):
        rows.append({
            "axis_id": axis_id,
            "value": obs.get("value"),
            "unit": obs.get("unit"),
            "day": obs.get("day"),
        })
    return rows


def observation_map_hash(case: dict) -> str:
    raw = json.dumps(observation_map_payload(case), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def display_candidate(candidate: str) -> str:
    parts = candidate.split("+")
    labels = []
    for disease_id in parts:
        ja, en = DISPLAY_NAMES.get(disease_id, ("日本語名未登録", "English name not registered"))
        labels.append(f"{ja} / {en} / `{disease_id}`")
    return " + ".join(labels)


def residuals(score: dict, limit: int = 5) -> list[dict]:
    best = score.get("best")
    if not best:
        return []
    rows = []
    for meta, x, mean, sigma in zip(best["meta"], best["x"], best["mu"], best["sigmas"]):
        axis_id, obs_value, unit, mu_value, source = meta
        z = abs((x - mean) / max(sigma, 1e-6))
        rows.append({
            "axis_id": axis_id,
            "observed": obs_value,
            "unit": unit,
            "expected_mu": mu_value,
            "source": source,
            "abs_z": float(z),
        })
    return sorted(rows, key=lambda item: -item["abs_z"])[:limit]


def score_rows(case: dict, manifolds: dict, background_axes: dict, candidates: list[tuple[str, ...]]) -> tuple[list[dict], dict | None]:
    scores = joint.score_candidates_for_case(case, manifolds, background_axes, candidates)
    health = joint.score_health_reference(case, manifolds, background_axes)
    if health:
        for score in scores:
            score["delta_to_health_reference"] = score["log_marginal"] - health["log_marginal"]
    scores.sort(key=lambda item: -item["log_marginal"])
    return scores, health


def compact_score(score: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "candidate": score["candidate"],
        "candidate_tuple": list(score["candidate_tuple"]),
        "log_marginal": score["log_marginal"],
        "mean_log_per_axis": score["mean_log_per_axis"],
        "n_axes": score["n_axes"],
        "delta_to_health_reference": score.get("delta_to_health_reference"),
        "latent_time_by_disease": (score.get("best") or {}).get("t_by_disease"),
        "largest_residuals": residuals(score),
    }


def target_rows(scores: list[dict], targets: list[str]) -> list[dict]:
    out = []
    for target in targets:
        found = next(((idx, score) for idx, score in enumerate(scores, 1) if score["candidate"] == target), None)
        if found:
            idx, score = found
            out.append(compact_score(score, idx))
        else:
            out.append({"candidate": target, "rank": None, "reason": "not_scored_or_not_active"})
    return out


def family_for_path(path: Path) -> str:
    return path.parent.name


def score_signature(case: dict, manifolds: dict, background_axes: dict, candidates: list[tuple[str, ...]]) -> list[tuple[str, float]]:
    scores = joint.score_candidates_for_case(case, manifolds, background_axes, candidates)
    return sorted((score["candidate"], float(score["log_marginal"])) for score in scores)


def history_collision(case_path: Path, prepared: dict, manifolds: dict, background_axes: dict, candidates: list[tuple[str, ...]]) -> dict | None:
    raw = json.loads(case_path.read_text(encoding="utf-8"))
    twin = copy.deepcopy(raw)
    if "PMC7005653" in raw["case_id"] and raw["snapshot_day"] >= 2:
        for obs in twin.get("observations", []):
            if obs.get("axis_id") == "left_ventricular_ejection_fraction":
                obs["value"] = 15.0
                obs["source_text_value"] = "counterfactual prior-history probe: EF 15% before recovery to the same day-2 EF 32%"
                break
        altered = "prior day-0 EF 52 -> 15; current day-2 EF unchanged at 32"
    elif "PMC10448002" in raw["case_id"] and raw["snapshot_day"] >= 4:
        for obs in twin.get("observations", []):
            if obs.get("axis_id") == "platelet_count":
                obs["value"] = 250.0
                obs["source_text_value"] = "counterfactual prior-history probe: admission platelet 250 with same later platelet value"
                break
        altered = "prior admission platelet 92 -> 250; current later platelet unchanged"
    else:
        return None
    twin["case_id"] = raw["case_id"] + "_HISTORY_TWIN"
    twin_prepared = joint.prepare_case_data(twin)
    original_scores = score_signature(prepared, manifolds, background_axes, candidates)
    twin_scores = score_signature(twin_prepared, manifolds, background_axes, candidates)
    return {
        "alteration": altered,
        "original_prepared_observation_map_hash": observation_map_hash(prepared),
        "twin_prepared_observation_map_hash": observation_map_hash(twin_prepared),
        "prepared_observation_maps_identical": observation_map_payload(prepared) == observation_map_payload(twin_prepared),
        "focused_score_outputs_identical": original_scores == twin_scores,
        "raw_histories_identical": False,
    }


def action_history_collision(case_path: Path, prepared: dict, manifolds: dict, background_axes: dict, candidates: list[tuple[str, ...]]) -> dict | None:
    """Test whether diagnostic ranking changes when prior actions vanish."""
    raw = json.loads(case_path.read_text(encoding="utf-8"))
    actions = raw.get("action_history") or []
    if not actions:
        return None
    twin = copy.deepcopy(raw)
    twin["case_id"] = raw["case_id"] + "_NO_ACTION_HISTORY"
    twin["action_history"] = []
    twin_prepared = joint.prepare_case_data(twin)
    original_scores = score_signature(prepared, manifolds, background_axes, candidates)
    twin_scores = score_signature(twin_prepared, manifolds, background_axes, candidates)
    return {
        "removed_action_count": len(actions),
        "original_prepared_observation_map_hash": observation_map_hash(prepared),
        "no_action_prepared_observation_map_hash": observation_map_hash(twin_prepared),
        "prepared_observation_maps_identical": observation_map_payload(prepared) == observation_map_payload(twin_prepared),
        "focused_score_outputs_identical": original_scores == twin_scores,
    }


def main() -> None:
    stage_root = HERE / "staged_cases"
    manifest_path = stage_root / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("No staged-case manifest. Run build_staged_cases.py first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = [Path(path) for path in manifest.get("generated_files") or []]
    if not paths:
        raise SystemExit("No staged cases. Run build_staged_cases.py first.")

    manifolds = {label: joint.load_manifold(path) for label, path in joint.MANIFOLD_PATHS.items()}
    background_axes = joint.build_background_axes(manifolds, joint.load_master_axes())
    singles = [(label,) for label in manifolds]
    results = {
        "runtime": {
            "active_manifold_count": len(manifolds),
            "score_mode": joint.SCORE_MODE,
            "ranking_philosophy": joint.ranking_philosophy_label(),
            "single_candidate_count": len(singles),
            "shared_posterior_carried_between_cuts": False,
            "note": "Each cut calls score_candidate independently; no posterior/state object is returned for the next cut.",
        },
        "atlas_coverage_audit": {
            family: [
                {"disease_id": disease_id, "active_manifold_present": disease_id in manifolds}
                for disease_id in disease_ids
            ]
            for family, disease_ids in PAPER_PROCESSES.items()
        },
        "stages": [],
    }

    for index, path in enumerate(paths, 1):
        print(f"[{index}/{len(paths)}] scoring {path.name}", flush=True)
        case = joint.load_case(path)
        scores, health = score_rows(case, manifolds, background_axes, singles)
        family = family_for_path(path)
        targets = [case["expected_manifold"]]
        targets.extend(case.get("related_manifolds_per_paper") or [])
        target_combo = "+".join(sorted(targets)) if len(targets) > 1 else None

        focused_ids = [d for d in FOCUSED[family] if d in manifolds]
        focused_candidates = [(d,) for d in focused_ids] + list(itertools.combinations(focused_ids, 2))
        focused_scores, focused_health = score_rows(case, manifolds, background_axes, focused_candidates)

        stage = {
            "case_file": str(path),
            "case_id": case["case_id"],
            "source_pmcid": case.get("source_pmcid"),
            "snapshot_day": case.get("snapshot_day"),
            "snapshot_label": case.get("snapshot_label"),
            "ranked_axis_count": len(case["observations_by_axis"]),
            "prepared_observation_map_hash": observation_map_hash(case),
            "top10_singles": [compact_score(score, rank) for rank, score in enumerate(scores[:10], 1)],
            "paper_supported_single_targets": target_rows(scores, targets),
            "health_reference": {
                "log_marginal": health["log_marginal"] if health else None,
                "mean_log_per_axis": health["mean_log_per_axis"] if health else None,
                "n_axes": health["n_axes"] if health else None,
            },
            "focused_top10_singles_and_pairs": [compact_score(score, rank) for rank, score in enumerate(focused_scores[:10], 1)],
            "focused_target_pair": target_rows(focused_scores, [target_combo]) if target_combo else [],
            "focused_health_reference_logP": focused_health["log_marginal"] if focused_health else None,
            "history_collision_probe": history_collision(
                path, case, manifolds, background_axes, [(d,) for d in focused_ids]
            ),
            "action_history_collision_probe": action_history_collision(
                path, case, manifolds, background_axes, [(d,) for d in focused_ids]
            ),
        }
        results["stages"].append(stage)

    out = HERE / "longitudinal_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Live longitudinal ranking summary",
        "",
        f"Active manifolds: {len(manifolds)}; mode: {joint.SCORE_MODE}; philosophy: {joint.ranking_philosophy_label()}.",
        "",
        "| Case cut | Day | Axes | Best single | Paper-supported target rank(s) | Best focused single/pair |",
        "|---|---:|---:|---|---|---|",
    ]
    for stage in results["stages"]:
        target_text = "; ".join(
            f"{display_candidate(x['candidate'])} #{x['rank']}" for x in stage["paper_supported_single_targets"]
        )
        best = stage["top10_singles"][0]["candidate"]
        best_focused = stage["focused_top10_singles_and_pairs"][0]["candidate"]
        lines.append(
            f"| {stage['case_id']} | {stage['snapshot_day']} | {stage['ranked_axis_count']} | "
            f"{display_candidate(best)} | {target_text} | {display_candidate(best_focused)} |"
        )
    (HERE / "longitudinal_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
