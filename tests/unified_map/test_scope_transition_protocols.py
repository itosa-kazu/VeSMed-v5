from __future__ import annotations

import base64
import copy

import pytest

import prototype.unified_map.scope_transition_protocols as protocols
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    domain_digest,
)
from prototype.unified_map.metric_configuration import (
    benchmark_v1_metric_target_registry,
)
from prototype.unified_map.metric_runtime_bindings import (
    benchmark_v1_metric_runtime_bindings,
)
from prototype.unified_map.panel_split_authority import (
    AuthoritySplit,
    FamilyDefinitionIntent,
    GeneratorIntent,
    PanelPhysicalIdentity,
    SplitNeutralFamilyUnitIntent,
    SplitPolicyContext,
    SplitSeedCommitmentContext,
)
from prototype.unified_map.scope_manifest import (
    SCOPE_AXES,
    ScopeAxisDeclarations,
    ScopeDeclaration,
    ScopeManifest,
)
from prototype.unified_map.scope_transition_protocols import (
    ACTUAL_SCOPE_DIFF_SCHEMA,
    EXTENSION_SCOPE_REQUEST_SCHEMA,
    EXTENSION_SCOPE_REVEAL_SCHEMA,
    EXTENSION_SCOPE_TRANSCRIPT_SCHEMA,
    EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST,
    EXTENSION_TEMPLATE_SET_BYTES,
    EXTENSION_TEMPLATE_SET_DOMAIN,
    EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST,
    EXTENSION_TRANSITION_SEAL_SCHEMA,
    SPLIT_DERIVATION_ARTIFACT_DIGEST,
    SPLIT_DERIVATION_DOMAIN,
    SPLIT_DERIVATION_PROTOCOL_BYTES,
    SPLIT_DERIVATION_SEMANTIC_DIGEST,
    SUCCESSOR_RECEIPT_SCHEMA,
    ActualScopeDiff,
    ExtensionScopeRequest,
    ExtensionScopeReveal,
    ExtensionScopeTranscript,
    ExtensionAxisPatch,
    ExtensionFirstQueryEnvelope,
    ExtensionFirstResultEnvelope,
    ExtensionScopeSpec,
    ExtensionTemplateSet,
    ExtensionTransitionSeal,
    PostScopeRequirement,
    SplitAssignmentDerivation,
    SplitDerivationProtocol,
    SplitDerivationUnit,
    SplitUnitAssignment,
    SuccessorReceipt,
    SuccessorRuntimeBlocker,
    build_actual_scope_diff,
    build_extension_template_set,
    build_split_derivation_protocol,
    compute_extension_scope_commitment,
    compute_split_seed_commitment,
    derive_panel_family_assignments,
    derive_successor_scope_from_spec,
    extension_template_set_artifact_digest_from_bytes,
    extension_template_set_semantic_digest_from_bytes,
    parse_actual_scope_diff_bytes,
    parse_extension_first_query_bytes,
    parse_extension_first_result_bytes,
    parse_extension_scope_spec_bytes,
    parse_extension_template_set_bytes,
    parse_split_derivation_protocol_bytes,
    parse_successor_receipt_bytes,
    split_derivation_artifact_digest_from_bytes,
    split_derivation_known_answer,
    split_derivation_semantic_digest_from_bytes,
    verify_panel_family_assignments,
    verify_successor_distance_axis,
)


def _sha(tag: str) -> str:
    return "sha256:" + tag * 64


def _split_wire() -> dict:
    return build_split_derivation_protocol().to_wire()


def _extension_wire() -> dict:
    return build_extension_template_set().to_wire()


def _split_mutation(mutator) -> bytes:
    value = copy.deepcopy(_split_wire())
    mutator(value)
    return canonical_json_bytes(value)


def _extension_mutation(mutator) -> bytes:
    value = copy.deepcopy(_extension_wire())
    mutator(value)
    return canonical_json_bytes(value)


def _preimage_bytes(row: dict) -> bytes:
    raw = base64.b64decode(row["payload_b64"], validate=True)
    assert len(raw) == row["byte_count"]
    assert digest_bytes(raw) == row["digest"]
    assert base64.b64encode(raw).decode("ascii") == row["payload_b64"]
    return raw


def _scope(scope_id: str) -> ScopeManifest:
    return ScopeManifest(
        "ucm-extension-test",
        scope_id,
        {
            axis: ScopeAxisDeclarations(
                (ScopeDeclaration(f"{axis.lower()}-base", {"axis": axis, "v": 1}),)
            )
            for axis in SCOPE_AXES
        },
    )


def _split_unit(index: int, group_id: str, weight: int) -> SplitDerivationUnit:
    intent = SplitNeutralFamilyUnitIntent(
        f"unit-{index}",
        FamilyDefinitionIntent(f"definition-{index}", (f"member-{index}",)),
        GeneratorIntent(
            f"generator-{index}", "1", "generator-protocol", f"population-{index}"
        ),
        group_id,
        weight,
    )
    return SplitDerivationUnit(canonical_json_bytes(intent.to_wire()))


def _split_context() -> SplitSeedCommitmentContext:
    return SplitSeedCommitmentContext(
        PanelPhysicalIdentity("ucm", "rev", _sha("0"), "W01", "primary"),
        SplitPolicyContext("policy", "1"),
    )


def _split_units() -> tuple[SplitDerivationUnit, ...]:
    return tuple(
        sorted(
            (
                _split_unit(1, "group-a", 1),
                _split_unit(2, "group-a", 2),
                _split_unit(3, "group-b", 3),
                _split_unit(4, "group-c", 4),
            ),
            key=lambda item: item.unit_intent_digest,
        )
    )


def _successor_scope(
    base: ScopeManifest,
    scope_id: str,
    non_distance_changes: tuple[str, ...],
    world_slot: str = "W16",
) -> ScopeManifest:
    spec = _extension_spec(base, scope_id, non_distance_changes, world_slot)
    metric = benchmark_v1_metric_target_registry().canonical_bytes
    runtime = benchmark_v1_metric_runtime_bindings(metric).canonical_bytes
    return derive_successor_scope_from_spec(
        base,
        spec,
        metric,
        runtime,
    )


def _extension_spec(
    base: ScopeManifest,
    scope_id: str,
    non_distance_changes: tuple[str, ...],
    world_slot: str = "W16",
) -> ExtensionScopeSpec:
    patches = tuple(
        ExtensionAxisPatch(
            axis,
            ScopeAxisDeclarations(
                (ScopeDeclaration(f"{axis.lower()}-successor", {"axis": axis, "v": 2}),)
            ),
        )
        for axis in SCOPE_AXES
        if axis in non_distance_changes
    )
    return ExtensionScopeSpec(world_slot, base.scope_digest, scope_id, patches)


def _actual_diff(
    world_slot: str = "W16",
    non_distance_changes: tuple[str, ...] = ("Q",),
) -> ActualScopeDiff:
    base = _scope("scope-S")
    spec = _extension_spec(base, "scope-S-prime", non_distance_changes, world_slot)
    return build_actual_scope_diff(
        spec.canonical_bytes,
        base.canonical_bytes,
    )


def _receipt() -> SuccessorReceipt:
    diff = _actual_diff()
    spec = diff.extension_spec_bytes
    nonce = bytes(range(32))
    commitment = compute_extension_scope_commitment("W16", spec, nonce)
    root = _sha("1")
    state_hashes = (_sha("4"), _sha("5"))
    state_root = protocols._primary_state_set_root(state_hashes)
    seal = ExtensionTransitionSeal(
        "W16",
        build_extension_template_set().semantic_digest,
        diff.base_scope.scope_digest,
        commitment,
        _sha("2"),
        _sha("3"),
        state_hashes,
        state_root,
        _sha("8"),
        root,
    )
    reveal = ExtensionScopeReveal(
        "W16", commitment, spec, nonce, seal.seal_digest, root
    )
    first_query = ExtensionFirstQueryEnvelope(
        "W16",
        diff.base_scope.scope_digest,
        diff.successor_scope.scope_digest,
        diff.diff_digest,
        diff.extension_spec.spec_digest,
        state_hashes[0],
        canonical_json_bytes(
            {
                "schema_version": "ucm-extension-state-only-readout-query/1",
                "query_type": "extension_readout",
                "readout_id": "readout-1",
            }
        ),
    )
    request = ExtensionScopeRequest(
        "W16",
        seal.seal_digest,
        diff.diff_digest,
        diff.base_scope.scope_digest,
        diff.successor_scope.scope_digest,
        first_query.canonical_bytes,
    )
    first_result = ExtensionFirstResultEnvelope(
        request.request_digest,
        "ok",
        canonical_json_bytes({"prediction": 7}),
    )
    extension_result = first_result.result_digest
    transcript = ExtensionScopeTranscript(
        request.request_digest,
        seal.seal_digest,
        diff.diff_digest,
        diff.base_scope.scope_digest,
        diff.successor_scope.scope_digest,
        first_result.canonical_bytes,
        False,
    )
    return SuccessorReceipt(
        seal,
        reveal,
        diff,
        request,
        transcript,
        root,
        root,
        extension_result,
    )


def test_predecessors_are_scope_independent_protocol_complete_and_zero_gap() -> None:
    split = parse_split_derivation_protocol_bytes(SPLIT_DERIVATION_PROTOCOL_BYTES)
    extension = parse_extension_template_set_bytes(EXTENSION_TEMPLATE_SET_BYTES)

    assert type(split) is SplitDerivationProtocol
    assert type(extension) is ExtensionTemplateSet
    assert split.gap_count == len(split.gaps) == 0
    assert extension.gap_count == len(extension.gaps) == 0
    assert split.to_wire()["benchmark_status"] == "PRE-FREEZE"
    assert extension.to_wire()["benchmark_status"] == "PRE-FREEZE"
    assert split.to_wire()["freeze_authority_status"] == "not_claimed"
    assert extension.to_wire()["freeze_authority_status"] == "not_claimed"


def test_post_scope_requirements_and_successor_blockers_do_not_block_base_S() -> None:
    split = build_split_derivation_protocol()
    extension = build_extension_template_set()

    assert split.post_scope_requirement_count == 2
    assert extension.successor_blocker_count == 4
    assert all(
        type(item) is PostScopeRequirement and item.blocks_base_scope is False
        for item in split.post_scope_requirements
    )
    assert all(
        type(item) is SuccessorRuntimeBlocker and item.blocks_base_scope is False
        for item in extension.successor_blockers
    )
    assert all(item not in split.gaps for item in split.post_scope_requirements)
    assert all(item not in extension.gaps for item in extension.successor_blockers)


def test_split_inventory_and_template_exclude_live_materialization() -> None:
    wire = _split_wire()
    inventory = wire["protocol"]["inventory_semantics"]
    assert inventory["panel_count"] == 21
    assert inventory["task_count"] == 5
    assert inventory["physical_assignment_count"] == 21
    assert inventory["panel_task_projection_count"] == 105
    assert inventory["physical_panel_split_count"] == 63
    assert inventory["zipped_slot_count"] == 315
    assert inventory["task_is_logical_projection_not_physical_shard_dimension"] is True
    assert (
        wire["protocol"]["deterministic_derivation"]["materialized_assignments"]
        == "excluded"
    )
    assert (
        wire["protocol"]["deterministic_derivation"]["materialized_partitions"]
        == "excluded"
    )
    assert wire["scope_binding_status"] == "not_bound"


def test_split_protocol_binds_exact_commitment_hkdf_and_algorithm_semantics() -> None:
    protocol = _split_wire()["protocol"]
    algorithm = _preimage_bytes(
        protocol["deterministic_derivation"]["algorithm_source"]
    )
    commitment = protocol["commitment_protocol"]
    commit_reveal = _preimage_bytes(commitment["commit_reveal_protocol"])
    kdf = _preimage_bytes(commitment["per_panel_seed_kdf"])

    assert commitment["commitment_scheme"] == (
        "sha256_domain_framed_context_nonce_seed_v1"
    )
    assert b"uint64_be_byte_length_then_exact_bytes" in commit_reveal
    assert b"exact_32_byte_nonce" in commit_reveal
    assert protocols.SPLIT_SEED_COMMITMENT_DOMAIN.hex().encode() in commit_reveal
    assert b"RFC5869-HKDF-SHA256" in kdf
    assert b'"task_identity_in_context_or_KDF":false' in kdf
    assert b"raw_group_priority_with_HMAC_SHA256" in algorithm
    assert b"split-kat-v1" in algorithm
    assert b"92a3d28bd4cef2837d36b216e56b26e8" in algorithm
    assert b"exact_canonical_SplitNeutralFamilyUnitIntent_bytes" in algorithm


def test_rfc5869_sha256_official_known_answer_case_1() -> None:
    # RFC 5869, Appendix A.1.  Literal values catch extract/expand drift.
    ikm = bytes.fromhex("0b" * 22)
    salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    okm = protocols._hkdf_sha256_extract_expand(ikm, salt, info, 42)
    assert okm.hex() == (
        "3cb25f25faacd57a90434f64d0362f2a"
        "2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
        "34007208d5b887185865"
    )


def test_split_literal_known_answer_and_atomic_weighted_greedy_assignment() -> None:
    kat = split_derivation_known_answer()
    summary = {
        "protocol": kat.preimage_wire()["protocol"],
        "commitment": kat.commitment,
        "commitment_context_digest": kat.commitment_context_digest,
        "panel_identity_digest": kat.panel_identity_digest,
        "panel_seed_digest": kat.panel_seed_digest,
        "input_set_root": kat.input_set_root,
        "assignments": [item.to_wire() for item in kat.assignments],
        "assignment_root": kat.assignment_root,
    }
    assert summary == {
        "protocol": "ucm-executable-split-assignment/1",
        "commitment": "sha256:d5855469bcaa6461edb534ad30cfca683933e34f5c0f846f7b34d877543683a7",
        "commitment_context_digest": "sha256:f11e9dcd1f5967d438fe525d145fb02fe90efd886f58c23a7043e772987af38c",
        "panel_identity_digest": "sha256:0bddc7b7ed9906e41a0a33a0833ab1de8da7fb70c95016e205e54655b99bf4c9",
        "panel_seed_digest": "sha256:e1ad929a71b06676b43d0a921811a7ff5239963324386de2cd3f7923736b835f",
        "input_set_root": "sha256:1e74941249c2e41ff18a7506cfce672e5eaf25b178a59068c265be233ac6ae79",
        "assignments": [
            {
                "unit_intent_digest": "sha256:01b106845337d9607efcfb589f288e70314f063f692b533b916d6a61ff027e92",
                "split": "validation",
            },
            {
                "unit_intent_digest": "sha256:12522e33645147c67f0f8d2d6d374d1824be017d1a8916d21df807ec7c78d026",
                "split": "test",
            },
            {
                "unit_intent_digest": "sha256:15ea9dc6c8fcdfda9d23edcc4d2f713d7a13b10b0aef1a71267dfee74b14c492",
                "split": "train",
            },
            {
                "unit_intent_digest": "sha256:6ed4b5afaf9d4c30defb0f2923b6b9ac9501a01559b00dd08c8eadb6c37e85d3",
                "split": "train",
            },
            {
                "unit_intent_digest": "sha256:fa1558e984adb059d227135e64305f8c680e9b12c6080bee98d834d1061b4501",
                "split": "validation",
            },
        ],
        "assignment_root": "sha256:92a3d28bd4cef2837d36b216e56b26e81edadd2f5e74bb3b6cf1c40fe47cec5c",
    }
    assignment_by_digest = {
        item.unit_intent_digest: item.split for item in kat.assignments
    }
    grouped: dict[str, set[AuthoritySplit]] = {}
    for unit in kat.input_units:
        grouped.setdefault(unit.atomic_group_id, set()).add(
            assignment_by_digest[unit.unit_intent_digest]
        )
    assert all(len(splits) == 1 for splits in grouped.values())
    assert {row.split for row in kat.assignments} == set(AuthoritySplit)


def test_split_commitment_must_open_before_assignment() -> None:
    context = _split_context()
    units = _split_units()
    with pytest.raises(ProtocolViolation, match="does not open"):
        derive_panel_family_assignments(
            units,
            expected_commitment=_sha("f"),
            context=context,
            hidden_seed=bytes(32),
            nonce=bytes(range(32)),
        )


def test_split_verifier_recomputes_full_assignment_and_rejects_mutation() -> None:
    context = _split_context()
    units = _split_units()
    seed = bytes(range(32))
    nonce = bytes(range(32, 64))
    commitment = compute_split_seed_commitment(context, seed, nonce)
    derived = derive_panel_family_assignments(
        units,
        expected_commitment=commitment,
        context=context,
        hidden_seed=seed,
        nonce=nonce,
    )
    verify_panel_family_assignments(
        derived,
        units,
        expected_commitment=commitment,
        context=context,
        hidden_seed=seed,
        nonce=nonce,
    )
    changed = tuple(
        SplitUnitAssignment(
            row.unit_intent_digest,
            AuthoritySplit.TEST
            if row.split is not AuthoritySplit.TEST
            else AuthoritySplit.TRAIN,
        )
        for row in derived.assignments
    )
    changed_preimage = {
        **derived.preimage_wire(),
        "assignments": [item.to_wire() for item in changed],
    }
    changed_root = domain_digest(
        protocols.SPLIT_ASSIGNMENT_ROOT_DOMAIN,
        (canonical_json_bytes(changed_preimage),),
    )
    mutated = SplitAssignmentDerivation(
        derived.commitment,
        derived.commitment_context_digest,
        derived.panel_identity_digest,
        derived.panel_seed_digest,
        derived.input_units,
        derived.input_set_root,
        changed,
        changed_root,
    )
    with pytest.raises(ProtocolViolation, match="exact-replay"):
        verify_panel_family_assignments(
            mutated,
            units,
            expected_commitment=commitment,
            context=context,
            hidden_seed=seed,
            nonce=nonce,
        )


def test_split_rejects_non_ascii_group_and_noncanonical_unit_order() -> None:
    with pytest.raises(ProtocolViolation, match="ASCII"):
        _split_unit(99, "患者族", 1)
    canonical = _split_units()
    units = tuple(reversed(canonical))
    context = _split_context()
    seed = bytes(32)
    nonce = bytes(range(32))
    with pytest.raises(ProtocolViolation, match="canonical digest order"):
        derive_panel_family_assignments(
            units,
            expected_commitment=compute_split_seed_commitment(context, seed, nonce),
            context=context,
            hidden_seed=seed,
            nonce=nonce,
        )


def test_split_unit_recomputes_digest_group_and_weight_from_exact_intent() -> None:
    unit = _split_unit(1, "group-a", 7)
    wire = unit.to_wire()
    assert unit.unit_intent_digest == unit.intent.unit_intent_digest
    assert unit.atomic_group_id == "group-a"
    assert unit.weight == 7
    assert _preimage_bytes(wire["unit_intent"]) == unit.unit_intent_bytes

    tampered = copy.deepcopy(unit.intent.to_wire())
    tampered["weight"] = 8
    with pytest.raises(ProtocolViolation, match="digest mismatch"):
        SplitDerivationUnit(canonical_json_bytes(tampered))
    with pytest.raises(ProtocolViolation, match="canonical"):
        SplitDerivationUnit(unit.unit_intent_bytes.rstrip(b"\n"))


def test_split_resigned_group_or_weight_change_cannot_verify_old_derivation() -> None:
    context = _split_context()
    units = _split_units()
    seed = bytes(range(32))
    nonce = bytes(range(32, 64))
    commitment = compute_split_seed_commitment(context, seed, nonce)
    original = derive_panel_family_assignments(
        units,
        expected_commitment=commitment,
        context=context,
        hidden_seed=seed,
        nonce=nonce,
    )
    intent = units[0].intent
    changed_intent = SplitNeutralFamilyUnitIntent(
        intent.family_unit_id,
        intent.family_definition,
        intent.generator_intent,
        "group-z" if intent.atomic_group_id != "group-z" else "group-y",
        intent.weight + 11,
    )
    changed_unit = SplitDerivationUnit(canonical_json_bytes(changed_intent.to_wire()))
    changed_units = tuple(
        sorted(
            (changed_unit, *units[1:]),
            key=lambda item: item.unit_intent_digest,
        )
    )
    with pytest.raises(ProtocolViolation, match="exact-replay"):
        verify_panel_family_assignments(
            original,
            changed_units,
            expected_commitment=commitment,
            context=context,
            hidden_seed=seed,
            nonce=nonce,
        )


def test_split_assignment_root_binds_full_ordered_input_set() -> None:
    result = split_derivation_known_answer()
    with pytest.raises(ProtocolViolation, match="input set root mismatch"):
        SplitAssignmentDerivation(
            result.commitment,
            result.commitment_context_digest,
            result.panel_identity_digest,
            result.panel_seed_digest,
            result.input_units,
            _sha("f"),
            result.assignments,
            result.assignment_root,
        )
    with pytest.raises(ProtocolViolation, match="canonical digest order"):
        SplitAssignmentDerivation(
            result.commitment,
            result.commitment_context_digest,
            result.panel_identity_digest,
            result.panel_seed_digest,
            tuple(reversed(result.input_units)),
            result.input_set_root,
            tuple(reversed(result.assignments)),
            result.assignment_root,
        )


def test_split_mutated_context_fails_typed_round_trip() -> None:
    context = _split_context()
    object.__setattr__(context, "commitment_stage", "after_family_assignment")
    with pytest.raises(ProtocolViolation, match="pre-assignment"):
        compute_split_seed_commitment(context, bytes(32), bytes(range(32)))


def test_source_closures_embed_exact_replay_bytes_and_owning_module() -> None:
    split_closure = _split_wire()["protocol"]["deterministic_derivation"][
        "source_closure"
    ]
    extension_closure = _extension_wire()["protocol"]["source_closure"]
    for closure in (split_closure, extension_closure):
        assert closure["raw_source_bytes_embedded"] is True
        assert closure["self_contained_replay"] is True
        assert closure["member_count"] == len(closure["members"])
        paths = [member["relative_path"] for member in closure["members"]]
        assert "prototype/unified_map/scope_transition_protocols.py" in paths
        assert {
            "prototype/unified_map/canonical.py",
            "prototype/unified_map/extensions.py",
            "prototype/unified_map/metric_configuration.py",
            "prototype/unified_map/metric_runtime_bindings.py",
            "prototype/unified_map/panel_split_authority.py",
            "prototype/unified_map/scope_manifest.py",
            "prototype/unified_map/seed_protocol.py",
            "prototype/unified_map/world_registry.py",
            "prototype/unified_map/worlds/w16.py",
            "prototype/unified_map/worlds/w17.py",
        }.issubset(paths)
        assert paths == sorted(set(paths))
        for member in closure["members"]:
            raw = base64.b64decode(member["payload_b64"], validate=True)
            assert raw == protocols._read_source_bytes(member["relative_path"])
            assert digest_bytes(raw) == member["digest"]
    with pytest.raises(TypeError):
        protocols._IMPORTED_SOURCE_BYTES["decoy.py"] = b"decoy"


def test_extension_templates_require_role_axis_and_bind_executable_D_contract() -> None:
    protocol = _extension_wire()["protocol"]
    by_world = {row["world_slot"]: row for row in protocol["templates"]}
    assert by_world["W16"]["required_changed_axes"] == ["Q"]
    assert by_world["W17"]["required_changed_axes"] == ["A"]
    assert by_world["W16"]["allowed_changed_axes"] == [
        "O",
        "Q",
        "Pi",
        "Gamma",
        "Y",
        "U",
        "R",
        "D",
    ]
    assert by_world["W17"]["allowed_changed_axes"] == ["A", "Pi", "U", "R", "D"]
    assert all(
        row["successor_axis_order"] == list(SCOPE_AXES) for row in by_world.values()
    )
    raw = _preimage_bytes(protocol["distance_derivation_contract"])
    assert raw == protocols.distance_derivation_contract_bytes()
    for row in by_world.values():
        assert row["distance_derivation_contract_digest"] == (
            protocols.distance_derivation_contract_digest()
        )
        spec_contract = _preimage_bytes(row["extension_scope_spec_contract"])
        assert b'"typed_spec_schema":"ucm-extension-scope-spec/1"' in spec_contract
        assert (
            b'"successor_deriver":"derive_successor_scope_from_spec"' in spec_contract
        )


def test_extension_template_declares_typed_seal_reveal_diff_receipt_and_full_S_prime() -> (
    None
):
    protocol = _extension_wire()["protocol"]
    gate = protocol["reveal_gate"]
    external = protocol["external_successor_artifacts"]
    assert gate["transition_seal_schema"] == EXTENSION_TRANSITION_SEAL_SCHEMA
    assert gate["scope_reveal_schema"] == EXTENSION_SCOPE_REVEAL_SCHEMA
    assert gate["primary_result_root_seal_required"] is True
    assert gate["primary_result_root_reveal_binding_required"] is True
    assert external["actual_scope_diff"]["schema_version"] == ACTUAL_SCOPE_DIFF_SCHEMA
    assert external["actual_scope_diff"]["parser"] == "parse_actual_scope_diff_bytes"
    assert external["actual_scope_diff"]["successor_axis_order"] == list(SCOPE_AXES)
    assert external["successor_receipt"]["schema_version"] == SUCCESSOR_RECEIPT_SCHEMA
    assert external["successor_receipt"]["parser"] == "parse_successor_receipt_bytes"
    assert (
        external["successor_receipt"]["scope_request_schema"]
        == EXTENSION_SCOPE_REQUEST_SCHEMA
    )
    assert (
        external["successor_receipt"]["scope_transcript_schema"]
        == EXTENSION_SCOPE_TRANSCRIPT_SCHEMA
    )
    assert (
        external["successor_receipt"]["scope_reveal_schema"]
        == EXTENSION_SCOPE_REVEAL_SCHEMA
    )
    assert external["successor_receipt"]["primary_aggregate_eligible"] is False
    assert external["successor_receipt"]["runtime_binding_status"] == (
        "successor_runtime_not_integrated"
    )


@pytest.mark.parametrize(
    ("world_slot", "changes", "expected"),
    (("W16", ("Q",), ("Q", "D")), ("W17", ("A",), ("A", "D"))),
)
def test_actual_scope_diff_round_trip_requires_full_exact_S_prime(
    world_slot: str, changes: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    diff = _actual_diff(world_slot, changes)
    assert diff.changed_axes == expected
    assert tuple(diff.successor_scope.axes) == SCOPE_AXES
    assert diff.base_scope.scope_digest != diff.successor_scope.scope_digest
    parsed = parse_actual_scope_diff_bytes(canonical_json_bytes(diff.to_wire()))
    assert parsed.to_wire() == diff.to_wire()


def test_extension_spec_round_trip_and_noop_patch_fail_closed() -> None:
    base = _scope("scope-S")
    spec = _extension_spec(base, "scope-S-prime", ("Q",))
    assert parse_extension_scope_spec_bytes(spec.canonical_bytes) == spec
    noop = ExtensionScopeSpec(
        "W16",
        base.scope_digest,
        "scope-S-prime",
        (ExtensionAxisPatch("Q", base.axes["Q"]),),
    )
    metric = benchmark_v1_metric_target_registry().canonical_bytes
    runtime = benchmark_v1_metric_runtime_bindings(metric).canonical_bytes
    with pytest.raises(ProtocolViolation, match="no-op"):
        derive_successor_scope_from_spec(base, noop, metric, runtime)


def test_successor_scope_deriver_requires_distinct_scope_id() -> None:
    base = _scope("scope-S")
    same_id_spec = _extension_spec(base, base.scope_id, ("Q",))
    metric = benchmark_v1_metric_target_registry().canonical_bytes
    runtime = benchmark_v1_metric_runtime_bindings(metric).canonical_bytes
    with pytest.raises(ProtocolViolation, match="distinct from base"):
        derive_successor_scope_from_spec(base, same_id_spec, metric, runtime)


def test_resigned_contradictory_extension_spec_cannot_reuse_successor() -> None:
    diff = _actual_diff()
    base = diff.base_scope
    contradictory = ExtensionScopeSpec(
        "W16",
        base.scope_digest,
        diff.successor_scope.scope_id,
        (
            ExtensionAxisPatch(
                "Q",
                ScopeAxisDeclarations(
                    (ScopeDeclaration("q-successor", {"axis": "Q", "v": 999}),)
                ),
            ),
        ),
    )
    with pytest.raises(ProtocolViolation, match="does not exact-replay"):
        ActualScopeDiff(
            diff.world_slot,
            diff.template_set_semantic_digest,
            contradictory.canonical_bytes,
            diff.base_scope_manifest_bytes,
            diff.successor_scope_manifest_bytes,
            diff.metric_registry_bytes,
            diff.metric_runtime_binding_bytes,
            diff.changed_axes,
        )


def test_distance_axis_binds_exact_changed_axis_values_not_only_ids() -> None:
    base = _scope("scope-S")
    metric = benchmark_v1_metric_target_registry().canonical_bytes
    runtime = benchmark_v1_metric_runtime_bindings(metric).canonical_bytes
    spec_a = _extension_spec(base, "scope-S-prime-a", ("Q",))
    scope_a = derive_successor_scope_from_spec(base, spec_a, metric, runtime)
    spec_b = ExtensionScopeSpec(
        "W16",
        base.scope_digest,
        "scope-S-prime-b",
        (
            ExtensionAxisPatch(
                "Q",
                ScopeAxisDeclarations(
                    (ScopeDeclaration("q-successor", {"axis": "Q", "v": 3}),)
                ),
            ),
        ),
    )
    scope_b = derive_successor_scope_from_spec(base, spec_b, metric, runtime)
    assert canonical_json_bytes(scope_a.axes["D"].to_wire()) != canonical_json_bytes(
        scope_b.axes["D"].to_wire()
    )
    value_a = next(
        item.value
        for item in scope_a.axes["D"].declarations
        if item.declaration_id == "extension-distance-derivation"
    )
    value_b = next(
        item.value
        for item in scope_b.axes["D"].declarations
        if item.declaration_id == "extension-distance-derivation"
    )
    assert value_a["actual_non_distance_diff"][0]["axis_id"] == "Q"
    assert (
        value_a["actual_non_distance_diff"][0]["successor_axis_digest"]
        != value_b["actual_non_distance_diff"][0]["successor_axis_digest"]
    )
    verify_successor_distance_axis(
        base,
        scope_a.axes["D"],
        ("Q",),
        (scope_a.axes["Q"],),
        metric,
        runtime,
    )


def test_actual_scope_diff_missing_required_axis_fails_closed() -> None:
    base = _scope("scope-S")
    with pytest.raises(ProtocolViolation, match="required changed axis"):
        _extension_spec(base, "scope-S-prime", ("O",))


def test_actual_scope_diff_axis_outside_template_fails_closed() -> None:
    base = _scope("scope-S")
    with pytest.raises(ProtocolViolation, match="outside template"):
        _extension_spec(base, "scope-S-prime", ("A", "Q"))


def test_actual_scope_diff_tampered_D_and_metric_runtime_mismatch_fail_closed() -> None:
    base = _scope("scope-S")
    spec = _extension_spec(base, "scope-S-prime", ("Q",))
    successor = _successor_scope(base, "scope-S-prime", ("Q",))
    axes = dict(successor.axes)
    axes["D"] = ScopeAxisDeclarations(
        tuple(
            sorted(
                (
                    *axes["D"].declarations,
                    ScopeDeclaration("tampered-distance", {"v": 999}),
                ),
                key=lambda item: item.declaration_id.encode("utf-8"),
            )
        )
    )
    tampered = ScopeManifest(base.benchmark_id, successor.scope_id, axes)
    with pytest.raises(ProtocolViolation, match="does not exact-replay"):
        ActualScopeDiff(
            "W16",
            build_extension_template_set().semantic_digest,
            spec.canonical_bytes,
            base.canonical_bytes,
            tampered.canonical_bytes,
            benchmark_v1_metric_target_registry().canonical_bytes,
            benchmark_v1_metric_runtime_bindings(
                benchmark_v1_metric_target_registry().canonical_bytes
            ).canonical_bytes,
            ("Q", "D"),
        )

    registry = copy.deepcopy(benchmark_v1_metric_target_registry().to_wire())
    registry["benchmark_status"] = "tampered"
    with pytest.raises(ProtocolViolation, match="code-owned"):
        build_actual_scope_diff(
            spec.canonical_bytes,
            base.canonical_bytes,
            canonical_json_bytes(registry),
        )

    metric = benchmark_v1_metric_target_registry().canonical_bytes
    runtime = copy.deepcopy(benchmark_v1_metric_runtime_bindings(metric).to_wire())
    runtime["benchmark_status"] = "tampered"
    with pytest.raises(ProtocolViolation, match="fresh code-owned truth"):
        build_actual_scope_diff(
            spec.canonical_bytes,
            base.canonical_bytes,
            metric,
            canonical_json_bytes(runtime),
        )


def test_successor_receipt_round_trip_exact_joins_and_primary_root_isolation() -> None:
    receipt = _receipt()
    parsed = parse_successor_receipt_bytes(canonical_json_bytes(receipt.to_wire()))
    assert parsed.to_wire() == receipt.to_wire()
    assert (
        len(
            {
                parsed.primary_result_root_before_extension,
                parsed.primary_result_root_after_extension,
                parsed.transition_seal.primary_result_root,
                parsed.reveal.primary_result_root,
            }
        )
        == 1
    )
    assert parsed.extension_result_namespace == "extension_only"
    assert parsed.primary_aggregate_eligible is False
    assert parsed.mixed_scope_aggregation == "forbidden"
    assert parsed.successor_runtime_trust_status == "UNVERIFIED_SUCCESSOR_RUNTIME"
    assert parsed.successor_runtime_eligible is False


def test_first_query_and_result_require_exact_typed_preimages() -> None:
    receipt = _receipt()
    query = receipt.request.first_query
    result = receipt.transcript.first_result
    assert parse_extension_first_query_bytes(query.canonical_bytes) == query
    assert parse_extension_first_result_bytes(result.canonical_bytes) == result
    with pytest.raises(ProtocolViolation, match="keys mismatch"):
        ExtensionFirstQueryEnvelope(
            query.world_slot,
            query.source_scope_digest,
            query.target_scope_digest,
            query.actual_scope_diff_digest,
            query.extension_spec_digest,
            query.primary_state_hash,
            canonical_json_bytes(
                {
                    "schema_version": "ucm-extension-state-only-readout-query/1",
                    "query_type": "extension_readout",
                    "readout_id": "readout-1",
                    "history": ["forbidden"],
                }
            ),
        )
    with pytest.raises(ProtocolViolation, match="cannot claim a prediction"):
        ExtensionFirstResultEnvelope(
            query.request_digest,
            "scope_insufficient",
            canonical_json_bytes({"prediction": 1}),
        )


def test_receipt_rejects_revealed_spec_cross_splice() -> None:
    receipt = _receipt()
    diff = receipt.actual_scope_diff
    base = diff.base_scope
    alternate_spec = ExtensionScopeSpec(
        "W16",
        base.scope_digest,
        diff.successor_scope.scope_id,
        (
            ExtensionAxisPatch(
                "Q",
                ScopeAxisDeclarations(
                    (ScopeDeclaration("q-successor", {"axis": "Q", "v": 999}),)
                ),
            ),
        ),
    )
    nonce = bytes(range(32))
    commitment = compute_extension_scope_commitment(
        "W16", alternate_spec.canonical_bytes, nonce
    )
    old_seal = receipt.transition_seal
    seal = ExtensionTransitionSeal(
        old_seal.world_slot,
        old_seal.template_set_semantic_digest,
        old_seal.source_scope_digest,
        commitment,
        old_seal.candidate_bundle_digest,
        old_seal.model_digest,
        old_seal.primary_state_hashes,
        old_seal.primary_state_root,
        old_seal.primary_state_snapshot_digest,
        old_seal.primary_result_root,
    )
    reveal = ExtensionScopeReveal(
        "W16",
        commitment,
        alternate_spec.canonical_bytes,
        nonce,
        seal.seal_digest,
        receipt.primary_result_root_before_extension,
    )
    request = ExtensionScopeRequest(
        "W16",
        seal.seal_digest,
        diff.diff_digest,
        diff.base_scope.scope_digest,
        diff.successor_scope.scope_digest,
        receipt.request.first_query_bytes,
    )
    result = ExtensionFirstResultEnvelope(
        request.request_digest,
        "ok",
        canonical_json_bytes({"prediction": 7}),
    )
    transcript = ExtensionScopeTranscript(
        request.request_digest,
        seal.seal_digest,
        diff.diff_digest,
        diff.base_scope.scope_digest,
        diff.successor_scope.scope_digest,
        result.canonical_bytes,
        False,
    )
    with pytest.raises(ProtocolViolation, match="reveal/spec/diff"):
        SuccessorReceipt(
            seal,
            reveal,
            diff,
            request,
            transcript,
            receipt.primary_result_root_before_extension,
            receipt.primary_result_root_after_extension,
            result.result_digest,
        )


def test_successor_receipt_source_target_and_request_transcript_mismatch_fail_closed() -> (
    None
):
    receipt = _receipt()
    wire = receipt.to_wire()
    wire["request"]["target_scope_digest"] = _sha("8")
    with pytest.raises(ProtocolViolation):
        parse_successor_receipt_bytes(canonical_json_bytes(wire))

    wire = receipt.to_wire()
    wire["primary_result_root_after_extension"] = _sha("9")
    wire.pop("receipt_digest")
    wire["receipt_digest"] = domain_digest(
        protocols.SUCCESSOR_RECEIPT_DOMAIN,
        (canonical_json_bytes(wire),),
    )
    with pytest.raises(ProtocolViolation, match="primary result root changed"):
        parse_successor_receipt_bytes(canonical_json_bytes(wire))

    receipt = _receipt()
    outside_query = ExtensionFirstQueryEnvelope(
        receipt.request.world_slot,
        receipt.request.source_scope_digest,
        receipt.request.target_scope_digest,
        receipt.request.actual_scope_diff_digest,
        receipt.actual_scope_diff.extension_spec.spec_digest,
        _sha("9"),
        canonical_json_bytes(
            {
                "schema_version": "ucm-extension-state-only-readout-query/1",
                "query_type": "extension_readout",
                "readout_id": "outside-state",
            }
        ),
    )
    mismatched_request = ExtensionScopeRequest(
        receipt.request.world_slot,
        receipt.request.transition_seal_digest,
        receipt.request.actual_scope_diff_digest,
        receipt.request.source_scope_digest,
        receipt.request.target_scope_digest,
        outside_query.canonical_bytes,
    )
    outside_result = ExtensionFirstResultEnvelope(
        mismatched_request.request_digest,
        "ok",
        canonical_json_bytes({"prediction": 7}),
    )
    mismatched_transcript = ExtensionScopeTranscript(
        mismatched_request.request_digest,
        receipt.transcript.transition_seal_digest,
        receipt.transcript.actual_scope_diff_digest,
        receipt.transcript.source_scope_digest,
        receipt.transcript.target_scope_digest,
        outside_result.canonical_bytes,
        False,
    )
    with pytest.raises(ProtocolViolation, match="sealed primary state set"):
        SuccessorReceipt(
            receipt.transition_seal,
            receipt.reveal,
            receipt.actual_scope_diff,
            mismatched_request,
            mismatched_transcript,
            receipt.primary_result_root_before_extension,
            receipt.primary_result_root_after_extension,
            receipt.extension_result_root,
        )


def test_receipt_revalidates_object_mutated_transition_components() -> None:
    receipt = _receipt()
    object.__setattr__(
        receipt.transition_seal,
        "primary_state_hashes",
        (*receipt.transition_seal.primary_state_hashes, _sha("9")),
    )
    with pytest.raises(ProtocolViolation, match="primary state root"):
        receipt.to_wire()


def test_extension_scope_insufficient_is_the_only_optional_migration_gate() -> None:
    receipt = _receipt()
    request = receipt.request
    insufficient_result = ExtensionFirstResultEnvelope(
        request.request_digest, "scope_insufficient", None
    )
    transcript = ExtensionScopeTranscript(
        request.request_digest,
        request.transition_seal_digest,
        request.actual_scope_diff_digest,
        request.source_scope_digest,
        request.target_scope_digest,
        insufficient_result.canonical_bytes,
        True,
    )
    scoped = SuccessorReceipt(
        receipt.transition_seal,
        receipt.reveal,
        receipt.actual_scope_diff,
        request,
        transcript,
        receipt.primary_result_root_before_extension,
        receipt.primary_result_root_after_extension,
        None,
    )
    assert scoped.transcript.migration_authorized is True
    with pytest.raises(ProtocolViolation, match="ok transcript"):
        ok_result = ExtensionFirstResultEnvelope(
            request.request_digest,
            "ok",
            canonical_json_bytes({"prediction": 8}),
        )
        ExtensionScopeTranscript(
            request.request_digest,
            request.transition_seal_digest,
            request.actual_scope_diff_digest,
            request.source_scope_digest,
            request.target_scope_digest,
            ok_result.canonical_bytes,
            True,
        )


def test_artifact_and_domain_digests_have_exact_preimages() -> None:
    assert SPLIT_DERIVATION_ARTIFACT_DIGEST == digest_bytes(
        SPLIT_DERIVATION_PROTOCOL_BYTES
    )
    assert SPLIT_DERIVATION_SEMANTIC_DIGEST == domain_digest(
        SPLIT_DERIVATION_DOMAIN, (SPLIT_DERIVATION_PROTOCOL_BYTES,)
    )
    assert EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST == digest_bytes(
        EXTENSION_TEMPLATE_SET_BYTES
    )
    assert EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST == domain_digest(
        EXTENSION_TEMPLATE_SET_DOMAIN, (EXTENSION_TEMPLATE_SET_BYTES,)
    )
    assert (
        split_derivation_artifact_digest_from_bytes(SPLIT_DERIVATION_PROTOCOL_BYTES)
        == SPLIT_DERIVATION_ARTIFACT_DIGEST
    )
    assert (
        split_derivation_semantic_digest_from_bytes(SPLIT_DERIVATION_PROTOCOL_BYTES)
        == SPLIT_DERIVATION_SEMANTIC_DIGEST
    )
    assert (
        extension_template_set_artifact_digest_from_bytes(EXTENSION_TEMPLATE_SET_BYTES)
        == EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST
    )
    assert (
        extension_template_set_semantic_digest_from_bytes(EXTENSION_TEMPLATE_SET_BYTES)
        == EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST
    )


@pytest.mark.parametrize(
    ("parser", "payload"),
    (
        (parse_split_derivation_protocol_bytes, SPLIT_DERIVATION_PROTOCOL_BYTES),
        (parse_extension_template_set_bytes, EXTENSION_TEMPLATE_SET_BYTES),
    ),
    ids=("split", "extension"),
)
def test_template_parsers_require_exact_canonical_bytes(parser, payload: bytes) -> None:
    with pytest.raises(ProtocolViolation, match="exact bytes"):
        parser({})
    with pytest.raises(ProtocolViolation, match="canonical"):
        parser(payload.rstrip(b"\n"))
    with pytest.raises(ProtocolViolation, match="duplicate key"):
        parser(payload.replace(b"{", b'{"schema_version":"duplicate",', 1))


def test_template_parsers_reject_tamper_resign_cross_splice_and_bool_int_alias() -> (
    None
):
    with pytest.raises(ProtocolViolation, match="code-owned"):
        parse_split_derivation_protocol_bytes(
            _split_mutation(
                lambda row: row["protocol"]["inventory_semantics"].__setitem__(
                    "panel_count", 20
                )
            )
        )
    with pytest.raises(ProtocolViolation, match="code-owned"):
        parse_extension_template_set_bytes(
            _extension_mutation(
                lambda row: row["protocol"]["reveal_gate"].__setitem__(
                    "all_primary_state_seals_required", 1
                )
            )
        )

    w16_contract = _extension_wire()["protocol"]["templates"][0][
        "extension_scope_spec_contract"
    ]
    with pytest.raises(ProtocolViolation, match="preimage drifted"):
        parse_extension_template_set_bytes(
            _extension_mutation(
                lambda row: row["protocol"]["templates"][1].__setitem__(
                    "extension_scope_spec_contract", w16_contract
                )
            )
        )


def test_invalid_and_resigned_embedded_preimages_fail_closed() -> None:
    def invalidate_base64(row: dict) -> None:
        preimage = row["protocol"]["deterministic_derivation"]["algorithm_source"]
        preimage["payload_b64"] = preimage["payload_b64"][:-1] + "!"

    with pytest.raises(ProtocolViolation, match="base64"):
        parse_split_derivation_protocol_bytes(_split_mutation(invalidate_base64))

    def resign_distance_contract(row: dict) -> None:
        preimage = row["protocol"]["distance_derivation_contract"]
        raw = base64.b64decode(preimage["payload_b64"], validate=True) + b" "
        preimage["payload_b64"] = base64.b64encode(raw).decode("ascii")
        preimage["byte_count"] = len(raw)
        preimage["digest"] = digest_bytes(raw)

    with pytest.raises(ProtocolViolation, match="preimage drifted"):
        parse_extension_template_set_bytes(
            _extension_mutation(resign_distance_contract)
        )


def test_to_wire_returns_fresh_nested_copies() -> None:
    split = build_split_derivation_protocol()
    split_wire = split.to_wire()
    split_wire["protocol"]["inventory_semantics"]["panel_count"] = 1
    assert split.to_wire()["protocol"]["inventory_semantics"]["panel_count"] == 21

    extension = build_extension_template_set()
    extension_wire = extension.to_wire()
    extension_wire["protocol"]["templates"][0]["required_changed_axes"].clear()
    assert extension.to_wire()["protocol"]["templates"][0]["required_changed_axes"] == [
        "Q"
    ]


def test_live_source_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = protocols._read_source_bytes

    def drift(relative_path: str) -> bytes:
        payload = original(relative_path)
        if relative_path == "prototype/unified_map/panel_split_authority.py":
            return payload + b"# drift\n"
        return payload

    monkeypatch.setattr(protocols, "_read_source_bytes", drift)
    with pytest.raises(ProtocolViolation, match="drifted"):
        build_split_derivation_protocol().canonical_bytes


def test_protocol_global_and_callable_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(protocols, "_SPLIT_SOURCE_PATHS", ("decoy.py",))
    with pytest.raises(ProtocolViolation, match="source-path control plane drifted"):
        build_split_derivation_protocol()
    monkeypatch.undo()

    monkeypatch.setattr(protocols, "_group_priority", lambda *_args: bytes(32))
    with pytest.raises(ProtocolViolation, match="control plane drifted"):
        build_split_derivation_protocol()


def test_live_dependency_function_class_and_constant_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        protocols._scope_manifest_module,
        "parse_scope_manifest_bytes",
        lambda payload: payload,
    )
    with pytest.raises(ProtocolViolation, match="runtime dependency surface drifted"):
        build_extension_template_set()
    monkeypatch.undo()

    monkeypatch.setattr(
        SplitNeutralFamilyUnitIntent,
        "from_wire",
        classmethod(lambda cls, value: value),
    )
    with pytest.raises(ProtocolViolation, match="runtime dependency surface drifted"):
        build_split_derivation_protocol()
    monkeypatch.undo()

    monkeypatch.setattr(protocols._extensions_module, "COMMIT_PROTOCOL", "drifted")
    with pytest.raises(ProtocolViolation, match="drifted"):
        build_extension_template_set()


def test_dependency_data_domain_and_function_metadata_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        protocols._panel_split_authority_module,
        "_UNIT_INTENT_DOMAIN",
        b"alternate-unit-domain\0",
    )
    with pytest.raises(ProtocolViolation, match="dependency data drifted"):
        compute_split_seed_commitment(_split_context(), bytes(32), bytes(range(32)))
    monkeypatch.undo()

    monkeypatch.setattr(
        protocols._extensions_module,
        "_COMMIT_DOMAIN",
        b"alternate-extension-domain\0",
    )
    with pytest.raises(ProtocolViolation, match="dependency data drifted"):
        build_extension_template_set()
    monkeypatch.undo()

    kwdefaults = protocols._canonical_module.validate_json_like.__kwdefaults__
    assert kwdefaults is not None
    monkeypatch.setitem(kwdefaults, "max_depth", 65)
    with pytest.raises(ProtocolViolation, match="runtime dependency surface drifted"):
        build_split_derivation_protocol()


def test_local_data_followup_and_final_cache_global_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(protocols, "DISTANCE_DERIVATION_SCHEMA", "alternate/1")
    with pytest.raises(ProtocolViolation, match="protocol constant"):
        build_extension_template_set()
    monkeypatch.undo()

    requirement = protocols._SPLIT_POST_SCOPE_REQUIREMENTS[0]
    original_detail = requirement.detail
    object.__setattr__(requirement, "detail", "mutated shared followup")
    try:
        with pytest.raises(ProtocolViolation, match="gap/followup"):
            build_split_derivation_protocol()
    finally:
        object.__setattr__(requirement, "detail", original_detail)

    alternate = canonical_json_bytes(
        {
            **_split_wire(),
            "authority_claim": "alternate-resigned-semantics",
        }
    )
    monkeypatch.setattr(protocols, "SPLIT_DERIVATION_PROTOCOL_BYTES", alternate)
    with pytest.raises(ProtocolViolation, match="cache/global"):
        build_split_derivation_protocol()


def test_final_cache_cannot_be_unsealed_and_resigned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = protocols._FINAL_ARTIFACT_CACHE
    original = (
        cache._sealed,
        cache._split_bytes,
        cache._split_artifact_digest,
        cache._split_semantic_digest,
        cache._extension_bytes,
        cache._extension_artifact_digest,
        cache._extension_semantic_digest,
    )
    evil_wire = _extension_wire()
    evil_wire["authority_claim"] = "attacker-resigned"
    evil = canonical_json_bytes(evil_wire)
    evil_artifact_digest = digest_bytes(evil)
    evil_semantic_digest = domain_digest(EXTENSION_TEMPLATE_SET_DOMAIN, (evil,))
    try:
        object.__setattr__(cache, "_sealed", False)
        cache.seal(
            SPLIT_DERIVATION_PROTOCOL_BYTES,
            SPLIT_DERIVATION_ARTIFACT_DIGEST,
            SPLIT_DERIVATION_SEMANTIC_DIGEST,
            evil,
            evil_artifact_digest,
            evil_semantic_digest,
        )
        monkeypatch.setattr(protocols, "EXTENSION_TEMPLATE_SET_BYTES", evil)
        monkeypatch.setattr(
            protocols,
            "EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST",
            evil_artifact_digest,
        )
        monkeypatch.setattr(
            protocols,
            "EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST",
            evil_semantic_digest,
        )
        with pytest.raises(ProtocolViolation, match="immutable closure"):
            build_extension_template_set()
    finally:
        for name, value in zip(
            (
                "_sealed",
                "_split_bytes",
                "_split_artifact_digest",
                "_split_semantic_digest",
                "_extension_bytes",
                "_extension_artifact_digest",
                "_extension_semantic_digest",
            ),
            original,
            strict=True,
        ):
            object.__setattr__(cache, name, value)


def test_exported_entrypoint_rejects_validator_global_rebind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(protocols, "_validate_executable_control_plane", lambda: None)
    with pytest.raises(ProtocolViolation, match="immutable closure"):
        build_extension_template_set()
