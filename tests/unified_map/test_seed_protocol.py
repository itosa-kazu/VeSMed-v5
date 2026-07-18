from __future__ import annotations

import json
from dataclasses import replace

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
    domain_digest,
)
from prototype.unified_map.seed_protocol import (
    COMMITMENT_CONTEXT_PROTOCOL,
    EVALUATION_REPLICATE_IDS,
    FROZEN_BENCHMARK_REVISION,
    OFFICIAL_SEED_DOMAINS,
    OFFICIAL_COMMITMENT_HASH_DOMAIN,
    SEED_PROTOCOL_DIGEST,
    SEED_PROTOCOL_MANIFEST_BYTES,
    TRAIN5_PRECOMMIT_ARTIFACT_TYPE,
    TRAIN5_PRECOMMIT_STAGE,
    TRAINING_REPLICATE_IDS,
    ZIPPED_REPLICATE_IDS,
    EvaluationSeedPanel,
    EvaluationSeedTuple,
    OfficialCommitmentContext,
    OfficialCommitmentDomain,
    OfficialCommitmentStage,
    OfficialSeedDomain,
    Train5Precommit,
    TrainingSeedPanel,
    TrainingSeedTuple,
    ZippedPairingAuthority,
    official_commitment_digest,
    parse_official_commitment_context_bytes,
    parse_train5_precommit_bytes,
    train5_precommit_digest,
    write_train5_precommit,
)


def _digest(label: str) -> str:
    return digest_json({"fixture": label})


def _training_tuples() -> tuple[TrainingSeedTuple, ...]:
    return tuple(
        TrainingSeedTuple(
            model_initialization_seed=index * 10 + 1,
            training_data_seed=index * 10 + 2,
            training_order_seed=index * 10 + 3,
        )
        for index in range(5)
    )


def _evaluation_tuples() -> tuple[EvaluationSeedTuple, ...]:
    return tuple(
        EvaluationSeedTuple(
            world_process_noise_seed=index * 10 + 4,
            observation_schedule_seed=index * 10 + 5,
            evaluation_episode_seed=index * 10 + 6,
            analysis_seed=index * 10 + 7,
        )
        for index in range(5)
    )


def _artifact() -> Train5Precommit:
    freeze_manifest_digest = _digest("freeze-manifest")
    return Train5Precommit(
        confirmation_id="CONFIRM5-v1",
        benchmark_id="UCM-BENCHMARK-v1",
        benchmark_revision=FROZEN_BENCHMARK_REVISION,
        previous_artifact_digest=freeze_manifest_digest,
        scope_digest=_digest("scope"),
        scope_manifest_digest=_digest("scope-manifest"),
        freeze_manifest_digest=freeze_manifest_digest,
        freeze_authorization_digest=_digest("freeze-authorization"),
        seed_protocol_digest=SEED_PROTOCOL_DIGEST,
        draw_program_digest=_digest("draw-program"),
        committed_at="2026-07-18T12:00:00Z",
        panel=TrainingSeedPanel.from_tuples(
            OfficialSeedDomain.TRAIN5, _training_tuples()
        ),
    )


def _commitment_context() -> OfficialCommitmentContext:
    artifact = _artifact()
    evaluation = EvaluationSeedPanel.from_tuples(
        OfficialSeedDomain.EVAL5, _evaluation_tuples()
    )
    pairing = ZippedPairingAuthority(
        commitment_domain=OfficialCommitmentDomain.CONFIRM,
        training_panel_digest=artifact.panel.panel_digest,
        evaluation_panel_digest=evaluation.panel_digest,
    )
    return OfficialCommitmentContext(
        confirmation_id=artifact.confirmation_id,
        benchmark_id=artifact.benchmark_id,
        benchmark_revision=artifact.benchmark_revision,
        freeze_manifest_digest=artifact.freeze_manifest_digest,
        freeze_authorization_digest=artifact.freeze_authorization_digest,
        scope_digest=artifact.scope_digest,
        scope_manifest_digest=artifact.scope_manifest_digest,
        train5_precommit_digest=train5_precommit_digest(artifact),
        training_panel_digest=artifact.panel.panel_digest,
        candidate_seals_artifact_digest=_digest("candidate-seals-artifact"),
        candidate_seal_set_root=_digest("candidate-seal-set-root"),
        candidate_seal_count=15,
        candidate_ids_digest=_digest("candidate-ids"),
        candidate_family_ids_digest=_digest("candidate-family-ids"),
        seed_protocol_digest=artifact.seed_protocol_digest,
        draw_program_digest=artifact.draw_program_digest,
        evaluation_panel_digest=evaluation.panel_digest,
        zipped_pairing_digest=pairing.pairing_digest,
        commitment_domain=OfficialCommitmentDomain.CONFIRM,
        commitment_stage=OfficialCommitmentStage.HIDDEN_EVALUATION,
        committed_at="2026-07-18T14:00:00Z",
    )


def _mutated_payload(mutator) -> bytes:
    wire = _artifact().to_wire()
    mutator(wire)
    return canonical_json_bytes(wire)


def test_official_seed_domains_are_exact_and_closed() -> None:
    assert OFFICIAL_SEED_DOMAINS == (
        "DEV5",
        "TRAIN5",
        "EVAL5",
        "REPRO5",
        "REDTEAM5",
        "analysis",
    )
    with pytest.raises(ValueError):
        OfficialSeedDomain("CONFIRM5")


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("model_initialization_seed", -1),
        ("training_data_seed", True),
        ("training_order_seed", 1.5),
    ],
)
def test_training_seed_tuple_requires_exact_nonnegative_integers(
    field: str, bad_value: object
) -> None:
    values = {
        "model_initialization_seed": 1,
        "training_data_seed": 2,
        "training_order_seed": 3,
    }
    values[field] = bad_value
    with pytest.raises(ProtocolViolation, match="uint64 integer"):
        TrainingSeedTuple(**values)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("world_process_noise_seed", -1),
        ("observation_schedule_seed", False),
        ("evaluation_episode_seed", "7"),
        ("analysis_seed", 2.5),
    ],
)
def test_evaluation_seed_tuple_requires_exact_nonnegative_integers(
    field: str, bad_value: object
) -> None:
    values = {
        "world_process_noise_seed": 1,
        "observation_schedule_seed": 2,
        "evaluation_episode_seed": 3,
        "analysis_seed": 4,
    }
    values[field] = bad_value
    with pytest.raises(ProtocolViolation, match="uint64 integer"):
        EvaluationSeedTuple(**values)


def test_seed_tuples_reject_uint64_upper_bound() -> None:
    with pytest.raises(ProtocolViolation, match="uint64"):
        TrainingSeedTuple(2**64, 0, 0)
    with pytest.raises(ProtocolViolation, match="uint64"):
        EvaluationSeedTuple(0, 0, 0, 2**64)


def test_tuple_parser_is_closed_and_tuple_digest_binds_domain_and_replicate() -> None:
    seed_tuple = _training_tuples()[0]
    with pytest.raises(ProtocolViolation, match="keys mismatch"):
        TrainingSeedTuple.from_wire({**seed_tuple.to_wire(), "extra": 0})
    digest = seed_tuple.digest(OfficialSeedDomain.TRAIN5, "train-01")
    assert digest != seed_tuple.digest(OfficialSeedDomain.TRAIN5, "train-02")
    assert digest != seed_tuple.digest(OfficialSeedDomain.REPRO5, "train-01")
    with pytest.raises(ProtocolViolation, match="not a training panel domain"):
        seed_tuple.digest(OfficialSeedDomain.EVAL5, "train-01")


def test_exact_five_entry_panels_and_zipped_pairing_authority() -> None:
    training = TrainingSeedPanel.from_tuples(
        OfficialSeedDomain.TRAIN5, _training_tuples()
    )
    evaluation = EvaluationSeedPanel.from_tuples(
        OfficialSeedDomain.EVAL5, _evaluation_tuples()
    )
    assert tuple(row.training_replicate_id for row in training.entries) == (
        TRAINING_REPLICATE_IDS
    )
    assert tuple(row.evaluation_replicate_id for row in evaluation.entries) == (
        EVALUATION_REPLICATE_IDS
    )
    authority = ZippedPairingAuthority(
        commitment_domain=OfficialCommitmentDomain.CONFIRM,
        training_panel_digest=training.panel_digest,
        evaluation_panel_digest=evaluation.panel_digest,
    )
    assert authority.pairs == ZIPPED_REPLICATE_IDS
    assert len(authority.to_wire()["pairs"]) == 5
    assert authority.to_wire()["pairs"][0] == {
        "training_replicate_id": "train-01",
        "evaluation_replicate_id": "eval-01",
    }
    assert "pairing_digest" in authority.to_wire()


def test_panels_reject_wrong_count_duplicate_and_reorder() -> None:
    with pytest.raises(ProtocolViolation, match="exactly five"):
        TrainingSeedPanel.from_tuples(
            OfficialSeedDomain.TRAIN5, _training_tuples()[:-1]
        )
    panel = TrainingSeedPanel.from_tuples(OfficialSeedDomain.TRAIN5, _training_tuples())
    with pytest.raises(ProtocolViolation, match="canonical order"):
        replace(panel, entries=(panel.entries[1], panel.entries[0], *panel.entries[2:]))
    with pytest.raises(ProtocolViolation, match="canonical order"):
        replace(panel, entries=(panel.entries[0], panel.entries[0], *panel.entries[2:]))
    with pytest.raises(ProtocolViolation, match="canonical five zipped pairs"):
        ZippedPairingAuthority(
            commitment_domain=OfficialCommitmentDomain.CONFIRM,
            training_panel_digest=panel.panel_digest,
            evaluation_panel_digest=_digest("eval-panel"),
            pairs=(
                ZIPPED_REPLICATE_IDS[1],
                ZIPPED_REPLICATE_IDS[0],
                *ZIPPED_REPLICATE_IDS[2:],
            ),
        )


def test_train5_precommit_round_trip_contains_public_raw_seeds_and_stage(
    tmp_path,
) -> None:
    artifact = _artifact()
    wire = artifact.to_wire()
    assert wire["artifact_type"] == TRAIN5_PRECOMMIT_ARTIFACT_TYPE
    assert wire["stage"] == TRAIN5_PRECOMMIT_STAGE
    assert wire["domain"] == "TRAIN5"
    assert wire["entries"][0]["seed_tuple"] == _training_tuples()[0].to_wire()
    assert len(wire["entries"]) == 5
    assert parse_train5_precommit_bytes(artifact.to_bytes()) == artifact
    path = write_train5_precommit(tmp_path / "TRAIN5_PRECOMMIT.json", artifact)
    assert path.read_bytes() == artifact.to_bytes()
    assert train5_precommit_digest(artifact) == _digest_bytes(artifact.to_bytes())


def test_train5_precommit_writer_is_append_only(tmp_path) -> None:
    artifact = _artifact()
    path = tmp_path / "TRAIN5_PRECOMMIT.json"
    write_train5_precommit(path, artifact)
    original = path.read_bytes()
    with pytest.raises(ProtocolViolation, match="append-only"):
        write_train5_precommit(path, artifact)
    assert path.read_bytes() == original


def _digest_bytes(payload: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("key", sorted(Train5Precommit._TOP_LEVEL_KEYS))
def test_train5_precommit_rejects_every_missing_top_level_key(key: str) -> None:
    with pytest.raises(ProtocolViolation, match="keys mismatch"):
        parse_train5_precommit_bytes(_mutated_payload(lambda wire: wire.pop(key)))


def test_train5_precommit_rejects_extra_duplicate_and_noncanonical_json() -> None:
    with pytest.raises(ProtocolViolation, match="keys mismatch"):
        parse_train5_precommit_bytes(
            _mutated_payload(lambda wire: wire.__setitem__("extra", None))
        )

    canonical = _artifact().to_bytes().decode("utf-8")
    duplicate = canonical.replace(
        '"artifact_type":"TRAIN5_PRECOMMIT",',
        '"artifact_type":"TRAIN5_PRECOMMIT","artifact_type":"TRAIN5_PRECOMMIT",',
        1,
    ).encode("utf-8")
    with pytest.raises(ProtocolViolation, match="duplicate key"):
        parse_train5_precommit_bytes(duplicate)

    noncanonical = json.dumps(_artifact().to_wire(), indent=2).encode("utf-8")
    with pytest.raises(ProtocolViolation, match="canonical"):
        parse_train5_precommit_bytes(noncanonical)


def test_train5_precommit_rejects_wrong_tuple_and_panel_digests() -> None:
    with pytest.raises(ProtocolViolation, match="tuple digest mismatch"):
        parse_train5_precommit_bytes(
            _mutated_payload(
                lambda wire: wire["entries"][0].__setitem__(
                    "tuple_digest", _digest("wrong-tuple")
                )
            )
        )
    with pytest.raises(ProtocolViolation, match="panel digest mismatch"):
        parse_train5_precommit_bytes(
            _mutated_payload(
                lambda wire: wire.__setitem__("panel_digest", _digest("wrong-panel"))
            )
        )


def test_train5_precommit_requires_code_owned_seed_protocol_digest() -> None:
    with pytest.raises(ProtocolViolation, match="code-owned seed protocol digest"):
        replace(_artifact(), seed_protocol_digest=_digest("arbitrary-protocol"))
    with pytest.raises(ProtocolViolation, match="code-owned seed protocol digest"):
        parse_train5_precommit_bytes(
            _mutated_payload(
                lambda wire: wire.__setitem__(
                    "seed_protocol_digest", _digest("arbitrary-protocol")
                )
            )
        )


def test_train5_precommit_binds_previous_freeze_manifest() -> None:
    with pytest.raises(ProtocolViolation, match="previous artifact"):
        replace(_artifact(), previous_artifact_digest=_digest("not-the-freeze"))
    with pytest.raises(ProtocolViolation, match="previous artifact"):
        parse_train5_precommit_bytes(
            _mutated_payload(
                lambda wire: wire.__setitem__(
                    "previous_artifact_digest", _digest("not-the-freeze")
                )
            )
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("confirmation_id", "", "identity"),
        ("confirmation_id", "bad id", "identity"),
        ("benchmark_id", "../benchmark", "identity"),
        ("benchmark_revision", "PRE-FREEZE", "FROZEN-v1"),
        ("committed_at", "2026-07-18T12:00:00+00:00", "RFC3339"),
        ("committed_at", "2026-02-30T12:00:00Z", "real UTC"),
        ("committed_at", "2026-07-18T12:00:00.000Z", "RFC3339"),
    ],
)
def test_train5_precommit_identity_revision_and_time_boundaries(
    field: str, value: str, message: str
) -> None:
    with pytest.raises(ProtocolViolation, match=message):
        replace(_artifact(), **{field: value})


def test_train5_precommit_rejects_wrong_stage_domain_count_and_order() -> None:
    with pytest.raises(ProtocolViolation, match="post-freeze and pre-training"):
        parse_train5_precommit_bytes(
            _mutated_payload(
                lambda wire: wire.__setitem__("stage", "pre_freeze_pre_training")
            )
        )
    with pytest.raises(ProtocolViolation, match="domain must be TRAIN5"):
        parse_train5_precommit_bytes(
            _mutated_payload(lambda wire: wire.__setitem__("domain", "REPRO5"))
        )
    with pytest.raises(ProtocolViolation, match="exactly five"):
        parse_train5_precommit_bytes(
            _mutated_payload(lambda wire: wire["entries"].pop())
        )
    with pytest.raises(ProtocolViolation, match="canonical order"):
        parse_train5_precommit_bytes(
            _mutated_payload(
                lambda wire: wire["entries"].__setitem__(
                    slice(0, 2), reversed(wire["entries"][:2])
                )
            )
        )


def test_train5_precommit_rejects_nested_extra_key() -> None:
    with pytest.raises(ProtocolViolation, match="keys mismatch"):
        parse_train5_precommit_bytes(
            _mutated_payload(
                lambda wire: wire["entries"][0]["seed_tuple"].__setitem__(
                    "hidden_seed", 123
                )
            )
        )


def test_commitment_helper_is_domain_and_stage_separated() -> None:
    seed = bytes(range(32))
    nonce = bytes(reversed(range(32)))
    confirm_context = _commitment_context()
    confirm = official_commitment_digest(
        commitment_domain=OfficialCommitmentDomain.CONFIRM,
        stage=OfficialCommitmentStage.HIDDEN_EVALUATION,
        context=confirm_context,
        seed=seed,
        nonce=nonce,
    )
    assert COMMITMENT_CONTEXT_PROTOCOL == "ucm-official-commitment-context/1"
    assert OFFICIAL_COMMITMENT_HASH_DOMAIN == (b"UCM-OFFICIAL-SEED-COMMITMENT-v2\0")
    expected = domain_digest(
        OFFICIAL_COMMITMENT_HASH_DOMAIN,
        [
            OfficialCommitmentDomain.CONFIRM.value.encode("ascii"),
            OfficialCommitmentStage.HIDDEN_EVALUATION.value.encode("ascii"),
            confirm_context.context_digest.encode("ascii"),
            seed,
            nonce,
        ],
    )
    assert confirm == expected
    assert confirm != domain_digest(
        b"UCM-OFFICIAL-SEED-COMMITMENT-v1\0",
        [
            OfficialCommitmentDomain.CONFIRM.value.encode("ascii"),
            OfficialCommitmentStage.HIDDEN_EVALUATION.value.encode("ascii"),
            confirm_context.context_digest.encode("ascii"),
            seed,
            nonce,
        ],
    )
    repro_context = replace(
        confirm_context, commitment_domain=OfficialCommitmentDomain.REPRO
    )
    repro = official_commitment_digest(
        commitment_domain=OfficialCommitmentDomain.REPRO,
        stage=OfficialCommitmentStage.HIDDEN_EVALUATION,
        context=repro_context,
        seed=seed,
        nonce=nonce,
    )
    redteam_context = replace(
        confirm_context, commitment_domain=OfficialCommitmentDomain.REDTEAM
    )
    redteam = official_commitment_digest(
        commitment_domain=OfficialCommitmentDomain.REDTEAM,
        stage=OfficialCommitmentStage.HIDDEN_EVALUATION,
        context=redteam_context,
        seed=seed,
        nonce=nonce,
    )
    assert len({confirm, repro, redteam}) == 3
    with pytest.raises(ProtocolViolation, match="OfficialCommitmentDomain"):
        official_commitment_digest(
            commitment_domain="CONFIRM5-v1",
            stage=OfficialCommitmentStage.HIDDEN_EVALUATION,
            context=_commitment_context(),
            seed=seed,
            nonce=nonce,
        )
    with pytest.raises(ProtocolViolation, match="does not match context"):
        official_commitment_digest(
            commitment_domain=OfficialCommitmentDomain.REPRO,
            stage=OfficialCommitmentStage.HIDDEN_EVALUATION,
            context=confirm_context,
            seed=seed,
            nonce=nonce,
        )
    with pytest.raises(ProtocolViolation, match="OfficialCommitmentStage"):
        official_commitment_digest(
            commitment_domain=OfficialCommitmentDomain.CONFIRM,
            stage="analysis_commitment",
            context=confirm_context,
            seed=seed,
            nonce=nonce,
        )


def test_commitment_helper_binds_scope_freeze_precommit_and_candidate_seals() -> None:
    seed = b"s" * 32
    nonce = b"n" * 32
    baseline_context = _commitment_context()

    def commit(context: OfficialCommitmentContext) -> str:
        return official_commitment_digest(
            commitment_domain=OfficialCommitmentDomain.CONFIRM,
            stage=OfficialCommitmentStage.HIDDEN_EVALUATION,
            context=context,
            seed=seed,
            nonce=nonce,
        )

    baseline = commit(baseline_context)
    mutations = {
        "confirmation_id": "CONFIRM5-v1-alt",
        "benchmark_id": "UCM-BENCHMARK-v1-alt",
        "freeze_manifest_digest": _digest("other-freeze-manifest"),
        "freeze_authorization_digest": _digest("other-freeze-authorization"),
        "scope_digest": _digest("other-scope"),
        "scope_manifest_digest": _digest("other-scope-manifest"),
        "train5_precommit_digest": _digest("other-train5-precommit"),
        "training_panel_digest": _digest("other-training-panel"),
        "candidate_seals_artifact_digest": _digest("other-seals-artifact"),
        "candidate_seal_set_root": _digest("other-seal-root"),
        "candidate_seal_count": 20,
        "candidate_ids_digest": _digest("other-candidate-ids"),
        "candidate_family_ids_digest": _digest("other-family-ids"),
        "draw_program_digest": _digest("other-draw-program"),
        "evaluation_panel_digest": _digest("other-evaluation-panel"),
        "zipped_pairing_digest": _digest("other-pairing"),
        "committed_at": "2026-07-18T14:00:01Z",
    }
    changed = {
        commit(replace(baseline_context, **{field: value}))
        for field, value in mutations.items()
    }
    assert baseline not in changed
    assert len(changed) == len(mutations)


def test_commitment_context_is_closed_canonical_and_exactly_reconstructs() -> None:
    context = _commitment_context()
    assert parse_official_commitment_context_bytes(context.to_bytes()) == context
    assert context.context_digest == _digest_bytes(context.to_bytes())

    wire = context.to_wire()
    wire["extra"] = None
    with pytest.raises(ProtocolViolation, match="keys mismatch"):
        parse_official_commitment_context_bytes(canonical_json_bytes(wire))

    wire = context.to_wire()
    wire.pop("candidate_ids_digest")
    with pytest.raises(ProtocolViolation, match="keys mismatch"):
        parse_official_commitment_context_bytes(canonical_json_bytes(wire))


@pytest.mark.parametrize("count", [0, 5, 10, 14, 16, 2**64])
def test_commitment_context_requires_three_five_artifact_panels(count: int) -> None:
    with pytest.raises(ProtocolViolation, match="candidate seal count"):
        replace(_commitment_context(), candidate_seal_count=count)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("confirmation_id", "bad id", "identity"),
        ("benchmark_id", "", "identity"),
        ("benchmark_revision", "PRE-FREEZE", "FROZEN-v1"),
        ("seed_protocol_digest", "sha256:" + "0" * 64, "code-owned"),
        ("committed_at", "2026-07-18T14:00:00+00:00", "RFC3339"),
    ],
)
def test_commitment_context_identity_authority_and_time_boundaries(
    field: str, value: str, message: str
) -> None:
    with pytest.raises(ProtocolViolation, match=message):
        replace(_commitment_context(), **{field: value})


@pytest.mark.parametrize(
    ("seed", "nonce"),
    [
        (b"s" * 31, b"n" * 32),
        (b"s" * 33, b"n" * 32),
        (b"s" * 32, b"n" * 15),
    ],
)
def test_commitment_helper_requires_exact_seed_and_minimum_nonce(
    seed: bytes, nonce: bytes
) -> None:
    with pytest.raises(ProtocolViolation, match="32-byte|at least 16"):
        official_commitment_digest(
            commitment_domain=OfficialCommitmentDomain.CONFIRM,
            stage=OfficialCommitmentStage.HIDDEN_EVALUATION,
            context=_commitment_context(),
            seed=seed,
            nonce=nonce,
        )


@pytest.mark.parametrize("nonce_length", [16, 32, 33])
def test_commitment_helper_accepts_nonce_at_least_16_bytes(nonce_length: int) -> None:
    context = _commitment_context()
    assert official_commitment_digest(
        commitment_domain=context.commitment_domain,
        stage=context.commitment_stage,
        context=context,
        seed=b"s" * 32,
        nonce=b"n" * nonce_length,
    ).startswith("sha256:")


def test_redteam_cannot_claim_training_pairing_authority() -> None:
    with pytest.raises(ProtocolViolation, match="no training-panel pairing"):
        ZippedPairingAuthority(
            commitment_domain=OfficialCommitmentDomain.REDTEAM,
            training_panel_digest=_digest("train-panel"),
            evaluation_panel_digest=_digest("eval-panel"),
        )


def test_scope_boundary_contains_only_scope_digest_not_scope_or_raw_values() -> None:
    wire = _artifact().to_wire()
    assert "scope_digest" in wire
    assert "scope_manifest" not in wire
    assert "scope" not in wire
    assert all(
        key not in wire
        for key in ("P", "O", "A", "Q", "Pi", "Tau", "Gamma", "Y", "U", "D", "R")
    )
    assert "entries" in wire  # Raw public TRAIN values live here, not in scope.

    semantic_manifest = json.loads(SEED_PROTOCOL_MANIFEST_BYTES)
    assert _digest_bytes(SEED_PROTOCOL_MANIFEST_BYTES) == SEED_PROTOCOL_DIGEST
    assert semantic_manifest["scope_binding"]["run_specific_raw_seed_values"] == (
        "excluded_from_scope_manifest"
    )
    assert "entries" not in semantic_manifest
    assert "seed_tuple" not in semantic_manifest


@pytest.mark.parametrize(
    "payload",
    [
        b'{"x":"\\ud800"}\n',
        b'{"x":' + (b"[" * 2000) + b"0" + (b"]" * 2000) + b"}\n",
        b'{"x":' + (b"9" * 5000) + b"}\n",
    ],
)
def test_train5_parser_normalizes_host_json_failures(payload: bytes) -> None:
    with pytest.raises(ProtocolViolation):
        parse_train5_precommit_bytes(payload)
