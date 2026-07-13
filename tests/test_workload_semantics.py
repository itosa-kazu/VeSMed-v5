"""Regression checks for the discriminating content of the frozen panel.

These tests intentionally inspect fixtures/oracles, not candidate outcomes.
They prevent a future refactor from turning a semantic stress test back into a
negative-only, query-echo, or self-equivalence smoke test.
"""

from __future__ import annotations

import json

from prototype.workloads import build_all_workloads, candidate_view


def _workload(test_id: str) -> dict:
    return build_all_workloads()[test_id]


def _queries(test_id: str) -> dict[str, dict]:
    rows = _workload(test_id)["candidate_view"]["fixtures"]["queries"]
    return {row["query_id"]: row for row in rows}


def _modules(test_id: str) -> dict[str, dict]:
    rows = _workload(test_id)["candidate_view"]["fixtures"]["modules"]
    return {row["module_id"]: row for row in rows}


def _assertions(test_id: str) -> list[dict]:
    return _workload(test_id)["oracle_view"]["assertions"]


def _oracle_ids(test_id: str) -> list[str]:
    return [row["oracle_id"] for row in _assertions(test_id)]


def test_t18_does_not_accept_identified_temporal_succession() -> None:
    workload = _workload("T18")
    assert {a["source_id"] for a in workload["candidate_view"]["fixtures"]["artifacts"]} == {
        "treatment-root",
        "outcome-root",
    }
    assert _queries("T18")["q-main"]["kind"] == "intervene"
    assert _oracle_ids("T18") == ["result.identification_boundary@1"]
    encoded = json.dumps(workload["oracle_view"], sort_keys=True)
    assert '"identified"' not in encoded
    assert '"partially_identified"' not in encoded


def test_t20_is_a_projection_coverage_test_not_invariant_api_test() -> None:
    workload = _workload("T20")
    assert _queries("T20")["q-main"]["kind"] == "project"
    registry = workload["candidate_view"]["public_model"]["coverage_registry"]
    assert registry["open_world"] is True
    assert registry["unknown_target"] not in registry["registered_hypotheses"]


def test_version_cut_workloads_ship_two_real_versioned_modules() -> None:
    for test_id in ("T23", "T36", "T47"):
        modules = list(_modules(test_id).values())
        assert len(modules) == 2
        assert len({module["knowledge_version"] for module in modules}) == 2
        assert len({module["model_version"] for module in modules}) == 2
        assert all(module.get("public_model", {}).get("closed_ir") for module in modules)
        steps = _workload(test_id)["candidate_view"]["branches"][0]["steps"]
        registered = [step["module_id"] for step in steps if step["op"] == "register_module"]
        assert set(registered) == {module["module_id"] for module in modules}
        queries = _queries(test_id)
        assert queries["q-old"]["model_version"] != queries["q-now"]["model_version"]
        # Besides merely asserting difference, every workload checks concrete
        # module semantics (high/low, rule retirement, or 0.5/0.4).
        assert any(a["oracle_id"] in {"result.contains_all@1", "result.not_contains@1"} for a in _assertions(test_id))


def test_t29_separates_raw_acceptance_from_canonical_refusal() -> None:
    workload = _workload("T29")
    steps = workload["candidate_view"]["branches"][0]["steps"]
    assert [step["op"] for step in steps] == ["ingest", "query", "query"]
    # Raw preservation is a guarantee on the normal projection algebra, not a
    # mandatory extra query-kind surface.
    assert _queries("T29")["q-raw"]["kind"] == "project"
    assert _queries("T29")["q-canonical"]["kind"] == "project"
    assert _oracle_ids("T29") == [
        "result.status@1",
        "evidence.raw_roundtrip@1",
        "result.typed_boundary@1",
    ]
    status_assertion = _assertions("T29")[0]
    assert status_assertion["args"]["expected"] == ["ok"]


def test_t33_preserves_both_raw_units_and_tests_only_canonical_adaptation() -> None:
    modules = _modules("T33")
    assert set(modules) == {"glucose-unit-adapter-v1"}
    assert modules["glucose-unit-adapter-v1"]["public_model"]["from_unit"] == "mg/dL"
    assert modules["glucose-unit-adapter-v1"]["public_model"]["to_unit"] == "mmol/L"
    branches = {b["branch_id"]: b for b in _workload("T33")["candidate_view"]["branches"]}
    assert set(branches) == {"legal", "illegal"}
    raw_assertions = [a for a in _assertions("T33") if a["oracle_id"] == "evidence.raw_roundtrip@1"]
    assert {(a["args"]["raw_value"], a["args"]["raw_unit"]) for a in raw_assertions} == {
        (100, "mg/dL"),
        (5, "meters"),
    }
    typed = [a for a in _assertions("T33") if a["oracle_id"] == "result.typed_boundary@1"]
    assert len(typed) == 1 and typed[0]["args"]["result"] == "illegal:canonical"


def test_t35_numeric_trace_is_a_hard_contract() -> None:
    assertions = _assertions("T35")
    assert len(assertions) == 2
    assertion = next(row for row in assertions if row["oracle_id"] == "result.numeric_contract@1")
    assert assertion["hard_gate"] is True
    allowed = set(assertion["args"]["allowed_computation"])
    assert {"exact", "approx", "nonconverged", "numerical_failure"} <= allowed
    required = assertion["args"]["required_diagnostics"]
    assert required["seed"] is True
    assert set(required["error_any_of"]) == {"error", "error_bound", "tolerance", "residual"}

    semantic = next(row for row in assertions if row["oracle_id"] == "reference.closed_recurrence@1")
    assert semantic["hard_gate"] is True
    assert semantic["args"]["target"] == "latent_state"
    assert semantic["args"]["horizon_hours"] == 24.0
    recurrence = semantic["args"]["closed_recurrence"]
    assert recurrence["state"] == semantic["args"]["target"]
    assert recurrence["horizon_hours"] == semantic["args"]["horizon_hours"]
    assert recurrence["step_hours"] == 1.0


def test_t39_registers_two_incompatible_probabilistic_modules() -> None:
    modules = _modules("T39")
    assert set(modules) == {"probabilistic-model-a", "probabilistic-model-b"}
    probabilities = {
        module_id: module["public_model"]["distribution"][0]["probability"]
        for module_id, module in modules.items()
    }
    assert probabilities == {"probabilistic-model-a": 0.9, "probabilistic-model-b": 0.1}
    assert all(module["public_model"]["arbitration_policy"] is None for module in modules.values())
    steps = _workload("T39")["candidate_view"]["branches"][0]["steps"]
    assert [step["op"] for step in steps[:2]] == ["register_module", "register_module"]
    assert any(a["oracle_id"] == "result.information_state@1" for a in _assertions("T39"))


def test_t45_checks_all_required_raw_roundtrip_fields() -> None:
    assertion = next(a for a in _assertions("T45") if a["oracle_id"] == "evidence.raw_roundtrip@1")
    assert assertion["args"] == {
        "result": "main:result",
        "root": "raw-root",
        "raw_value": 1.8,
        "raw_unit": "mg/dL",
        "span": [0, 13],
        "mapping_version": "fixture-map-v1",
    }


def test_t48_has_duplicate_delivery_and_later_effective_cancellation() -> None:
    workload = _workload("T48")
    artifacts = {a["artifact_id"]: a for a in workload["candidate_view"]["fixtures"]["artifacts"]}
    assert artifacts["action-performed"]["context"]["idempotency_key"] == "A1/dose/1"
    assert artifacts["action-stopped"]["semantic_role"] == "stopped_intervention"
    assert artifacts["action-stopped"]["clocks"]["effective_start"] > artifacts["action-performed"]["clocks"]["effective_start"]
    steps = workload["candidate_view"]["branches"][0]["steps"]
    assert steps[0]["artifact_ids"] == ["action-performed", "action-performed"]
    assertions = {a["assertion_id"]: a for a in _assertions("T48")}
    assert assertions["delivery-idempotent-one-root"]["args"]["expected"] == 1
    assert assertions["performed-live-during"]["args"]["visible"] is True
    assert assertions["performed-stopped-after-cancel"]["args"]["visible"] is False
    assert assertions["no-effect-roots-after-cancel"]["args"]["expected"] == 0


def test_negative_and_equivalence_cases_have_positive_liveness_controls() -> None:
    required_oracles = {
        "T03": "evidence.root_present@1",
        "T05": "evidence.root_present@1",
        "T24": "evidence.root_present@1",
        "T26": "evidence.root_present@1",
        "T30": "evidence.root_present@1",
        "T31": "evidence.root_present@1",
        "T32": "evidence.root_present@1",
        "T40": "temporal.root_visibility@1",
        "T42": "evidence.root_present@1",
        "T43": "evidence.root_present@1",
        "T49": "result.contains_all@1",
    }
    for test_id, required in required_oracles.items():
        assert required in _oracle_ids(test_id), (test_id, _oracle_ids(test_id))

    assert _queries("T03")["q-observed"]["kind"] == "project"


def test_all_candidate_fixtures_remain_plain_json_data() -> None:
    for workload in build_all_workloads().values():
        # This is also the transport boundary: no callback/object can hide in a
        # public model or module fixture.
        json.loads(json.dumps(candidate_view(workload), sort_keys=True, allow_nan=False))
