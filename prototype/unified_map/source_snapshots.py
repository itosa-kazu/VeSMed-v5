"""Content-addressed source archive for historical UCM benchmark runs.

Run summaries bind the exact bytes that executed.  A Git commit is not enough
when several experiments were run from intermediate worktree states, so this
module verifies a portable byte archive against every selected run summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import canonical_json_bytes, digest_json


INDEX_RELATIVE_PATH = Path("results/unified_map/source_snapshots/index.json")
RUNS_RELATIVE_PATH = Path("results/unified_map/runs")
FAILED_RUNS_RELATIVE_PATH = Path("results/unified_map/failed_runs")
PROTOCOL = "ucm-source-snapshot-index/1"


class SourceSnapshotError(RuntimeError):
    """Raised when the historical source archive is incomplete or corrupt."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceSnapshotError(f"cannot load JSON {path}: {exc}") from exc
    if type(value) is not dict:
        raise SourceSnapshotError(f"JSON root must be an object: {path}")
    return value


def _experiment_number(experiment_id: str) -> int:
    try:
        prefix, number = experiment_id.split("-", 1)
        if prefix != "EXP":
            raise ValueError
        return int(number)
    except (AttributeError, ValueError) as exc:
        raise SourceSnapshotError(
            f"invalid experiment_id in run summary: {experiment_id!r}"
        ) from exc


def _safe_relative_path(value: str, *, field: str) -> PurePosixPath:
    if type(value) is not str or not value:
        raise SourceSnapshotError(f"unsafe {field}: {value!r}")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in value
    ):
        raise SourceSnapshotError(f"unsafe {field}: {value!r}")
    return path


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def resolve_source_snapshot(
    repo_root: Path,
    digest: str,
    relative_path: str,
    *,
    index_path: Path | None = None,
) -> Path:
    """Resolve one run binding to verified, exact archived bytes."""

    repo_root = repo_root.resolve()
    index_path = (index_path or repo_root / INDEX_RELATIVE_PATH).resolve()
    index = _load_json(index_path)
    if index.get("protocol") != PROTOCOL:
        raise SourceSnapshotError(
            f"unexpected snapshot protocol: {index.get('protocol')!r}"
        )
    normalized_original = _safe_relative_path(
        relative_path, field="relative_path"
    ).as_posix()
    matches = [
        entry
        for entry in index.get("objects", [])
        if type(entry) is dict and entry.get("sha256") == digest
    ]
    if len(matches) != 1:
        raise SourceSnapshotError(
            f"expected one archived object for {digest}, found {len(matches)}"
        )
    entry = matches[0]
    original_paths = entry.get("original_relative_paths")
    if type(original_paths) is not list or normalized_original not in original_paths:
        raise SourceSnapshotError(
            f"object {digest} is not bound to source path {normalized_original}"
        )
    object_rel = _safe_relative_path(entry.get("object_path"), field="object_path")
    object_path = index_path.parent.joinpath(*object_rel.parts).resolve()
    try:
        object_path.relative_to(index_path.parent)
    except ValueError as exc:
        raise SourceSnapshotError(
            f"object escapes snapshot root: {object_path}"
        ) from exc
    data = object_path.read_bytes()
    actual_digest = _sha256(data)
    if actual_digest != digest:
        raise SourceSnapshotError(
            f"snapshot digest mismatch for {object_rel}: "
            f"expected {digest}, got {actual_digest}"
        )
    if entry.get("byte_length") != len(data):
        raise SourceSnapshotError(
            f"snapshot length mismatch for {object_rel}: "
            f"expected {entry.get('byte_length')}, got {len(data)}"
        )
    return object_path


def verify_source_snapshots(
    repo_root: Path,
    *,
    index_path: Path | None = None,
    runs_root: Path | None = None,
    failed_runs_root: Path | None = None,
    through_experiment: int | None = None,
) -> dict[str, Any]:
    """Verify archived bytes and their coverage of run source bindings.

    ``through_experiment`` makes a historical closure assertion explicit.  If
    omitted, every completed run currently present under ``runs_root`` must be
    represented in the index.
    """

    repo_root = repo_root.resolve()
    index_path = (index_path or repo_root / INDEX_RELATIVE_PATH).resolve()
    runs_root = (runs_root or repo_root / RUNS_RELATIVE_PATH).resolve()
    failed_runs_root = (
        failed_runs_root or repo_root / FAILED_RUNS_RELATIVE_PATH
    ).resolve()
    index = _load_json(index_path)
    if index.get("protocol") != PROTOCOL:
        raise SourceSnapshotError(
            f"unexpected snapshot protocol: {index.get('protocol')!r}"
        )

    raw_objects = index.get("objects")
    raw_runs = index.get("runs")
    raw_failed_attempts = index.get("failed_attempts", [])
    if (
        type(raw_objects) is not list
        or type(raw_runs) is not list
        or type(raw_failed_attempts) is not list
    ):
        raise SourceSnapshotError(
            "index objects, runs and failed_attempts must be lists"
        )

    objects: dict[str, dict[str, Any]] = {}
    for entry in raw_objects:
        if type(entry) is not dict:
            raise SourceSnapshotError("object entry must be an object")
        digest = entry.get("sha256")
        if (
            type(digest) is not str
            or not digest.startswith("sha256:")
            or len(digest) != 71
        ):
            raise SourceSnapshotError(f"invalid object digest: {digest!r}")
        if digest in objects:
            raise SourceSnapshotError(f"duplicate object digest: {digest}")
        object_rel = _safe_relative_path(
            entry.get("object_path"), field="object_path"
        )
        expected_prefix = PurePosixPath("sha256", digest.removeprefix("sha256:"))
        if object_rel.parts[:2] != expected_prefix.parts:
            raise SourceSnapshotError(
                f"object is not content-addressed by its digest: {object_rel}"
            )
        object_path = index_path.parent.joinpath(*object_rel.parts).resolve()
        try:
            object_path.relative_to(index_path.parent)
        except ValueError as exc:
            raise SourceSnapshotError(
                f"object escapes snapshot root: {object_path}"
            ) from exc
        data = object_path.read_bytes()
        actual_digest = _sha256(data)
        if actual_digest != digest:
            raise SourceSnapshotError(
                f"snapshot digest mismatch for {object_rel}: "
                f"expected {digest}, got {actual_digest}"
            )
        if entry.get("byte_length") != len(data):
            raise SourceSnapshotError(
                f"snapshot length mismatch for {object_rel}: "
                f"expected {entry.get('byte_length')}, got {len(data)}"
            )
        original_paths = entry.get("original_relative_paths")
        if type(original_paths) is not list or not original_paths:
            raise SourceSnapshotError(
                f"object {digest} has no original_relative_paths"
            )
        normalized_paths = {
            _safe_relative_path(path, field="original_relative_paths").as_posix()
            for path in original_paths
        }
        objects[digest] = {**entry, "_original_paths": normalized_paths}

    indexed_runs: dict[str, dict[str, Any]] = {}
    for entry in raw_runs:
        if type(entry) is not dict or type(entry.get("run_id")) is not str:
            raise SourceSnapshotError("invalid run entry in source snapshot index")
        run_id = entry["run_id"]
        if run_id in indexed_runs:
            raise SourceSnapshotError(f"duplicate indexed run: {run_id}")
        indexed_runs[run_id] = entry

    indexed_failed_attempts: dict[str, dict[str, Any]] = {}
    for entry in raw_failed_attempts:
        if type(entry) is not dict or type(entry.get("run_id")) is not str:
            raise SourceSnapshotError(
                "invalid failed attempt entry in source snapshot index"
            )
        run_id = entry["run_id"]
        if run_id in indexed_failed_attempts or run_id in indexed_runs:
            raise SourceSnapshotError(f"duplicate indexed run/attempt: {run_id}")
        indexed_failed_attempts[run_id] = entry

    checked_runs = 0
    checked_bindings = 0
    referenced_digests: set[str] = set()
    completed_run_ids: set[str] = set()
    for run_dir in sorted(runs_root.iterdir()):
        summary_path = run_dir / "summary.json"
        manifest_path = run_dir / "manifest.json"
        if not summary_path.is_file() or not manifest_path.is_file():
            continue
        summary = _load_json(summary_path)
        experiment_id = summary.get("config", {}).get("experiment_id")
        experiment_number = _experiment_number(experiment_id)
        if through_experiment is not None and experiment_number > through_experiment:
            continue
        manifest = _load_json(manifest_path)
        run_id = summary.get("run_id")
        if run_id != run_dir.name or manifest.get("run_id") != run_id:
            raise SourceSnapshotError(
                f"run identity mismatch in {run_dir}: "
                f"summary={run_id!r}, manifest={manifest.get('run_id')!r}"
            )
        completed_run_ids.add(run_id)
        indexed = indexed_runs.get(run_id)
        if indexed is None:
            raise SourceSnapshotError(f"run missing from snapshot index: {run_id}")
        if indexed.get("experiment_id") != experiment_id:
            raise SourceSnapshotError(
                f"indexed experiment mismatch for {run_id}: "
                f"{indexed.get('experiment_id')!r} != {experiment_id!r}"
            )
        source_binding = summary.get("source_binding")
        if type(source_binding) is not dict or type(source_binding.get("files")) is not list:
            raise SourceSnapshotError(f"run has no valid source_binding: {run_id}")
        source_files = source_binding["files"]
        valid_source_digests = {digest_json(source_files)}
        # The ineligible true-state upper bound is a single-file control whose
        # v1 writer used the file digest directly rather than digest_json(rows).
        if len(source_files) == 1 and type(source_files[0]) is dict:
            valid_source_digests.add(source_files[0].get("sha256"))
        if source_binding.get("source_digest") not in valid_source_digests:
            raise SourceSnapshotError(f"source_digest mismatch for run {run_id}")
        indexed_files = indexed.get("files")
        if indexed.get("source_digest") != source_binding.get("source_digest"):
            raise SourceSnapshotError(f"indexed source_digest mismatch for {run_id}")
        if indexed_files != source_files:
            raise SourceSnapshotError(f"indexed file binding mismatch for {run_id}")
        for binding in source_files:
            if type(binding) is not dict:
                raise SourceSnapshotError(f"invalid source file binding in {run_id}")
            digest = binding.get("sha256")
            original_path = _safe_relative_path(
                binding.get("relative_path"), field="relative_path"
            ).as_posix()
            archived = objects.get(digest)
            if archived is None:
                raise SourceSnapshotError(
                    f"source object {digest!r} for {run_id} is not archived"
                )
            if archived.get("byte_length") != binding.get("byte_length"):
                raise SourceSnapshotError(
                    f"source length binding mismatch for {run_id}: {original_path}"
                )
            if original_path not in archived["_original_paths"]:
                raise SourceSnapshotError(
                    f"source path {original_path} is not bound to object {digest}"
                )
            referenced_digests.add(digest)
            checked_bindings += 1
        checked_runs += 1

    checked_failed_attempts = 0
    present_failed_attempt_ids: set[str] = set()
    if failed_runs_root.is_dir():
        for run_dir in sorted(failed_runs_root.iterdir()):
            failure_path = run_dir / "failure.json"
            manifest_path = run_dir / "manifest.json"
            if not failure_path.is_file() or not manifest_path.is_file():
                continue
            failure = _load_json(failure_path)
            experiment_id = failure.get("experiment_id")
            experiment_number = _experiment_number(experiment_id)
            if through_experiment is not None and experiment_number > through_experiment:
                continue
            manifest = _load_json(manifest_path)
            run_id = failure.get("run_id")
            if run_id != run_dir.name or manifest.get("run_id") != run_id:
                raise SourceSnapshotError(
                    f"failed attempt identity mismatch in {run_dir}"
                )
            present_failed_attempt_ids.add(run_id)
            indexed = indexed_failed_attempts.get(run_id)
            if indexed is None:
                raise SourceSnapshotError(
                    f"failed attempt missing from snapshot index: {run_id}"
                )
            if indexed.get("experiment_id") != experiment_id:
                raise SourceSnapshotError(
                    f"indexed failed experiment mismatch for {run_id}"
                )
            source_binding = failure.get("source_binding")
            if (
                type(source_binding) is not dict
                or type(source_binding.get("files")) is not list
            ):
                raise SourceSnapshotError(
                    f"failed attempt has no valid source_binding: {run_id}"
                )
            source_files = source_binding["files"]
            if source_binding.get("source_digest") != digest_json(source_files):
                raise SourceSnapshotError(
                    f"failed attempt source_digest mismatch: {run_id}"
                )
            if (
                indexed.get("source_digest") != source_binding["source_digest"]
                or indexed.get("files") != source_files
            ):
                raise SourceSnapshotError(
                    f"indexed failed source binding mismatch for {run_id}"
                )
            for binding in source_files:
                if type(binding) is not dict:
                    raise SourceSnapshotError(
                        f"invalid failed source file binding in {run_id}"
                    )
                digest = binding.get("sha256")
                original_path = _safe_relative_path(
                    binding.get("relative_path"), field="relative_path"
                ).as_posix()
                archived = objects.get(digest)
                if archived is None:
                    raise SourceSnapshotError(
                        f"failed source object {digest!r} for {run_id} is not archived"
                    )
                if archived.get("byte_length") != binding.get("byte_length"):
                    raise SourceSnapshotError(
                        f"failed source length mismatch for {run_id}: {original_path}"
                    )
                if original_path not in archived["_original_paths"]:
                    raise SourceSnapshotError(
                        f"failed source path {original_path} is not bound to {digest}"
                    )
                referenced_digests.add(digest)
                checked_bindings += 1
            checked_failed_attempts += 1

    extra_indexed = set(indexed_runs) - completed_run_ids
    if through_experiment is not None:
        extra_indexed = {
            run_id
            for run_id in extra_indexed
            if _experiment_number(indexed_runs[run_id]["experiment_id"])
            <= through_experiment
        }
    if extra_indexed:
        raise SourceSnapshotError(
            "index contains runs absent from completed run ledger: "
            + ", ".join(sorted(extra_indexed))
        )
    extra_failed = set(indexed_failed_attempts) - present_failed_attempt_ids
    if through_experiment is not None:
        extra_failed = {
            run_id
            for run_id in extra_failed
            if _experiment_number(indexed_failed_attempts[run_id]["experiment_id"])
            <= through_experiment
        }
    if extra_failed:
        raise SourceSnapshotError(
            "index contains failed attempts absent from failed ledger: "
            + ", ".join(sorted(extra_failed))
        )
    unreferenced = set(objects) - referenced_digests
    if through_experiment is not None:
        unreferenced = {
            digest
            for digest in unreferenced
            if any(
                _experiment_number(binding.get("experiment_id"))
                <= through_experiment
                for binding in objects[digest].get("bindings", [])
                if type(binding) is dict
            )
        }
    if unreferenced:
        raise SourceSnapshotError(
            "index contains unreferenced source objects: "
            + ", ".join(sorted(unreferenced))
        )

    return {
        "protocol": PROTOCOL,
        "index": str(index_path),
        "run_count": checked_runs,
        "failed_attempt_count": checked_failed_attempts,
        "binding_count": checked_bindings,
        "object_count": len(referenced_digests),
        "through_experiment": through_experiment,
        "status": "verified",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("resolve", "verify"))
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--index", type=Path)
    parser.add_argument("--runs-root", type=Path)
    parser.add_argument("--failed-runs-root", type=Path)
    parser.add_argument("--through-experiment", type=int)
    parser.add_argument("--sha256")
    parser.add_argument("--relative-path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "resolve":
        if args.sha256 is None or args.relative_path is None:
            raise SourceSnapshotError(
                "resolve requires --sha256 and --relative-path"
            )
        source_path = resolve_source_snapshot(
            args.repo_root,
            args.sha256,
            args.relative_path,
            index_path=args.index,
        )
        data = source_path.read_bytes()
        print(
            canonical_json_bytes(
                {
                    "byte_length": len(data),
                    "object_path": str(source_path),
                    "relative_path": args.relative_path,
                    "sha256": _sha256(data),
                    "status": "resolved",
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    report = verify_source_snapshots(
        args.repo_root,
        index_path=args.index,
        runs_root=args.runs_root,
        failed_runs_root=args.failed_runs_root,
        through_experiment=args.through_experiment,
    )
    print(canonical_json_bytes(report).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
