"""List the tool calls each LLM-baseline agent made, from its session transcript.

Pass criterion (DEVIATIONS.md item 5): the only tool calls are one Read of its own
llm_in/<label>.txt file, plus the harness hand-back call that returns the answer.
Usage: python audit_llm_tools.py <transcript_dir> LABEL=agentId [...]
"""

import json
import sys
from pathlib import Path


def tool_calls(path):
    calls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                inp = block.get("input") or {}
                target = inp.get("file_path") or inp.get("path") or inp.get("pattern") or inp.get("command") or ""
                calls.append((block.get("name"), Path(str(target)).name if target else ""))
    return calls


def main():
    base = Path(sys.argv[1])
    for pair in sys.argv[2:]:
        label, agent_id = pair.split("=")
        calls = tool_calls(base / f"agent-{agent_id}.jsonl")
        reads = [t for n, t in calls if n == "Read"]
        others = [(n, t) for n, t in calls if n != "Read"]
        ok = reads == [f"{label}.txt"] and all("handback" in (n or "").lower() for n, _ in others)
        print(f"{label} {'PASS' if ok else 'CHECK'} calls={calls}")


if __name__ == "__main__":
    main()
