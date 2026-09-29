"""Freeze the inputs of the blind V5-vs-LLM experiment before any new case is seen.

Writes:
  frozen/atlas.json          active leaves (id, English name, eligibility)
  frozen/leaf_order.json     seeded order in which case agents search leaves
  frozen/known_pmcids.txt    every PMC id already mentioned anywhere in the repo
"""

import hashlib
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "frozen"
SEED = 20260929

sys.path.insert(0, str(ROOT))
import v5_joint_sde_case_test as rt  # noqa: E402


def leaf_record(disease_id, path):
    data = json.loads(path.read_text(encoding="utf-8"))
    scope = data.get("distillation_scope")
    stage = scope.get("candidate_requires_diagnostic_stage") if isinstance(scope, dict) else None
    return {
        "disease_id": disease_id,
        "disease_name_en": data.get("disease_name") or disease_id,
        "requires_diagnostic_stage": stage,
        "presentation_eligible": not stage,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def known_pmcids():
    ids = set()
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".md", ".txt", ".py"}:
            continue
        if "blind_vs_llm" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        ids.update(m.upper() for m in re.findall(r"PMC\d{5,8}", text, flags=re.IGNORECASE))
    return sorted(ids)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    atlas = [leaf_record(d, p) for d, p in rt.MANIFOLD_PATHS.items()]
    eligible = sorted(r["disease_id"] for r in atlas if r["presentation_eligible"])
    order = list(eligible)
    random.Random(SEED).shuffle(order)

    (OUT / "atlas.json").write_text(json.dumps(atlas, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "leaf_order.json").write_text(
        json.dumps({"seed": SEED, "n_active": len(atlas), "n_eligible": len(order), "order": order}, indent=2),
        encoding="utf-8",
    )
    pmcids = known_pmcids()
    (OUT / "known_pmcids.txt").write_text("\n".join(pmcids) + "\n", encoding="utf-8")
    print(f"active leaves={len(atlas)} eligible={len(order)} known_pmcids={len(pmcids)}")
    print("first 24 in search order:", order[:24])


if __name__ == "__main__":
    main()
