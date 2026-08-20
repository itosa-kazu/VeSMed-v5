"""Fail-closed checks for the real-case longitudinal stress-test artifacts."""
from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STAGED = HERE / "staged_cases"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import v5_joint_sde_case_test as joint  # noqa: E402


def available_day(item: dict) -> float | None:
    for key in ("available_at_day", "result_day", "reported_day", "report_day", "day"):
        if item.get(key) is not None:
            return float(item[key])
    return None


def main() -> None:
    manifest = json.loads((STAGED / "manifest.json").read_text(encoding="utf-8"))
    paths = [Path(path) for path in manifest["generated_files"]]
    assert len(paths) == 11, f"expected 11 cuts, got {len(paths)}"
    assert len(list(STAGED.glob("PMC*/v5_case_*.json"))) == len(paths), "stale staged files present"

    for path in paths:
        assert path.exists(), path
        case = json.loads(path.read_text(encoding="utf-8"))
        cut = float(case["snapshot_day"])
        source = Path(case["provenance_contract"]["source_case_path"])
        assert source.exists(), source
        for section in ("observations", "course_observations"):
            for item in case.get(section, []):
                day = available_day(item)
                assert day is None or day <= cut, (path.name, section, day, cut)
        for item in case.get("action_history", []):
            if item.get("day") is not None:
                assert float(item["day"]) <= cut, (path.name, "action_history", item["day"], cut)

    tma_admission = joint.load_case(paths[0])
    assert "anti_gbm_antibody_positivity_probability" in tma_admission["observations_by_axis"]
    assert "active_serious_infection_activity" not in tma_admission["observations_by_axis"]
    tma_workup = joint.load_case(paths[3])
    for axis_id in ("renal_biopsy_tma_confirmation_activity", "adamts13_activity", "schistocytes_presence"):
        assert axis_id in tma_workup["observations_by_axis"], axis_id
    assert "linear_gbm_igg_staining_activity" not in tma_workup["observations_by_axis"]

    results = json.loads((HERE / "longitudinal_results.json").read_text(encoding="utf-8"))
    assert len(results["stages"]) == len(paths)
    assert results["runtime"]["shared_posterior_carried_between_cuts"] is False
    history_probes = [s["history_collision_probe"] for s in results["stages"] if s["history_collision_probe"]]
    action_probes = [s["action_history_collision_probe"] for s in results["stages"] if s["action_history_collision_probe"]]
    assert history_probes and all(
        p["prepared_observation_maps_identical"] and p["focused_score_outputs_identical"]
        for p in history_probes
    )
    assert action_probes and all(
        p["prepared_observation_maps_identical"] and p["focused_score_outputs_identical"]
        for p in action_probes
    )

    hav_coverage = results["atlas_coverage_audit"]["PMC7005653"]
    takotsubo = next(x for x in hav_coverage if x["disease_id"] == "D-TAKOTSUBO-CARDIOMYOPATHY")
    assert takotsubo["active_manifold_present"] is False
    assert all("paper_process_atlas_coverage" not in s for s in results["stages"])
    assert all("unsupported_paper_processes" not in s for s in results["stages"])
    assert not (ROOT / "distillations" / "v5_D-TAKOTSUBO-CARDIOMYOPATHY.json").exists()

    full_pairs = json.loads((HERE / "critical_day2_full_pairs.json").read_text(encoding="utf-8"))
    critical_case = STAGED / "PMC7005653" / "v5_case_02_PMC7005653_DAY_2.json"
    assert full_pairs["case_file_sha256"] == hashlib.sha256(critical_case.read_bytes()).hexdigest()
    assert full_pairs["candidate_count"] == 17020
    assert full_pairs["probe_ranks"]["D-ACUTE-HEPATITIS-A+D-ACUTE-LIVER-FAILURE"] == 371

    tma_policy = (HERE / "treatment_tma_result.txt").read_text(encoding="utf-8")
    alf_policy = (HERE / "treatment_alf_result.txt").read_text(encoding="utf-8")
    assert "eculizumab" in tma_policy and "ravulizumab" in tma_policy
    for token in ("urgent_liver_transplantation", "acyclovir", "pregnancy_context_delivery", "therapeutic_plasma_exchange"):
        assert token in alf_policy, token

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.splitlines()
    active_changes = [
        line for line in status
        if (line[3:].replace("\\", "/").startswith("distillations/v5_")
            or line[3:].replace("\\", "/").startswith("distillations/cases/"))
    ]
    assert not active_changes, active_changes

    summary = {
        "status": "PASS",
        "staged_cut_count": len(paths),
        "history_collision_probe_count": len(history_probes),
        "action_history_ablation_probe_count": len(action_probes),
        "active_manifold_count": results["runtime"]["active_manifold_count"],
        "takotsubo_active_manifold_present": False,
        "active_atlas_or_case_changes": active_changes,
    }
    (HERE / "verification.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
