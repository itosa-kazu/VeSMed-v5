from __future__ import annotations

import json

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.panel_split_authority import (
    ASSIGNMENT_AUTHORITY_COUNT,
    EXPECTED_PANEL_TASK_KEYS,
    PARTITION_AUTHORITY_COUNT,
    AuthoritySplit,
    FamilyDefinitionIntent,
    FamilyIntentPolicy,
    FamilyUnitSplitAssignment,
    GeneratorIntent,
    GlobalPanelTaskPartitionAuthoritySet,
    LegacyGlobalStrataRootBytePreimageSet,
    PanelTaskFamilyAssignmentAuthority,
    PanelTaskIdentity,
    PanelPhysicalIdentity,
    SplitPolicyContext,
    SplitSeedCommitmentContext,
    SplitNeutralFamilyIntent,
    SplitNeutralFamilyUnitIntent,
    ZippedSeedPairingProtocolContext,
    build_global_panel_task_family_authority_set,
    parse_global_panel_task_family_authority_set_bytes,
    parse_global_panel_task_partition_authority_set_bytes,
    parse_panel_task_family_assignment_authority_bytes,
    parse_panel_task_split_partition_authority_bytes,
    parse_legacy_global_strata_root_byte_preimage_set_bytes,
)
from prototype.unified_map.seed_protocol import ZIPPED_REPLICATE_IDS
from prototype.unified_map.strata_manifest import StrataReceiptBatch
from tests.unified_map.test_strata_manifest import (
    _all_receipts as _legacy_all_receipts,
)
from tests.unified_map.test_strata_manifest import _authority as _legacy_authority


def _d(label: str) -> str:
    return digest_json({"fixture": label})


def _assignment(
    world_slot: str,
    panel_id: str,
    task: object,
    *,
    scope_digest: str,
    variant: str = "",
    split_rotation: int = 0,
) -> PanelTaskFamilyAssignmentAuthority:
    identity = PanelTaskIdentity(
        "UCM-BENCHMARK-v1",
        "PRE-FREEZE",
        scope_digest,
        world_slot,
        panel_id,
        task,
    )
    units = tuple(
        sorted(
            (
                SplitNeutralFamilyUnitIntent(
                    f"{world_slot}-{panel_id}-family-{index}{variant}",
                    FamilyDefinitionIntent(
                        f"{world_slot}-{panel_id}-definition-{index}{variant}",
                        (f"member-{index}",),
                    ),
                    GeneratorIntent(
                        f"{world_slot}-{panel_id}-generator",
                        "v1",
                        "ucm-world-generator-v1",
                        f"population-{index}",
                    ),
                    f"atomic-{index}",
                    index,
                )
                for index in range(1, 4)
            ),
            key=lambda item: item.unit_intent_digest,
        )
    )
    intent = SplitNeutralFamilyIntent(
        identity, FamilyIntentPolicy("family-intent-policy", "v1"), units
    )
    split_policy = SplitPolicyContext("weighted-atomic-split", "v1")
    split_values = tuple(AuthoritySplit)
    split_by_group = {
        f"atomic-{index}": split_values[(index - 1 + split_rotation) % 3]
        for index in range(1, 4)
    }
    return PanelTaskFamilyAssignmentAuthority(
        intent,
        split_policy,
        SplitSeedCommitmentContext(
            PanelPhysicalIdentity.from_task_identity(identity), split_policy
        ),
        _d("split-seed-commitment"),
        tuple(
            FamilyUnitSplitAssignment(
                unit.unit_intent_digest, split_by_group[unit.atomic_group_id]
            )
            for unit in units
        ),
    )


@pytest.fixture(scope="module")
def authority_sets():
    scope_digest = _d("formal-scope")
    assignments = tuple(
        _assignment(world_slot, panel_id, task, scope_digest=scope_digest)
        for world_slot, panel_id, task in EXPECTED_PANEL_TASK_KEYS
    )
    assignment_set = build_global_panel_task_family_authority_set(assignments)
    pairing = ZippedSeedPairingProtocolContext()
    partition_set = GlobalPanelTaskPartitionAuthoritySet.build(assignment_set, pairing)
    return assignment_set, partition_set


def test_global_authority_and_partition_counts_are_exact(authority_sets) -> None:
    assignment_set, partition_set = authority_sets

    assert len(assignment_set.authorities) == ASSIGNMENT_AUTHORITY_COUNT == 105
    assert len(partition_set.partitions) == PARTITION_AUTHORITY_COUNT == 315
    assert (
        len({item.physical_assignment_digest for item in assignment_set.authorities})
        == 21
    )
    assert (
        len(
            {
                shard.shard_slot_digest
                for partition in partition_set.partitions
                for shard in partition.zipped_shard_slots
            }
        )
        == 315
    )
    assert partition_set.to_wire()["semantic_shard_slot_count"] == 315
    assert (
        partition_set.to_wire()["physical_shard_materialization_authority"]
        == "not_claimed"
    )
    partition_text = partition_set.canonical_bytes.decode("utf-8")
    assert '"seed_tuple"' not in partition_text
    assert '"model_initialization_seed"' not in partition_text
    assert '"world_process_noise_seed"' not in partition_text
    assert '"raw_seed_values":"excluded_pre_freeze"' in partition_text
    assert all(
        tuple(
            (shard.training_replicate_id, shard.evaluation_replicate_id)
            for shard in partition.zipped_shard_slots
        )
        == ZIPPED_REPLICATE_IDS
        for partition in partition_set.partitions
    )

    assignment_replay = parse_global_panel_task_family_authority_set_bytes(
        assignment_set.canonical_bytes
    )
    partition_replay = parse_global_panel_task_partition_authority_set_bytes(
        partition_set.canonical_bytes
    )
    assert assignment_replay.authority_set_root == assignment_set.authority_set_root
    assert partition_replay.partition_set_root == partition_set.partition_set_root
    assert (
        parse_panel_task_family_assignment_authority_bytes(
            assignment_set.authorities[0].canonical_bytes
        ).assignment_authority_digest
        == assignment_set.authorities[0].assignment_authority_digest
    )
    first_partition = partition_set.partitions[0]
    assert (
        parse_panel_task_split_partition_authority_bytes(
            canonical_json_bytes(first_partition.to_wire())
        ).partition_authority_digest
        == first_partition.partition_authority_digest
    )


def test_w15_panels_are_distinct_authority_identities(authority_sets) -> None:
    assignment_set, partition_set = authority_sets
    w15 = [
        item
        for item in assignment_set.authorities
        if item.family_intent.identity.world_slot == "W15"
    ]
    assert len(w15) == 10
    assert {item.family_intent.identity.panel_id for item in w15} == {
        "W15A-randomized-identifiable",
        "W15B-observational-nonidentified",
    }
    assert len({item.assignment_authority_digest for item in w15}) == 10

    w15_partitions = [
        item
        for item in partition_set.partitions
        if item.assignment.family_intent.identity.world_slot == "W15"
    ]
    assert len(w15_partitions) == 30
    assert len({item.partition_authority_digest for item in w15_partitions}) == 30


def test_split_neutral_intent_rejects_row_and_split_bearing_fields(
    authority_sets,
) -> None:
    assignment_set, _ = authority_sets
    wire = assignment_set.authorities[0].family_intent.to_wire()
    wire["candidate_row_digest"] = _d("candidate-row")
    wire["judge_row_digest"] = _d("judge-row")

    with pytest.raises(ProtocolViolation, match="keys mismatch"):
        SplitNeutralFamilyIntent.from_wire(wire)

    unit_wire = assignment_set.authorities[0].family_intent.units[0].to_wire()
    unit_wire["assigned_split"] = "test"
    with pytest.raises(ProtocolViolation, match="keys mismatch"):
        SplitNeutralFamilyUnitIntent.from_wire(unit_wire)


def test_missing_duplicate_and_cross_panel_authorities_fail_closed(
    authority_sets,
) -> None:
    assignment_set, _ = authority_sets
    with pytest.raises(ProtocolViolation, match="inventory mismatch"):
        build_global_panel_task_family_authority_set(assignment_set.authorities[:-1])
    with pytest.raises(ProtocolViolation, match="duplicate identity"):
        build_global_panel_task_family_authority_set(
            assignment_set.authorities[:-1] + (assignment_set.authorities[0],)
        )

    last_identity = assignment_set.authorities[-1].family_intent.identity
    with pytest.raises(ProtocolViolation, match="share one physical assignment"):
        build_global_panel_task_family_authority_set(
            assignment_set.authorities[:-1]
            + (
                _assignment(
                    last_identity.world_slot,
                    last_identity.panel_id,
                    last_identity.task,
                    scope_digest=last_identity.scope_digest,
                    variant="-changed",
                ),
            )
        )
    with pytest.raises(ProtocolViolation, match="share one physical assignment"):
        build_global_panel_task_family_authority_set(
            assignment_set.authorities[:-1]
            + (
                _assignment(
                    last_identity.world_slot,
                    last_identity.panel_id,
                    last_identity.task,
                    scope_digest=last_identity.scope_digest,
                    split_rotation=1,
                ),
            )
        )

    wire = json.loads(assignment_set.canonical_bytes)
    w15a = next(
        item
        for item in wire["authorities"]
        if item["identity"]["world_slot"] == "W15"
        and item["identity"]["panel_id"] == "W15A-randomized-identifiable"
    )
    w15a["identity"] = PanelTaskIdentity(
        w15a["identity"]["benchmark_id"],
        w15a["identity"]["benchmark_revision"],
        w15a["identity"]["scope_digest"],
        "W15",
        "W15B-observational-nonidentified",
        assignment_set.authorities[0].family_intent.identity.task,
    ).to_wire()
    with pytest.raises(ProtocolViolation):
        parse_global_panel_task_family_authority_set_bytes(canonical_json_bytes(wire))


def test_partition_omission_duplication_and_cartesian_shards_fail_closed(
    authority_sets,
) -> None:
    _, partition_set = authority_sets
    wire = json.loads(partition_set.canonical_bytes)
    wire["partitions"].pop()
    wire["partition_count"] = 314
    with pytest.raises(ProtocolViolation, match="105 authorities x 3 splits"):
        parse_global_panel_task_partition_authority_set_bytes(
            canonical_json_bytes(wire)
        )

    wire = json.loads(partition_set.canonical_bytes)
    wire["partitions"][-1] = wire["partitions"][0]
    with pytest.raises(ProtocolViolation, match="105 authorities x 3 splits"):
        parse_global_panel_task_partition_authority_set_bytes(
            canonical_json_bytes(wire)
        )

    wire = json.loads(partition_set.canonical_bytes)
    wire["partitions"][0]["zipped_shard_slots"] = (
        wire["partitions"][0]["zipped_shard_slots"] * 5
    )
    wire["partitions"][0]["zipped_shard_slot_count"] = 25
    with pytest.raises(ProtocolViolation, match="reconstruction mismatch"):
        parse_global_panel_task_partition_authority_set_bytes(
            canonical_json_bytes(wire)
        )


def test_five_legacy_strata_roots_are_real_typed_bytes_but_global_only() -> None:
    authority = _legacy_authority("W03")
    batch = StrataReceiptBatch(authority, _legacy_all_receipts(authority))
    root_set = LegacyGlobalStrataRootBytePreimageSet.from_typed_authorities(
        authority.public,
        authority.judge.allocation_manifest,
        authority.judge,
        authority,
        batch,
    )
    replay = parse_legacy_global_strata_root_byte_preimage_set_bytes(
        root_set.canonical_bytes
    )
    assert replay.root_set_digest == root_set.root_set_digest
    assert len(replay.roots) == 5
    wire = replay.to_wire()
    assert wire["authority_claim"] == "exact_byte_integrity_only"
    assert wire["semantic_schema_replay"] == "not_proven"
    assert wire["panel_task_split_partition_authority"] == "not_claimed"
    assert "identity" not in wire
    assert "split" not in wire
    assert "partition_authority_digest" not in wire

    tampered = json.loads(root_set.canonical_bytes)
    tampered["roots"][0]["preimage"]["canonical_bytes_base64"] = tampered["roots"][1][
        "preimage"
    ]["canonical_bytes_base64"]
    with pytest.raises(ProtocolViolation):
        parse_legacy_global_strata_root_byte_preimage_set_bytes(
            canonical_json_bytes(tampered)
        )


def test_legacy_materializer_is_never_upgraded(authority_sets) -> None:
    assignment_set, partition_set = authority_sets
    for wire in (assignment_set.to_wire(), partition_set.to_wire()):
        assert wire["status"] == "pre_freeze_scaffold"
        assert wire["freeze_grade_evidence"] is False
        assert wire["benchmark_freeze_eligible"] is False
        assert wire["legacy_materializer_status"] == "incomplete_not_upgradeable"
        assert wire["blockers"][0]["code"] == "UCM-E003-HARNESS_INCOMPLETE"
