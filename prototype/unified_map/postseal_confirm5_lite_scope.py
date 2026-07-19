"""Canonical custody scope for the all-world CONFIRM5 lite batch.

The verifier deliberately performs only canonical-metadata and streaming-digest
checks.  It does not replay metrics, open private seed material, or read a
public reveal.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from .postseal_confirm5 import commitment_digest, verify_commitment_bytes


PROTOCOL = "ucm-postseal-confirm5-lite-scope/1"
SCOPE_CLASS = "supplemental_all_world_lite"
AMENDMENT_PROTOCOL = "ucm-redteam-v2-evaluator-amendment/1"
AMENDMENT_GIT_COMMIT = "1538a4c0e30e827caf178075bcb214109565bcdc"

COMMITMENT_PATH = "research/unified_map/POSTSEAL_CONFIRM5_COMMITMENT.json"
CANDIDATE_SET_PATH = "research/unified_map/POSTSEAL_CANDIDATE_SET.json"
AMENDMENT_PATH = "research/unified_map/REDTEAM_V2_EVALUATOR_AMENDMENT.json"

CONFIRM_SOURCE_PATHS = (
    "prototype/unified_map/baselines_v2.py",
    "prototype/unified_map/benchmark_v1_runner.py",
    "prototype/unified_map/candidate_families.py",
    "prototype/unified_map/postseal_confirm5.py",
    "prototype/unified_map/postseal_confirm5_runner.py",
)
SUPERSEDED_REDTEAM_EVALUATOR_PATHS = (
    "prototype/unified_map/redteam_v2_adapter.py",
    "prototype/unified_map/redteam_v2_runner.py",
)
EXPECTED_CANDIDATE_ORDER = ("F10", "F14", "F18", "B02V2", "B03V2")
EXPECTED_ALIASES = ("C01", "C02", "C03", "C04", "C05")
EXPECTED_WORLD_SLOTS = tuple(f"W{index:02d}" for index in range(1, 21))
EXPECTED_CONFIG = {
    "candidate_order": list(EXPECTED_CANDIDATE_ORDER),
    "complete_benchmark": False,
    "confirm_aliases": list(EXPECTED_ALIASES),
    "pair_probe_limit_per_declaration": 0,
    "test_episodes_per_panel": 2,
    "train_episodes_per_panel": 4,
    "validation_episodes_per_panel": 1,
    "world_slots": list(EXPECTED_WORLD_SLOTS),
}

# Operator-observed chronology that cannot be reconstructed from the finalized
# batch alone.  A prior full-size invocation loaded the private seed authority
# and was terminated before publishing a bundle.  Preserve that failed attempt
# explicitly instead of making the stronger (and false) "consumed once" claim.
EXECUTION_DISCLOSURE = {
    "finalized_batch_count_for_pack": 1,
    "prior_unfinalized_execution_attempt": True,
    "private_seed_material_loaded_by_prior_attempt": True,
    "machine_reverified_from_finalized_batch": False,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_canonical_object(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} is unavailable or invalid") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    return raw, value


def _safe_repo_relative(repo: Path, path: Path, label: str) -> str:
    try:
        relative = path.resolve(strict=True).relative_to(repo).as_posix()
    except (OSError, ValueError) as exc:
        raise ProtocolViolation(f"{label} must be inside the repository") from exc
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise ProtocolViolation(f"{label} escapes the repository")
    return relative


def _git_show(repo: Path, commit: str, relative: str) -> bytes:
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
        raise ProtocolViolation("Git binding must use a full lowercase object id")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise ProtocolViolation("Git-bound path escapes the repository")
    completed = subprocess.run(
        ["git", "show", f"{commit}:{pure.as_posix()}"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        raise ProtocolViolation(f"Git-bound blob is unavailable: {relative}")
    return completed.stdout


def _require_ancestor(repo: Path, ancestor: str, descendant: str, label: str) -> None:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        raise ProtocolViolation(f"{label} is not an ancestor-or-equal relation")


def _candidate_set_binding(repo: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw, candidate_set = _read_canonical_object(
        repo / CANDIDATE_SET_PATH, "post-seal candidate-set seal"
    )
    required = {
        "protocol",
        "status",
        "freeze_root",
        "primary_candidate_seal_digest",
        "primary_seal_commit",
        "prepack_source_commit",
        "subjects",
        "source_binding",
        "mutation_rule",
        "seal_root",
    }
    if set(candidate_set) != required or candidate_set["protocol"] != (
        "ucm-postseal-candidate-set/1"
    ):
        raise ProtocolViolation("candidate-set seal schema mismatch")
    preimage = {
        key: value for key, value in candidate_set.items() if key != "seal_root"
    }
    if candidate_set["seal_root"] != digest_json(preimage):
        raise ProtocolViolation("candidate-set seal root mismatch")
    source_binding = candidate_set.get("source_binding")
    if type(source_binding) is not dict or set(source_binding) != {
        "files",
        "source_digest",
    }:
        raise ProtocolViolation("candidate-set source binding mismatch")
    rows = source_binding["files"]
    if type(rows) is not list or source_binding["source_digest"] != digest_json(rows):
        raise ProtocolViolation("candidate-set source digest mismatch")

    prepack_commit = candidate_set["prepack_source_commit"]
    row_by_path: dict[str, dict[str, Any]] = {}
    drifted: list[str] = []
    for row in rows:
        if type(row) is not dict or set(row) != {
            "relative_path",
            "byte_length",
            "sha256",
        }:
            raise ProtocolViolation("candidate-set source row mismatch")
        relative = row["relative_path"]
        if type(relative) is not str or relative in row_by_path:
            raise ProtocolViolation(
                "candidate-set source paths are invalid or duplicated"
            )
        prepack_blob = _git_show(repo, prepack_commit, relative)
        if row != {
            "relative_path": relative,
            "byte_length": len(prepack_blob),
            "sha256": digest_bytes(prepack_blob),
        }:
            raise ProtocolViolation(
                f"candidate-set prepack receipt mismatch: {relative}"
            )
        row_by_path[relative] = row
        live_path = repo / Path(*PurePosixPath(relative).parts)
        try:
            live_blob = live_path.read_bytes()
        except OSError as exc:
            raise ProtocolViolation(
                f"candidate-set live source unavailable: {relative}"
            ) from exc
        if live_blob != prepack_blob:
            drifted.append(relative)

    if tuple(sorted(drifted)) != tuple(sorted(SUPERSEDED_REDTEAM_EVALUATOR_PATHS)):
        raise ProtocolViolation(
            "candidate-set live drift is not limited to the amended red-team evaluator"
        )
    try:
        confirm_rows = [row_by_path[path] for path in CONFIRM_SOURCE_PATHS]
    except KeyError as exc:
        raise ProtocolViolation(
            "candidate-set seal lacks a CONFIRM-relevant source"
        ) from exc
    for row in confirm_rows:
        relative = row["relative_path"]
        if (repo / relative).read_bytes() != _git_show(repo, prepack_commit, relative):
            raise ProtocolViolation(f"CONFIRM-relevant source drifted: {relative}")

    binding = {
        "path": CANDIDATE_SET_PATH,
        "sha256": digest_bytes(raw),
        "protocol": candidate_set["protocol"],
        "seal_root": candidate_set["seal_root"],
        "prepack_source_commit": prepack_commit,
    }
    return binding, confirm_rows


def _amendment_binding(repo: Path, prepack_commit: str) -> dict[str, Any]:
    raw, amendment = _read_canonical_object(
        repo / AMENDMENT_PATH, "red-team evaluator amendment"
    )
    if _git_show(repo, AMENDMENT_GIT_COMMIT, AMENDMENT_PATH) != raw:
        raise ProtocolViolation("live amendment differs from its committed Git blob")
    required = {
        "protocol",
        "original_commitment_digest",
        "original_pack_digest",
        "commitment_git_commit",
        "prepack_bindings",
        "final_protocol_source_bindings",
        "declarations",
    }
    if set(amendment) != required or amendment["protocol"] != AMENDMENT_PROTOCOL:
        raise ProtocolViolation("red-team evaluator amendment schema mismatch")
    expected_declarations = {
        "candidate_sources_changed": False,
        "generator_source_changed": False,
        "pack_digest_changed": False,
        "private_reveal_accessed_for_amendment": False,
        "scope": "evaluator_observability_custody_and_verification_only",
    }
    if amendment["declarations"] != expected_declarations:
        raise ProtocolViolation("red-team evaluator amendment scope changed")
    prepack = amendment.get("prepack_bindings")
    if (
        type(prepack) is not dict
        or prepack.get("pre_pack_git_commit") != prepack_commit
    ):
        raise ProtocolViolation("red-team amendment prepack commit mismatch")

    expected_labels = {"adapter", "runner"}
    prepack_protocol = prepack.get("protocol_source_bindings")
    final_protocol = amendment.get("final_protocol_source_bindings")
    if (
        type(prepack_protocol) is not dict
        or set(prepack_protocol) != expected_labels
        or type(final_protocol) is not dict
        or set(final_protocol) != expected_labels
    ):
        raise ProtocolViolation("red-team evaluator amendment source registry mismatch")
    for label, relative in zip(
        ("adapter", "runner"), SUPERSEDED_REDTEAM_EVALUATOR_PATHS, strict=True
    ):
        old_blob = _git_show(repo, prepack_commit, relative)
        if prepack_protocol[label] != {
            "path": relative,
            "byte_length": len(old_blob),
            "sha256": digest_bytes(old_blob),
        }:
            raise ProtocolViolation(f"amendment changed prepack {label} binding")
        amended_blob = _git_show(repo, AMENDMENT_GIT_COMMIT, relative)
        expected_final = {
            "path": relative,
            "byte_length": len(amended_blob),
            "sha256": digest_bytes(amended_blob),
        }
        if final_protocol[label] != expected_final:
            raise ProtocolViolation(f"amendment final {label} binding mismatch")
        if (repo / relative).read_bytes() != amended_blob:
            raise ProtocolViolation(
                f"live red-team {label} differs from amendment commit"
            )

    changed = subprocess.run(
        [
            "git",
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            AMENDMENT_GIT_COMMIT,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if changed != [AMENDMENT_PATH]:
        raise ProtocolViolation("amendment Git commit is not amendment-file-only")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _require_ancestor(
        repo, prepack_commit, AMENDMENT_GIT_COMMIT, "prepack to amendment"
    )
    _require_ancestor(repo, AMENDMENT_GIT_COMMIT, head, "amendment to current HEAD")
    return {
        "path": AMENDMENT_PATH,
        "sha256": digest_bytes(raw),
        "protocol": AMENDMENT_PROTOCOL,
        "git_commit": AMENDMENT_GIT_COMMIT,
        "scope": "redteam_evaluator_only",
    }


def _stream_gzip_receipt(path: Path) -> tuple[int, str]:
    length = 0
    digest = hashlib.sha256()
    try:
        with gzip.open(path, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                length += len(chunk)
                digest.update(chunk)
    except (OSError, EOFError) as exc:
        raise ProtocolViolation(f"gzip artifact is invalid: {path.name}") from exc
    return length, "sha256:" + digest.hexdigest()


def _verify_child_custody(batch_dir: Path, row: dict[str, Any]) -> None:
    relative = row.get("relative_path")
    if type(relative) is not str:
        raise ProtocolViolation("CONFIRM5 child relative path is invalid")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise ProtocolViolation("CONFIRM5 child path escapes the batch")
    child = batch_dir / Path(*pure.parts)
    manifest_raw, manifest = _read_canonical_object(
        child / "manifest.json", "CONFIRM5 child manifest"
    )
    if digest_bytes(manifest_raw) != row.get("manifest_sha256"):
        raise ProtocolViolation("CONFIRM5 child manifest digest mismatch")
    bundle_preimage = {
        key: value for key, value in manifest.items() if key != "bundle_root"
    }
    if (
        manifest.get("bundle_root") != digest_json(bundle_preimage)
        or manifest.get("bundle_root") != row.get("bundle_root")
        or manifest.get("run_id") != row.get("run_id")
    ):
        raise ProtocolViolation("CONFIRM5 child bundle custody mismatch")
    files = manifest.get("files")
    if type(files) is not list or [item.get("name") for item in files] != [
        "raw-episodes.jsonl",
        "raw-pairs.jsonl",
        "summary.json",
    ]:
        raise ProtocolViolation("CONFIRM5 child file registry mismatch")
    for item in files:
        name = item["name"]
        if name.endswith(".jsonl"):
            if (child / name).exists() or not (child / f"{name}.gz").is_file():
                raise ProtocolViolation("CONFIRM5 child is not gzip-only")
            byte_length, sha256 = _stream_gzip_receipt(child / f"{name}.gz")
        else:
            payload = (child / name).read_bytes()
            byte_length, sha256 = len(payload), digest_bytes(payload)
        if (byte_length, sha256) != (item.get("byte_length"), item.get("sha256")):
            raise ProtocolViolation(f"CONFIRM5 child artifact digest mismatch: {name}")
    if files[1]["byte_length"] != 0:
        raise ProtocolViolation(
            "pair-probe-free lite child unexpectedly contains pair rows"
        )


def _batch_binding(
    repo: Path, batch_dir: Path, commitment: dict[str, Any]
) -> dict[str, Any]:
    relative = _safe_repo_relative(repo, batch_dir, "CONFIRM5 lite batch")
    manifest_raw, manifest = _read_canonical_object(
        batch_dir / "batch-manifest.json", "CONFIRM5 lite batch manifest"
    )
    if manifest.get("protocol") != "ucm-postseal-confirm5-batch-manifest/1":
        raise ProtocolViolation("CONFIRM5 lite batch protocol mismatch")
    expected_root = digest_json(
        {key: value for key, value in manifest.items() if key != "batch_root"}
    )
    if manifest.get("batch_root") != expected_root:
        raise ProtocolViolation("CONFIRM5 lite batch root mismatch")
    if manifest.get("config") != EXPECTED_CONFIG:
        raise ProtocolViolation(
            "CONFIRM5 lite batch config is not the frozen lite scope"
        )
    if (
        manifest.get("purpose") != "supplemental_postseal_confirm"
        or manifest.get("commitment_digest") != commitment_digest(commitment)
        or manifest.get("pack_root") != commitment["pack_root"]
        or manifest.get("candidate_source_digest")
        != commitment["candidate_source_digest"]
        or manifest.get("freeze_root") != commitment["freeze_root"]
        or manifest.get("durable_seal_commit") != commitment["durable_seal_commit"]
        or manifest.get("confirm_aliases") != list(EXPECTED_ALIASES)
    ):
        raise ProtocolViolation("CONFIRM5 lite batch authority binding mismatch")
    children = manifest.get("children")
    if type(children) is not list or len(children) != len(EXPECTED_CANDIDATE_ORDER):
        raise ProtocolViolation("CONFIRM5 lite batch child cardinality mismatch")
    if [row.get("family_code") for row in children] != list(EXPECTED_CANDIDATE_ORDER):
        raise ProtocolViolation("CONFIRM5 lite child order mismatch")
    for row in children:
        _verify_child_custody(batch_dir, row)
    return {
        "relative_path": relative,
        "manifest_sha256": digest_bytes(manifest_raw),
        "batch_id": manifest["batch_id"],
        "batch_root": manifest["batch_root"],
        "config": manifest["config"],
        "children": children,
        "gzip_only_verified": True,
        "verification_profile": "metadata_and_streaming_digest_no_metric_recomputation",
    }


def build_lite_scope(
    *, batch_dir: Path, repo_root: Path | None = None
) -> dict[str, Any]:
    """Build the exact canonical scope receipt without opening seed authority."""

    repo = (repo_root or _repo_root()).resolve(strict=True)
    commitment_raw = (repo / COMMITMENT_PATH).read_bytes()
    commitment = verify_commitment_bytes(commitment_raw)
    candidate_set_binding, confirm_rows = _candidate_set_binding(repo)
    prepack_commit = candidate_set_binding["prepack_source_commit"]
    amendment_binding = _amendment_binding(repo, prepack_commit)
    preimage = {
        "protocol": PROTOCOL,
        "scope_class": SCOPE_CLASS,
        "complete_benchmark": False,
        "no_pair_collision_evidence": True,
        "execution_disclosure": EXECUTION_DISCLOSURE,
        "commitment_binding": {
            "path": COMMITMENT_PATH,
            "sha256": digest_bytes(commitment_raw),
            "schema_version": commitment["schema_version"],
            "commitment_digest": commitment_digest(commitment),
            "pack_root": commitment["pack_root"],
            "candidate_source_digest": commitment["candidate_source_digest"],
            "durable_seal_commit": commitment["durable_seal_commit"],
        },
        "candidate_set_binding": candidate_set_binding,
        "confirm_source_binding": {
            "prepack_source_commit": prepack_commit,
            "files": confirm_rows,
            "source_digest": digest_json(confirm_rows),
            "live_bytes_equal_prepack_git_blobs": True,
            "candidate_baseline_confirm_sources_unchanged": True,
        },
        "full_candidate_set_live_verifier": {
            "status": "SUPERSEDED_ONLY_FOR_REDTEAM_EVALUATOR_SOURCES",
            "superseded_paths": list(SUPERSEDED_REDTEAM_EVALUATOR_PATHS),
            "superseding_amendment_path": AMENDMENT_PATH,
            "superseding_amendment_git_commit": AMENDMENT_GIT_COMMIT,
            "confirm_scope_requires_evaluator_supersession": False,
        },
        "evaluator_amendment_binding": amendment_binding,
        "batch_binding": _batch_binding(
            repo, batch_dir.resolve(strict=True), commitment
        ),
    }
    return {**preimage, "scope_root": digest_json(preimage)}


def verify_lite_scope_bytes(
    payload: bytes, *, repo_root: Path | None = None
) -> dict[str, Any]:
    """Verify the published scope and its exact batch/source custody bindings."""

    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("CONFIRM5 lite scope is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise ProtocolViolation("CONFIRM5 lite scope is not canonical JSON")
    required = {
        "protocol",
        "scope_class",
        "complete_benchmark",
        "no_pair_collision_evidence",
        "execution_disclosure",
        "commitment_binding",
        "candidate_set_binding",
        "confirm_source_binding",
        "full_candidate_set_live_verifier",
        "evaluator_amendment_binding",
        "batch_binding",
        "scope_root",
    }
    if set(value) != required or value["protocol"] != PROTOCOL:
        raise ProtocolViolation("CONFIRM5 lite scope schema mismatch")
    preimage = {key: item for key, item in value.items() if key != "scope_root"}
    if value["scope_root"] != digest_json(preimage):
        raise ProtocolViolation("CONFIRM5 lite scope root mismatch")
    repo = (repo_root or _repo_root()).resolve(strict=True)
    relative = value.get("batch_binding", {}).get("relative_path")
    if type(relative) is not str:
        raise ProtocolViolation("CONFIRM5 lite scope batch path mismatch")
    rebuilt = build_lite_scope(
        batch_dir=repo / Path(*PurePosixPath(relative).parts), repo_root=repo
    )
    if rebuilt != value:
        raise ProtocolViolation("CONFIRM5 lite scope no longer matches live custody")
    return value


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--batch", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--scope", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        if args.output.exists():
            raise ProtocolViolation("CONFIRM5 lite scope publication is append-only")
        scope = build_lite_scope(batch_dir=args.batch)
        args.output.write_bytes(canonical_json_bytes(scope))
    else:
        scope = verify_lite_scope_bytes(args.scope.read_bytes())
    print(
        json.dumps(
            {
                "status": "verified",
                "scope_root": scope["scope_root"],
                "batch_root": scope["batch_binding"]["batch_root"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["PROTOCOL", "build_lite_scope", "verify_lite_scope_bytes"]
