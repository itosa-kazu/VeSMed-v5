"""Fill the frozen LLM prompt template for every accepted test case and condition.

Writes prompts/<CASE_ID>__present.txt and prompts/<CASE_ID>__removed.txt.
The only difference between the two is whether the true leaf is in the list.

Usage: python build_llm_prompts.py <CASE_ID> [...]
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    template = (HERE / "frozen" / "llm_prompt_template.txt").read_text(encoding="utf-8")
    names = json.loads((HERE / "frozen" / "display_names_en.json").read_text(encoding="utf-8"))
    out_dir = HERE / "prompts"
    out_dir.mkdir(exist_ok=True)
    for case_id in sys.argv[1:]:
        case = json.loads((HERE / "cases" / f"v5_case_{case_id}.json").read_text(encoding="utf-8"))
        truth = case["expected_manifold"]
        vignette = (HERE / "vignettes" / f"{case_id}.txt").read_text(encoding="utf-8").strip()
        for condition in ("present", "removed"):
            ids = sorted(d for d in names if not (condition == "removed" and d == truth))
            candidates = "\n".join(f"{d}: {names[d]}" for d in ids)
            text = template.replace("{VIGNETTE}", vignette).replace("{CANDIDATES}", candidates)
            (out_dir / f"{case_id}__{condition}.txt").write_text(text, encoding="utf-8")
            print(f"{case_id} {condition}: {len(ids)} candidates")


if __name__ == "__main__":
    main()
