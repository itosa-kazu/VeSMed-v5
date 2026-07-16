from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import prototype.unified_map.expected_cell_receipts as receipts_module
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.evaluator import (
    EvaluationCohort,
    EvaluationManifest,
    EvaluationSplit,
    EvaluationTask,
    ExpectedEvaluationCell,
    ExpectedPairCell,
    IdentificationKind,
    OODAttribution,
    PairThresholds,
    W19SafetyDeclaration,
)
from prototype.unified_map.expected_cell_receipts import (
    E002_CODE,
    E003_CODE,
    CanonicalCellPreimage,
    CellPreimageKind,
    ExpectedCellPreimageReceipt,
    ExpectedCellReceiptBatch,
    ExpectedCellReceiptRoot,
)
from prototype.unified_map.evaluation_cells import (
    BenchmarkCoverageLock,
    ExpectedCellsScopeContract,
    FrozenAuthorityRoots,
    FrozenCorpusShard,
    FrozenFamilyLineage,
    LockedQueryTemplate,
    LockedShardCoverage,
    PairCellContract,
    QueryCellContract,
    W19SafetyContract,
)
from prototype.unified_map.family_manifest import (
    BuilderRandomnessTranscript,
    FamilySplit,
    MaterializationRole,
    MaterializationSlotDraft,
    ProducerSourceUnitDraft,
    RowMaterializationEvidence,
    SourceMemberDraft,
    SourceMemberSemantic,
    SourceUnitSemantic,
    build_pre_split_family_source,
    build_materialization_receipt_ledger,
    build_weighted_atomic_assignment,
    compute_row_bundle_commitment,
    issue_materialization_receipt,
)
from prototype.unified_map.world_registry import registry_digest


SCOPE = digest_json({"scope": "expected-cell-preimage-fixture"})
DEFAULT_CODE_LOCK = receipts_module.CODE_OWNED_COVERAGE_LOCK
DEFAULT_CORPUS_PINS = receipts_module.CODE_OWNED_CORPUS_SCOPE_PINS
DEFAULT_SCOPE_CONTRACT_PIN = receipts_module.CODE_OWNED_SCOPE_CONTRACT_DIGEST
DEFAULT_EXPECTED_MANIFEST_PIN = receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST
DEFAULT_MATERIALIZATION_LEDGERS = receipts_module.CODE_OWNED_MATERIALIZATION_LEDGERS


@pytest.fixture(autouse=True)
def _restore_code_owned_lock() -> None:
    try:
        yield
    finally:
        receipts_module.CODE_OWNED_COVERAGE_LOCK = DEFAULT_CODE_LOCK
        receipts_module.CODE_OWNED_CORPUS_SCOPE_PINS = DEFAULT_CORPUS_PINS
        receipts_module.CODE_OWNED_SCOPE_CONTRACT_DIGEST = DEFAULT_SCOPE_CONTRACT_PIN
        receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST = (
            DEFAULT_EXPECTED_MANIFEST_PIN
        )
        receipts_module.CODE_OWNED_MATERIALIZATION_LEDGERS = (
            DEFAULT_MATERIALIZATION_LEDGERS
        )


def _digest(label: str) -> str:
    return digest_json({"fixture": label})


def _derived_record_id(
    *,
    scope_digest: str,
    world_slot: str,
    panel_id: str,
    source_record_id: str,
    split: str,
    family_id: str,
    cut_alias: str,
    training_replicate_id: str,
    evaluation_replicate_id: str,
    task: str,
    horizon: int,
    policy_alias: str,
) -> str:
    return "c-" + digest_json(
        {
            "schema_version": "ucm-evaluation-cell-id/1",
            "scope_digest": scope_digest,
            "world_slot": world_slot,
            "panel_id": panel_id,
            "source_record_id": source_record_id,
            "split": split,
            "family_id": family_id,
            "cut_alias": cut_alias,
            "training_replicate_id": training_replicate_id,
            "evaluation_replicate_id": evaluation_replicate_id,
            "task": task,
            "horizon": horizon,
            "policy_alias": policy_alias,
        }
    )[7:]


def _derived_episode_alias(
    *,
    scope_digest: str,
    world_slot: str,
    panel_id: str,
    split: str,
    evaluation_replicate_id: str,
    source_record_id: str,
) -> str:
    return "e-" + digest_json(
        {
            "schema_version": "ucm-evaluation-episode-alias/1",
            "scope_digest": scope_digest,
            "world_slot": world_slot,
            "panel_id": panel_id,
            "split": split,
            "evaluation_replicate_id": evaluation_replicate_id,
            "source_record_id": source_record_id,
        }
    )[7:]


def _derived_family_id(
    *,
    scope_digest: str,
    world_slot: str,
    panel_id: str,
    split: str,
    evaluation_replicate_id: str,
    source_family_digest: str,
) -> str:
    return "f-" + digest_json(
        {
            "schema_version": "ucm-evaluation-family-id/1",
            "scope_digest": scope_digest,
            "world_slot": world_slot,
            "panel_id": panel_id,
            "split": split,
            "evaluation_replicate_id": evaluation_replicate_id,
            "source_family_digest": source_family_digest,
        }
    )[7:]


def _derived_pair_id(
    *,
    scope_digest: str,
    world_slot: str,
    panel_id: str,
    source_pair_id: str,
    split: str,
    family_id: str,
    training_replicate_id: str,
    evaluation_replicate_id: str,
) -> str:
    return "p-" + digest_json(
        {
            "schema_version": "ucm-evaluation-pair-cell-id/1",
            "scope_digest": scope_digest,
            "world_slot": world_slot,
            "panel_id": panel_id,
            "source_pair_id": source_pair_id,
            "split": split,
            "family_id": family_id,
            "training_replicate_id": training_replicate_id,
            "evaluation_replicate_id": evaluation_replicate_id,
        }
    )[7:]


@dataclass(frozen=True)
class _Fixture:
    cell: ExpectedEvaluationCell
    materialization: object
    query: CanonicalCellPreimage
    oracle: CanonicalCellPreimage
    request: CanonicalCellPreimage
    response: CanonicalCellPreimage
    receipt: ExpectedCellPreimageReceipt


def _rederive_cell(
    cell: ExpectedEvaluationCell,
    source_record_id: str,
    **changes: object,
) -> ExpectedEvaluationCell:
    changed = replace(cell, **changes)
    record_id = _derived_record_id(
        scope_digest=changed.scope_digest,
        world_slot=changed.world_slot,
        panel_id=changed.panel_id,
        source_record_id=source_record_id,
        split=changed.split.value,
        family_id=changed.family_id,
        cut_alias=changed.cut_alias,
        training_replicate_id=changed.training_replicate_id,
        evaluation_replicate_id=changed.evaluation_replicate_id,
        task=changed.task.value,
        horizon=changed.horizon,
        policy_alias=changed.policy_alias,
    )
    episode_alias = _derived_episode_alias(
        scope_digest=changed.scope_digest,
        world_slot=changed.world_slot,
        panel_id=changed.panel_id,
        split=changed.split.value,
        evaluation_replicate_id=changed.evaluation_replicate_id,
        source_record_id=source_record_id,
    )
    return replace(changed, record_id=record_id, episode_alias=episode_alias)


def _make_fixture(
    index: int,
    *,
    world_slot: str = "W03",
    task: EvaluationTask = EvaluationTask.DIAGNOSIS,
    horizon: int = 0,
    policy_alias: str = "natural",
    tail_member: bool = False,
    cell_unsafe_action_ids: tuple[str, ...] = (),
    query_unsafe_action_ids: tuple[str, ...] = (),
) -> _Fixture:
    suffix = f"{index:02d}"
    source_record_id = f"source-{suffix}"
    unit_alias = f"family-{suffix}"
    member_alias = "member"
    draft = ProducerSourceUnitDraft(
        unit_alias=unit_alias,
        world_slot=world_slot,
        semantic_type=SourceUnitSemantic.PATIENT_FAMILY,
        recipe_payload={"recipe": "fixture", "index": index},
        weight=1,
        members=(
            SourceMemberDraft(
                member_alias=member_alias,
                semantic_type=SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
                semantic_payload={"observation_path": [index]},
            ),
        ),
    )
    transcript = BuilderRandomnessTranscript(
        unit_alias=unit_alias,
        builder_id="fixture-authority-builder",
        builder_run_id=f"builder-run-{suffix}",
        latent_transcript={"draws": [index + 0.1]},
        noise_transcript={"draws": [index + 0.2]},
        acquisition_transcript={"draws": [index + 0.3]},
    )
    preliminary_source = build_pre_split_family_source(
        benchmark_id="ucm-benchmark-v1",
        benchmark_revision="PRE-FREEZE-v1",
        registry_digest=registry_digest(),
        generator_bundle_digest=_digest("generator-bundle"),
        topology_contract_digest=_digest("topology-contract"),
        query_contract_digest=_digest("query-contract"),
        builder_id="fixture-authority-builder",
        builder_version="fixture-v1",
        drafts=(draft,),
        transcripts=(transcript,),
    )
    family_id = _derived_family_id(
        scope_digest=SCOPE,
        world_slot=world_slot,
        panel_id="primary",
        split="train",
        evaluation_replicate_id="eval-01",
        source_family_digest=preliminary_source.units[0].family_digest,
    )
    cell_fields = {
        "scope_digest": SCOPE,
        "world_slot": world_slot,
        "panel_id": "primary",
        "source_record_id": source_record_id,
        "split": "train",
        "family_id": family_id,
        "cut_alias": "presentation",
        "training_replicate_id": "train-01",
        "evaluation_replicate_id": "eval-01",
        "task": task.value,
        "horizon": horizon,
        "policy_alias": policy_alias,
    }
    cell = ExpectedEvaluationCell(
        record_id=_derived_record_id(**cell_fields),
        world_slot=world_slot,
        panel_id="primary",
        episode_alias=_derived_episode_alias(
            scope_digest=SCOPE,
            world_slot=world_slot,
            panel_id="primary",
            split="train",
            evaluation_replicate_id="eval-01",
            source_record_id=source_record_id,
        ),
        cohort=EvaluationCohort.POPULATION,
        task=task,
        scope_digest=SCOPE,
        split=EvaluationSplit.TRAIN,
        family_id=family_id,
        cut_alias="presentation",
        training_replicate_id="train-01",
        evaluation_replicate_id="eval-01",
        horizon=horizon,
        policy_alias=policy_alias,
        tail_member=tail_member,
        ood_attribution=OODAttribution.NOT_APPLICABLE,
        identification=IdentificationKind.POINT,
        unsafe_action_ids=cell_unsafe_action_ids,
    )
    query_payload = {
        "shard_id": f"shard-{world_slot}-primary-train-01-eval-01",
        "source_record_id": source_record_id,
        "cut_alias": "presentation",
        "task": task.value,
        "horizon": horizon,
        "policy_alias": policy_alias,
        "ood_attribution": "not_applicable",
        "unsafe_action_ids": list(query_unsafe_action_ids),
    }
    oracle_payload = {
        "schema_version": "fixture-oracle/1",
        "target": {"state": index, "labels": ["A", "B"]},
    }
    request_payload = {
        "schema_version": "fixture-candidate-request/1",
        "operation": "diagnose",
        "request_id": f"request-{suffix}",
        "payload": {"history": [{"t": 0, "value": index}]},
    }
    response_payload = {
        "schema_version": "fixture-candidate-response/1",
        "request_id": f"request-{suffix}",
        "status": "ok",
        "probabilities": {"A": 0.75, "B": 0.25},
    }
    query = CanonicalCellPreimage.from_payload(
        CellPreimageKind.QUERY_CELL, query_payload
    )
    oracle = CanonicalCellPreimage.from_payload(
        CellPreimageKind.ORACLE_TARGET, oracle_payload
    )
    request = CanonicalCellPreimage.from_payload(
        CellPreimageKind.RAW_REQUEST, request_payload
    )
    response = CanonicalCellPreimage.from_payload(
        CellPreimageKind.RAW_RESPONSE, response_payload
    )
    row_fields = {
        "record_id": cell.record_id,
        "public_history_digest": _digest(f"history-{suffix}"),
        "hidden_state_at_cut_digest": _digest(f"hidden-{suffix}"),
        "oracle_target_digest": oracle.preimage_digest,
        "candidate_row_digest": _digest(f"candidate-row-{suffix}"),
        "judge_row_digest": _digest(f"judge-row-{suffix}"),
        "raw_request_digest": request.preimage_digest,
        "raw_response_digest": response.preimage_digest,
    }
    row_bundle = compute_row_bundle_commitment(**row_fields)
    source = build_pre_split_family_source(
        benchmark_id="ucm-benchmark-v1",
        benchmark_revision="PRE-FREEZE-v1",
        registry_digest=registry_digest(),
        generator_bundle_digest=_digest("generator-bundle"),
        topology_contract_digest=_digest("topology-contract"),
        query_contract_digest=_digest("query-contract"),
        builder_id="fixture-authority-builder",
        builder_version="fixture-v1",
        drafts=(draft,),
        transcripts=(transcript,),
        materialization_slots=(
            MaterializationSlotDraft(
                slot_alias=f"slot-{suffix}",
                unit_alias=unit_alias,
                member_alias=member_alias,
                materialization_role=MaterializationRole.STANDARD_ROW,
                stage_label="evaluation",
                cut_digest=_digest(f"cut-{suffix}"),
                query_cell_digest=query.preimage_digest,
                row_bundle_commitment_digest=row_bundle,
            ),
        ),
    )
    assert source.units[0].family_digest == preliminary_source.units[0].family_digest
    authority = source.units[0].authority_digest
    assignment = build_weighted_atomic_assignment(
        source,
        {authority: FamilySplit.TRAIN},
        split_policy_digest=_digest("split-policy"),
        split_seed_commitment=_digest("split-seed"),
    )
    slot = source.materialization_slots[0]
    evidence = RowMaterializationEvidence(
        **row_fields,
        assigned_split=FamilySplit.TRAIN,
        authority_digest=authority,
        member_digest=source.units[0].members[0].member_digest,
        query_cell_digest=query.preimage_digest,
        materialization_slot_digest=slot.slot_digest,
        cut_digest=slot.cut_digest,
        stage_label=slot.stage_label,
        materialization_role=slot.materialization_role,
        pair_digest=slot.pair_digest,
        pair_side=slot.pair_side,
        atomic_link_digest=slot.atomic_link_digest,
    )
    materialization = issue_materialization_receipt(source, assignment, evidence)
    receipt = ExpectedCellPreimageReceipt(
        cell,
        materialization,
        query,
        oracle,
        request,
        response,
    )
    return _Fixture(cell, materialization, query, oracle, request, response, receipt)


def _make_multi_cell_fixtures(index: int = 3) -> tuple[_Fixture, ...]:
    """One source member/episode with two independently materialized queries."""

    suffix = f"{index:02d}"
    source_record_id = f"source-{suffix}"
    unit_alias = f"family-{suffix}"
    member_alias = "member"
    draft = ProducerSourceUnitDraft(
        unit_alias=unit_alias,
        world_slot="W03",
        semantic_type=SourceUnitSemantic.PATIENT_FAMILY,
        recipe_payload={"recipe": "multi-cell-fixture", "index": index},
        weight=1,
        members=(
            SourceMemberDraft(
                member_alias=member_alias,
                semantic_type=SourceMemberSemantic.COUNTERFACTUAL_VARIANT,
                semantic_payload={"observation_path": [index], "source": source_record_id},
            ),
        ),
    )
    transcript = BuilderRandomnessTranscript(
        unit_alias=unit_alias,
        builder_id="fixture-authority-builder",
        builder_run_id=f"builder-run-{suffix}",
        latent_transcript={"draws": [index + 0.1]},
        noise_transcript={"draws": [index + 0.2]},
        acquisition_transcript={"draws": [index + 0.3]},
    )
    source_kwargs = {
        "benchmark_id": "ucm-benchmark-v1",
        "benchmark_revision": "PRE-FREEZE-v1",
        "registry_digest": registry_digest(),
        "generator_bundle_digest": _digest("generator-bundle"),
        "topology_contract_digest": _digest("topology-contract"),
        "query_contract_digest": _digest("query-contract"),
        "builder_id": "fixture-authority-builder",
        "builder_version": "fixture-v1",
        "drafts": (draft,),
        "transcripts": (transcript,),
    }
    preliminary_source = build_pre_split_family_source(**source_kwargs)
    family_id = _derived_family_id(
        scope_digest=SCOPE,
        world_slot="W03",
        panel_id="primary",
        split="train",
        evaluation_replicate_id="eval-01",
        source_family_digest=preliminary_source.units[0].family_digest,
    )
    specs = (
        (EvaluationTask.DIAGNOSIS, 0, "natural"),
        (EvaluationTask.NATURAL_FORECAST, 2, "natural"),
    )
    pending: list[dict[str, object]] = []
    slots: list[MaterializationSlotDraft] = []
    for ordinal, (task, horizon, policy_alias) in enumerate(specs):
        cell_fields = {
            "scope_digest": SCOPE,
            "world_slot": "W03",
            "panel_id": "primary",
            "source_record_id": source_record_id,
            "split": "train",
            "family_id": family_id,
            "cut_alias": "presentation",
            "training_replicate_id": "train-01",
            "evaluation_replicate_id": "eval-01",
            "task": task.value,
            "horizon": horizon,
            "policy_alias": policy_alias,
        }
        cell = ExpectedEvaluationCell(
            record_id=_derived_record_id(**cell_fields),
            world_slot="W03",
            panel_id="primary",
            episode_alias=_derived_episode_alias(
                scope_digest=SCOPE,
                world_slot="W03",
                panel_id="primary",
                split="train",
                evaluation_replicate_id="eval-01",
                source_record_id=source_record_id,
            ),
            cohort=EvaluationCohort.POPULATION,
            task=task,
            scope_digest=SCOPE,
            split=EvaluationSplit.TRAIN,
            family_id=family_id,
            cut_alias="presentation",
            training_replicate_id="train-01",
            evaluation_replicate_id="eval-01",
            horizon=horizon,
            policy_alias=policy_alias,
            ood_attribution=OODAttribution.NOT_APPLICABLE,
            identification=IdentificationKind.POINT,
        )
        query = CanonicalCellPreimage.from_payload(
            CellPreimageKind.QUERY_CELL,
            {
                "shard_id": "shard-W03-primary-train-01-eval-01",
                "source_record_id": source_record_id,
                "cut_alias": "presentation",
                "task": task.value,
                "horizon": horizon,
                "policy_alias": policy_alias,
                "ood_attribution": "not_applicable",
                "unsafe_action_ids": [],
            },
        )
        oracle = CanonicalCellPreimage.from_payload(
            CellPreimageKind.ORACLE_TARGET,
            {"schema_version": "fixture-oracle/1", "cell": cell.record_id},
        )
        request = CanonicalCellPreimage.from_payload(
            CellPreimageKind.RAW_REQUEST,
            {
                "schema_version": "fixture-candidate-request/1",
                "cell": cell.record_id,
                "ordinal": ordinal,
            },
        )
        response = CanonicalCellPreimage.from_payload(
            CellPreimageKind.RAW_RESPONSE,
            {
                "schema_version": "fixture-candidate-response/1",
                "cell": cell.record_id,
                "ordinal": ordinal,
                "status": "ok",
            },
        )
        row_fields = {
            "record_id": cell.record_id,
            "public_history_digest": _digest(f"history-{suffix}-{ordinal}"),
            "hidden_state_at_cut_digest": _digest(f"hidden-{suffix}-{ordinal}"),
            "oracle_target_digest": oracle.preimage_digest,
            "candidate_row_digest": _digest(f"candidate-{suffix}-{ordinal}"),
            "judge_row_digest": _digest(f"judge-{suffix}-{ordinal}"),
            "raw_request_digest": request.preimage_digest,
            "raw_response_digest": response.preimage_digest,
        }
        slot_alias = f"slot-{suffix}-{ordinal}"
        slots.append(
            MaterializationSlotDraft(
                slot_alias=slot_alias,
                unit_alias=unit_alias,
                member_alias=member_alias,
                materialization_role=MaterializationRole.STANDARD_ROW,
                stage_label="evaluation",
                cut_digest=_digest(f"cut-{suffix}"),
                query_cell_digest=query.preimage_digest,
                row_bundle_commitment_digest=compute_row_bundle_commitment(
                    **row_fields
                ),
            )
        )
        pending.append(
            {
                "cell": cell,
                "query": query,
                "oracle": oracle,
                "request": request,
                "response": response,
                "row_fields": row_fields,
                "slot_alias": slot_alias,
            }
        )
    source = build_pre_split_family_source(
        **source_kwargs, materialization_slots=tuple(slots)
    )
    authority_digest = source.units[0].authority_digest
    assignment = build_weighted_atomic_assignment(
        source,
        {authority_digest: FamilySplit.TRAIN},
        split_policy_digest=_digest("split-policy"),
        split_seed_commitment=_digest("split-seed"),
    )
    slots_by_alias = {item.slot_alias: item for item in source.materialization_slots}
    fixtures: list[_Fixture] = []
    for item in pending:
        slot = slots_by_alias[item["slot_alias"]]
        evidence = RowMaterializationEvidence(
            **item["row_fields"],
            assigned_split=FamilySplit.TRAIN,
            authority_digest=authority_digest,
            member_digest=source.units[0].members[0].member_digest,
            query_cell_digest=item["query"].preimage_digest,
            materialization_slot_digest=slot.slot_digest,
            cut_digest=slot.cut_digest,
            stage_label=slot.stage_label,
            materialization_role=slot.materialization_role,
            pair_digest=slot.pair_digest,
            pair_side=slot.pair_side,
            atomic_link_digest=slot.atomic_link_digest,
        )
        materialization = issue_materialization_receipt(
            source, assignment, evidence
        )
        receipt = ExpectedCellPreimageReceipt(
            item["cell"],
            materialization,
            item["query"],
            item["oracle"],
            item["request"],
            item["response"],
        )
        fixtures.append(
            _Fixture(
                item["cell"],
                materialization,
                item["query"],
                item["oracle"],
                item["request"],
                item["response"],
                receipt,
            )
        )
    return tuple(sorted(fixtures, key=lambda item: item.cell.record_id))


@pytest.fixture(scope="module")
def fixtures() -> tuple[_Fixture, _Fixture]:
    values = (_make_fixture(1), _make_fixture(2))
    return tuple(sorted(values, key=lambda item: item.cell.record_id))


@dataclass(frozen=True)
class _RootAuthority:
    lock: BenchmarkCoverageLock
    contract: ExpectedCellsScopeContract
    manifest: EvaluationManifest


def _root_authority(
    receipts: tuple[ExpectedCellPreimageReceipt, ...],
    *,
    expected_cells: tuple[ExpectedEvaluationCell, ...] | None = None,
    w19_contract: W19SafetyContract | None = None,
    w19_declaration: W19SafetyDeclaration | None = None,
) -> _RootAuthority:
    selected = tuple(item.selected_query_wire for item in receipts)
    queries = tuple(
        QueryCellContract(
            shard_id=item["shard_id"],
            source_record_id=item["source_record_id"],
            cut_alias=item["cut_alias"],
            task=EvaluationTask(item["task"]),
            horizon=item["horizon"],
            policy_alias=item["policy_alias"],
            ood_attribution=OODAttribution(item["ood_attribution"]),
            unsafe_action_ids=tuple(item["unsafe_action_ids"]),
        )
        for item in selected
    )
    first = receipts[0].expected_cell
    assert all(
        (
            item.expected_cell.world_slot,
            item.expected_cell.panel_id,
            item.expected_cell.split,
            item.expected_cell.training_replicate_id,
            item.expected_cell.evaluation_replicate_id,
        )
        == (
            first.world_slot,
            first.panel_id,
            first.split,
            first.training_replicate_id,
            first.evaluation_replicate_id,
        )
        for item in receipts
    )
    templates_by_cohort: dict[EvaluationCohort, dict[tuple, LockedQueryTemplate]] = {
        EvaluationCohort.POPULATION: {},
        EvaluationCohort.PROBE: {},
    }
    for receipt in receipts:
        cell = receipt.expected_cell
        template = LockedQueryTemplate(
            cell.cut_alias, cell.task, cell.horizon, cell.policy_alias
        )
        templates_by_cohort[cell.cohort][template.identity] = template
    locked_shard = LockedShardCoverage(
        world_slot=first.world_slot,
        panel_id=first.panel_id,
        split=first.split,
        training_replicate_id=first.training_replicate_id,
        evaluation_replicate_id=first.evaluation_replicate_id,
        population_queries=tuple(
            sorted(
                templates_by_cohort[EvaluationCohort.POPULATION].values(),
                key=lambda item: canonical_json_bytes(item.to_wire()),
            )
        ),
        probe_queries=tuple(
            sorted(
                templates_by_cohort[EvaluationCohort.PROBE].values(),
                key=lambda item: canonical_json_bytes(item.to_wire()),
            )
        ),
    )
    lock = BenchmarkCoverageLock(
        benchmark_id="UCM-BENCHMARK-v1",
        benchmark_revision="FROZEN-v1",
        scope_digest=SCOPE,
        scope_manifest_digest=_digest("scope-manifest"),
        family_source_digest=_digest("family-source-root"),
        family_manifest_digest=_digest("family-manifest-root"),
        family_seal_digest=_digest("family-seal-root"),
        raw_roots_digest=_digest("raw-roots"),
        query_scope_frozen=True,
        shards=(locked_shard,),
    )
    shard_id = selected[0]["shard_id"]
    assert all(item["shard_id"] == shard_id for item in selected)
    shard = FrozenCorpusShard(
        shard_id=shard_id,
        world_slot=first.world_slot,
        panel_id=first.panel_id,
        split=first.split,
        training_replicate_id=first.training_replicate_id,
        evaluation_replicate_id=first.evaluation_replicate_id,
        required_tasks=tuple(
            sorted(
                {item.expected_cell.task for item in receipts},
                key=lambda item: item.value,
            )
        ),
        candidate_path=Path("fixture-candidate.jsonl"),
        judge_path=Path("fixture-judge.jsonl"),
        status_path=Path("fixture-status.json"),
        candidate_digest=_digest("candidate-corpus"),
        judge_digest=_digest("judge-corpus"),
        status_digest=_digest("corpus-status"),
    )
    contract = ExpectedCellsScopeContract(
        benchmark_id=lock.benchmark_id,
        benchmark_revision=lock.benchmark_revision,
        scope_digest=SCOPE,
        registry_digest=registry_digest(),
        coverage_lock_digest=lock.digest,
        family_lineage=FrozenFamilyLineage(
            source_path=Path("fixture-family-source.json"),
            manifest_path=Path("fixture-family-manifest.json"),
            seal_path=Path("fixture-family-seal.json"),
            source_digest=_digest("family-source-root"),
            manifest_digest=_digest("family-manifest-root"),
            seal_digest=_digest("family-seal-root"),
        ),
        authority_roots=FrozenAuthorityRoots(
            scope_manifest_path=Path("fixture-scope-manifest.json"),
            raw_roots_path=Path("fixture-raw-roots.json"),
            scope_manifest_digest=_digest("scope-manifest"),
            raw_roots_digest=_digest("raw-roots"),
        ),
        shards=(shard,),
        queries=tuple(
            sorted(queries, key=lambda item: canonical_json_bytes(item.to_wire()))
        ),
        pairs=(),
        w19_safety=w19_contract,
    )
    manifest = EvaluationManifest(
        scope_digest=SCOPE,
        expected_cells=expected_cells
        if expected_cells is not None
        else tuple(item.expected_cell for item in receipts),
        w19_safety=w19_declaration,
        cell_contract_digest=contract.digest,
    )
    receipts_module.CODE_OWNED_COVERAGE_LOCK = lock
    receipts_module.CODE_OWNED_CORPUS_SCOPE_PINS = (shard,)
    receipts_module.CODE_OWNED_SCOPE_CONTRACT_DIGEST = contract.digest
    receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST = manifest.digest
    ledger_groups: dict[str, list[object]] = {}
    ledger_parents: dict[str, object] = {}
    for receipt in receipts:
        parent = receipt.materialization_receipt
        key = parent.source.source_digest
        ledger_groups.setdefault(key, []).append(parent)
        ledger_parents[key] = parent
    ledgers = []
    for key in sorted(ledger_groups):
        parent = ledger_parents[key]
        ledgers.append(
            build_materialization_receipt_ledger(
                parent.source,
                parent.assignment,
                tuple(ledger_groups[key]),
            )
        )
    receipts_module.CODE_OWNED_MATERIALIZATION_LEDGERS = tuple(ledgers)
    return _RootAuthority(lock, contract, manifest)


def _build_root(
    receipts: tuple[ExpectedCellPreimageReceipt, ...],
    batches: tuple[ExpectedCellReceiptBatch, ...],
    *,
    expected_cells: tuple[ExpectedEvaluationCell, ...] | None = None,
    w19_contract: W19SafetyContract | None = None,
    w19_declaration: W19SafetyDeclaration | None = None,
) -> tuple[_RootAuthority, ExpectedCellReceiptRoot]:
    authority = _root_authority(
        receipts,
        expected_cells=expected_cells,
        w19_contract=w19_contract,
        w19_declaration=w19_declaration,
    )
    return authority, ExpectedCellReceiptRoot(
        authority.manifest, authority.contract, batches
    )


def test_canonical_preimage_retains_exact_bytes_and_roundtrips() -> None:
    payload = {"nested": {"alpha": [1, 2]}, "z": True}
    preimage = CanonicalCellPreimage.from_payload(
        CellPreimageKind.RAW_REQUEST, payload
    )
    assert preimage.canonical_bytes == canonical_json_bytes(payload)
    assert CanonicalCellPreimage.from_wire(preimage.to_wire()) == preimage
    assert preimage.preimage_digest == digest_json(payload)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1}',
        b'{ "a": 1 }\n',
        b'{"z":0,"a":1}\n',
        b'[1,2]\n',
    ],
)
def test_preimage_rejects_noncanonical_or_nonobject_bytes(raw: bytes) -> None:
    with pytest.raises(ProtocolViolation, match="canonical|exact JSON object"):
        CanonicalCellPreimage(CellPreimageKind.RAW_RESPONSE, raw)


def test_preimage_wire_is_closed_and_recomputes_digest() -> None:
    preimage = CanonicalCellPreimage.from_payload(
        CellPreimageKind.ORACLE_TARGET, {"oracle": 1}
    )
    extra = preimage.to_wire()
    extra["forged"] = True
    with pytest.raises(ProtocolViolation, match="schema mismatch"):
        CanonicalCellPreimage.from_wire(extra)
    stale = preimage.to_wire()
    stale["preimage_digest"] = _digest("forged")
    with pytest.raises(ProtocolViolation, match="stale|non-canonical"):
        CanonicalCellPreimage.from_wire(stale)


def test_preimage_snapshots_nested_mutability() -> None:
    payload = {"nested": {"items": [1, 2]}}
    preimage = CanonicalCellPreimage.from_payload(
        CellPreimageKind.RAW_REQUEST, payload
    )
    before = preimage.to_wire()
    payload["nested"]["items"].append(3)
    returned = preimage.payload
    returned["nested"]["items"].append(4)
    assert preimage.to_wire() == before


def test_receipt_exact_joins_all_four_preimages_and_roundtrips(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    wire = fixture.receipt.to_wire()
    assert wire["expected_cell"]["record_id"] == fixture.cell.record_id
    assert wire["preimages"]["query_cell"]["preimage_digest"] == (
        fixture.materialization.evidence.query_cell_digest
    )
    assert (
        ExpectedCellPreimageReceipt.from_wire(
            wire,
            expected_cell=fixture.cell,
            materialization_receipt=fixture.materialization,
        ).receipt_digest
        == fixture.receipt.receipt_digest
    )


def test_receipt_recomputes_cell_and_episode_identity_to_reject_cross_row_swap(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    first, second = fixtures
    with pytest.raises(ProtocolViolation, match="family_id|record_id"):
        ExpectedCellPreimageReceipt(
            first.cell,
            second.materialization,
            second.query,
            second.oracle,
            second.request,
            second.response,
        )
    drifted_episode = replace(first.cell, episode_alias=second.cell.episode_alias)
    with pytest.raises(ProtocolViolation, match="episode_alias is not derived"):
        ExpectedCellPreimageReceipt(
            drifted_episode,
            first.materialization,
            first.query,
            first.oracle,
            first.request,
            first.response,
        )


@pytest.mark.parametrize(
    ("field", "kind"),
    [
        ("query_cell", CellPreimageKind.QUERY_CELL),
        ("oracle_target", CellPreimageKind.ORACLE_TARGET),
        ("raw_request", CellPreimageKind.RAW_REQUEST),
        ("raw_response", CellPreimageKind.RAW_RESPONSE),
    ],
)
def test_receipt_rejects_each_preimage_digest_mismatch(
    fixtures: tuple[_Fixture, _Fixture],
    field: str,
    kind: CellPreimageKind,
) -> None:
    fixture = fixtures[0]
    values = {
        "expected_cell": fixture.cell,
        "materialization_receipt": fixture.materialization,
        "query_cell": fixture.query,
        "oracle_target": fixture.oracle,
        "raw_request": fixture.request,
        "raw_response": fixture.response,
    }
    payload = {"rewrapped": field}
    if field == "query_cell":
        payload = fixture.query.payload
        payload["shard_id"] = "rewrapped-shard"
    values[field] = CanonicalCellPreimage.from_payload(kind, payload)
    with pytest.raises(ProtocolViolation, match="preimage does not match committed digest"):
        ExpectedCellPreimageReceipt(**values)


def test_query_preimage_has_closed_schema_and_exact_cell_join(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    query = fixture.query.payload
    query["extra"] = "smuggled"
    with pytest.raises(ProtocolViolation, match="query-cell preimage schema mismatch"):
        ExpectedCellPreimageReceipt(
            fixture.cell,
            fixture.materialization,
            CanonicalCellPreimage.from_payload(CellPreimageKind.QUERY_CELL, query),
            fixture.oracle,
            fixture.request,
            fixture.response,
        )
    mismatched_cell = replace(fixture.cell, horizon=1)
    with pytest.raises(ProtocolViolation, match="horizon does not join"):
        ExpectedCellPreimageReceipt(
            mismatched_cell,
            fixture.materialization,
            fixture.query,
            fixture.oracle,
            fixture.request,
            fixture.response,
        )


def test_receipt_wire_rejects_missing_extra_and_status_rewrite(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    for mutate in ("missing", "extra", "status"):
        wire = fixture.receipt.to_wire()
        if mutate == "missing":
            del wire["blockers"]
        elif mutate == "extra":
            wire["authority"] = "caller"
        else:
            wire["status"] = "complete"
            wire["benchmark_freeze_eligible"] = True
        with pytest.raises(ProtocolViolation, match="schema mismatch|stale|non-canonical"):
            ExpectedCellPreimageReceipt.from_wire(
                wire,
                expected_cell=fixture.cell,
                materialization_receipt=fixture.materialization,
            )


def test_from_wire_rejects_recursive_bool_int_and_int_float_aliases(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    receipt_wire = fixture.receipt.to_wire()
    receipt_wire["freeze_grade_evidence"] = 0
    receipt_wire["expected_cell"]["horizon"] = 0.0
    with pytest.raises(ProtocolViolation, match="stale|non-canonical"):
        ExpectedCellPreimageReceipt.from_wire(
            receipt_wire,
            expected_cell=fixture.cell,
            materialization_receipt=fixture.materialization,
        )

    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    batch_wire = batch.to_wire()
    batch_wire["benchmark_freeze_eligible"] = 0
    with pytest.raises(ProtocolViolation, match="stale|non-canonical"):
        ExpectedCellReceiptBatch.from_wire(batch_wire, receipts=batch.receipts)

    authority, root = _build_root((fixture.receipt,), (batch,))
    root_wire = root.to_wire()
    root_wire["freeze_grade_evidence"] = 0
    with pytest.raises(ProtocolViolation, match="stale|non-canonical"):
        ExpectedCellReceiptRoot.from_wire(
            root_wire,
            manifest=root.manifest,
            scope_contract=authority.contract,
            batches=root.batches,
        )


def test_batch_requires_sorted_unique_identity_and_slot(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    first, second = fixtures
    batch = ExpectedCellReceiptBatch("batch-a", (first.receipt, second.receipt))
    assert batch.to_wire()["record_ids"] == sorted(
        [first.cell.record_id, second.cell.record_id]
    )
    with pytest.raises(ProtocolViolation, match="sorted"):
        ExpectedCellReceiptBatch("batch-a", (second.receipt, first.receipt))
    with pytest.raises(ProtocolViolation, match="unique"):
        ExpectedCellReceiptBatch("batch-a", (first.receipt, first.receipt))


def test_batch_wire_detects_set_and_digest_rewrite(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    batch = ExpectedCellReceiptBatch(
        "batch-a", tuple(item.receipt for item in fixtures)
    )
    wire = batch.to_wire()
    wire["record_ids"] = list(reversed(wire["record_ids"]))
    wire["exact_set_digest"] = _digest("rewritten-set")
    with pytest.raises(ProtocolViolation, match="stale|non-canonical"):
        ExpectedCellReceiptBatch.from_wire(wire, receipts=batch.receipts)


def test_root_exactly_covers_manifest_and_roundtrips(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    batch = ExpectedCellReceiptBatch(
        "batch-a", tuple(item.receipt for item in fixtures)
    )
    authority, root = _build_root(
        tuple(item.receipt for item in fixtures), (batch,)
    )
    manifest = authority.manifest
    wire = root.to_wire()
    decoded_manifest = base64.b64decode(wire["manifest_preimage_base64"])
    assert decoded_manifest == manifest.canonical_bytes
    assert wire["expected_record_ids"] == sorted(
        item.cell.record_id for item in fixtures
    )
    assert (
        ExpectedCellReceiptRoot.from_wire(
            wire,
            manifest=manifest,
            scope_contract=authority.contract,
            batches=(batch,),
        ).root_digest
        == root.root_digest
    )


def test_root_rejects_missing_extra_and_duplicate_receipts(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    first, second = fixtures
    first_batch = ExpectedCellReceiptBatch("batch-a", (first.receipt,))
    second_batch = ExpectedCellReceiptBatch("batch-b", (second.receipt,))
    authority = _root_authority((first.receipt, second.receipt))
    with pytest.raises(
        ProtocolViolation, match="exact manifest set|materialization ledgers"
    ):
        ExpectedCellReceiptRoot(
            authority.manifest, authority.contract, (first_batch,)
        )
    first_authority = _root_authority((first.receipt,))
    with pytest.raises(ProtocolViolation, match="duplicate receipt identity"):
        ExpectedCellReceiptRoot(
            first_authority.manifest,
            first_authority.contract,
            (
                first_batch,
                ExpectedCellReceiptBatch("batch-b", (first.receipt,)),
            ),
        )
    authority = _root_authority((first.receipt, second.receipt))
    with pytest.raises(ProtocolViolation, match="sorted"):
        ExpectedCellReceiptRoot(
            authority.manifest,
            authority.contract,
            (second_batch, first_batch),
        )


def test_one_source_row_legitimately_expands_to_multiple_task_horizon_cells() -> None:
    fixtures = _make_multi_cell_fixtures()
    receipts = tuple(item.receipt for item in fixtures)
    assert len({item.materialization.source.source_digest for item in fixtures}) == 1
    assert len({item.cell.episode_alias for item in fixtures}) == 1
    assert len({item.materialization.receipt_digest for item in fixtures}) == 2
    assert len(
        {
            item.materialization.evidence.materialization_slot_digest
            for item in fixtures
        }
    ) == 2
    assert len({item.query.preimage_digest for item in fixtures}) == 2
    assert len({item.request.preimage_digest for item in fixtures}) == 2
    assert len({item.response.preimage_digest for item in fixtures}) == 2
    batch = ExpectedCellReceiptBatch("batch-multi-query", receipts)
    authority, root = _build_root(receipts, (batch,))
    assert len(root.to_wire()["expected_record_ids"]) == 2
    assert len(authority.contract.queries) == 2


def _make_w19_tail_fixture() -> _Fixture:
    return _make_fixture(
        19,
        world_slot="W19",
        task=EvaluationTask.INTERVENTION,
        horizon=7,
        policy_alias="safety-policy",
        tail_member=True,
        cell_unsafe_action_ids=("A1",),
    )


def test_w19_tail_receipt_root_exact_joins_safety_and_intervention() -> None:
    fixture = _make_w19_tail_fixture()
    aliases = (fixture.cell.episode_alias,)
    contract_safety = W19SafetyContract("A1", 10.0)
    declaration = W19SafetyDeclaration(
        aliases,
        W19SafetyDeclaration.compute_digest(aliases),
        "A1",
        10.0,
    )
    batch = ExpectedCellReceiptBatch("batch-w19", (fixture.receipt,))
    authority, root = _build_root(
        (fixture.receipt,),
        (batch,),
        w19_contract=contract_safety,
        w19_declaration=declaration,
    )
    assert authority.contract.w19_safety == contract_safety
    assert root.manifest.w19_safety == declaration
    assert root.to_wire()["expected_record_ids"] == [fixture.cell.record_id]


def test_w19_tail_root_rejects_wrong_aliases_and_stale_live_digest() -> None:
    fixture = _make_w19_tail_fixture()
    aliases = (fixture.cell.episode_alias,)
    batch = ExpectedCellReceiptBatch("batch-w19", (fixture.receipt,))
    contract_safety = W19SafetyContract("A1", 10.0)

    wrong_aliases = ("foreign-tail-episode",)
    wrong_alias_declaration = W19SafetyDeclaration(
        wrong_aliases,
        W19SafetyDeclaration.compute_digest(wrong_aliases),
        "A1",
        10.0,
    )
    wrong_alias_authority = _root_authority(
        (fixture.receipt,),
        w19_contract=contract_safety,
        w19_declaration=wrong_alias_declaration,
    )
    with pytest.raises(ProtocolViolation, match="aliases do not exactly cover"):
        ExpectedCellReceiptRoot(
            wrong_alias_authority.manifest,
            wrong_alias_authority.contract,
            (batch,),
        )

    stale_digest_declaration = W19SafetyDeclaration(
        aliases,
        _digest("stale-w19-tail-cohort"),
        "A1",
        10.0,
    )
    stale_authority = _root_authority(
        (fixture.receipt,),
        w19_contract=contract_safety,
        w19_declaration=stale_digest_declaration,
    )
    with pytest.raises(ProtocolViolation, match="tail cohort digest is not live-derived"):
        ExpectedCellReceiptRoot(
            stale_authority.manifest,
            stale_authority.contract,
            (batch,),
        )


def test_w19_contract_action_and_margin_must_exact_join_manifest() -> None:
    fixture = _make_w19_tail_fixture()
    aliases = (fixture.cell.episode_alias,)
    declaration = W19SafetyDeclaration(
        aliases,
        W19SafetyDeclaration.compute_digest(aliases),
        "B2",
        20.0,
    )
    batch = ExpectedCellReceiptBatch("batch-w19", (fixture.receipt,))
    authority = _root_authority(
        (fixture.receipt,),
        w19_contract=W19SafetyContract("A1", 10.0),
        w19_declaration=declaration,
    )
    with pytest.raises(ProtocolViolation, match="action/margin"):
        ExpectedCellReceiptRoot(
            authority.manifest,
            authority.contract,
            (batch,),
        )


def test_repackaged_cell_cannot_enter_original_manifest_root(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    repackaged_panel = "repackaged-panel"
    repackaged_family_id = _derived_family_id(
        scope_digest=fixture.cell.scope_digest,
        world_slot=fixture.cell.world_slot,
        panel_id=repackaged_panel,
        split=fixture.cell.split.value,
        evaluation_replicate_id=fixture.cell.evaluation_replicate_id,
        source_family_digest=fixture.materialization.source.units[0].family_digest,
    )
    repackaged_cell = _rederive_cell(
        fixture.cell,
        fixture.query.payload["source_record_id"],
        panel_id=repackaged_panel,
        family_id=repackaged_family_id,
    )
    with pytest.raises(ProtocolViolation, match="record_id does not join"):
        ExpectedCellPreimageReceipt(
            repackaged_cell,
            fixture.materialization,
            fixture.query,
            fixture.oracle,
            fixture.request,
            fixture.response,
        )


def test_root_swap_and_manifest_identity_drift_fail_closed(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    first, second = fixtures
    batch = ExpectedCellReceiptBatch(
        "batch-a", (first.receipt, second.receipt)
    )
    authority, root = _build_root((first.receipt, second.receipt), (batch,))
    manifest = authority.manifest
    swapped = root.to_wire()
    swapped["receipt_set_root"] = _digest("foreign-root")
    swapped["root_digest"] = _digest("resigned-root")
    with pytest.raises(ProtocolViolation, match="stale|non-canonical"):
        ExpectedCellReceiptRoot.from_wire(
            swapped,
            manifest=manifest,
            scope_contract=authority.contract,
            batches=(batch,),
        )
    drifted_manifest = EvaluationManifest(
        scope_digest=SCOPE,
        expected_cells=(replace(first.cell, panel_id="foreign-panel"), second.cell),
        cell_contract_digest=manifest.cell_contract_digest,
    )
    with pytest.raises(
        ProtocolViolation, match="contradicts manifest|corpus pin|not code-owned"
    ):
        ExpectedCellReceiptRoot(drifted_manifest, authority.contract, (batch,))


def test_root_requires_ready_code_owned_coverage_and_corpus_scope_pins(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    authority = _root_authority((fixture.receipt,))

    receipts_module.CODE_OWNED_COVERAGE_LOCK = DEFAULT_CODE_LOCK
    with pytest.raises(ProtocolViolation, match="not ready|coverage lock|benchmark"):
        ExpectedCellReceiptRoot(
            authority.manifest, authority.contract, (batch,)
        )

    receipts_module.CODE_OWNED_COVERAGE_LOCK = authority.lock
    receipts_module.CODE_OWNED_CORPUS_SCOPE_PINS = ()
    with pytest.raises(ProtocolViolation, match="corpus scope pins are not ready"):
        ExpectedCellReceiptRoot(
            authority.manifest, authority.contract, (batch,)
        )

    foreign_pin = replace(
        authority.contract.shards[0],
        candidate_digest=_digest("foreign-candidate-corpus"),
    )
    receipts_module.CODE_OWNED_CORPUS_SCOPE_PINS = (foreign_pin,)
    with pytest.raises(ProtocolViolation, match="code-owned pins"):
        ExpectedCellReceiptRoot(
            authority.manifest, authority.contract, (batch,)
        )


def test_caller_cannot_resign_repackaged_corpus_scope_contract(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    authority = _root_authority((fixture.receipt,))
    foreign_shard = replace(
        authority.contract.shards[0],
        panel_id="caller-repackaged-panel",
        training_replicate_id="caller-train",
        evaluation_replicate_id="caller-eval",
        candidate_digest=_digest("caller-candidate"),
        judge_digest=_digest("caller-judge"),
        status_digest=_digest("caller-status"),
    )
    foreign_contract = replace(authority.contract, shards=(foreign_shard,))
    resigned_manifest = replace(
        authority.manifest, cell_contract_digest=foreign_contract.digest
    )
    # Keep the reviewed lock and corpus pins; only the caller-owned contract and
    # its manifest digest are re-signed.
    receipts_module.CODE_OWNED_COVERAGE_LOCK = authority.lock
    receipts_module.CODE_OWNED_CORPUS_SCOPE_PINS = authority.contract.shards
    with pytest.raises(ProtocolViolation, match="code-owned pins|not code-owned"):
        ExpectedCellReceiptRoot(
            resigned_manifest, foreign_contract, (batch,)
        )


def test_root_rejects_foreign_or_overlapping_materialization_ledgers(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    authority = _root_authority((fixture.receipt,))
    original_ledgers = receipts_module.CODE_OWNED_MATERIALIZATION_LEDGERS
    assert len(original_ledgers) == 1
    receipts_module.CODE_OWNED_MATERIALIZATION_LEDGERS = (
        original_ledgers[0],
        original_ledgers[0],
    )
    with pytest.raises(
        ProtocolViolation, match="multiple code-owned ledgers|ledgers repeat"
    ):
        ExpectedCellReceiptRoot(
            authority.manifest, authority.contract, (batch,)
        )

    foreign = _make_fixture(99)
    receipts_module.CODE_OWNED_MATERIALIZATION_LEDGERS = (
        build_materialization_receipt_ledger(
            foreign.materialization.source,
            foreign.materialization.assignment,
            (foreign.materialization,),
        ),
    )
    with pytest.raises(ProtocolViolation, match="materialization ledgers"):
        ExpectedCellReceiptRoot(
            authority.manifest, authority.contract, (batch,)
        )


def test_coverage_lock_rejects_duplicate_identity_under_new_shard_alias(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    authority = _root_authority((fixture.receipt,))
    original_shard = authority.contract.shards[0]
    duplicate_identity = replace(original_shard, shard_id="second-shard-alias")
    duplicate_contract = replace(
        authority.contract, shards=(original_shard, duplicate_identity)
    )
    duplicate_manifest = replace(
        authority.manifest, cell_contract_digest=duplicate_contract.digest
    )
    receipts_module.CODE_OWNED_CORPUS_SCOPE_PINS = (
        original_shard,
        duplicate_identity,
    )
    receipts_module.CODE_OWNED_SCOPE_CONTRACT_DIGEST = duplicate_contract.digest
    receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST = duplicate_manifest.digest
    with pytest.raises(ProtocolViolation, match="repeat a coverage identity"):
        ExpectedCellReceiptRoot(
            duplicate_manifest, duplicate_contract, (batch,)
        )


def test_coverage_lock_recursively_rejects_numeric_template_type_drift(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    authority = _root_authority((fixture.receipt,))
    template = authority.lock.shards[0].population_queries[0]
    object.__setattr__(template, "horizon", 0.0)
    resigned_contract = replace(
        authority.contract, coverage_lock_digest=authority.lock.digest
    )
    resigned_manifest = replace(
        authority.manifest, cell_contract_digest=resigned_contract.digest
    )
    receipts_module.CODE_OWNED_SCOPE_CONTRACT_DIGEST = resigned_contract.digest
    receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST = resigned_manifest.digest
    with pytest.raises(ProtocolViolation, match="locked query horizon"):
        ExpectedCellReceiptRoot(
            resigned_manifest, resigned_contract, (batch,)
        )


def test_each_source_exactly_covers_locked_query_template_denominator(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    authority = _root_authority((fixture.receipt,))
    locked_shard = authority.lock.shards[0]
    extra_template = LockedQueryTemplate(
        "presentation", EvaluationTask.NATURAL_FORECAST, 2, "natural"
    )
    expanded_locked_shard = replace(
        locked_shard,
        population_queries=tuple(
            sorted(
                (*locked_shard.population_queries, extra_template),
                key=lambda item: canonical_json_bytes(item.to_wire()),
            )
        ),
    )
    expanded_lock = replace(authority.lock, shards=(expanded_locked_shard,))
    expanded_corpus_shard = replace(
        authority.contract.shards[0],
        required_tasks=(
            EvaluationTask.DIAGNOSIS,
            EvaluationTask.NATURAL_FORECAST,
        ),
    )
    resigned_contract = replace(
        authority.contract,
        coverage_lock_digest=expanded_lock.digest,
        shards=(expanded_corpus_shard,),
    )
    resigned_manifest = replace(
        authority.manifest, cell_contract_digest=resigned_contract.digest
    )
    receipts_module.CODE_OWNED_COVERAGE_LOCK = expanded_lock
    receipts_module.CODE_OWNED_CORPUS_SCOPE_PINS = (expanded_corpus_shard,)
    receipts_module.CODE_OWNED_SCOPE_CONTRACT_DIGEST = resigned_contract.digest
    receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST = resigned_manifest.digest
    with pytest.raises(ProtocolViolation, match="template denominator"):
        ExpectedCellReceiptRoot(
            resigned_manifest, resigned_contract, (batch,)
        )


def test_receipt_set_root_is_invariant_to_transport_batch_partition(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    first, second = fixtures
    receipts = (first.receipt, second.receipt)
    authority = _root_authority(receipts)
    one_batch_root = ExpectedCellReceiptRoot(
        authority.manifest,
        authority.contract,
        (ExpectedCellReceiptBatch("batch-all", receipts),),
    )
    split_batch_root = ExpectedCellReceiptRoot(
        authority.manifest,
        authority.contract,
        (
            ExpectedCellReceiptBatch("batch-a", (first.receipt,)),
            ExpectedCellReceiptBatch("batch-b", (second.receipt,)),
        ),
    )
    assert one_batch_root.receipt_set_root == split_batch_root.receipt_set_root
    assert (
        one_batch_root.to_wire()["receipt_entries"]
        == split_batch_root.to_wire()["receipt_entries"]
    )


def test_pair_metadata_rederives_identity_and_exact_joins_thresholds(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    authority = _root_authority((fixture.receipt,))
    shard = authority.contract.shards[0]
    source_pair_id = "source-pair"
    contract_thresholds = PairThresholds(0.1, 0.2, 0.3, 0.4, 10.0)
    contract_pair = PairCellContract(
        shard.shard_id, source_pair_id, contract_thresholds
    )
    pair_fields = {
        "scope_digest": SCOPE,
        "world_slot": shard.world_slot,
        "panel_id": shard.panel_id,
        "source_pair_id": source_pair_id,
        "split": shard.split.value,
        "family_id": fixture.cell.family_id,
        "training_replicate_id": shard.training_replicate_id,
        "evaluation_replicate_id": shard.evaluation_replicate_id,
    }
    correct_pair_id = _derived_pair_id(**pair_fields)
    contract = replace(authority.contract, pairs=(contract_pair,))

    arbitrary_pair = ExpectedPairCell(
        pair_id="p-arbitrary",
        world_slot=shard.world_slot,
        panel_id=shard.panel_id,
        thresholds=contract_thresholds,
        scope_digest=SCOPE,
        split=shard.split,
        family_id=fixture.cell.family_id,
        training_replicate_id=shard.training_replicate_id,
        evaluation_replicate_id=shard.evaluation_replicate_id,
    )
    arbitrary_manifest = replace(
        authority.manifest,
        expected_pairs=(arbitrary_pair,),
        cell_contract_digest=contract.digest,
    )
    receipts_module.CODE_OWNED_SCOPE_CONTRACT_DIGEST = contract.digest
    receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST = arbitrary_manifest.digest
    with pytest.raises(ProtocolViolation, match="pair_id is not exactly derived"):
        ExpectedCellReceiptRoot(arbitrary_manifest, contract, (batch,))

    drifted_pair = replace(
        arbitrary_pair,
        pair_id=correct_pair_id,
        thresholds=PairThresholds(0.1, 0.2, 0.3, 0.4, 20.0),
    )
    drifted_manifest = replace(
        authority.manifest,
        expected_pairs=(drifted_pair,),
        cell_contract_digest=contract.digest,
    )
    receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST = drifted_manifest.digest
    with pytest.raises(ProtocolViolation, match="pair thresholds"):
        ExpectedCellReceiptRoot(drifted_manifest, contract, (batch,))


def test_registry_and_evaluator_thresholds_exact_join_code_owned_contract(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    authority = _root_authority((fixture.receipt,))
    foreign_registry_contract = replace(
        authority.contract, registry_digest=_digest("foreign-registry")
    )
    foreign_registry_manifest = replace(
        authority.manifest,
        cell_contract_digest=foreign_registry_contract.digest,
    )
    receipts_module.CODE_OWNED_SCOPE_CONTRACT_DIGEST = (
        foreign_registry_contract.digest
    )
    receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST = (
        foreign_registry_manifest.digest
    )
    with pytest.raises(ProtocolViolation, match="registry digest"):
        ExpectedCellReceiptRoot(
            foreign_registry_manifest, foreign_registry_contract, (batch,)
        )

    authority = _root_authority((fixture.receipt,))
    drifted_threshold_manifest = replace(
        authority.manifest, forced_known_max_known=0.85
    )
    receipts_module.CODE_OWNED_EXPECTED_MANIFEST_DIGEST = (
        drifted_threshold_manifest.digest
    )
    with pytest.raises(ProtocolViolation, match="forced_known_max_known"):
        ExpectedCellReceiptRoot(
            drifted_threshold_manifest, authority.contract, (batch,)
        )


def test_root_recursively_revalidates_post_construction_manifest_children(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    authority = _root_authority((fixture.receipt,))
    manifest_cell = replace(fixture.cell)
    manifest = EvaluationManifest(
        scope_digest=SCOPE,
        expected_cells=(manifest_cell,),
        cell_contract_digest=authority.contract.digest,
    )
    object.__setattr__(manifest_cell, "horizon", 0.0)
    batch = ExpectedCellReceiptBatch("batch-a", (fixture.receipt,))
    with pytest.raises(ProtocolViolation, match="horizon"):
        ExpectedCellReceiptRoot(manifest, authority.contract, (batch,))


def test_live_post_construction_mutation_is_detected(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    fixture = fixtures[0]
    original = fixture.request.canonical_bytes
    try:
        object.__setattr__(
            fixture.request,
            "canonical_bytes",
            canonical_json_bytes({"post_construction": "rewrite"}),
        )
        with pytest.raises(ProtocolViolation, match="changed after construction"):
            fixture.receipt.to_wire()
    finally:
        object.__setattr__(fixture.request, "canonical_bytes", original)
    assert fixture.receipt.to_wire()["status"] == "pre_freeze_scaffold"


def test_receipt_root_never_claims_freeze_or_clears_e002_e003(
    fixtures: tuple[_Fixture, _Fixture],
) -> None:
    batch = ExpectedCellReceiptBatch(
        "batch-a", tuple(item.receipt for item in fixtures)
    )
    _, root = _build_root(tuple(item.receipt for item in fixtures), (batch,))
    wire = root.to_wire()
    assert root.benchmark_freeze_eligible is False
    assert wire["status"] == "pre_freeze_scaffold"
    assert wire["freeze_grade_evidence"] is False
    assert wire["benchmark_freeze_eligible"] is False
    assert {item["code"] for item in wire["blockers"]} == {E002_CODE, E003_CODE}
