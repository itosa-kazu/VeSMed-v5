from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from prototype.unified_map.candidate_protocol import ResultStatus
from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes, digest_bytes, digest_json
from prototype.unified_map.extensions import (
    ExtensionFirstQueryResult,
    ExtensionRunner,
    ExtensionVerdict,
    candidate_tree_digest,
)
from prototype.unified_map.schema import PlanKind
from prototype.unified_map.state import StateClass, StatePayload, seal_state
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w16 import W16World, make_w16_extension_custody
from prototype.unified_map.worlds.w17 import W17World, make_w17_extension_custody


def _primary_fixture(tmp_path: Path, world: W16World | W17World, custody: object):
    candidate = tmp_path / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "candidate.py").write_text(
        "def head(state, query):\n    return {'status': 'scope_insufficient'}\n",
        encoding="utf-8",
    )
    model = b"primary-model-artifact-v1\x00"
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 7301, 3)
    payload = StatePayload.from_json(
        {"summary": [0.125, 0.25]},
        schema_version="primary-state/1",
        state_class=StateClass.COMPRESSED_SHARED,
    )
    state = seal_state(
        payload,
        candidate_bundle_digest=candidate_tree_digest(candidate),
        model_digest=digest_bytes(model),
        scope_digest=digest_json({"world": type(world).__name__, "stage": "S0"}),
        catalog_digest=world.catalog.digest,
        as_of_available_at=episode.public_history.as_of_available_at,
        operation="initialize",
        state_instance_id="primary-state-instance",
    )
    runner = ExtensionRunner(custody, primary_catalog_digest=world.catalog.digest)
    return candidate, model, episode, state, runner


def _activated_world(
    tmp_path: Path,
    world_type: type,
    custody_factory: object,
) -> W16World | W17World:
    custody = custody_factory()
    primary = world_type(extension_commitment=custody.public.commitment)
    candidate, model, episode, state, runner = _primary_fixture(
        tmp_path, primary, custody
    )
    runner.seal_primary(
        candidate_root=candidate,
        model_artifact=model,
        states=(state,),
        histories={state.record.state_hash: episode.public_history},
    )
    return primary.activate_extension(runner.reveal())


@pytest.mark.parametrize(
    ("world_type", "custody_factory", "forbidden"),
    (
        (W16World, make_w16_extension_custody, (b"obs_2", b"p_result_1_given_C1")),
        (W17World, make_w17_extension_custody, (b'"A2"', b"effect_C1")),
    ),
)
def test_extension_source_is_opaque_until_candidate_model_and_state_are_sealed(
    tmp_path: Path,
    world_type: type,
    custody_factory: object,
    forbidden: tuple[bytes, ...],
) -> None:
    custody = custody_factory()
    world = world_type(extension_commitment=custody.public.commitment)
    candidate, model, episode, state, runner = _primary_fixture(
        tmp_path, world, custody
    )

    public = canonical_json_bytes(runner.public_commitment.to_wire())
    assert b"world_id" not in public
    candidate_bytes = (candidate / "candidate.py").read_bytes()
    for marker in forbidden:
        assert marker not in public
        assert marker not in custody.ciphertext
        assert marker not in candidate_bytes
        assert marker not in model
        assert marker not in state.candidate_input.payload.payload
    assert "hiding_nonce" not in runner.public_commitment.to_wire()
    assert "encryption_key" not in runner.public_commitment.to_wire()
    with pytest.raises(ProtocolViolation, match="requires candidate, model, and primary state seals"):
        runner.reveal()
    with pytest.raises(ProtocolViolation, match="before reveal"):
        _ = world.extension_catalog

    primary = runner.seal_primary(
        candidate_root=candidate,
        model_artifact=model,
        states=(state,),
        histories={state.record.state_hash: episode.public_history},
    )
    reveal = runner.reveal()
    assert reveal.commitment == custody.public.commitment
    assert reveal.pack_digest == digest_bytes(reveal.pack_bytes)
    assert primary.state_hashes == (state.record.state_hash,)
    activated = world.activate_extension(reveal)
    assert activated.extension_catalog.digest == reveal.pack["catalog_digest"]


def test_hiding_commitment_is_randomized_and_opens_exactly() -> None:
    first = make_w16_extension_custody()
    second = make_w16_extension_custody()
    assert first.public.commitment != second.public.commitment
    assert first.public.ciphertext_digest != second.public.ciphertext_digest
    assert len(first.hiding_nonce) == len(first.encryption_key) == 32


def test_reveal_fails_if_primary_candidate_changes_after_seal(tmp_path: Path) -> None:
    custody = make_w16_extension_custody()
    world = W16World(extension_commitment=custody.public.commitment)
    candidate, model, episode, state, runner = _primary_fixture(tmp_path, world, custody)
    runner.seal_primary(
        candidate_root=candidate,
        model_artifact=model,
        states=(state,),
        histories={state.record.state_hash: episode.public_history},
    )
    (candidate / "candidate.py").write_text("# post-seal rewrite\n", encoding="utf-8")
    with pytest.raises(ProtocolViolation, match="candidate bundle changed"):
        runner.reveal()


def test_first_extension_query_contains_only_sealed_state_and_typed_query(
    tmp_path: Path,
) -> None:
    custody = make_w17_extension_custody()
    world = W17World(extension_commitment=custody.public.commitment)
    candidate, model, episode, state, runner = _primary_fixture(tmp_path, world, custody)
    runner.seal_primary(
        candidate_root=candidate,
        model_artifact=model,
        states=(state,),
        histories={state.record.state_hash: episode.public_history},
    )
    runner.reveal()
    original_payload = state.candidate_input.payload.payload

    def candidate_head(request):
        wire = request.to_wire()
        encoded = canonical_json_bytes(wire)
        assert b"history" not in encoded.lower()
        assert b"events" not in encoded.lower()
        assert b"world_id" not in encoded.lower()
        assert set(wire) == {
            "protocol",
            "state",
            "state_hash",
            "extension_pack_digest",
            "extension_pack",
            "query",
        }
        assert wire["extension_pack"]["operator"]["action_id"] == "A2"
        return ExtensionFirstQueryResult(
            ResultStatus.OK,
            {"expected_utility": -1.25},
        )

    transcript = runner.first_state_only_query(
        state_hash=state.record.state_hash,
        query={"kind": "rollout", "action_id": "A2", "horizon": 4},
        invoke=candidate_head,
        expected_prediction={"expected_utility": -1.25},
    )
    assert transcript.status is ResultStatus.OK
    assert transcript.verdict is ExtensionVerdict.PASS
    assert transcript.state_snapshot_before == transcript.state_snapshot_after
    assert state.candidate_input.payload.payload == original_payload


def test_scope_insufficient_is_honest_and_only_then_authorizes_measured_migration(
    tmp_path: Path,
) -> None:
    custody = make_w17_extension_custody()
    world = W17World(extension_commitment=custody.public.commitment)
    candidate, model, episode, state, runner = _primary_fixture(tmp_path, world, custody)
    runner.seal_primary(
        candidate_root=candidate,
        model_artifact=model,
        states=(state,),
        histories={state.record.state_hash: episode.public_history},
    )
    reveal = runner.reveal()
    activated = world.activate_extension(reveal)
    with pytest.raises(ProtocolViolation, match="only after scope_insufficient"):
        runner.authorize_migration(
            state_hash=state.record.state_hash,
            migrate=lambda history, pack: state.candidate_input.payload,
            extension_catalog_digest=activated.extension_catalog.digest,
        )

    transcript = runner.first_state_only_query(
        state_hash=state.record.state_hash,
        query={"kind": "rollout", "action_id": "A2", "horizon": 4},
        invoke=lambda request: ExtensionFirstQueryResult(
            ResultStatus.SCOPE_INSUFFICIENT
        ),
    )
    assert transcript.verdict is ExtensionVerdict.HONEST_LIMIT

    def replay(history, pack):
        return StatePayload.from_json(
            {"history_digest": history.digest, "extension": pack.pack_digest},
            schema_version="migrated-state/1",
            state_class=StateClass.DYNAMIC_SHARED,
        )

    outcome = runner.authorize_migration(
        state_hash=state.record.state_hash,
        migrate=replay,
        extension_catalog_digest=activated.extension_catalog.digest,
        training_examples=(b"row-1", b"row-2"),
    )
    assert outcome.migrated_state.record.operation == "replay"
    assert outcome.migrated_state.record.parent_state_hash == state.record.state_hash
    assert outcome.migrated_state.record.catalog_digest == activated.extension_catalog.digest
    assert outcome.cost.replay_history_bytes > 0
    assert outcome.cost.training_examples == 2
    assert outcome.cost.training_bytes == 10
    assert outcome.s0_snapshot_before == outcome.s0_snapshot_after


def test_w16_one_sealed_state_forks_by_delta_only_and_preserves_lineage(
    tmp_path: Path,
) -> None:
    custody = make_w16_extension_custody()
    primary_world = W16World(extension_commitment=custody.public.commitment)
    candidate, model, episode, state, runner = _primary_fixture(
        tmp_path, primary_world, custody
    )
    runner.seal_primary(
        candidate_root=candidate,
        model_artifact=model,
        states=(state,),
        histories={state.record.state_hash: episode.public_history},
    )
    world = primary_world.activate_extension(runner.reveal())
    original = state.candidate_input.payload.payload

    def updater(request):
        assert not hasattr(request, "history")
        decoded = json.loads(request.state.payload.payload)
        result = next(
            event.payload["value"]
            for event in request.delta.events
            if event.payload.get("channel_id") == "obs_2"
        )
        decoded["q2_result"] = result
        return StatePayload.from_json(
            decoded,
            schema_version="extension-state/1",
            state_class=StateClass.DYNAMIC_SHARED,
        )

    negative = runner.update_from_sealed_state(
        state_hash=state.record.state_hash,
        delta=world.extension_delta(0, seed=1, episode_index=1),
        seed=7,
        invoke=updater,
        extension_catalog_digest=world.extension_catalog.digest,
    )
    positive = runner.update_from_sealed_state(
        state_hash=state.record.state_hash,
        delta=world.extension_delta(1, seed=1, episode_index=1),
        seed=7,
        invoke=updater,
        extension_catalog_digest=world.extension_catalog.digest,
    )
    assert negative.record.parent_state_hash == positive.record.parent_state_hash == state.record.state_hash
    assert negative.record.state_hash != positive.record.state_hash
    assert negative.record.operation == positive.record.operation == "update"
    assert state.candidate_input.payload.payload == original


def test_w16_adaptive_q2_branches_only_after_result_availability_and_references_agree(
    tmp_path: Path,
) -> None:
    world = _activated_world(
        tmp_path, W16World, make_w16_extension_custody
    )
    episode = world.generate_extension_episode(WorldSplit.VALIDATION, 1600, 5)
    adaptive = next(
        policy
        for policy in world.extension_policy_set(4)
        if policy.kind is PlanKind.ACTION_SEQUENCE
        and any(action.parameters.get("result_available_offset") == 1 for action in policy.actions)
    )
    production = world.counterfactual(episode, adaptive, 4, 1)
    reference = world.reference_counterfactual(episode, adaptive, 4, 999)
    assert production.expected_utility == pytest.approx(reference.expected_utility, abs=1e-12)
    branches = production.observation_distribution["branches"]
    assert [row["q2_result"] for row in branches] == [0, 1]
    assert all(row["steps"][0]["action"] == "NoNewAction" for row in branches)
    assert branches[0]["steps"][1]["action"] == "NoNewAction"
    assert branches[1]["steps"][1]["action"] == "A1"
    assert production.outcome_distribution["adaptive_action_occurs_only_after_available"]


@pytest.mark.parametrize(
    ("world_type", "custody_factory"),
    ((W16World, make_w16_extension_custody), (W17World, make_w17_extension_custody)),
)
def test_oracles_are_public_history_only_under_private_swap_and_reference_is_source_distinct(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    world_type: type,
    custody_factory: object,
) -> None:
    world = _activated_world(tmp_path, world_type, custody_factory)
    episode = world.generate_extension_episode(WorldSplit.SEALED_TEST, 991, 4)
    private_swap = replace(
        episode,
        case_key="judge-private-swap",
        hidden_state_at_cut={"x": 99999.0, "private": 1},
        invariant_parameters={"class_index": 1, "adversarial": True},
        diagnostic_target={"adversarial": 1.0},
        factual_future=[{"leak": 1}],
        oracle_anchor={"leak": 1},
    )
    policies = (
        world.extension_policy_set(4)
        if isinstance(world, W17World)
        else world.extension_policy_set(4)
    )
    policy = policies[-1]
    left = world.counterfactual(episode, policy, 4, 3)
    right = world.counterfactual(private_swap, policy, 4, 3)
    assert left.expected_utility == right.expected_utility
    assert left.observation_distribution == right.observation_distribution
    reference = world.reference_counterfactual(episode, policy, 4, 3)
    assert reference.expected_utility == pytest.approx(left.expected_utility, abs=1e-12)

    # Break the production posterior method.  The reference path must remain live.
    monkeypatch.setattr(
        world,
        "public_history_posterior",
        lambda episode: (_ for _ in ()).throw(AssertionError("production called")),
    )
    again = world.reference_counterfactual(episode, policy, 4, 3)
    assert again.expected_utility == reference.expected_utility


def test_w17_randomized_s1_corpus_has_both_arms_and_frozen_propensity(
    tmp_path: Path,
) -> None:
    world = _activated_world(
        tmp_path, W17World, make_w17_extension_custody
    )
    corpus = world.generate_extension_corpus(WorldSplit.VALIDATION, 1700, size=128)
    arms = [row.oracle_anchor["randomized_s1_arm"] for row in corpus]
    assert set(arms) == {"NoNewAction", "A2"}
    for row in corpus:
        assignment = row.action_propensities[-1]
        assert assignment["randomized"] is True
        assert assignment["probabilities"] == {"NoNewAction": 0.5, "A2": 0.5}
        assert row.factual_future[0]["performed_action"] == assignment["selected"]


def test_w16_randomized_s1_corpus_orders_q2_independently_at_half_propensity(
    tmp_path: Path,
) -> None:
    world = _activated_world(
        tmp_path, W16World, make_w16_extension_custody
    )
    corpus = world.generate_extension_corpus(WorldSplit.VALIDATION, 160016, size=128)
    arms = [row.action_propensities[-1]["selected"] for row in corpus]
    assert set(arms) == {"NoNewCheck", "Q2"}
    for row in corpus:
        assignment = row.action_propensities[-1]
        assert assignment["probabilities"] == {"NoNewCheck": 0.5, "Q2": 0.5}
        has_result = any(
            event.payload.get("channel_id") == "obs_2"
            for event in row.public_history.events
        )
        assert has_result is (assignment["selected"] == "Q2")


@pytest.mark.parametrize(
    ("world_type", "custody_factory"),
    ((W16World, make_w16_extension_custody), (W17World, make_w17_extension_custody)),
)
def test_production_and_reference_public_posteriors_and_policy_values_agree_on_panel(
    tmp_path: Path,
    world_type: type,
    custody_factory: object,
) -> None:
    world = _activated_world(tmp_path, world_type, custody_factory)
    for index in range(16):
        episode = world.generate_extension_episode(WorldSplit.VALIDATION, 8800, index)
        production_posterior = world.public_history_posterior(episode)
        reference_posterior = world.reference_public_history_posterior(episode)
        assert production_posterior == pytest.approx(reference_posterior, abs=1e-12)
        for policy in world.extension_policy_set(4):
            production = world.counterfactual(episode, policy, 4, 0)
            reference = world.reference_counterfactual(episode, policy, 4, 2**64 - 1)
            assert production.expected_utility == pytest.approx(
                reference.expected_utility, abs=1e-12
            )


def test_legacy_verdicts_use_protocol_ok_and_have_no_caller_truth_booleans() -> None:
    for world_type in (W16World, W17World):
        signature = inspect.signature(world_type.legacy_extension_verdict)
        assert tuple(signature.parameters) == ("status",)
        assert (
            world_type.legacy_extension_verdict(ResultStatus.SCOPE_INSUFFICIENT)
            == "HONEST_LIMIT"
        )
        assert world_type.legacy_extension_verdict(ResultStatus.OK) == "UNSCORED_OK"
        assert (
            world_type.legacy_extension_verdict(ResultStatus.UNSUPPORTED)
            == "HARD_FAILURE"
        )
        with pytest.raises(ProtocolViolation, match="must use ResultStatus"):
            world_type.legacy_extension_verdict("ok")


def test_w16_w17_strata_are_exact_public_replayable_and_cover_registry_contract(
    tmp_path: Path,
) -> None:
    w16 = _activated_world(
        tmp_path / "w16", W16World, make_w16_extension_custody
    )
    primary16 = w16.generate_episode(WorldSplit.SEALED_TEST, 6100, 3)
    strata16 = w16.strata_for_episode(primary16)
    assert strata16[0] == "iid_support"
    assert "extension_check" in strata16
    assert "behavior_pair" not in strata16
    pair16 = w16.pre_result_alias_pair()[0]
    assert w16.strata_for_episode(pair16)[-1] == "behavior_pair"
    assert w16.strata_for_episode(
        replace(pair16, hidden_state_at_cut={"private": 999})
    ) == w16.strata_for_episode(pair16)

    w17 = _activated_world(
        tmp_path / "w17", W17World, make_w17_extension_custody
    )
    primary17 = w17.generate_episode(WorldSplit.SEALED_TEST, 6200, 3)
    strata17 = w17.strata_for_episode(primary17)
    assert strata17[0] == "iid_support"
    assert "extension_treatment" in strata17
    assert "behavior_pair" not in strata17
    pair17 = w17.extension_split_pair()[0]
    assert w17.strata_for_episode(pair17)[-1] == "behavior_pair"
    assert w17.strata_for_episode(
        replace(pair17, invariant_parameters={"private": "swapped"})
    ) == w17.strata_for_episode(pair17)

    # Boundary membership is the declared public threshold and is populated.
    for world in (w16, w17):
        rows = [
            world.generate_episode(WorldSplit.SEALED_TEST, 6300, index)
            for index in range(512)
        ]
        tails = [row for row in rows if "boundary_tail" in world.strata_for_episode(row)]
        assert tails
        for row in tails:
            public_values = [
                float(event.payload["value"])
                for event in row.public_history.events
                if event.payload.get("channel_id") == "obs_0"
            ]
            assert any(value <= 0.0 or value >= 1.25 for value in public_values)
