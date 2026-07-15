from __future__ import annotations

from dataclasses import replace

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_json
from prototype.unified_map.family_manifest import (
    AtomicLinkDraft,
    AtomicLinkSemantic,
    BuilderRandomnessTranscript,
    FamilyScaffoldStatus,
    FamilySplit,
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
    build_weighted_atomic_assignment,
    issue_materialization_receipt,
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
):
    return build_pre_split_family_source(
        benchmark_id="ucm-benchmark-v1",
        benchmark_revision="PRE-FREEZE-v1",
        registry_digest=_digest("registry"),
        generator_bundle_digest=_digest("generator-bundle"),
        topology_contract_digest=_digest("topology-contract"),
        query_contract_digest=_digest("query-contract"),
        builder_id="fixture-authority-builder",
        builder_version="fixture-v2",
        drafts=drafts,
        transcripts=tuple(
            _transcript(item.unit_alias, draw=(index + 1) / 10)
            for index, item in enumerate(drafts)
        ),
        pair_topology=pairs,
        atomic_links=links,
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
    source = _source(drafts, pairs=(pair,))
    assignment = _assignment(
        source,
        {
            source.units[0].authority_digest: FamilySplit.TRAIN,
            source.units[1].authority_digest: FamilySplit.SEALED_TEST,
        },
    )
    side_one = replace(
        _evidence(source),
        member_digest=source.units[0].members[1].member_digest,
        assigned_split=FamilySplit.SEALED_TEST,
    )
    with pytest.raises(ProtocolViolation, match="does not match"):
        issue_materialization_receipt(source, assignment, side_one)


def test_generic_atomic_connected_component_cannot_cross_split() -> None:
    drafts = (_draft("family-a", weight=3), _draft("family-b", weight=5))
    link = AtomicLinkDraft(
        "s0-s1-release",
        AtomicLinkSemantic.RELEASE_S0_S1,
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
    family_a = _draft(
        "w19-family-a",
        world="W19",
        members=(
            _member(
                "assignment-row",
                semantic=SourceMemberSemantic.W19_ASSIGNMENT_ROW,
            ),
        ),
    )
    family_b = _draft(
        "w19-family-b",
        world="W19",
        members=(
            _member(
                "assignment-row",
                semantic=SourceMemberSemantic.W19_ASSIGNMENT_ROW,
            ),
        ),
    )
    cluster = AtomicLinkDraft(
        "w19-quota-cluster",
        AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER,
        (
            MemberRefDraft("w19-family-a", "assignment-row"),
            MemberRefDraft("w19-family-b", "assignment-row"),
        ),
    )
    source = _source((family_a, family_b), links=(cluster,))
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
                source.units[0].authority_digest: FamilySplit.TRAIN,
                source.units[1].authority_digest: FamilySplit.SEALED_TEST,
            },
        )
    assignment = _assignment(
        source,
        {unit.authority_digest: FamilySplit.TRAIN for unit in source.units},
    )
    receipt = issue_materialization_receipt(source, assignment, _evidence(source))
    assert receipt.to_wire()["assignment_cluster_digests"] == [
        cluster_wire["link_digest"]
    ]

    with pytest.raises(ProtocolViolation, match="topology is incomplete"):
        _source((family_a, family_b))
    wrong_cluster = AtomicLinkDraft(
        "wrong-w19-cluster",
        AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER,
        (
            MemberRefDraft("ordinary-a", "left"),
            MemberRefDraft("ordinary-b", "right"),
        ),
    )
    with pytest.raises(ProtocolViolation, match="typed rows"):
        _source(
            (_draft("ordinary-a"), _draft("ordinary-b")),
            links=(wrong_cluster,),
        )


def test_receipt_exactly_joins_source_assignment_state_query_oracle_and_raw() -> None:
    source = _source((_draft("family-a"),))
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    evidence = _evidence(source)
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


def test_row_receipt_cannot_define_or_reassign_authority() -> None:
    source = _source((_draft("family-a"),))
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    wire = _evidence(source).to_wire()
    wire["family_digest"] = _digest("row-defined-family")
    with pytest.raises(ProtocolViolation, match="judge-private field"):
        RowMaterializationEvidence.from_wire(wire)

    unknown = replace(_evidence(source), authority_digest=_digest("unknown-authority"))
    with pytest.raises(ProtocolViolation, match="unknown source authority"):
        issue_materialization_receipt(source, assignment, unknown)

    wrong_split = replace(_evidence(source), assigned_split=FamilySplit.SEALED_TEST)
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
    source = _source((_draft("family-a"),))
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.VALIDATION},
    )
    receipt = issue_materialization_receipt(
        source,
        assignment,
        _evidence(source, FamilySplit.VALIDATION),
    )
    for artifact in (source.to_wire(), assignment.to_wire(), receipt.to_wire()):
        assert artifact["status"] == "pre_freeze_scaffold"
        assert artifact["freeze_grade_evidence"] is False
        assert artifact["benchmark_freeze_eligible"] is False

    assert set(FamilyScaffoldStatus) == {
        FamilyScaffoldStatus.PRE_FREEZE_SCAFFOLD,
        FamilyScaffoldStatus.INCOMPLETE,
    }


def test_wire_protocol_literals_ignore_mutated_enum_values() -> None:
    source = _source((_draft("family-a"),))
    assignment = _assignment(
        source,
        {source.units[0].authority_digest: FamilySplit.TRAIN},
    )
    receipt = issue_materialization_receipt(source, assignment, _evidence(source))

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
        } == {"counterfactual_variant"}
        assert assignment.to_wire()["status"] == "pre_freeze_scaffold"
        assert assignment.to_wire()["assignments"][0]["split"] == "train"
        assert receipt.to_wire()["status"] == "pre_freeze_scaffold"
        assert receipt.to_wire()["row_join"]["split"] == "train"
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
