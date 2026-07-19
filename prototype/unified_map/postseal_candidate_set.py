"""Durable source seal for supplemental CONFIRM5 and red-team subjects."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .benchmark_v1_freeze import verify_freeze_manifest_bytes
from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes, digest_json


PROTOCOL = "ucm-postseal-candidate-set/1"
STATUS = "SEALED_BEFORE_SUPPLEMENTAL_PACK_MATERIALIZATION"
PRIMARY_SEAL_COMMIT = "68dee722bd95ea8f61ba09d7e6a150f5e4191ab1"
DEFAULT_FREEZE = Path("research/unified_map/BENCHMARK_V1_FREEZE.json")
DEFAULT_PRIMARY_SEAL = Path("research/unified_map/CANDIDATE_SEAL.json")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_blob(repo: Path, commit: str, relative: str) -> bytes:
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
        raise ProtocolViolation("source commit must be a full lowercase Git object id")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ProtocolViolation("sealed source path escapes repository")
    try:
        return subprocess.check_output(
            ["git", "show", f"{commit}:{path.as_posix()}"],
            cwd=repo,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProtocolViolation(f"sealed Git source is unavailable: {relative}") from exc


def build_candidate_set_seal(
    *,
    source_commit: str,
    source_paths: Iterable[str],
    subjects: list[dict[str, Any]],
    repo_root: Path | None = None,
) -> dict[str, Any]:
    repo = (repo_root or _repo_root()).resolve(strict=True)
    freeze = verify_freeze_manifest_bytes((repo / DEFAULT_FREEZE).read_bytes())
    primary_seal_raw = (repo / DEFAULT_PRIMARY_SEAL).read_bytes()
    rows = []
    for relative in sorted(set(source_paths)):
        blob = _git_blob(repo, source_commit, relative)
        live = (repo / relative).read_bytes()
        if live != blob:
            raise ProtocolViolation(f"live source differs from pre-pack commit: {relative}")
        rows.append(
            {
                "relative_path": PurePosixPath(relative).as_posix(),
                "byte_length": len(blob),
                "sha256": digest_bytes(blob),
            }
        )
    if not rows:
        raise ProtocolViolation("candidate-set seal requires source files")
    preimage = {
        "protocol": PROTOCOL,
        "status": STATUS,
        "freeze_root": freeze["freeze_root"],
        "primary_candidate_seal_digest": digest_bytes(primary_seal_raw),
        "primary_seal_commit": PRIMARY_SEAL_COMMIT,
        "prepack_source_commit": source_commit,
        "subjects": subjects,
        "source_binding": {"files": rows, "source_digest": digest_json(rows)},
        "mutation_rule": "Any bound source-byte change creates a new subject/version and seal.",
    }
    return {**preimage, "seal_root": digest_json(preimage)}


def verify_candidate_set_seal_bytes(
    payload: bytes, *, repo_root: Path | None = None
) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("candidate-set seal is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise ProtocolViolation("candidate-set seal is not canonical JSON")
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
    if set(value) != required or value["protocol"] != PROTOCOL or value["status"] != STATUS:
        raise ProtocolViolation("candidate-set seal schema/status mismatch")
    preimage = {key: item for key, item in value.items() if key != "seal_root"}
    if value["seal_root"] != digest_json(preimage):
        raise ProtocolViolation("candidate-set seal root mismatch")
    rebuilt = build_candidate_set_seal(
        source_commit=value["prepack_source_commit"],
        source_paths=[row["relative_path"] for row in value["source_binding"]["files"]],
        subjects=value["subjects"],
        repo_root=repo_root,
    )
    if rebuilt != value:
        raise ProtocolViolation("candidate-set seal no longer matches live/Git authority")
    return value


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seal", type=Path)
    args = parser.parse_args()
    seal = verify_candidate_set_seal_bytes(args.seal.read_bytes())
    print(json.dumps({"status": "verified", "seal_root": seal["seal_root"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
