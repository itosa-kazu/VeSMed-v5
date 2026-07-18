from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter

import pytest

import prototype.unified_map.world_scope_fragments as world_scope_fragments_module
from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.evaluator import EvaluationTask
from prototype.unified_map.metric_configuration import (
    METRIC_TARGET_DOMAIN,
    benchmark_v1_metric_target_registry,
)
from prototype.unified_map.scope_manifest import SCOPE_AXES
from prototype.unified_map.scope_transition_protocols import (
    DISTANCE_DERIVATION_SCHEMA,
    EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST,
    EXTENSION_TEMPLATE_SET_BYTES,
    EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST,
    SPLIT_DERIVATION_ARTIFACT_DIGEST,
    SPLIT_DERIVATION_PROTOCOL_BYTES,
    SPLIT_DERIVATION_SEMANTIC_DIGEST,
    distance_derivation_contract_bytes,
    distance_derivation_contract_digest,
    parse_extension_template_set_bytes,
    parse_split_derivation_protocol_bytes,
)
from prototype.unified_map.task_protocol import TASK_EXECUTION_TRUTH
from prototype.unified_map.world_scope_fragments import (
    CODE_OWNED_WORLD_SCOPE_FRAGMENT_ARTIFACT_DIGEST,
    CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES,
    CODE_OWNED_WORLD_SCOPE_FRAGMENT_SEMANTIC_DIGEST,
    CODE_OWNED_WORLD_SCOPE_FRAGMENTS,
    EXPECTED_PANEL_IDENTITIES,
    ActionDeclaration,
    ExtensionSemantic,
    ExtensionTemplateRole,
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


def _string_values(value: object) -> tuple[str, ...]:
    if type(value) is dict:
        return tuple(item for child in value.values() for item in _string_values(child))
    if type(value) is list:
        return tuple(item for child in value for item in _string_values(child))
    return (value,) if type(value) is str else ()


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


def test_w15_panels_and_w16_w17_extension_successors_are_not_axis_shortcuts() -> None:
    w15 = [x for x in CODE_OWNED_WORLD_SCOPE_FRAGMENTS.panels if x.world_slot == "W15"]
    assert [x.panel_id for x in w15] == [
        "W15A-randomized-identifiable",
        "W15B-observational-nonidentified",
    ]
    assert [x.axes.R.identification for x in w15] == ["point", "none"]
    by_slot = {x.world_slot: x for x in CODE_OWNED_WORLD_SCOPE_FRAGMENTS.panels}
    w16, w17 = by_slot["W16"], by_slot["W17"]
    assert (
        w16.axes.Q.extension_commitment_template.role is ExtensionTemplateRole.NEW_CHECK
    )
    assert w16.axes.A.extension_commitment_template is None
    assert (
        w17.axes.A.extension_commitment_template.role
        is ExtensionTemplateRole.NEW_TREATMENT
    )
    assert w17.axes.Q.extension_commitment_template is None
    for panel in (w16, w17):
        transition = panel.axes.R.extension_transition
        assert transition.semantic is ExtensionSemantic.OPAQUE_POST_SEAL_SCOPE_SUCCESSOR
        assert transition.successor_axis_coverage == SCOPE_AXES
        assert transition.required_changed_axes == (transition.role_axis,)
        assert "D" in transition.allowed_changed_axes
        assert transition.role_axis in transition.role_specific_allowed_changed_axes
        assert transition.primary_aggregate_eligible is False
        assert (
            transition.extension_result_namespace == "separate_extension_only_namespace"
        )
        assert transition.mixed_scope_aggregation == "forbidden"
        assert transition.source_target_scope_join == "fail_closed_exact_identity_join"
        assert transition.chronology.index(
            "seal_primary_result_root_before_extension_reveal"
        ) < transition.chronology.index(
            "reveal_only_after_candidate_model_and_state_seals"
        )
        assert transition.chronology.index(
            "reveal_only_after_candidate_model_and_state_seals"
        ) < transition.chronology.index("derive_full_expanded_state_space_S_prime")
        assert transition.chronology.index(
            "run_state_only_first_extension_query"
        ) < transition.chronology.index(
            "allow_optional_measured_migration_only_after_scope_insufficient"
        )
        assert {
            "base_scope_exact_bytes_unchanged",
            "primary_result_root_is_exactly_equal_before_seal_reveal_and_after_extension",
            "seal_reveal_diff_request_transcript_source_and_target_scope_identity_join_fail_closed",
            "state_only_first_request_primary_state_hash_is_a_member_of_the_sealed_primary_state_set",
            "typed_first_query_and_result_exact_preimages_join_request_and_transcript",
            "revealed_extension_spec_bytes_equal_the_actual_diff_spec_bytes",
            "mixed_scope_aggregation_forbidden",
            "extension_outputs_use_a_separate_extension_only_namespace",
        }.issubset(set(transition.successor_receipt_required_verifications))
        assert transition.closure_status == "protocol_complete_predecessor"
        assert transition.successor_receipt_schema == "ucm-successor-scope-receipt/2"
        assert transition.actual_scope_diff_schema == "ucm-actual-scope-diff/2"
        assert transition.extension_scope_spec_schema == "ucm-extension-scope-spec/1"
        assert (
            transition.first_query_envelope_schema
            == "ucm-extension-first-query-envelope/1"
        )
        assert (
            transition.first_result_envelope_schema
            == "ucm-extension-first-result-envelope/1"
        )
        assert transition.successor_runtime_eligible is False
        assert transition.runtime_binding_status == "successor_runtime_not_integrated"
        assert transition.successor_runtime_requirements
        assert transition.successor_runtime_requirement_count == 4
        assert all(
            requirement.blocks_base_scope is False
            for requirement in transition.successor_runtime_requirements
        )
        assert (
            transition.task_relation
            == "world_extension_is_distinct_from_new_readout_task"
        )
    assert (
        w16.task_applicability[-1].applicability
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
    derivation = panel.axes.R.family_split_derivation
    split_protocol = parse_split_derivation_protocol_bytes(
        SPLIT_DERIVATION_PROTOCOL_BYTES
    )
    assert split_protocol.gap_count == 0
    assert split_protocol.post_scope_requirement_count == 2
    assert split_protocol.artifact_digest == SPLIT_DERIVATION_ARTIFACT_DIGEST
    assert split_protocol.semantic_digest == SPLIT_DERIVATION_SEMANTIC_DIGEST
    assert (
        derivation.protocol_reference.artifact_digest
        == SPLIT_DERIVATION_ARTIFACT_DIGEST
    )
    assert (
        derivation.protocol_reference.semantic_digest
        == SPLIT_DERIVATION_SEMANTIC_DIGEST
    )
    assert (
        derivation.panel_count,
        derivation.task_count,
        derivation.split_count,
        derivation.physical_assignment_count,
        derivation.task_assignment_projection_count,
        derivation.physical_partition_count,
        derivation.task_partition_projection_count,
        derivation.zipped_slots_per_physical_partition,
        derivation.semantic_zipped_slot_count,
    ) == (21, 5, 3, 21, 105, 63, 315, 5, 315)
    assert len(derivation.zipped_slots) == 5
    assert all(
        slot.training_commitment_stage == "post_freeze_pre_training_precommit"
        and slot.evaluation_commitment_stage == "post_candidate_seals_hidden_commitment"
        and slot.evaluation_reveal_stage == "post_corpus_finalization"
        for slot in derivation.zipped_slots
    )
    assert derivation.post_scope_derivation_stage == "post_scope_authorization"
    assert (
        derivation.post_scope_derivation_rule
        == "actual_authorities_bind_S_one_way_and_never_feed_back_into_S"
    )
    assert derivation.closure_status == "protocol_complete_predecessor"
    assert derivation.post_scope_authority_requirement_count == 2
    assert tuple(
        requirement.to_wire()
        for requirement in derivation.post_scope_authority_requirements
    ) == tuple(split_protocol.to_wire()["post_scope_requirements"])
    assert all(
        requirement.blocks_base_scope is False
        for requirement in derivation.post_scope_authority_requirements
    )


def test_gap_inventory_is_live_field_derived_and_exact() -> None:
    report = inspect_world_scope_fragments()
    assert report.status == "PRE-FREEZE" and not report.scope_ready
    assert not report.scope_manifest_emitted and not report.freeze_authority
    metric_gap_count = benchmark_v1_metric_target_registry().target_gap_count
    assert len(report.gaps) == 537 + metric_gap_count + 2
    by_axis = Counter(x.axis for x in report.gaps)
    assert by_axis == {
        "P": 63,
        "O": 69,
        "A": 37,
        "Q": 43,
        "Pi": 4,
        "Gamma": 21,
        "Y": 90,
        "U": 21,
        "D": 126 + metric_gap_count + 2,
        "R": 63,
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
    assert {x.axis for x in report.gaps if x.scope_level is GapScope.GLOBAL} == {"D"}
    post_scope_ids = {
        requirement.requirement_id
        for panel in report.fragments.panels
        for requirement in panel.axes.R.family_split_derivation.post_scope_authority_requirements
    }
    post_scope_ids.update(
        requirement.requirement_id
        for panel in report.fragments.panels
        if panel.axes.R.extension_transition is not None
        for requirement in panel.axes.R.extension_transition.successor_runtime_requirements
    )
    assert post_scope_ids
    assert post_scope_ids.isdisjoint(gap.subject_id for gap in report.gaps)
    assert all(
        "successor" not in gap.detail.lower() and "post-scope" not in gap.detail.lower()
        for gap in report.gaps
    )
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
            "actual_family_assignment_root",
            "actual_split_partition_root",
            "panel_assignment_digest",
            "extension_scope_digest",
            "extension_pack_digest",
            "revealed_extension_payload",
            "actual_changed_axes",
            "successor_scope_digest",
            "target_scope_digest",
            "base_scope_digest_before",
            "base_scope_digest_after",
            "primary_result_root_before",
            "primary_result_root_after",
        }
    )
    text = CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES.decode()
    assert "SCOPE_MANIFEST" not in text and "FROZEN-v1" not in text


def test_successor_contracts_are_symbolic_and_do_not_self_reference_base_scope() -> (
    None
):
    for panel in CODE_OWNED_WORLD_SCOPE_FRAGMENTS.panels:
        derivation = panel.axes.R.family_split_derivation
        wire = derivation.to_wire()
        assert derivation.closure_status == "protocol_complete_predecessor"
        assert derivation.scope_forbidden_inputs == (
            "actual_family_assignment_root",
            "actual_split_partition_root",
            "actual_panel_assignment_or_partition_digest",
            "actual_split_seed_commitment_or_opening",
            "actual_TRAIN5_or_EVAL5_tuple",
            "actual_TRAIN5_PRECOMMIT_or_EVAL5_commitment_value",
            "actual_run_specific_raw_seed_value_or_digest",
        )
        symbolic_wire = dict(wire)
        symbolic_wire.pop("protocol_reference")
        assert not any(
            value.startswith("sha256:") for value in _string_values(symbolic_wire)
        )
        assert _keys(wire).isdisjoint(
            {
                "scope_digest",
                "panel_digest",
                "raw_seed_digest",
                "assignment_root",
                "partition_root",
            }
        )

        transition = panel.axes.R.extension_transition
        if transition is None:
            continue
        transition_wire = transition.to_wire()
        extension_protocol = parse_extension_template_set_bytes(
            EXTENSION_TEMPLATE_SET_BYTES
        )
        assert extension_protocol.gap_count == 0
        assert extension_protocol.successor_blocker_count == 4
        assert (
            extension_protocol.artifact_digest == EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST
        )
        assert (
            extension_protocol.semantic_digest == EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST
        )
        assert (
            transition.protocol_reference.artifact_digest
            == EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST
        )
        assert (
            transition.protocol_reference.semantic_digest
            == EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST
        )
        assert transition.closure_status == "protocol_complete_predecessor"
        extension_protocol_wire = extension_protocol.to_wire()
        protocol = extension_protocol_wire["protocol"]
        template = next(
            row
            for row in protocol["templates"]
            if row["world_slot"] == panel.world_slot
        )
        distance_preimage = protocol["distance_derivation_contract"]
        scope_spec_preimage = template["extension_scope_spec_contract"]
        scope_spec_contract = json.loads(
            base64.b64decode(scope_spec_preimage["payload_b64"], validate=True)
        )
        contract_wire = json.loads(distance_derivation_contract_bytes())
        assert transition.required_changed_axes == tuple(
            template["required_changed_axes"]
        )
        assert (
            transition.extension_scope_spec_contract_preimage_schema
            == scope_spec_preimage["schema_version"]
        )
        assert (
            transition.extension_scope_spec_contract_preimage_label
            == scope_spec_preimage["label"]
        )
        assert (
            transition.extension_scope_spec_contract_preimage_encoding
            == scope_spec_preimage["encoding"]
            == "base64"
        )
        assert (
            transition.extension_scope_spec_contract_schema
            == scope_spec_contract["schema_version"]
        )
        assert (
            transition.extension_scope_spec_contract_byte_count
            == scope_spec_preimage["byte_count"]
        )
        assert (
            transition.extension_scope_spec_contract_artifact_digest
            == scope_spec_preimage["digest"]
        )
        assert (
            transition.extension_scope_spec_schema
            == scope_spec_contract["typed_spec_schema"]
            == protocol["external_successor_artifacts"]["actual_scope_diff"][
                "extension_scope_spec_schema"
            ]
        )
        assert (
            transition.extension_scope_spec_parser
            == scope_spec_contract["parser"]
            == "parse_extension_scope_spec_bytes"
        )
        assert (
            transition.successor_scope_deriver
            == scope_spec_contract["successor_deriver"]
            == "derive_successor_scope_from_spec"
        )
        assert (
            transition.distance_derivation_declaration_schema
            == DISTANCE_DERIVATION_SCHEMA
        )
        assert (
            transition.distance_derivation_contract_preimage_schema
            == distance_preimage["schema_version"]
        )
        assert (
            transition.distance_derivation_contract_preimage_label
            == distance_preimage["label"]
        )
        assert (
            transition.distance_derivation_contract_preimage_encoding
            == distance_preimage["encoding"]
            == "base64"
        )
        assert (
            transition.distance_derivation_contract_schema
            == contract_wire["schema_version"]
        )
        assert (
            transition.distance_derivation_contract_byte_count
            == distance_preimage["byte_count"]
        )
        assert (
            transition.distance_derivation_contract_artifact_digest
            == distance_preimage["digest"]
        )
        assert (
            transition.distance_derivation_contract_digest
            == distance_derivation_contract_digest()
            == template["distance_derivation_contract_digest"]
        )
        assert tuple(
            requirement.to_wire()
            for requirement in transition.successor_runtime_requirements
        ) == tuple(extension_protocol_wire["successor_blockers"])
        symbolic_extension_wire = dict(transition_wire)
        symbolic_extension_wire.pop("protocol_reference", None)
        symbolic_extension_wire.pop("distance_derivation_contract", None)
        symbolic_extension_wire.pop("extension_scope_spec_contract", None)
        assert not any(
            value.startswith("sha256:")
            for value in _string_values(symbolic_extension_wire)
        )
        assert _keys(transition_wire).isdisjoint(
            {
                "commitment_digest",
                "extension_scope_digest",
                "extension_pack_digest",
                "S_prime",
                "primary_score_delta",
                "actual_changed_axes",
                "successor_scope_digest",
                "target_scope_digest",
            }
        )


def test_resigned_axis_catalog_policy_and_task_tampering_is_rejected() -> None:
    mutations = (
        lambda b: b["panels"][0]["axes"]["A"]["actions"][0].__setitem__("cost", 99.0),
        lambda b: b["panels"][0]["axes"]["Tau"]["horizons"].append(99),
        lambda b: b["panels"][0]["axes"]["D"].__setitem__("calibration_bins", 10),
        lambda b: b["panels"][0]["axes"]["D"].__setitem__(
            "metric_target_digest", "sha256:" + "0" * 64
        ),
        lambda b: b["panels"][0]["axes"]["R"]["family_split_derivation"][
            "projection_shape"
        ].__setitem__("task_partition_projection_count", 314),
        lambda b: next(p for p in b["panels"] if p["world_slot"] == "W16")["axes"]["R"][
            "extension_transition"
        ]["successor_axis_coverage"].remove("D"),
        lambda b: next(p for p in b["panels"] if p["world_slot"] == "W16")["axes"]["R"][
            "extension_transition"
        ]["required_changed_axes"].__setitem__(0, "A"),
        lambda b: next(p for p in b["panels"] if p["world_slot"] == "W16")["axes"]["R"][
            "extension_transition"
        ]["distance_derivation_contract"].__setitem__(
            "contract_digest", "sha256:" + "0" * 64
        ),
        lambda b: next(p for p in b["panels"] if p["world_slot"] == "W16")["axes"]["R"][
            "extension_transition"
        ]["extension_scope_spec_contract"].__setitem__(
            "artifact_digest", "sha256:" + "0" * 64
        ),
        lambda b: next(p for p in b["panels"] if p["world_slot"] == "W17")["axes"]["R"][
            "extension_transition"
        ]["external_successor_contract"].__setitem__(
            "successor_runtime_eligible", True
        ),
        lambda b: b["panels"][0]["axes"]["R"]["family_split_derivation"][
            "post_scope_authority_requirements"
        ][0].__setitem__("blocks_base_scope", True),
        lambda b: next(p for p in b["panels"] if p["world_slot"] == "W17")["axes"]["R"][
            "extension_transition"
        ]["external_successor_contract"]["successor_runtime_requirements"][
            0
        ].__setitem__("blocks_base_scope", True),
        lambda b: next(p for p in b["panels"] if p["world_slot"] == "W16")["axes"][
            "Q"
        ].__setitem__("extension_commitment_template", None),
        lambda b: b["panels"][0]["task_applicability"][0].__setitem__(
            "operations", ["rollout"]
        ),
    )
    for mutation in mutations:
        with pytest.raises(ProtocolViolation):
            parse_world_scope_fragment_set_bytes(_mutate(mutation))


@pytest.mark.parametrize(
    ("binding_name", "replacement", "factory"),
    (
        (
            "SPLIT_DERIVATION_ARTIFACT_DIGEST",
            "sha256:" + "0" * 64,
            lambda: world_scope_fragments_module._family_split_derivation_requirement(),
        ),
        (
            "EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST",
            "sha256:" + "0" * 64,
            lambda: world_scope_fragments_module._extension_transition(
                ExtensionTemplateRole.NEW_CHECK
            ),
        ),
        (
            "DISTANCE_DERIVATION_SCHEMA",
            "evil-schema",
            lambda: world_scope_fragments_module._extension_transition(
                ExtensionTemplateRole.NEW_CHECK
            ),
        ),
        (
            "_parsed_protocol_reference_contract",
            lambda kind: (
                "evil-schema",
                "sha256:" + "0" * 64,
                "sha256:" + "1" * 64,
                "evil.source",
            ),
            lambda: world_scope_fragments_module._family_split_derivation_requirement(),
        ),
        (
            "_exact_protocol_reference_contract",
            lambda kind: (
                "evil-schema",
                "sha256:" + "0" * 64,
                "sha256:" + "1" * 64,
                "evil.source",
            ),
            lambda: world_scope_fragments_module._family_split_derivation_requirement(),
        ),
        (
            "_exact_distance_derivation_declaration_schema",
            lambda: "evil-schema",
            lambda: world_scope_fragments_module._extension_transition(
                ExtensionTemplateRole.NEW_CHECK
            ),
        ),
    ),
)
def test_local_predecessor_identity_alias_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    binding_name: str,
    replacement: object,
    factory: object,
) -> None:
    monkeypatch.setattr(world_scope_fragments_module, binding_name, replacement)
    with pytest.raises(ProtocolViolation, match="drifted"):
        factory()  # type: ignore[operator]


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
