from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import prototype.unified_map.evaluation_cells as cells_module
from prototype.unified_map.candidate_protocol import ResultStatus
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from prototype.unified_map.evaluation_cells import (
    BenchmarkCoverageLock,
    BenchmarkCoverageLockV2,
    CellMaterializationStatus,
    ExpectedCellsScopeContract,
    FrozenAuthorityRoots,
    FrozenCorpusShard,
    FrozenFamilyLineage,
    LockedPairCoverageV2,
    LockedQueryTemplate,
    LockedQuerySetV2,
    LockedShardCoverage,
    LockedShardCoverageV2,
    LockedSourceDenominatorV2,
    PairCellContract,
    QueryCellContract,
    W19SafetyContract,
    audit_raw_exact_join,
    build_expected_cells,
    materialize_expected_cells,
)
from prototype.unified_map.evaluator import (
    EvaluationCohort,
    EvaluationSplit,
    EvaluationTask,
    OODAttribution,
    PairThresholds,
    RawEvaluationRecord,
    RawPairRecord,
    evaluate_records,
)
from prototype.unified_map.metrics import InformationRelation, PairProbe
from prototype.unified_map.world_registry import (
    WORLD_REGISTRY,
    materialize_world_split,
    registry_digest,
)
from prototype.unified_map.worlds.base import WorldSplit


SCOPE = digest_json({"scope": "expected-cells-local-scaffold"})
EMPTY = digest_json({})
THRESHOLDS = PairThresholds(0.01, 0.4, 0.4, 0.01, 10.0)
DEFAULT_CODE_LOCK = cells_module.BENCHMARK_V1_COVERAGE_LOCK
DEFAULT_CODE_LOCK_V2 = cells_module.BENCHMARK_V2_COVERAGE_LOCK


@pytest.fixture(autouse=True)
def _restore_code_owned_lock() -> None:
    try:
        yield
    finally:
        cells_module.BENCHMARK_V1_COVERAGE_LOCK = DEFAULT_CODE_LOCK


@dataclass(frozen=True)
class _FixtureAuthority:
    shards: tuple[FrozenCorpusShard, ...]
    lineage: FrozenFamilyLineage
    roots: FrozenAuthorityRoots
    lock: BenchmarkCoverageLock


def _population_count(world: str, panel: str, split: EvaluationSplit) -> int:
    declaration = next(
        item for item in WORLD_REGISTRY[world].panels if item.panel_id == panel
    )
    source_split = "sealed_test" if split is EvaluationSplit.TEST else split.value
    return next(count for key, count in declaration.split_sizes if key.value == source_split)


def _placeholder_family(name: str) -> str:
    return digest_json({"untrusted_grouping_placeholder": name})


def _judge_row(
    record_id: str,
    *,
    world: str,
    panel: str,
    split: EvaluationSplit,
    cohort: str = "population",
    family_placeholder: str | None = None,
    strata: tuple[str, ...] = ("iid_support",),
    pair_id: str | None = None,
    pair_side: int | None = None,
    public_history_alias: str | None = None,
    source_episode_split: str | None = None,
) -> dict:
    identification = next(
        item.identification
        for item in WORLD_REGISTRY[world].panels
        if item.panel_id == panel
    )
    return {
        "schema_version": "ucm-judge-private-episode/1",
        "record_id": record_id,
        "world_slot": world,
        "panel_id": panel,
        "split": "sealed_test" if split is EvaluationSplit.TEST else split.value,
        "source_episode_split": source_episode_split
        or ("sealed_test" if split is EvaluationSplit.TEST else split.value),
        "cohort": cohort,
        "population_denominator": cohort == "population",
        "probe_denominator": cohort == "probe",
        "population_ordinal": None,
        "probe_id": None if cohort == "population" else "fixture",
        "pair_id": pair_id,
        "pair_side": pair_side,
        "strata": list(strata),
        "unverified_declared_strata": [],
        "case_key": f"case-{record_id}",
        # This value is deliberately only a grouping placeholder.  The
        # independent source artifact is frozen first and the helper then
        # replaces it with the digest derived from those source bytes.
        "family_digest": family_placeholder or _placeholder_family(record_id),
        "environment_key": "fixture-environment",
        "generator_seed": 1,
        "public_history_digest": digest_json(
            {"fixture_history": public_history_alias or record_id}
        ),
        "hidden_state_at_cut": {},
        "invariant_parameters": {},
        "diagnostic_target": {},
        "factual_future": {},
        "action_propensities": {},
        "factual_utility": 0.0,
        "oracle_anchor": {},
        "identification": identification,
    }


def _write_shard(
    root: Path,
    shard_id: str,
    world: str,
    panel: str,
    split: EvaluationSplit,
    required_tasks: tuple[EvaluationTask, ...],
    *,
    family_placeholders: dict[int, str] | None = None,
    strata: dict[int, tuple[str, ...]] | None = None,
    probe_rows: tuple[dict, ...] = (),
    public_history_aliases: dict[int, str] | None = None,
    training_replicate_id: str = "train-01",
    evaluation_replicate_id: str = "eval-01",
) -> tuple[FrozenCorpusShard, tuple[dict, ...]]:
    count = _population_count(world, panel, split)
    rows = tuple(
        _judge_row(
            f"{shard_id}-population-{index:05d}",
            world=world,
            panel=panel,
            split=split,
            family_placeholder=(family_placeholders or {}).get(index),
            strata=(strata or {}).get(index, ("iid_support",)),
            public_history_alias=(public_history_aliases or {}).get(index),
        )
        for index in range(count)
    ) + probe_rows
    public_rows = tuple(
        {
            "schema_version": "ucm-candidate-public-episode/1",
            "record_id": row["record_id"],
            "catalog": {},
            "public_history": {
                "fixture_history": (
                    (public_history_aliases or {}).get(index)
                    if index < count
                    else row["record_id"]
                )
                or row["record_id"]
            },
        }
        for index, row in enumerate(rows)
    )
    directory = root / shard_id
    directory.mkdir(parents=True)
    candidate_path = directory / "candidate-public.jsonl"
    judge_path = directory / "judge-private.jsonl"
    status_path = directory / "materialization-status.json"
    candidate_payload = b"".join(canonical_json_bytes(row) for row in public_rows)
    judge_payload = b"".join(canonical_json_bytes(row) for row in rows)
    candidate_path.write_bytes(candidate_payload)
    judge_path.write_bytes(judge_payload)
    candidate_digest = digest_bytes(candidate_payload)
    judge_digest = digest_bytes(judge_payload)
    status = {
        "schema_version": "ucm-materialization-result/1",
        "status": "complete",
        "world_slot": world,
        "panel_id": panel,
        "split": "sealed_test" if split is EvaluationSplit.TEST else split.value,
        "population_count": count,
        "probe_record_count": len(probe_rows),
        "candidate_file": candidate_path.name,
        "judge_file": judge_path.name,
        "candidate_digest": candidate_digest,
        "judge_digest": judge_digest,
        "blockers": [],
    }
    status_payload = canonical_json_bytes(status)
    status_path.write_bytes(status_payload)
    return (
        FrozenCorpusShard(
            shard_id=shard_id,
            world_slot=world,
            panel_id=panel,
            split=split,
            training_replicate_id=training_replicate_id,
            evaluation_replicate_id=evaluation_replicate_id,
            required_tasks=required_tasks,
            candidate_path=candidate_path,
            judge_path=judge_path,
            status_path=status_path,
            candidate_digest=candidate_digest,
            judge_digest=judge_digest,
            status_digest=digest_bytes(status_payload),
        ),
        rows,
    )


def _queries(
    shard: FrozenCorpusShard,
    rows: tuple[dict, ...],
    task: EvaluationTask,
    *,
    attribution: OODAttribution = OODAttribution.NOT_APPLICABLE,
) -> tuple[QueryCellContract, ...]:
    return tuple(
        QueryCellContract(
            shard.shard_id,
            row["record_id"],
            "cut-0",
            task,
            0 if task in {EvaluationTask.DIAGNOSIS, EvaluationTask.OOD} else 2,
            "policy:A1-A2"
            if task is EvaluationTask.INTERVENTION
            else "policy:none",
            attribution,
        )
        for row in rows
        if row["cohort"] == "population"
    )


def _query_template(query: QueryCellContract) -> LockedQueryTemplate:
    return LockedQueryTemplate(
        query.cut_alias, query.task, query.horizon, query.policy_alias
    )


def _freeze_fixture_authority(
    root: Path,
    shards: tuple[FrozenCorpusShard, ...],
    queries: tuple[QueryCellContract, ...],
    *,
    locked_templates: dict[
        str, tuple[LockedQueryTemplate, ...]
    ] | None = None,
) -> _FixtureAuthority:
    """Create a code-locked local fixture; never benchmark-freeze evidence."""

    rows_by_shard: dict[str, list[dict]] = {}
    placeholder_groups: dict[str, list[dict[str, str]]] = {}
    for shard in shards:
        rows = [
            json.loads(line)
            for line in shard.judge_path.read_text("utf-8").splitlines()
        ]
        rows_by_shard[shard.shard_id] = rows
        for row in rows:
            placeholder_groups.setdefault(row["family_digest"], []).append(
                {
                    "record_id": row["record_id"],
                    "world_slot": row["world_slot"],
                    "panel_id": row["panel_id"],
                    "cohort": row["cohort"],
                }
            )

    source_families: list[dict] = []
    authoritative_by_record: dict[str, str] = {}
    for index, placeholder in enumerate(sorted(placeholder_groups)):
        members = sorted(
            placeholder_groups[placeholder], key=lambda item: canonical_json_bytes(item)
        )
        family_key = f"fixture-family-{index:06d}"
        source_families.append({"family_key": family_key, "members": members})
        family_digest = digest_json(
            {
                "schema_version": "ucm-pre-split-counterfactual-family/1",
                "family_key": family_key,
                "members": members,
            }
        )
        for member in members:
            authoritative_by_record[member["record_id"]] = family_digest

    authority_dir = root / "fixture-authority"
    authority_dir.mkdir(parents=True, exist_ok=True)
    source_path = authority_dir / "family-source.json"
    source = {
        "schema_version": "ucm-pre-split-family-source/1",
        "benchmark_id": "UCM-LOCAL-FIXTURE",
        "benchmark_revision": "LOCAL-SCAFFOLD-v1",
        "scope_digest": SCOPE,
        "registry_digest": registry_digest(),
        "generation_phase": "pre_split",
        "families": source_families,
    }
    source_payload = canonical_json_bytes(source)
    source_path.write_bytes(source_payload)
    source_digest = digest_bytes(source_payload)

    assignment_rows = []
    for family in source_families:
        family_digest = digest_json(
            {
                "schema_version": "ucm-pre-split-counterfactual-family/1",
                "family_key": family["family_key"],
                "members": family["members"],
            }
        )
        for member in family["members"]:
            assignment_rows.append(
                {**member, "family_digest": family_digest}
            )
    assignment_rows.sort(key=lambda item: item["record_id"])
    manifest_path = authority_dir / "family-manifest.json"
    manifest = {
        "schema_version": "ucm-pre-split-family-manifest/1",
        "benchmark_id": "UCM-LOCAL-FIXTURE",
        "benchmark_revision": "LOCAL-SCAFFOLD-v1",
        "scope_digest": SCOPE,
        "source_digest": source_digest,
        "assignments": assignment_rows,
    }
    manifest_payload = canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_payload)
    manifest_digest = digest_bytes(manifest_payload)

    seal_path = authority_dir / "family-seal.json"
    seal = {
        "schema_version": "ucm-pre-split-family-seal/1",
        "state": "PRE_SPLIT_FROZEN",
        "sequence": 0,
        "benchmark_id": "UCM-LOCAL-FIXTURE",
        "benchmark_revision": "LOCAL-SCAFFOLD-v1",
        "scope_digest": SCOPE,
        "registry_digest": registry_digest(),
        "source_digest": source_digest,
        "manifest_digest": manifest_digest,
    }
    seal_payload = canonical_json_bytes(seal)
    seal_path.write_bytes(seal_payload)
    seal_digest = digest_bytes(seal_payload)
    lineage = FrozenFamilyLineage(
        source_path,
        manifest_path,
        seal_path,
        source_digest,
        manifest_digest,
        seal_digest,
    )

    scope_path = authority_dir / "scope.json"
    scope_payload = canonical_json_bytes(
        {"schema_version": "ucm-scope-manifest/1", "scope_digest": SCOPE}
    )
    scope_path.write_bytes(scope_payload)
    scope_manifest_digest = digest_bytes(scope_payload)
    raw_roots_path = authority_dir / "raw-roots.json"
    raw_roots_payload = canonical_json_bytes(
        {
            "schema_version": "ucm-expected-raw-roots/1",
            "scope_digest": SCOPE,
            # Deliberately empty: the implementation must remain a scaffold.
            "cell_roots": [],
        }
    )
    raw_roots_path.write_bytes(raw_roots_payload)
    raw_roots_digest = digest_bytes(raw_roots_payload)
    roots = FrozenAuthorityRoots(
        scope_path,
        raw_roots_path,
        scope_manifest_digest,
        raw_roots_digest,
    )

    updated_shards: list[FrozenCorpusShard] = []
    row_lookup = {
        row["record_id"]: row
        for rows in rows_by_shard.values()
        for row in rows
    }
    for record_id, family_digest in authoritative_by_record.items():
        row_lookup[record_id]["family_digest"] = family_digest
    for shard in shards:
        rows = rows_by_shard[shard.shard_id]
        judge_payload = b"".join(canonical_json_bytes(row) for row in rows)
        shard.judge_path.write_bytes(judge_payload)
        judge_digest = digest_bytes(judge_payload)
        status = json.loads(shard.status_path.read_text("utf-8"))
        status["judge_digest"] = judge_digest
        status["pre_split_family_source_digest"] = source_digest
        status["pre_split_family_manifest_digest"] = manifest_digest
        status["pre_split_family_seal_digest"] = seal_digest
        status_payload = canonical_json_bytes(status)
        shard.status_path.write_bytes(status_payload)
        updated_shards.append(
            replace(
                shard,
                judge_digest=judge_digest,
                status_digest=digest_bytes(status_payload),
            )
        )

    queries_by_shard: dict[str, list[QueryCellContract]] = {}
    for query in queries:
        queries_by_shard.setdefault(query.shard_id, []).append(query)
    coverage: list[LockedShardCoverage] = []
    for shard in updated_shards:
        rows = rows_by_shard[shard.shard_id]
        cohort_by_record = {row["record_id"]: row["cohort"] for row in rows}
        shard_queries = queries_by_shard.get(shard.shard_id, [])
        population_templates = (
            locked_templates[shard.shard_id]
            if locked_templates is not None
            else tuple(
                {
                    _query_template(query)
                    for query in shard_queries
                    if cohort_by_record.get(query.source_record_id) == "population"
                }
            )
        )
        probe_templates = tuple(
            {
                _query_template(query)
                for query in shard_queries
                if cohort_by_record.get(query.source_record_id) == "probe"
            }
        )
        coverage.append(
            LockedShardCoverage(
                shard.world_slot,
                shard.panel_id,
                shard.split,
                shard.training_replicate_id,
                shard.evaluation_replicate_id,
                tuple(population_templates),
                tuple(probe_templates),
            )
        )
    lock = BenchmarkCoverageLock(
        benchmark_id="UCM-LOCAL-FIXTURE",
        benchmark_revision="LOCAL-SCAFFOLD-v1",
        scope_digest=SCOPE,
        scope_manifest_digest=scope_manifest_digest,
        family_source_digest=source_digest,
        family_manifest_digest=manifest_digest,
        family_seal_digest=seal_digest,
        raw_roots_digest=raw_roots_digest,
        query_scope_frozen=True,
        shards=tuple(coverage),
    )
    cells_module.BENCHMARK_V1_COVERAGE_LOCK = lock
    return _FixtureAuthority(tuple(updated_shards), lineage, roots, lock)


def _contract(
    authority: _FixtureAuthority,
    queries: tuple[QueryCellContract, ...],
    pairs: tuple[PairCellContract, ...] = (),
    *,
    w19: W19SafetyContract | None = None,
) -> ExpectedCellsScopeContract:
    return ExpectedCellsScopeContract(
        benchmark_id=authority.lock.benchmark_id,
        benchmark_revision=authority.lock.benchmark_revision,
        scope_digest=SCOPE,
        registry_digest=registry_digest(),
        coverage_lock_digest=authority.lock.digest,
        family_lineage=authority.lineage,
        authority_roots=authority.roots,
        shards=authority.shards,
        queries=queries,
        pairs=pairs,
        w19_safety=w19,
    )


def _raw(cell, **changes) -> RawEvaluationRecord:
    values = dict(
        record_id=cell.record_id,
        world_slot=cell.world_slot,
        panel_id=cell.panel_id,
        episode_alias=cell.episode_alias,
        cohort=cell.cohort,
        task=cell.task,
        result_status=ResultStatus.OK,
        scope_digest=cell.scope_digest,
        split=cell.split,
        family_id=cell.family_id,
        cut_alias=cell.cut_alias,
        training_replicate_id=cell.training_replicate_id,
        evaluation_replicate_id=cell.evaluation_replicate_id,
        horizon=cell.horizon,
        policy_alias=cell.policy_alias,
        state_hash=EMPTY,
        public_input_digest=EMPTY,
        query_digest=EMPTY,
        candidate_output={},
        candidate_output_digest=EMPTY,
        oracle_record={},
        oracle_record_digest=EMPTY,
        analysis_weight=1.0 if cell.cohort is EvaluationCohort.POPULATION else 0.0,
        loss=0.1,
        selection_confidence=0.9,
        unknown_probability=0.9 if cell.task is EvaluationTask.OOD else None,
        max_known_probability=0.1 if cell.task is EvaluationTask.OOD else None,
        action_ids=("A1", "A2") if cell.task is EvaluationTask.INTERVENTION else (),
        predicted_utilities=(0.0, 1.0)
        if cell.task is EvaluationTask.INTERVENTION
        else (),
        oracle_utilities=(-20.0, 0.0)
        if cell.task is EvaluationTask.INTERVENTION
        else (),
        chosen_action_id="A2" if cell.task is EvaluationTask.INTERVENTION else None,
    )
    values.update(changes)
    return RawEvaluationRecord(**values)


def _raw_pair(cell) -> RawPairRecord:
    probe = PairProbe(
        cell.pair_id,
        "self-reported-side-a",
        "self-reported-side-b",
        (0.0,),
        (1.0,),
        (0.0,),
        (1.0,),
        (1.0, 0.0),
        (0.0, 1.0),
        InformationRelation.DISTINGUISHABLE,
        True,
    )
    return RawPairRecord(
        pair_id=cell.pair_id,
        world_slot=cell.world_slot,
        panel_id=cell.panel_id,
        probe=probe,
        scope_digest=cell.scope_digest,
        split=cell.split,
        family_id=cell.family_id,
        training_replicate_id=cell.training_replicate_id,
        evaluation_replicate_id=cell.evaluation_replicate_id,
        analysis_weight=0.0,
        candidate_record={},
        candidate_record_digest=EMPTY,
        oracle_record={},
        oracle_record_digest=EMPTY,
    )


def _unavailable_authority(tmp_path: Path) -> tuple[FrozenFamilyLineage, FrozenAuthorityRoots]:
    missing = tmp_path / "missing"
    lineage = FrozenFamilyLineage(
        missing / "source.json",
        missing / "manifest.json",
        missing / "seal.json",
        EMPTY,
        EMPTY,
        EMPTY,
    )
    roots = FrozenAuthorityRoots(
        missing / "scope.json", missing / "raw.json", EMPTY, EMPTY
    )
    return lineage, roots


def _v2_digest(label: str, shard: LockedShardCoverageV2 | None = None) -> str:
    identity = None if shard is None else [
        shard.world_slot,
        shard.panel_id,
        shard.split.value,
        shard.training_replicate_id,
        shard.evaluation_replicate_id,
    ]
    return digest_json({"v2-fixture": label, "shard": identity})


def _complete_v2_lock() -> BenchmarkCoverageLockV2:
    query_contract = _v2_digest("query-template-contract")
    denominator_contract = _v2_digest("source-denominator-contract")
    threshold_contract = _v2_digest("pair-threshold-contract")
    shards: list[LockedShardCoverageV2] = []
    for shard in DEFAULT_CODE_LOCK_V2.shards:
        population_slot = cells_module._v2_coverage_slot_digest(
            world_slot=shard.world_slot,
            panel_id=shard.panel_id,
            split=shard.split,
            training_replicate_id=shard.training_replicate_id,
            evaluation_replicate_id=shard.evaluation_replicate_id,
            cohort=EvaluationCohort.POPULATION,
        )
        probe_slot = cells_module._v2_coverage_slot_digest(
            world_slot=shard.world_slot,
            panel_id=shard.panel_id,
            split=shard.split,
            training_replicate_id=shard.training_replicate_id,
            evaluation_replicate_id=shard.evaluation_replicate_id,
            cohort=EvaluationCohort.PROBE,
        )
        population = LockedSourceDenominatorV2(
            coverage_slot_digest=population_slot,
            denominator_contract_digest=denominator_contract,
            source_count=_population_count(
                shard.world_slot, shard.panel_id, shard.split
            ),
            source_record_ids_root=_v2_digest("population-source-ids", shard),
            materialization_receipts_root=_v2_digest(
                "population-materialization-receipts", shard
            ),
        )
        population_queries = LockedQuerySetV2(
            coverage_slot_digest=population_slot,
            template_contract_digest=query_contract,
            query_set_ids=(
                (
                    f"population:{shard.world_slot}:{shard.panel_id}:"
                    f"{shard.split.value}:{shard.training_replicate_id}:"
                    f"{shard.evaluation_replicate_id}"
                ),
            ),
            template_count=1,
            query_templates_root=_v2_digest("population-query-templates", shard),
            source_cut_binding_count=population.source_count,
            source_cut_bindings_root=_v2_digest(
                "population-source-cut-bindings", shard
            ),
        )
        probe = LockedSourceDenominatorV2(
            coverage_slot_digest=probe_slot,
            denominator_contract_digest=denominator_contract,
            source_count=2,
            source_record_ids_root=_v2_digest("probe-source-ids", shard),
            materialization_receipts_root=_v2_digest(
                "probe-materialization-receipts", shard
            ),
        )
        probe_queries = LockedQuerySetV2(
            coverage_slot_digest=probe_slot,
            template_contract_digest=query_contract,
            query_set_ids=(
                (
                    f"probe:{shard.world_slot}:{shard.panel_id}:"
                    f"{shard.split.value}:{shard.training_replicate_id}:"
                    f"{shard.evaluation_replicate_id}"
                ),
            ),
            template_count=1,
            query_templates_root=_v2_digest("probe-query-templates", shard),
            source_cut_binding_count=probe.source_count,
            source_cut_bindings_root=_v2_digest("probe-source-cut-bindings", shard),
        )
        pairs = LockedPairCoverageV2(
            coverage_slot_digest=probe_slot,
            threshold_contract_digest=threshold_contract,
            pair_count=1,
            endpoint_count=2,
            pair_endpoint_bindings_root=_v2_digest("pair-endpoint-bindings", shard),
            pair_threshold_bindings_root=_v2_digest(
                "pair-threshold-bindings", shard
            ),
            threshold_registry_entry_ids=("behavior-pair-default",),
        )
        shards.append(
            replace(
                shard,
                population_denominator=population,
                population_query_set=population_queries,
                probe_denominator=probe,
                probe_query_set=probe_queries,
                pair_coverage=pairs,
            )
        )
    return replace(
        DEFAULT_CODE_LOCK_V2,
        query_template_contract_digest=query_contract,
        source_denominator_contract_digest=denominator_contract,
        pair_threshold_contract_digest=threshold_contract,
        generator_raw_preimage_roots_digest=_v2_digest(
            "generator-raw-preimage-roots"
        ),
        shards=tuple(shards),
    )


def test_builtin_v2_lock_is_closed_canonical_and_stays_pre_freeze() -> None:
    lock = DEFAULT_CODE_LOCK_V2
    assert not lock.ready
    assert not lock.benchmark_freeze_eligible
    assert len(lock.shards) == 20 * 3 * 5 + 3 * 5
    assert {
        item.panel_id for item in lock.shards if item.world_slot == "W15"
    } == {"W15A-randomized-identifiable", "W15B-observational-nonidentified"}

    payload = lock.canonical_bytes
    parsed = BenchmarkCoverageLockV2.from_canonical_bytes(payload)
    assert parsed == lock
    assert parsed.canonical_bytes == payload
    assert parsed.digest == digest_bytes(payload)

    wire = parsed.to_wire()
    assert wire["status"] == "PRE-FREEZE"
    assert wire["freeze_grade_evidence"] is False
    assert wire["benchmark_freeze_eligible"] is False
    for field in (
        "query_template_contract_digest",
        "source_denominator_contract_digest",
        "pair_threshold_contract_digest",
        "generator_raw_preimage_roots_digest",
    ):
        assert wire[field] is None
    dependencies = set(wire["generator_raw_preimage_dependencies"])
    assert dependencies
    assert not dependencies & {
        "expected_cells",
        "expected_cell_receipt_root",
        "coverage_lock_root",
        "freeze_manifest",
        "run_bundle",
    }

    pretty = json.dumps(wire, indent=2, ensure_ascii=False).encode("utf-8")
    with pytest.raises(ProtocolViolation, match="canonical JSON"):
        BenchmarkCoverageLockV2.from_canonical_bytes(pretty)

    extra = dict(wire)
    extra["caller_claimed_ready"] = True
    with pytest.raises(ProtocolViolation, match="closed object"):
        BenchmarkCoverageLockV2.from_canonical_bytes(canonical_json_bytes(extra))

    missing = dict(wire)
    missing.pop("pair_threshold_contract_digest")
    with pytest.raises(ProtocolViolation, match="closed object"):
        BenchmarkCoverageLockV2.from_canonical_bytes(canonical_json_bytes(missing))

    reordered = dict(wire)
    reordered["shards"] = list(reversed(reordered["shards"]))
    with pytest.raises(ProtocolViolation, match="canonical round-trip"):
        BenchmarkCoverageLockV2.from_canonical_bytes(canonical_json_bytes(reordered))


def test_v2_lock_enforces_exact_zipped_315_shard_outer_shape() -> None:
    lock = DEFAULT_CODE_LOCK_V2
    with pytest.raises(ProtocolViolation, match="exactly 315"):
        replace(lock, shards=lock.shards[:-1])

    duplicate = (*lock.shards[:-1], lock.shards[0])
    with pytest.raises(ProtocolViolation, match="identities must be unique"):
        replace(lock, shards=duplicate)

    mismatched = replace(lock.shards[0], evaluation_replicate_id="eval-02")
    with pytest.raises(ProtocolViolation, match="outer shape mismatch"):
        replace(lock, shards=(mismatched, *lock.shards[1:]))

    w15_index = next(
        index
        for index, shard in enumerate(lock.shards)
        if shard.world_slot == "W15"
        and shard.panel_id == "W15A-randomized-identifiable"
    )
    merged_w15 = replace(lock.shards[w15_index], panel_id="primary")
    merged_shards = list(lock.shards)
    merged_shards[w15_index] = merged_w15
    with pytest.raises(ProtocolViolation, match="outer shape mismatch"):
        replace(lock, shards=tuple(merged_shards))

    without_validation = tuple(
        shard for shard in lock.shards if shard.split is not EvaluationSplit.VALIDATION
    )
    with pytest.raises(ProtocolViolation, match="exactly 315"):
        replace(lock, shards=without_validation)

    cross_product = tuple(
        LockedShardCoverageV2(
            world_slot=world,
            panel_id=panel,
            split=split,
            training_replicate_id=f"train-{training:02d}",
            evaluation_replicate_id=f"eval-{evaluation:02d}",
        )
        for world, declaration in WORLD_REGISTRY.items()
        for panel in (item.panel_id for item in declaration.panels)
        for split in (
            EvaluationSplit.TRAIN,
            EvaluationSplit.VALIDATION,
            EvaluationSplit.TEST,
        )
        for training in range(1, 6)
        for evaluation in range(1, 6)
    )
    assert len(cross_product) == 21 * 3 * 25
    with pytest.raises(ProtocolViolation, match="exactly 315"):
        replace(lock, shards=cross_product)


def test_v2_ready_requires_prior_commits_and_all_typed_denominators() -> None:
    complete = _complete_v2_lock()
    assert complete.structurally_complete
    assert not complete.ready
    assert not complete.benchmark_freeze_eligible

    for field in (
        "query_template_contract_digest",
        "source_denominator_contract_digest",
        "pair_threshold_contract_digest",
        "generator_raw_preimage_roots_digest",
    ):
        assert not replace(complete, **{field: None}).structurally_complete

    first = complete.shards[0]
    for field in (
        "population_denominator",
        "population_query_set",
        "probe_denominator",
        "probe_query_set",
        "pair_coverage",
    ):
        incomplete_shard = replace(first, **{field: None})
        assert not replace(
            complete, shards=(incomplete_shard, *complete.shards[1:])
        ).structurally_complete

    wrong_population_count = replace(
        first.population_denominator,
        source_count=first.population_denominator.source_count + 1,
    )
    with pytest.raises(ProtocolViolation, match="population source_count"):
        replace(
            complete,
            shards=(
                replace(first, population_denominator=wrong_population_count),
                *complete.shards[1:],
            ),
        )

    with pytest.raises(ProtocolViolation, match="twice pair_count"):
        replace(first.pair_coverage, endpoint_count=4)
    with pytest.raises(ProtocolViolation, match="non-empty tuple"):
        replace(first.pair_coverage, threshold_registry_entry_ids=())
    with pytest.raises(ProtocolViolation, match="template_count"):
        replace(first.population_query_set, template_count=0)
    with pytest.raises(ProtocolViolation, match="source_count"):
        replace(first.population_denominator, source_count=0)
    with pytest.raises(ProtocolViolation, match="query_set_ids must be unique"):
        replace(
            first.population_query_set,
            query_set_ids=("duplicate", "duplicate"),
        )
    with pytest.raises(ProtocolViolation, match="cover every non-empty query set"):
        replace(
            first.population_query_set,
            query_set_ids=("set-a", "set-b"),
            template_count=1,
        )
    with pytest.raises(ProtocolViolation, match="reference every query set"):
        replace(
            first.population_query_set,
            query_set_ids=("set-a", "set-b"),
            template_count=2,
            source_cut_binding_count=1,
        )
    with pytest.raises(
        ProtocolViolation, match="leave threshold registry entries unused"
    ):
        replace(
            first.pair_coverage,
            threshold_registry_entry_ids=("threshold-a", "threshold-b"),
        )

    multiple_query_sets = replace(
        first.population_query_set,
        query_set_ids=(*first.population_query_set.query_set_ids, "stage-2-role-b"),
        template_count=2,
        query_templates_root=_v2_digest("multiple-query-template-sets", first),
        source_cut_bindings_root=_v2_digest(
            "multiple-query-set-source-cut-bindings", first
        ),
    )
    multi_lock = replace(
        complete,
        shards=(
            replace(first, population_query_set=multiple_query_sets),
            *complete.shards[1:],
        ),
    )
    assert multi_lock.structurally_complete
    assert not multi_lock.ready

    second = complete.shards[1]
    for field, foreign in (
        ("population_denominator", second.population_denominator),
        ("population_query_set", second.population_query_set),
        ("probe_denominator", second.probe_denominator),
        ("probe_query_set", second.probe_query_set),
        ("pair_coverage", second.pair_coverage),
    ):
        with pytest.raises(ProtocolViolation, match="cross-cohort or cross-shard"):
            replace(
                complete,
                shards=(replace(first, **{field: foreign}), *complete.shards[1:]),
            )

    with pytest.raises(ProtocolViolation, match="cross-cohort or cross-shard"):
        replace(
            complete,
            shards=(
                replace(
                    first,
                    population_query_set=first.probe_query_set,
                ),
                *complete.shards[1:],
            ),
        )

    contract_drift_cases = (
        (
            "population_denominator",
            replace(
                first.population_denominator,
                denominator_contract_digest=_v2_digest("foreign-denominator"),
            ),
        ),
        (
            "population_query_set",
            replace(
                first.population_query_set,
                template_contract_digest=_v2_digest("foreign-templates"),
            ),
        ),
        (
            "pair_coverage",
            replace(
                first.pair_coverage,
                threshold_contract_digest=_v2_digest("foreign-thresholds"),
            ),
        ),
    )
    for field, drifted in contract_drift_cases:
        with pytest.raises(ProtocolViolation, match="contradicts its prior contract"):
            replace(
                complete,
                shards=(replace(first, **{field: drifted}), *complete.shards[1:]),
            )

    # Probe rows need not all be pair endpoints (W18 also has singleton OOD
    # probes), so pair coverage is an exact subset of the probe denominator.
    w18_index = next(
        index
        for index, shard in enumerate(complete.shards)
        if shard.world_slot == "W18"
    )
    w18 = complete.shards[w18_index]
    w18_with_singletons = replace(
        w18,
        probe_denominator=replace(w18.probe_denominator, source_count=4),
        probe_query_set=replace(
            w18.probe_query_set,
            source_cut_binding_count=4,
            source_cut_bindings_root=_v2_digest(
                "w18-probe-source-cut-bindings-with-singletons", w18
            ),
        ),
    )
    singleton_shards = list(complete.shards)
    singleton_shards[w18_index] = w18_with_singletons
    singleton_lock = replace(complete, shards=tuple(singleton_shards))
    assert singleton_lock.structurally_complete
    assert not singleton_lock.ready

    too_few_probe_sources = replace(
        first,
        probe_denominator=replace(first.probe_denominator, source_count=1),
    )
    assert not replace(
        complete, shards=(too_few_probe_sources, *complete.shards[1:])
    ).structurally_complete


def test_v2_parser_rejects_caller_self_signing_and_resigning() -> None:
    complete = _complete_v2_lock()
    assert complete.structurally_complete
    assert not complete.ready
    payload = complete.canonical_bytes
    external_resigned_digest = digest_bytes(payload)
    assert external_resigned_digest == complete.digest

    with pytest.raises(ProtocolViolation, match="code-owned v2 coverage lock"):
        BenchmarkCoverageLockV2.from_canonical_bytes(payload)

    forged = DEFAULT_CODE_LOCK_V2.to_wire()
    forged["generator_raw_preimage_dependencies"] = [
        *forged["generator_raw_preimage_dependencies"],
        "expected_cell_receipt_root",
    ]
    with pytest.raises(ProtocolViolation, match="code-owned field"):
        BenchmarkCoverageLockV2.from_canonical_bytes(canonical_json_bytes(forged))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda wire: wire.__setitem__("query_template_contract_digest", 7),
            "query_template_contract_digest",
        ),
        (
            lambda wire: wire.__setitem__("freeze_grade_evidence", 0),
            "code-owned field",
        ),
        (
            lambda wire: wire["shards"][0].__setitem__("split", True),
            "split",
        ),
        (
            lambda wire: wire.__setitem__("shards", {}),
            "shards must be a list",
        ),
    ],
)
def test_v2_parser_rejects_json_type_drift(mutate, message: str) -> None:
    wire = DEFAULT_CODE_LOCK_V2.to_wire()
    mutate(wire)
    with pytest.raises(ProtocolViolation, match=message):
        BenchmarkCoverageLockV2.from_canonical_bytes(canonical_json_bytes(wire))


def test_v2_parser_rejects_nested_count_type_drift_before_pin_check() -> None:
    wire = _complete_v2_lock().to_wire()
    wire["shards"][0]["population_denominator"]["source_count"] = True
    with pytest.raises(ProtocolViolation, match="source_count"):
        BenchmarkCoverageLockV2.from_canonical_bytes(canonical_json_bytes(wire))

    wire = _complete_v2_lock().to_wire()
    wire["shards"][0]["population_query_set"]["template_count"] = 1.0
    with pytest.raises(ProtocolViolation, match="template_count"):
        BenchmarkCoverageLockV2.from_canonical_bytes(canonical_json_bytes(wire))


def test_builtin_v1_lock_is_unready_and_single_w01_cannot_claim_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cells_module, "BENCHMARK_V1_COVERAGE_LOCK", DEFAULT_CODE_LOCK)
    assert not DEFAULT_CODE_LOCK.ready
    assert len(DEFAULT_CODE_LOCK.shards) == 21 * 3 * 5
    assert {
        item.panel_id for item in DEFAULT_CODE_LOCK.shards if item.world_slot == "W15"
    } == {"W15A-randomized-identifiable", "W15B-observational-nonidentified"}

    shard, rows = _write_shard(
        tmp_path,
        "only-w01",
        "W01",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS,),
    )
    lineage, roots = _unavailable_authority(tmp_path)
    query = _queries(shard, rows, EvaluationTask.DIAGNOSIS)[0]
    contract = ExpectedCellsScopeContract(
        benchmark_id="UCM-BENCHMARK-v1",
        benchmark_revision="FROZEN-v1",
        scope_digest=SCOPE,
        registry_digest=registry_digest(),
        coverage_lock_digest=DEFAULT_CODE_LOCK.digest,
        family_lineage=lineage,
        authority_roots=roots,
        shards=(shard,),
        queries=(query,),
        pairs=(),
    )
    result = build_expected_cells(contract)
    assert result.status is CellMaterializationStatus.INCOMPLETE
    assert result.manifest is None
    assert any("lock is not frozen" in item.detail for item in result.blockers)
    assert any("required locked shard is missing" in item.detail for item in result.blockers)


def test_random_per_row_family_and_self_consistent_receipt_cannot_replace_frozen_source(
    tmp_path: Path,
) -> None:
    shard, rows = _write_shard(
        tmp_path,
        "w01-family-forgery",
        "W01",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS,),
    )
    queries = _queries(shard, rows, EvaluationTask.DIAGNOSIS)
    authority = _freeze_fixture_authority(tmp_path, (shard,), queries)
    frozen_shard = authority.shards[0]

    forged_rows = [
        json.loads(line)
        for line in frozen_shard.judge_path.read_text("utf-8").splitlines()
    ]
    for index, row in enumerate(forged_rows):
        row["family_digest"] = digest_json({"random-per-row": index})
    judge_payload = b"".join(canonical_json_bytes(row) for row in forged_rows)
    frozen_shard.judge_path.write_bytes(judge_payload)
    judge_digest = digest_bytes(judge_payload)
    status = json.loads(frozen_shard.status_path.read_text("utf-8"))
    status["judge_digest"] = judge_digest
    # The malicious producer self-signs a perfectly consistent-looking local
    # assignment receipt.  It still cannot alter the earlier code-locked source.
    status["family_assignment_basis"] = "pre_split_counterfactual_family"
    status["family_assignment_digest"] = digest_json(
        {
            "assignments": [
                {"record_id": row["record_id"], "family_digest": row["family_digest"]}
                for row in forged_rows
            ]
        }
    )
    status["family_count"] = len(forged_rows)
    status_payload = canonical_json_bytes(status)
    frozen_shard.status_path.write_bytes(status_payload)
    forged_shard = replace(
        frozen_shard,
        judge_digest=judge_digest,
        status_digest=digest_bytes(status_payload),
    )
    forged_authority = replace(authority, shards=(forged_shard,))
    result = build_expected_cells(_contract(forged_authority, queries))
    assert result.status is CellMaterializationStatus.INCOMPLETE
    assert any("contradicts frozen lineage" in item.detail for item in result.blockers)


def test_two_members_of_frozen_source_family_share_cluster_but_stay_pre_freeze(
    tmp_path: Path,
) -> None:
    shared = _placeholder_family("two-members")
    shard, rows = _write_shard(
        tmp_path,
        "w06-shared-family",
        "W06",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS,),
        family_placeholders={0: shared, 1: shared},
    )
    queries = _queries(shard, rows, EvaluationTask.DIAGNOSIS)
    authority = _freeze_fixture_authority(tmp_path, (shard,), queries)
    result = build_expected_cells(_contract(authority, queries))
    assert result.status is CellMaterializationStatus.PRE_FREEZE_SCAFFOLD
    assert result.manifest is not None
    family_counts: dict[str, int] = {}
    for cell in result.manifest.expected_cells:
        family_counts[cell.family_id] = family_counts.get(cell.family_id, 0) + 1
    assert max(family_counts.values()) == 2
    assert len(family_counts) == 1023
    assert result.to_wire()["status"] == "pre_freeze_scaffold"
    assert not result.benchmark_freeze_eligible


def test_frozen_family_cannot_cross_validation_and_test(tmp_path: Path) -> None:
    shared = _placeholder_family("cross-split-leak")
    validation, validation_rows = _write_shard(
        tmp_path,
        "w08-validation",
        "W08",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS,),
        family_placeholders={0: shared},
    )
    sealed_test, test_rows = _write_shard(
        tmp_path,
        "w08-test",
        "W08",
        "primary",
        EvaluationSplit.TEST,
        (EvaluationTask.DIAGNOSIS,),
        family_placeholders={0: shared},
    )
    queries = _queries(validation, validation_rows, EvaluationTask.DIAGNOSIS) + _queries(
        sealed_test, test_rows, EvaluationTask.DIAGNOSIS
    )
    authority = _freeze_fixture_authority(
        tmp_path, (validation, sealed_test), queries
    )
    result = build_expected_cells(_contract(authority, queries))
    assert result.status is CellMaterializationStatus.INCOMPLETE
    assert any("appears in multiple splits" in item.detail for item in result.blockers)


def test_probe_source_split_mismatch_is_a_typed_blocker(tmp_path: Path) -> None:
    probe_family = _placeholder_family("w09-wrong-split-probe")
    probe_rows = (
        _judge_row(
            "w09-probe-from-train",
            world="W09",
            panel="primary",
            split=EvaluationSplit.TEST,
            cohort="probe",
            family_placeholder=probe_family,
            strata=("behavior_pair",),
            pair_id="w09-wrong-split-pair",
            pair_side=0,
            source_episode_split="train",
        ),
        _judge_row(
            "w09-probe-test-side",
            world="W09",
            panel="primary",
            split=EvaluationSplit.TEST,
            cohort="probe",
            family_placeholder=probe_family,
            strata=("behavior_pair",),
            pair_id="w09-wrong-split-pair",
            pair_side=1,
        ),
    )
    shard, rows = _write_shard(
        tmp_path,
        "w09-probe-provenance",
        "W09",
        "primary",
        EvaluationSplit.TEST,
        (EvaluationTask.DIAGNOSIS,),
        probe_rows=probe_rows,
    )
    queries = _queries(shard, rows, EvaluationTask.DIAGNOSIS)
    authority = _freeze_fixture_authority(tmp_path, (shard,), queries)
    pair = PairCellContract(shard.shard_id, "w09-wrong-split-pair", THRESHOLDS)
    result = build_expected_cells(_contract(authority, queries, (pair,)))
    assert result.status is CellMaterializationStatus.INCOMPLETE
    assert any("source episode split provenance" in item.detail for item in result.blockers)


def test_exact_public_prefix_duplicate_across_splits_is_a_blocker(tmp_path: Path) -> None:
    duplicate_prefix = "w09-train-index-2-reused-by-test-probe"
    validation, validation_rows = _write_shard(
        tmp_path,
        "w09-validation-prefix",
        "W09",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS,),
        public_history_aliases={0: duplicate_prefix},
    )
    sealed_test, test_rows = _write_shard(
        tmp_path,
        "w09-test-prefix",
        "W09",
        "primary",
        EvaluationSplit.TEST,
        (EvaluationTask.DIAGNOSIS,),
        public_history_aliases={0: duplicate_prefix},
    )
    queries = _queries(validation, validation_rows, EvaluationTask.DIAGNOSIS) + _queries(
        sealed_test, test_rows, EvaluationTask.DIAGNOSIS
    )
    authority = _freeze_fixture_authority(
        tmp_path, (validation, sealed_test), queries
    )
    result = build_expected_cells(_contract(authority, queries))
    assert result.status is CellMaterializationStatus.INCOMPLETE
    assert any("exact public-history prefix" in item.detail for item in result.blockers)


def test_locked_query_scope_rejects_missing_cell_even_when_caller_declares_subset(
    tmp_path: Path,
) -> None:
    shard, rows = _write_shard(
        tmp_path,
        "w02-query-subset",
        "W02",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS, EvaluationTask.NATURAL_FORECAST),
    )
    diagnosis = _queries(shard, rows, EvaluationTask.DIAGNOSIS)
    forecast = _queries(shard, rows, EvaluationTask.NATURAL_FORECAST)
    full_queries = diagnosis + forecast
    locked_templates = {
        shard.shard_id: (_query_template(diagnosis[0]), _query_template(forecast[0]))
    }
    authority = _freeze_fixture_authority(
        tmp_path,
        (shard,),
        full_queries,
        locked_templates=locked_templates,
    )
    result = build_expected_cells(_contract(authority, diagnosis + forecast[:-1]))
    assert result.status is CellMaterializationStatus.INCOMPLETE
    assert any(
        "query identities contradict locked scope" in item.detail
        for item in result.blockers
    )


def test_w15_panels_remain_distinct_but_scaffold_is_never_written_as_freeze(
    tmp_path: Path,
) -> None:
    shard_a, rows_a = _write_shard(
        tmp_path,
        "w15a",
        "W15",
        "W15A-randomized-identifiable",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS,),
    )
    shard_b, rows_b = _write_shard(
        tmp_path,
        "w15b",
        "W15",
        "W15B-observational-nonidentified",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS,),
    )
    queries = _queries(shard_a, rows_a, EvaluationTask.DIAGNOSIS) + _queries(
        shard_b, rows_b, EvaluationTask.DIAGNOSIS
    )
    authority = _freeze_fixture_authority(tmp_path, (shard_a, shard_b), queries)
    contract = _contract(authority, queries)
    result = build_expected_cells(contract)
    assert result.status is CellMaterializationStatus.PRE_FREEZE_SCAFFOLD
    assert result.manifest is not None
    assert {cell.panel_id for cell in result.manifest.expected_cells} == {
        "W15A-randomized-identifiable",
        "W15B-observational-nonidentified",
    }
    assert {cell.identification.value for cell in result.manifest.expected_cells} == {
        "point",
        "none",
    }
    output = tmp_path / "expected-cells.json"
    materialized = materialize_expected_cells(contract, output)
    assert materialized.status is CellMaterializationStatus.PRE_FREEZE_SCAFFOLD
    assert not output.exists()


def test_empty_self_hash_raw_rows_never_become_benchmark_complete(tmp_path: Path) -> None:
    shard, rows = _write_shard(
        tmp_path,
        "w03-empty-self-hash",
        "W03",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS,),
    )
    queries = _queries(shard, rows, EvaluationTask.DIAGNOSIS)
    authority = _freeze_fixture_authority(tmp_path, (shard,), queries)
    built = build_expected_cells(_contract(authority, queries))
    assert built.manifest is not None
    # Every evidence object and digest below is candidate/judge self-consistent
    # but unbound to an authoritative per-cell raw root.
    raw = tuple(_raw(cell) for cell in built.manifest.expected_cells)
    audit = audit_raw_exact_join(built.manifest, raw, ())
    assert audit.status is CellMaterializationStatus.PRE_FREEZE_SCAFFOLD
    assert not audit.benchmark_freeze_eligible
    report = evaluate_records(raw, (), built.manifest)
    assert report.evidence_status.value == "incomplete"
    assert not report.benchmark_freeze_eligible
    assert report.benchmark_evidence_status.value == "incomplete"
    assert any("PRE_FREEZE_SCAFFOLD" in item.detail for item in report.blockers)


def test_pair_without_frozen_endpoint_ids_and_side_roots_is_incomplete(
    tmp_path: Path,
) -> None:
    pair_placeholder = _placeholder_family("w04-probe-pair")
    probe_rows = (
        _judge_row(
            "w04-probe-a",
            world="W04",
            panel="primary",
            split=EvaluationSplit.TEST,
            cohort="probe",
            family_placeholder=pair_placeholder,
            strata=("behavior_pair",),
            pair_id="source-pair",
            pair_side=0,
        ),
        _judge_row(
            "w04-probe-b",
            world="W04",
            panel="primary",
            split=EvaluationSplit.TEST,
            cohort="probe",
            family_placeholder=pair_placeholder,
            strata=("behavior_pair",),
            pair_id="source-pair",
            pair_side=1,
        ),
    )
    shard, rows = _write_shard(
        tmp_path,
        "w04-pair",
        "W04",
        "primary",
        EvaluationSplit.TEST,
        (EvaluationTask.DIAGNOSIS,),
        probe_rows=probe_rows,
    )
    queries = _queries(shard, rows, EvaluationTask.DIAGNOSIS)
    authority = _freeze_fixture_authority(tmp_path, (shard,), queries)
    pair_contract = PairCellContract(shard.shard_id, "source-pair", THRESHOLDS)
    built = build_expected_cells(_contract(authority, queries, (pair_contract,)))
    assert built.manifest is not None
    raw = tuple(_raw(cell) for cell in built.manifest.expected_cells)
    raw_pair = _raw_pair(built.manifest.expected_pairs[0])
    audit = audit_raw_exact_join(built.manifest, raw, (raw_pair,))
    assert audit.status is CellMaterializationStatus.INCOMPLETE
    assert any("does not yet bind frozen endpoint" in item.detail for item in audit.blockers)


def test_w19_tail_and_ood_denominators_survive_missing_raw_rows(tmp_path: Path) -> None:
    w18, rows18 = _write_shard(
        tmp_path,
        "w18",
        "W18",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.OOD,),
    )
    ood_queries = tuple(
        QueryCellContract(
            w18.shard_id,
            row["record_id"],
            "cut-0",
            EvaluationTask.OOD,
            0,
            "policy:none",
            OODAttribution.ATTRIBUTABLE if index == 0 else OODAttribution.KNOWN,
            ("A1",) if index == 0 else (),
        )
        for index, row in enumerate(rows18)
    )
    tail_strata = {index: ("iid_support", "boundary_tail") for index in range(16)}
    w19, rows19 = _write_shard(
        tmp_path,
        "w19",
        "W19",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.INTERVENTION,),
        strata=tail_strata,
    )
    intervention_queries = _queries(w19, rows19, EvaluationTask.INTERVENTION)
    queries = ood_queries + intervention_queries
    authority = _freeze_fixture_authority(tmp_path, (w18, w19), queries)
    built = build_expected_cells(
        _contract(authority, queries, w19=W19SafetyContract("A1", 10.0))
    )
    assert built.status is CellMaterializationStatus.PRE_FREEZE_SCAFFOLD
    assert built.manifest is not None and built.manifest.w19_safety is not None
    assert len(built.manifest.w19_safety.tail_episode_aliases) == 16
    all_raw = tuple(_raw(cell) for cell in built.manifest.expected_cells)
    tail_ids = {cell.record_id for cell in built.manifest.expected_cells if cell.tail_member}
    omitted = tuple(row for row in all_raw if row.record_id not in tail_ids)
    audit = audit_raw_exact_join(built.manifest, omitted, ())
    assert audit.status is CellMaterializationStatus.INCOMPLETE
    report = evaluate_records(omitted, (), built.manifest)
    assert report.w19 is not None and report.w19.expected_tail_episodes == 16
    assert report.ood is not None and report.ood.primary_denominator == 1024


def test_duplicate_query_and_pair_contract_rows_fail_closed(tmp_path: Path) -> None:
    shard, rows = _write_shard(
        tmp_path,
        "w05-duplicates",
        "W05",
        "primary",
        EvaluationSplit.VALIDATION,
        (EvaluationTask.DIAGNOSIS,),
    )
    queries = _queries(shard, rows, EvaluationTask.DIAGNOSIS)
    authority = _freeze_fixture_authority(tmp_path, (shard,), queries)
    base = _contract(authority, queries)
    with pytest.raises(Exception, match="exactly unique"):
        replace(base, queries=queries + (queries[0],))
    pair = PairCellContract(shard.shard_id, "pair-x", THRESHOLDS)
    with pytest.raises(Exception, match="exactly unique"):
        replace(base, pairs=(pair, pair))


def test_ordinary_materializer_without_authoritative_roots_remains_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cells_module, "BENCHMARK_V1_COVERAGE_LOCK", DEFAULT_CODE_LOCK)
    materialized = materialize_world_split(
        "W01",
        "primary",
        WorldSplit.VALIDATION,
        101,
        tmp_path / "ordinary",
        alias_secret=b"o" * 32,
        episode_limit=1,
    )
    status_path = materialized.candidate_path.parent / "materialization-status.json"
    shard = FrozenCorpusShard(
        "ordinary",
        "W01",
        "primary",
        EvaluationSplit.VALIDATION,
        "train-01",
        "eval-01",
        (EvaluationTask.DIAGNOSIS,),
        materialized.candidate_path,
        materialized.judge_path,
        status_path,
        materialized.candidate_digest,
        materialized.judge_digest,
        digest_bytes(status_path.read_bytes()),
    )
    source_row = json.loads(materialized.judge_path.read_text("utf-8").splitlines()[0])
    lineage, roots = _unavailable_authority(tmp_path)
    query = QueryCellContract(
        shard.shard_id,
        source_row["record_id"],
        "cut-0",
        EvaluationTask.DIAGNOSIS,
        0,
        "policy:none",
    )
    contract = ExpectedCellsScopeContract(
        "UCM-BENCHMARK-v1",
        "FROZEN-v1",
        SCOPE,
        registry_digest(),
        DEFAULT_CODE_LOCK.digest,
        lineage,
        roots,
        (shard,),
        (query,),
        (),
    )
    result = build_expected_cells(contract)
    assert result.status is CellMaterializationStatus.INCOMPLETE
    assert result.manifest is None
    assert any("artifact is unavailable" in item.detail for item in result.blockers)
