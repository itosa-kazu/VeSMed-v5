from __future__ import annotations

import json
from dataclasses import fields, replace

import pytest

import prototype.unified_map.family_manifest as family_manifest_module
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    domain_digest,
)
from prototype.unified_map.family_manifest import (
    AUTHORITY_ARTIFACT_SET_PROTOCOL,
    AtomicLinkDraft,
    AtomicLinkSemantic,
    BuilderRandomnessTranscript,
    FamilyMaterializationAuthorityArtifactSet,
    FamilyScaffoldStatus,
    FamilySplit,
    MaterializationReceiptLedger,
    MaterializationRole,
    MaterializationSlotDraft,
    MemberRefDraft,
    PairConstraintDraft,
    PairSemantic,
    PairSideDraft,
    PreSplitSourceUnit,
    ProducerSourceUnitDraft,
    RowMaterializationEvidence,
    SourceMemberDraft,
    SourceMemberSemantic,
    SourceUnitSemantic,
    UnitSplitAssignment,
    WeightedAtomicAssignment,
    audit_legacy_post_split_adapter,
    build_pre_split_family_source,
    build_materialization_receipt_ledger,
    build_weighted_atomic_assignment,
    compute_row_bundle_commitment,
    issue_materialization_receipt,
    issue_materialization_receipt_batch,
    parse_family_materialization_authority_artifact_set_bytes,
    parse_materialization_ledger_bytes,
    parse_materialization_receipt_bytes,
    parse_pre_split_family_source_bytes,
    parse_weighted_atomic_assignment_bytes,
)


def _member(
    alias: str,
    *,
    semantic: SourceMemberSemantic = SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
) -> SourceMemberDraft:
    return SourceMemberDraft(
        member_alias=alias,
        semantic_type=semantic,
        semantic_payload={"observation_path": [alias, 1], "clinical_value": 0.5},
    )


def _draft(
    alias: str,
    *,
    world: str = "W03",
    semantic: SourceUnitSemantic = SourceUnitSemantic.PATIENT_FAMILY,
    members: tuple[SourceMemberDraft, ...] | None = None,
    weight: int = 2,
) -> ProducerSourceUnitDraft:
    return ProducerSourceUnitDraft(
        unit_alias=alias,
        world_slot=world,
        semantic_type=semantic,
        recipe_payload={"recipe": "fixture", "cohort": "blind"},
        weight=weight,
        members=members or (_member("left"), _member("right")),
    )


def _transcript(alias: str, *, draw: float = 0.1) -> BuilderRandomnessTranscript:
    return BuilderRandomnessTranscript(
        unit_alias=alias,
        builder_id="fixture-authority-builder",
        builder_run_id="builder-run-001",
        latent_transcript={"draws": [draw], "stream": "latent"},
        noise_transcript={"draws": [draw + 0.1], "stream": "noise"},
        acquisition_transcript={"draws": [draw + 0.2], "stream": "acquisition"},
    )


def _source(
    drafts: tuple[ProducerSourceUnitDraft, ...],
    *,
    pairs: tuple[PairConstraintDraft, ...] = (),
    links: tuple[AtomicLinkDraft, ...] = (),
    slots: tuple[MaterializationSlotDraft, ...] = (),
    builder_version: str = "fixture-v2",
):
    return build_pre_split_family_source(
        benchmark_id="ucm-benchmark-v1",
        benchmark_revision="PRE-FREEZE-v1",
        registry_digest=_digest("registry"),
        generator_bundle_digest=_digest("generator-bundle"),
        topology_contract_digest=_digest("topology-contract"),
        query_contract_digest=_digest("query-contract"),
        builder_id="fixture-authority-builder",
        builder_version=builder_version,
        drafts=drafts,
        transcripts=tuple(
            _transcript(item.unit_alias, draw=(index + 1) / 10)
            for index, item in enumerate(drafts)
        ),
        pair_topology=pairs,
        atomic_links=links,
        materialization_slots=slots,
    )


def _producer_wire() -> dict:
    return {
        "unit_alias": "family-a",
        "world_slot": "W03",
        "semantic_type": "patient_family",
        "recipe_payload": {"recipe": "fixture"},
        "weight": 2,
        "members": [
            {
                "member_alias": "left",
                "semantic_type": "counterfactual_variant",
                "semantic_payload": {"value": 1},
            },
            {
                "member_alias": "right",
                "semantic_type": "counterfactual_variant",
                "semantic_payload": {"value": 2},
            },
        ],
    }


def _digest(label: str) -> str:
    return digest_json({"fixture": label})


def _row_bundle_fields(label: str) -> dict[str, str]:
    return {
        "record_id": f"record-{label}",
        "public_history_digest": _digest(f"history-{label}"),
        "hidden_state_at_cut_digest": _digest(f"hidden-{label}"),
        "oracle_target_digest": _digest(f"oracle-{label}"),
        "candidate_row_digest": _digest(f"candidate-{label}"),
        "judge_row_digest": _digest(f"judge-{label}"),
        "raw_request_digest": _digest(f"request-{label}"),
        "raw_response_digest": _digest(f"response-{label}"),
    }


def _row_bundle_commitment(label: str, **overrides: str) -> str:
    fields = _row_bundle_fields(label)
    fields.update(overrides)
    return compute_row_bundle_commitment(**fields)


SPLIT_POLICY_DIGEST = _digest("split-policy")
SPLIT_SEED_COMMITMENT = _digest("split-seed-commitment")


def _assignment(source, split_by_authority_digest):
    return build_weighted_atomic_assignment(
        source,
        split_by_authority_digest,
        split_policy_digest=SPLIT_POLICY_DIGEST,
        split_seed_commitment=SPLIT_SEED_COMMITMENT,
    )


def _evidence(source, split: FamilySplit = FamilySplit.TRAIN):
    unit = source.units[0]
    return RowMaterializationEvidence(
        record_id="r-fixture-0001",
        assigned_split=split,
        authority_digest=unit.authority_digest,
        member_digest=unit.members[0].member_digest,
        public_history_digest=_digest("history"),
        hidden_state_at_cut_digest=_digest("hidden-state"),
        query_cell_digest=_digest("query"),
        oracle_target_digest=_digest("oracle"),
        candidate_row_digest=_digest("candidate-row"),
        judge_row_digest=_digest("judge-row"),
        raw_request_digest=_digest("raw-request"),
        raw_response_digest=_digest("raw-response"),
    )


def _w19_drafts(
    count: int = 64,
    *,
    prefix: str = "w19-family",
) -> tuple[ProducerSourceUnitDraft, ...]:
    return tuple(
        _draft(
            f"{prefix}-{index:02d}",
            world="W19",
            members=(
                _member(
                    "assignment-row",
                    semantic=SourceMemberSemantic.W19_ASSIGNMENT_ROW,
                ),
            ),
            weight=1,
        )
        for index in range(count)
    )


def _w19_cluster(
    drafts: tuple[ProducerSourceUnitDraft, ...],
    *,
    alias: str = "w19-quota-cluster",
) -> AtomicLinkDraft:
    return AtomicLinkDraft(
        alias,
        AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER,
        tuple(MemberRefDraft(item.unit_alias, "assignment-row") for item in drafts),
    )


def _w19_slots(
    drafts: tuple[ProducerSourceUnitDraft, ...],
) -> tuple[MaterializationSlotDraft, ...]:
    return tuple(
        MaterializationSlotDraft(
            f"w19-slot-{index:02d}",
            draft.unit_alias,
            "assignment-row",
            MaterializationRole.W19_ASSIGNMENT_ROW,
            "quota-assignment",
            _digest(f"w19-cut-{index:02d}"),
            _digest("w19-query-cell"),
            atomic_link_alias="w19-quota-cluster",
            row_bundle_commitment_digest=_row_bundle_commitment(
                f"w19-slot-{index:02d}"
            ),
        )
        for index, draft in enumerate(drafts)
    )


def _closed_slot_source(
    *,
    duplicate_followup_record: bool = False,
    builder_version: str = "fixture-v2",
):
    draft = _draft(
        "family-slots",
        members=(
            _member("left"),
            _member("right"),
            _member(
                "unmaterialized",
                semantic=SourceMemberSemantic.PATIENT_TRAJECTORY,
            ),
        ),
        weight=4,
    )
    pair = PairConstraintDraft(
        "counterfactual-pair",
        PairSemantic.COUNTERFACTUAL,
        (
            PairSideDraft("family-slots", "left", 0),
            PairSideDraft("family-slots", "right", 1),
        ),
    )
    slots = (
        # Two rows for one source member make the multiplicity explicit rather
        # than silently assuming one materialized row per member.
        MaterializationSlotDraft(
            "left-baseline",
            "family-slots",
            "left",
            MaterializationRole.STANDARD_ROW,
            "baseline",
            _digest("cut-left-baseline"),
            _digest("query-left-baseline"),
            row_bundle_commitment_digest=_row_bundle_commitment("left-baseline"),
        ),
        MaterializationSlotDraft(
            "left-followup",
            "family-slots",
            "left",
            MaterializationRole.STANDARD_ROW,
            "followup",
            _digest("cut-left-followup"),
            _digest("query-left-followup"),
            row_bundle_commitment_digest=_row_bundle_commitment(
                "left-followup",
                **(
                    {"record_id": "record-left-baseline"}
                    if duplicate_followup_record
                    else {}
                ),
            ),
        ),
        MaterializationSlotDraft(
            "pair-side-0",
            "family-slots",
            "left",
            MaterializationRole.PAIR_SIDE,
            "counterfactual-readout",
            _digest("cut-pair"),
            _digest("query-pair"),
            pair_alias="counterfactual-pair",
            pair_side=0,
            row_bundle_commitment_digest=_row_bundle_commitment("pair-side-0"),
        ),
        MaterializationSlotDraft(
            "pair-side-1",
            "family-slots",
            "right",
            MaterializationRole.PAIR_SIDE,
            "counterfactual-readout",
            _digest("cut-pair"),
            _digest("query-pair"),
            pair_alias="counterfactual-pair",
            pair_side=1,
            row_bundle_commitment_digest=_row_bundle_commitment("pair-side-1"),
        ),
    )
    return _source(
        (draft,), pairs=(pair,), slots=slots, builder_version=builder_version
    )


def _slot_evidence(source, assignment, slot_index: int) -> RowMaterializationEvidence:
    slot = source.materialization_slots[slot_index]
    # ``assignment`` has already crossed its public constructor boundary.
    # Avoid revalidating the complete 64-family W19 graph once per fixture row;
    # receipt issuance still performs the authoritative full validation.
    assigned = next(
        (
            item
            for item in assignment.assignments
            if item.authority_digest == slot.reference.authority_digest
        ),
        None,
    )
    assert assigned is not None
    label = slot.slot_alias
    row_bundle = _row_bundle_fields(label)
    return RowMaterializationEvidence(
        record_id=row_bundle["record_id"],
        assigned_split=assigned.assigned_split,
        authority_digest=slot.reference.authority_digest,
        member_digest=slot.reference.member_digest,
        public_history_digest=row_bundle["public_history_digest"],
        hidden_state_at_cut_digest=row_bundle["hidden_state_at_cut_digest"],
        query_cell_digest=slot.query_cell_digest,
        oracle_target_digest=row_bundle["oracle_target_digest"],
        candidate_row_digest=row_bundle["candidate_row_digest"],
        judge_row_digest=row_bundle["judge_row_digest"],
        raw_request_digest=row_bundle["raw_request_digest"],
        raw_response_digest=row_bundle["raw_response_digest"],
        materialization_slot_digest=slot.slot_digest,
        cut_digest=slot.cut_digest,
        stage_label=slot.stage_label,
        materialization_role=slot.materialization_role,
        pair_digest=slot.pair_digest,
        pair_side=slot.pair_side,
        atomic_link_digest=slot.atomic_link_digest,
    )


def _exact_authority_graph(
    *,
    split: FamilySplit = FamilySplit.TRAIN,
    builder_version: str = "fixture-v2",
):
    source = _closed_slot_source(builder_version=builder_version)
    assignment = _assignment(
        source, {source.units[0].authority_digest: split}
    )
    receipts = issue_materialization_receipt_batch(
        source,
        assignment,
        tuple(
            _slot_evidence(source, assignment, index)
            for index in range(len(source.materialization_slots))
        ),
    )
    ledger = build_materialization_receipt_ledger(source, assignment, receipts)
    return source, assignment, receipts, ledger


def _exact_authority_preimages(
    *,
    split: FamilySplit = FamilySplit.TRAIN,
    builder_version: str = "fixture-v2",
):
    source, assignment, receipts, ledger = _exact_authority_graph(
        split=split, builder_version=builder_version
    )
    return (
        source,
        assignment,
        receipts,
        ledger,
        canonical_json_bytes(source.to_wire()),
        canonical_json_bytes(assignment.to_wire()),
        canonical_json_bytes(ledger.to_wire()),
    )


def test_producer_cannot_forge_or_smuggle_family_digest() -> None:
    good = ProducerSourceUnitDraft.from_wire(_producer_wire())
    assert good.unit_alias == "family-a"

    forged = _producer_wire()
    forged["family_digest"] = _digest("producer-forgery")
    with pytest.raises(ProtocolViolation, match="judge-private field"):
        ProducerSourceUnitDraft.from_wire(forged)

    nested = _producer_wire()
    nested["recipe_payload"] = {
        "nested": {"familyDigest": _digest("camel-case-forgery")}
    }
    with pytest.raises(ProtocolViolation, match="judge-private field"):
        ProducerSourceUnitDraft.from_wire(nested)


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "schema_version",
        "blockers",
        "status",
        "freeze_grade_evidence",
        "freezeGradeEvidence",
        "benchmark_freeze_eligible",
        "benchmark_id",
        "benchmark_revision",
        "authority_origin",
        "authorityRole",
        "authority-scope-digest",
        "split",
        "split_policy_digest",
        "splitSeedCommitment",
        "record_id",
        "case_key",
        "generator_seed",
        "master_seed",
        "noise_seed",
        "population_index",
        "randomness_transcript",
        "builder-run-id",
        "builder_version",
        "latent_transcript",
        "registry_digest",
        "generatorBundleDigest",
        "topology-contract-digest",
        "query_contract_digest",
        "assignment_cluster_digests",
        "authority_digests",
        "split_weight_totals",
        "preSplitSource",
        "assignments",
        "connectedComponents",
        "materialization-receipts",
        "family_identity",
        "randomnessIdentity",
        "input_digest",
        "rowJoin",
        "row_count",
        "total-weight",
        "units",
        "pair_topology",
        "atomicLinks",
        "candidate_row_digest",
        "rawResponseDigest",
        "receipt_digest",
        "materialization_slots",
        "materializationSlotDigest",
        "slot_digest",
        "cutDigest",
        "stage_label",
        "materialization_role",
        "pair_alias",
        "pairSide",
        "atomic_link_alias",
        "atomicLinkDigest",
        "row_bundle_commitment_digest",
        "strataAllocationCommitmentDigest",
        "member_coverage",
        "ledger_digest",
    ],
)
def test_pre_split_source_rejects_post_split_or_seed_fields(forbidden_key: str) -> None:
    wire = _producer_wire()
    wire["members"][0]["semantic_payload"] = {
        "nested": {forbidden_key: "forbidden"}
    }
    with pytest.raises(ProtocolViolation, match="judge-private field"):
        ProducerSourceUnitDraft.from_wire(wire)


def test_alpha_renaming_and_builder_run_metadata_cannot_create_a_new_family() -> None:
    semantic_left = {
        "observation_path": ["shared-clinical-path", 1],
        "clinical_value": 0.25,
    }
    semantic_right = {
        "observation_path": ["shared-clinical-path", 2],
        "clinical_value": 0.75,
    }
    draft_a = _draft(
        "producer-family-a",
        members=(
            SourceMemberDraft(
                "producer-left-a",
                SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
                semantic_left,
            ),
            SourceMemberDraft(
                "producer-right-a",
                SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
                semantic_right,
            ),
        ),
        weight=2,
    )
    draft_b = _draft(
        "renamed-family-b",
        members=(
            SourceMemberDraft(
                "renamed-right-b",
                SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
                semantic_right,
            ),
            SourceMemberDraft(
                "renamed-left-b",
                SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
                semantic_left,
            ),
        ),
        # Allocation weight is not patient identity.
        weight=99,
    )
    transcript_a = _transcript("producer-family-a", draw=0.4)
    transcript_b = replace(
        _transcript("renamed-family-b", draw=0.4),
        builder_run_id="renamed-run-999",
    )

    with pytest.raises(ProtocolViolation, match="authority digests must be unique"):
        build_pre_split_family_source(
            benchmark_id="ucm-benchmark-v1",
            benchmark_revision="PRE-FREEZE-v1",
            registry_digest=_digest("registry"),
            generator_bundle_digest=_digest("generator-bundle"),
            topology_contract_digest=_digest("topology-contract"),
            query_contract_digest=_digest("query-contract"),
            builder_id="fixture-authority-builder",
            builder_version="fixture-v2",
            drafts=(draft_a, draft_b),
            transcripts=(transcript_a, transcript_b),
        )


def test_one_family_rejects_duplicate_semantic_members_hidden_by_aliases() -> None:
    duplicate_payload = {"clinical_value": 0.5, "path": ["same", 1]}
    draft = _draft(
        "family-a",
        members=(
            SourceMemberDraft(
                "first-alias",
                SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
                duplicate_payload,
            ),
            SourceMemberDraft(
                "second-alias",
                SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
                duplicate_payload.copy(),
            ),
        ),
    )
    with pytest.raises(ProtocolViolation, match="duplicate semantic members"):
        _source((draft,))


def test_builder_derives_authority_from_all_three_randomness_transcripts() -> None:
    draft = _draft("family-a")
    source_a = _source((draft,))
    source_b = build_pre_split_family_source(
        benchmark_id="ucm-benchmark-v1",
        benchmark_revision="PRE-FREEZE-v1",
        registry_digest=_digest("registry"),
        generator_bundle_digest=_digest("generator-bundle"),
        topology_contract_digest=_digest("topology-contract"),
        query_contract_digest=_digest("query-contract"),
        builder_id="fixture-authority-builder",
        builder_version="fixture-v2",
        drafts=(draft,),
        transcripts=(_transcript("family-a", draw=0.9),),
    )

    assert source_a.units[0].authority_digest != source_b.units[0].authority_digest
    with pytest.raises(ProtocolViolation, match="authority scope is stale"):
        replace(source_a, generator_bundle_digest=_digest("stale-generator"))
    wire = source_a.to_wire()
    transcript = wire["units"][0]["randomness_transcript"]
    assert transcript["owner_role"] == "authority_builder"
    assert set(
        key
        for key in transcript
        if key.endswith("_transcript")
    ) == {"latent_transcript", "noise_transcript", "acquisition_transcript"}
    assert wire["status"] == "pre_freeze_scaffold"
    assert wire["freeze_grade_evidence"] is False
    assert wire["benchmark_freeze_eligible"] is False


def test_forged_resolved_authority_and_member_digests_are_rejected() -> None:
    unit = _source((_draft("family-a"),)).units[0]
    with pytest.raises(ProtocolViolation, match="not builder-derived"):
        replace(unit, authority_digest=_digest("forged-authority"))

    forged_member = replace(unit.members[0], member_digest=_digest("forged-member"))
    with pytest.raises(ProtocolViolation, match="not builder-derived"):
        PreSplitSourceUnit(
            unit_alias=unit.unit_alias,
            world_slot=unit.world_slot,
            semantic_type=unit.semantic_type,
            recipe_payload=unit.recipe_payload,
            weight=unit.weight,
            authority_scope_digest=unit.authority_scope_digest,
            randomness_transcript=unit.randomness_transcript,
            members=(forged_member, unit.members[1]),
            authority_digest=unit.authority_digest,
        )


def test_topology_rejects_missing_member_and_duplicate_aliases() -> None:
    drafts = (_draft("family-a"), _draft("family-b"))
    missing = PairConstraintDraft(
        "pair-missing",
        PairSemantic.COUNTERFACTUAL,
        (
            PairSideDraft("family-a", "left", 0),
            PairSideDraft("family-a", "does-not-exist", 1),
        ),
    )
    with pytest.raises(ProtocolViolation, match="missing member"):
        _source(drafts, pairs=(missing,))

    pair = PairConstraintDraft(
        "pair-duplicate-alias",
        PairSemantic.COUNTERFACTUAL,
        (
            PairSideDraft("family-a", "left", 0),
            PairSideDraft("family-a", "right", 1),
        ),
    )
    duplicate_alias = replace(pair)
    with pytest.raises(ProtocolViolation, match="aliases must be unique"):
        _source(drafts, pairs=(pair, duplicate_alias))


def test_topology_rejects_duplicate_pair_or_atomic_group_content() -> None:
    drafts = (_draft("family-a"), _draft("family-b"))
    pair_a = PairConstraintDraft(
        "pair-a",
        PairSemantic.COUNTERFACTUAL,
        (
            PairSideDraft("family-a", "left", 0),
            PairSideDraft("family-a", "right", 1),
        ),
    )
    pair_b = replace(pair_a, pair_alias="pair-b")
    with pytest.raises(ProtocolViolation, match="duplicate pair topology"):
        _source(drafts, pairs=(pair_a, pair_b))

    link_a = AtomicLinkDraft(
        "link-a",
        AtomicLinkSemantic.QUOTA_CLUSTER,
        (
            MemberRefDraft("family-a", "left"),
            MemberRefDraft("family-b", "right"),
        ),
    )
    link_b = replace(link_a, link_alias="link-b")
    with pytest.raises(ProtocolViolation, match="duplicate atomic link topology"):
        _source(drafts, links=(link_a, link_b))


def test_pair_topology_requires_both_unique_sides() -> None:
    with pytest.raises(ProtocolViolation, match="exactly sides 0 and 1"):
        PairConstraintDraft(
            "one-sided",
            PairSemantic.BEHAVIORAL,
            (PairSideDraft("family-a", "left", 0),),
        )
    with pytest.raises(ProtocolViolation, match="exactly sides 0 and 1"):
        PairConstraintDraft(
            "duplicate-side",
            PairSemantic.BEHAVIORAL,
            (
                PairSideDraft("family-a", "left", 0),
                PairSideDraft("family-a", "right", 0),
            ),
        )
    with pytest.raises(ProtocolViolation, match="distinct members"):
        PairConstraintDraft(
            "same-member",
            PairSemantic.BEHAVIORAL,
            (
                PairSideDraft("family-a", "left", 0),
                PairSideDraft("family-a", "left", 1),
            ),
        )


def test_pair_cannot_cross_family_or_split() -> None:
    drafts = (_draft("family-a"), _draft("family-b"))
    with pytest.raises(ProtocolViolation, match="same pre-split family"):
        PairConstraintDraft(
            "cross-family-pair",
            PairSemantic.COUNTERFACTUAL,
            (
                PairSideDraft("family-a", "left", 0),
                PairSideDraft("family-b", "right", 1),
            ),
        )

    pair = PairConstraintDraft(
        "in-family-pair",
        PairSemantic.COUNTERFACTUAL,
        (
            PairSideDraft("family-a", "left", 0),
            PairSideDraft("family-a", "right", 1),
        ),
    )
    pair_slots = (
        MaterializationSlotDraft(
            "family-a-pair-0",
            "family-a",
            "left",
            MaterializationRole.PAIR_SIDE,
            "pair-readout",
            _digest("family-a-pair-cut"),
            _digest("family-a-pair-query"),
            pair_alias="in-family-pair",
            pair_side=0,
            row_bundle_commitment_digest=_row_bundle_commitment(
                "family-a-pair-0"
            ),
        ),
        MaterializationSlotDraft(
            "family-a-pair-1",
            "family-a",
            "right",
            MaterializationRole.PAIR_SIDE,
            "pair-readout",
            _digest("family-a-pair-cut"),
            _digest("family-a-pair-query"),
            pair_alias="in-family-pair",
            pair_side=1,
            row_bundle_commitment_digest=_row_bundle_commitment(
                "family-a-pair-1"
            ),
        ),
    )
    source = _source(drafts, pairs=(pair,), slots=pair_slots)
    assignment = _assignment(
        source,
        {
            source.units[0].authority_digest: FamilySplit.TRAIN,
            source.units[1].authority_digest: FamilySplit.SEALED_TEST,
        },
    )
    side_one = replace(
        _slot_evidence(source, assignment, 1),
        assigned_split=FamilySplit.SEALED_TEST,
    )
    with pytest.raises(ProtocolViolation, match="does not match"):
        issue_materialization_receipt(source, assignment, side_one)


def test_generic_atomic_connected_component_cannot_cross_split() -> None:
    drafts = (_draft("family-a", weight=3), _draft("family-b", weight=5))
    link = AtomicLinkDraft(
        "s0-s1-release",
        AtomicLinkSemantic.CUT_SET,
        (
            MemberRefDraft("family-a", "left"),
            MemberRefDraft("family-b", "right"),
        ),
    )
    source = _source(drafts, links=(link,))
    with pytest.raises(ProtocolViolation, match="cannot be divided across splits"):
        WeightedAtomicAssignment(
            source=source,
            split_policy_digest=SPLIT_POLICY_DIGEST,
            split_seed_commitment=SPLIT_SEED_COMMITMENT,
            assignments=(
                UnitSplitAssignment(
                    source.units[0].authority_digest, FamilySplit.TRAIN, 3
                ),
                UnitSplitAssignment(
                    source.units[1].authority_digest, FamilySplit.VALIDATION, 5
                ),
            ),
        )

    assignment = _assignment(
        source,
        {
            source.units[0].authority_digest: FamilySplit.SEALED_TEST,
            source.units[1].authority_digest: FamilySplit.SEALED_TEST,
        },
    )
    assert len(assignment.components) == 1
    assert assignment.components[0].total_weight == 8
    assert assignment.to_wire()["split_weight_totals"] == {
        "train": 0,
        "validation": 0,
        "sealed_test": 8,
    }
    assert assignment.to_wire()["freeze_grade_evidence"] is False


def test_assignment_rejects_missing_duplicate_and_reweighted_units() -> None:
    source = _source((_draft("family-a", weight=7),))
    unit = source.units[0]
    with pytest.raises(ProtocolViolation, match="must not be empty"):
        WeightedAtomicAssignment(
            source,
            SPLIT_POLICY_DIGEST,
            SPLIT_SEED_COMMITMENT,
            (),
        )
    duplicate = UnitSplitAssignment(unit.authority_digest, FamilySplit.TRAIN, 7)
    with pytest.raises(ProtocolViolation, match="duplicate"):
        WeightedAtomicAssignment(
            source,
            SPLIT_POLICY_DIGEST,
            SPLIT_SEED_COMMITMENT,
            (duplicate, duplicate),
        )
    with pytest.raises(ProtocolViolation, match="weight does not match"):
        WeightedAtomicAssignment(
            source,
            SPLIT_POLICY_DIGEST,
            SPLIT_SEED_COMMITMENT,
            (UnitSplitAssignment(unit.authority_digest, FamilySplit.TRAIN, 99),),
        )


def test_w19_assignment_cluster_is_not_a_patient_family() -> None:
    families = _w19_drafts()
    cluster = _w19_cluster(families)
    source = _source(families, links=(cluster,), slots=_w19_slots(families))
    assert len(source.atomic_links[0].members) == 64
    assert len({item.authority_digest for item in source.units}) == 64
    assert all(
        unit.to_wire()["semantic_type"] == "patient_family" for unit in source.units
    )
    assert all(
        unit.to_wire()["family_digest"] == unit.authority_digest
        for unit in source.units
    )
    cluster_wire = source.atomic_links[0].to_wire()
    assert cluster_wire["semantic_type"] == "w19_assignment_cluster"
    assert cluster_wire["assignment_cluster_digest"] == cluster_wire["link_digest"]
    assert cluster_wire["link_digest"] not in {
        unit.authority_digest for unit in source.units
    }
    with pytest.raises(ProtocolViolation, match="cannot be divided across splits"):
        _assignment(
            source,
            {
                unit.authority_digest: (
                    FamilySplit.SEALED_TEST if index == 63 else FamilySplit.TRAIN
                )
                for index, unit in enumerate(source.units)
            },
        )
    assignment = _assignment(
        source,
        {unit.authority_digest: FamilySplit.TRAIN for unit in source.units},
    )
    receipt = issue_materialization_receipt(
        source, assignment, _slot_evidence(source, assignment, 0)
    )
    assert receipt.to_wire()["assignment_cluster_digests"] == [
        cluster_wire["link_digest"]
    ]

    with pytest.raises(ProtocolViolation, match="topology is incomplete"):
        _source(families)

    short_families = _w19_drafts(63)
    with pytest.raises(ProtocolViolation, match="exactly 64"):
        _source(short_families, links=(_w19_cluster(short_families),))

    long_families = _w19_drafts(65)
    with pytest.raises(ProtocolViolation, match="exactly 64"):
        _source(long_families, links=(_w19_cluster(long_families),))

    with pytest.raises(ProtocolViolation, match="only one assignment row"):
        _draft(
            "w19-family-duplicate",
            world="W19",
            members=(
                _member(
                    "assignment-row-a",
                    semantic=SourceMemberSemantic.W19_ASSIGNMENT_ROW,
                ),
                _member(
                    "assignment-row-b",
                    semantic=SourceMemberSemantic.W19_ASSIGNMENT_ROW,
                ),
            ),
            weight=1,
        )
    with pytest.raises(ProtocolViolation, match="weight must be 1"):
        _draft(
            "w19-weighted-family",
            world="W19",
            members=(
                _member(
                    "assignment-row",
                    semantic=SourceMemberSemantic.W19_ASSIGNMENT_ROW,
                ),
            ),
            weight=99,
        )

    ordinary = tuple(_draft(f"ordinary-{index:02d}") for index in range(64))
    wrong_cluster = AtomicLinkDraft(
        "wrong-w19-cluster",
        AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER,
        tuple(MemberRefDraft(item.unit_alias, "left") for item in ordinary),
    )
    with pytest.raises(ProtocolViolation, match="typed rows"):
        _source(ordinary, links=(wrong_cluster,))

    resolved_cluster = source.atomic_links[0]
    object.__setattr__(resolved_cluster, "members", resolved_cluster.members[:-1])
    with pytest.raises(ProtocolViolation, match="exactly 64"):
        source.to_wire()


def test_w19_cluster_cannot_be_bridged_to_cluster_or_foreign_world() -> None:
    cluster_a_families = _w19_drafts(prefix="w19-cluster-a-family")
    cluster_b_families = _w19_drafts(prefix="w19-cluster-b-family")
    cluster_a = _w19_cluster(cluster_a_families, alias="w19-cluster-a")
    cluster_b = _w19_cluster(cluster_b_families, alias="w19-cluster-b")
    cross_cluster_bridge = AtomicLinkDraft(
        "cross-cluster-bridge",
        AtomicLinkSemantic.CUT_SET,
        (
            MemberRefDraft(cluster_a_families[0].unit_alias, "assignment-row"),
            MemberRefDraft(cluster_b_families[0].unit_alias, "assignment-row"),
        ),
    )
    with pytest.raises(ProtocolViolation, match="cannot be bridged"):
        _source(
            (*cluster_a_families, *cluster_b_families),
            links=(cluster_a, cluster_b, cross_cluster_bridge),
        )

    foreign = _draft("w18-foreign-family", world="W18")
    cross_world_bridge = AtomicLinkDraft(
        "cross-world-bridge",
        AtomicLinkSemantic.CUT_SET,
        (
            MemberRefDraft(cluster_a_families[0].unit_alias, "assignment-row"),
            MemberRefDraft(foreign.unit_alias, "left"),
        ),
    )
    with pytest.raises(ProtocolViolation, match="cannot be bridged"):
        _source(
            (*cluster_a_families, foreign),
            links=(cluster_a, cross_world_bridge),
        )


def test_closed_w19_inventory_requires_exactly_one_slot_per_each_of_64_rows() -> None:
    families = _w19_drafts()
    cluster = _w19_cluster(families)
    slots = _w19_slots(families)
    with pytest.raises(ProtocolViolation, match="exactly one slot"):
        _source(families, links=(cluster,), slots=slots[:-1])
    duplicate_first = replace(
        slots[0],
        slot_alias="w19-slot-duplicate-first",
        stage_label="quota-assignment-duplicate",
        cut_digest=_digest("w19-cut-duplicate-first"),
    )
    with pytest.raises(ProtocolViolation, match="exactly one slot"):
        _source(
            families,
            links=(cluster,),
            slots=(*slots, duplicate_first),
        )

    source = _source(families, links=(cluster,), slots=slots)
    assert len(source.materialization_slots) == 64
    counts: dict[tuple[str, str], int] = {}
    for slot in source.materialization_slots:
        reference = (
            slot.reference.authority_digest,
            slot.reference.member_digest,
        )
        counts[reference] = counts.get(reference, 0) + 1
    assert len(counts) == 64
    assert set(counts.values()) == {1}


def test_w19_batch_receipts_exactly_cover_all_64_typed_assignment_rows() -> None:
    families = _w19_drafts()
    source = _source(
        families,
        links=(_w19_cluster(families),),
        slots=_w19_slots(families),
    )
    assignment = _assignment(
        source,
        {
            unit.authority_digest: FamilySplit.SEALED_TEST
            for unit in source.units
        },
    )
    evidences = tuple(
        _slot_evidence(source, assignment, index)
        for index in range(len(source.materialization_slots))
    )
    receipts = issue_materialization_receipt_batch(
        source,
        assignment,
        evidences,
    )
    ledger = build_materialization_receipt_ledger(source, assignment, receipts)
    wire = ledger.to_wire()

    assert len(receipts) == 64
    assert wire["declared_slot_count"] == 64
    assert wire["receipt_count"] == 64
    assert len(wire["member_coverage"]) == 64
    assert {len(item["entries"]) for item in wire["member_coverage"]} == {1}
    assert {
        item["row_join"]["materialization_role"] for item in wire["receipts"]
    } == {"w19_assignment_row"}

    swapped_cut = replace(evidences[1], cut_digest=evidences[0].cut_digest)
    with pytest.raises(ProtocolViolation, match="cut does not match"):
        issue_materialization_receipt_batch(
            source,
            assignment,
            (evidences[0], swapped_cut, *evidences[2:]),
        )

    # Batch construction is only a parent-validation optimization; each child
    # retains its own sealed evidence and receipt integrity boundary.
    rewritten_evidence = replace(
        receipts[0].evidence,
        public_history_digest=_digest("batch-post-construction-rewrite"),
    )
    object.__setattr__(receipts[0], "evidence", rewritten_evidence)
    with pytest.raises(ProtocolViolation, match="row bundle commitment"):
        receipts[0].to_wire()


def test_batch_receipts_match_individual_api_and_revalidate_parent_authority() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    evidences = tuple(
        _slot_evidence(source, assignment, index)
        for index in range(len(source.materialization_slots))
    )
    individual = tuple(
        issue_materialization_receipt(source, assignment, evidence)
        for evidence in evidences
    )
    batched = issue_materialization_receipt_batch(source, assignment, evidences)

    assert [item.receipt_digest for item in batched] == [
        item.receipt_digest for item in individual
    ]
    assert [item.to_wire() for item in batched] == [
        item.to_wire() for item in individual
    ]

    ledger = build_materialization_receipt_ledger(source, assignment, batched)
    # The validation context is operation-local, never a cache.  Mutating
    # nested parent authority after issuance must therefore fail on the next
    # receipt/ledger boundary.
    source.units[0].recipe_payload["cohort"] = "post-batch-rewrite"
    with pytest.raises(ProtocolViolation, match="not builder-derived"):
        batched[0].to_wire()
    with pytest.raises(ProtocolViolation, match="not builder-derived"):
        ledger.to_wire()


def test_receipt_exactly_joins_source_assignment_state_query_oracle_and_raw() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    evidence = _slot_evidence(source, assignment, 0)
    receipt = issue_materialization_receipt(source, assignment, evidence)
    wire = receipt.to_wire()

    assert wire["authority_origin"] == "pre_split_source"
    assert wire["source_digest"] == source.source_digest
    assert wire["assignment_digest"] == assignment.assignment_digest
    assert wire["row_join"] == evidence.to_wire()
    assert wire["family_digest"] == source.units[0].authority_digest
    assert wire["assignment_cluster_digests"] == []
    assert wire["status"] == "pre_freeze_scaffold"
    assert wire["freeze_grade_evidence"] is False
    assert wire["benchmark_freeze_eligible"] is False
    assert wire["receipt_digest"] == digest_json(
        {key: value for key, value in wire.items() if key != "receipt_digest"}
    )


def test_closed_materialization_ledger_exactly_covers_declared_slots() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.SEALED_TEST},
    )
    receipts = tuple(
        issue_materialization_receipt(
            source,
            assignment,
            _slot_evidence(source, assignment, index),
        )
        for index in range(len(source.materialization_slots))
    )
    ledger = build_materialization_receipt_ledger(source, assignment, receipts)
    assert isinstance(ledger, MaterializationReceiptLedger)
    wire = ledger.to_wire()
    assert wire["declared_slot_count"] == 4
    assert wire["receipt_count"] == 4
    assert wire["status"] == "pre_freeze_scaffold"
    assert wire["freeze_grade_evidence"] is False
    assert wire["benchmark_freeze_eligible"] is False
    assert wire["ledger_digest"] == digest_json(
        {key: value for key, value in wire.items() if key != "ledger_digest"}
    )

    coverage = {
        (item["authority_digest"], item["member_digest"]): item["entries"]
        for item in wire["member_coverage"]
    }
    unit = source.units[0]
    assert len(coverage[(unit.authority_digest, unit.members[0].member_digest)]) == 3
    assert len(coverage[(unit.authority_digest, unit.members[1].member_digest)]) == 1
    # Zero rows is explicit coverage, not an implicit one-row-per-member rule.
    assert coverage[(unit.authority_digest, unit.members[2].member_digest)] == []
    assert {
        item["materialization_role"]
        for item in source.to_wire()["materialization_slots"]
    } == {"standard_row", "pair_side"}


def test_materialization_ledger_rejects_missing_duplicate_and_undeclared_slots() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    receipts = tuple(
        issue_materialization_receipt(
            source,
            assignment,
            _slot_evidence(source, assignment, index),
        )
        for index in range(len(source.materialization_slots))
    )
    with pytest.raises(ProtocolViolation, match="exactly cover declared slots"):
        build_materialization_receipt_ledger(source, assignment, receipts[:-1])
    with pytest.raises(ProtocolViolation, match="duplicate slot receipt"):
        build_materialization_receipt_ledger(
            source,
            assignment,
            (*receipts, receipts[0]),
        )

    undeclared = replace(
        _slot_evidence(source, assignment, 0),
        materialization_slot_digest=_digest("undeclared-slot"),
    )
    with pytest.raises(ProtocolViolation, match="unknown materialization slot"):
        issue_materialization_receipt(source, assignment, undeclared)

    duplicate_source = _closed_slot_source(duplicate_followup_record=True)
    duplicate_assignment = _assignment(
        duplicate_source,
        {duplicate_source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    duplicate_evidences = [
        _slot_evidence(duplicate_source, duplicate_assignment, index)
        for index in range(len(duplicate_source.materialization_slots))
    ]
    duplicate_evidences[1] = replace(
        duplicate_evidences[1],
        record_id=duplicate_evidences[0].record_id,
    )
    duplicate_receipts = issue_materialization_receipt_batch(
        duplicate_source,
        duplicate_assignment,
        tuple(duplicate_evidences),
    )
    with pytest.raises(ProtocolViolation, match="record ids must be unique"):
        build_materialization_receipt_ledger(
            duplicate_source,
            duplicate_assignment,
            duplicate_receipts,
        )


def test_materialization_receipt_rejects_cross_split_cut_query_and_pair_side_joins() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    evidence = _slot_evidence(source, assignment, 2)

    with pytest.raises(ProtocolViolation, match="split does not match"):
        issue_materialization_receipt(
            source,
            assignment,
            replace(evidence, assigned_split=FamilySplit.SEALED_TEST),
        )
    with pytest.raises(ProtocolViolation, match="cut does not match"):
        issue_materialization_receipt(
            source,
            assignment,
            replace(evidence, cut_digest=_digest("wrong-cut")),
        )
    with pytest.raises(ProtocolViolation, match="query cell does not match"):
        issue_materialization_receipt(
            source,
            assignment,
            replace(evidence, query_cell_digest=_digest("wrong-query")),
        )
    with pytest.raises(ProtocolViolation, match="stage does not match"):
        issue_materialization_receipt(
            source,
            assignment,
            replace(evidence, stage_label="swapped-stage"),
        )
    with pytest.raises(ProtocolViolation, match="role does not match"):
        issue_materialization_receipt(
            source,
            assignment,
            replace(
                evidence,
                materialization_role=MaterializationRole.STANDARD_ROW,
                pair_digest=None,
                pair_side=None,
            ),
        )
    with pytest.raises(ProtocolViolation, match="pair side does not match"):
        issue_materialization_receipt(
            source,
            assignment,
            replace(evidence, pair_side=1),
        )
    with pytest.raises(ProtocolViolation, match="member does not match"):
        issue_materialization_receipt(
            source,
            assignment,
            replace(evidence, member_digest=source.units[0].members[1].member_digest),
        )


def test_pair_slot_inventory_requires_both_exact_sides_and_existing_pair() -> None:
    draft = _draft("pair-family")
    pair = PairConstraintDraft(
        "pair",
        PairSemantic.BEHAVIORAL,
        (
            PairSideDraft("pair-family", "left", 0),
            PairSideDraft("pair-family", "right", 1),
        ),
    )
    only_side_zero = MaterializationSlotDraft(
        "only-side-zero",
        "pair-family",
        "left",
        MaterializationRole.PAIR_SIDE,
        "paired-readout",
        _digest("pair-cut"),
        _digest("pair-query"),
        pair_alias="pair",
        pair_side=0,
        row_bundle_commitment_digest=_row_bundle_commitment("only-side-zero"),
    )
    with pytest.raises(ProtocolViolation, match="exactly sides 0 and 1"):
        _source((draft,), pairs=(pair,), slots=(only_side_zero,))
    with pytest.raises(ProtocolViolation, match="missing pair alias"):
        _source((draft,), slots=(only_side_zero,))

    downgraded_pair_slots = tuple(
        MaterializationSlotDraft(
            f"standard-{side}",
            "pair-family",
            member,
            MaterializationRole.STANDARD_ROW,
            "paired-readout",
            _digest(f"standard-cut-{side}"),
            _digest(f"standard-query-{side}"),
            row_bundle_commitment_digest=_row_bundle_commitment(
                f"standard-{side}"
            ),
        )
        for side, member in enumerate(("left", "right"))
    )
    with pytest.raises(ProtocolViolation, match="omits declared pair topology"):
        _source((draft,), pairs=(pair,), slots=downgraded_pair_slots)


@pytest.mark.parametrize(
    ("semantic", "role"),
    [
        (SourceMemberSemantic.PROBE_VARIANT, MaterializationRole.STANDARD_ROW),
        (SourceMemberSemantic.RELEASE_STAGE, MaterializationRole.STANDARD_ROW),
    ],
)
def test_typed_member_role_cannot_be_downgraded(
    semantic: SourceMemberSemantic,
    role: MaterializationRole,
) -> None:
    draft = _draft(
        "typed-family",
        members=(_member("typed-member", semantic=semantic),),
    )
    slot = MaterializationSlotDraft(
        "downgraded-slot",
        "typed-family",
        "typed-member",
        role,
        "typed-stage",
        _digest("typed-cut"),
        _digest("typed-query"),
        row_bundle_commitment_digest=_row_bundle_commitment("downgraded-slot"),
    )
    with pytest.raises(ProtocolViolation, match="typed materialization role"):
        _source((draft,), slots=(slot,))


def test_foreign_or_mutated_slot_inventory_cannot_join_source_authority() -> None:
    source = _closed_slot_source()
    foreign_draft = _draft(
        "foreign-family",
        members=(
            SourceMemberDraft(
                "foreign-member",
                SourceMemberSemantic.PATIENT_TRAJECTORY,
                {"foreign_clinical_value": 9},
            ),
        ),
    )
    foreign_source = _source(
        (foreign_draft,),
        slots=(
            MaterializationSlotDraft(
                "foreign-slot",
                "foreign-family",
                "foreign-member",
                MaterializationRole.STANDARD_ROW,
                "foreign-stage",
                _digest("foreign-cut"),
                _digest("foreign-query"),
                row_bundle_commitment_digest=_row_bundle_commitment("foreign-slot"),
            ),
        ),
    )
    with pytest.raises(ProtocolViolation, match="unknown source member"):
        replace(
            source,
            materialization_slots=(foreign_source.materialization_slots[0],),
        )

    # A frozen dataclass can still be attacked with object.__setattr__; every
    # wire/ledger boundary re-derives the slot digest and fails closed.
    slot = source.materialization_slots[0]
    object.__setattr__(slot, "cut_digest", _digest("post-build-cut-mutation"))
    with pytest.raises(ProtocolViolation, match="not builder-derived"):
        source.to_wire()


def test_exact_ledger_requires_pre_split_closed_inventory() -> None:
    source = _source((_draft("family-a"),))
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    with pytest.raises(ProtocolViolation, match="closed pre-split slot"):
        issue_materialization_receipt(source, assignment, _evidence(source))


def test_slot_role_and_ledger_status_wires_ignore_enum_value_mutation() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    receipts = tuple(
        issue_materialization_receipt(
            source,
            assignment,
            _slot_evidence(source, assignment, index),
        )
        for index in range(len(source.materialization_slots))
    )
    ledger = build_materialization_receipt_ledger(source, assignment, receipts)
    original = MaterializationRole.PAIR_SIDE.value
    try:
        object.__setattr__(MaterializationRole.PAIR_SIDE, "_value_", "forged-role")
        assert {
            item["materialization_role"]
            for item in source.to_wire()["materialization_slots"]
        } == {"standard_row", "pair_side"}
        assert ledger.to_wire()["status"] == "pre_freeze_scaffold"
        assert ledger.to_wire()["benchmark_freeze_eligible"] is False
    finally:
        object.__setattr__(MaterializationRole.PAIR_SIDE, "_value_", original)

    object.__setattr__(ledger, "receipts", ())
    with pytest.raises(ProtocolViolation, match="must not be empty"):
        ledger.to_wire()


def test_evidence_receipt_and_ledger_detect_post_construction_object_rewrites() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    receipts = tuple(
        issue_materialization_receipt(
            source,
            assignment,
            _slot_evidence(source, assignment, index),
        )
        for index in range(len(source.materialization_slots))
    )
    ledger = build_materialization_receipt_ledger(source, assignment, receipts)

    evidence = receipts[0].evidence
    object.__setattr__(
        evidence,
        "public_history_digest",
        _digest("post-construction-history-rewrite"),
    )
    with pytest.raises(ProtocolViolation, match="evidence changed after construction"):
        receipts[0].to_wire()

    # Use a fresh graph to distinguish the child evidence seal from the receipt
    # and exact-ledger seals.
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    receipts = tuple(
        issue_materialization_receipt(
            source,
            assignment,
            _slot_evidence(source, assignment, index),
        )
        for index in range(len(source.materialization_slots))
    )
    ledger = build_materialization_receipt_ledger(source, assignment, receipts)
    original_receipt_seal = receipts[0].receipt_digest
    object.__setattr__(
        receipts[0],
        "_sealed_receipt_digest",
        _digest("forged-receipt-seal"),
    )
    with pytest.raises(ProtocolViolation, match="receipt changed after construction"):
        receipts[0].to_wire()
    object.__setattr__(receipts[0], "_sealed_receipt_digest", original_receipt_seal)

    object.__setattr__(
        ledger,
        "_sealed_ledger_digest",
        _digest("forged-ledger-seal"),
    )
    with pytest.raises(ProtocolViolation, match="ledger changed after construction"):
        ledger.to_wire()


@pytest.mark.parametrize(
    ("artifact_kind", "seal_attribute", "changed_message"),
    [
        (
            "source",
            "_sealed_source_digest",
            "pre-split family source changed after construction",
        ),
        (
            "assignment",
            "_sealed_assignment_digest",
            "weighted atomic assignment changed after construction",
        ),
        (
            "evidence",
            "evidence_digest",
            "row materialization evidence changed after construction",
        ),
        (
            "receipt",
            "_sealed_receipt_digest",
            "materialization receipt changed after construction",
        ),
        (
            "ledger",
            "_sealed_ledger_digest",
            "materialization ledger changed after construction",
        ),
    ],
)
def test_external_seal_registry_rejects_complete_state_and_internal_seal_rewrite(
    artifact_kind: str,
    seal_attribute: str,
    changed_message: str,
) -> None:
    """An attacker cannot re-bless an existing authority object in place.

    Both sides of each attack are independently valid artifacts.  The attack
    replaces the complete dataclass state of the first object with the second
    object's state and also writes the second object's valid internal seal.
    Only the process-external first-digest registry distinguishes that rewrite
    from legitimate construction.
    """

    if artifact_kind == "source":
        original = _closed_slot_source()
        replacement = _closed_slot_source(duplicate_followup_record=True)
    else:
        source = _closed_slot_source()
        train_assignment = _assignment(
            source,
            {source.units[0].authority_digest: FamilySplit.TRAIN},
        )
        validation_assignment = _assignment(
            source,
            {source.units[0].authority_digest: FamilySplit.VALIDATION},
        )
        train_receipts = issue_materialization_receipt_batch(
            source,
            train_assignment,
            tuple(
                _slot_evidence(source, train_assignment, index)
                for index in range(len(source.materialization_slots))
            ),
        )
        validation_receipts = issue_materialization_receipt_batch(
            source,
            validation_assignment,
            tuple(
                _slot_evidence(source, validation_assignment, index)
                for index in range(len(source.materialization_slots))
            ),
        )
        if artifact_kind == "assignment":
            original, replacement = train_assignment, validation_assignment
        elif artifact_kind == "evidence":
            original = train_receipts[0].evidence
            replacement = validation_receipts[0].evidence
        elif artifact_kind == "receipt":
            original, replacement = train_receipts[0], validation_receipts[0]
        else:
            original = build_materialization_receipt_ledger(
                source, train_assignment, train_receipts
            )
            replacement = build_materialization_receipt_ledger(
                source, validation_assignment, validation_receipts
            )

    original_digest = object.__getattribute__(original, seal_attribute)
    replacement_digest = object.__getattribute__(replacement, seal_attribute)
    assert original_digest != replacement_digest

    for dataclass_field in fields(original):
        if dataclass_field.name != seal_attribute:
            object.__setattr__(
                original,
                dataclass_field.name,
                object.__getattribute__(replacement, dataclass_field.name),
            )
    object.__setattr__(original, seal_attribute, replacement_digest)

    with pytest.raises(ProtocolViolation, match=changed_message):
        original.to_wire()


def test_public_wire_boundaries_never_reinitialize_missing_seals() -> None:
    def fresh_graph():
        source = _closed_slot_source()
        assignment = _assignment(
            source,
            {source.units[0].authority_digest: FamilySplit.TRAIN},
        )
        evidences = tuple(
            _slot_evidence(source, assignment, index)
            for index in range(len(source.materialization_slots))
        )
        receipts = issue_materialization_receipt_batch(
            source, assignment, evidences
        )
        ledger = build_materialization_receipt_ledger(
            source, assignment, receipts
        )
        return source, assignment, evidences, receipts, ledger

    source, _, _, _, _ = fresh_graph()
    object.__delattr__(source, "_sealed_source_digest")
    with pytest.raises(ProtocolViolation, match="source seal is missing"):
        source.__post_init__()
    with pytest.raises(ProtocolViolation, match="source seal is missing"):
        source.to_wire()

    _, assignment, _, _, _ = fresh_graph()
    object.__delattr__(assignment, "_sealed_assignment_digest")
    with pytest.raises(ProtocolViolation, match="assignment seal is missing"):
        assignment.__post_init__()
    with pytest.raises(ProtocolViolation, match="assignment seal is missing"):
        assignment.to_wire()

    _, _, evidences, _, _ = fresh_graph()
    object.__delattr__(evidences[0], "evidence_digest")
    with pytest.raises(ProtocolViolation, match="evidence seal is missing"):
        evidences[0].__post_init__()
    with pytest.raises(ProtocolViolation, match="evidence seal is missing"):
        evidences[0].to_wire()

    _, _, _, receipts, _ = fresh_graph()
    object.__delattr__(receipts[0], "_sealed_receipt_digest")
    with pytest.raises(ProtocolViolation, match="receipt seal is missing"):
        receipts[0].__post_init__()
    with pytest.raises(ProtocolViolation, match="receipt seal is missing"):
        receipts[0].to_wire()
    with pytest.raises(ProtocolViolation, match="receipt seal is missing"):
        receipts[0].receipt_digest

    _, _, _, _, ledger = fresh_graph()
    object.__delattr__(ledger, "_sealed_ledger_digest")
    with pytest.raises(ProtocolViolation, match="ledger seal is missing"):
        ledger.__post_init__()
    with pytest.raises(ProtocolViolation, match="ledger seal is missing"):
        ledger.to_wire()


def test_row_receipt_cannot_define_or_reassign_authority() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    wire = _slot_evidence(source, assignment, 0).to_wire()
    wire["family_digest"] = _digest("row-defined-family")
    with pytest.raises(ProtocolViolation, match="judge-private field"):
        RowMaterializationEvidence.from_wire(wire)

    evidence = _slot_evidence(source, assignment, 0)
    unknown = replace(evidence, authority_digest=_digest("unknown-authority"))
    with pytest.raises(ProtocolViolation, match="unknown source authority"):
        issue_materialization_receipt(source, assignment, unknown)

    wrong_split = replace(evidence, assigned_split=FamilySplit.SEALED_TEST)
    with pytest.raises(ProtocolViolation, match="does not match"):
        issue_materialization_receipt(source, assignment, wrong_split)


def test_legacy_or_post_split_adapter_is_permanently_incomplete() -> None:
    audit = audit_legacy_post_split_adapter(
        [
            {
                "record_id": "r-legacy",
                "split": "sealed_test",
                "case_key": "post-split-case",
                "family_digest": _digest("self-reported"),
            }
        ]
    )
    wire = audit.to_wire()
    assert wire["status"] == "incomplete"
    assert wire["freeze_grade_evidence"] is False
    assert wire["benchmark_freeze_eligible"] is False
    assert wire["pre_split_source"] is None
    assert wire["assignments"] is None
    assert wire["materialization_receipts"] == []
    assert wire["blockers"]


def test_wire_artifacts_have_no_status_or_freeze_eligibility_override() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.VALIDATION},
    )
    receipt = issue_materialization_receipt(
        source,
        assignment,
        _slot_evidence(source, assignment, 0),
    )
    for artifact in (
        source.to_wire(),
        assignment.to_wire(),
        receipt.evidence.to_wire(),
        receipt.to_wire(),
    ):
        assert artifact["status"] == "pre_freeze_scaffold"
        assert artifact["freeze_grade_evidence"] is False
        assert artifact["benchmark_freeze_eligible"] is False

    assert set(FamilyScaffoldStatus) == {
        FamilyScaffoldStatus.PRE_FREEZE_SCAFFOLD,
        FamilyScaffoldStatus.INCOMPLETE,
    }


def test_wire_protocol_literals_ignore_mutated_enum_values() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    receipt = issue_materialization_receipt(
        source, assignment, _slot_evidence(source, assignment, 0)
    )

    mutations = (
        (FamilyScaffoldStatus.PRE_FREEZE_SCAFFOLD, "complete"),
        (FamilyScaffoldStatus.INCOMPLETE, "complete"),
        (FamilySplit.TRAIN, "sealed_test"),
        (SourceUnitSemantic.PATIENT_FAMILY, "forged_family"),
        (SourceMemberSemantic.COUNTERFACTUAL_VARIANT, "forged_member"),
    )
    originals = tuple((member, member.value) for member, _ in mutations)
    try:
        for member, forged in mutations:
            object.__setattr__(member, "_value_", forged)

        assert source.to_wire()["status"] == "pre_freeze_scaffold"
        assert source.to_wire()["units"][0]["semantic_type"] == "patient_family"
        assert {
            item["semantic_type"]
            for item in source.to_wire()["units"][0]["members"]
        } == {"counterfactual_variant", "patient_trajectory"}
        assert assignment.to_wire()["status"] == "pre_freeze_scaffold"
        assert assignment.to_wire()["assignments"][0]["split"] == "train"
        assert receipt.to_wire()["status"] == "pre_freeze_scaffold"
        assert receipt.to_wire()["row_join"]["split"] == "train"
        parsed_producer = ProducerSourceUnitDraft.from_wire(_producer_wire())
        assert parsed_producer.semantic_type is SourceUnitSemantic.PATIENT_FAMILY
        assert (
            parsed_producer.members[0].semantic_type
            is SourceMemberSemantic.COUNTERFACTUAL_VARIANT
        )
        parsed_evidence = RowMaterializationEvidence.from_wire(
            receipt.evidence.to_wire()
        )
        assert parsed_evidence.assigned_split is FamilySplit.TRAIN
        assert audit_legacy_post_split_adapter([]).to_wire()["status"] == "incomplete"
    finally:
        for member, original in originals:
            object.__setattr__(member, "_value_", original)


def test_to_wire_revalidates_mutated_builder_inputs_fail_closed() -> None:
    draft = _draft("family-a")
    transcript = _transcript("family-a")
    source = build_pre_split_family_source(
        benchmark_id="ucm-benchmark-v1",
        benchmark_revision="PRE-FREEZE-v1",
        registry_digest=_digest("registry"),
        generator_bundle_digest=_digest("generator-bundle"),
        topology_contract_digest=_digest("topology-contract"),
        query_contract_digest=_digest("query-contract"),
        builder_id="fixture-authority-builder",
        builder_version="fixture-v2",
        drafts=(draft,),
        transcripts=(transcript,),
    )
    # Frozen dataclasses cannot prevent mutation of a nested exact JSON dict.
    # The wire boundary must therefore re-derive and reject stale authority.
    transcript.latent_transcript["draws"] = [999.0]
    with pytest.raises(ProtocolViolation, match="not builder-derived"):
        source.to_wire()


def test_source_rejects_mutated_nested_builder_provenance() -> None:
    source = _source((_draft("family-a"),))
    unit = source.units[0]
    forged_transcript = replace(
        unit.randomness_transcript,
        builder_id="evil-builder",
    )
    forged_unit = replace(unit, randomness_transcript=forged_transcript)
    with pytest.raises(ProtocolViolation, match="does not match source builder"):
        replace(source, units=(forged_unit,))


def test_source_wire_contains_no_post_split_identity_or_generator_seed() -> None:
    wire = _source((_draft("family-a"),)).to_wire()

    seen: set[str] = set()

    def walk(value) -> None:
        if type(value) is dict:
            for key, item in value.items():
                seen.add(key)
                walk(item)
        elif type(value) is list:
            for item in value:
                walk(item)

    walk(wire)
    assert {
        "split",
        "record_id",
        "case_key",
        "generator_seed",
        "master_seed",
        "population_index",
    }.isdisjoint(seen)


def test_digest_fields_reject_noncanonical_lexical_aliases() -> None:
    canonical = _digest("strict-digest-lexeme")
    hex_part = list(canonical[7:])
    alpha_index = next(
        index for index, character in enumerate(hex_part) if character in "abcdef"
    )
    uppercase = hex_part.copy()
    uppercase[alpha_index] = uppercase[alpha_index].upper()
    aliases = (
        "sha256:" + "".join(uppercase),
        "sha256:+" + canonical[8:],
        "sha256:-" + canonical[8:],
        "sha256: " + canonical[8:],
        "sha256:_" + canonical[8:],
    )

    for alias in aliases:
        fields = _row_bundle_fields("strict-digest-row")
        fields["public_history_digest"] = alias
        with pytest.raises(ProtocolViolation, match="sha256-prefixed digest"):
            compute_row_bundle_commitment(**fields)


@pytest.mark.parametrize(
    "payload_fields",
    [
        (
            "public_history_digest",
            "hidden_state_at_cut_digest",
            "oracle_target_digest",
            "candidate_row_digest",
            "judge_row_digest",
        ),
        ("raw_request_digest", "raw_response_digest"),
        (
            "record_id",
            "public_history_digest",
            "hidden_state_at_cut_digest",
            "oracle_target_digest",
            "candidate_row_digest",
            "judge_row_digest",
            "raw_request_digest",
            "raw_response_digest",
        ),
    ],
    ids=("semantic_bundle", "raw_bundle", "complete_bundle"),
)
def test_same_split_row_bundle_swaps_cannot_reuse_receiving_slot_metadata(
    payload_fields: tuple[str, ...],
) -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    receiver = _slot_evidence(source, assignment, 0)
    donor = _slot_evidence(source, assignment, 1)
    swapped = replace(
        receiver,
        **{field: getattr(donor, field) for field in payload_fields},
    )

    with pytest.raises(ProtocolViolation, match="row bundle commitment"):
        issue_materialization_receipt(source, assignment, swapped)


@pytest.mark.parametrize(
    "payload_fields",
    [
        (
            "public_history_digest",
            "hidden_state_at_cut_digest",
            "oracle_target_digest",
            "candidate_row_digest",
            "judge_row_digest",
        ),
        ("raw_request_digest", "raw_response_digest"),
    ],
    ids=("semantic_bundle", "raw_bundle"),
)
def test_train_and_sealed_test_row_bundles_cannot_be_cross_split_swapped(
    payload_fields: tuple[str, ...],
) -> None:
    drafts = (
        _draft("train-family", members=(_member("row"),)),
        _draft("sealed-family", members=(_member("row"),)),
    )
    slots = tuple(
        MaterializationSlotDraft(
            f"{label}-slot",
            f"{label}-family",
            "row",
            MaterializationRole.STANDARD_ROW,
            "evaluation",
            _digest(f"{label}-cut"),
            _digest(f"{label}-query"),
            row_bundle_commitment_digest=_row_bundle_commitment(f"{label}-slot"),
        )
        for label in ("train", "sealed")
    )
    source = _source(drafts, slots=slots)
    unit_by_alias = {unit.unit_alias: unit for unit in source.units}
    assignment = _assignment(
        source,
        {
            unit_by_alias["train-family"].authority_digest: FamilySplit.TRAIN,
            unit_by_alias["sealed-family"].authority_digest: FamilySplit.SEALED_TEST,
        },
    )
    evidence_by_slot = {
        slot.slot_alias: _slot_evidence(source, assignment, index)
        for index, slot in enumerate(source.materialization_slots)
    }
    receiver = evidence_by_slot["train-slot"]
    donor = evidence_by_slot["sealed-slot"]
    swapped = replace(
        receiver,
        **{field: getattr(donor, field) for field in payload_fields},
    )

    with pytest.raises(ProtocolViolation, match="row bundle commitment"):
        issue_materialization_receipt(source, assignment, swapped)


def test_post_assignment_materialization_slot_injection_breaks_source_seal() -> None:
    draft = _draft("late-inventory", members=(_member("row"),))
    baseline_slot = MaterializationSlotDraft(
        "baseline-slot",
        "late-inventory",
        "row",
        MaterializationRole.STANDARD_ROW,
        "baseline",
        _digest("late-baseline-cut"),
        _digest("late-baseline-query"),
        row_bundle_commitment_digest=_row_bundle_commitment("baseline-slot"),
    )
    late_slot = MaterializationSlotDraft(
        "late-slot",
        "late-inventory",
        "row",
        MaterializationRole.STANDARD_ROW,
        "late",
        _digest("late-injected-cut"),
        _digest("late-injected-query"),
        row_bundle_commitment_digest=_row_bundle_commitment("late-slot"),
    )
    source = _source((draft,), slots=(baseline_slot,))
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    evidence = _slot_evidence(source, assignment, 0)
    expanded_source = _source((draft,), slots=(baseline_slot, late_slot))
    assert (
        expanded_source.units[0].authority_digest
        == source.units[0].authority_digest
    )

    object.__setattr__(
        source,
        "materialization_slots",
        expanded_source.materialization_slots,
    )
    for boundary in (
        source.to_wire,
        assignment.to_wire,
        lambda: issue_materialization_receipt(source, assignment, evidence),
    ):
        with pytest.raises(ProtocolViolation, match="source changed after construction"):
            boundary()


def test_materialization_slot_rejects_malformed_strata_allocation_commitment() -> None:
    with pytest.raises(
        ProtocolViolation,
        match="strata_allocation_commitment_digest",
    ):
        MaterializationSlotDraft(
            "strata-commitment-slot",
            "strata-commitment-family",
            "row",
            MaterializationRole.STANDARD_ROW,
            "baseline",
            _digest("strata-commitment-cut"),
            _digest("strata-commitment-query"),
            row_bundle_commitment_digest=_row_bundle_commitment(
                "strata-commitment-slot"
            ),
            strata_allocation_commitment_digest="not-a-sha256-digest",
        )


def test_strata_allocation_commitment_binds_slot_source_and_assignment() -> None:
    draft = _draft(
        "strata-commitment-family",
        members=(_member("row"),),
    )
    baseline_slot = MaterializationSlotDraft(
        "strata-commitment-slot",
        "strata-commitment-family",
        "row",
        MaterializationRole.STANDARD_ROW,
        "baseline",
        _digest("strata-commitment-cut"),
        _digest("strata-commitment-query"),
        row_bundle_commitment_digest=_row_bundle_commitment(
            "strata-commitment-slot"
        ),
        strata_allocation_commitment_digest=_digest("strata-allocation-a"),
    )
    changed_slot = replace(
        baseline_slot,
        strata_allocation_commitment_digest=_digest("strata-allocation-b"),
    )

    baseline_source = _source((draft,), slots=(baseline_slot,))
    changed_source = _source((draft,), slots=(changed_slot,))
    baseline_resolved_slot = baseline_source.materialization_slots[0]
    changed_resolved_slot = changed_source.materialization_slots[0]

    assert (
        baseline_source.units[0].authority_digest
        == changed_source.units[0].authority_digest
    )
    assert baseline_resolved_slot.slot_digest != changed_resolved_slot.slot_digest
    assert baseline_source.source_digest != changed_source.source_digest

    authority_digest = baseline_source.units[0].authority_digest
    baseline_assignment = _assignment(
        baseline_source,
        {authority_digest: FamilySplit.TRAIN},
    )
    changed_assignment = _assignment(
        changed_source,
        {authority_digest: FamilySplit.TRAIN},
    )

    assert baseline_assignment.source is baseline_source
    assert changed_assignment.source is changed_source
    assert baseline_assignment.assignment_digest != changed_assignment.assignment_digest


def test_w19_typed_row_cannot_gain_a_second_pair_bound_physical_slot() -> None:
    drafts = list(_w19_drafts())
    first_alias = drafts[0].unit_alias
    drafts[0] = _draft(
        first_alias,
        world="W19",
        members=(
            _member(
                "assignment-row",
                semantic=SourceMemberSemantic.W19_ASSIGNMENT_ROW,
            ),
            _member("pair-companion"),
        ),
        weight=1,
    )
    drafts_tuple = tuple(drafts)
    pair = PairConstraintDraft(
        "w19-extra-pair",
        PairSemantic.BEHAVIORAL,
        (
            PairSideDraft(first_alias, "assignment-row", 0),
            PairSideDraft(first_alias, "pair-companion", 1),
        ),
    )
    pair_cut = _digest("w19-extra-pair-cut")
    pair_query = _digest("w19-extra-pair-query")
    slots = _w19_slots(drafts_tuple) + (
        MaterializationSlotDraft(
            "w19-extra-pair-side",
            first_alias,
            "assignment-row",
            MaterializationRole.W19_ASSIGNMENT_ROW,
            "pair-readout",
            pair_cut,
            pair_query,
            pair_alias="w19-extra-pair",
            pair_side=0,
            atomic_link_alias="w19-quota-cluster",
            row_bundle_commitment_digest=_row_bundle_commitment(
                "w19-extra-pair-side"
            ),
        ),
        MaterializationSlotDraft(
            "w19-pair-companion",
            first_alias,
            "pair-companion",
            MaterializationRole.PAIR_SIDE,
            "pair-readout",
            pair_cut,
            pair_query,
            pair_alias="w19-extra-pair",
            pair_side=1,
            row_bundle_commitment_digest=_row_bundle_commitment(
                "w19-pair-companion"
            ),
        ),
    )

    with pytest.raises(ProtocolViolation, match="exactly one slot"):
        _source(
            drafts_tuple,
            pairs=(pair,),
            links=(_w19_cluster(drafts_tuple),),
            slots=slots,
        )


def _typed_atomic_fixture(
    link_semantic: AtomicLinkSemantic,
    member_semantic: SourceMemberSemantic,
    materialization_role: MaterializationRole,
) -> tuple[
    tuple[ProducerSourceUnitDraft, ...],
    AtomicLinkDraft,
    tuple[MaterializationSlotDraft, ...],
]:
    drafts = tuple(
        _draft(
            f"typed-atomic-{side}",
            members=(_member("typed-row", semantic=member_semantic),),
        )
        for side in ("left", "right")
    )
    link = AtomicLinkDraft(
        "typed-atomic-link",
        link_semantic,
        tuple(MemberRefDraft(draft.unit_alias, "typed-row") for draft in drafts),
    )
    slots = tuple(
        MaterializationSlotDraft(
            f"typed-atomic-{side}-slot",
            draft.unit_alias,
            "typed-row",
            materialization_role,
            "typed-atomic-stage",
            _digest(f"typed-atomic-{side}-cut"),
            _digest(f"typed-atomic-{side}-query"),
            atomic_link_alias="typed-atomic-link",
            row_bundle_commitment_digest=_row_bundle_commitment(
                f"typed-atomic-{side}-slot"
            ),
        )
        for side, draft in zip(("left", "right"), drafts, strict=True)
    )
    return drafts, link, slots


@pytest.mark.parametrize(
    ("link_semantic", "member_semantic", "materialization_role"),
    [
        (
            AtomicLinkSemantic.RELEASE_S0_S1,
            SourceMemberSemantic.RELEASE_STAGE,
            MaterializationRole.RELEASE_STAGE_ROW,
        ),
        (
            AtomicLinkSemantic.SHARED_PROBE_BASE,
            SourceMemberSemantic.PROBE_VARIANT,
            MaterializationRole.PROBE_ROW,
        ),
    ],
    ids=("release_s0_s1", "shared_probe_base"),
)
def test_closed_atomic_link_inventory_rejects_one_sided_materialization(
    link_semantic: AtomicLinkSemantic,
    member_semantic: SourceMemberSemantic,
    materialization_role: MaterializationRole,
) -> None:
    drafts, link, slots = _typed_atomic_fixture(
        link_semantic,
        member_semantic,
        materialization_role,
    )
    with pytest.raises(ProtocolViolation, match="exactly cover atomic link"):
        _source(drafts, links=(link,), slots=slots[:1])


def test_atomic_link_join_cannot_be_dropped_or_replaced_at_receipt_time() -> None:
    drafts, link, slots = _typed_atomic_fixture(
        AtomicLinkSemantic.RELEASE_S0_S1,
        SourceMemberSemantic.RELEASE_STAGE,
        MaterializationRole.RELEASE_STAGE_ROW,
    )
    source = _source(drafts, links=(link,), slots=slots)
    assignment = _assignment(
        source,
        {unit.authority_digest: FamilySplit.VALIDATION for unit in source.units},
    )
    evidence = _slot_evidence(source, assignment, 0)

    for forged_link in (None, _digest("foreign-atomic-link")):
        forged = replace(evidence, atomic_link_digest=forged_link)
        with pytest.raises(ProtocolViolation, match="atomic link"):
            issue_materialization_receipt(source, assignment, forged)


def test_physical_cell_cannot_be_duplicated_by_stage_and_role_aliases() -> None:
    draft = _draft(
        "physical-cell-family",
        members=(_member("left"), _member("right")),
    )
    pair = PairConstraintDraft(
        "physical-cell-pair",
        PairSemantic.RESPONSE_REVERSAL,
        (
            PairSideDraft("physical-cell-family", "left", 0),
            PairSideDraft("physical-cell-family", "right", 1),
        ),
    )
    shared_cut = _digest("physical-cell-cut")
    shared_query = _digest("physical-cell-query")
    slots = (
        MaterializationSlotDraft(
            "left-standard-alias",
            "physical-cell-family",
            "left",
            MaterializationRole.STANDARD_ROW,
            "standard-stage-alias",
            shared_cut,
            shared_query,
            row_bundle_commitment_digest=_row_bundle_commitment(
                "left-standard-alias"
            ),
        ),
        MaterializationSlotDraft(
            "left-pair-alias",
            "physical-cell-family",
            "left",
            MaterializationRole.PAIR_SIDE,
            "pair-stage-alias",
            shared_cut,
            shared_query,
            pair_alias="physical-cell-pair",
            pair_side=0,
            row_bundle_commitment_digest=_row_bundle_commitment("left-pair-alias"),
        ),
        MaterializationSlotDraft(
            "right-pair-side",
            "physical-cell-family",
            "right",
            MaterializationRole.PAIR_SIDE,
            "pair-stage-alias",
            shared_cut,
            shared_query,
            pair_alias="physical-cell-pair",
            pair_side=1,
            row_bundle_commitment_digest=_row_bundle_commitment("right-pair-side"),
        ),
    )

    with pytest.raises(ProtocolViolation, match="duplicate physical cells"):
        _source((draft,), pairs=(pair,), slots=slots)


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    [
        ("schema_version", "ucm-row-materialization-evidence/999"),
        ("status", "complete"),
        ("freeze_grade_evidence", True),
        ("benchmark_freeze_eligible", True),
        ("blockers", []),
    ],
)
def test_standalone_evidence_wire_cannot_forge_protocol_or_freeze_markers(
    field_name: str,
    forged_value: object,
) -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    wire = _slot_evidence(source, assignment, 0).to_wire()
    assert wire["schema_version"] == "ucm-row-materialization-evidence/2"
    assert wire["status"] == "pre_freeze_scaffold"
    assert wire["freeze_grade_evidence"] is False
    assert wire["benchmark_freeze_eligible"] is False
    assert wire["blockers"]
    forged = {**wire, field_name: forged_value}

    with pytest.raises(ProtocolViolation, match="non-canonical or stale"):
        RowMaterializationEvidence.from_wire(forged)


def test_rewritten_global_blocker_is_ignored_before_wire_emission() -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    evidence = _slot_evidence(source, assignment, 0)
    blocker = family_manifest_module._EVIDENCE_BLOCKER
    original = (blocker.code, blocker.artifact, blocker.detail)
    try:
        object.__setattr__(blocker, "code", "UCM-OK")
        object.__setattr__(blocker, "artifact", "freeze_certificate")
        object.__setattr__(blocker, "detail", "complete")
        emitted = evidence.to_wire()["blockers"]
        assert emitted == [
            {
                "code": "UCM-E003-HARNESS_INCOMPLETE",
                "artifact": "row_materialization_evidence",
                "detail": (
                    "row evidence is structurally bound but builder custody and "
                    "the raw ledger are not independently sealed"
                ),
            }
        ]
    finally:
        object.__setattr__(blocker, "code", original[0])
        object.__setattr__(blocker, "artifact", original[1])
        object.__setattr__(blocker, "detail", original[2])

    assert evidence.to_wire()["blockers"]


def _resign_top_level_wire(wire: dict, digest_field: str) -> dict:
    body = dict(wire)
    body.pop(digest_field)
    wire[digest_field] = digest_json(body)
    return wire


def test_exact_authority_byte_parsers_and_artifact_set_roundtrip() -> None:
    (
        source,
        assignment,
        receipts,
        ledger,
        source_bytes,
        assignment_bytes,
        ledger_bytes,
    ) = _exact_authority_preimages()

    parsed_source = parse_pre_split_family_source_bytes(source_bytes)
    parsed_assignment = parse_weighted_atomic_assignment_bytes(
        assignment_bytes, parsed_source
    )
    parsed_receipts = tuple(
        parse_materialization_receipt_bytes(
            canonical_json_bytes(receipt.to_wire()),
            parsed_source,
            parsed_assignment,
        )
        for receipt in receipts
    )
    parsed_ledger = parse_materialization_ledger_bytes(
        ledger_bytes, parsed_source, parsed_assignment
    )

    assert parsed_source.source_digest == source.source_digest
    assert parsed_assignment.assignment_digest == assignment.assignment_digest
    assert tuple(item.receipt_digest for item in parsed_receipts) == tuple(
        item.receipt_digest for item in receipts
    )
    assert parsed_ledger.ledger_digest == ledger.ledger_digest
    assert canonical_json_bytes(parsed_source.to_wire()) == source_bytes
    assert canonical_json_bytes(parsed_assignment.to_wire()) == assignment_bytes
    assert canonical_json_bytes(parsed_ledger.to_wire()) == ledger_bytes

    artifact_set = FamilyMaterializationAuthorityArtifactSet.from_preimages(
        source_bytes, assignment_bytes, ledger_bytes
    )
    wire = artifact_set.to_wire()
    assert wire["schema_version"] == AUTHORITY_ARTIFACT_SET_PROTOCOL
    assert wire["status"] == "pre_freeze_scaffold"
    assert wire["freeze_grade_evidence"] is False
    assert wire["benchmark_freeze_eligible"] is False
    assert wire["blockers"] == [
        {
            "code": "UCM-E003-HARNESS_INCOMPLETE",
            "artifact": "family_materialization_authority_artifact_set",
            "detail": (
                "exact authority preimages are locally retained but external "
                "custody, independent runtime sealing, and atomic publication "
                "are not yet available"
            ),
        }
    ]
    expected_preimages = {
        "source": (source_bytes, source.source_digest),
        "assignment": (assignment_bytes, assignment.assignment_digest),
        "ledger": (ledger_bytes, ledger.ledger_digest),
    }
    for name, (preimage, authority_body_digest) in expected_preimages.items():
        entry = wire["preimages"][name]
        assert entry["artifact_digest"] == digest_bytes(preimage)
        assert entry["authority_body_digest"] == authority_body_digest
        assert entry["byte_length"] == len(preimage)

    assert wire["receipt_count"] == len(receipts)
    assert {
        entry["receipt_authority_body_digest"]
        for entry in wire["receipt_entries"]
    } == {receipt.receipt_digest for receipt in receipts}
    assert {
        entry["receipt_artifact_digest"] for entry in wire["receipt_entries"]
    } == {
        digest_bytes(canonical_json_bytes(receipt.to_wire()))
        for receipt in receipts
    }
    assert wire["receipt_exact_set_root"] == domain_digest(
        b"UCM\0FAMILY_MATERIALIZATION_RECEIPT_EXACT_SET_V1\0",
        (canonical_json_bytes(wire["receipt_entries"]),),
    )
    assert wire["artifact_set_digest"] == digest_json(
        {key: value for key, value in wire.items() if key != "artifact_set_digest"}
    )

    reparsed = parse_family_materialization_authority_artifact_set_bytes(
        artifact_set.canonical_bytes
    )
    assert reparsed.canonical_bytes == artifact_set.canonical_bytes
    assert reparsed.artifact_set_digest == artifact_set.artifact_set_digest
    assert reparsed.receipt_exact_set_root == artifact_set.receipt_exact_set_root


def test_exact_authority_parsers_reject_noncanonical_framing_and_nonbytes() -> None:
    (
        _,
        _,
        receipts,
        _,
        source_bytes,
        assignment_bytes,
        ledger_bytes,
    ) = _exact_authority_preimages()
    source = parse_pre_split_family_source_bytes(source_bytes)
    assignment = parse_weighted_atomic_assignment_bytes(assignment_bytes, source)
    receipt_bytes = canonical_json_bytes(receipts[0].to_wire())
    artifact_set_bytes = FamilyMaterializationAuthorityArtifactSet.from_preimages(
        source_bytes, assignment_bytes, ledger_bytes
    ).canonical_bytes
    parser_cases = (
        (source_bytes, parse_pre_split_family_source_bytes),
        (
            assignment_bytes,
            lambda payload: parse_weighted_atomic_assignment_bytes(payload, source),
        ),
        (
            receipt_bytes,
            lambda payload: parse_materialization_receipt_bytes(
                payload, source, assignment
            ),
        ),
        (
            ledger_bytes,
            lambda payload: parse_materialization_ledger_bytes(
                payload, source, assignment
            ),
        ),
        (
            artifact_set_bytes,
            parse_family_materialization_authority_artifact_set_bytes,
        ),
    )
    for canonical_payload, parser in parser_cases:
        attacks = (
            canonical_payload[:-1],
            canonical_payload.replace(b"\n", b"\r\n"),
            b"\xef\xbb\xbf" + canonical_payload,
            canonical_payload[:-1] + b" \n",
            canonical_payload + b"\n",
            b"\xff" + canonical_payload,
        )
        for attack in attacks:
            with pytest.raises(ProtocolViolation):
                parser(attack)
        with pytest.raises(ProtocolViolation, match="exact bytes"):
            parser(bytearray(canonical_payload))

    duplicate_key_payload = (
        b'{"schema_version":"duplicate",' + source_bytes[1:]
    )
    with pytest.raises(ProtocolViolation, match="duplicate key"):
        parse_pre_split_family_source_bytes(duplicate_key_payload)


def test_exact_authority_parsers_reject_missing_and_extra_fields() -> None:
    (
        _,
        _,
        receipts,
        _,
        source_bytes,
        assignment_bytes,
        ledger_bytes,
    ) = _exact_authority_preimages()
    source = parse_pre_split_family_source_bytes(source_bytes)
    assignment = parse_weighted_atomic_assignment_bytes(assignment_bytes, source)
    receipt_bytes = canonical_json_bytes(receipts[0].to_wire())
    parser_cases = (
        (
            source_bytes,
            "source_digest",
            parse_pre_split_family_source_bytes,
        ),
        (
            assignment_bytes,
            "assignment_digest",
            lambda payload: parse_weighted_atomic_assignment_bytes(payload, source),
        ),
        (
            receipt_bytes,
            "receipt_digest",
            lambda payload: parse_materialization_receipt_bytes(
                payload, source, assignment
            ),
        ),
        (
            ledger_bytes,
            "ledger_digest",
            lambda payload: parse_materialization_ledger_bytes(
                payload, source, assignment
            ),
        ),
    )
    for payload, required_field, parser in parser_cases:
        extra = json.loads(payload)
        extra["unexpected"] = "re-signed"
        with pytest.raises(ProtocolViolation, match="keys do not match schema"):
            parser(canonical_json_bytes(extra))

        missing = json.loads(payload)
        del missing[required_field]
        with pytest.raises(ProtocolViolation, match="keys do not match schema"):
            parser(canonical_json_bytes(missing))


@pytest.mark.parametrize(
    "flag",
    ["freeze_grade_evidence", "benchmark_freeze_eligible"],
)
def test_row_evidence_from_wire_rejects_bool_int_alias(flag: str) -> None:
    source = _closed_slot_source()
    assignment = _assignment(
        source, {source.units[0].authority_digest: FamilySplit.TRAIN}
    )
    wire = _slot_evidence(source, assignment, 0).to_wire()
    assert wire[flag] is False
    wire[flag] = 0
    with pytest.raises(ProtocolViolation, match="non-canonical or stale"):
        RowMaterializationEvidence.from_wire(wire)


def test_exact_authority_parsers_reject_numeric_type_drift_after_resign() -> None:
    (
        _,
        _,
        receipts,
        _,
        source_bytes,
        assignment_bytes,
        ledger_bytes,
    ) = _exact_authority_preimages()
    source = parse_pre_split_family_source_bytes(source_bytes)
    assignment = parse_weighted_atomic_assignment_bytes(assignment_bytes, source)

    source_wire = json.loads(source_bytes)
    source_wire["units"][0]["weight"] = float(source_wire["units"][0]["weight"])
    _resign_top_level_wire(source_wire, "source_digest")
    with pytest.raises(ProtocolViolation):
        parse_pre_split_family_source_bytes(canonical_json_bytes(source_wire))

    assignment_wire = json.loads(assignment_bytes)
    assignment_wire["assignments"][0]["weight"] = float(
        assignment_wire["assignments"][0]["weight"]
    )
    _resign_top_level_wire(assignment_wire, "assignment_digest")
    with pytest.raises(ProtocolViolation):
        parse_weighted_atomic_assignment_bytes(
            canonical_json_bytes(assignment_wire), source
        )

    receipt_wire = receipts[0].to_wire()
    receipt_wire["row_join"]["freeze_grade_evidence"] = 0
    _resign_top_level_wire(receipt_wire, "receipt_digest")
    with pytest.raises(ProtocolViolation, match="non-canonical or stale"):
        parse_materialization_receipt_bytes(
            canonical_json_bytes(receipt_wire), source, assignment
        )

    ledger_wire = json.loads(ledger_bytes)
    ledger_wire["receipt_count"] = float(ledger_wire["receipt_count"])
    _resign_top_level_wire(ledger_wire, "ledger_digest")
    with pytest.raises(ProtocolViolation, match="non-canonical, stale, or re-signed"):
        parse_materialization_ledger_bytes(
            canonical_json_bytes(ledger_wire), source, assignment
        )


def test_exact_authority_graph_rejects_cross_bundle_a_b_mix() -> None:
    (
        _,
        _,
        receipts_a,
        _,
        source_bytes_a,
        assignment_bytes_a,
        ledger_bytes_a,
    ) = _exact_authority_preimages(
        split=FamilySplit.TRAIN, builder_version="fixture-a"
    )
    (
        _,
        _,
        receipts_b,
        _,
        source_bytes_b,
        assignment_bytes_b,
        ledger_bytes_b,
    ) = _exact_authority_preimages(
        split=FamilySplit.VALIDATION, builder_version="fixture-b"
    )
    source_a = parse_pre_split_family_source_bytes(source_bytes_a)
    assignment_a = parse_weighted_atomic_assignment_bytes(
        assignment_bytes_a, source_a
    )

    with pytest.raises(ProtocolViolation):
        parse_weighted_atomic_assignment_bytes(assignment_bytes_b, source_a)
    with pytest.raises(ProtocolViolation):
        parse_materialization_receipt_bytes(
            canonical_json_bytes(receipts_b[0].to_wire()), source_a, assignment_a
        )
    with pytest.raises(ProtocolViolation):
        parse_materialization_ledger_bytes(
            ledger_bytes_b, source_a, assignment_a
        )
    with pytest.raises(ProtocolViolation):
        FamilyMaterializationAuthorityArtifactSet.from_preimages(
            source_bytes_a, assignment_bytes_b, ledger_bytes_b
        )
    with pytest.raises(ProtocolViolation):
        FamilyMaterializationAuthorityArtifactSet.from_preimages(
            source_bytes_a, assignment_bytes_a, ledger_bytes_b
        )

    artifact_a = FamilyMaterializationAuthorityArtifactSet.from_preimages(
        source_bytes_a, assignment_bytes_a, ledger_bytes_a
    )
    artifact_b = FamilyMaterializationAuthorityArtifactSet.from_preimages(
        source_bytes_b, assignment_bytes_b, ledger_bytes_b
    )
    assert artifact_a.artifact_set_digest != artifact_b.artifact_set_digest
    assert receipts_a[0].receipt_digest != receipts_b[0].receipt_digest


def test_authority_artifact_set_rejects_resigned_derived_and_fixed_fields() -> None:
    (
        _,
        _,
        _,
        _,
        source_bytes,
        assignment_bytes,
        ledger_bytes,
    ) = _exact_authority_preimages()
    artifact_set = FamilyMaterializationAuthorityArtifactSet.from_preimages(
        source_bytes, assignment_bytes, ledger_bytes
    )

    def assert_rejected(mutator) -> None:
        wire = json.loads(artifact_set.canonical_bytes)
        mutator(wire)
        _resign_top_level_wire(wire, "artifact_set_digest")
        with pytest.raises(ProtocolViolation):
            parse_family_materialization_authority_artifact_set_bytes(
                canonical_json_bytes(wire)
            )

    assert_rejected(
        lambda wire: wire.__setitem__(
            "schema_version", "ucm-family-materialization-authority-artifact-set/2"
        )
    )
    assert_rejected(lambda wire: wire.__setitem__("status", "authorized_frozen"))
    assert_rejected(
        lambda wire: wire["blockers"][0].__setitem__("code", "UCM-E000-RESIGNED")
    )
    assert_rejected(lambda wire: wire.__setitem__("freeze_grade_evidence", 0))
    assert_rejected(
        lambda wire: wire.__setitem__("benchmark_freeze_eligible", 0)
    )
    assert_rejected(
        lambda wire: wire.__setitem__("freeze_manifest_digest", digest_json({}))
    )
    assert_rejected(
        lambda wire: wire["preimages"]["source"].__setitem__(
            "artifact_digest", wire["preimages"]["assignment"]["artifact_digest"]
        )
    )
    assert_rejected(
        lambda wire: wire["preimages"]["source"].__setitem__(
            "authority_body_digest",
            wire["preimages"]["assignment"]["authority_body_digest"],
        )
    )

    def drop_and_resign_receipt_set(wire: dict) -> None:
        wire["receipt_entries"].pop()
        wire["receipt_count"] = len(wire["receipt_entries"])
        wire["receipt_exact_set_root"] = domain_digest(
            b"UCM\0FAMILY_MATERIALIZATION_RECEIPT_EXACT_SET_V1\0",
            (canonical_json_bytes(wire["receipt_entries"]),),
        )

    assert_rejected(drop_and_resign_receipt_set)


def test_authority_artifact_set_external_seal_rejects_coherent_mutation() -> None:
    (
        _,
        _,
        _,
        _,
        source_bytes_a,
        assignment_bytes_a,
        ledger_bytes_a,
    ) = _exact_authority_preimages(
        split=FamilySplit.TRAIN, builder_version="fixture-a"
    )
    (
        _,
        _,
        _,
        _,
        source_bytes_b,
        assignment_bytes_b,
        ledger_bytes_b,
    ) = _exact_authority_preimages(
        split=FamilySplit.VALIDATION, builder_version="fixture-b"
    )
    artifact_a = FamilyMaterializationAuthorityArtifactSet.from_preimages(
        source_bytes_a, assignment_bytes_a, ledger_bytes_a
    )
    artifact_b = FamilyMaterializationAuthorityArtifactSet.from_preimages(
        source_bytes_b, assignment_bytes_b, ledger_bytes_b
    )
    replacement_digest = artifact_b.artifact_set_digest

    object.__setattr__(artifact_a, "source_preimage", source_bytes_b)
    object.__setattr__(artifact_a, "assignment_preimage", assignment_bytes_b)
    object.__setattr__(artifact_a, "ledger_preimage", ledger_bytes_b)
    object.__setattr__(
        artifact_a, "_sealed_artifact_set_digest", replacement_digest
    )
    with pytest.raises(ProtocolViolation, match="changed after construction"):
        artifact_a.to_wire()


def test_authority_artifact_set_constructor_accepts_only_exact_preimage_bytes() -> None:
    (
        source,
        _,
        _,
        _,
        _,
        assignment_bytes,
        ledger_bytes,
    ) = _exact_authority_preimages()
    with pytest.raises(ProtocolViolation, match="source preimage must be exact bytes"):
        FamilyMaterializationAuthorityArtifactSet.from_preimages(
            source, assignment_bytes, ledger_bytes
        )
