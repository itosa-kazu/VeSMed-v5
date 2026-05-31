import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = ROOT / "distillations" / "cases"
DISTILL_DIR = ROOT / "distillations"
OUT_DIR = ROOT / "tmp_blind_eval" / "skill50_20260531"
OUT_CASE_DIR = OUT_DIR / "cases"
MANIFEST_PATH = OUT_DIR / "skill50_manifest.json"

TARGET_N = 50
EXCLUDE_BATCH_DIRS = [
    ROOT / "tmp_blind_eval" / "skill20_20260531" / "cases",
]


def git_dirty_paths():
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", "distillations/cases"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    dirty = set()
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty.add(path.replace("\\", "/"))
    return dirty


def active_disease_ids():
    ids = set()
    for path in DISTILL_DIR.glob("v5_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if data.get("case_id"):
            continue
        axes = data.get("axes")
        if not isinstance(axes, list):
            continue
        if not any(isinstance(axis, dict) and axis.get("axis_id") for axis in axes):
            continue
        ids.add((data.get("disease") or path.stem.removeprefix("v5_")).strip())
    return ids


def excluded_source_ids():
    ids = set()
    for directory in EXCLUDE_BATCH_DIRS:
        if not directory.exists():
            continue
        for path in directory.glob("v5_case_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            for key in ("case_id", "source_pmcid", "source_pmid"):
                value = str(data.get(key) or "").strip()
                if value:
                    ids.add(value)
    return ids


def expected_tuple(data):
    if isinstance(data.get("expected_manifolds"), list) and data["expected_manifolds"]:
        return tuple(str(item).strip() for item in data["expected_manifolds"] if str(item).strip())
    expected = str(data.get("expected_manifold") or data.get("expected_disease_id") or "").strip()
    return (expected,) if expected else tuple()


def disease_order_key(disease_id):
    # Spread the batch over the active atlas instead of taking 50 adjacent files.
    return sum(ord(ch) for ch in disease_id), disease_id


def case_quality_key(item):
    path, data = item
    obs = data.get("observations") or []
    pmcid = str(data.get("source_pmcid") or "")
    dirty = str(path.relative_to(ROOT)).replace("\\", "/") in DIRTY_PATHS
    return (
        dirty,
        not pmcid.startswith("PMC"),
        -len(obs),
        str(data.get("case_id") or path.stem),
    )


def load_candidates():
    active_ids = active_disease_ids()
    excluded = excluded_source_ids()
    grouped = defaultdict(list)
    skipped = defaultdict(int)
    for path in sorted(CASE_DIR.glob("v5_case_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            skipped["json_error"] += 1
            continue
        case_id = str(data.get("case_id") or path.stem).strip()
        pmcid = str(data.get("source_pmcid") or "").strip()
        pmid = str(data.get("source_pmid") or "").strip()
        if case_id.startswith("SKILL20_") or case_id in excluded or pmcid in excluded or pmid in excluded:
            skipped["skill20_overlap"] += 1
            continue
        expected = expected_tuple(data)
        if len(expected) != 1:
            skipped["not_single_expected"] += 1
            continue
        disease_id = expected[0]
        if disease_id not in active_ids:
            skipped["expected_not_active"] += 1
            continue
        if not (pmcid.startswith("PMC") or pmid):
            skipped["no_literature_id"] += 1
            continue
        if not isinstance(data.get("observations"), list) or len(data["observations"]) < 3:
            skipped["too_few_observations"] += 1
            continue
        grouped[disease_id].append((path, data))
    return grouped, skipped


def select_cases(grouped):
    selected = []
    for disease_id in sorted(grouped, key=disease_order_key):
        if len(selected) >= TARGET_N:
            break
        selected.append(sorted(grouped[disease_id], key=case_quality_key)[0])
    return selected


def main():
    grouped, skipped = load_candidates()
    selected = select_cases(grouped)
    if len(selected) != TARGET_N:
        raise SystemExit(f"selected {len(selected)} cases, expected {TARGET_N}; skipped={dict(skipped)}")

    OUT_CASE_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_CASE_DIR.glob("v5_case_*.json"):
        old.unlink()

    manifest = {
        "batch_id": "skill50_20260531",
        "source_pool": str(CASE_DIR.relative_to(ROOT)),
        "selection_rule": "50 single-manifold real PMC/PubMed active cases, one per expected disease when possible, excluding skill20 overlaps",
        "target_n": TARGET_N,
        "available_disease_groups": len(grouped),
        "skipped_counts": dict(skipped),
        "selected_cases": [],
    }
    for path, data in selected:
        out_path = OUT_CASE_DIR / path.name
        shutil.copy2(path, out_path)
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        manifest["selected_cases"].append(
            {
                "case_id": data.get("case_id") or path.stem,
                "source_pmid": data.get("source_pmid") or "",
                "source_pmcid": data.get("source_pmcid") or "",
                "source_url": data.get("source_url") or "",
                "expected_manifold": expected_tuple(data)[0],
                "observations": len(data.get("observations") or []),
                "source_case_path": rel,
                "source_case_was_dirty": rel in DIRTY_PATHS,
                "batch_case_path": str(out_path.relative_to(ROOT)).replace("\\", "/"),
            }
        )
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"selected={len(selected)}")
    print(f"available_disease_groups={len(grouped)}")
    print(f"source_cases_dirty={sum(1 for row in manifest['selected_cases'] if row['source_case_was_dirty'])}")
    print(f"wrote {MANIFEST_PATH.relative_to(ROOT)}")


DIRTY_PATHS = git_dirty_paths()


if __name__ == "__main__":
    main()
