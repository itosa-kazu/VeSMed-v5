"""Commit/reveal authority for a supplemental post-seal CONFIRM5 pack.

This protocol is intentionally separate from the five seed commitments frozen
inside ``BENCHMARK_V1_FREEZE.json``.  It creates a new, unseen five-replicate
pack only after the candidate has a durable Git seal.  The adapter at the end
of this module maps public aliases C01--C05 to the legacy runner's internal
R01--R05 names, while returning provenance that forbids calling these seeds
the original frozen benchmark seeds.

The issue command is append-only.  Its public commitment must be written
inside the repository and its private preimages must be written outside the
repository.  No commitment is issued merely by importing this module.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
from pathlib import Path
from typing import Any

from .benchmark_v1_freeze import BENCHMARK_ID, REPLICATE_IDS, SEED_SECRET_SCHEMA
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    domain_digest,
    validate_json_like,
)


COMMITMENT_SCHEMA = "ucm-postseal-confirm5-commitment/1"
SECRET_SCHEMA = "ucm-postseal-confirm5-secret/1"
REVEAL_SCHEMA = "ucm-postseal-confirm5-reveal/1"
PURPOSE = "supplemental_postseal_confirm"
COMMITMENT_ARTIFACT_TYPE = "POSTSEAL_CONFIRM5_SEED_COMMITMENT"
SECRET_ARTIFACT_TYPE = "POSTSEAL_CONFIRM5_PRIVATE_SEED_SECRET"
REVEAL_ARTIFACT_TYPE = "POSTSEAL_CONFIRM5_PUBLIC_SEED_REVEAL"

# These two authorities are deliberately fixed in protocol code.  A different
# freeze or a different durable seal is a different protocol issuance.
FROZEN_FREEZE_ROOT = (
    "sha256:8acb6623c2fdf79008240c5f5967b2143c4fb5e7bb87a4e8aa9f72e77ef33a2d"
)
DURABLE_SEAL_COMMIT = "68dee722bd95ea8f61ba09d7e6a150f5e4191ab1"

CONFIRM_ALIASES = tuple(f"C{index:02d}" for index in range(1, 6))
SEED_FIELDS = (
    "train_root_seed",
    "validation_root_seed",
    "sealed_test_root_seed",
)
SEED_BITS = 63

ROW_COMMITMENT_DOMAIN = b"UCM-POSTSEAL-CONFIRM5-ROW-COMMITMENT-v1\0"
PACK_ROOT_DOMAIN = b"UCM-POSTSEAL-CONFIRM5-PACK-ROOT-v1\0"

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

_CONTEXT_KEYS = frozenset(
    {
        "benchmark_id",
        "candidate_source_digest",
        "durable_seal_commit",
        "freeze_root",
        "purpose",
    }
)
_SEED_ROW_KEYS = frozenset({"confirm_alias", *SEED_FIELDS})
_COMMITMENT_KEYS = frozenset(
    {
        "alias_order",
        "artifact_type",
        "benchmark_id",
        "candidate_source_digest",
        "durable_seal_commit",
        "freeze_root",
        "pack_root",
        "preimage_status",
        "purpose",
        "row_commitments",
        "schema_version",
        "seed_bits",
        "seed_fields",
    }
)
_SECRET_KEYS = frozenset(
    {
        "artifact_type",
        "benchmark_id",
        "candidate_source_digest",
        "durable_seal_commit",
        "freeze_root",
        "purpose",
        "replicates",
        "schema_version",
    }
)
_REVEAL_KEYS = frozenset(
    {
        "artifact_type",
        "benchmark_id",
        "candidate_source_digest",
        "commitment_digest",
        "durable_seal_commit",
        "freeze_root",
        "pack_root",
        "purpose",
        "replicates",
        "schema_version",
    }
)


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    actual = frozenset(value)
    if actual != expected:
        raise ProtocolViolation(
            f"{label} keys mismatch: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a lowercase sha256 digest")
    return value


def _decode_canonical_object(payload: bytes, label: str) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation(f"{label} payload must be exact bytes")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for key, value in pairs:
            if key in decoded:
                raise ProtocolViolation(f"{label} contains duplicate key {key!r}")
            decoded[key] = value
        return decoded

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
    except ProtocolViolation:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProtocolViolation(f"{label} is not valid JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise ProtocolViolation(f"{label} is not canonical compact JSON plus LF")
    validate_json_like(value, path=label)
    return value


def _validate_context(value: object, label: str) -> dict[str, Any]:
    context = _exact_keys(value, _CONTEXT_KEYS, label)
    if context["benchmark_id"] != BENCHMARK_ID:
        raise ProtocolViolation(f"{label} benchmark identity mismatch")
    if context["purpose"] != PURPOSE:
        raise ProtocolViolation(f"{label} purpose must be {PURPOSE!r}")
    if context["freeze_root"] != FROZEN_FREEZE_ROOT:
        raise ProtocolViolation(f"{label} freeze root mismatch")
    _digest(context["candidate_source_digest"], f"{label}.candidate_source_digest")
    if (
        type(context["durable_seal_commit"]) is not str
        or _GIT_COMMIT_RE.fullmatch(context["durable_seal_commit"]) is None
        or context["durable_seal_commit"] != DURABLE_SEAL_COMMIT
    ):
        raise ProtocolViolation(f"{label} durable seal commit mismatch")
    return context


def _context_from(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(_CONTEXT_KEYS)}


def _validate_seed_rows(rows: object, label: str) -> list[dict[str, Any]]:
    if type(rows) is not list or len(rows) != len(CONFIRM_ALIASES):
        raise ProtocolViolation(f"{label} must contain exactly five seed rows")
    for index, row_value in enumerate(rows):
        row = _exact_keys(row_value, _SEED_ROW_KEYS, f"{label}[{index}]")
        if row["confirm_alias"] != CONFIRM_ALIASES[index]:
            raise ProtocolViolation(f"{label} aliases must be C01--C05 in order")
        for field in SEED_FIELDS:
            seed = row[field]
            if type(seed) is not int or not 0 <= seed < 2**SEED_BITS:
                raise ProtocolViolation(
                    f"{label}[{index}].{field} must be an exact 63-bit seed"
                )
    return rows


def _row_preimage(context: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding": context,
        "confirm_alias": row["confirm_alias"],
        "sealed_test_root_seed": row["sealed_test_root_seed"],
        "train_root_seed": row["train_root_seed"],
        "validation_root_seed": row["validation_root_seed"],
    }


def _row_commitment(context: dict[str, Any], row: dict[str, Any]) -> str:
    return domain_digest(
        ROW_COMMITMENT_DOMAIN,
        (canonical_json_bytes(_row_preimage(context, row)),),
    )


def _pack_root(
    context: dict[str, Any], row_commitments: list[dict[str, str]]
) -> str:
    return domain_digest(
        PACK_ROOT_DOMAIN,
        (
            canonical_json_bytes(
                {
                    "alias_order": list(CONFIRM_ALIASES),
                    "binding": context,
                    "row_commitments": row_commitments,
                    "seed_bits": SEED_BITS,
                    "seed_fields": list(SEED_FIELDS),
                }
            ),
        ),
    )


def build_secret(
    replicates: list[dict[str, Any]], *, candidate_source_digest: str
) -> dict[str, Any]:
    """Build and validate private preimages from caller-supplied seed rows."""

    secret = {
        "schema_version": SECRET_SCHEMA,
        "artifact_type": SECRET_ARTIFACT_TYPE,
        "purpose": PURPOSE,
        "benchmark_id": BENCHMARK_ID,
        "freeze_root": FROZEN_FREEZE_ROOT,
        "candidate_source_digest": candidate_source_digest,
        "durable_seal_commit": DURABLE_SEAL_COMMIT,
        "replicates": replicates,
    }
    return _validate_secret(secret)


def new_secret(*, candidate_source_digest: str) -> dict[str, Any]:
    """Draw a fresh private five-row secret using OS cryptographic entropy."""

    rows = [
        {
            "confirm_alias": alias,
            "train_root_seed": secrets.randbits(SEED_BITS),
            "validation_root_seed": secrets.randbits(SEED_BITS),
            "sealed_test_root_seed": secrets.randbits(SEED_BITS),
        }
        for alias in CONFIRM_ALIASES
    ]
    return build_secret(rows, candidate_source_digest=candidate_source_digest)


def _validate_secret(value: object) -> dict[str, Any]:
    secret = _exact_keys(value, _SECRET_KEYS, "post-seal CONFIRM5 secret")
    if (
        secret["schema_version"] != SECRET_SCHEMA
        or secret["artifact_type"] != SECRET_ARTIFACT_TYPE
    ):
        raise ProtocolViolation("post-seal CONFIRM5 secret schema/type mismatch")
    _validate_context(_context_from(secret), "post-seal CONFIRM5 secret binding")
    _validate_seed_rows(secret["replicates"], "post-seal CONFIRM5 secret replicates")
    return secret


def build_commitment(secret: dict[str, Any]) -> dict[str, Any]:
    """Commit every secret row and the ordered pack under separate domains."""

    secret = _validate_secret(secret)
    context = _context_from(secret)
    row_commitments = [
        {
            "confirm_alias": row["confirm_alias"],
            "commitment": _row_commitment(context, row),
        }
        for row in secret["replicates"]
    ]
    commitment = {
        "schema_version": COMMITMENT_SCHEMA,
        "artifact_type": COMMITMENT_ARTIFACT_TYPE,
        "purpose": PURPOSE,
        "benchmark_id": BENCHMARK_ID,
        "freeze_root": context["freeze_root"],
        "candidate_source_digest": context["candidate_source_digest"],
        "durable_seal_commit": context["durable_seal_commit"],
        "alias_order": list(CONFIRM_ALIASES),
        "seed_fields": list(SEED_FIELDS),
        "seed_bits": SEED_BITS,
        "row_commitments": row_commitments,
        "pack_root": _pack_root(context, row_commitments),
        "preimage_status": "withheld",
    }
    return _validate_commitment(commitment)


def _validate_commitment(value: object) -> dict[str, Any]:
    commitment = _exact_keys(
        value, _COMMITMENT_KEYS, "post-seal CONFIRM5 commitment"
    )
    if (
        commitment["schema_version"] != COMMITMENT_SCHEMA
        or commitment["artifact_type"] != COMMITMENT_ARTIFACT_TYPE
        or commitment["preimage_status"] != "withheld"
    ):
        raise ProtocolViolation("post-seal CONFIRM5 commitment schema/type mismatch")
    context = _validate_context(
        _context_from(commitment), "post-seal CONFIRM5 commitment binding"
    )
    if commitment["alias_order"] != list(CONFIRM_ALIASES):
        raise ProtocolViolation("post-seal CONFIRM5 alias order mismatch")
    if commitment["seed_fields"] != list(SEED_FIELDS) or commitment["seed_bits"] != SEED_BITS:
        raise ProtocolViolation("post-seal CONFIRM5 seed semantics mismatch")
    rows = commitment["row_commitments"]
    if type(rows) is not list or len(rows) != len(CONFIRM_ALIASES):
        raise ProtocolViolation("post-seal CONFIRM5 must carry five row commitments")
    for index, row in enumerate(rows):
        row = _exact_keys(
            row,
            frozenset({"confirm_alias", "commitment"}),
            f"post-seal CONFIRM5 row commitment {index}",
        )
        if row["confirm_alias"] != CONFIRM_ALIASES[index]:
            raise ProtocolViolation("post-seal CONFIRM5 row commitment order mismatch")
        _digest(row["commitment"], f"post-seal CONFIRM5 row commitment {index}")
    expected_root = _pack_root(context, rows)
    if commitment["pack_root"] != expected_root:
        raise ProtocolViolation("post-seal CONFIRM5 pack root mismatch")
    return commitment


def verify_commitment_bytes(payload: bytes) -> dict[str, Any]:
    """Verify canonical bytes and every context/pack-level public binding."""

    return _validate_commitment(
        _decode_canonical_object(payload, "post-seal CONFIRM5 commitment")
    )


def commitment_digest(commitment: dict[str, Any]) -> str:
    return digest_bytes(canonical_json_bytes(_validate_commitment(commitment)))


def _verify_opening(
    secret: dict[str, Any], commitment: dict[str, Any]
) -> dict[str, Any]:
    secret = _validate_secret(secret)
    commitment = _validate_commitment(commitment)
    if _context_from(secret) != _context_from(commitment):
        raise ProtocolViolation("post-seal CONFIRM5 opening context mismatch")
    expected_rows = [
        {
            "confirm_alias": row["confirm_alias"],
            "commitment": _row_commitment(_context_from(secret), row),
        }
        for row in secret["replicates"]
    ]
    if commitment["row_commitments"] != expected_rows:
        raise ProtocolViolation("post-seal CONFIRM5 seed preimages do not open commitment")
    if commitment["pack_root"] != _pack_root(_context_from(secret), expected_rows):
        raise ProtocolViolation("post-seal CONFIRM5 opening pack root mismatch")
    return secret


def verify_secret_bytes(
    payload: bytes, commitment: dict[str, Any]
) -> dict[str, Any]:
    """Verify canonical private bytes and that all five rows open commitment."""

    secret = _decode_canonical_object(payload, "post-seal CONFIRM5 secret")
    return _verify_opening(secret, commitment)


def build_reveal(
    secret: dict[str, Any], commitment: dict[str, Any]
) -> dict[str, Any]:
    """Build a public reveal only after verifying the private opening."""

    secret = _verify_opening(secret, commitment)
    reveal = {
        "schema_version": REVEAL_SCHEMA,
        "artifact_type": REVEAL_ARTIFACT_TYPE,
        "purpose": PURPOSE,
        "benchmark_id": BENCHMARK_ID,
        "freeze_root": secret["freeze_root"],
        "candidate_source_digest": secret["candidate_source_digest"],
        "durable_seal_commit": secret["durable_seal_commit"],
        "commitment_digest": commitment_digest(commitment),
        "pack_root": commitment["pack_root"],
        "replicates": secret["replicates"],
    }
    return _validate_reveal(reveal, commitment)


def _validate_reveal(
    value: object, commitment: dict[str, Any]
) -> dict[str, Any]:
    reveal = _exact_keys(value, _REVEAL_KEYS, "post-seal CONFIRM5 reveal")
    commitment = _validate_commitment(commitment)
    if (
        reveal["schema_version"] != REVEAL_SCHEMA
        or reveal["artifact_type"] != REVEAL_ARTIFACT_TYPE
    ):
        raise ProtocolViolation("post-seal CONFIRM5 reveal schema/type mismatch")
    _validate_context(_context_from(reveal), "post-seal CONFIRM5 reveal binding")
    _validate_seed_rows(reveal["replicates"], "post-seal CONFIRM5 reveal replicates")
    _digest(reveal["commitment_digest"], "post-seal CONFIRM5 reveal commitment_digest")
    if reveal["commitment_digest"] != commitment_digest(commitment):
        raise ProtocolViolation("post-seal CONFIRM5 reveal commitment digest mismatch")
    if reveal["pack_root"] != commitment["pack_root"]:
        raise ProtocolViolation("post-seal CONFIRM5 reveal pack root mismatch")
    as_secret = {
        "schema_version": SECRET_SCHEMA,
        "artifact_type": SECRET_ARTIFACT_TYPE,
        "purpose": reveal["purpose"],
        "benchmark_id": reveal["benchmark_id"],
        "freeze_root": reveal["freeze_root"],
        "candidate_source_digest": reveal["candidate_source_digest"],
        "durable_seal_commit": reveal["durable_seal_commit"],
        "replicates": reveal["replicates"],
    }
    _verify_opening(as_secret, commitment)
    return reveal


def verify_reveal_bytes(
    payload: bytes, commitment: dict[str, Any]
) -> dict[str, Any]:
    """Verify canonical public reveal bytes and all committed preimages."""

    reveal = _decode_canonical_object(payload, "post-seal CONFIRM5 reveal")
    return _validate_reveal(reveal, commitment)


def normalize_to_benchmark_v1_execution_secret(
    authority: dict[str, Any], commitment: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map C01--C05 to runner R01--R05 and return non-ambiguous provenance.

    The normalized first value intentionally has the legacy runner's private
    shape.  It is an in-memory compatibility object, not evidence that these
    seeds open ``BENCHMARK_V1_FREEZE.json``.  The mandatory provenance return
    records that distinction.
    """

    commitment = _validate_commitment(commitment)
    schema = authority.get("schema_version") if type(authority) is dict else None
    if schema == SECRET_SCHEMA:
        secret = _verify_opening(authority, commitment)
        authority_kind = "supplemental_postseal_confirm_private_secret"
        published = False
    elif schema == REVEAL_SCHEMA:
        reveal = _validate_reveal(authority, commitment)
        secret = {
            "schema_version": SECRET_SCHEMA,
            "artifact_type": SECRET_ARTIFACT_TYPE,
            "purpose": reveal["purpose"],
            "benchmark_id": reveal["benchmark_id"],
            "freeze_root": reveal["freeze_root"],
            "candidate_source_digest": reveal["candidate_source_digest"],
            "durable_seal_commit": reveal["durable_seal_commit"],
            "replicates": reveal["replicates"],
        }
        authority_kind = "supplemental_postseal_confirm_public_reveal"
        published = True
    else:
        raise ProtocolViolation("post-seal CONFIRM5 authority schema mismatch")

    mapping = [
        {"confirm_alias": alias, "runner_replicate_id": replicate_id}
        for alias, replicate_id in zip(CONFIRM_ALIASES, REPLICATE_IDS, strict=True)
    ]
    execution_secret = {
        "schema_version": SEED_SECRET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "replicates": [
            {
                "replicate_id": replicate_id,
                **{field: row[field] for field in SEED_FIELDS},
            }
            for replicate_id, row in zip(
                REPLICATE_IDS, secret["replicates"], strict=True
            )
        ],
    }
    provenance = {
        "authority_kind": authority_kind,
        "authority_schema_version": schema,
        "purpose": PURPOSE,
        "supplemental_postseal_confirm": True,
        "original_freeze_seed_authority": False,
        "seed_preimages_published": published,
        "freeze_root": commitment["freeze_root"],
        "candidate_source_digest": commitment["candidate_source_digest"],
        "durable_seal_commit": commitment["durable_seal_commit"],
        "commitment_digest": commitment_digest(commitment),
        "pack_root": commitment["pack_root"],
        "alias_mapping": mapping,
    }
    return execution_secret, provenance


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _exclusive_write(path: Path, payload: bytes, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise ProtocolViolation(f"{label} already exists; append-only policy") from exc


def issue_postseal_confirm5(
    commitment_path: Path,
    secret_path: Path,
    *,
    candidate_source_digest: str,
    repo_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Issue public commitments in-repo and private preimages out-of-repo."""

    repo_root = (repo_root or _repo_root()).resolve()
    if not _is_within(commitment_path, repo_root):
        raise ProtocolViolation("commitment output must be inside the repository")
    if _is_within(secret_path, repo_root):
        raise ProtocolViolation("private secret output must be outside the repository")
    if commitment_path.resolve() == secret_path.resolve():
        raise ProtocolViolation("commitment and private secret paths must differ")
    if commitment_path.exists() or secret_path.exists():
        raise ProtocolViolation("issue output already exists; append-only policy")

    secret = new_secret(candidate_source_digest=candidate_source_digest)
    commitment = build_commitment(secret)
    secret_written = False
    try:
        _exclusive_write(
            secret_path,
            canonical_json_bytes(secret),
            "post-seal CONFIRM5 private secret",
        )
        secret_written = True
        _exclusive_write(
            commitment_path,
            canonical_json_bytes(commitment),
            "post-seal CONFIRM5 commitment",
        )
    except Exception:
        # Best-effort transactional rollback applies only to the file created by
        # this failed call.  Existing artifacts are never removed or replaced.
        if secret_written and not commitment_path.exists():
            try:
                secret_path.unlink()
            except OSError:
                pass
        raise

    verify_commitment_bytes(commitment_path.read_bytes())
    verify_secret_bytes(secret_path.read_bytes(), commitment)
    return commitment, secret


def write_reveal(
    output: Path,
    secret: dict[str, Any],
    commitment: dict[str, Any],
) -> dict[str, Any]:
    """Write a canonical reveal without replacing an existing artifact."""

    reveal = build_reveal(secret, commitment)
    _exclusive_write(
        output, canonical_json_bytes(reveal), "post-seal CONFIRM5 reveal"
    )
    verify_reveal_bytes(output.read_bytes(), commitment)
    return reveal


def _read_canonical(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(f"{label} is unavailable") from exc
    return _decode_canonical_object(payload, label)


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Issue or verify supplemental post-seal CONFIRM5 seeds"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue")
    issue.add_argument("--commitment", type=Path, required=True)
    issue.add_argument("--secret", type=Path, required=True)
    issue.add_argument("--candidate-source-digest", required=True)
    issue.add_argument("--repo-root", type=Path, default=_repo_root())

    verify_commitment = sub.add_parser("verify-commitment")
    verify_commitment.add_argument("--commitment", type=Path, required=True)

    verify_secret = sub.add_parser("verify-secret")
    verify_secret.add_argument("--commitment", type=Path, required=True)
    verify_secret.add_argument("--secret", type=Path, required=True)

    reveal = sub.add_parser("reveal")
    reveal.add_argument("--commitment", type=Path, required=True)
    reveal.add_argument("--secret", type=Path, required=True)
    reveal.add_argument("--output", type=Path, required=True)

    verify_reveal = sub.add_parser("verify-reveal")
    verify_reveal.add_argument("--commitment", type=Path, required=True)
    verify_reveal.add_argument("--reveal", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "issue":
        commitment, _ = issue_postseal_confirm5(
            args.commitment,
            args.secret,
            candidate_source_digest=args.candidate_source_digest,
            repo_root=args.repo_root,
        )
        result = {
            "schema_version": commitment["schema_version"],
            "purpose": commitment["purpose"],
            "commitment_digest": commitment_digest(commitment),
            "pack_root": commitment["pack_root"],
            "preimages_published": False,
        }
    else:
        commitment = verify_commitment_bytes(args.commitment.read_bytes())
        if args.command == "verify-commitment":
            result = {
                "schema_version": commitment["schema_version"],
                "commitment_digest": commitment_digest(commitment),
                "pack_root": commitment["pack_root"],
            }
        elif args.command == "verify-secret":
            secret = verify_secret_bytes(args.secret.read_bytes(), commitment)
            result = {
                "schema_version": secret["schema_version"],
                "commitment_digest": commitment_digest(commitment),
                "opening_verified": True,
                "preimages_published": False,
            }
        elif args.command == "reveal":
            secret = verify_secret_bytes(args.secret.read_bytes(), commitment)
            public = write_reveal(args.output, secret, commitment)
            result = {
                "schema_version": public["schema_version"],
                "commitment_digest": public["commitment_digest"],
                "opening_verified": True,
                "preimages_published": True,
            }
        else:
            public = verify_reveal_bytes(args.reveal.read_bytes(), commitment)
            result = {
                "schema_version": public["schema_version"],
                "commitment_digest": public["commitment_digest"],
                "opening_verified": True,
                "preimages_published": True,
            }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "COMMITMENT_SCHEMA",
    "CONFIRM_ALIASES",
    "DURABLE_SEAL_COMMIT",
    "FROZEN_FREEZE_ROOT",
    "PURPOSE",
    "REVEAL_SCHEMA",
    "SECRET_SCHEMA",
    "SEED_BITS",
    "SEED_FIELDS",
    "build_commitment",
    "build_reveal",
    "build_secret",
    "commitment_digest",
    "issue_postseal_confirm5",
    "new_secret",
    "normalize_to_benchmark_v1_execution_secret",
    "verify_commitment_bytes",
    "verify_reveal_bytes",
    "verify_secret_bytes",
    "write_reveal",
]
