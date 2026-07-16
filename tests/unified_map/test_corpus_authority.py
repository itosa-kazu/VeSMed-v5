from __future__ import annotations

import inspect
from dataclasses import fields, replace
from pathlib import Path

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from prototype.unified_map.corpus_authority import (
    AUDIT_PROTOCOL,
    INCOMPLETE_CODE,
    AuthorityBoundCorpusAudit,
    AuthorityBoundCorpusScope,
    CorpusAuthorityStatus,
    audit_authority_bound_corpus,
)
from prototype.unified_map.family_manifest import (
    AtomicLinkDraft,
    AtomicLinkSemantic,
    BuilderRandomnessTranscript,
    FamilySplit,
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
    build_materialization_receipt_ledger,
    build_pre_split_family_source,
    build_weighted_atomic_assignment,
    compute_row_bundle_commitment,
    issue_materialization_receipt_batch,
)
from prototype.unified_map.schema import VisibleHistory
from prototype.unified_map.strata_manifest import (
    AllocationCellValue,
    AllocationDimension,
    DualChannelStrataAuthority,
    JudgeStrataAuthority,
    PublicClassifierAuthority,
    SlotAllocationCell,
    SlotAllocationDraft,
    StrataReceiptBatch,
    StrataRowJoin,
    build_pre_split_strata_allocation_manifest,
    compute_slot_strata_allocation_commitment,
    issue_strata_row_receipt_batch,
)
from prototype.unified_map.world_registry import (
    MaterializationStatus,
    materialize_world_split,
)
from prototype.unified_map.worlds.base import WorldSplit


BENCHMARK = "UCM-BENCHMARK-v1"
REVISION = "PRE-FREEZE-v1"
SCOPE = digest_json({"fixture": "authority-bound-corpus-scope"})
PANEL = "panel-main"
TRAINING_REPLICATE = "train-01"
EVALUATION_REPLICATE = "eval-01"


def _digest(label: str) -> str:
    return digest_json({"fixture": label})


def _member(alias: str, semantic: SourceMemberSemantic) -> SourceMemberDraft:
    return SourceMemberDraft(
        alias,
        semantic,
        {"trajectory_cell": alias, "clinical_value": 0.5},
    )


def _write_rows(path: Path, rows: list[dict]) -> bytes:
    payload = b"".join(canonical_json_bytes(row) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _fixture_rows(
    world: str,
    count: int,
    history: VisibleHistory,
    catalog: dict,
) -> tuple[list[dict], list[dict]]:
    candidates: list[dict] = []
    judges: list[dict] = []
    for index in range(count):
        record_id = f"record-{index:03d}"
        if world == "W01":
            labels = ["iid_support", "boundary_tail"]
        elif world == "W03":
            labels = ["iid_support", "behavior_pair"]
        else:
            labels = (
                ["iid_support", "boundary_tail"]
                if index == 0
                else ["iid_support"]
            )
        candidates.append(
            {
                "schema_version": "ucm-candidate-public-episode/1",
                "record_id": record_id,
                "scope_digest": SCOPE,
                "catalog": catalog,
                "public_history": history.to_wire(),
            }
        )
        judges.append(
            {
                "schema_version": "ucm-judge-private-episode/1",
                "record_id": record_id,
                "scope_digest": SCOPE,
                "world_slot": world,
                "panel_id": PANEL,
                "split": "sealed_test",
                "cohort": "population" if world != "W03" else "probe",
                "population_denominator": world != "W03",
                "probe_denominator": world == "W03",
                "pair_id": "pair-live-0" if world == "W03" else None,
                "pair_side": index if world == "W03" else None,
                "strata": labels,
                "unverified_declared_strata": [],
                "public_history_digest": history.digest,
                "hidden_state_at_cut": {"row": index, "state": [index, 0.5]},
            }
        )
    return candidates, judges


def _build_scope(tmp_path: Path, world: str = "W01") -> AuthorityBoundCorpusScope:
    if world not in {"W01", "W03", "W19"}:
        raise AssertionError("unsupported fixture world")
    count = {"W01": 1, "W03": 2, "W19": 64}[world]
    catalog = {"schema_version": "unit-catalog/1", "world_slot": world}
    history = VisibleHistory((), 0, digest_json(catalog))
    candidate_rows, judge_rows = _fixture_rows(world, count, history, catalog)

    row_bindings: list[dict[str, object]] = []
    for index, (candidate, judge) in enumerate(zip(candidate_rows, judge_rows, strict=True)):
        record_id = candidate["record_id"]
        row_bindings.append(
            {
                "index": index,
                "record_id": record_id,
                "candidate_digest": digest_json(candidate),
                "judge_digest": digest_json(judge),
                "hidden_digest": digest_json(judge["hidden_state_at_cut"]),
                "oracle_digest": _digest(f"oracle-{record_id}"),
                "request_digest": _digest(f"request-{record_id}"),
                "response_digest": _digest(f"response-{record_id}"),
            }
        )

    drafts: tuple[ProducerSourceUnitDraft, ...]
    transcripts: tuple[BuilderRandomnessTranscript, ...]
    pairs: tuple[PairConstraintDraft, ...]
    links: tuple[AtomicLinkDraft, ...]
    slot_drafts: list[MaterializationSlotDraft] = []
    cells_by_slot_alias: dict[str, tuple[SlotAllocationCell, ...]] = {}

    if world == "W19":
        drafts = tuple(
            ProducerSourceUnitDraft(
                f"family-{index:03d}",
                world,
                SourceUnitSemantic.PATIENT_FAMILY,
                {"recipe": "w19-row"},
                1,
                (_member("assignment-row", SourceMemberSemantic.W19_ASSIGNMENT_ROW),),
            )
            for index in range(count)
        )
        transcripts = tuple(
            BuilderRandomnessTranscript(
                draft.unit_alias,
                "corpus-fixture-builder",
                f"build-{index:03d}",
                {"draws": [index, 1]},
                {"draws": [index, 2]},
                {"draws": [index, 3]},
            )
            for index, draft in enumerate(drafts)
        )
        pairs = ()
        links = (
            AtomicLinkDraft(
                "w19-block-0",
                AtomicLinkSemantic.W19_ASSIGNMENT_CLUSTER,
                tuple(
                    MemberRefDraft(draft.unit_alias, "assignment-row")
                    for draft in drafts
                ),
            ),
        )
        for binding, draft in zip(row_bindings, drafts, strict=True):
            index = int(binding["index"])
            cells = (
                SlotAllocationCell(
                    AllocationDimension.BOUNDARY_TAIL,
                    (
                        AllocationCellValue.RARE_TAIL
                        if index == 0
                        else AllocationCellValue.COMMON
                    ),
                ),
                SlotAllocationCell(
                    AllocationDimension.POLICY_COVERAGE_HOLDOUT,
                    AllocationCellValue.SUPPORT,
                ),
            )
            slot_alias = f"slot-{index:03d}"
            cells_by_slot_alias[slot_alias] = cells
            slot_drafts.append(
                MaterializationSlotDraft(
                    slot_alias,
                    draft.unit_alias,
                    "assignment-row",
                    MaterializationRole.W19_ASSIGNMENT_ROW,
                    "sealed-test",
                    _digest(f"cut-{index:03d}"),
                    _digest(f"query-{index:03d}"),
                    atomic_link_alias="w19-block-0",
                    row_bundle_commitment_digest=compute_row_bundle_commitment(
                        record_id=str(binding["record_id"]),
                        public_history_digest=history.digest,
                        hidden_state_at_cut_digest=str(binding["hidden_digest"]),
                        oracle_target_digest=str(binding["oracle_digest"]),
                        candidate_row_digest=str(binding["candidate_digest"]),
                        judge_row_digest=str(binding["judge_digest"]),
                        raw_request_digest=str(binding["request_digest"]),
                        raw_response_digest=str(binding["response_digest"]),
                    ),
                    strata_allocation_commitment_digest=(
                        compute_slot_strata_allocation_commitment(world, cells)
                    ),
                )
            )
    else:
        member_specs = (
            (
                ("left", SourceMemberSemantic.COUNTERFACTUAL_VARIANT),
                ("right", SourceMemberSemantic.COUNTERFACTUAL_VARIANT),
            )
            if world == "W03"
            else (("ordinary", SourceMemberSemantic.PATIENT_TRAJECTORY),)
        )
        drafts = (
            ProducerSourceUnitDraft(
                "family-main",
                world,
                SourceUnitSemantic.PATIENT_FAMILY,
                {"recipe": "authority-corpus-fixture"},
                1,
                tuple(_member(alias, semantic) for alias, semantic in member_specs),
            ),
        )
        transcripts = (
            BuilderRandomnessTranscript(
                "family-main",
                "corpus-fixture-builder",
                "build-main",
                {"draws": [1]},
                {"draws": [2]},
                {"draws": [3]},
            ),
        )
        pairs = (
            (
                PairConstraintDraft(
                    "pair-main",
                    PairSemantic.BEHAVIORAL,
                    (
                        PairSideDraft("family-main", "left", 0),
                        PairSideDraft("family-main", "right", 1),
                    ),
                ),
            )
            if world == "W03"
            else ()
        )
        links = ()
        for binding, (member_alias, _) in zip(row_bindings, member_specs, strict=True):
            index = int(binding["index"])
            cells = (
                ()
                if world == "W03"
                else (
                    SlotAllocationCell(
                        AllocationDimension.BOUNDARY_TAIL,
                        AllocationCellValue.HOLDOUT,
                    ),
                )
            )
            slot_alias = f"slot-{index:03d}"
            cells_by_slot_alias[slot_alias] = cells
            slot_drafts.append(
                MaterializationSlotDraft(
                    slot_alias,
                    "family-main",
                    member_alias,
                    (
                        MaterializationRole.PAIR_SIDE
                        if world == "W03"
                        else MaterializationRole.STANDARD_ROW
                    ),
                    "sealed-test",
                    _digest("pair-cut") if world == "W03" else _digest("cut-main"),
                    _digest("pair-query") if world == "W03" else _digest("query-main"),
                    "pair-main" if world == "W03" else None,
                    index if world == "W03" else None,
                    row_bundle_commitment_digest=compute_row_bundle_commitment(
                        record_id=str(binding["record_id"]),
                        public_history_digest=history.digest,
                        hidden_state_at_cut_digest=str(binding["hidden_digest"]),
                        oracle_target_digest=str(binding["oracle_digest"]),
                        candidate_row_digest=str(binding["candidate_digest"]),
                        judge_row_digest=str(binding["judge_digest"]),
                        raw_request_digest=str(binding["request_digest"]),
                        raw_response_digest=str(binding["response_digest"]),
                    ),
                    strata_allocation_commitment_digest=(
                        compute_slot_strata_allocation_commitment(world, cells)
                    ),
                )
            )

    source = build_pre_split_family_source(
        benchmark_id=BENCHMARK,
        benchmark_revision=REVISION,
        registry_digest=_digest("registry"),
        generator_bundle_digest=_digest(f"generator-bundle-{world}"),
        topology_contract_digest=_digest("topology-contract"),
        query_contract_digest=_digest("query-contract"),
        builder_id="corpus-fixture-builder",
        builder_version="fixture-v1",
        drafts=drafts,
        transcripts=transcripts,
        pair_topology=pairs,
        atomic_links=links,
        materialization_slots=tuple(slot_drafts),
    )
    assignment = build_weighted_atomic_assignment(
        source,
        {unit.authority_digest: FamilySplit.SEALED_TEST for unit in source.units},
        split_policy_digest=_digest("split-policy"),
        split_seed_commitment=_digest("split-seed"),
    )
    binding_by_slot = {
        f"slot-{int(binding['index']):03d}": binding for binding in row_bindings
    }
    evidences = []
    assignment_by_authority = {
        item.authority_digest: item for item in assignment.assignments
    }
    for slot in source.materialization_slots:
        binding = binding_by_slot[slot.slot_alias]
        evidences.append(
            RowMaterializationEvidence(
                record_id=str(binding["record_id"]),
                assigned_split=assignment_by_authority[
                    slot.reference.authority_digest
                ].assigned_split,
                authority_digest=slot.reference.authority_digest,
                member_digest=slot.reference.member_digest,
                public_history_digest=history.digest,
                hidden_state_at_cut_digest=str(binding["hidden_digest"]),
                query_cell_digest=slot.query_cell_digest,
                oracle_target_digest=str(binding["oracle_digest"]),
                candidate_row_digest=str(binding["candidate_digest"]),
                judge_row_digest=str(binding["judge_digest"]),
                raw_request_digest=str(binding["request_digest"]),
                raw_response_digest=str(binding["response_digest"]),
                materialization_slot_digest=slot.slot_digest,
                cut_digest=slot.cut_digest,
                stage_label=slot.stage_label,
                materialization_role=slot.materialization_role,
                pair_digest=slot.pair_digest,
                pair_side=slot.pair_side,
                atomic_link_digest=slot.atomic_link_digest,
            )
        )
    receipts = issue_materialization_receipt_batch(source, assignment, tuple(evidences))
    ledger = build_materialization_receipt_ledger(source, assignment, receipts)
    allocation = build_pre_split_strata_allocation_manifest(
        family_source=source,
        world_slot=world,
        generator_source_digest=_digest(f"generator-source-{world}"),
        allocation_policy_digest=_digest(f"allocation-policy-{world}"),
        builder_id="corpus-strata-builder",
        builder_version="fixture-v1",
        slot_drafts=tuple(
            SlotAllocationDraft(slot.slot_digest, cells_by_slot_alias[slot.slot_alias])
            for slot in source.materialization_slots
        ),
    )
    public = PublicClassifierAuthority(
        BENCHMARK,
        REVISION,
        world,
        f"{world.lower()}-public-classifier",
        "fixture-v1",
        _digest(f"classifier-source-{world}"),
    )
    judge = JudgeStrataAuthority(
        source,
        assignment,
        world,
        _digest(f"judge-definition-source-{world}"),
        allocation,
        ledger,
    )
    authority = DualChannelStrataAuthority(public, judge)
    strata_receipts = issue_strata_row_receipt_batch(
        authority,
        tuple(StrataRowJoin(receipt, history) for receipt in ledger.receipts),
    )
    batch = StrataReceiptBatch(authority, strata_receipts)
    expected_labels = {
        receipt.join.family_receipt.evidence.record_id: list(receipt.combined_labels)
        for receipt in batch.receipts
    }
    assert {
        row["record_id"]: row["strata"] for row in judge_rows
    } == expected_labels

    candidate_path = tmp_path / "candidate-public.jsonl"
    judge_path = tmp_path / "judge-private.jsonl"
    candidate_payload = _write_rows(candidate_path, candidate_rows)
    judge_payload = _write_rows(judge_path, judge_rows)
    return AuthorityBoundCorpusScope(
        benchmark_id=BENCHMARK,
        benchmark_revision=REVISION,
        scope_digest=SCOPE,
        world_slot=world,
        panel_id=PANEL,
        training_replicate_id=TRAINING_REPLICATE,
        evaluation_replicate_id=EVALUATION_REPLICATE,
        split=FamilySplit.SEALED_TEST,
        candidate_path=candidate_path,
        judge_path=judge_path,
        candidate_corpus_digest=digest_bytes(candidate_payload),
        judge_corpus_digest=digest_bytes(judge_payload),
        family_source=source,
        family_assignment=assignment,
        family_ledger=ledger,
        strata_batch=batch,
    )


def _rewrite_row(path: Path, index: int, **changes: object) -> None:
    rows = [
        __import__("json").loads(line)
        for line in path.read_bytes().splitlines()
    ]
    rows[index] = {**rows[index], **changes}
    _write_rows(path, rows)


def _details(audit: AuthorityBoundCorpusAudit) -> str:
    return "\n".join(item.detail for item in audit.structural_blockers)


def test_exact_authority_bound_corpus_is_structurally_complete_but_never_freeze_grade(
    tmp_path: Path,
) -> None:
    scope = _build_scope(tmp_path)
    audit = audit_authority_bound_corpus(scope)
    assert audit.status is CorpusAuthorityStatus.PRE_FREEZE_SCAFFOLD
    assert audit.structural_join_complete is True
    assert audit.structural_blockers == ()
    wire = audit.to_wire()
    assert wire["protocol"] == AUDIT_PROTOCOL
    assert wire["status"] == "pre_freeze_scaffold"
    assert wire["freeze_grade_evidence"] is False
    assert wire["benchmark_freeze_eligible"] is False
    assert wire["live_pre_split_materialization_complete"] is False
    assert wire["record_count"] == 1
    assert wire["training_replicate_id"] == TRAINING_REPLICATE
    assert wire["evaluation_replicate_id"] == EVALUATION_REPLICATE
    assert len(wire["authority_roots"]) == 13
    assert all(row["digest"] is not None for row in wire["authority_roots"])
    roots = {row["root_id"]: row["digest"] for row in wire["authority_roots"]}
    assert roots["family_source"] == scope.family_source.source_digest
    assert roots["family_assignment"] == scope.family_assignment.assignment_digest
    assert roots["family_materialization_ledger"] == scope.family_ledger.ledger_digest
    assert roots["dual_channel_authority"] == scope.strata_batch.authority.authority_digest
    assert roots["strata_receipt_batch"] == scope.strata_batch.batch_digest
    assert roots["generator_bundle"] == scope.family_source.generator_bundle_digest
    assert roots["topology_contract"] == scope.family_source.topology_contract_digest
    assert roots["query_contract"] == scope.family_source.query_contract_digest
    assert roots["split_policy"] == scope.family_assignment.split_policy_digest
    assert wire["blockers"] == [
        {
            "code": INCOMPLETE_CODE,
            "artifact": "external_custody_and_atomic_publication",
            "detail": "typed local joins do not prove independent pre-split custody or one atomic publication of the authority roots and both corpus streams",
        }
    ]
    audit_body = dict(wire)
    audit_digest = audit_body.pop("audit_digest")
    assert audit_digest == digest_json(audit_body)
    assert audit.digest == digest_bytes(audit.canonical_bytes)
    assert "freeze_manifest" not in wire


@pytest.mark.parametrize(
    ("target", "mutator", "detail"),
    [
        ("candidate", lambda rows: rows[:-1], "record coverage mismatch"),
        ("candidate", lambda rows: [*rows, rows[0]], "duplicate record_id"),
        (
            "candidate",
            lambda rows: [*rows, {**rows[0], "record_id": "extra-record"}],
            "record coverage mismatch",
        ),
        ("judge", lambda rows: rows[:-1], "record coverage mismatch"),
    ],
)
def test_missing_duplicate_and_extra_rows_fail_closed(
    tmp_path: Path,
    target: str,
    mutator,
    detail: str,
) -> None:
    scope = _build_scope(tmp_path)
    path = scope.candidate_path if target == "candidate" else scope.judge_path
    rows = [__import__("json").loads(line) for line in path.read_bytes().splitlines()]
    _write_rows(path, mutator(rows))
    audit = audit_authority_bound_corpus(scope)
    assert audit.status is CorpusAuthorityStatus.INCOMPLETE
    assert detail in _details(audit)


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("scope_digest", _digest("foreign-scope"), "foreign scope"),
        ("split", "validation", "split contradicts"),
        ("strata", ["iid_support"], "strata labels"),
        ("unverified_declared_strata", ["boundary_tail"], "unverified self-reported"),
        ("public_history_digest", _digest("foreign-history"), "does not exact-join candidate history"),
    ],
)
def test_cross_scope_history_split_and_labels_fail_closed(
    tmp_path: Path,
    field: str,
    value: object,
    detail: str,
) -> None:
    scope = _build_scope(tmp_path)
    _rewrite_row(scope.judge_path, 0, **{field: value})
    audit = audit_authority_bound_corpus(scope)
    assert audit.status is CorpusAuthorityStatus.INCOMPLETE
    assert detail in _details(audit)


def test_noncanonical_or_reordered_live_bytes_fail_closed(tmp_path: Path) -> None:
    scope = _build_scope(tmp_path / "noncanonical", "W03")
    payload = scope.candidate_path.read_bytes()
    scope.candidate_path.write_bytes(payload.replace(b"\n", b"\r\n", 1))
    audit = audit_authority_bound_corpus(scope)
    assert "exactly one LF" in _details(audit)

    scope = _build_scope(tmp_path / "reordered", "W03")
    rows = scope.judge_path.read_bytes().splitlines(keepends=True)
    scope.judge_path.write_bytes(b"".join(reversed(rows)))
    audit = audit_authority_bound_corpus(scope)
    assert "record_id order" in _details(audit)


def test_candidate_row_is_an_exact_closed_schema_not_only_a_key_blacklist(
    tmp_path: Path,
) -> None:
    scope = _build_scope(tmp_path)
    _rewrite_row(
        scope.candidate_path,
        0,
        benign_looking_extension={"opaque": "private-value-smuggling-channel"},
    )
    audit = audit_authority_bound_corpus(scope)
    assert audit.status is CorpusAuthorityStatus.INCOMPLETE
    assert "exact closed public schema" in _details(audit)


def test_replicate_and_source_contract_roots_are_explicit_scope_bindings(
    tmp_path: Path,
) -> None:
    scope = _build_scope(tmp_path)
    wire = scope.to_wire()
    assert scope.contract_digest == digest_json(wire)
    assert wire["training_replicate_id"] == TRAINING_REPLICATE
    assert wire["evaluation_replicate_id"] == EVALUATION_REPLICATE
    roots = {row["root_id"]: row["digest"] for row in wire["authority_roots"]}
    expected_source_roots = {
        "generator_bundle": scope.family_source.generator_bundle_digest,
        "topology_contract": scope.family_source.topology_contract_digest,
        "query_contract": scope.family_source.query_contract_digest,
        "split_policy": scope.family_assignment.split_policy_digest,
    }
    assert {
        root_id: roots[root_id] for root_id in expected_source_roots
    } == expected_source_roots

    changed = replace(scope, evaluation_replicate_id="eval-02")
    assert changed.contract_digest != scope.contract_digest
    assert changed.to_wire()["evaluation_replicate_id"] == "eval-02"
    assert changed.to_wire()["freeze_grade_evidence"] is False
    with pytest.raises(ProtocolViolation, match="training_replicate_id"):
        replace(scope, training_replicate_id=" ")


def test_scope_and_audit_first_digest_seals_reject_rewrite_and_resign(
    tmp_path: Path,
) -> None:
    scope = _build_scope(tmp_path)
    object.__setattr__(scope, "training_replicate_id", "train-02")
    object.__setattr__(
        scope,
        "_sealed_contract_digest",
        digest_json(scope._body_unchecked()),
    )
    audit = audit_authority_bound_corpus(scope)
    assert audit.status is CorpusAuthorityStatus.INCOMPLETE
    assert "scope changed after construction" in _details(audit)

    clean = audit_authority_bound_corpus(_build_scope(tmp_path / "clean"))
    object.__setattr__(clean, "record_count", clean.record_count + 1)
    object.__setattr__(
        clean,
        "_sealed_audit_body_digest",
        digest_json(clean._body_unchecked()),
    )
    with pytest.raises(ProtocolViolation, match="audit changed after construction"):
        clean.to_wire()


def test_source_contract_root_drift_cannot_be_hidden_by_recomputed_inner_seal(
    tmp_path: Path,
) -> None:
    scope = _build_scope(tmp_path)
    source = scope.family_source
    object.__setattr__(source, "generator_bundle_digest", _digest("foreign-generator"))
    object.__setattr__(
        source,
        "_sealed_source_digest",
        digest_json(source._body_unchecked()),
    )
    audit = audit_authority_bound_corpus(scope)
    assert audit.status is CorpusAuthorityStatus.INCOMPLETE
    assert any(
        marker in _details(audit)
        for marker in ("changed after construction", "stale or mismatched")
    )


def test_foreign_authority_and_mutated_slot_fail_closed(tmp_path: Path) -> None:
    scope = _build_scope(tmp_path / "left")
    foreign = _build_scope(tmp_path / "right")
    crossed = replace(scope, family_source=foreign.family_source)
    audit = audit_authority_bound_corpus(crossed)
    assert "foreign family source" in _details(audit)

    scope = _build_scope(tmp_path / "slot")
    slot = scope.family_source.materialization_slots[0]
    object.__setattr__(slot, "stage_label", "foreign-stage")
    audit = audit_authority_bound_corpus(scope)
    assert audit.status is CorpusAuthorityStatus.INCOMPLETE
    assert "slot" in _details(audit) or "authority root is invalid" in _details(audit)


@pytest.mark.parametrize(
    "field_name",
    ("family_source", "family_assignment", "family_ledger", "strata_batch"),
)
def test_each_foreign_authority_root_fails_the_exact_graph_join(
    tmp_path: Path,
    field_name: str,
) -> None:
    scope = _build_scope(tmp_path / "left")
    foreign = _build_scope(tmp_path / "right")
    crossed = replace(scope, **{field_name: getattr(foreign, field_name)})
    audit = audit_authority_bound_corpus(crossed)
    assert audit.status is CorpusAuthorityStatus.INCOMPLETE
    assert "foreign" in _details(audit) or "validation failed" in _details(audit)


def test_pair_alias_side_and_authority_labels_are_not_self_reported(tmp_path: Path) -> None:
    scope = _build_scope(tmp_path, "W03")
    assert audit_authority_bound_corpus(scope).structural_join_complete
    _rewrite_row(scope.judge_path, 1, pair_id="replacement-pair", pair_side=0)
    audit = audit_authority_bound_corpus(scope)
    details = _details(audit)
    assert "replaced by multiple judge pair_ids" in details
    assert "pair_side contradicts" in details


def test_w19_row_replacement_cannot_preserve_a_64_row_quota_block(tmp_path: Path) -> None:
    scope = _build_scope(tmp_path, "W19")
    _rewrite_row(
        scope.judge_path,
        17,
        cohort="probe",
        population_denominator=False,
        probe_denominator=True,
    )
    audit = audit_authority_bound_corpus(scope)
    assert audit.status is CorpusAuthorityStatus.INCOMPLETE
    assert "W19 assignment-row population was replaced" in _details(audit)


def test_protocol_status_flags_and_custody_blocker_are_not_caller_fields(
    tmp_path: Path,
) -> None:
    scope = _build_scope(tmp_path)
    scope_parameters = inspect.signature(AuthorityBoundCorpusScope).parameters
    for forbidden in (
        "protocol",
        "status",
        "freeze_grade_evidence",
        "benchmark_freeze_eligible",
        "blockers",
    ):
        assert forbidden not in scope_parameters
    audit_field_names = {item.name for item in fields(AuthorityBoundCorpusAudit)}
    assert "status" not in audit_field_names
    assert "freeze_grade_evidence" not in audit_field_names
    first = audit_authority_bound_corpus(scope).to_wire()
    first["status"] = "PASS"
    first["freeze_grade_evidence"] = True
    second = audit_authority_bound_corpus(scope).to_wire()
    assert second["status"] == "pre_freeze_scaffold"
    assert second["freeze_grade_evidence"] is False
    assert second["blockers"][0]["code"] == INCOMPLETE_CODE


def test_legacy_post_split_materializer_remains_typed_incomplete(
    tmp_path: Path,
) -> None:
    result = materialize_world_split(
        "W01",
        "primary",
        WorldSplit.VALIDATION,
        101,
        tmp_path / "legacy-materializer",
        alias_secret=b"legacy-authority-bound-corpus".ljust(32, b"!"),
        episode_limit=1,
    )
    assert result.status is MaterializationStatus.INCOMPLETE
    wire = result.to_wire()
    assert wire["status"] == "incomplete"
    assert wire["blockers"]
    assert all(row["code"] == INCOMPLETE_CODE for row in wire["blockers"])
    assert {
        row["interface"] for row in wire["blockers"]
    } >= {"pre_split_family_authority", "dual_channel_stratum_authority"}
