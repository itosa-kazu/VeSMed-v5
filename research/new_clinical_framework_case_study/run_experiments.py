"""Run the two sealed real-case replays through the *new* framework.

This runner is intentionally independent of VeSMed V5.  It applies a separately
sealed runtime concept map, recursively updates one serialized shared state, and
forces diagnosis, natural forecast, and every action rollout to consume the exact
same state hash at each information cut.

The numerical engine is ordinal and uncalibrated.  Real cases can establish
ledger integrity and structural/case consistency; they cannot establish clinical
calibration or individual treatment counterfactual truth.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from case_adapter import NormalizedCase, load_case, validate_monotone_case
from framework import FrameworkModel, SharedPatientState, _severity
from harness_utils import assert_seal, load_json, seal_files, write_json


ROOT = Path(__file__).resolve().parent
CASE_MODEL = {
    "PMC10448002": ROOT / "models" / "tma_generic_model.json",
    "PMC7005653": ROOT / "models" / "hav_takotsubo_generic_model.json",
}
CASE_LEDGER = {
    case_id: ROOT / "cases" / case_id.lower() / "case_event_stream.json"
    for case_id in CASE_MODEL
}


def _observed_ids(spec: Mapping[str, Any]) -> set[str]:
    graph = spec.get("typed_factor_graph", {})
    nodes = graph.get("observed_nodes", graph.get("observation_nodes", []))
    return {str(row["id"]) for row in nodes}


def _action_ids(spec: Mapping[str, Any]) -> list[str]:
    if "actions" in spec:
        rows = spec["actions"].get("catalog", [])
    else:
        rows = spec.get("dynamics", {}).get("action_catalog", [])
    if isinstance(rows, Mapping):
        return sorted(str(key) for key in rows)
    return sorted(
        str(row.get("action_id") or row.get("id"))
        for row in rows
        if row.get("action_id") or row.get("id")
    )


def _mapping_rows(concept_map: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    """Read the mapper's frozen schema, with narrow backwards-compatible forms."""

    cases = concept_map.get("cases", concept_map)
    body = cases.get(case_id, cases.get(case_id.lower(), {})) if isinstance(cases, Mapping) else {}
    if isinstance(body, Mapping) and isinstance(body.get("mappings"), Mapping):
        return body["mappings"]
    if isinstance(body, Mapping):
        return body
    raise ValueError(f"concept map has no mapping object for {case_id}")


def _disposition(row: Any) -> str:
    if isinstance(row, str):
        return "rankable_observation"
    return str(row.get("disposition", row.get("status", "record_only/unmapped"))).lower()


def _target_ids(row: Any) -> list[str]:
    if isinstance(row, str):
        return [row]
    values = row.get("observed_node_ids")
    if values is None:
        value = row.get("target_concept_id") or row.get("model_concept_id")
        values = [] if value is None else [value]
    if isinstance(values, str):
        values = [values]
    return [str(value) for value in values if value]


def apply_concept_map(
    case: NormalizedCase,
    spec: Mapping[str, Any],
    concept_map: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compile source events to model public events without inventing evidence.

    One source observation may map to multiple declared observed nodes.  All such
    projections retain the same ``source_result_id`` so the factor graph can
    prevent copies of one result from becoming independent evidence.
    """

    rows = _mapping_rows(concept_map, case.case_id)
    declared = _observed_ids(spec)
    compiled: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    source_rankable = 0
    mapped = 0
    record_only = 0
    unmapped = 0
    context_only = 0
    mapped_action_events = 0

    for event in case.events:
        source = copy.deepcopy(event)
        concept = str(source.get("concept_id") or "")
        if source.get("event_type") != "ObservationAvailable" or not source.get("rankable", False):
            mapping = rows.get(concept, {})
            action_ids = [] if not isinstance(mapping, Mapping) else list(mapping.get("action_ids", []))
            if source.get("event_type") in {"PerformedTreatment", "PerformedProcedure", "PlannedTreatment"} and action_ids:
                mapped_action_events += 1
                for index, action_id in enumerate(action_ids):
                    projected = copy.deepcopy(source)
                    projected["event_id"] = f"{source['event_id']}#action{index}:{action_id}"
                    projected["concept_id"] = str(action_id)
                    projected.setdefault("provenance", {})["runtime_mapping"] = {
                        "source_concept_id": concept,
                        "target_action_id": str(action_id),
                    }
                    compiled.append(projected)
            else:
                compiled.append(source)
            continue
        source_rankable += 1
        mapping = rows.get(concept)
        disposition = _disposition(mapping or {})
        targets = _target_ids(mapping or {})
        entry = {
            "source_event_id": source["event_id"],
            "source_concept_id": concept,
            "disposition": disposition,
            "observed_node_ids": targets,
        }
        if disposition == "rankable_observation":
            if not targets:
                raise ValueError(f"{case.case_id}:{concept} rankable but has no observed_node_ids")
            undeclared = sorted(set(targets).difference(declared))
            if undeclared:
                raise ValueError(
                    f"{case.case_id}:{concept} maps to nodes absent from sealed model: {undeclared}"
                )
            mapped += 1
            for index, target in enumerate(targets):
                projected = copy.deepcopy(source)
                projected["event_id"] = f"{source['event_id']}#mapped{index}:{target}"
                projected["concept_id"] = target
                projected["rankable"] = True
                provenance = projected.setdefault("provenance", {})
                provenance["source_result_id"] = source["event_id"]
                provenance["runtime_mapping"] = {
                    "source_concept_id": concept,
                    "target_observed_node_id": target,
                }
                compiled.append(projected)
        elif disposition == "context_or_action_only":
            context_only += 1
            demoted = copy.deepcopy(source)
            demoted["event_type"] = "ContextUpdate"
            demoted["rankable"] = False
            demoted.setdefault("provenance", {})["runtime_mapping"] = {
                "source_concept_id": concept,
                "disposition": disposition,
            }
            compiled.append(demoted)
        else:
            # Preserve unmapped facts in the public ledger but do not let them
            # silently alter a known branch likelihood.  Open-world pressure is
            # reported explicitly as mapping coverage, not fabricated evidence.
            if "unmapped" in disposition:
                unmapped += 1
            else:
                record_only += 1
            demoted = copy.deepcopy(source)
            demoted["event_type"] = "ContextUpdate"
            demoted["rankable"] = False
            demoted.setdefault("provenance", {})["runtime_mapping"] = {
                "source_concept_id": concept,
                "disposition": disposition,
            }
            compiled.append(demoted)
        audit.append(entry)

    denominator = max(1, source_rankable)
    stats = {
        "source_rankable_observation_count": source_rankable,
        "mapped_rankable_source_count": mapped,
        "context_or_action_only_count": context_only,
        "mapped_action_source_event_count": mapped_action_events,
        "record_only_count": record_only,
        "unmapped_count": unmapped,
        "record_only_or_unmapped_count": record_only + unmapped,
        "mapped_ratio": mapped / denominator,
        "record_only_ratio": record_only / denominator,
        "unmapped_ratio": unmapped / denominator,
        "record_only_or_unmapped_ratio": (record_only + unmapped) / denominator,
        "compiled_event_count": len(compiled),
        "mapping_audit": audit,
    }
    return sorted(compiled, key=lambda row: (row["available_cut"], row["event_id"])), stats


def _semantic_wire(state: SharedPatientState) -> dict[str, Any]:
    wire = state.to_dict()
    wire.pop("lineage", None)
    return wire


def _expected_direction(rollout: Mapping[str, Any]) -> str | None:
    outcomes = rollout.get("branch_outcomes", {})
    if not outcomes:
        return None
    initial = sum(float(v["posterior_mass"]) * float(v["initial_load"]) for v in outcomes.values())
    final = float(rollout["expected_final_burden"])
    if final < initial - 1e-9:
        return "improve"
    if final > initial + 1e-9:
        return "worsen"
    return "stable"


def _aggregate_observation_direction(
    current: Iterable[Mapping[str, Any]], nxt: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """A deliberately weak ordinal next-cut consistency proxy.

    This is not a clinical scoring rule: different observed nodes are not
    commensurate.  It is included only to ensure that the runner compares every
    cut with subsequently available facts rather than reporting final top-1.
    """

    def values(rows: Iterable[Mapping[str, Any]]) -> list[float]:
        return [
            _severity(row.get("value"))
            for row in rows
            if row.get("event_type") == "ObservationAvailable" and row.get("rankable", False)
        ]

    before = values(current)
    after = values(nxt)
    if not before or not after:
        return {"status": "NOT_ASSESSABLE", "reason": "no comparable mapped observations"}
    old = sum(before) / len(before)
    new = sum(after) / len(after)
    direction = "improve" if new < old - 1e-9 else "worsen" if new > old + 1e-9 else "stable"
    return {
        "status": "ORDINAL_AGGREGATE_PROXY_ONLY",
        "current_mean_severity": old,
        "next_mean_severity": new,
        "observed_direction": direction,
        "warning": "heterogeneous observed nodes are not clinically commensurate",
    }


def replay_case(
    case: NormalizedCase,
    spec: Mapping[str, Any],
    concept_map: Mapping[str, Any],
) -> dict[str, Any]:
    validate_monotone_case(case)
    events, mapping_stats = apply_concept_map(case, spec, concept_map)
    model = FrameworkModel.from_dict(spec)
    policies = _action_ids(spec)
    no_action = "A_NO_NEW_ACTION" if "A_NO_NEW_ACTION" in policies else "NoNewAction"
    if no_action not in policies:
        policies = [no_action, *policies]

    cuts: list[dict[str, Any]] = []
    state: SharedPatientState | None = None
    previous_cut = -1
    for index, cut_id in enumerate(case.cut_ids):
        delta = [row for row in events if previous_cut < row["available_cut"] <= index]
        available = [row for row in events if row["available_cut"] <= index]
        if state is None:
            state = model.initialize(delta, cut=index)
            recursive_closure_exact = True
        else:
            parent = state
            state = model.update(parent, delta, advance_to=index)
            restored = SharedPatientState.from_bytes(parent.to_bytes())
            fresh_model = FrameworkModel.from_dict(spec)
            cold = fresh_model.update(restored, delta, advance_to=index)
            recursive_closure_exact = cold.to_bytes() == state.to_bytes()
            if not recursive_closure_exact:
                raise AssertionError(f"fresh recursive closure failed at {case.case_id}:{cut_id}")

        cold_all = FrameworkModel.from_dict(spec).initialize(available, cut=index)
        semantic_cold_replay_equal = _semantic_wire(cold_all) == _semantic_wire(state)
        if not semantic_cold_replay_equal:
            raise AssertionError(f"full replay semantic closure failed at {case.case_id}:{cut_id}")

        diagnosis = model.diagnose(state)
        natural = model.rollout(state, {"policy_id": no_action}, horizon=1)
        action_rollouts = [model.rollout(state, {"policy_id": policy}, horizon=1) for policy in policies]
        plan = model.plan(state, [{"policy_id": policy} for policy in policies], horizon=1)
        hashes = {
            diagnosis["consumed_state_hash"],
            natural["consumed_state_hash"],
            plan["consumed_state_hash"],
            *(row["consumed_state_hash"] for row in action_rollouts),
        }
        exact_shared_state_hash = hashes == {state.state_hash}
        if not exact_shared_state_hash:
            raise AssertionError(f"query state hash divergence at {case.case_id}:{cut_id}")

        if index + 1 < len(case.cut_ids):
            next_available = [row for row in events if row["available_cut"] <= index + 1]
            observed = _aggregate_observation_direction(available, next_available)
            predicted = _expected_direction(natural)
            next_consistency = {
                **observed,
                "predicted_direction": predicted,
                "direction_consistent": (
                    observed.get("observed_direction") == predicted
                    if observed.get("observed_direction") and predicted
                    else None
                ),
                "next_cut_id": case.cut_ids[index + 1],
            }
        else:
            next_consistency = {"status": "NO_LATER_CUT"}

        wire = state.to_dict()
        cuts.append(
            {
                "cut_index": index,
                "cut_id": cut_id,
                "available_event_count": len(available),
                "delta_event_count": len(delta),
                "state_hash": state.state_hash,
                "parent_state_hash": wire["lineage"]["parent_state_hash"],
                "recursive_closure_exact": recursive_closure_exact,
                "semantic_full_replay_equal": semantic_cold_replay_equal,
                "exact_shared_state_hash_across_queries": exact_shared_state_hash,
                "branch_posterior": wire["branch_posterior"],
                "mode_posterior": wire["mode_posterior"],
                "unknown_mass": wire["unknown_mass"],
                "recognized_observation_count": wire["recognized_observation_count"],
                "unrecognized_observation_count": wire["unrecognized_observation_count"],
                "action_exposure": wire["action_exposure"],
                "diagnosis_readout": diagnosis,
                "natural_forecast": natural,
                "action_feasibility_and_rollouts": action_rollouts,
                "plan_readout": plan,
                "next_event_consistency": next_consistency,
                "warnings": wire["warnings"],
            }
        )
        previous_cut = index

    assert state is not None
    all_hashes_equal = all(row["exact_shared_state_hash_across_queries"] for row in cuts)
    all_recursive_closed = all(row["recursive_closure_exact"] for row in cuts)
    # This audit is intentionally post-replay and is never fed back into the
    # sealed model or runtime map.  It identifies concrete case-level failures
    # rather than tuning the model to the article's conclusion.
    final_top = max(cuts[-1]["branch_posterior"], key=cuts[-1]["branch_posterior"].get)
    selected_actions = [row["plan_readout"]["selected_policy_id"] for row in cuts]
    if case.case_id == "PMC10448002":
        readout_audit = {
            "status": "FAILED",
            "source_reported_final_process_reference": "B_COMPLEMENT_TMA",
            "model_final_top_branch": final_top,
            "final_branch_match": final_top == "B_COMPLEMENT_TMA",
            "mode_failure": (
                "initial presentation was labelled recovering and discharge was labelled compensated; "
                "the ordinal engine did not represent the procedural complication and later recovery as reliable mode transitions"
            ),
        }
    else:
        cardiac_cut = cuts[4]
        cardiac = cardiac_cut["branch_posterior"]
        top_mass = max(cardiac.values())
        top_tie = sorted(key for key, value in cardiac.items() if abs(value - top_mass) < 1e-12)
        readout_audit = {
            "status": "FAILED",
            "source_reported_cardiac_process_reference": "takotsubo_syndrome",
            "cardiac_workup_top_tie": top_tie,
            "takotsubo_uniquely_resolved": top_tie == ["takotsubo_syndrome"],
            "final_mode": max(cuts[-1]["mode_posterior"], key=cuts[-1]["mode_posterior"].get),
            "mode_failure": (
                "the state remained strained through extubation and ward transfer because no mapped recovery observation "
                "or action-conditioned recovery transition reached the mode estimator"
            ),
        }
    readout_audit.update(
        {
            "unique_selected_action_count": len(set(selected_actions)),
            "selected_actions_by_cut": selected_actions,
            "unknown_mass_range": [
                min(row["unknown_mass"] for row in cuts),
                max(row["unknown_mass"] for row in cuts),
            ],
            "mapping_gap_ratio": mapping_stats["record_only_or_unmapped_ratio"],
            "unknown_handling_failure": (
                "unknown mass stayed at its minimum while a large record-only/unmapped fraction remained outside the model; "
                "the current skeleton cannot distinguish benign record-only facts from OOD pressure"
            ),
            "audit_phase": "post_replay_no_model_or_mapping_feedback",
        }
    )

    return {
        "case_id": case.case_id,
        "source": case.source,
        "model_id": spec.get("model_id"),
        "model_status": spec.get("model_status", spec.get("status")),
        "mapping_coverage": mapping_stats,
        "cut_count": len(cuts),
        "all_query_hashes_exact": all_hashes_equal,
        "all_recursive_updates_closed": all_recursive_closed,
        "all_full_replays_semantically_equal": all(row["semantic_full_replay_equal"] for row in cuts),
        "cuts": cuts,
        "case_evidence_status": "CASE-CONSISTENT" if all_hashes_equal and all_recursive_closed else "FAILED",
        "clinical_case_readout_audit": readout_audit,
        "claim_boundary": {
            "supports": [
                "event-time availability replay",
                "single shared-state query contract",
                "recursive serializable state closure",
                "case-level structural consistency",
            ],
            "does_not_support": [
                "clinical diagnosis accuracy",
                "probability calibration",
                "individual treatment counterfactual truth",
                "clinical treatment recommendation",
            ],
        },
    }


def _write_report(result: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# 新临床框架：真实病例回放初步报告",
        "",
        "> 本报告只评估新框架的事件回放与共享状态合同，不使用 VeSMed V5。",
        "> 数值内核为未校准序数模型；动作模拟不是临床治疗建议。",
        "",
        "## 结果摘要",
        "",
    ]
    for case_id, case in result["real_cases"].items():
        coverage = case["mapping_coverage"]
        consistent = sum(
            row.get("next_event_consistency", {}).get("direction_consistent") is True
            for row in case["cuts"]
        )
        assessed = sum(
            row.get("next_event_consistency", {}).get("direction_consistent") is not None
            for row in case["cuts"]
        )
        lines.extend(
            [
                f"### {case_id}",
                "",
                f"- cuts: `{case['cut_count']}`",
                f"- shared-state exact hash: `{case['all_query_hashes_exact']}`",
                f"- recursive closure: `{case['all_recursive_updates_closed']}`",
                f"- mapped rankable ratio: `{coverage['mapped_ratio']:.3f}`",
                f"- record-only/unmapped ratio: `{coverage['record_only_or_unmapped_ratio']:.3f}`",
                f"- ordinal next-cut direction proxy: `{consistent}/{assessed}` (not a clinical metric)",
                f"- status: `{case['case_evidence_status']}`",
                f"- post-replay clinical readout audit: `{case['clinical_case_readout_audit']['status']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## 能说明什么",
            "",
            "- 同一个递归、可序列化患者状态确实能同时供诊断、自然预测和动作模拟读取。",
            "- 两个不同病例 schema 能按真实可见性 cut 回放，未来结果不会进入较早状态。",
            "- 映射覆盖、未知/record-only 信息和动作暴露均可审计。",
            "",
            "## 不能说明什么",
            "",
            "- 不能证明分支 posterior 是真实患病概率。",
            "- 不能把病例后续结局当成未实施治疗的反事实真值。",
            "- 不能证明总体临床有效，也不能证明这是唯一或最终理想模型。",
            "- `next_event_consistency` 只是异质序数观察的弱结构代理，不是医学准确率。",
            "",
            "## 两个病例暴露的具体失败",
            "",
            "- **PMC10448002**：最终 top branch 仍是 `B_TTP`，而不是病例后续证据支持的 `B_COMPLEMENT_TMA`；首次就诊还被标成 `recovering`。",
            "- **PMC7005653**：到心脏检查 cut，Takotsubo、myocarditis、ACS 三支仍完全并列；到拔管和转普通病房后，mode 仍停在 `strained`。",
            "- 两例的动作选择几乎不随 cut 改变，说明当前动作转移只是占位序数规则，不是有效的病例条件化规划。",
            "- 两例 unknown mass 都固定在最小值 `0.05`，但 record-only/unmapped 比例分别约为 41% 与 60%；当前骨架尚不会把模型外信息正确转成开放世界不确定性。",
            "- 这些失败推翻的是当前最小实现已经足够的说法，不是推翻聊天中的候选架构。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run(concept_map_path: Path, output_path: Path, report_path: Path) -> dict[str, Any]:
    assert_seal(ROOT, load_json(ROOT / "evidence" / "blind_model_seal.json"))
    assert_seal(ROOT, load_json(ROOT / "evidence" / "case_ledger_seal.json"))
    if not concept_map_path.exists():
        raise FileNotFoundError(
            f"runtime concept map is required and must be sealed separately: {concept_map_path}"
        )
    concept_map = load_json(concept_map_path)
    mapping_seal = seal_files(ROOT, [concept_map_path], role="post_freeze_runtime_concept_mapping")
    write_json(ROOT / "evidence" / "runtime_concept_map_seal.json", mapping_seal)

    real_cases: dict[str, Any] = {}
    for case_id in sorted(CASE_MODEL):
        spec = load_json(CASE_MODEL[case_id])
        case = load_case(CASE_LEDGER[case_id])
        real_cases[case_id] = replay_case(case, spec, concept_map)

    result = {
        "protocol": "new-clinical-framework-real-case-replay/1",
        "uses_v5": False,
        "framework_under_test": {
            "state": [
                "branch/topology posterior",
                "branch-local continuous coordinates",
                "compensated/decompensated discrete modes",
                "action-sufficient history summary",
            ],
            "factor_graph": "hidden mechanisms/modes -> observations",
            "hybrid_controlled_dynamics": "time and performed actions -> state/mode",
            "branch_geometry": "topology-aware clinical nearness",
            "shared_state": "identical serialized state hash for diagnosis, natural forecast, and action forecasts",
        },
        "artifact_seals": {
            "blind_models": load_json(ROOT / "evidence" / "blind_model_seal.json"),
            "case_ledgers": load_json(ROOT / "evidence" / "case_ledger_seal.json"),
            "runtime_concept_map": mapping_seal,
        },
        "real_cases": real_cases,
        "structural_status": (
            "CASE-CONSISTENT"
            if all(row["case_evidence_status"] == "CASE-CONSISTENT" for row in real_cases.values())
            else "FAILED"
        ),
        "clinical_readout_status": (
            "FAILED"
            if any(row["clinical_case_readout_audit"]["status"] == "FAILED" for row in real_cases.values())
            else "NOT_FAILED"
        ),
        "evidence_boundary": {
            "real_case_role": "factual replay and structural consistency only",
            "counterfactual_role": "not identified by these real cases",
            "clinical_validation": False,
            "probability_calibration": False,
        },
        "reproduce": [
            "python -m unittest -v",
            "python run_experiments.py --concept-map runtime_concept_map.json",
        ],
    }
    result["overall_status"] = (
        "STRUCTURALLY_CASE_CONSISTENT_BUT_CLINICAL_READOUT_FAILED"
        if result["structural_status"] == "CASE-CONSISTENT" and result["clinical_readout_status"] == "FAILED"
        else result["structural_status"]
    )
    write_json(output_path, result)
    _write_report(result, report_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concept-map", type=Path, default=ROOT / "runtime_concept_map.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "real_case_results.json")
    parser.add_argument("--report", type=Path, default=ROOT / "REAL_CASE_REPORT_CN.md")
    args = parser.parse_args()
    result = run(args.concept_map.resolve(), args.output.resolve(), args.report.resolve())
    print(json.dumps({
        "overall_status": result["overall_status"],
        "cases": {
            key: {
                "status": value["case_evidence_status"],
                "cuts": value["cut_count"],
                "mapped_ratio": value["mapping_coverage"]["mapped_ratio"],
            }
            for key, value in result["real_cases"].items()
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
