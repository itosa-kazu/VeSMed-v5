from __future__ import annotations

import hashlib
import json
from collections import Counter

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.evaluator import EvaluationTask
from prototype.unified_map.metric_configuration import (
    METRIC_TARGET_DOMAIN,
    benchmark_v1_metric_target_registry,
)
from prototype.unified_map.scope_manifest import SCOPE_AXES
from prototype.unified_map.task_protocol import TASK_EXECUTION_TRUTH
from prototype.unified_map.world_scope_fragments import (
    CODE_OWNED_WORLD_SCOPE_FRAGMENT_ARTIFACT_DIGEST,
    CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES,
    CODE_OWNED_WORLD_SCOPE_FRAGMENT_SEMANTIC_DIGEST,
    CODE_OWNED_WORLD_SCOPE_FRAGMENTS,
    EXPECTED_PANEL_IDENTITIES,
    ActionDeclaration,
    ExtensionSemantic,
    GapScope,
    PlannedActionDeclaration,
    ScopeGapCode,
    TaskApplicability,
    WORLD_SCOPE_FRAGMENT_DOMAIN,
    WorldScopeBuildReport,
    build_code_owned_world_scope_fragments,
    inspect_world_scope_fragments,
    parse_world_scope_fragment_set_bytes,
    world_scope_fragment_artifact_digest_from_bytes,
    world_scope_fragment_semantic_digest_from_bytes,
)


def _mutate(fn) -> bytes:
    body = json.loads(CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES)
    fn(body)
    return canonical_json_bytes(body)


def _keys(value: object) -> set[str]:
    if type(value) is dict:
        return set(value).union(*(_keys(x) for x in value.values()))
    if type(value) is list:
        return set().union(*(_keys(x) for x in value)) if value else set()
    return set()


def test_exact_21_panels_11_axes_and_105_rows() -> None:
    artifact = build_code_owned_world_scope_fragments()
    assert tuple(x.identity for x in artifact.panels) == EXPECTED_PANEL_IDENTITIES
    assert len(artifact.panels) == 21
    assert all(tuple(x.axes.to_wire()) == SCOPE_AXES for x in artifact.panels)
    assert sum(len(x.task_applicability) for x in artifact.panels) == 105


def test_task_rows_bind_task_execution_truth_not_free_text() -> None:
    truth = {
        task: (kind, operations) for task, kind, operations in TASK_EXECUTION_TRUTH
    }
    for panel in CODE_OWNED_WORLD_SCOPE_FRAGMENTS.panels:
        rows = {row.task: row for row in panel.task_applicability}
        assert tuple(rows) == tuple(EvaluationTask)
        for task, row in rows.items():
            assert (row.execution_kind, row.operations) == truth[task]
        assert (
            rows[EvaluationTask.DIAGNOSIS].applicability is TaskApplicability.REQUIRED
        )
        assert (
            rows[EvaluationTask.NATURAL_FORECAST].applicability
            is TaskApplicability.REQUIRED
        )
        assert (
            rows[EvaluationTask.INTERVENTION].applicability
            is TaskApplicability.REQUIRED
        )
        assert rows[EvaluationTask.OOD].applicability is (
            TaskApplicability.REQUIRED
            if panel.world_slot == "W18"
            else TaskApplicability.CONTROL
        )
        assert (
            rows[EvaluationTask.NEW_READOUT].applicability
            is TaskApplicability.POST_SEAL_EXTENSION
        )


def test_catalog_actions_checks_policies_horizons_and_labels_are_live_bound() -> None:
    w20 = next(
        x for x in CODE_OWNED_WORLD_SCOPE_FRAGMENTS.panels if x.world_slot == "W20"
    )
    axes = w20.axes
    assert tuple(x.action_id for x in axes.A.actions) == ("A1", "A2")
    assert all(type(x.parameter_schema) is dict for x in axes.A.actions)
    assert tuple(x.check_id for x in axes.Q.checks) == ("Q0", "Q1")
    assert tuple(x.horizon for x in axes.Pi.by_horizon) == (1, 4, 8)
    assert any(
        plan.adaptive_rule_ids for row in axes.Pi.by_horizon for plan in row.policies
    )
    assert axes.Tau.horizons == (1, 4, 8)
    assert axes.Gamma.labels == ("C0", "C1")
    assert axes.O.time_fields == ("occurred_at", "collected_at", "available_at")


def test_w15_panels_and_w16_w17_extension_semantics_are_separate() -> None:
    w15 = [x for x in CODE_OWNED_WORLD_SCOPE_FRAGMENTS.panels if x.world_slot == "W15"]
    assert [x.panel_id for x in w15] == [
        "W15A-randomized-identifiable",
        "W15B-observational-nonidentified",
    ]
    assert [x.axes.R.identification for x in w15] == ["point", "none"]
    by_slot = {x.world_slot: x for x in CODE_OWNED_WORLD_SCOPE_FRAGMENTS.panels}
    assert (
        by_slot["W16"].axes.R.extension_semantics
        is ExtensionSemantic.NEW_CHECK_SCOPE_REFINEMENT
    )
    assert (
        by_slot["W17"].axes.R.extension_semantics
        is ExtensionSemantic.NEW_TREATMENT_SCOPE_REFINEMENT
    )
    assert (
        by_slot["W16"].task_applicability[-1].applicability
        is TaskApplicability.POST_SEAL_EXTENSION
    )


def test_d_is_metrics_distance_and_r_is_data_resources_isolation_identification() -> (
    None
):
    panel = CODE_OWNED_WORLD_SCOPE_FRAGMENTS.panels[0]
    registry = benchmark_v1_metric_target_registry()
    assert panel.axes.D.metric_target_schema.startswith(
        "ucm-pre-freeze-metric-target-registry/"
    )
    assert panel.axes.D.metric_target_domain_hex == METRIC_TARGET_DOMAIN.hex()
    assert panel.axes.D.metric_target_artifact_digest == registry.artifact_digest
    assert panel.axes.D.metric_target_digest == registry.metric_target_digest
    assert (
        panel.axes.D.metric_target_source
        == "metric_configuration.benchmark_v1_metric_target_registry"
    )
    assert (
        panel.axes.D.panel_metric_applicability_status == "unresolved_global_target_gap"
    )
    assert panel.axes.D.applicable_measurement_ids == ()
    assert panel.axes.D.calibration_bins == 15
    assert panel.axes.D.behavior_distance_id == "linf_max_abs_behavior_signature"
    assert panel.axes.D.pair_classifier_id == "metrics.classify_pair"
    assert tuple(x.generator_split.value for x in panel.axes.R.split_roles) == (
        "train",
        "validation",
        "sealed_test",
    )
    assert panel.axes.R.projection_layers == (
        "candidate_inputs",
        "trainer_targets",
        "judge_oracle",
    )
    assert dict(panel.axes.R.worker_contracts)["head_worker"].startswith(
        "fresh_process_"
    )


def test_gap_inventory_is_live_field_derived_and_exact() -> None:
    report = inspect_world_scope_fragments()
    assert report.status == "PRE-FREEZE" and not report.scope_ready
    assert not report.scope_manifest_emitted and not report.freeze_authority
    metric_gap_count = benchmark_v1_metric_target_registry().target_gap_count
    assert len(report.gaps) == 562 + metric_gap_count + 2
    by_axis = Counter(x.axis for x in report.gaps)
    assert by_axis == {
        "P": 63,
        "O": 69,
        "A": 38,
        "Q": 44,
        "Pi": 4,
        "Gamma": 21,
        "Y": 90,
        "U": 21,
        "D": 126 + metric_gap_count + 2,
        "R": 86,
    }
    assert {x.code for x in report.gaps} == set(ScopeGapCode)
    assert sum(x.code is ScopeGapCode.A_EFFECT_KERNEL for x in report.gaps) == sum(
        len(p.axes.A.actions) for p in report.fragments.panels
    )
    assert sum(x.code is ScopeGapCode.Q_RESULT_KERNEL for x in report.gaps) == sum(
        len(p.axes.Q.checks) for p in report.fragments.panels
    )
    assert (
        sum(x.code is ScopeGapCode.D_METRIC_TARGET_GAP for x in report.gaps)
        == metric_gap_count
    )
    global_d_codes = {
        ScopeGapCode.D_METRIC_TARGET_GAP,
        ScopeGapCode.D_BEHAVIOR_DISTANCE_CLOSURE,
        ScopeGapCode.D_PAIR_CLASSIFIER_CLOSURE,
    }
    assert all(
        x.scope_level is GapScope.GLOBAL and x.world_slot is None and x.panel_id is None
        for x in report.gaps
        if x.code in global_d_codes
    )
    assert [
        (x.world_slot, x.axis)
        for x in report.gaps
        if x.code in {ScopeGapCode.Q_W16_EXTENSION, ScopeGapCode.A_W17_EXTENSION}
    ] == [("W16", "Q"), ("W17", "A")]
    with pytest.raises(ProtocolViolation, match="PRE-FREEZE and incomplete"):
        report.require_scope_ready()
    with pytest.raises(ProtocolViolation, match="gap inventory"):
        WorldScopeBuildReport(report.fragments, report.gaps[:-1])


def test_exact_preimage_digests_and_live_roundtrip() -> None:
    parsed = parse_world_scope_fragment_set_bytes(CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES)
    assert parsed == CODE_OWNED_WORLD_SCOPE_FRAGMENTS
    assert (
        world_scope_fragment_artifact_digest_from_bytes(parsed.canonical_bytes)
        == CODE_OWNED_WORLD_SCOPE_FRAGMENT_ARTIFACT_DIGEST
    )
    assert (
        world_scope_fragment_semantic_digest_from_bytes(parsed.canonical_bytes)
        == CODE_OWNED_WORLD_SCOPE_FRAGMENT_SEMANTIC_DIGEST
    )
    assert (
        CODE_OWNED_WORLD_SCOPE_FRAGMENT_ARTIFACT_DIGEST
        == "sha256:" + hashlib.sha256(parsed.canonical_bytes).hexdigest()
    )
    assert (
        CODE_OWNED_WORLD_SCOPE_FRAGMENT_SEMANTIC_DIGEST
        == "sha256:"
        + hashlib.sha256(
            WORLD_SCOPE_FRAGMENT_DOMAIN + parsed.canonical_bytes
        ).hexdigest()
    )


def test_semantic_preimage_excludes_readiness_corpus_freeze_and_raw_seeds() -> None:
    body = json.loads(CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES)
    assert _keys(body).isdisjoint(
        {
            "registry_digest",
            "readiness",
            "evidence",
            "corpus",
            "freeze_manifest_digest",
            "raw_seed",
            "train_seed",
            "eval_seed",
            "expected_cells_digest",
        }
    )
    text = CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES.decode()
    assert "SCOPE_MANIFEST" not in text and "FROZEN-v1" not in text


def test_resigned_axis_catalog_policy_and_task_tampering_is_rejected() -> None:
    mutations = (
        lambda b: b["panels"][0]["axes"]["A"]["actions"][0].__setitem__("cost", 99.0),
        lambda b: b["panels"][0]["axes"]["Tau"]["horizons"].append(99),
        lambda b: b["panels"][0]["axes"]["D"].__setitem__("calibration_bins", 10),
        lambda b: b["panels"][0]["axes"]["D"].__setitem__(
            "metric_target_digest", "sha256:" + "0" * 64
        ),
        lambda b: b["panels"][0]["task_applicability"][0].__setitem__(
            "operations", ["rollout"]
        ),
    )
    for mutation in mutations:
        with pytest.raises(ProtocolViolation):
            parse_world_scope_fragment_set_bytes(_mutate(mutation))


def test_d_exact_metric_target_binding_is_formula_sensitive() -> None:
    registry = benchmark_v1_metric_target_registry()
    body = registry.to_wire()
    output = body["measurement_contracts"][0]["outputs"][0]
    output["formula_version"] = "tampered-v1"
    tampered_bytes = canonical_json_bytes(body)
    tampered_digest = (
        "sha256:" + hashlib.sha256(METRIC_TARGET_DOMAIN + tampered_bytes).hexdigest()
    )

    assert tampered_bytes != registry.canonical_bytes
    assert tampered_digest != registry.metric_target_digest
    assert (
        CODE_OWNED_WORLD_SCOPE_FRAGMENTS.panels[0].axes.D.metric_target_digest
        == registry.metric_target_digest
    )


def test_nested_action_and_policy_objects_do_not_retain_mutable_aliases() -> None:
    source_schema = {"nested": {"enum": [1, 2]}}
    action = ActionDeclaration.from_live("AX", source_schema, 0.0)
    source_schema["nested"]["enum"].append(3)
    emitted_action = action.to_wire()
    emitted_action["parameter_schema"]["nested"]["enum"].append(4)
    assert action.to_wire()["parameter_schema"] == {"nested": {"enum": [1, 2]}}

    source_parameters = {"adaptive_rule": "rule-x", "nested": [1]}
    planned = PlannedActionDeclaration.from_live(0, "AX", source_parameters)
    source_parameters["nested"].append(2)
    emitted_planned = planned.to_wire()
    emitted_planned["parameters"]["nested"].append(3)
    assert planned.to_wire()["parameters"] == {
        "adaptive_rule": "rule-x",
        "nested": [1],
    }

    before_bytes = CODE_OWNED_WORLD_SCOPE_FRAGMENTS.canonical_bytes
    before_digest = CODE_OWNED_WORLD_SCOPE_FRAGMENTS.semantic_digest
    emitted_fragment = CODE_OWNED_WORLD_SCOPE_FRAGMENTS.to_wire()
    emitted_fragment["panels"][0]["axes"]["A"]["actions"][0]["parameter_schema"][
        "mutated"
    ] = True
    assert CODE_OWNED_WORLD_SCOPE_FRAGMENTS.canonical_bytes == before_bytes
    assert CODE_OWNED_WORLD_SCOPE_FRAGMENTS.semantic_digest == before_digest


def test_panel_enum_noncanonical_duplicate_and_extra_fields_fail_closed() -> None:
    with pytest.raises(ProtocolViolation):
        parse_world_scope_fragment_set_bytes(_mutate(lambda b: b["panels"].pop()))
    with pytest.raises(ProtocolViolation):
        parse_world_scope_fragment_set_bytes(
            _mutate(lambda b: b["panels"][0].__setitem__("panel_id", "renamed"))
        )
    with pytest.raises(ProtocolViolation, match="canonical"):
        parse_world_scope_fragment_set_bytes(
            CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES.rstrip(b"\n")
        )
    duplicate = CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES.replace(
        b'{"authority_claim":', b'{"authority_claim":"x","authority_claim":', 1
    )
    with pytest.raises(ProtocolViolation, match="duplicate key"):
        parse_world_scope_fragment_set_bytes(duplicate)
    with pytest.raises(ProtocolViolation, match="missing/extra"):
        parse_world_scope_fragment_set_bytes(
            _mutate(lambda b: b.__setitem__("scope_digest", "caller"))
        )
