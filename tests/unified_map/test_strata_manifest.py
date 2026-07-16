from __future__ import annotations

import copy
import inspect
from dataclasses import replace

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_json
from prototype.unified_map.family_manifest import (
    AtomicLinkDraft,
    AtomicLinkSemantic,
    BuilderRandomnessTranscript,
    FamilySplit,
    MaterializationReceiptLedger,
    MaterializationRole,
    MaterializationSlotDraft,
    MemberRefDraft,
    PairConstraintDraft,
    PairSemantic,
    PairSideDraft,
    ProducerSourceUnitDraft,
    RowMaterializationEvidence,
    SourceMemberDraft,
    SourceMemberSemantic,
    SourceUnitSemantic,
    build_pre_split_family_source,
    build_materialization_receipt_ledger,
    build_weighted_atomic_assignment,
    compute_row_bundle_commitment,
    issue_materialization_receipt_batch,
)
from prototype.unified_map.schema import (
    CandidateVisibleEvent,
    EventKind,
    VisibleHistory,
    event_sort_key,
)
from prototype.unified_map.extensions import _open_custody
from prototype.unified_map.strata_manifest import (
    AllocationCellValue,
    AllocationDimension,
    DualChannelStrataAuthority,
    FrozenSlotAllocation,
    GeneratorAllocationEntry,
    JudgeChannelResult,
    JudgeRule,
    JudgeRuleKind,
    JudgeStrataAuthority,
    PreSplitStrataAllocationManifest,
    PublicChannelResult,
    PublicClassifierAuthority,
    PublicRule,
    PublicRuleKind,
    StrataReceiptBatch,
    StrataRowJoin,
    StrataRowReceipt,
    StrataScaffoldStatus,
    SlotAllocationCell,
    SlotAllocationDraft,
    StratumChannel,
    StratumDefinition,
    WORLD_DECLARED_STRATA,
    build_pre_split_strata_allocation_manifest,
    build_generator_allocation_entry,
    compute_slot_strata_allocation_commitment,
    issue_strata_row_receipt,
    issue_strata_row_receipt_batch,
)
from prototype.unified_map.world_registry import WORLD_REGISTRY
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w16 import W16World, make_w16_extension_custody


_DEFAULT_AUTHORITY_CACHE: dict[str, DualChannelStrataAuthority] = {}


def _digest(label: str) -> str:
    return digest_json({"fixture": label})


def _row_bundle_commitment(
    ordinal: int,
    history: VisibleHistory,
) -> str:
    label = f"row-{ordinal}"
    return compute_row_bundle_commitment(
        record_id=label,
        public_history_digest=history.digest,
        hidden_state_at_cut_digest=_digest(f"hidden-{label}"),
        oracle_target_digest=_digest(f"oracle-{label}"),
        candidate_row_digest=_digest(f"candidate-{label}"),
        judge_row_digest=_digest(f"judge-{label}"),
        raw_request_digest=_digest(f"request-{label}"),
        raw_response_digest=_digest(f"response-{label}"),
    )


def _history(
    *,
    obs_value: float = 1.30,
    heldout_assay_slots: bool = True,
    extra_payload: dict | None = None,
) -> VisibleHistory:
    payload = {
        "check_id": "Q1",
        "assay_slot": 1 if heldout_assay_slots else 0,
        "channel_id": "obs_0",
        "value": obs_value,
    }
    if extra_payload:
        payload.update(extra_payload)
    return VisibleHistory(
        (
            CandidateVisibleEvent(
                EventKind.OBSERVATION_AVAILABLE,
                0,
                0,
                "visible-event-0",
                payload,
                collected_at=0,
            ),
            CandidateVisibleEvent(
                EventKind.OBSERVATION_AVAILABLE,
                0,
                0,
                "visible-event-1",
                {
                    "check_id": "Q1",
                    "assay_slot": 2 if heldout_assay_slots else 1,
                    "channel_id": "obs_1",
                    "value": obs_value,
                },
                collected_at=0,
            ),
        ),
        0,
        _digest("catalog"),
    )


def _member(alias: str, semantic: SourceMemberSemantic) -> SourceMemberDraft:
    return SourceMemberDraft(
        alias,
        semantic,
        {"trajectory_cell": alias, "clinical_value": 0.5},
    )


_DIMENSION_BY_LABEL = {
    "boundary_tail": AllocationDimension.BOUNDARY_TAIL,
    "compositional_holdout": AllocationDimension.COMPOSITIONAL_HOLDOUT,
    "schedule_time_holdout": AllocationDimension.SCHEDULE_TIME_HOLDOUT,
    "policy_coverage_holdout": AllocationDimension.POLICY_COVERAGE_HOLDOUT,
    "extension_check": AllocationDimension.EXTENSION_CHECK,
    "extension_treatment": AllocationDimension.EXTENSION_TREATMENT,
    "mechanism_ood": AllocationDimension.MECHANISM_OOD,
}


def _positive_value(world: str, dimension: AllocationDimension) -> AllocationCellValue:
    if world == "W10" and dimension is AllocationDimension.COMPOSITIONAL_HOLDOUT:
        return AllocationCellValue.HELDOUT_HOST_MECHANISM
    if world == "W18" and dimension is AllocationDimension.BOUNDARY_TAIL:
        return AllocationCellValue.FROZEN_BOUNDARY
    if world == "W18" and dimension is AllocationDimension.MECHANISM_OOD:
        return AllocationCellValue.SEALED_NOVEL_MECHANISM
    if world == "W19" and dimension is AllocationDimension.BOUNDARY_TAIL:
        return AllocationCellValue.RARE_TAIL
    return AllocationCellValue.HOLDOUT


def _support_value(world: str, dimension: AllocationDimension) -> AllocationCellValue:
    if world == "W18" and dimension is AllocationDimension.MECHANISM_OOD:
        return AllocationCellValue.KNOWN_MECHANISM
    if world == "W19" and dimension is AllocationDimension.BOUNDARY_TAIL:
        return AllocationCellValue.COMMON
    return AllocationCellValue.SUPPORT


def _allocation_cells(
    world: str,
    overrides: dict[AllocationDimension, AllocationCellValue] | None = None,
) -> tuple[SlotAllocationCell, ...]:
    public_only = {
        ("W03", "boundary_tail"),
        ("W14", "boundary_tail"),
        ("W15", "boundary_tail"),
        ("W16", "boundary_tail"),
        ("W16", "extension_check"),
        ("W17", "boundary_tail"),
        ("W17", "extension_treatment"),
    }
    topology_only = {("W20", "boundary_tail")}
    values: dict[AllocationDimension, AllocationCellValue] = {}
    for label in WORLD_DECLARED_STRATA[world]:
        if (
            label in {"iid_support", "behavior_pair"}
            or (world, label) in public_only
            or (world, label) in topology_only
        ):
            continue
        dimension = _DIMENSION_BY_LABEL[label]
        values[dimension] = _positive_value(world, dimension)
    if world == "W20":
        values[AllocationDimension.SCHEDULE_TIME_HOLDOUT] = AllocationCellValue.SUPPORT
        values[AllocationDimension.POLICY_COVERAGE_HOLDOUT] = AllocationCellValue.SUPPORT
    if overrides:
        values.update(overrides)
    return tuple(
        SlotAllocationCell(_DIMENSION_BY_LABEL[label], values[_DIMENSION_BY_LABEL[label]])
        for label in WORLD_DECLARED_STRATA[world]
        if label not in {"iid_support", "behavior_pair"}
        and (world, label) not in public_only
        and (world, label) not in topology_only
    )


def _build_source(
    world: str,
    cells: tuple[SlotAllocationCell, ...] | None = None,
    *,
    history: VisibleHistory | None = None,
    with_pair: bool = True,
    pair_semantic: PairSemantic = PairSemantic.BEHAVIORAL,
    w19_size: int = 64,
    w19_tail_indices: frozenset[int] = frozenset({0}),
    same_member_extra_slot: bool = False,
    same_pair_member_extra_slot: bool = False,
    include_dormant_member: bool = False,
    recipe_payload: dict | None = None,
    slot_cell_overrides: dict[
        str, tuple[SlotAllocationCell, ...]
    ] | None = None,
):
    history = history or _history()
    cells = cells or _allocation_cells(world)
    slot_cells: dict[str, tuple[SlotAllocationCell, ...]] = {}
    slot_cell_overrides = slot_cell_overrides or {}

    def cells_for(alias: str, *, w19_tail: bool | None = None):
        resolved = cells
        if w19_tail is not None:
            resolved = _allocation_cells(
                world,
                {
                    AllocationDimension.BOUNDARY_TAIL: (
                        AllocationCellValue.RARE_TAIL
                        if w19_tail
                        else AllocationCellValue.COMMON
                    )
                },
            )
        resolved = slot_cell_overrides.get(alias, resolved)
        slot_cells[alias] = resolved
        return resolved

    if world == "W19":
        drafts = tuple(
            ProducerSourceUnitDraft(
                f"w19-family-{index:03d}",
                "W19",
                SourceUnitSemantic.PATIENT_FAMILY,
                recipe_payload or {"recipe": "w19-frozen-quota-row"},
                1,
                (
                    _member(
                        "assignment-row",
                        SourceMemberSemantic.W19_ASSIGNMENT_ROW,
                    ),
                ),
            )
            for index in range(w19_size)
        )
        transcripts = tuple(
            BuilderRandomnessTranscript(
                draft.unit_alias,
                "fixture-family-builder",
                f"build-w19-{index:03d}",
                {"draws": [index, 1]},
                {"draws": [index, 2]},
                {"draws": [index, 3]},
            )
            for index, draft in enumerate(drafts)
        )
        cluster_ranges = tuple(
            range(start, min(start + 64, w19_size))
            for start in range(0, w19_size, 64)
        )
        links = tuple(
            AtomicLinkDraft(
                f"w19-quota-cluster-{cluster_index}",
                AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER,
                tuple(
                    MemberRefDraft(drafts[index].unit_alias, "assignment-row")
                    for index in cluster_range
                ),
            )
            for cluster_index, cluster_range in enumerate(cluster_ranges)
        )
        pairs = ()
        slots_list = []
        for index, draft in enumerate(drafts):
            alias = f"w19-slot-{index:03d}"
            resolved_cells = cells_for(
                alias,
                w19_tail=index in w19_tail_indices,
            )
            slots_list.append(
                MaterializationSlotDraft(
                    alias,
                    draft.unit_alias,
                    "assignment-row",
                    MaterializationRole.W19_ASSIGNMENT_ROW,
                    "sealed-test",
                    _digest(f"w19-cut-{index:03d}"),
                    _digest(f"w19-query-{index:03d}"),
                    atomic_link_alias=f"w19-quota-cluster-{index // 64}",
                    row_bundle_commitment_digest=_row_bundle_commitment(
                        index,
                        history,
                    ),
                    strata_allocation_commitment_digest=(
                        compute_slot_strata_allocation_commitment(
                            world,
                            resolved_cells,
                        )
                    ),
                )
            )
        slots = tuple(slots_list)
    else:
        alias = f"{world.lower()}-family"
        members = [
            _member("left", SourceMemberSemantic.COUNTERFACTUAL_VARIANT),
            _member("right", SourceMemberSemantic.COUNTERFACTUAL_VARIANT),
            _member("ordinary", SourceMemberSemantic.PATIENT_TRAJECTORY),
        ]
        if include_dormant_member:
            members.append(
                _member("dormant", SourceMemberSemantic.PATIENT_TRAJECTORY)
            )
        drafts = (
            ProducerSourceUnitDraft(
                alias,
                world,
                SourceUnitSemantic.PATIENT_FAMILY,
                recipe_payload or {"recipe": "ordinary-strata-fixture"},
                3,
                tuple(members),
            ),
        )
        transcripts = (
            BuilderRandomnessTranscript(
                alias,
                "fixture-family-builder",
                f"build-{world}",
                {"draws": [0.1]},
                {"draws": [0.2]},
                {"draws": [0.3]},
            ),
        )
        pairs = (
            (
                PairConstraintDraft(
                    f"{world.lower()}-pair",
                    pair_semantic,
                    (
                        PairSideDraft(alias, "left", 0),
                        PairSideDraft(alias, "right", 1),
                    ),
                ),
            )
            if with_pair
            else ()
        )
        links = ()
        raw_slot_specs = [
            (
                f"{world.lower()}-left-slot",
                "left",
                MaterializationRole.PAIR_SIDE,
                "sealed-test",
                _digest(f"{world}-pair-cut"),
                _digest(f"{world}-pair-query"),
                f"{world.lower()}-pair",
                0,
            ),
            (
                f"{world.lower()}-right-slot",
                "right",
                MaterializationRole.PAIR_SIDE,
                "sealed-test",
                _digest(f"{world}-pair-cut"),
                _digest(f"{world}-pair-query"),
                f"{world.lower()}-pair",
                1,
            ),
            (
                f"{world.lower()}-ordinary-slot",
                "ordinary",
                MaterializationRole.STANDARD_ROW,
                "sealed-test",
                _digest(f"{world}-ordinary-cut"),
                _digest(f"{world}-ordinary-query"),
                None,
                None,
            ),
        ]
        slots_list = []
        for ordinal, spec in enumerate(raw_slot_specs):
            (
                slot_alias,
                member_alias,
                role,
                stage,
                cut,
                query,
                pair_alias,
                pair_side,
            ) = spec
            resolved_cells = cells_for(slot_alias)
            slots_list.append(
                MaterializationSlotDraft(
                    slot_alias,
                    alias,
                    member_alias,
                    role,
                    stage,
                    cut,
                    query,
                    pair_alias,
                    pair_side,
                    row_bundle_commitment_digest=_row_bundle_commitment(
                        ordinal,
                        history,
                    ),
                    strata_allocation_commitment_digest=(
                        compute_slot_strata_allocation_commitment(
                            world,
                            resolved_cells,
                        )
                    ),
                )
            )
        slots = tuple(slots_list)
        if not with_pair:
            slots = tuple(
                replace(
                    slot,
                    materialization_role=MaterializationRole.STANDARD_ROW,
                    pair_alias=None,
                    pair_side=None,
                )
                for slot in slots
            )
        if same_member_extra_slot:
            slot_alias = f"{world.lower()}-ordinary-recheck-slot"
            resolved_cells = cells_for(slot_alias)
            slots = (
                *slots,
                MaterializationSlotDraft(
                    slot_alias,
                    alias,
                    "ordinary",
                    MaterializationRole.STANDARD_ROW,
                    "sealed-test",
                    _digest(f"{world}-ordinary-cut"),
                    _digest(f"{world}-ordinary-recheck-query"),
                    row_bundle_commitment_digest=_row_bundle_commitment(3, history),
                    strata_allocation_commitment_digest=(
                        compute_slot_strata_allocation_commitment(
                            world,
                            resolved_cells,
                        )
                    ),
                ),
            )
        if same_pair_member_extra_slot:
            ordinal = len(slots)
            slot_alias = f"{world.lower()}-left-unpaired-recheck-slot"
            resolved_cells = cells_for(slot_alias)
            slots = (
                *slots,
                MaterializationSlotDraft(
                    slot_alias,
                    alias,
                    "left",
                    MaterializationRole.STANDARD_ROW,
                    "sealed-test-unpaired-recheck",
                    _digest(f"{world}-left-unpaired-recheck-cut"),
                    _digest(f"{world}-left-unpaired-recheck-query"),
                    row_bundle_commitment_digest=_row_bundle_commitment(
                        ordinal,
                        history,
                    ),
                    strata_allocation_commitment_digest=(
                        compute_slot_strata_allocation_commitment(
                            world,
                            resolved_cells,
                        )
                    ),
                ),
            )
    source = build_pre_split_family_source(
        benchmark_id="ucm-benchmark-v1",
        benchmark_revision="PRE-FREEZE-v1",
        registry_digest=_digest("registry"),
        generator_bundle_digest=_digest(f"generator-bundle-{world}"),
        topology_contract_digest=_digest("topology-contract"),
        query_contract_digest=_digest("query-contract"),
        builder_id="fixture-family-builder",
        builder_version="fixture-v2",
        drafts=drafts,
        transcripts=transcripts,
        pair_topology=pairs,
        atomic_links=links,
        materialization_slots=slots,
    )
    return source, slot_cells


def _assignment(source, split: FamilySplit = FamilySplit.SEALED_TEST):
    return build_weighted_atomic_assignment(
        source,
        {unit.authority_digest: split for unit in source.units},
        split_policy_digest=_digest("split-policy"),
        split_seed_commitment=_digest("split-seed-commitment"),
    )


def _ledger(source, assignment, history: VisibleHistory):
    evidences = []
    assignments_by_authority = {
        item.authority_digest: item for item in assignment.assignments
    }
    for ordinal, slot in enumerate(source.materialization_slots):
        assigned = assignments_by_authority.get(slot.reference.authority_digest)
        assert assigned is not None
        label = f"row-{ordinal}"
        evidences.append(
            RowMaterializationEvidence(
                record_id=label,
                assigned_split=assigned.assigned_split,
                authority_digest=slot.reference.authority_digest,
                member_digest=slot.reference.member_digest,
                public_history_digest=history.digest,
                hidden_state_at_cut_digest=_digest(f"hidden-{label}"),
                query_cell_digest=slot.query_cell_digest,
                oracle_target_digest=_digest(f"oracle-{label}"),
                candidate_row_digest=_digest(f"candidate-{label}"),
                judge_row_digest=_digest(f"judge-{label}"),
                raw_request_digest=_digest(f"request-{label}"),
                raw_response_digest=_digest(f"response-{label}"),
                materialization_slot_digest=slot.slot_digest,
                cut_digest=slot.cut_digest,
                stage_label=slot.stage_label,
                materialization_role=slot.materialization_role,
                pair_digest=slot.pair_digest,
                pair_side=slot.pair_side,
                atomic_link_digest=slot.atomic_link_digest,
            )
        )
    receipts = issue_materialization_receipt_batch(
        source,
        assignment,
        tuple(evidences),
    )
    return build_materialization_receipt_ledger(
        source,
        assignment,
        receipts,
    )


def _allocation_manifest(
    source,
    world: str,
    slot_cells: dict[str, tuple[SlotAllocationCell, ...]],
):
    return build_pre_split_strata_allocation_manifest(
        family_source=source,
        world_slot=world,
        generator_source_digest=_digest(f"generator-source-{world}"),
        allocation_policy_digest=_digest(f"allocation-policy-{world}"),
        builder_id="fixture-strata-builder",
        builder_version="fixture-v1",
        slot_drafts=tuple(
            SlotAllocationDraft(slot.slot_digest, slot_cells[slot.slot_alias])
            for slot in source.materialization_slots
        ),
    )


def _authority(
    world: str = "W03",
    *,
    cell_overrides: dict[
        AllocationDimension, AllocationCellValue
    ] | None = None,
    slot_cell_overrides: dict[
        str, tuple[SlotAllocationCell, ...]
    ] | None = None,
    history: VisibleHistory | None = None,
    with_pair: bool = True,
    pair_semantic: PairSemantic = PairSemantic.BEHAVIORAL,
    w19_size: int = 64,
    w19_tail_indices: frozenset[int] = frozenset({0}),
    split: FamilySplit = FamilySplit.SEALED_TEST,
    same_member_extra_slot: bool = False,
    same_pair_member_extra_slot: bool = False,
    include_dormant_member: bool = False,
):
    cacheable = (
        cell_overrides is None
        and slot_cell_overrides is None
        and history is None
        and with_pair
        and pair_semantic is PairSemantic.BEHAVIORAL
        and w19_size == 64
        and w19_tail_indices == frozenset({0})
        and split is FamilySplit.SEALED_TEST
        and world != "W19"
        and not same_member_extra_slot
        and not same_pair_member_extra_slot
        and not include_dormant_member
    )
    if cacheable and world in _DEFAULT_AUTHORITY_CACHE:
        return _DEFAULT_AUTHORITY_CACHE[world]

    history = history or _history()
    cells = _allocation_cells(world, cell_overrides)
    source, slot_cells = _build_source(
        world,
        cells,
        history=history,
        with_pair=with_pair,
        pair_semantic=pair_semantic,
        w19_size=w19_size,
        w19_tail_indices=w19_tail_indices,
        same_member_extra_slot=same_member_extra_slot,
        same_pair_member_extra_slot=same_pair_member_extra_slot,
        include_dormant_member=include_dormant_member,
        slot_cell_overrides=slot_cell_overrides,
    )
    allocation_manifest = _allocation_manifest(source, world, slot_cells)
    assignment = _assignment(source, split)
    ledger = _ledger(source, assignment, history)
    public = PublicClassifierAuthority(
        source.benchmark_id,
        source.benchmark_revision,
        world,
        f"{world.lower()}-public-classifier",
        "fixture-v1",
        _digest(f"public-classifier-source-{world}"),
    )
    judge = JudgeStrataAuthority(
        source,
        assignment,
        world,
        _digest(f"definition-source-{world}"),
        allocation_manifest,
        ledger,
    )
    authority = DualChannelStrataAuthority(public, judge)
    if cacheable:
        _DEFAULT_AUTHORITY_CACHE[world] = authority
    return authority


def _join(
    authority: DualChannelStrataAuthority,
    index: int = 0,
    history: VisibleHistory | None = None,
):
    return StrataRowJoin(
        authority.judge.materialization_ledger.receipts[index],
        history or _history(),
    )


def _all_receipts(authority: DualChannelStrataAuthority):
    return issue_strata_row_receipt_batch(
        authority,
        tuple(
            _join(authority, index)
            for index in range(
                len(authority.judge.materialization_ledger.receipts)
            )
        ),
    )


def test_real_visible_history_and_exact_family_receipt_join() -> None:
    world = WORLD_REGISTRY["W03"].panels[0].instantiate()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 12345, 4)
    assert world.strata_for_episode(episode) == ("iid_support", "boundary_tail")
    authority = _authority("W03", history=episode.public_history)
    join = _join(authority, history=episode.public_history)
    receipt = issue_strata_row_receipt(authority, join)
    wire = receipt.to_wire()
    assert authority.judge.to_wire()[
        "family_materialization_ledger_digest"
    ] == authority.judge.materialization_ledger.ledger_digest
    assert wire["row_join"]["public_history"] == episode.public_history.to_wire()
    assert join.cut_digest == join.family_receipt.evidence.cut_digest
    assert wire["row_join"]["family_materialization_receipt_digest"] == (
        join.family_receipt.receipt_digest
    )
    assert receipt.combined_labels == (
        "iid_support",
        "boundary_tail",
        "behavior_pair",
    )


def test_world_declared_strata_exactly_match_the_w01_w20_registry() -> None:
    assert WORLD_DECLARED_STRATA == {
        world_slot: declaration.panels[0].strata
        for world_slot, declaration in WORLD_REGISTRY.items()
    }


def test_boundary_authority_channel_table_is_closed_for_all_twenty_worlds() -> None:
    expected_public = {"W03", "W14", "W15", "W16", "W17"}
    for world_slot in WORLD_DECLARED_STRATA:
        authority = _live_public_authority(world_slot, "channel-table")
        boundary = next(
            (
                definition
                for definition in authority.definitions
                if definition.label == "boundary_tail"
            ),
            None,
        )
        if world_slot in expected_public:
            assert boundary is not None
            assert boundary.channel is StratumChannel.PUBLIC_REPLAYABLE
        elif world_slot == "W18":
            assert boundary is not None
            assert boundary.channel is StratumChannel.DUAL_CONJUNCTION
        else:
            assert boundary is None

    assert not hasattr(PublicRuleKind, "CODE_OWNED_BOUNDARY_EVIDENCE")


def test_allocation_entry_api_accepts_only_receipt_and_typed_manifest() -> None:
    authority = _authority("W03")
    receipt = authority.judge.materialization_ledger.receipts[0]
    assert tuple(inspect.signature(build_generator_allocation_entry).parameters) == (
        "materialization_receipt",
        "allocation_manifest",
    )
    entry = build_generator_allocation_entry(
        receipt,
        authority.judge.allocation_manifest,
    )
    assert entry.receipt_digest == receipt.receipt_digest
    assert set(GeneratorAllocationEntry.__dataclass_fields__) == {
        "materialization_receipt",
        "allocation_manifest",
    }
    with pytest.raises(TypeError):
        build_generator_allocation_entry(  # type: ignore[call-arg]
            receipt,
            allocation_facts={"mechanism_cell": "forged"},
        )


def test_entry_lookup_disambiguates_same_member_and_cut_by_slot_and_receipt() -> None:
    authority = _authority(
        "W03",
        with_pair=False,
        same_member_extra_slot=True,
    )
    grouped: dict[tuple[str, str, str], list] = {}
    for receipt in authority.judge.materialization_ledger.receipts:
        evidence = receipt.evidence
        assert evidence.cut_digest is not None
        grouped.setdefault(
            (
                evidence.authority_digest,
                evidence.member_digest,
                evidence.cut_digest,
            ),
            [],
        ).append(receipt)
    first, second = next(
        receipts for receipts in grouped.values() if len(receipts) == 2
    )
    first_evidence = first.evidence
    second_evidence = second.evidence
    assert first_evidence.materialization_slot_digest != (
        second_evidence.materialization_slot_digest
    )

    found = authority.judge.entry_for(
        first_evidence.authority_digest,
        first_evidence.member_digest,
        first_evidence.cut_digest,
        first_evidence.materialization_slot_digest,
        first.receipt_digest,
    )
    assert found is not None
    assert found.receipt_digest == first.receipt_digest
    assert authority.judge.entry_for(
        first_evidence.authority_digest,
        first_evidence.member_digest,
        first_evidence.cut_digest,
        second_evidence.materialization_slot_digest,
        first.receipt_digest,
    ) is None
    assert authority.judge.entry_for(
        first_evidence.authority_digest,
        first_evidence.member_digest,
        first_evidence.cut_digest,
        first_evidence.materialization_slot_digest,
        second.receipt_digest,
    ) is None

    forged_receipt = copy.copy(first)
    object.__setattr__(
        forged_receipt,
        "evidence",
        replace(
            first_evidence,
            materialization_slot_digest=(
                second_evidence.materialization_slot_digest
            ),
        ),
    )
    forged_entry = object.__new__(GeneratorAllocationEntry)
    object.__setattr__(
        forged_entry,
        "materialization_receipt",
        forged_receipt,
    )
    object.__setattr__(
        forged_entry,
        "allocation_manifest",
        authority.judge.allocation_manifest,
    )
    with pytest.raises(ProtocolViolation):
        authority.judge.classify(forged_entry)


def test_judge_membership_is_derived_from_committed_typed_slot_cells() -> None:
    matched = _authority("W10")
    unmatched = _authority(
        "W10",
        cell_overrides={
            AllocationDimension.COMPOSITIONAL_HOLDOUT: AllocationCellValue.SUPPORT
        },
    )
    assert (
        matched.judge.family_source.source_digest
        != unmatched.judge.family_source.source_digest
    )
    assert "compositional_holdout" in issue_strata_row_receipt(
        matched, _join(matched)
    ).judge_result.judge_frozen_labels
    assert "compositional_holdout" not in issue_strata_row_receipt(
        unmatched, _join(unmatched)
    ).judge_result.judge_frozen_labels
    assert "allocation_cells" not in matched.judge.family_source.units[0].recipe_payload
    slot = matched.judge.family_source.materialization_slots[0]
    allocation = matched.judge.allocation_manifest.entry_for_slot(slot.slot_digest)
    assert allocation is not None
    assert slot.strata_allocation_commitment_digest == (
        allocation.allocation_commitment_digest
    )


def test_typed_allocation_manifest_exactly_covers_physical_slots() -> None:
    authority = _authority("W03", history=_history())
    manifest = authority.judge.allocation_manifest
    drafts = tuple(
        SlotAllocationDraft(
            entry.materialization_slot_digest,
            entry.cells,
        )
        for entry in manifest.entries
    )
    kwargs = {
        "family_source": authority.judge.family_source,
        "world_slot": "W03",
        "generator_source_digest": manifest.generator_source_digest,
        "allocation_policy_digest": manifest.allocation_policy_digest,
        "builder_id": "fixture-strata-builder",
        "builder_version": "fixture-v1",
    }
    with pytest.raises(ProtocolViolation, match="exactly cover"):
        build_pre_split_strata_allocation_manifest(
            **kwargs,
            slot_drafts=drafts[:-1],
        )
    with pytest.raises(ProtocolViolation, match="duplicate"):
        build_pre_split_strata_allocation_manifest(
            **kwargs,
            slot_drafts=(*drafts, drafts[0]),
        )
    with pytest.raises(ProtocolViolation, match="exactly cover"):
        build_pre_split_strata_allocation_manifest(
            **kwargs,
            slot_drafts=(
                *drafts[:-1],
                SlotAllocationDraft(_digest("foreign-slot"), drafts[-1].cells),
            ),
        )
    first, second, *rest = manifest.entries
    cross_bound = (
        replace(first, materialization_slot=second.materialization_slot),
        replace(second, materialization_slot=first.materialization_slot),
        *rest,
    )
    with pytest.raises(ProtocolViolation, match="entry digest"):
        replace(
            manifest,
            entries=tuple(
                sorted(
                    cross_bound,
                    key=lambda entry: entry.materialization_slot_digest,
                )
            ),
        )


def test_public_boundary_cannot_be_hidden_in_slot_allocation() -> None:
    with pytest.raises(ProtocolViolation, match="exactly cover"):
        compute_slot_strata_allocation_commitment(
            "W03",
            (
                SlotAllocationCell(
                    AllocationDimension.BOUNDARY_TAIL,
                    AllocationCellValue.HOLDOUT,
                ),
            ),
        )


def test_w01_boundary_is_judge_allocation_not_a_public_float_proxy() -> None:
    world = WORLD_REGISTRY["W01"].panels[0].instantiate()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 12345, 0)
    assert "boundary_tail" in world.strata_for_episode(episode)

    positive = _authority("W01", history=episode.public_history)
    positive_receipt = issue_strata_row_receipt(
        positive,
        _join(positive, history=episode.public_history),
    )
    assert "boundary_tail" not in positive_receipt.public_result.labels
    assert "boundary_tail" in positive_receipt.judge_result.judge_frozen_labels
    assert "boundary_tail" in positive_receipt.combined_labels

    support = _authority(
        "W01",
        history=episode.public_history,
        cell_overrides={
            AllocationDimension.BOUNDARY_TAIL: AllocationCellValue.SUPPORT
        },
    )
    support_receipt = issue_strata_row_receipt(
        support,
        _join(support, history=episode.public_history),
    )
    assert "boundary_tail" not in support_receipt.public_result.labels
    assert "boundary_tail" not in support_receipt.combined_labels


def _live_public_authority(world_slot: str, suffix: str) -> PublicClassifierAuthority:
    return PublicClassifierAuthority(
        "ucm-benchmark-v1",
        "registry-live-cross-regression",
        world_slot,
        f"live-{world_slot.lower()}-{suffix}",
        "v1",
        _digest(f"live-public-source-{world_slot}-{suffix}"),
    )


@pytest.mark.parametrize(
    ("world_slot", "panel_index", "positive_split", "positive_index", "negative_split", "negative_index"),
    [
        ("W03", 0, WorldSplit.SEALED_TEST, 4, WorldSplit.TRAIN, 0),
        ("W14", 0, WorldSplit.TRAIN, 3, WorldSplit.TRAIN, 0),
        # These two rows deliberately lock the non-union W15 panel behavior:
        # W15A index 1 reaches |obs_0|>=.9 but remains below its 1.20 tail;
        # W15B index 34 has |obs_0| in [.9,1.2) and is a B-only tail.
        ("W15", 0, WorldSplit.TRAIN, 0, WorldSplit.TRAIN, 1),
        ("W15", 1, WorldSplit.TRAIN, 34, WorldSplit.TRAIN, 0),
        ("W16", 0, WorldSplit.TRAIN, 12, WorldSplit.TRAIN, 0),
        ("W17", 0, WorldSplit.TRAIN, 3, WorldSplit.TRAIN, 0),
        ("W18", 0, WorldSplit.SEALED_TEST, 0, WorldSplit.TRAIN, 0),
    ],
)
def test_live_public_boundary_rules_are_isomorphic_to_served_worlds(
    world_slot: str,
    panel_index: int,
    positive_split: WorldSplit,
    positive_index: int,
    negative_split: WorldSplit,
    negative_index: int,
) -> None:
    world = WORLD_REGISTRY[world_slot].panels[panel_index].instantiate()
    authority = _live_public_authority(world_slot, f"panel-{panel_index}")
    for split, index, expected in (
        (positive_split, positive_index, True),
        (negative_split, negative_index, False),
    ):
        episode = world.generate_episode(split, 12345, index)
        live = "boundary_tail" in world.strata_for_episode(episode)
        replay = "boundary_tail" in authority.classify(episode.public_history)
        assert live is expected
        assert replay is live

    for split in WorldSplit:
        for index in range(64):
            episode = world.generate_episode(split, 12345, index)
            expected_public_boundary = (
                world.public_ood_attributable(episode)
                or world.attribution_tag(episode) == "KNOWN_EXTREME"
                if world_slot == "W18"
                else "boundary_tail" in world.strata_for_episode(episode)
            )
            assert (
                "boundary_tail" in authority.classify(episode.public_history)
            ) is expected_public_boundary

    if world_slot == "W16":
        assert "extension_check" in authority.classify(
            world.generate_episode(negative_split, 12345, negative_index).public_history
        )
    if world_slot == "W17":
        assert "extension_treatment" in authority.classify(
            world.generate_episode(negative_split, 12345, negative_index).public_history
        )


def test_w03_public_boundary_requires_the_exact_live_sparse_timeline() -> None:
    world = WORLD_REGISTRY["W03"].panels[0].instantiate()
    authority = _live_public_authority("W03", "sparse-timeline")
    positive = world.generate_episode(WorldSplit.SEALED_TEST, 12345, 4)
    ordinary = world.generate_episode(WorldSplit.TRAIN, 12345, 0)
    assert "boundary_tail" in authority.classify(positive.public_history)
    assert "boundary_tail" not in authority.classify(ordinary.public_history)

    delayed_events = tuple(
        replace(event, available_at=-1)
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == "obs_0"
        and event.collected_at == -2
        else event
        for event in ordinary.public_history.events
    )
    delayed = VisibleHistory(
        tuple(sorted(delayed_events, key=event_sort_key)),
        ordinary.public_history.as_of_available_at,
        ordinary.public_history.catalog_digest,
    )
    assert "boundary_tail" not in authority.classify(delayed)

    other_missing = VisibleHistory(
        tuple(
            event
            for event in ordinary.public_history.events
            if not (
                event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.payload.get("channel_id") == "obs_0"
                and event.collected_at == -3
            )
        ),
        ordinary.public_history.as_of_available_at,
        ordinary.public_history.catalog_digest,
    )
    assert "boundary_tail" not in authority.classify(other_missing)


@pytest.mark.parametrize(
    ("world_slot", "boundary_index"),
    [
        ("W01", 0),
        ("W02", 1),
        ("W04", 2),
        ("W05", 0),
        ("W06", 14),
        ("W07", 30),
        ("W08", 1),
        ("W09", 4),
        ("W10", 5),
        ("W11", 14),
        ("W12", 5),
        ("W13", 0),
        ("W19", 50),
        ("W20", 10),
    ],
)
def test_live_judge_boundary_worlds_never_self_label_on_the_public_channel(
    world_slot: str,
    boundary_index: int,
) -> None:
    world = WORLD_REGISTRY[world_slot].panels[0].instantiate()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 12345, boundary_index)
    assert "boundary_tail" in world.strata_for_episode(episode)
    labels = _live_public_authority(world_slot, "judge-boundary").classify(
        episode.public_history
    )
    assert "boundary_tail" not in labels


def test_w10_live_compositional_public_half_matches_served_subset_rule() -> None:
    world = WORLD_REGISTRY["W10"].panels[0].instantiate()
    authority = _live_public_authority("W10", "compositional")
    positive = world.generate_episode(WorldSplit.SEALED_TEST, 12345, 12)
    negative = world.generate_episode(WorldSplit.SEALED_TEST, 12345, 5)
    for episode in (positive, negative):
        assert (
            "compositional_holdout" in authority.classify(episode.public_history)
        ) is ("compositional_holdout" in world.strata_for_episode(episode))
    for split in WorldSplit:
        for index in range(64):
            episode = world.generate_episode(split, 12345, index)
            assert (
                "compositional_holdout" in authority.classify(
                    episode.public_history
                )
            ) is ("compositional_holdout" in world.strata_for_episode(episode))


def test_two_slots_for_same_member_and_cut_can_have_distinct_allocations() -> None:
    extra_alias = "w12-ordinary-recheck-slot"
    authority = _authority(
        "W12",
        with_pair=False,
        same_member_extra_slot=True,
        slot_cell_overrides={
            extra_alias: _allocation_cells(
                "W12",
                {
                    AllocationDimension.COMPOSITIONAL_HOLDOUT: (
                        AllocationCellValue.SUPPORT
                    )
                },
            )
        },
    )
    slots = {
        slot.slot_alias: slot for slot in authority.judge.family_source.materialization_slots
    }
    positive_slot = slots["w12-ordinary-slot"]
    support_slot = slots[extra_alias]
    assert positive_slot.reference == support_slot.reference
    assert positive_slot.cut_digest == support_slot.cut_digest
    assert positive_slot.slot_digest != support_slot.slot_digest
    receipts = {
        receipt.evidence.materialization_slot_digest: receipt
        for receipt in authority.judge.materialization_ledger.receipts
    }
    assert "compositional_holdout" in authority.judge.classify(
        GeneratorAllocationEntry(
            receipts[positive_slot.slot_digest],
            authority.judge.allocation_manifest,
        )
    )
    assert "compositional_holdout" not in authority.judge.classify(
        GeneratorAllocationEntry(
            receipts[support_slot.slot_digest],
            authority.judge.allocation_manifest,
        )
    )


@pytest.mark.parametrize(
    "forged_key",
    [
        "allocation_cells",
        "allocationCells",
        "strata",
        "stratumLabel",
        "judgeFrozenLabels",
        "boundaryTailCell",
        "policyCoverageHoldoutCell",
    ],
)
def test_recipe_payload_cannot_supply_strata_authority(forged_key: str) -> None:
    cells = _allocation_cells("W03")
    source, slot_cells = _build_source(
        "W03",
        cells,
        recipe_payload={"clinical": {forged_key: "forged"}},
    )
    with pytest.raises(ProtocolViolation, match="recipe payload cannot supply"):
        _allocation_manifest(source, "W03", slot_cells)


def test_recipe_text_value_is_not_scanned_as_allocation_authority() -> None:
    cells = _allocation_cells("W03")
    source, slot_cells = _build_source(
        "W03",
        cells,
        recipe_payload={"clinical_note": "rare-tail"},
    )
    assert _allocation_manifest(source, "W03", slot_cells).manifest_digest


def test_w10_dual_conjunction_requires_both_halves() -> None:
    both = _authority("W10")
    both_receipt = issue_strata_row_receipt(both, _join(both))
    assert "compositional_holdout" in both_receipt.combined_labels

    public_only = _authority(
        "W10",
        cell_overrides={
            AllocationDimension.COMPOSITIONAL_HOLDOUT: AllocationCellValue.SUPPORT
        },
    )
    public_only_receipt = issue_strata_row_receipt(public_only, _join(public_only))
    assert "compositional_holdout" in public_only_receipt.public_result.labels
    assert "compositional_holdout" not in public_only_receipt.combined_labels

    seen_history = _history(heldout_assay_slots=False)
    judge_only = _authority("W10", history=seen_history)
    judge_only_receipt = issue_strata_row_receipt(
        judge_only, _join(judge_only, history=seen_history)
    )
    assert "compositional_holdout" in judge_only_receipt.judge_result.judge_frozen_labels
    assert "compositional_holdout" not in judge_only_receipt.combined_labels

    neither = _authority(
        "W10",
        history=seen_history,
        cell_overrides={
            AllocationDimension.COMPOSITIONAL_HOLDOUT: AllocationCellValue.SUPPORT
        },
    )
    neither_receipt = issue_strata_row_receipt(
        neither,
        _join(neither, history=seen_history),
    )
    assert "compositional_holdout" not in neither_receipt.public_result.labels
    assert "compositional_holdout" not in neither_receipt.judge_result.judge_frozen_labels
    assert "compositional_holdout" not in neither_receipt.combined_labels


def test_w18_dual_boundary_and_mechanism_ood_are_distinct() -> None:
    both = _authority("W18")
    both_cells = {
        cell.dimension: cell.value
        for cell in both.judge.allocation_manifest.entries[0].cells
    }
    assert both_cells[AllocationDimension.BOUNDARY_TAIL] is (
        AllocationCellValue.FROZEN_BOUNDARY
    )
    assert both_cells[AllocationDimension.MECHANISM_OOD] is (
        AllocationCellValue.SEALED_NOVEL_MECHANISM
    )
    assert not hasattr(AllocationCellValue, "FROZEN_EXTREME")
    both_receipt = issue_strata_row_receipt(both, _join(both))
    assert "boundary_tail" in both_receipt.public_result.labels
    assert "boundary_tail" in both_receipt.judge_result.judge_frozen_labels
    assert "boundary_tail" in both_receipt.combined_labels

    authority = _authority(
        "W18",
        cell_overrides={
            AllocationDimension.BOUNDARY_TAIL: AllocationCellValue.SUPPORT
        },
    )
    receipt = issue_strata_row_receipt(authority, _join(authority))
    assert "boundary_tail" in receipt.public_result.labels
    assert "boundary_tail" not in receipt.combined_labels
    assert "mechanism_ood" in receipt.combined_labels

    judge_only_history = _history(obs_value=0.50)
    judge_only = _authority("W18", history=judge_only_history)
    judge_only_receipt = issue_strata_row_receipt(
        judge_only,
        _join(judge_only, history=judge_only_history),
    )
    assert "boundary_tail" in judge_only_receipt.judge_result.judge_frozen_labels
    assert "boundary_tail" not in judge_only_receipt.public_result.labels
    assert "boundary_tail" not in judge_only_receipt.combined_labels

    neither = _authority(
        "W18",
        history=judge_only_history,
        cell_overrides={
            AllocationDimension.BOUNDARY_TAIL: AllocationCellValue.SUPPORT
        },
    )
    neither_receipt = issue_strata_row_receipt(
        neither,
        _join(neither, history=judge_only_history),
    )
    assert "boundary_tail" not in neither_receipt.public_result.labels
    assert "boundary_tail" not in neither_receipt.judge_result.judge_frozen_labels
    assert "boundary_tail" not in neither_receipt.combined_labels


def test_judge_ledger_must_cover_every_source_member_and_pair_side() -> None:
    authority = _authority("W03")
    ledger = authority.judge.materialization_ledger
    assert len(ledger.receipts) == 3
    with pytest.raises(ProtocolViolation, match="exactly cover declared slots"):
        build_materialization_receipt_ledger(
            ledger.source, ledger.assignment, ledger.receipts[:1]
        )
    with pytest.raises(ProtocolViolation, match="exactly cover declared slots"):
        build_materialization_receipt_ledger(
            ledger.source,
            ledger.assignment,
            (ledger.receipts[0], ledger.receipts[2]),
        )


def test_zero_slot_member_needs_no_allocation_or_receipt() -> None:
    authority = _authority(
        "W03",
        include_dormant_member=True,
    )
    source = authority.judge.family_source
    ledger = authority.judge.materialization_ledger
    assert len(authority.judge.allocation_manifest.entries) == len(
        source.materialization_slots
    )
    dormant = next(
        member
        for member in source.units[0].members
        if member.member_alias == "dormant"
    )
    dormant_coverage = next(
        coverage
        for coverage in ledger.member_coverage
        if coverage.member_digest == dormant.member_digest
    )
    assert dormant_coverage.entries == ()
    assert len(_all_receipts(authority)) == len(source.materialization_slots)


def test_judge_ledger_rejects_duplicate_join_record_receipt_and_foreign_source() -> None:
    authority = _authority("W03")
    ledger = authority.judge.materialization_ledger
    with pytest.raises(ProtocolViolation, match="duplicate slot receipt"):
        build_materialization_receipt_ledger(
            ledger.source,
            ledger.assignment,
            (ledger.receipts[0], ledger.receipts[0], *ledger.receipts[1:]),
        )

    foreign = _authority("W03", with_pair=False)
    with pytest.raises(ProtocolViolation, match="foreign source/assignment"):
        replace(
            authority.judge,
            materialization_ledger=foreign.judge.materialization_ledger,
        )


def test_batch_coverage_is_exactly_the_typed_materialization_ledger() -> None:
    authority = _authority("W03")
    receipts = _all_receipts(authority)
    batch = StrataReceiptBatch(authority, receipts)
    assert batch.to_wire()["expected_join_count"] == len(
        authority.judge.materialization_ledger.receipts
    )
    with pytest.raises(ProtocolViolation, match="exactly cover"):
        StrataReceiptBatch(authority, receipts[:-1])
    with pytest.raises(ProtocolViolation, match="duplicate allocation joins"):
        StrataReceiptBatch(authority, (*receipts, receipts[0]))


def test_strata_row_join_has_no_caller_cut_or_membership_fields() -> None:
    assert set(StrataRowJoin.__dataclass_fields__) == {
        "family_receipt",
        "public_history",
    }
    authority = _authority("W03")
    with pytest.raises(TypeError):
        StrataRowJoin(  # type: ignore[call-arg]
            authority.judge.materialization_ledger.receipts[0],
            _history(),
            cut_digest=_digest("posthoc-cut"),
        )


def test_w10_compositional_and_w18_boundary_cells_are_sealed_only() -> None:
    with pytest.raises(ProtocolViolation, match="sealed-test family"):
        _authority("W10", split=FamilySplit.TRAIN)
    with pytest.raises(ProtocolViolation, match="sealed-test family"):
        _authority("W18", split=FamilySplit.VALIDATION)


def test_w18_mechanism_cells_bind_distinct_live_validation_and_sealed_semantics() -> None:
    world = WORLD_REGISTRY["W18"].panels[0].instantiate()
    live_validation = world.generate_episode(WorldSplit.VALIDATION, 12345, 0)
    assert "mechanism_ood" in world.strata_for_episode(live_validation)
    assert "boundary_tail" not in world.strata_for_episode(live_validation)

    validation = _authority(
        "W18",
        split=FamilySplit.VALIDATION,
        history=live_validation.public_history,
        cell_overrides={
            AllocationDimension.BOUNDARY_TAIL: AllocationCellValue.SUPPORT,
            AllocationDimension.MECHANISM_OOD: (
                AllocationCellValue.DEVELOPMENT_ANOMALY_MECHANISM
            ),
        },
    )
    validation_receipt = issue_strata_row_receipt(
        validation,
        _join(validation, history=live_validation.public_history),
    )
    assert "mechanism_ood" in validation_receipt.judge_result.judge_frozen_labels
    assert "boundary_tail" in validation_receipt.public_result.labels
    assert "boundary_tail" not in validation_receipt.combined_labels

    with pytest.raises(ProtocolViolation, match="contradicts its assigned split"):
        _authority(
            "W18",
            split=FamilySplit.TRAIN,
            cell_overrides={
                AllocationDimension.BOUNDARY_TAIL: AllocationCellValue.SUPPORT,
                AllocationDimension.MECHANISM_OOD: (
                    AllocationCellValue.DEVELOPMENT_ANOMALY_MECHANISM
                ),
            },
        )
    with pytest.raises(ProtocolViolation, match="contradicts its assigned split"):
        _authority(
            "W18",
            split=FamilySplit.VALIDATION,
            cell_overrides={
                AllocationDimension.BOUNDARY_TAIL: AllocationCellValue.SUPPORT,
                AllocationDimension.MECHANISM_OOD: (
                    AllocationCellValue.SEALED_NOVEL_MECHANISM
                ),
            },
        )
    with pytest.raises(ProtocolViolation, match="contradicts its assigned split"):
        _authority(
            "W18",
            split=FamilySplit.SEALED_TEST,
            cell_overrides={
                AllocationDimension.BOUNDARY_TAIL: AllocationCellValue.SUPPORT,
                AllocationDimension.MECHANISM_OOD: (
                    AllocationCellValue.DEVELOPMENT_ANOMALY_MECHANISM
                ),
            },
        )


@pytest.mark.parametrize(
    ("boundary_value", "compositional_value"),
    [
        (AllocationCellValue.HOLDOUT, AllocationCellValue.SUPPORT),
        (AllocationCellValue.SUPPORT, AllocationCellValue.HOLDOUT),
    ],
)
def test_w13_threshold_shell_cells_cannot_be_split_apart(
    boundary_value: AllocationCellValue,
    compositional_value: AllocationCellValue,
) -> None:
    with pytest.raises(ProtocolViolation, match="threshold-shell"):
        compute_slot_strata_allocation_commitment(
            "W13",
            _allocation_cells(
                "W13",
                {
                    AllocationDimension.BOUNDARY_TAIL: boundary_value,
                    AllocationDimension.COMPOSITIONAL_HOLDOUT: (
                        compositional_value
                    ),
                },
            ),
        )


def test_family_manifest_and_strata_contract_reject_small_w19_cluster() -> None:
    cells = _allocation_cells("W19")
    with pytest.raises(ProtocolViolation, match="exactly 64"):
        _build_source("W19", cells, w19_size=2)


def test_w19_requires_exactly_64_rows_and_exactly_one_tail() -> None:
    authority = _authority("W19")
    source = authority.judge.family_source
    cluster = source.atomic_links[0]
    assert len(cluster.members) == 64
    assert len(authority.judge.materialization_ledger.receipts) == 64
    source_labels = [
        entry.value_for(AllocationDimension.BOUNDARY_TAIL)
        for entry in authority.judge.allocation_manifest.entries
    ]
    assert source_labels.count(AllocationCellValue.RARE_TAIL) == 1
    assert source_labels.count(AllocationCellValue.COMMON) == 63
    assert "boundary_tail" in authority.judge.classify(
        GeneratorAllocationEntry(
            authority.judge.materialization_ledger.receipts[0],
            authority.judge.allocation_manifest,
        )
    )
    assert "boundary_tail" not in authority.judge.classify(
        GeneratorAllocationEntry(
            authority.judge.materialization_ledger.receipts[1],
            authority.judge.allocation_manifest,
        )
    )
    receipts = _all_receipts(authority)
    assert len(receipts) == 64
    batch = StrataReceiptBatch(authority, receipts)
    assert batch.to_wire()["expected_join_count"] == 64
    with pytest.raises(ProtocolViolation, match="exactly cover"):
        StrataReceiptBatch(authority, receipts[:-1])

    with pytest.raises(ProtocolViolation, match="exactly one RARE_TAIL"):
        _authority(
            "W19",
            w19_size=64,
            w19_tail_indices=frozenset({0, 1}),
        )
    with pytest.raises(ProtocolViolation, match="exactly one RARE_TAIL"):
        _authority(
            "W19",
            w19_size=64,
            w19_tail_indices=frozenset(),
        )
    with pytest.raises(ProtocolViolation, match="AllocationCellValue"):
        SlotAllocationCell(  # type: ignore[arg-type]
            AllocationDimension.BOUNDARY_TAIL,
            "garbage-nontail",
        )


def test_w19_accepts_two_exact_disjoint_64_row_tail_blocks() -> None:
    authority = _authority(
        "W19",
        w19_size=128,
        w19_tail_indices=frozenset({63, 64}),
    )
    manifest_wire = authority.judge.allocation_manifest.to_wire()
    assert len(manifest_wire["w19_blocks"]) == 2
    assert {
        block["rare_tail_slot_digest"] for block in manifest_wire["w19_blocks"]
    } == {
        authority.judge.family_source.materialization_slots[63].slot_digest,
        authority.judge.family_source.materialization_slots[64].slot_digest,
    }
    assert all(
        block["rare_tail_count"] == 1 and block["common_count"] == 63
        for block in manifest_wire["w19_blocks"]
    )
    assert manifest_wire["w19_population_slot_union_digest"] is not None
    assert {
        slot_digest
        for block in manifest_wire["w19_blocks"]
        for slot_digest in block["materialization_slot_digests"]
    } == {
        slot.slot_digest
        for slot in authority.judge.family_source.materialization_slots
        if slot.materialization_role is MaterializationRole.W19_ASSIGNMENT_ROW
    }
    receipts = _all_receipts(authority)
    assert sum(
        "boundary_tail" in item.judge_result.judge_frozen_labels
        for item in receipts
    ) == 2
    assert StrataReceiptBatch(authority, receipts).to_wire()[
        "expected_join_count"
    ] == 128


def test_behavior_pair_comes_only_from_topology_including_w20_response_reversal() -> None:
    no_pair = _authority("W03", with_pair=False)
    assert "behavior_pair" not in issue_strata_row_receipt(
        no_pair, _join(no_pair)
    ).combined_labels
    w20 = _authority("W20", pair_semantic=PairSemantic.RESPONSE_REVERSAL)
    assert all(
        all(cell.dimension is not AllocationDimension.BOUNDARY_TAIL for cell in entry.cells)
        for entry in w20.judge.allocation_manifest.entries
    )
    with pytest.raises(ProtocolViolation, match="exactly cover"):
        compute_slot_strata_allocation_commitment(
            "W20",
            (
                SlotAllocationCell(
                    AllocationDimension.BOUNDARY_TAIL,
                    AllocationCellValue.HOLDOUT,
                ),
                *_allocation_cells("W20"),
            ),
        )
    for index in (0, 1):
        labels = issue_strata_row_receipt(w20, _join(w20, index)).combined_labels
        assert "behavior_pair" in labels
        assert "boundary_tail" in labels
    ordinary_labels = issue_strata_row_receipt(w20, _join(w20, 2)).combined_labels
    assert "behavior_pair" not in ordinary_labels
    assert "boundary_tail" not in ordinary_labels
    wrong_w20_topology = _authority("W20")
    wrong_labels = issue_strata_row_receipt(
        wrong_w20_topology,
        _join(wrong_w20_topology, 0),
    ).combined_labels
    assert "behavior_pair" not in wrong_labels
    assert "boundary_tail" not in wrong_labels
    wrong_non_w20_topology = _authority(
        "W03",
        pair_semantic=PairSemantic.RESPONSE_REVERSAL,
    )
    assert "behavior_pair" not in issue_strata_row_receipt(
        wrong_non_w20_topology,
        _join(wrong_non_w20_topology, 0),
    ).combined_labels

    extra_cut = _authority(
        "W20",
        pair_semantic=PairSemantic.RESPONSE_REVERSAL,
        same_pair_member_extra_slot=True,
    )
    assert "behavior_pair" in issue_strata_row_receipt(
        extra_cut,
        _join(extra_cut, 0),
    ).combined_labels
    assert "behavior_pair" not in issue_strata_row_receipt(
        extra_cut,
        _join(extra_cut, 3),
    ).combined_labels
    assert "boundary_tail" not in issue_strata_row_receipt(
        extra_cut,
        _join(extra_cut, 3),
    ).combined_labels


def test_live_row_local_pair_proxies_never_replace_pre_split_family_topology() -> None:
    custody = make_w16_extension_custody()
    reveal = _open_custody(custody)
    w16 = W16World(
        extension_commitment=custody.public.commitment,
        extension_reveal=reveal,
    )
    w17 = WORLD_REGISTRY["W17"].panels[0].instantiate()
    w18 = WORLD_REGISTRY["W18"].panels[0].instantiate()
    fixtures = (
        ("W16", w16, w16.pre_result_alias_pair()[0]),
        ("W17", w17, w17.extension_split_pair()[0]),
        ("W18", w18, w18.irreducible_alias_pair()[0]),
    )
    for world_slot, world, episode in fixtures:
        assert "behavior_pair" in world.strata_for_episode(episode)
        authority = _authority(
            world_slot,
            with_pair=False,
            history=episode.public_history,
            cell_overrides=(
                {
                    AllocationDimension.BOUNDARY_TAIL: (
                        AllocationCellValue.SUPPORT
                    )
                }
                if world_slot == "W18"
                else None
            ),
        )
        receipt = issue_strata_row_receipt(
            authority,
            _join(authority, history=episode.public_history),
        )
        assert "behavior_pair" not in receipt.public_result.labels
        assert "behavior_pair" not in receipt.judge_result.judge_frozen_labels
        assert "behavior_pair" not in receipt.combined_labels
        extension_label = (
            "extension_check" if world_slot == "W16" else
            "extension_treatment" if world_slot == "W17" else None
        )
        if extension_label is not None:
            assert all(
                entry.cells == ()
                for entry in authority.judge.allocation_manifest.entries
            )
            definition = next(
                item
                for item in authority.public.definitions
                if item.label == extension_label
            )
            assert definition.channel is StratumChannel.PUBLIC_REPLAYABLE
            assert definition.public_rule == PublicRule(PublicRuleKind.ALWAYS)


@pytest.mark.parametrize(
    "key",
    [
        "worldSlot",
        "source-member-id",
        "assignmentUnitDigest",
        "pairGroup",
        "family-source-digest",
        "allocationBucket",
        "mechanismCell",
        "authorityRole",
        "judgeStrata",
        "stratum-control-digest",
        "materializationSlotDigest",
        "queryCellDigest",
        "pairSide",
        "stageLabel",
        "materializationRole",
        "candidateRowDigest",
        "hiddenStateAtCutDigest",
        "evidenceDigest",
        "familyMaterializationReceiptDigest",
        "materializationSlot",
        "slotDigest",
        "slotAlias",
        "pairAlias",
        "assignmentClusterDigests",
        "ledgerDigest",
        "builderId",
        "generatorBundleDigest",
        "registryDigest",
        "sourceMember",
        "unregisteredClinicalDigest",
    ],
)
def test_visible_history_rejects_nested_private_provenance(key: str) -> None:
    with pytest.raises(ProtocolViolation, match="judge-private field"):
        history = _history(extra_payload={key: "forged"})
        authority = _authority("W03", history=history)
        _join(authority, history=history)


@pytest.mark.parametrize(
    "extra_payload",
    [
        {"slotdigest": _digest("leaked-slot")},
        {"materializationslot": "secret-slot"},
        {"generatorbundledigest": _digest("leaked-generator")},
        {"pairaliases": ["secret-pair"]},
        {"assignments": {"row": "sealed_test"}},
        {"metadata": {"opaque": _digest("leaked-through-wrapper")}},
        {"value": _digest("leaked-through-allowed-value")},
    ],
)
def test_typed_public_projection_rejects_alias_and_value_smuggling(
    extra_payload: dict,
) -> None:
    history = _history(extra_payload=extra_payload)
    authority = _authority("W03", history=history)
    with pytest.raises(ProtocolViolation, match="forbidden"):
        _join(authority, history=history)


@pytest.mark.parametrize(
    "extra_payload",
    [
        {"value": "behavior_pair"},
        {"marker": "sealed_test"},
        {"signal": "materialization_slot"},
        {"value": "judge-only-strata"},
    ],
)
def test_public_scalar_values_cannot_carry_control_plane_namespaces(
    extra_payload: dict,
) -> None:
    history = _history(extra_payload=extra_payload)
    authority = _authority("W03", history=history)
    with pytest.raises(ProtocolViolation, match="scalar namespace"):
        _join(authority, history=history)


def test_public_event_uid_cannot_carry_pair_or_split_authority() -> None:
    baseline = _history()
    events = (
        replace(
            baseline.events[0],
            event_uid="behavior_pair:sealed_test",
        ),
        *baseline.events[1:],
    )
    history = VisibleHistory(
        tuple(sorted(events, key=event_sort_key)),
        baseline.as_of_available_at,
        baseline.catalog_digest,
    )
    authority = _authority("W03", history=history)
    with pytest.raises(ProtocolViolation, match="scalar namespace"):
        _join(authority, history=history)


def test_public_event_uid_cannot_carry_an_opaque_authority_digest() -> None:
    baseline = _history()
    events = (
        replace(
            baseline.events[0],
            event_uid=_digest("pair-digest"),
        ),
        *baseline.events[1:],
    )
    history = VisibleHistory(
        tuple(sorted(events, key=event_sort_key)),
        baseline.as_of_available_at,
        baseline.catalog_digest,
    )
    authority = _authority("W03", history=history)
    with pytest.raises(ProtocolViolation, match="digest-shaped"):
        _join(authority, history=history)


def test_public_event_uid_accepts_live_canonical_world_history() -> None:
    world = WORLD_REGISTRY["W03"].panels[0].instantiate()
    history = world.generate_episode(
        WorldSplit.SEALED_TEST,
        12345,
        4,
    ).public_history
    assert history.events
    assert all(not event.event_uid.startswith("sha256:") for event in history.events)
    authority = _authority("W03", history=history)
    assert _join(authority, history=history).public_history is history


def test_public_scalar_namespace_keeps_ordinary_clinical_strings() -> None:
    history = _history(
        extra_payload={
            "marker": "clinical-marker-positive",
            "signal": "observed-signal",
        }
    )
    authority = _authority("W03", history=history)
    assert StrataRowJoin(
        authority.judge.materialization_ledger.receipts[0],
        history,
    ).public_history is history


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        (
            EventKind.PERFORMED_TREATMENT,
            {
                "action_id": "A1",
                "parameters": {
                    "metadata": {"opaque": _digest("parameter-wrapper")}
                },
            },
        ),
        (
            EventKind.PERFORMED_TREATMENT,
            {
                "action_id": "A1",
                "parameters": {
                    "purpose": {"opaque": "private-source-member"}
                },
            },
        ),
        (
            EventKind.OBSERVATION_AVAILABLE,
            {
                "check_id": "Q0",
                "results": [
                    {
                        "channel_id": "obs_0",
                        "value": 0.5,
                        "metadata": {"opaque": "private-slot"},
                    }
                ],
            },
        ),
        (
            EventKind.OBSERVATION_AVAILABLE,
            {
                "check_id": "Q0",
                "results": [
                    {
                        "channel_id": "obs_0",
                        "value": _digest("result-value-smuggling"),
                    }
                ],
            },
        ),
    ],
)
def test_typed_public_projection_closes_parameter_and_result_wrappers(
    kind: EventKind,
    payload: dict,
) -> None:
    history = VisibleHistory(
        (
            CandidateVisibleEvent(
                kind,
                0,
                0,
                "typed-wrapper-event",
                payload,
                collected_at=(
                    0 if kind is EventKind.OBSERVATION_AVAILABLE else None
                ),
            ),
        ),
        0,
        _digest("catalog"),
    )
    authority = _authority("W03", history=history)
    with pytest.raises(ProtocolViolation):
        _join(authority, history=history)


def test_public_history_recursively_revalidates_mutated_event_objects() -> None:
    history = _history()
    authority = _authority("W03", history=history)
    event = history.events[0]
    object.__setattr__(event, "occurred_at", 0.5)
    with pytest.raises(ProtocolViolation, match="occurred_at"):
        StrataRowJoin(
            authority.judge.materialization_ledger.receipts[0],
            history,
        )


def test_dual_rule_semantics_are_code_owned_not_caller_selected() -> None:
    authority = _authority("W10")
    assert "definitions" not in inspect.signature(PublicClassifierAuthority).parameters
    assert "definitions" not in inspect.signature(JudgeStrataAuthority).parameters
    assert not hasattr(PublicRuleKind, "PATH_EQUALS")
    with pytest.raises(TypeError):
        PublicClassifierAuthority(  # type: ignore[call-arg]
            authority.public.benchmark_id,
            authority.public.benchmark_revision,
            "W10",
            "forged-public",
            "v1",
            _digest("forged-public-source"),
            definitions=(
                StratumDefinition(
                    "boundary_tail",
                    StratumChannel.PUBLIC_REPLAYABLE,
                    public_rule=PublicRule(PublicRuleKind.ALWAYS),
                ),
            ),
        )
    with pytest.raises(ProtocolViolation, match="accept no caller"):
        JudgeRule(
            JudgeRuleKind.W10_COMPOSITIONAL_CELL,
            "compositional_cell",
            ("caller-selected-cell",),
        )

    original = authority.public.definitions
    forged = (
        StratumDefinition(
            "iid_support",
            StratumChannel.PUBLIC_REPLAYABLE,
            public_rule=PublicRule(PublicRuleKind.ALWAYS),
        ),
    )
    object.__setattr__(authority.public, "definitions", forged)
    try:
        with pytest.raises(ProtocolViolation):
            authority.public._validate()
    finally:
        object.__setattr__(authority.public, "definitions", original)


def test_allocation_manifest_rejects_mixed_world_source_projection() -> None:
    cells = _allocation_cells("W03")
    commitment = compute_slot_strata_allocation_commitment("W03", cells)
    drafts = (
        ProducerSourceUnitDraft(
            "w03-only-materialized",
            "W03",
            SourceUnitSemantic.PATIENT_FAMILY,
            {"recipe": "mixed-world-redteam"},
            1,
            (_member("ordinary", SourceMemberSemantic.PATIENT_TRAJECTORY),),
        ),
        ProducerSourceUnitDraft(
            "w04-zero-slot-extra",
            "W04",
            SourceUnitSemantic.PATIENT_FAMILY,
            {"recipe": "mixed-world-redteam"},
            1,
            (_member("ordinary", SourceMemberSemantic.PATIENT_TRAJECTORY),),
        ),
    )
    transcripts = tuple(
        BuilderRandomnessTranscript(
            draft.unit_alias,
            "fixture-family-builder",
            f"mixed-{index}",
            {"draws": [index, 1]},
            {"draws": [index, 2]},
            {"draws": [index, 3]},
        )
        for index, draft in enumerate(drafts)
    )
    source = build_pre_split_family_source(
        benchmark_id="ucm-benchmark-v1",
        benchmark_revision="PRE-FREEZE-v1",
        registry_digest=_digest("registry"),
        generator_bundle_digest=_digest("mixed-world-generator"),
        topology_contract_digest=_digest("topology-contract"),
        query_contract_digest=_digest("query-contract"),
        builder_id="fixture-family-builder",
        builder_version="fixture-v2",
        drafts=drafts,
        transcripts=transcripts,
        materialization_slots=(
            MaterializationSlotDraft(
                "w03-only-slot",
                "w03-only-materialized",
                "ordinary",
                MaterializationRole.STANDARD_ROW,
                "sealed-test",
                _digest("mixed-cut"),
                _digest("mixed-query"),
                row_bundle_commitment_digest=_row_bundle_commitment(0, _history()),
                strata_allocation_commitment_digest=commitment,
            ),
        ),
    )
    slot = source.materialization_slots[0]
    with pytest.raises(ProtocolViolation, match="world-scoped family source"):
        build_pre_split_strata_allocation_manifest(
            family_source=source,
            world_slot="W03",
            generator_source_digest=_digest("mixed-generator-source"),
            allocation_policy_digest=_digest("mixed-allocation-policy"),
            builder_id="fixture-strata-builder",
            builder_version="fixture-v1",
            slot_drafts=(SlotAllocationDraft(slot.slot_digest, cells),),
        )


def test_authority_post_construction_mutation_fails_closed() -> None:
    public_mutated = _authority("W10", history=_history())
    object.__setattr__(
        public_mutated.public,
        "classifier_source_digest",
        _digest("mutated-public-source"),
    )
    with pytest.raises(ProtocolViolation, match="changed after construction"):
        public_mutated.public.classify(_history())
    with pytest.raises(ProtocolViolation, match="changed after construction"):
        public_mutated.public.to_wire()

    definition_mutated = _authority(
        "W03",
        history=_history(obs_value=0.50),
    )
    object.__setattr__(
        definition_mutated.public,
        "definitions",
        (),
    )
    with pytest.raises(ProtocolViolation):
        definition_mutated.public.classify(_history(obs_value=0.50))

    judge_mutated = _authority("W03", with_pair=False)
    object.__setattr__(
        judge_mutated.judge,
        "definition_source_digest",
        _digest("mutated-definition-source"),
    )
    with pytest.raises(ProtocolViolation, match="changed after construction"):
        judge_mutated.judge.to_wire()
    with pytest.raises(ProtocolViolation, match="changed after construction"):
        issue_strata_row_receipt(judge_mutated, _join(judge_mutated))

    dual_mutated = _authority("W03", history=_history())
    replacement_public = replace(
        dual_mutated.public,
        classifier_version="fixture-v2-mutated",
    )
    object.__setattr__(dual_mutated, "public", replacement_public)
    with pytest.raises(ProtocolViolation, match="changed after construction"):
        dual_mutated.to_wire()


def test_public_authority_boundaries_never_reinitialize_a_missing_seal() -> None:
    authority = _authority("W03", history=_history())
    object.__setattr__(
        authority.public,
        "classifier_version",
        "fixture-v1-post-construction-rewrite",
    )
    object.__delattr__(authority.public, "_sealed_classifier_digest")
    with pytest.raises(ProtocolViolation, match="public classifier seal is missing"):
        authority.public.__post_init__()
    with pytest.raises(ProtocolViolation, match="public classifier seal is missing"):
        authority.public.classify(_history())
    with pytest.raises(ProtocolViolation, match="public classifier seal is missing"):
        authority.public.to_wire()


def test_external_seal_registry_rejects_rewritten_state_and_seal_together() -> None:
    public = _authority("W03", history=_history()).public
    object.__setattr__(public, "classifier_version", "attacker-rewritten-version")
    object.__setattr__(
        public,
        "_sealed_classifier_digest",
        public._classifier_digest_unchecked(),
    )
    with pytest.raises(ProtocolViolation, match="changed after construction"):
        public.to_wire()


def test_judge_authority_boundaries_never_reinitialize_a_missing_seal() -> None:
    authority = _authority("W03", with_pair=False)
    object.__setattr__(
        authority.judge,
        "definition_source_digest",
        _digest("judge-source-post-construction-rewrite"),
    )
    object.__delattr__(authority.judge, "_sealed_allocation_manifest_digest")
    with pytest.raises(ProtocolViolation, match="judge strata authority seal is missing"):
        authority.judge.__post_init__()
    with pytest.raises(ProtocolViolation, match="judge strata authority seal is missing"):
        authority.judge.to_wire()
    with pytest.raises(ProtocolViolation, match="judge strata authority seal is missing"):
        issue_strata_row_receipt(authority, _join(authority))


def test_allocation_manifest_never_reinitializes_a_missing_seal() -> None:
    manifest = _authority("W03", history=_history()).judge.allocation_manifest
    object.__setattr__(
        manifest,
        "builder_version",
        "fixture-v1-post-construction-rewrite",
    )
    object.__delattr__(manifest, "_sealed_manifest_digest")
    with pytest.raises(
        ProtocolViolation,
        match="pre-split strata allocation manifest seal is missing",
    ):
        manifest.__post_init__()
    with pytest.raises(
        ProtocolViolation,
        match="pre-split strata allocation manifest seal is missing",
    ):
        manifest.to_wire()


def test_dual_authority_boundaries_never_reinitialize_a_missing_seal() -> None:
    authority = _authority("W03", history=_history())
    replacement_public = replace(
        authority.public,
        classifier_version="fixture-v1-replacement-child",
    )
    object.__setattr__(authority, "public", replacement_public)
    object.__delattr__(authority, "_sealed_authority_digest")
    with pytest.raises(
        ProtocolViolation,
        match="dual-channel strata authority seal is missing",
    ):
        authority.__post_init__()
    with pytest.raises(
        ProtocolViolation,
        match="dual-channel strata authority seal is missing",
    ):
        authority.to_wire()
    with pytest.raises(
        ProtocolViolation,
        match="dual-channel strata authority seal is missing",
    ):
        issue_strata_row_receipt(authority, _join(authority))


def test_exact_world_label_and_channel_contract_rejects_public_behavior_bypass() -> None:
    authority = _authority("W03")
    with pytest.raises(ProtocolViolation, match="exact world contract"):
        authority.combine_labels(
            ("iid_support", "boundary_tail"),
            ("compositional_holdout", "behavior_pair"),
        )
    with pytest.raises(ProtocolViolation, match="exact world contract"):
        authority.combine_labels(
            ("iid_support", "boundary_tail", "behavior_pair"),
            (),
        )


def test_channel_missing_extra_duplicate_unknown_and_disagreement_fail_closed() -> None:
    authority = _authority("W03")
    receipt = issue_strata_row_receipt(authority, _join(authority))
    with pytest.raises(ProtocolViolation, match="public stratum result"):
        replace(receipt, public_result=replace(receipt.public_result, labels=()))
    with pytest.raises(ProtocolViolation, match="judge stratum result"):
        replace(receipt, judge_result=replace(receipt.judge_result, judge_frozen_labels=()))
    with pytest.raises(ProtocolViolation, match="duplicate labels"):
        replace(receipt.public_result, labels=("iid_support", "iid_support"))
    with pytest.raises(ProtocolViolation, match="known benchmark-v1"):
        replace(receipt.public_result, labels=("invented",))
    with pytest.raises(ProtocolViolation, match="replay channels disagree"):
        replace(
            receipt,
            judge_result=replace(
                receipt.judge_result,
                public_replay_labels=("iid_support", "boundary_tail"),
            ),
        )


def test_all_artifacts_remain_pre_freeze_and_blocked() -> None:
    authority = _authority("W03")
    receipt = issue_strata_row_receipt(authority, _join(authority))
    batch = StrataReceiptBatch(authority, _all_receipts(authority))
    for artifact in (
        authority.judge.allocation_manifest.to_wire(),
        authority.public.to_wire(),
        authority.judge.to_wire(),
        authority.to_wire(),
        receipt.public_result.to_wire(),
        receipt.judge_result.to_wire(),
        receipt.to_wire(),
        batch.to_wire(),
    ):
        assert artifact["status"] == "pre_freeze_scaffold"
        assert artifact["freeze_grade_evidence"] is False
        assert artifact["benchmark_freeze_eligible"] is False
        assert {row["code"] for row in artifact["blockers"]} == {
            "UCM-E003-HARNESS_INCOMPLETE"
        }
    assert "typed per-slot allocation" in authority.judge.to_wire()[
        "blockers"
    ][0]["detail"]


def test_wire_literals_ignore_enum_value_mutation() -> None:
    authority = _authority("W10")
    receipt = issue_strata_row_receipt(authority, _join(authority))
    mutations = (
        (StrataScaffoldStatus.PRE_FREEZE_SCAFFOLD, "complete"),
        (StratumChannel.DUAL_CONJUNCTION, "public_replayable"),
        (PublicRuleKind.ALWAYS, "forged"),
        (JudgeRuleKind.W10_COMPOSITIONAL_CELL, "frozen_allocation_value"),
        (AllocationDimension.COMPOSITIONAL_HOLDOUT, "forged_dimension"),
        (AllocationCellValue.HELDOUT_HOST_MECHANISM, "forged_value"),
        (FamilySplit.SEALED_TEST, "train"),
        (PairSemantic.BEHAVIORAL, "counterfactual_pair"),
    )
    originals = tuple((member, member.value) for member, _ in mutations)
    try:
        for member, forged in mutations:
            object.__setattr__(member, "_value_", forged)
        wire = receipt.to_wire()
        assert wire["status"] == "pre_freeze_scaffold"
        assert wire["assigned_split"] == "sealed_test"
        definition = next(
            item
            for item in authority.public.to_wire()["definitions"]
            if item["label"] == "compositional_holdout"
        )
        assert definition["channel"] == "dual_conjunction"
        assert definition["judge_rule"]["kind"] == "w10_frozen_compositional_cell"
    finally:
        for member, original in originals:
            object.__setattr__(member, "_value_", original)


def test_no_status_override_fields_exist() -> None:
    for cls in (
        PublicChannelResult,
        JudgeChannelResult,
        StrataRowReceipt,
        StrataReceiptBatch,
    ):
        assert "status" not in cls.__dataclass_fields__
        assert "freeze_grade_evidence" not in cls.__dataclass_fields__
        assert "benchmark_freeze_eligible" not in cls.__dataclass_fields__
