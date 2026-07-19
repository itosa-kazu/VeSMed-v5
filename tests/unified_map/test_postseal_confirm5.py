from __future__ import annotations

import json

import pytest

from prototype.unified_map.benchmark_v1_freeze import REPLICATE_IDS, SEED_SECRET_SCHEMA
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.postseal_confirm5 import (
    COMMITMENT_SCHEMA,
    CONFIRM_ALIASES,
    DURABLE_SEAL_COMMIT,
    FROZEN_FREEZE_ROOT,
    PURPOSE,
    REVEAL_SCHEMA,
    SECRET_SCHEMA,
    build_commitment,
    build_reveal,
    build_secret,
    commitment_digest,
    issue_postseal_confirm5,
    normalize_to_benchmark_v1_execution_secret,
    verify_commitment_bytes,
    verify_reveal_bytes,
    verify_secret_bytes,
    write_reveal,
)


def _candidate_digest(label: str = "candidate") -> str:
    return digest_json({"source": label})


def _rows() -> list[dict[str, int | str]]:
    return [
        {
            "confirm_alias": alias,
            "train_root_seed": index * 100 + 11,
            "validation_root_seed": index * 100 + 12,
            "sealed_test_root_seed": index * 100 + 13,
        }
        for index, alias in enumerate(CONFIRM_ALIASES, start=1)
    ]


def _artifacts():
    secret = build_secret(_rows(), candidate_source_digest=_candidate_digest())
    commitment = build_commitment(secret)
    reveal = build_reveal(secret, commitment)
    return secret, commitment, reveal


def test_canonical_commit_secret_reveal_round_trip_and_fixed_authorities() -> None:
    secret, commitment, reveal = _artifacts()

    assert commitment["schema_version"] == COMMITMENT_SCHEMA
    assert secret["schema_version"] == SECRET_SCHEMA
    assert reveal["schema_version"] == REVEAL_SCHEMA
    assert commitment["purpose"] == PURPOSE == "supplemental_postseal_confirm"
    assert commitment["freeze_root"] == FROZEN_FREEZE_ROOT
    assert commitment["durable_seal_commit"] == DURABLE_SEAL_COMMIT
    assert commitment["alias_order"] == list(CONFIRM_ALIASES)
    assert [row["confirm_alias"] for row in commitment["row_commitments"]] == list(
        CONFIRM_ALIASES
    )

    decoded_commitment = verify_commitment_bytes(canonical_json_bytes(commitment))
    decoded_secret = verify_secret_bytes(canonical_json_bytes(secret), decoded_commitment)
    decoded_reveal = verify_reveal_bytes(canonical_json_bytes(reveal), decoded_commitment)
    assert decoded_secret == secret
    assert decoded_reveal == reveal
    assert reveal["commitment_digest"] == commitment_digest(commitment)
    assert canonical_json_bytes(commitment).endswith(b"\n")
    assert not canonical_json_bytes(commitment).endswith(b"\n\n")


def test_each_row_commitment_binds_seed_alias_and_full_selection_context() -> None:
    secret_a = build_secret(_rows(), candidate_source_digest=_candidate_digest("a"))
    secret_b = build_secret(_rows(), candidate_source_digest=_candidate_digest("b"))
    commitment_a = build_commitment(secret_a)
    commitment_b = build_commitment(secret_b)

    assert commitment_a["pack_root"] != commitment_b["pack_root"]
    assert [row["commitment"] for row in commitment_a["row_commitments"]] != [
        row["commitment"] for row in commitment_b["row_commitments"]
    ]

    changed_seed = _rows()
    changed_seed[2]["validation_root_seed"] += 1
    commitment_c = build_commitment(
        build_secret(changed_seed, candidate_source_digest=_candidate_digest("a"))
    )
    changed = [
        left["commitment"] != right["commitment"]
        for left, right in zip(
            commitment_a["row_commitments"],
            commitment_c["row_commitments"],
            strict=True,
        )
    ]
    assert changed == [False, False, True, False, False]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda wire: wire.update(candidate_source_digest=_candidate_digest("tamper")),
        lambda wire: wire["row_commitments"][0].update(
            commitment="sha256:" + "0" * 64
        ),
        lambda wire: wire.update(pack_root="sha256:" + "1" * 64),
        lambda wire: wire["alias_order"].reverse(),
    ],
)
def test_commitment_tamper_is_rejected(mutator) -> None:
    _, commitment, _ = _artifacts()
    wire = json.loads(canonical_json_bytes(commitment))
    mutator(wire)
    with pytest.raises(ProtocolViolation):
        verify_commitment_bytes(canonical_json_bytes(wire))


def test_secret_and_reveal_tamper_cannot_open_commitment() -> None:
    secret, commitment, reveal = _artifacts()

    bad_secret = json.loads(canonical_json_bytes(secret))
    bad_secret["replicates"][4]["sealed_test_root_seed"] += 1
    with pytest.raises(ProtocolViolation, match="do not open"):
        verify_secret_bytes(canonical_json_bytes(bad_secret), commitment)

    bad_reveal = json.loads(canonical_json_bytes(reveal))
    bad_reveal["replicates"][0]["train_root_seed"] += 1
    with pytest.raises(ProtocolViolation, match="do not open"):
        verify_reveal_bytes(canonical_json_bytes(bad_reveal), commitment)

    bad_digest = json.loads(canonical_json_bytes(reveal))
    bad_digest["commitment_digest"] = "sha256:" + "f" * 64
    with pytest.raises(ProtocolViolation, match="commitment digest"):
        verify_reveal_bytes(canonical_json_bytes(bad_digest), commitment)


def test_noncanonical_and_duplicate_key_bytes_are_rejected() -> None:
    _, commitment, _ = _artifacts()
    pretty = json.dumps(commitment, indent=2, sort_keys=True).encode("utf-8")
    with pytest.raises(ProtocolViolation, match="canonical"):
        verify_commitment_bytes(pretty)

    duplicate = b'{"schema_version":"x","schema_version":"y"}\n'
    with pytest.raises(ProtocolViolation, match="duplicate key"):
        verify_commitment_bytes(duplicate)


@pytest.mark.parametrize("bad_seed", [-1, 2**63, True, 1.5, "12"])
def test_seed_rows_require_exact_63_bit_integers(bad_seed: object) -> None:
    rows = _rows()
    rows[0]["train_root_seed"] = bad_seed
    with pytest.raises(ProtocolViolation, match="63-bit seed"):
        build_secret(rows, candidate_source_digest=_candidate_digest())


def test_normalization_maps_c_aliases_but_cannot_masquerade_as_freeze_seeds() -> None:
    secret, commitment, reveal = _artifacts()

    execution, private_provenance = normalize_to_benchmark_v1_execution_secret(
        secret, commitment
    )
    assert execution["schema_version"] == SEED_SECRET_SCHEMA
    assert tuple(row["replicate_id"] for row in execution["replicates"]) == REPLICATE_IDS
    assert execution["replicates"][0]["train_root_seed"] == _rows()[0][
        "train_root_seed"
    ]
    assert private_provenance["purpose"] == "supplemental_postseal_confirm"
    assert private_provenance["supplemental_postseal_confirm"] is True
    assert private_provenance["original_freeze_seed_authority"] is False
    assert private_provenance["seed_preimages_published"] is False
    assert private_provenance["alias_mapping"] == [
        {"confirm_alias": alias, "runner_replicate_id": replicate_id}
        for alias, replicate_id in zip(CONFIRM_ALIASES, REPLICATE_IDS, strict=True)
    ]

    execution_from_reveal, public_provenance = (
        normalize_to_benchmark_v1_execution_secret(reveal, commitment)
    )
    assert execution_from_reveal == execution
    assert public_provenance["seed_preimages_published"] is True
    assert public_provenance["authority_kind"].endswith("public_reveal")


def test_issue_is_append_only_public_in_repo_private_outside_repo(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commitment_path = repo / "research" / "POSTSEAL_CONFIRM5.json"
    secret_path = tmp_path / "private" / "POSTSEAL_CONFIRM5.secret.json"

    commitment, secret = issue_postseal_confirm5(
        commitment_path,
        secret_path,
        candidate_source_digest=_candidate_digest(),
        repo_root=repo,
    )
    original_commitment = commitment_path.read_bytes()
    original_secret = secret_path.read_bytes()
    assert verify_commitment_bytes(original_commitment) == commitment
    assert verify_secret_bytes(original_secret, commitment) == secret

    with pytest.raises(ProtocolViolation, match="append-only"):
        issue_postseal_confirm5(
            commitment_path,
            secret_path,
            candidate_source_digest=_candidate_digest(),
            repo_root=repo,
        )
    assert commitment_path.read_bytes() == original_commitment
    assert secret_path.read_bytes() == original_secret

    with pytest.raises(ProtocolViolation, match="inside the repository"):
        issue_postseal_confirm5(
            tmp_path / "outside-commitment.json",
            tmp_path / "another-private.json",
            candidate_source_digest=_candidate_digest(),
            repo_root=repo,
        )
    with pytest.raises(ProtocolViolation, match="outside the repository"):
        issue_postseal_confirm5(
            repo / "new-commitment.json",
            repo / "private-secret.json",
            candidate_source_digest=_candidate_digest(),
            repo_root=repo,
        )


def test_reveal_writer_is_append_only(tmp_path) -> None:
    secret, commitment, _ = _artifacts()
    output = tmp_path / "reveal.json"
    reveal = write_reveal(output, secret, commitment)
    original = output.read_bytes()
    assert verify_reveal_bytes(original, commitment) == reveal
    with pytest.raises(ProtocolViolation, match="append-only"):
        write_reveal(output, secret, commitment)
    assert output.read_bytes() == original
