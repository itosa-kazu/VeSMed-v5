"""Combine system and LLM outputs into the pre-registered metrics (PROTOCOL.md sections 7-8).

Inputs:
  test/test_results.jsonl            from run_system.py on the accepted test cases
  llm/<CASE_ID>__<condition>.json    raw JSON answer of each fresh LLM subagent
Output: printed tables and test/metrics_<block>.json
Usage: python score.py [main|appendix|all]   (main = the pre-registered 10 cases)
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
S0_DELTA = 2.3


def load_llm(case_id, condition):
    path = HERE / "llm" / f"{case_id}__{condition}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def llm_rank(answer, truth):
    ids = [item.get("disease_id") for item in answer.get("ranking") or []]
    return ids.index(truth) + 1 if truth in ids else None


def main():
    block = sys.argv[1] if len(sys.argv) > 1 else "main"
    tau = json.loads((HERE / "frozen" / "threshold.json").read_text(encoding="utf-8"))["tau"]
    assignment = json.loads((HERE / "llm" / "assignment.json").read_text(encoding="utf-8"))
    in_block = {v["case_id"] for v in assignment.values() if block == "all" or v["block"] == block}
    rows = [json.loads(l) for l in (HERE / "test" / "test_results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    by_case = {}
    for r in rows:
        if r["case_id"] in in_block:
            by_case.setdefault(r["case_id"], {})[r["condition"]] = r

    table = []
    for case_id, conds in sorted(by_case.items()):
        truth = conds["present"]["truth"][0]
        entry = {"case_id": case_id, "truth": truth}
        for condition in ("present", "removed"):
            sys_row = conds[condition]
            top1 = sys_row["top10"][0]
            answer = load_llm(case_id, condition)
            entry[condition] = {
                "v5_top1": top1["disease_id"],
                "v5_truth_rank": sys_row["truth_rank"],
                "v5_delta_to_health": top1["delta_to_health"],
                "v5_fit": top1["fit_mean_z2"],
                "S0_abstain": top1["delta_to_health"] is not None and top1["delta_to_health"] <= S0_DELTA,
                "S1_abstain": top1["fit_mean_z2"] is not None and top1["fit_mean_z2"] > tau,
                "llm_top1": ((answer or {}).get("ranking") or [{}])[0].get("disease_id") if answer else None,
                "llm_top1_p": ((answer or {}).get("ranking") or [{}])[0].get("probability") if answer else None,
                "llm_truth_rank": llm_rank(answer, truth) if answer and condition == "present" else None,
                "llm_p_none": (answer or {}).get("p_none_of_list"),
                "L_abstain": (answer or {}).get("decision") == "none_fit" if answer else None,
                "llm_free_text": (answer or {}).get("most_likely_actual_diagnosis_free_text"),
            }
        table.append(entry)

    def count(cond, key, fn=bool):
        return sum(1 for e in table if e[cond][key] is not None and fn(e[cond][key]))

    def hits(key, k):
        return sum(1 for e in table if e["present"][key] is not None and e["present"][key] <= k)

    n = len(table)
    metrics = {
        "n_cases": n,
        "tau": tau,
        "present": {
            "v5_top1": hits("v5_truth_rank", 1), "v5_top3": hits("v5_truth_rank", 3), "v5_top10": hits("v5_truth_rank", 10),
            "llm_top1": hits("llm_truth_rank", 1), "llm_top3": hits("llm_truth_rank", 3), "llm_top10": hits("llm_truth_rank", 10),
            "false_abstain_S0": count("present", "S0_abstain"),
            "false_abstain_S1": count("present", "S1_abstain"),
            "false_abstain_L": count("present", "L_abstain"),
        },
        "removed": {
            "abstain_S0": count("removed", "S0_abstain"),
            "abstain_S1": count("removed", "S1_abstain"),
            "abstain_L": count("removed", "L_abstain"),
        },
    }
    a_s1, fa_s1, a_l = metrics["removed"]["abstain_S1"], metrics["present"]["false_abstain_S1"], metrics["removed"]["abstain_L"]
    if a_s1 >= 5 and fa_s1 <= 2 and a_s1 > a_l:
        verdict = "系统显示出价值"
    elif a_s1 >= 5 and fa_s1 > 2:
        verdict = "只是更爱拒答，不算价值"
    else:
        verdict = "这次没有显示出价值"
    metrics["verdict"] = verdict
    metrics["block"] = block
    (HERE / "test" / f"metrics_{block}.json").write_text(json.dumps({"metrics": metrics, "cases": table}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    for e in table:
        p, r = e["present"], e["removed"]
        print(f"\n{e['case_id']} truth={e['truth']}")
        print(f"  present: V5 rank={p['v5_truth_rank']} top1={p['v5_top1']} fit={p['v5_fit']} S1={p['S1_abstain']} | "
              f"LLM rank={p['llm_truth_rank']} top1={p['llm_top1']}({p['llm_top1_p']}) none={p['L_abstain']}")
        print(f"  removed: V5 top1={r['v5_top1']} fit={r['v5_fit']} S0={r['S0_abstain']} S1={r['S1_abstain']} | "
              f"LLM top1={r['llm_top1']}({r['llm_top1_p']}) p_none={r['llm_p_none']} none={r['L_abstain']} free='{r['llm_free_text']}'")


if __name__ == "__main__":
    main()
