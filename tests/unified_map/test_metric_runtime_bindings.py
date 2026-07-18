from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

import pytest

import prototype.unified_map.metric_runtime_bindings as metric_runtime_bindings_module
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
)
from prototype.unified_map.metric_configuration import (
    benchmark_v1_metric_target_registry,
)
from prototype.unified_map.metric_runtime_bindings import (
    ARTIFACT_DOMAIN,
    BINDING_SET_DOMAIN,
    SOURCE_CLOSURE_DOMAIN,
    TARGET_OBJECT_DOMAIN,
    FormulaImplementationKey,
    RuntimeBindingStatus,
    benchmark_v1_metric_runtime_bindings,
    parse_metric_runtime_bindings_bytes,
)


def _resign(wire: dict) -> bytes:
    preimage = {
        key: value for key, value in wire.items() if key != "binding_set_digest"
    }
    wire["binding_set_digest"] = (
        "sha256:"
        + hashlib.sha256(
            BINDING_SET_DOMAIN + canonical_json_bytes(preimage)
        ).hexdigest()
    )
    return canonical_json_bytes(wire)


def _assert_live_object_tamper_rejected(
    target: object, attribute: str, replacement: object
) -> None:
    artifact = benchmark_v1_metric_runtime_bindings()
    original = getattr(target, attribute)
    object.__setattr__(target, attribute, replacement)
    try:
        with pytest.raises(
            ProtocolViolation, match="code-owned control plane changed after import"
        ):
            benchmark_v1_metric_runtime_bindings()
        with pytest.raises(
            ProtocolViolation, match="code-owned control plane changed after import"
        ):
            parse_metric_runtime_bindings_bytes(artifact.canonical_bytes)
    finally:
        object.__setattr__(target, attribute, original)


def test_inventory_is_exactly_111_targets_and_closes_none() -> None:
    artifact = benchmark_v1_metric_runtime_bindings()
    wire = artifact.to_wire()

    assert wire["benchmark_status"] == "PRE-FREEZE"
    assert wire["authority_claim"] == "formula_runtime_coverage_inventory_only"
    assert wire["evaluator_binding"] == "not_bound"
    assert wire["freeze_authority"] == "not_claimed"
    assert wire["single_aggregate_score"] == "forbidden"
    assert wire["semantic_metric_config_ready"] is False
    assert wire["closed_target_count"] == 0
    assert wire["target_count"] == 111
    records = wire["target_records"]
    observed_coverage = Counter(row["runtime_binding_status"] for row in records)
    assert wire["coverage"] == {
        status.value: observed_coverage[status.value] for status in RuntimeBindingStatus
    }
    assert sum(wire["coverage"].values()) == wire["target_count"]
    joins = [(row["measurement_id"], row["ordinal"]) for row in records]
    assert len(joins) == len(set(joins)) == 111
    assert all(row["closed_definition_claimed"] is False for row in records)
    assert all(
        {"UCM-METRIC-B002", "UCM-METRIC-B003", "UCM-METRIC-B004", "UCM-METRIC-B007"}
        <= set(row["remaining_blocker_codes"])
        for row in records
    )


def test_executable_partial_and_unimplemented_statuses_are_fail_closed() -> None:
    records = benchmark_v1_metric_runtime_bindings().to_wire()["target_records"]
    executable = [
        row
        for row in records
        if row["runtime_binding_status"] == "formula_executable_unbound"
    ]
    partial = [
        row
        for row in records
        if row["runtime_binding_status"] == "partial_untrusted_collector"
    ]
    partial_formula = [
        row
        for row in records
        if row["runtime_binding_status"] == "partial_formula_coverage_unbound"
    ]
    unimplemented = [
        row for row in records if row["runtime_binding_status"] == "unimplemented"
    ]
    enum_values = {item.value for item in FormulaImplementationKey}

    assert all(
        implementation["implementation_key"] in enum_values
        for row in executable
        for implementation in row["implementations"]
    )
    assert all(row["implementations"] for row in executable)
    assert all(
        row["implemented_branches"] == row["required_branches"] for row in executable
    )
    assert all(not row["missing_branches"] for row in executable)
    assert all(row["denominator_contract"] is not None for row in executable)
    assert all(row["tie_policy"] is not None for row in executable)
    assert all(row["undefined_disposition"] is not None for row in executable)
    assert all(row["task_applicability"] is None for row in executable)
    assert all(row["world_panel_applicability"] is None for row in executable)
    assert all(row["aggregation_hierarchy"] is None for row in executable)
    assert all(row["evaluator_runtime_environment"] is None for row in executable)

    assert {(row["measurement_id"], row["ordinal"]) for row in partial_formula} == {
        ("M02", 11),
        ("M03", 1),
        ("M03", 4),
        ("M05", 6),
        ("M06", 5),
        ("M07", 8),
        ("M12", 1),
        ("M12", 2),
        ("M12", 4),
        ("M12", 5),
        ("M16", 1),
        ("M16", 2),
        ("M16", 3),
        ("M16", 4),
    }
    assert all(row["implementations"] for row in partial_formula)
    assert all(row["implemented_branches"] for row in partial_formula)
    assert all(row["missing_branches"] for row in partial_formula)
    assert all(
        "complete_formula_branch_coverage" in row["remaining_semantic_gaps"]
        for row in partial_formula
    )

    assert {row["measurement_id"] for row in partial} == {"M11", "M12", "M13", "M15"}
    expected_untrusted_implementations = {
        "M11": "m11_extension_cost",
        "M12": "m12_state_size",
        "M13": "m13_resource",
        "M15": "m15_update_consistency",
    }
    assert all(
        len(row["implementations"]) == 1
        and row["implementations"][0]["implementation_key"]
        == expected_untrusted_implementations[row["measurement_id"]]
        for row in partial
    )
    assert all(
        row["implemented_branches"] == row["required_branches"] for row in partial
    )
    assert all(not row["missing_branches"] for row in partial)
    assert all(
        "independent_trusted_input_collector" in row["remaining_semantic_gaps"]
        and "closed_expected_exposure_registry" in row["remaining_semantic_gaps"]
        for row in partial
    )
    assert all(
        "independent_extension_collector" in row["remaining_semantic_gaps"]
        for row in partial
        if row["measurement_id"] == "M11"
    )
    assert all("UCM-METRIC-B005" in row["remaining_blocker_codes"] for row in partial)

    assert all(not row["implementations"] for row in unimplemented)
    assert all(not row["implemented_branches"] for row in unimplemented)
    assert all(
        row["missing_branches"] == row["required_branches"] for row in unimplemented
    )
    assert all(row["denominator_contract"] is None for row in unimplemented)
    assert all(row["tie_policy"] is None for row in unimplemented)
    assert all(row["undefined_disposition"] is None for row in unimplemented)
    assert all(
        "code_owned_callable_and_typed_selector" in row["remaining_semantic_gaps"]
        for row in unimplemented
    )
    assert {
        (row["measurement_id"], row["ordinal"])
        for row in unimplemented
        if row["measurement_id"] in {"M12", "M13", "M14", "M15", "M16"}
    } == {("M14", 6), ("M16", 5)}
    for row in records:
        assert row["required_branches"]
        assert len(row["required_branches"]) == len(set(row["required_branches"]))
        assert not set(row["implemented_branches"]) & set(row["missing_branches"])
        assert set(row["implemented_branches"]) | set(row["missing_branches"]) == set(
            row["required_branches"]
        )
        assert {
            branch
            for implementation in row["implementations"]
            for branch in implementation["satisfies_target_branches"]
        } == set(row["implemented_branches"])
    assert (
        next(
            row
            for row in records
            if (row["measurement_id"], row["ordinal"]) == ("M02", 12)
        )["runtime_binding_status"]
        == "unimplemented"
    )
    m07_unknown = next(
        row for row in records if (row["measurement_id"], row["ordinal"]) == ("M07", 8)
    )
    assert m07_unknown["runtime_binding_status"] == "partial_formula_coverage_unbound"
    assert m07_unknown["implemented_branches"] == [
        "unknown_probability_brier",
        "unknown_probability_nll",
    ]
    assert m07_unknown["missing_branches"] == ["unknown_probability_calibration"]


def test_m01_primary_proper_scores_bind_both_truth_branches() -> None:
    records = {
        (row["measurement_id"], row["ordinal"]): row
        for row in benchmark_v1_metric_runtime_bindings().to_wire()["target_records"]
    }
    expected_selectors = {
        1: {
            "realized_label": "multiclass_nll",
            "oracle_posterior": "oracle_posterior_cross_entropy_nll",
        },
        2: {
            "realized_label": "multiclass_brier",
            "oracle_posterior": "oracle_posterior_multiclass_brier",
        },
    }
    for ordinal, selectors in expected_selectors.items():
        row = records[("M01", ordinal)]
        assert row["runtime_binding_status"] == "formula_executable_unbound"
        assert row["required_branches"] == ["realized_label", "oracle_posterior"]
        assert row["implemented_branches"] == row["required_branches"]
        assert row["missing_branches"] == []
        implementations = {item["branch_id"]: item for item in row["implementations"]}
        assert set(implementations) == set(selectors)
        assert {
            branch: implementation["selector_key"]
            for branch, implementation in implementations.items()
        } == selectors
        assert (
            implementations["realized_label"]["implementation_key"] == "m01_diagnosis"
        )
        assert (
            implementations["oracle_posterior"]["implementation_key"]
            == "m01_oracle_posterior"
        )
        assert implementations["realized_label"]["callable_output_type"].endswith(
            ".DiagnosisMetricReport"
        )
        assert implementations["oracle_posterior"]["callable_output_type"].endswith(
            ".OraclePosteriorDiagnosisMetricReport"
        )


def test_conditional_and_compound_targets_disclose_branch_coverage() -> None:
    records = {
        (row["measurement_id"], row["ordinal"]): row
        for row in benchmark_v1_metric_runtime_bindings().to_wire()["target_records"]
    }

    m02_joint = records[("M02", 11)]
    assert m02_joint["implemented_branches"] == ["normalized_joint_energy_score"]
    assert m02_joint["missing_branches"] == ["world_declared_joint_proper_score"]
    assert m02_joint["runtime_binding_status"] == "partial_formula_coverage_unbound"

    m03_trajectory = records[("M03", 1)]
    assert m03_trajectory["implemented_branches"] == ["continuous_gaussian_nll_slice"]
    assert {
        "continuous_crps",
        "discrete_event_nll",
        "discrete_event_brier",
        "normalized_joint_energy_score",
        "world_declared_joint_proper_score",
    } == set(m03_trajectory["missing_branches"])
    assert (
        m03_trajectory["runtime_binding_status"] == "partial_formula_coverage_unbound"
    )

    m03_calibration = records[("M03", 4)]
    assert m03_calibration["implemented_branches"] == ["policy_horizon_coverage"]
    assert m03_calibration["missing_branches"] == ["policy_horizon_calibration"]

    for key in (("M05", 6), ("M06", 5)):
        row = records[key]
        assert row["implemented_branches"] == ["pair_level_decisions"]
        assert row["missing_branches"] == ["pair_level_trajectory_evidence"]
        assert row["runtime_binding_status"] == "partial_formula_coverage_unbound"

    m04_tail = records[("M04", 11)]
    assert m04_tail["implemented_branches"] == [
        "point_identified_w19_tail",
        "partial_identified_w19_tail",
    ]
    assert m04_tail["missing_branches"] == []
    assert {item["branch_id"] for item in m04_tail["implementations"]} == set(
        m04_tail["required_branches"]
    )

    m02_survival = records[("M02", 12)]
    assert m02_survival["implemented_branches"] == []
    assert m02_survival["missing_branches"] == [
        "integrated_survival_brier",
        "integrated_survival_nll",
    ]
    assert m02_survival["runtime_binding_status"] == "unimplemented"


def test_m11_known_answer_projects_every_extension_in_explicit_order() -> None:
    result = metric_runtime_bindings_module._ADAPTERS[
        FormulaImplementationKey.M11_EXTENSION_COST
    ].invoke_known_answer()
    assert [row["extension_id"] for row in result.extensions] == [
        "known-extension-a",
        "known-extension-z",
    ]
    assert [row["retrain_examples"] for row in result.extensions] == [20, 35]

    records = {
        (row["measurement_id"], row["ordinal"]): row
        for row in benchmark_v1_metric_runtime_bindings().to_wire()["target_records"]
    }
    for ordinal in range(1, 7):
        spec = metric_runtime_bindings_module._TARGET_BINDINGS[("M11", ordinal)]
        assert len(spec.branches) == 1
        selected = spec.branches[0].selector(result)
        assert type(selected) is tuple
        assert [row["extension_id"] for row in selected] == [
            "known-extension-a",
            "known-extension-z",
        ]
        assert len(selected) == 2
        implementation = records[("M11", ordinal)]["implementations"][0]
        assert implementation["known_answer_selected_output_cardinality"] == 2
        assert implementation["formula_parameter_preimage"]["projection_order"] == (
            "extension_id_ascending"
        )


def test_m12_through_m16_bind_only_implemented_branches_and_trust_levels() -> None:
    records = {
        (row["measurement_id"], row["ordinal"]): row
        for row in benchmark_v1_metric_runtime_bindings().to_wire()["target_records"]
    }

    expected_m12 = {
        1: (
            "partial_formula_coverage_unbound",
            ["canonical_json_raw_bytes"],
            ["raw_f64le_raw_bytes", "bound_harness_state_custody"],
        ),
        2: (
            "partial_formula_coverage_unbound",
            ["canonical_json_compressed_bytes"],
            ["raw_f64le_compressed_bytes", "bound_harness_state_custody"],
        ),
        3: (
            "partial_untrusted_collector",
            ["scalar_count", "node_count", "edge_count", "particle_count"],
            [],
        ),
        4: (
            "partial_formula_coverage_unbound",
            ["canonical_json_history_length_ols"],
            ["raw_f64le_history_length_ols", "bound_harness_state_custody"],
        ),
        5: (
            "partial_formula_coverage_unbound",
            ["canonical_json_task_horizon_slices"],
            ["raw_f64le_task_horizon_slices", "bound_harness_state_custody"],
        ),
    }
    for ordinal, (status, implemented, missing) in expected_m12.items():
        row = records[("M12", ordinal)]
        assert row["runtime_binding_status"] == status
        assert row["implemented_branches"] == implemented
        assert row["missing_branches"] == missing
        assert "independent_trusted_input_collector" in row["remaining_semantic_gaps"]
        assert "UCM-METRIC-B005" in row["remaining_blocker_codes"]

    for ordinal in range(1, 7):
        row = records[("M13", ordinal)]
        assert row["runtime_binding_status"] == "partial_untrusted_collector"
        assert row["implemented_branches"] == row["required_branches"]
        assert row["missing_branches"] == []
        assert "trusted_runtime_resource_measurement" in row["remaining_semantic_gaps"]
        assert "UCM-METRIC-B005" in row["remaining_blocker_codes"]

    for ordinal in range(1, 6):
        row = records[("M14", ordinal)]
        assert row["runtime_binding_status"] == "formula_executable_unbound"
        assert row["implemented_branches"] == row["required_branches"]
        assert row["missing_branches"] == []
    hierarchical = records[("M14", 6)]
    assert hierarchical["runtime_binding_status"] == "unimplemented"
    assert hierarchical["missing_branches"] == ["hierarchical_bootstrap_ci95"]

    for ordinal in range(1, 5):
        row = records[("M15", ordinal)]
        assert row["runtime_binding_status"] == "partial_untrusted_collector"
        assert row["implemented_branches"] == row["required_branches"]
        assert row["missing_branches"] == []
        assert (
            "bound_update_query_score_evidence_roots" in row["remaining_semantic_gaps"]
        )

    expected_m16_missing = {
        1: ["formal_novel_readout_eligibility"],
        2: ["frozen_target_authority", "formal_novel_readout_eligibility"],
        3: ["same_basis_score_authority", "formal_novel_readout_eligibility"],
        4: ["independent_history_reread_proof"],
    }
    for ordinal, missing in expected_m16_missing.items():
        row = records[("M16", ordinal)]
        assert row["runtime_binding_status"] == "partial_formula_coverage_unbound"
        assert row["missing_branches"] == missing
        assert (
            "formal_novel_readout_eligibility_and_independent_trace_custody"
            in row["remaining_semantic_gaps"]
        )
        assert "UCM-METRIC-B005" in row["remaining_blocker_codes"]
    scope_disposition = records[("M16", 5)]
    assert scope_disposition["runtime_binding_status"] == "unimplemented"
    assert scope_disposition["missing_branches"] == [
        "formal_original_scope_sufficiency_disposition"
    ]


def test_m12_through_m16_known_answers_are_typed_and_branch_exercising() -> None:
    adapters = metric_runtime_bindings_module._ADAPTERS

    state_size = adapters[FormulaImplementationKey.M12_STATE_SIZE].invoke_known_answer()
    assert (
        type(state_size)
        is adapters[FormulaImplementationKey.M12_STATE_SIZE].expected_result_type
    )
    assert len(state_size.rows) == 3
    assert len(state_size.history_length_slopes) == 1
    assert state_size.history_length_slopes[0]["status"] == "defined"

    resources = adapters[FormulaImplementationKey.M13_RESOURCE].invoke_known_answer()
    assert (
        type(resources)
        is adapters[FormulaImplementationKey.M13_RESOURCE].expected_result_type
    )
    assert [row["operation"] for row in resources.cold_latency] == [
        "initialize",
        "update",
        "diagnose",
        "rollout",
    ]
    assert len(resources.resources) == 8
    assert all(row["status"] == "defined" for row in resources.resources)

    stability = adapters[FormulaImplementationKey.M14_STABILITY].invoke_known_answer()
    assert (
        type(stability)
        is adapters[FormulaImplementationKey.M14_STABILITY].expected_result_type
    )
    assert stability.candidate_summary["mean"] == 3.0
    assert stability.paired_summary is not None
    assert stability.paired_summary["mean"] == 0.5

    update = adapters[
        FormulaImplementationKey.M15_UPDATE_CONSISTENCY
    ].invoke_known_answer()
    assert (
        type(update)
        is adapters[
            FormulaImplementationKey.M15_UPDATE_CONSISTENCY
        ].expected_result_type
    )
    assert {
        (row["information_kind"], row["readout_kind"])
        for row in update.oracle_directional_changes
    } == {
        ("informative_observation", "diagnosis"),
        ("informative_observation", "rollout"),
        ("informative_treatment_response", "diagnosis"),
        ("informative_treatment_response", "rollout"),
        ("no_information_control", "diagnosis"),
    }

    readout = adapters[FormulaImplementationKey.M16_NOVEL_READOUT].invoke_known_answer()
    assert (
        type(readout)
        is adapters[FormulaImplementationKey.M16_NOVEL_READOUT].expected_result_type
    )
    assert [row["readout_id"] for row in readout.readouts] == [
        "known-readout-a",
        "known-readout-z",
    ]
    for ordinal in range(1, 5):
        spec = metric_runtime_bindings_module._TARGET_BINDINGS[("M16", ordinal)]
        selected = spec.branches[0].selector(readout)
        assert type(selected) is tuple
        assert [row["readout_id"] for row in selected] == [
            "known-readout-a",
            "known-readout-z",
        ]


def test_import_manifest_rejects_live_fake_branch_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = benchmark_v1_metric_runtime_bindings()
    fake_survival_binding = metric_runtime_bindings_module._TARGET_BINDINGS[("M02", 11)]

    with pytest.raises(TypeError):
        metric_runtime_bindings_module._TARGET_BINDINGS[("M02", 12)] = (
            fake_survival_binding
        )

    injected = dict(metric_runtime_bindings_module._TARGET_BINDINGS)
    injected[("M02", 12)] = fake_survival_binding
    monkeypatch.setattr(metric_runtime_bindings_module, "_TARGET_BINDINGS", injected)
    with pytest.raises(
        ProtocolViolation, match="manifest aliases changed after import"
    ):
        benchmark_v1_metric_runtime_bindings()
    with pytest.raises(
        ProtocolViolation, match="manifest aliases changed after import"
    ):
        parse_metric_runtime_bindings_bytes(artifact.canonical_bytes)


def test_import_attestation_rejects_frozen_dataclass_object_setattr_tamper() -> None:
    trajectory_branch = metric_runtime_bindings_module._TARGET_BINDINGS[
        ("M03", 1)
    ].branches[0]
    _assert_live_object_tamper_rejected(
        trajectory_branch,
        "satisfies_target_branches",
        metric_runtime_bindings_module._TARGET_REQUIRED_BRANCHES[("M03", 1)],
    )

    _assert_live_object_tamper_rejected(
        trajectory_branch,
        "selector",
        metric_runtime_bindings_module._TARGET_BINDINGS[("M03", 2)]
        .branches[0]
        .selector,
    )

    trajectory_adapter = metric_runtime_bindings_module._ADAPTERS[
        FormulaImplementationKey.M03_TRAJECTORY
    ]
    effect_adapter = metric_runtime_bindings_module._ADAPTERS[
        FormulaImplementationKey.M03_EFFECT
    ]
    _assert_live_object_tamper_rejected(
        trajectory_adapter, "function", effect_adapter.function
    )
    _assert_live_object_tamper_rejected(
        trajectory_adapter,
        "invoke_known_answer",
        effect_adapter.invoke_known_answer,
    )
    _assert_live_object_tamper_rejected(
        trajectory_adapter,
        "known_answer_parameter_preimage_bytes",
        canonical_json_bytes({"fixture": "forged-known-answer"}),
    )
    _assert_live_object_tamper_rejected(
        trajectory_adapter,
        "formula_family",
        "forged formula family",
    )


def test_import_attestation_rejects_all_live_control_plane_global_tamper() -> None:
    artifact = benchmark_v1_metric_runtime_bindings()
    imported_snapshot = metric_runtime_bindings_module._IMPORTED_SOURCE_DIGESTS
    first_path = next(iter(imported_snapshot))
    forged_snapshot = dict(imported_snapshot)
    forged_snapshot[first_path] = "sha256:" + "0" * 64

    with pytest.raises(TypeError):
        imported_snapshot[first_path] = forged_snapshot[first_path]

    mutations = (
        ("_SOURCE_PATHS", ()),
        ("_ALWAYS_REMAINING_BLOCKERS", ()),
        ("_REMAINING_GLOBAL_GAPS", ()),
        ("_IMPORTED_SOURCE_DIGESTS", forged_snapshot),
    )
    for global_name, replacement in mutations:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                metric_runtime_bindings_module, global_name, replacement
            )
            with pytest.raises(
                ProtocolViolation,
                match="code-owned control plane changed after import",
            ):
                benchmark_v1_metric_runtime_bindings()
            with pytest.raises(
                ProtocolViolation,
                match="code-owned control plane changed after import",
            ):
                parse_metric_runtime_bindings_bytes(artifact.canonical_bytes)


def test_every_join_binds_the_exact_target_object_digest() -> None:
    registry = benchmark_v1_metric_target_registry()
    records = benchmark_v1_metric_runtime_bindings(registry.canonical_bytes).to_wire()[
        "target_records"
    ]
    expected: dict[tuple[str, int], tuple[str, str]] = {}
    for contract in registry.measurement_contracts:
        for ordinal, output in enumerate(contract.outputs, 1):
            raw = canonical_json_bytes(output.to_wire())
            expected[(contract.measurement_id, ordinal)] = (
                output.metric_id,
                "sha256:" + hashlib.sha256(TARGET_OBJECT_DOMAIN + raw).hexdigest(),
            )

    assert len(expected) == 111
    assert {
        (row["measurement_id"], row["ordinal"]): (
            row["metric_id"],
            row["target_object_digest"],
        )
        for row in records
    } == expected


def test_target_bytes_and_fresh_exact_source_closure_are_bound() -> None:
    target = benchmark_v1_metric_target_registry()
    artifact = benchmark_v1_metric_runtime_bindings(target.canonical_bytes)
    wire = artifact.to_wire()
    binding = wire["target_registry_binding"]

    assert binding["artifact_digest"] == target.artifact_digest
    assert binding["metric_target_digest"] == target.metric_target_digest
    assert binding["byte_count"] == len(target.canonical_bytes)
    root = Path(__file__).resolve().parents[2]
    for entry in wire["source_closure"]:
        raw = (root / entry["path"]).read_bytes()
        assert entry["byte_count"] == len(raw)
        assert entry["artifact_digest"] == digest_bytes(raw)
    assert (
        wire["source_closure_digest"]
        == "sha256:"
        + hashlib.sha256(
            SOURCE_CLOSURE_DOMAIN + canonical_json_bytes(wire["source_closure"])
        ).hexdigest()
    )


def test_parser_is_exact_canonical_domain_separated_and_deterministic() -> None:
    first = benchmark_v1_metric_runtime_bindings()
    second = benchmark_v1_metric_runtime_bindings()
    assert first.canonical_bytes == second.canonical_bytes
    parsed = parse_metric_runtime_bindings_bytes(first.canonical_bytes)
    assert parsed.canonical_bytes == first.canonical_bytes
    assert parsed.artifact_digest == digest_bytes(first.canonical_bytes)
    assert (
        parsed.binding_artifact_digest
        == "sha256:"
        + hashlib.sha256(ARTIFACT_DOMAIN + first.canonical_bytes).hexdigest()
    )
    with pytest.raises(ProtocolViolation):
        parse_metric_runtime_bindings_bytes(first.canonical_bytes + b" ")
    with pytest.raises(ProtocolViolation):
        parse_metric_runtime_bindings_bytes("not-bytes")  # type: ignore[arg-type]
    duplicate = first.canonical_bytes.replace(
        b'{"authority_claim":', b'{"authority_claim":"duplicate","authority_claim":', 1
    )
    with pytest.raises(ProtocolViolation, match="duplicate key"):
        parse_metric_runtime_bindings_bytes(duplicate)


def test_resigned_semantic_target_ordinal_and_source_splices_are_rejected() -> None:
    artifact = benchmark_v1_metric_runtime_bindings()

    semantic = artifact.to_wire()
    semantic["target_records"][0]["runtime_binding_status"] = "unimplemented"
    semantic["target_records"][0]["implementations"] = []
    with pytest.raises(ProtocolViolation, match="fresh code-owned truth"):
        parse_metric_runtime_bindings_bytes(_resign(semantic))

    dropped_branch = artifact.to_wire()
    dropped_branch["target_records"][0]["implementations"].pop()
    with pytest.raises(ProtocolViolation, match="fresh code-owned truth"):
        parse_metric_runtime_bindings_bytes(_resign(dropped_branch))

    false_branch_completion = artifact.to_wire()
    m02_joint = next(
        row
        for row in false_branch_completion["target_records"]
        if (row["measurement_id"], row["ordinal"]) == ("M02", 11)
    )
    m02_joint["implemented_branches"].append(m02_joint["missing_branches"].pop())
    m02_joint["runtime_binding_status"] = "formula_executable_unbound"
    with pytest.raises(ProtocolViolation, match="fresh code-owned truth"):
        parse_metric_runtime_bindings_bytes(_resign(false_branch_completion))

    ordinal_splice = artifact.to_wire()
    first = ordinal_splice["target_records"][0]
    second = ordinal_splice["target_records"][1]
    first["target_object_digest"], second["target_object_digest"] = (
        second["target_object_digest"],
        first["target_object_digest"],
    )
    with pytest.raises(ProtocolViolation, match="fresh code-owned truth"):
        parse_metric_runtime_bindings_bytes(_resign(ordinal_splice))

    source_splice = artifact.to_wire()
    source_splice["source_closure"][0]["artifact_digest"] = "sha256:" + "0" * 64
    source_splice["source_closure_digest"] = (
        "sha256:"
        + hashlib.sha256(
            SOURCE_CLOSURE_DOMAIN
            + canonical_json_bytes(source_splice["source_closure"])
        ).hexdigest()
    )
    with pytest.raises(ProtocolViolation, match="fresh code-owned truth"):
        parse_metric_runtime_bindings_bytes(_resign(source_splice))

    bool_number = artifact.to_wire()
    bool_number["target_count"] = True
    with pytest.raises(ProtocolViolation, match="fresh code-owned truth"):
        parse_metric_runtime_bindings_bytes(_resign(bool_number))


def test_target_cross_splice_and_tamper_fail_before_binding() -> None:
    artifact = benchmark_v1_metric_runtime_bindings()
    target = benchmark_v1_metric_target_registry().to_wire()
    (
        target["measurement_contracts"][0]["outputs"][0],
        target["measurement_contracts"][0]["outputs"][1],
    ) = (
        target["measurement_contracts"][0]["outputs"][1],
        target["measurement_contracts"][0]["outputs"][0],
    )
    with pytest.raises(ProtocolViolation, match="code-owned v1 truth"):
        parse_metric_runtime_bindings_bytes(
            artifact.canonical_bytes, canonical_json_bytes(target)
        )

    tampered = bytearray(benchmark_v1_metric_target_registry().canonical_bytes)
    tampered[-2] ^= 1
    with pytest.raises(ProtocolViolation):
        parse_metric_runtime_bindings_bytes(artifact.canonical_bytes, bytes(tampered))


def test_parser_freshly_rehashes_source_and_rejects_long_lived_stale_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = benchmark_v1_metric_runtime_bindings()
    original = Path.read_bytes

    def changed_source(path: Path) -> bytes:
        raw = original(path)
        if path.as_posix().endswith(
            "prototype/unified_map/metrics_intervention_regret.py"
        ):
            return raw + b"# changed after import\n"
        return raw

    monkeypatch.setattr(Path, "read_bytes", changed_source)
    with pytest.raises(ProtocolViolation, match="loaded metric binding source differs"):
        parse_metric_runtime_bindings_bytes(artifact.canonical_bytes)


def test_callable_identity_and_known_answer_digest_are_runtime_derived() -> None:
    records = benchmark_v1_metric_runtime_bindings().to_wire()["target_records"]
    implementations = [
        implementation for row in records for implementation in row["implementations"]
    ]
    assert implementations
    for implementation in implementations:
        identity = implementation["callable_identity"]
        assert identity["module"].startswith("prototype.unified_map.")
        assert identity["qualname"]
        assert identity["signature"].startswith("(")
        assert identity["source_path"].startswith("prototype/unified_map/")
        assert implementation["selector_key"]
        assert implementation["input_type_contract"]
        assert implementation["callable_output_type"].startswith(
            "prototype.unified_map."
        )
        assert implementation["selector_output_type"]
        assert implementation["branch_id"]
        assert implementation["satisfies_target_branches"]
        assert implementation["denominator_contract"]
        assert implementation["tie_policy"]
        assert implementation["undefined_disposition"]
        assert implementation["known_answer_selected_output_digest"].startswith(
            "sha256:"
        )
