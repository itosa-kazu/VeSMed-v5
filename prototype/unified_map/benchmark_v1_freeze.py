"""Issue and verify the append-only executable UCM benchmark v1 freeze.

This issuer freezes the code that actually generates and scores W01--W20.  It
does not claim that the synthetic panel is clinically representative, that the
older formal-scope DSL is closed, or that any candidate has passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from .benchmark_v1_contract import (
    BENCHMARK_ID,
    SIGNATURE_DIMENSION,
    contract_digest,
    metric_contract_wire,
    oracle_signature,
)
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    domain_digest,
    validate_json_like,
)
from .world_registry import WORLD_REGISTRY
from .worlds.base import WorldSplit


FREEZE_SCHEMA = "ucm-executable-benchmark-freeze/1"
FREEZE_STATUS = "FROZEN-v1"
FREEZE_FILENAME = "research/unified_map/BENCHMARK_V1_FREEZE.json"
SEED_SECRET_SCHEMA = "ucm-benchmark-v1-seed-secret/1"
SEED_REVEAL_SCHEMA = "ucm-benchmark-v1-seed-reveal/1"
SOURCE_TREE_DOMAIN = b"UCM_EXECUTABLE_BENCHMARK_V1_SOURCE_TREE\0"
FREEZE_ROOT_DOMAIN = b"UCM_EXECUTABLE_BENCHMARK_V1_FREEZE_ROOT\0"
SEED_COMMITMENT_DOMAIN = b"UCM_EXECUTABLE_BENCHMARK_V1_SEED_COMMITMENT\0"

REPLICATE_IDS = tuple(f"R{index:02d}" for index in range(1, 6))
MODEL_SEEDS = (104729, 130363, 155921, 181081, 206369)
SPLIT_EPISODES_PER_PANEL = {
    "train": 32,
    "validation": 8,
    "sealed_test": 16,
}

_WORLD_SOURCE_PATHS = tuple(
    ["prototype/unified_map/worlds/__init__.py", "prototype/unified_map/worlds/base.py", "prototype/unified_map/worlds/randomness.py"]
    + [f"prototype/unified_map/worlds/w{index:02d}.py" for index in range(1, 21)]
)
FROZEN_SOURCE_PATHS = (
    "prototype/unified_map/benchmark_v1_contract.py",
    "prototype/unified_map/benchmark_v1_freeze.py",
    "prototype/unified_map/canonical.py",
    "prototype/unified_map/schema.py",
    "prototype/unified_map/world_registry.py",
    "prototype/unified_map/extensions.py",
    "prototype/unified_map/state.py",
    *_WORLD_SOURCE_PATHS,
    "research/unified_map/BENCHMARK_V1_SPEC.md",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_source_rows() -> tuple[dict[str, Any], ...]:
    root = _repo_root()
    rows: list[dict[str, Any]] = []
    if len(FROZEN_SOURCE_PATHS) != len(set(FROZEN_SOURCE_PATHS)):
        raise ProtocolViolation("frozen source paths are not unique")
    for relative in FROZEN_SOURCE_PATHS:
        path = root / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ProtocolViolation(f"frozen source is unreadable: {relative}") from exc
        rows.append(
            {
                "relative_path": relative,
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        )
    return tuple(rows)


def _source_tree_root(rows: tuple[dict[str, Any], ...]) -> str:
    return domain_digest(
        SOURCE_TREE_DOMAIN,
        tuple(canonical_json_bytes(row) for row in rows),
    )


def _runtime_panel_rows() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for world_slot, declaration in WORLD_REGISTRY.items():
        for panel in declaration.panels:
            world = panel.instantiate()
            episode = world.generate_episode(WorldSplit.TRAIN, 0x5EED, 0)
            horizon = world.catalog.horizons[0]
            policy = world.policy_set(horizon)[0]
            oracle = world.counterfactual(episode, policy, horizon, 0x0A11CE)
            canary = {
                "public_history_digest": episode.public_history.digest,
                "diagnostic_target": episode.diagnostic_target,
                "horizon": horizon,
                "policy": policy.to_wire(),
                "oracle_signature": list(oracle_signature(oracle)),
                "oracle_expected_utility": oracle.expected_utility,
            }
            rows.append(
                {
                    "world_slot": world_slot,
                    "panel_id": panel.panel_id,
                    "world_module": panel.module_name,
                    "world_class": panel.class_name,
                    "identification": panel.identification,
                    "catalog_digest": world.catalog.digest,
                    "catalog": world.catalog.to_wire(),
                    "horizons": list(world.catalog.horizons),
                    "split_sizes_available": {
                        split.value: panel.episode_count(split, world)
                        for split in WorldSplit
                    },
                    "freeze_canary_digest": digest_json(canary),
                }
            )
    identities = tuple((row["world_slot"], row["panel_id"]) for row in rows)
    expected = (
        *((f"W{index:02d}", "primary") for index in range(1, 15)),
        ("W15", "W15A-randomized-identifiable"),
        ("W15", "W15B-observational-nonidentified"),
        *((f"W{index:02d}", "primary") for index in range(16, 21)),
    )
    if identities != expected:
        raise ProtocolViolation("live W01-W20 panel identities drifted")
    return tuple(rows)


def _seed_commitment(record: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        SEED_COMMITMENT_DOMAIN + canonical_json_bytes(record)
    ).hexdigest()


def new_seed_secret() -> dict[str, Any]:
    rows = []
    for replicate_id in REPLICATE_IDS:
        rows.append(
            {
                "replicate_id": replicate_id,
                "train_root_seed": secrets.randbits(63),
                "validation_root_seed": secrets.randbits(63),
                "sealed_test_root_seed": secrets.randbits(63),
            }
        )
    return {
        "schema_version": SEED_SECRET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "replicates": rows,
    }


def _validate_seed_secret(secret: object) -> dict[str, Any]:
    if type(secret) is not dict:
        raise ProtocolViolation("seed secret must be an exact object")
    validate_json_like(secret, path="seed secret")
    if set(secret) != {"schema_version", "benchmark_id", "replicates"}:
        raise ProtocolViolation("seed secret has missing or extra fields")
    if (
        secret["schema_version"] != SEED_SECRET_SCHEMA
        or secret["benchmark_id"] != BENCHMARK_ID
        or type(secret["replicates"]) is not list
        or len(secret["replicates"]) != len(REPLICATE_IDS)
    ):
        raise ProtocolViolation("seed secret identity/cardinality drifted")
    for index, row in enumerate(secret["replicates"]):
        if type(row) is not dict or set(row) != {
            "replicate_id",
            "train_root_seed",
            "validation_root_seed",
            "sealed_test_root_seed",
        }:
            raise ProtocolViolation("seed replicate shape drifted")
        if row["replicate_id"] != REPLICATE_IDS[index] or any(
            type(row[key]) is not int or not 0 <= row[key] < 2**63
            for key in (
                "train_root_seed",
                "validation_root_seed",
                "sealed_test_root_seed",
            )
        ):
            raise ProtocolViolation("seed replicate value drifted")
    return secret


def _commitment_rows(secret: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "replicate_id": row["replicate_id"],
            "commitment": _seed_commitment(row),
        }
        for row in secret["replicates"]
    ]


def _freeze_preimage(secret: dict[str, Any]) -> dict[str, Any]:
    source_rows = _read_source_rows()
    panels = _runtime_panel_rows()
    metric_wire = metric_contract_wire()
    return {
        "schema_version": FREEZE_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "status": FREEZE_STATUS,
        "authority": "executable_world_oracle_metric_source_and_seed_commitment",
        "claim_boundary": {
            "synthetic_only": True,
            "clinical_validity_claimed": False,
            "candidate_result_claimed": False,
            "global_optimum_claimed": False,
            "older_formal_scope_dsl_is_freeze_authority": False,
        },
        "world_count": 20,
        "panel_count": 21,
        "world_panels": list(panels),
        "metric_contract": metric_wire,
        "metric_contract_digest": contract_digest(),
        "signature_dimension": SIGNATURE_DIMENSION,
        "split_protocol": {
            "replicate_ids": list(REPLICATE_IDS),
            "episodes_per_panel_per_replicate": dict(SPLIT_EPISODES_PER_PANEL),
            "model_seeds": list(MODEL_SEEDS),
            "complete_candidate_requires_all_replicates": True,
            "screening_subset_must_not_be_labelled_complete": True,
        },
        "seed_commitments": _commitment_rows(secret),
        "seed_reveal_status": "withheld_until_candidate_artifact_seal",
        "frozen_source_files": list(source_rows),
        "source_tree_root": _source_tree_root(source_rows),
        "change_rule": "any_frozen_byte_or_semantic_change_requires_new_benchmark_version",
    }


def build_freeze_manifest(secret: dict[str, Any]) -> dict[str, Any]:
    secret = _validate_seed_secret(secret)
    preimage = _freeze_preimage(secret)
    return {
        **preimage,
        "freeze_root": domain_digest(
            FREEZE_ROOT_DOMAIN,
            (canonical_json_bytes(preimage),),
        ),
    }


def _decode_canonical_object(payload: bytes, label: str) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation(f"{label} must be exact bytes")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
    except ProtocolViolation:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProtocolViolation(f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise ProtocolViolation(f"{label} is not canonical compact JSON plus LF")
    return value


def verify_freeze_manifest_bytes(payload: bytes) -> dict[str, Any]:
    """Verify immutable fields and live-rebuild every non-secret predecessor."""

    body = _decode_canonical_object(payload, "benchmark freeze manifest")
    expected_keys = set(_freeze_preimage(new_seed_secret())) | {"freeze_root"}
    if set(body) != expected_keys:
        raise ProtocolViolation("freeze manifest has missing or extra fields")
    if (
        body["schema_version"] != FREEZE_SCHEMA
        or body["benchmark_id"] != BENCHMARK_ID
        or body["status"] != FREEZE_STATUS
        or body["world_count"] != 20
        or body["panel_count"] != 21
        or body["metric_contract"] != metric_contract_wire()
        or body["metric_contract_digest"] != contract_digest()
        or body["world_panels"] != list(_runtime_panel_rows())
    ):
        raise ProtocolViolation("freeze manifest contradicts live benchmark semantics")
    source_rows = _read_source_rows()
    if (
        body["frozen_source_files"] != list(source_rows)
        or body["source_tree_root"] != _source_tree_root(source_rows)
    ):
        raise ProtocolViolation("frozen source bytes drifted")
    commitments = body["seed_commitments"]
    if (
        type(commitments) is not list
        or len(commitments) != len(REPLICATE_IDS)
        or tuple(row.get("replicate_id") for row in commitments) != REPLICATE_IDS
        or any(
            type(row) is not dict
            or set(row) != {"replicate_id", "commitment"}
            or type(row["commitment"]) is not str
            or len(row["commitment"]) != 71
            or not row["commitment"].startswith("sha256:")
            for row in commitments
        )
    ):
        raise ProtocolViolation("freeze seed commitments are malformed")
    preimage = {key: value for key, value in body.items() if key != "freeze_root"}
    expected_root = domain_digest(
        FREEZE_ROOT_DOMAIN,
        (canonical_json_bytes(preimage),),
    )
    if body["freeze_root"] != expected_root:
        raise ProtocolViolation("freeze root mismatch")
    return body


def build_seed_reveal(secret: dict[str, Any], freeze: dict[str, Any]) -> dict[str, Any]:
    secret = _validate_seed_secret(secret)
    commitments = _commitment_rows(secret)
    if commitments != freeze.get("seed_commitments"):
        raise ProtocolViolation("seed secret does not open the frozen commitments")
    return {
        "schema_version": SEED_REVEAL_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "freeze_root": freeze["freeze_root"],
        "replicates": secret["replicates"],
    }


def verify_seed_reveal(reveal: dict[str, Any], freeze: dict[str, Any]) -> None:
    if type(reveal) is not dict or set(reveal) != {
        "schema_version",
        "benchmark_id",
        "freeze_root",
        "replicates",
    }:
        raise ProtocolViolation("seed reveal has missing or extra fields")
    secret = {
        "schema_version": SEED_SECRET_SCHEMA,
        "benchmark_id": reveal.get("benchmark_id"),
        "replicates": reveal.get("replicates"),
    }
    _validate_seed_secret(secret)
    if (
        reveal["schema_version"] != SEED_REVEAL_SCHEMA
        or reveal["freeze_root"] != freeze.get("freeze_root")
        or _commitment_rows(secret) != freeze.get("seed_commitments")
    ):
        raise ProtocolViolation("seed reveal does not open this freeze")


def issue_freeze(output: Path, secret_path: Path) -> dict[str, Any]:
    if output.exists():
        raise ProtocolViolation("freeze output already exists; append-only policy")
    if secret_path.exists():
        secret = _decode_canonical_object(secret_path.read_bytes(), "seed secret")
    else:
        secret = new_seed_secret()
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_bytes(canonical_json_bytes(secret))
    manifest = build_freeze_manifest(secret)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(manifest))
    verify_freeze_manifest_bytes(output.read_bytes())
    return manifest


def _main() -> int:
    parser = argparse.ArgumentParser(description="Issue or verify UCM benchmark v1")
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--output", type=Path, default=_repo_root() / FREEZE_FILENAME)
    issue.add_argument("--secret", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--manifest", type=Path, default=_repo_root() / FREEZE_FILENAME)
    args = parser.parse_args()
    if args.command == "issue":
        manifest = issue_freeze(args.output, args.secret)
        print(json.dumps({"status": manifest["status"], "freeze_root": manifest["freeze_root"]}, sort_keys=True))
    else:
        manifest = verify_freeze_manifest_bytes(args.manifest.read_bytes())
        print(json.dumps({"status": manifest["status"], "freeze_root": manifest["freeze_root"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "BENCHMARK_ID",
    "FREEZE_FILENAME",
    "FREEZE_SCHEMA",
    "FREEZE_STATUS",
    "FROZEN_SOURCE_PATHS",
    "MODEL_SEEDS",
    "REPLICATE_IDS",
    "SEED_REVEAL_SCHEMA",
    "SEED_SECRET_SCHEMA",
    "SPLIT_EPISODES_PER_PANEL",
    "build_freeze_manifest",
    "build_seed_reveal",
    "issue_freeze",
    "new_seed_secret",
    "verify_freeze_manifest_bytes",
    "verify_seed_reveal",
]
