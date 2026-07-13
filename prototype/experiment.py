"""Immutable, self-describing architecture experiment panels.

The default execution path is the oracle-free subprocess boundary implemented
by :mod:`prototype.isolated_benchmark`.  ``--in-process`` remains available
only as a diagnostic aid; its bundles are labelled so they cannot be confused
with the evidentiary isolated panel.

Every run is assembled in a temporary sibling directory and published with one
rename while a per-run exclusive lock is held.  A previous result directory is
therefore never opened for writing and a failed run never leaves a partial
result at its final path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .benchmark import BENCHMARK_VERSION, BenchmarkRunner, summarize_runs
from .candidates.causal_state import build_candidate as build_causal
from .candidates.rewrite_open import build_candidate as build_rewrite
from .candidates.temporal_ledger import TemporalEvidenceLedger
from .contract import Track
from .isolated_benchmark import (
    ISOLATED_PROTOCOL,
    KNOWN_CANDIDATES,
    IsolatedBenchmarkRunner,
)
from .workloads import candidate_view, load_workloads, oracle_view


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_ROOT = ROOT / "results"
RUNNER_VERSION = "architecture-experiment-v2"
EXECUTION_MODES = ("isolated", "in_process_diagnostic")
ATOMIC_CANDIDATES = frozenset({"tel", "causal", "rewrite"})
DEFAULT_CANDIDATES = tuple(KNOWN_CANDIDATES)
DEFAULT_TRACKS = (Track.NATIVE, Track.COMPANION)

_CANDIDATE_SOURCES: dict[str, tuple[str, ...]] = {
    "tel": ("contract.py", "ir.py", "candidates/temporal_ledger.py"),
    "causal": ("contract.py", "ir.py", "candidates/causal_state.py"),
    "rewrite": ("contract.py", "ir.py", "candidates/rewrite_open.py"),
    "kernel": (
        "contract.py",
        "ir.py",
        "kernel.py",
        "candidates/temporal_ledger.py",
        "candidates/causal_state.py",
        "candidates/rewrite_open.py",
    ),
    "model": ("contract.py", "ir.py", "model_subkernel.py"),
}
_BENCHMARK_SOURCES = (
    "benchmark.py",
    "workloads.py",
    "reference_models.py",
    "isolated_benchmark.py",
    "isolated_worker.py",
    "experiment.py",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _sha256_files(root: Path, relative_paths: Iterable[str]) -> str:
    """Hash file names and bytes, not filesystem metadata or enumeration order."""

    digest = hashlib.sha256()
    paths = sorted(set(relative_paths))
    if not paths:
        raise ValueError("cannot hash an empty file set")
    for relative in paths:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        digest.update(relative.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _sha256_tree(root: Path, patterns: tuple[str, ...]) -> str:
    files: list[str] = []
    for pattern in patterns:
        files.extend(
            path.relative_to(root).as_posix()
            for path in root.glob(pattern)
            if path.is_file()
        )
    return _sha256_files(root, files)


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _git_revision() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return {
            "commit": commit,
            "dirty": bool(status),
            "status_digest": "sha256:"
            + hashlib.sha256(status.encode()).hexdigest(),
        }
    except Exception as exc:  # useful metadata, but not execution-critical
        return {
            "commit": None,
            "dirty": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _provider(candidate: str, track: Track) -> Callable[[], Any]:
    """Diagnostic in-process providers; the default path does not use these."""

    if candidate == "tel":
        return lambda: TemporalEvidenceLedger(track=track)
    if candidate == "causal":
        return lambda: build_causal(track=track)
    if candidate == "rewrite":
        return lambda: build_rewrite(track=track)
    if candidate == "kernel":
        from .kernel import build_candidate

        return lambda: build_candidate(track=track)
    if candidate == "model":
        from .model_subkernel import ExperimentalModelSubkernel

        return lambda: ExperimentalModelSubkernel(track=track)
    raise ValueError(f"unknown candidate: {candidate}")


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-panel-v2")


def _normalise_candidates(candidates: Sequence[str]) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(str(item) for item in candidates))
    unknown = sorted(set(selected) - set(KNOWN_CANDIDATES))
    if unknown:
        raise ValueError(f"unknown candidates: {unknown}")
    if not selected:
        raise ValueError("at least one candidate is required")
    return selected


def _normalise_tracks(tracks: Sequence[Track | str]) -> tuple[Track, ...]:
    try:
        selected = tuple(dict.fromkeys(Track(item) for item in tracks))
    except (TypeError, ValueError) as exc:
        raise ValueError("tracks must contain only native/companion") from exc
    if not selected:
        raise ValueError("at least one track is required")
    return selected


def _panel_matrix(
    candidates: Sequence[str], tracks: Sequence[Track | str]
) -> tuple[tuple[tuple[str, Track], ...], tuple[dict[str, str], ...]]:
    """Return the executable matrix and explicit non-applicable selections.

    Companion is an ablation for each *atomic* family.  K0 is already a
    composition/control-plane candidate and ``model`` is the typed model
    subkernel, so a companion version of either would have no defined
    experimental interpretation.
    """

    selected_candidates = _normalise_candidates(candidates)
    selected_tracks = _normalise_tracks(tracks)
    panels: list[tuple[str, Track]] = []
    skipped: list[dict[str, str]] = []
    for candidate in selected_candidates:
        for track in selected_tracks:
            if track is Track.COMPANION and candidate not in ATOMIC_CANDIDATES:
                skipped.append(
                    {
                        "candidate": candidate,
                        "track": track.value,
                        "reason": "companion ablation is defined only for atomic candidates",
                    }
                )
                continue
            panels.append((candidate, track))
    if not panels:
        raise ValueError("candidate/track selection produces no applicable panel")
    return tuple(panels), tuple(skipped)


def _select_workloads(
    workloads: Mapping[str, Mapping[str, Any]],
    *,
    panels: Sequence[str] = ("T", "E"),
    workload_ids: Sequence[str] | None = None,
) -> dict[str, Mapping[str, Any]]:
    selected_panels = tuple(dict.fromkeys(str(item) for item in panels))
    invalid_panels = sorted(set(selected_panels) - {"T", "E"})
    if invalid_panels or not selected_panels:
        raise ValueError(f"panels must be a non-empty subset of T/E: {invalid_panels}")
    selected = {
        key: value
        for key, value in workloads.items()
        if str(value.get("panel")) in selected_panels
    }
    if workload_ids is not None:
        requested = tuple(dict.fromkeys(str(item) for item in workload_ids))
        missing = sorted(set(requested) - set(selected))
        if missing:
            raise ValueError(f"unknown/not-selected workload IDs: {missing}")
        selected = {key: selected[key] for key in requested}
    if not selected:
        raise ValueError("workload selection is empty")
    return dict(sorted(selected.items()))


def _write_json_x(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _validate_run_id(run_id: str) -> None:
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be one non-empty path component")


def run_experiment(
    *,
    output_root: Path = DEFAULT_RESULTS_ROOT,
    run_id: str | None = None,
    candidates: Sequence[str] = DEFAULT_CANDIDATES,
    tracks: Sequence[Track | str] = DEFAULT_TRACKS,
    panels: Sequence[str] = ("T", "E"),
    workload_ids: Sequence[str] | None = None,
    execution_mode: str = "isolated",
    timeout_seconds: float = 30.0,
) -> Path:
    """Execute and atomically publish one frozen panel-v2 result bundle.

    ``workload_ids`` exists for focused reruns and fast harness tests.  It is
    recorded in metadata, so a focused run cannot masquerade as the complete
    T/E panel.
    """

    if execution_mode not in EXECUTION_MODES:
        raise ValueError(f"execution_mode must be one of {EXECUTION_MODES!r}")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    selected_run_id = run_id or _new_run_id()
    _validate_run_id(selected_run_id)
    matrix, skipped = _panel_matrix(candidates, tracks)
    all_workloads = load_workloads()
    workloads = _select_workloads(
        all_workloads, panels=panels, workload_ids=workload_ids
    )

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / selected_run_id
    lock_path = output_root / f".{selected_run_id}.lock"
    if target.exists():
        raise FileExistsError(target)

    # Exclusive creation also closes the concurrent same-run-id race.
    try:
        lock_handle = lock_path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise FileExistsError(f"run id is already being produced: {selected_run_id}") from exc

    stage: Path | None = None
    try:
        lock_handle.write(
            json.dumps({"pid": os.getpid(), "run_id": selected_run_id}) + "\n"
        )
        lock_handle.flush()
        if target.exists():
            raise FileExistsError(target)
        stage = Path(
            tempfile.mkdtemp(prefix=f".{selected_run_id}.tmp-", dir=output_root)
        )

        candidate_views = {
            key: candidate_view(value) for key, value in workloads.items()
        }
        oracle_views = {key: oracle_view(value) for key, value in workloads.items()}
        candidate_hashes = {
            candidate: _sha256_files(
                ROOT / "prototype", _CANDIDATE_SOURCES[candidate]
            )
            for candidate in dict.fromkeys(candidate for candidate, _ in matrix)
        }
        metadata = {
            "run_id": selected_run_id,
            "runner_version": RUNNER_VERSION,
            "benchmark_version": BENCHMARK_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope_note": "Synthetic architecture semantics benchmark; not clinical validation.",
            "execution": {
                "mode": execution_mode,
                "evidentiary_status": (
                    "isolated_panel"
                    if execution_mode == "isolated"
                    else "diagnostic_only_not_isolated_evidence"
                ),
                "isolation_protocol": (
                    ISOLATED_PROTOCOL if execution_mode == "isolated" else None
                ),
                "process": (
                    "fresh python -I -S per workload"
                    if execution_mode == "isolated"
                    else "judge and candidate share one Python process"
                ),
                "candidate_stdin": (
                    "candidate_view only" if execution_mode == "isolated" else None
                ),
                "oracle_location": "parent judge only" if execution_mode == "isolated" else "shared process",
                "python_confinement": (
                    "CPython audit hook: sandbox/runtime read allowlist; no subprocess/network/native loader"
                    if execution_mode == "isolated"
                    else None
                ),
                "security_boundary": (
                    "audited pure-Python candidates; not an OS sandbox"
                    if execution_mode == "isolated"
                    else "none"
                ),
                "timeout_seconds": timeout_seconds,
            },
            "environment": {
                "python_version": sys.version,
                "python_implementation": platform.python_implementation(),
                "python_executable": sys.executable,
                "platform": platform.platform(),
                "byteorder": sys.byteorder,
                "hash_seed_in_isolated_worker": "0" if execution_mode == "isolated" else None,
            },
            "git": _git_revision(),
            "selection": {
                "requested_candidates": list(_normalise_candidates(candidates)),
                "requested_tracks": [item.value for item in _normalise_tracks(tracks)],
                "requested_panels": list(dict.fromkeys(str(item) for item in panels)),
                "workload_ids": list(workloads),
                "workload_count": len(workloads),
                "panel_matrix": [
                    {"candidate": candidate, "track": track.value}
                    for candidate, track in matrix
                ],
                "skipped_non_applicable": list(skipped),
            },
            "hashes": {
                "requirements": _sha256_file(ROOT / "REQUIREMENTS.md"),
                "formal_spec": _sha256_file(ROOT / "FORMAL_SPEC.md"),
                "candidate_code": candidate_hashes,
                "model_subkernel_code": _sha256_files(
                    ROOT / "prototype", _CANDIDATE_SOURCES["model"]
                ),
                "benchmark_code": _sha256_files(
                    ROOT / "prototype", _BENCHMARK_SOURCES
                ),
                "workload_files": _sha256_tree(
                    ROOT / "tests" / "workloads", ("T/*.json", "E/*.json")
                ),
                "selected_candidate_views": _sha256_json(candidate_views),
                "selected_oracle_views": _sha256_json(oracle_views),
                "candidate_view_by_workload": {
                    key: _sha256_json(value)
                    for key, value in candidate_views.items()
                },
                "oracle_view_by_workload": {
                    key: _sha256_json(value) for key, value in oracle_views.items()
                },
            },
            "seeds": sorted(
                {
                    query["seed"]
                    for workload in workloads.values()
                    for query in workload["candidate_view"]["fixtures"]["queries"]
                }
            ),
        }
        _write_json_x(stage / "metadata.json", metadata)

        panel_summary: dict[str, Any] = {
            "run_id": selected_run_id,
            "runner_version": RUNNER_VERSION,
            "execution_mode": execution_mode,
            "workload_count": len(workloads),
            "panels": {},
            "skipped_non_applicable": list(skipped),
        }
        for candidate, track in matrix:
            if execution_mode == "isolated":
                runner: Any = IsolatedBenchmarkRunner(
                    candidate,
                    track=track.value,
                    timeout_seconds=timeout_seconds,
                )
            else:
                runner = BenchmarkRunner(_provider(candidate, track))
            runs = runner.run_panel(workloads)
            summary = summarize_runs(runs)
            key = f"{candidate}-{track.value}"
            bundle = {
                "run_id": selected_run_id,
                "runner_version": RUNNER_VERSION,
                "benchmark_version": BENCHMARK_VERSION,
                "candidate": candidate,
                "candidate_code_hash": candidate_hashes[candidate],
                "track": track.value,
                "execution_mode": execution_mode,
                "isolation_protocol": (
                    ISOLATED_PROTOCOL if execution_mode == "isolated" else None
                ),
                "workload_ids": list(workloads),
                "candidate_view_hash": metadata["hashes"]["selected_candidate_views"],
                "oracle_view_hash": metadata["hashes"]["selected_oracle_views"],
                "summary": summary,
                "runs": {
                    workload_id: run.to_dict()
                    for workload_id, run in runs.items()
                },
            }
            _write_json_x(stage / f"{key}.json", bundle)
            panel_summary["panels"][key] = summary
        _write_json_x(stage / "summary.json", panel_summary)

        # The lock guarantees that no peer can publish the same run id.  Rename
        # is confined to one filesystem because stage is a target sibling.
        if target.exists():
            raise FileExistsError(target)
        stage.rename(target)
        stage = None
        return target
    finally:
        lock_handle.close()
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Run and atomically freeze the architecture panel-v2 experiment"
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id", help="explicit unique run id; existing directories are rejected")
    parser.add_argument(
        "--candidate",
        action="append",
        choices=KNOWN_CANDIDATES,
        help="candidate to include; repeatable; default is all five",
    )
    parser.add_argument(
        "--track",
        action="append",
        choices=("native", "companion"),
        help="track to include; repeatable; default native plus atomic companion ablations",
    )
    parser.add_argument("--panel", action="append", choices=("T", "E"))
    parser.add_argument("--workload", action="append", help="focused workload id; repeatable")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="diagnostic only: disable process/oracle isolation and label the bundle accordingly",
    )
    args = parser.parse_args()
    target = run_experiment(
        output_root=args.output_root,
        run_id=args.run_id,
        candidates=tuple(args.candidate or DEFAULT_CANDIDATES),
        tracks=tuple(Track(item) for item in (args.track or ("native", "companion"))),
        panels=tuple(args.panel or ("T", "E")),
        workload_ids=tuple(args.workload) if args.workload else None,
        execution_mode="in_process_diagnostic" if args.in_process else "isolated",
        timeout_seconds=args.timeout,
    )
    print(target)
    return 0


__all__ = [
    "ATOMIC_CANDIDATES",
    "DEFAULT_CANDIDATES",
    "DEFAULT_RESULTS_ROOT",
    "RUNNER_VERSION",
    "run_experiment",
]


if __name__ == "__main__":  # pragma: no cover - integration command
    raise SystemExit(_cli())
