from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.benchmark_v1_contract import (
    DiagnosisPrediction,
    METRIC_CONTRACTS,
    RolloutPrediction,
    SharedPatientState,
    build_public_training_record,
    diagnosis_scores,
    metric_contract_wire,
    rollout_scores,
    treatment_regret,
)
from prototype.unified_map.benchmark_v1_freeze import (
    FREEZE_FILENAME,
    FREEZE_STATUS,
    MODEL_SEEDS,
    REPLICATE_IDS,
    build_freeze_manifest,
    build_seed_reveal,
    issue_freeze,
    new_seed_secret,
    verify_freeze_manifest_bytes,
    verify_seed_reveal,
)
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
)
from prototype.unified_map.world_registry import WORLD_REGISTRY
from prototype.unified_map.worlds.base import WorldSplit


PYTHON = Path(__file__).resolve().parents[2]


def test_executable_contract_closes_sixteen_noncompensating_measurements() -> None:
    assert len(METRIC_CONTRACTS) == 16
    assert tuple(row["measurement_id"] for row in METRIC_CONTRACTS) == tuple(
        f"M{index:02d}" for index in range(1, 17)
    )
    wire = metric_contract_wire()
    assert wire["aggregation"]["single_compensating_score"] == "forbidden"
    assert wire["undefined"]["metric_imputation"] == "forbidden"


def test_live_panel_has_twenty_worlds_twenty_one_panels_and_training_targets() -> None:
    identities: list[tuple[str, str]] = []
    for slot, declaration in WORLD_REGISTRY.items():
        for panel in declaration.panels:
            identities.append((slot, panel.panel_id))
            world = panel.instantiate()
            episode = world.generate_episode(WorldSplit.TRAIN, 73, 0)
            record = build_public_training_record(world, episode, oracle_seed=101)
            assert record.history is episode.public_history
            assert set(record.diagnostic_target) == set(world.catalog.diagnostic_labels)
            assert len(record.rollouts) == sum(
                len(world.policy_set(horizon)) for horizon in world.catalog.horizons
            )
    assert len(identities) == 21
    assert len({slot for slot, _ in identities}) == 20


def test_freeze_build_verify_and_seed_reveal_roundtrip() -> None:
    secret = new_seed_secret()
    freeze = build_freeze_manifest(secret)
    parsed = verify_freeze_manifest_bytes(canonical_json_bytes(freeze))
    assert parsed["status"] == FREEZE_STATUS
    assert parsed["world_count"] == 20
    assert parsed["panel_count"] == 21
    assert tuple(parsed["split_protocol"]["replicate_ids"]) == REPLICATE_IDS
    assert tuple(parsed["split_protocol"]["model_seeds"]) == MODEL_SEEDS
    reveal = build_seed_reveal(secret, parsed)
    verify_seed_reveal(reveal, parsed)


def test_freeze_rejects_resigned_semantic_or_source_drift() -> None:
    freeze = build_freeze_manifest(new_seed_secret())
    freeze["metric_contract"]["signature_dimension"] = 31
    preimage = {key: value for key, value in freeze.items() if key != "freeze_root"}
    # A caller cannot make alternate semantics valid merely by replacing the root.
    from prototype.unified_map.benchmark_v1_freeze import (
        FREEZE_ROOT_DOMAIN,
    )
    from prototype.unified_map.canonical import domain_digest

    freeze["freeze_root"] = domain_digest(
        FREEZE_ROOT_DOMAIN, (canonical_json_bytes(preimage),)
    )
    with pytest.raises(ProtocolViolation, match="live benchmark semantics"):
        verify_freeze_manifest_bytes(canonical_json_bytes(freeze))


def test_issue_is_append_only(tmp_path: Path) -> None:
    output = tmp_path / "freeze.json"
    secret = tmp_path / "private" / "seed.json"
    first = issue_freeze(output, secret)
    assert output.exists() and secret.exists()
    assert verify_freeze_manifest_bytes(output.read_bytes())["freeze_root"] == first[
        "freeze_root"
    ]
    with pytest.raises(ProtocolViolation, match="already exists"):
        issue_freeze(output, secret)


def test_shared_state_hash_and_primary_scores_are_executable() -> None:
    state = SharedPatientState(
        "test-state/1", canonical_json_bytes({"belief": [0.2, 0.8]}), (0.2, 0.8)
    )
    assert state.state_hash.startswith("sha256:")
    scores = diagnosis_scores(
        DiagnosisPrediction({"C0": 0.2, "C1": 0.8}),
        {"C0": 0.0, "C1": 1.0},
    )
    assert scores["top1_accuracy"] == 1.0
    assert scores["cross_entropy_nll"] > 0.0

    world = WORLD_REGISTRY["W01"].panels[0].instantiate()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 91, 0)
    horizon = world.catalog.horizons[0]
    oracles = [
        world.counterfactual(episode, policy, horizon, 707 + index)
        for index, policy in enumerate(world.policy_set(horizon))
    ]
    predictions = [
        RolloutPrediction(tuple([0.0] * 32), oracle.expected_utility)
        for oracle in oracles
    ]
    assert rollout_scores(predictions[0], oracles[0])["utility_absolute_error"] == 0.0
    assert treatment_regret(predictions, oracles)["regret"] == 0.0


def test_repository_freeze_manifest_is_live_verifiable_when_present() -> None:
    manifest = PYTHON / FREEZE_FILENAME
    if manifest.exists():
        assert verify_freeze_manifest_bytes(manifest.read_bytes())["status"] == FREEZE_STATUS

