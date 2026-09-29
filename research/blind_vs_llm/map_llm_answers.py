"""Copy llm/raw/<LABEL>.json to llm/<CASE_ID>__<condition>.json using llm/assignment.json."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    assignment = json.loads((HERE / "llm" / "assignment.json").read_text(encoding="utf-8"))
    done = missing = 0
    for label, item in sorted(assignment.items()):
        raw = HERE / "llm" / "raw" / f"{label}.json"
        if not raw.exists():
            missing += 1
            continue
        answer = json.loads(raw.read_text(encoding="utf-8"))
        answer["_label"] = label
        out = HERE / "llm" / f"{item['case_id']}__{item['condition']}.json"
        out.write_text(json.dumps(answer, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
    print(f"mapped {done}, missing {missing}")


if __name__ == "__main__":
    main()
