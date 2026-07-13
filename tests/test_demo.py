from __future__ import annotations

from prototype.demo import run_demo


def test_same_evidence_cut_yields_distinct_read_only_task_projections() -> None:
    output = run_demo()
    demo = output["demo_2_read_only_task_projections"]

    assert demo["shared_query_contract_except_task_and_query_id"] == {
        "kind": "project",
        "target": "*",
        "subject_id": "patient-demo",
        "as_known_at": "2026-01-01T09:00:00Z",
        "valid_at": "2026-01-01T08:30:00Z",
        "knowledge_version": "knowledge-v1",
    }
    assert demo["diagnosis"]["result"]["status"] == "ok"
    assert demo["medication_safety"]["result"]["status"] == "ok"
    assert demo["source_of_record_unchanged"] is True

    diagnosis = demo["diagnosis"]["claim_partition"]
    safety = demo["medication_safety"]["claim_partition"]
    assert "hypothesis" in diagnosis["semantic_roles"]
    assert "review_hypothesis" in diagnosis["concepts"]
    assert "hypothesis" not in safety["semantic_roles"]
    assert "review_hypothesis" not in safety["concepts"]
    assert {"temperature", "fever", "recorded_exposure"}.issubset(diagnosis["concepts"])
    assert {"temperature", "fever", "recorded_exposure"}.issubset(safety["concepts"])
    assert demo["diagnosis"]["result"]["origin"]["subkernel"] == "evidence"
    assert demo["medication_safety"]["result"]["origin"]["subkernel"] == "evidence"


def test_late_evidence_respects_knowledge_cut_without_changing_event_time() -> None:
    demo = run_demo()["demo_3_late_evidence_and_time_cut"]
    before = demo["as_known_at_09_00"]
    after = demo["as_known_at_11_00"]

    assert before["status"] == "insufficient"
    assert before["evidence_witness"]["root_sources"] == []
    assert before["time_cut"] == {
        "as_known_at": "2026-01-01T09:00:00Z",
        "valid_at": "2026-01-01T08:30:00Z",
        "mode": "project",
    }
    assert after["status"] == "ok"
    assert after["evidence_witness"]["root_sources"] == ["late-measurement-record"]
    assert after["time_cut"] == {
        "as_known_at": "2026-01-01T11:00:00Z",
        "valid_at": "2026-01-01T08:30:00Z",
        "mode": "project",
    }
    assert demo["event_time"] == "2026-01-01T08:15:00Z"
    assert demo["available_and_recorded_at"] == "2026-01-01T10:00:00Z"


def test_demo_refuses_unsupported_counterfactual_with_typed_boundary() -> None:
    result = run_demo()["demo_5_honest_refusal"]

    assert result["status"] == "unsupported"
    assert result["capability"] == "unsupported"
    assert result["origin"]["subkernel"] == "causal_state"
    assert result["diagnostics"]
    assert result["diagnostics"]["query_kind"] == "counterfactual"

