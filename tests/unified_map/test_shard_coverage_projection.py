from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import tests.unified_map.test_corpus_authority as corpus_fixtures
import prototype.unified_map.shard_coverage_projection as projection_module
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
)
from prototype.unified_map.corpus_authority import (
    audit_authority_bound_corpus,
    build_unified_corpus_authority_artifact,
    parse_authority_bound_corpus_scope_contract_bytes,
    parse_unified_corpus_authority_artifact_bytes,
)
from prototype.unified_map.evaluator import EvaluationCohort
from prototype.unified_map.family_manifest import (
    FamilyMaterializationAuthorityArtifactSet,
    MaterializationRole,
)
from prototype.unified_map.shard_coverage_projection import (
    INCOMPLETE_HARNESS_CODE,
    PROJECTION_PROTOCOL,
    derive_shard_coverage_projection,
    parse_shard_coverage_projection_bytes,
    verify_shard_coverage_projection_bytes,
)
from prototype.unified_map.world_registry import registry_digest


def _exact_fixture(
    tmp_path: Path,
    world: str,
    *,
    registry_digest_value: str | None = None,
):
    effective_registry_digest = registry_digest_value or registry_digest()
    original_digest = corpus_fixtures._digest
    original_panel = corpus_fixtures.PANEL
    original_projection_registry_digest = projection_module.registry_digest
    corpus_fixtures.PANEL = "primary"
    corpus_fixtures._digest = (
        lambda label: effective_registry_digest
        if label == "registry"
        else original_digest(label)
    )
    projection_module.registry_digest = lambda: effective_registry_digest
    try:
        scope = corpus_fixtures._build_scope(tmp_path, world)
        audit = audit_authority_bound_corpus(scope)
        assert audit.structural_join_complete
        family = FamilyMaterializationAuthorityArtifactSet.from_preimages(
            canonical_json_bytes(scope.family_source.to_wire()),
            canonical_json_bytes(scope.family_assignment.to_wire()),
            canonical_json_bytes(scope.family_ledger.to_wire()),
        )
        contract = parse_authority_bound_corpus_scope_contract_bytes(
            canonical_json_bytes(scope.to_wire())
        )
        unified = build_unified_corpus_authority_artifact(
            family_artifact_set_preimage=family.canonical_bytes,
            scope_contract_preimage=contract.canonical_bytes,
            audit_preimage=audit.canonical_bytes,
        )
        candidate_bytes = scope.candidate_path.read_bytes()
        judge_bytes = scope.judge_path.read_bytes()
        projection = derive_shard_coverage_projection(
            unified.canonical_bytes, candidate_bytes, judge_bytes
        )
        return projection, unified.canonical_bytes, candidate_bytes, judge_bytes
    finally:
        corpus_fixtures.PANEL = original_panel
        corpus_fixtures._digest = original_digest
        projection_module.registry_digest = original_projection_registry_digest


@pytest.fixture(scope="module")
def population_projection(tmp_path_factory: pytest.TempPathFactory):
    return _exact_fixture(tmp_path_factory.mktemp("shard-population"), "W01")


@pytest.fixture(scope="module")
def pair_projection(tmp_path_factory: pytest.TempPathFactory):
    return _exact_fixture(tmp_path_factory.mktemp("shard-pair"), "W03")


def test_population_projection_is_exact_but_registry_incomplete(
    population_projection,
) -> None:
    projection, unified_bytes, candidate_bytes, judge_bytes = population_projection

    assert projection.identity.world_slot == "W01"
    assert projection.identity.panel_id == "primary"
    assert projection.identity.to_wire()["family_split"] == "sealed_test"
    assert projection.population.record_count == 1
    assert projection.population.expected_source_count == 2048
    assert projection.population.registry_count_matches is False
    assert projection.probe.record_count == 0
    assert projection.structurally_complete is False
    assert projection.benchmark_freeze_eligible is False
    assert any(
        item.code == INCOMPLETE_HARNESS_CODE
        and item.artifact == "population_denominator"
        for item in projection.blockers
    )
    assert projection.to_wire()["schema_version"] == PROJECTION_PROTOCOL
    assert projection.to_wire()["status"] == "PRE-FREEZE"
    assert projection.to_wire()["authority_role"] == "judge_only"

    verified = verify_shard_coverage_projection_bytes(
        projection.canonical_bytes,
        unified_artifact_bytes=unified_bytes,
        candidate_corpus_bytes=candidate_bytes,
        judge_corpus_bytes=judge_bytes,
    )
    assert verified.artifact_digest == projection.artifact_digest


def test_pair_projection_is_role_derived_and_alias_free(pair_projection) -> None:
    projection, _, _, _ = pair_projection

    assert projection.population.record_count == 0
    assert projection.probe.record_count == 2
    assert len(projection.pairs) == 1
    pair = projection.pairs[0]
    assert tuple(item.pair_side for item in pair.endpoints) == (0, 1)
    assert all(item.cohort is EvaluationCohort.PROBE for item in pair.endpoints)
    assert all(
        item.materialization_role is MaterializationRole.PAIR_SIDE
        for item in pair.endpoints
    )
    assert pair.pair_semantic is pair.endpoints[0].pair_semantic
    assert projection.to_wire()["pairs"]["endpoint_count"] == 2
    assert b"pair-live-0" not in projection.canonical_bytes
    assert b'"pair_id"' not in projection.canonical_bytes


@pytest.mark.parametrize(
    ("role", "cohort"),
    (
        (MaterializationRole.STANDARD_ROW, EvaluationCohort.POPULATION),
        (MaterializationRole.RELEASE_STAGE_ROW, EvaluationCohort.POPULATION),
        (MaterializationRole.W19_ASSIGNMENT_ROW, EvaluationCohort.POPULATION),
        (MaterializationRole.PROBE_ROW, EvaluationCohort.PROBE),
    ),
)
def test_all_nonpair_roles_have_closed_code_owned_cohorts(
    population_projection,
    role: MaterializationRole,
    cohort: EvaluationCohort,
) -> None:
    base = population_projection[0].records[0]
    projected = replace(
        base,
        cohort=cohort,
        materialization_role=role,
        pair_digest=None,
        pair_semantic=None,
        pair_side=None,
    )
    assert projected.cohort is cohort
    with pytest.raises(ProtocolViolation, match="role mapping"):
        replace(
            projected,
            cohort=(
                EvaluationCohort.PROBE
                if cohort is EvaluationCohort.POPULATION
                else EvaluationCohort.POPULATION
            ),
        )


def test_projection_parser_is_canonical_but_not_parent_authority(
    population_projection,
) -> None:
    projection, unified_bytes, candidate_bytes, judge_bytes = population_projection
    parsed = parse_shard_coverage_projection_bytes(projection.canonical_bytes)
    assert parsed.canonical_bytes == projection.canonical_bytes

    with pytest.raises(ProtocolViolation):
        parse_shard_coverage_projection_bytes(
            json.dumps(projection.to_wire(), ensure_ascii=False, indent=2).encode()
        )
    with pytest.raises(ProtocolViolation):
        parse_shard_coverage_projection_bytes(
            projection.canonical_bytes.replace(b"\n", b"\r\n")
        )
    duplicated = projection.canonical_bytes.replace(
        b'{"authority_role":"judge_only",',
        b'{"authority_role":"judge_only","authority_role":"judge_only",',
        1,
    )
    with pytest.raises(ProtocolViolation, match="duplicate"):
        parse_shard_coverage_projection_bytes(duplicated)


def test_parser_accepts_historical_self_consistency_but_live_verify_rejects_drift(
    tmp_path: Path,
    population_projection,
) -> None:
    historical_registry = "sha256:" + "0" * 64
    if historical_registry == registry_digest():
        historical_registry = "sha256:" + "1" * 64
    projection, unified_bytes, candidate_bytes, judge_bytes = _exact_fixture(
        tmp_path,
        "W01",
        registry_digest_value=historical_registry,
    )

    parsed = parse_shard_coverage_projection_bytes(projection.canonical_bytes)
    assert parsed.identity.registry_digest == historical_registry
    assert (
        parsed.population.coverage_slot_digest
        != population_projection[0].population.coverage_slot_digest
    )
    assert parsed.pair_topology_root != population_projection[0].pair_topology_root
    assert (
        parsed.pair_endpoint_bindings_root
        != population_projection[0].pair_endpoint_bindings_root
    )
    with pytest.raises(ProtocolViolation, match="registry digest is stale"):
        verify_shard_coverage_projection_bytes(
            projection.canonical_bytes,
            unified_artifact_bytes=unified_bytes,
            candidate_corpus_bytes=candidate_bytes,
            judge_corpus_bytes=judge_bytes,
        )


def test_projection_rejects_bool_pair_side_even_when_equal_to_one(
    pair_projection,
) -> None:
    projection = pair_projection[0]
    wire = projection.to_wire()
    wire["records"][1]["pair_side"] = True
    with pytest.raises(ProtocolViolation, match="exact integer"):
        parse_shard_coverage_projection_bytes(canonical_json_bytes(wire))


def test_exact_parent_verifier_rejects_drop_swap_and_whole_reissue(
    population_projection,
    pair_projection,
) -> None:
    projection, unified_bytes, candidate_bytes, judge_bytes = population_projection
    # A path-independent, byte-identical rebuild is the same preimage and is
    # admissible.  A coherent-looking replacement with even one changed parent
    # byte is not.
    verify_shard_coverage_projection_bytes(
        projection.canonical_bytes,
        unified_artifact_bytes=unified_bytes,
        candidate_corpus_bytes=candidate_bytes,
        judge_corpus_bytes=judge_bytes,
    )
    foreign_projection, foreign_unified, foreign_candidate, foreign_judge = (
        pair_projection
    )
    with pytest.raises(ProtocolViolation):
        verify_shard_coverage_projection_bytes(
            projection.canonical_bytes,
            unified_artifact_bytes=foreign_unified,
            candidate_corpus_bytes=foreign_candidate,
            judge_corpus_bytes=foreign_judge,
        )
    verify_shard_coverage_projection_bytes(
        foreign_projection.canonical_bytes,
        unified_artifact_bytes=foreign_unified,
        candidate_corpus_bytes=foreign_candidate,
        judge_corpus_bytes=foreign_judge,
    )
    with pytest.raises(ProtocolViolation):
        derive_shard_coverage_projection(
            unified_bytes,
            b"",
            judge_bytes,
        )
    with pytest.raises(ProtocolViolation):
        derive_shard_coverage_projection(
            unified_bytes,
            judge_bytes,
            candidate_bytes,
        )


def test_candidate_and_judge_byte_mutations_are_not_re_signable(
    population_projection,
) -> None:
    _, unified_bytes, candidate_bytes, judge_bytes = population_projection
    candidate_wire = json.loads(candidate_bytes)
    candidate_wire["record_id"] = "replacement-record"
    with pytest.raises(ProtocolViolation, match="candidate corpus bytes"):
        derive_shard_coverage_projection(
            unified_bytes,
            canonical_json_bytes(candidate_wire),
            judge_bytes,
        )
    judge_wire = json.loads(judge_bytes)
    judge_wire["population_denominator"] = 1
    with pytest.raises(ProtocolViolation, match="judge corpus bytes"):
        derive_shard_coverage_projection(
            unified_bytes,
            candidate_bytes,
            canonical_json_bytes(judge_wire),
        )


def test_pair_projection_rejects_missing_edge_and_reused_endpoint(pair_projection) -> None:
    projection = pair_projection[0]
    pair = projection.pairs[0]
    with pytest.raises(ProtocolViolation, match="two typed endpoints"):
        replace(pair, endpoints=(pair.endpoints[0],))
    with pytest.raises(ProtocolViolation, match="ordered sides"):
        replace(pair, endpoints=(pair.endpoints[0], pair.endpoints[0]))


def test_projection_rejects_reused_receipt_body_identity(pair_projection) -> None:
    projection = pair_projection[0]
    wire = projection.to_wire()
    wire["records"][1]["receipt_authority_body_digest"] = wire["records"][0][
        "receipt_authority_body_digest"
    ]
    with pytest.raises(ProtocolViolation, match="reuse receipt_authority_body_digest"):
        parse_shard_coverage_projection_bytes(canonical_json_bytes(wire))


@pytest.mark.parametrize(
    "payload",
    (
        bytearray(canonical_json_bytes({"record_id": "r", "value": 1})),
        b"\xef\xbb\xbf" + canonical_json_bytes({"record_id": "r", "value": 1}),
        canonical_json_bytes({"record_id": "r", "value": 1}).replace(
            b"\n", b"\r\n"
        ),
        canonical_json_bytes({"record_id": "r", "value": 1})[:-1],
        canonical_json_bytes({"record_id": "r", "value": 1}) + b"\n",
        b'{"nested":{"x":1,"x":1},"record_id":"r"}\n',
        canonical_json_bytes({"record_id": "r", "value": 1}) * 2,
        canonical_json_bytes({"record_id": "r", "value": 1})[:-1] + b" \n",
        b'{"record_id":"r","value":"\xff"}\n',
    ),
)
def test_canonical_jsonl_parser_attack_matrix_fails_closed(payload: object) -> None:
    with pytest.raises(ProtocolViolation):
        projection_module._parse_canonical_jsonl(payload, label="attack corpus")


def test_post_construction_mutation_and_seal_rewrite_fail_closed(
    population_projection,
) -> None:
    projection = parse_shard_coverage_projection_bytes(
        population_projection[0].canonical_bytes
    )
    original = projection.parents.unified_artifact_digest
    replacement = "sha256:" + ("0" if original[7] != "0" else "1") + original[8:]
    object.__setattr__(
        projection.parents,
        "unified_artifact_digest",
        replacement,
    )
    object.__setattr__(projection, "_sealed_body_digest", digest_bytes(b"forged"))
    with pytest.raises(ProtocolViolation, match="changed after construction"):
        _ = projection.canonical_bytes


def test_projection_parent_wire_distinguishes_body_and_full_byte_digests(
    population_projection,
) -> None:
    projection, unified_bytes, _, _ = population_projection
    parents = projection.parents
    unified = parse_unified_corpus_authority_artifact_bytes(unified_bytes)
    assert parents.unified_artifact_digest != parents.unified_authority_body_digest
    assert parents.family_artifact_digest != parents.family_authority_body_digest
    assert parents.scope_artifact_digest == digest_bytes(unified.scope_contract_preimage)
    assert parents.audit_artifact_digest != parents.audit_authority_body_digest
