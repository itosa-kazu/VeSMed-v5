"""Adversarially isolated benchmark execution.

The normal :mod:`prototype.benchmark` runner already separates
``candidate_view`` from ``oracle_view`` as Python objects.  This module adds a
process and import boundary:

* the judge keeps workloads, assertions and reference models in the parent;
* a fresh temporary package contains only the frozen contract, closed IR and
  the selected candidate implementation;
* ``python -I -S`` receives *only* serialized ``candidate_view`` on stdin;
* a CPython audit hook denies filesystem reads outside the copied package and
  read-only interpreter roots, plus subprocess, network and native loaders;
* the worker returns raw calls/captures; the parent alone evaluates oracles.

This is Python-level process/import/filesystem confinement, not an operating-
system security sandbox.  It is designed for audited pure-Python candidates
and now rejects direct known-path reads as well as accidental imports and stack
inspection.  Native machine code or a CPython escape remains outside this
threat model and requires an AppContainer, VM or OS container.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping

from .benchmark import (
    BENCHMARK_VERSION,
    FAIL,
    NOT_APPLICABLE,
    PASS,
    AssertionResult,
    CallRecord,
    VerdictVector,
    WorkloadRun,
    _axis,
    _boundary_from_calls,
    _digest,
    _evaluate_assertion,
    summarize_runs,
)
from .workloads import candidate_view, load_workloads, oracle_view


ISOLATED_PROTOCOL = "vesmed-isolated-candidate/3"
KNOWN_CANDIDATES = ("tel", "causal", "rewrite", "kernel", "model")

_COMMON_FILES = (
    "__init__.py",
    "contract.py",
    "ir.py",
    "isolated_worker.py",
    "candidates/__init__.py",
)
_CANDIDATE_FILES = {
    "tel": ("candidates/temporal_ledger.py",),
    "causal": ("candidates/causal_state.py",),
    "rewrite": ("candidates/rewrite_open.py",),
    "kernel": (
        "kernel.py",
        "candidates/temporal_ledger.py",
        "candidates/causal_state.py",
        "candidates/rewrite_open.py",
    ),
    "model": ("model_subkernel.py",),
    "custom": (),
}
_FORBIDDEN_SANDBOX_NAMES = {
    "benchmark.py",
    "isolated_benchmark.py",
    "workloads.py",
    "reference_models.py",
    "experiment.py",
    "tests",
    "results",
}
_TRANSCRIPT_KEYS = {
    "protocol",
    "candidate_id",
    "manifest_snapshot",
    "candidate_input_digest",
    "calls",
    "captures",
    "capture_inputs",
    "harness_errors",
}


class IsolationError(RuntimeError):
    """The process/import isolation protocol itself was violated."""


def _safe_environment(root: Path) -> dict[str, str]:
    """Return a minimal Windows/POSIX environment without repository paths."""

    env: dict[str, str] = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "HOME": str(root),
        "USERPROFILE": str(root),
        "TEMP": str(root / "tmp"),
        "TMP": str(root / "tmp"),
    }
    # CPython and Windows DLL loading can require these platform variables.
    # They carry no repository/workload location.
    for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _copy_minimal_package(
    root: Path,
    candidate_name: str,
    custom_candidate_source: str | None,
) -> tuple[Path, tuple[str, ...]]:
    """Create and verify the candidate-visible allow-listed package."""

    if candidate_name not in _CANDIDATE_FILES:
        raise ValueError(f"unknown candidate {candidate_name!r}")
    if candidate_name == "custom" and not custom_candidate_source:
        raise ValueError("custom candidate requires custom_candidate_source")
    if candidate_name != "custom" and custom_candidate_source is not None:
        raise ValueError("custom_candidate_source is only valid for candidate='custom'")

    source_root = Path(__file__).resolve().parent
    package_root = root / "prototype"
    (package_root / "candidates").mkdir(parents=True, exist_ok=True)
    (root / "tmp").mkdir(parents=True, exist_ok=True)

    relative_files = list(_COMMON_FILES) + list(_CANDIDATE_FILES[candidate_name])
    for relative in relative_files:
        source = source_root / relative
        if not source.is_file():
            raise IsolationError(f"allow-listed source is missing: {relative}")
        destination = package_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    if candidate_name == "custom":
        (package_root / "sandbox_candidate.py").write_text(
            custom_candidate_source or "", encoding="utf-8"
        )

    inventory = tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )
    )
    for relative in inventory:
        parts = Path(relative).parts
        if any(part in _FORBIDDEN_SANDBOX_NAMES for part in parts):
            raise IsolationError(f"runner-only file entered sandbox: {relative}")
    return package_root / "isolated_worker.py", inventory


def _empty_transcript(error: str) -> dict[str, Any]:
    return {
        "protocol": ISOLATED_PROTOCOL,
        "candidate_id": "unknown",
        "manifest_snapshot": {},
        "candidate_input_digest": None,
        "calls": [],
        "captures": {},
        "capture_inputs": {},
        "harness_errors": [error],
    }


class IsolatedBenchmarkRunner:
    """Run candidates in fresh oracle-free Python processes, then judge them.

    ``custom_candidate_source`` exists to test the boundary with adversarial
    fixtures.  It is copied as ``prototype.sandbox_candidate`` but is never
    sent on stdin; stdin remains the pure public candidate view.
    """

    def __init__(
        self,
        candidate: str,
        *,
        track: str = "native",
        timeout_seconds: float = 30.0,
        custom_candidate_source: str | None = None,
    ) -> None:
        if candidate not in (*KNOWN_CANDIDATES, "custom"):
            raise ValueError(f"unknown candidate {candidate!r}")
        if track not in {"native", "companion"}:
            raise ValueError("track must be 'native' or 'companion'")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.candidate = candidate
        self.track = track
        self.timeout_seconds = float(timeout_seconds)
        self.custom_candidate_source = custom_candidate_source
        self.last_sandbox_inventory: tuple[str, ...] = ()
        self.last_worker_transcript: dict[str, Any] | None = None

    def _execute_view(self, view: Mapping[str, Any]) -> dict[str, Any]:
        # Re-serialize before creating the child process: the worker receives no
        # Python object, callback, oracle object, assertion or parent frame.
        payload = json.dumps(
            view, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with tempfile.TemporaryDirectory(prefix="vesmed-candidate-") as temp:
            root = Path(temp).resolve()
            worker, inventory = _copy_minimal_package(
                root, self.candidate, self.custom_candidate_source
            )
            self.last_sandbox_inventory = inventory
            command = [
                sys.executable,
                "-I",
                "-S",
                str(worker),
                "--candidate",
                self.candidate,
                "--track",
                self.track,
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    env=_safe_environment(root),
                    input=payload,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                transcript = _empty_transcript(
                    f"isolated worker timeout after {self.timeout_seconds:g}s"
                )
                self.last_worker_transcript = transcript
                return transcript
            except Exception as exc:
                transcript = _empty_transcript(
                    f"isolated worker launch failed: {type(exc).__name__}: {exc}"
                )
                self.last_worker_transcript = transcript
                return transcript

            try:
                transcript = json.loads(completed.stdout)
                if not isinstance(transcript, dict):
                    raise TypeError("worker stdout is not a JSON object")
            except Exception as exc:
                transcript = _empty_transcript(
                    f"invalid isolated worker stdout: {type(exc).__name__}: {exc}"
                )

            extra = set(transcript) - _TRANSCRIPT_KEYS
            missing = _TRANSCRIPT_KEYS - set(transcript)
            errors = transcript.get("harness_errors")
            if not isinstance(errors, list):
                errors = ["worker harness_errors is not a list"]
                transcript["harness_errors"] = errors
            if extra:
                errors.append(f"worker returned forbidden transcript keys: {sorted(extra)}")
            if missing:
                errors.append(f"worker omitted transcript keys: {sorted(missing)}")
            if transcript.get("protocol") != ISOLATED_PROTOCOL:
                errors.append(
                    f"worker protocol mismatch: {transcript.get('protocol')!r}"
                )
            if completed.returncode != 0 and not errors:
                errors.append(f"isolated worker exited {completed.returncode}")
            if completed.stderr:
                # Content is intentionally not copied: a malicious candidate
                # could try to exfiltrate host paths through stderr.
                errors.append("isolated worker emitted stderr")
            self.last_worker_transcript = copy.deepcopy(transcript)
            return transcript

    def run(self, workload: Mapping[str, Any]) -> WorkloadRun:
        workload_id = str(workload["workload_id"])
        view = json.loads(
            json.dumps(candidate_view(workload), ensure_ascii=False, sort_keys=True)
        )
        transcript = self._execute_view(view)
        harness_errors = [str(item) for item in transcript.get("harness_errors", [])]
        expected_digest = _digest(view)
        if transcript.get("candidate_input_digest") != expected_digest:
            harness_errors.append(
                "candidate_view digest mismatch across isolated stdin boundary"
            )

        calls: list[CallRecord] = []
        raw_calls = transcript.get("calls", [])
        if not isinstance(raw_calls, list):
            harness_errors.append("worker calls is not a list")
            raw_calls = []
        for index, item in enumerate(raw_calls):
            try:
                if not isinstance(item, Mapping) or not isinstance(
                    item.get("result"), Mapping
                ):
                    raise TypeError("call/result is not an object")
                calls.append(
                    CallRecord(
                        branch_id=str(item["branch_id"]),
                        call_index=int(item["call_index"]),
                        op=str(item["op"]),
                        input_digest=str(item["input_digest"]),
                        result=copy.deepcopy(dict(item["result"])),
                        capture=(
                            str(item["capture"])
                            if item.get("capture") is not None
                            else None
                        ),
                        query_kind=(
                            str(item["query_kind"])
                            if item.get("query_kind") is not None
                            else None
                        ),
                    )
                )
            except Exception as exc:
                harness_errors.append(
                    f"invalid worker call {index}: {type(exc).__name__}: {exc}"
                )

        raw_captures = transcript.get("captures", {})
        if not isinstance(raw_captures, Mapping):
            harness_errors.append("worker captures is not an object")
            raw_captures = {}
        captures: dict[str, dict[str, Any]] = {}
        for key, value in raw_captures.items():
            if isinstance(value, Mapping):
                captures[str(key)] = copy.deepcopy(dict(value))
            else:
                harness_errors.append(f"capture {key!r} is not an object")

        raw_capture_inputs = transcript.get("capture_inputs", {})
        if not isinstance(raw_capture_inputs, Mapping):
            harness_errors.append("worker capture_inputs is not an object")
            raw_capture_inputs = {}
        capture_inputs: dict[str, dict[str, Any]] = {}
        for key, value in raw_capture_inputs.items():
            if isinstance(value, Mapping):
                capture_inputs[str(key)] = copy.deepcopy(dict(value))
            else:
                harness_errors.append(f"capture input {key!r} is not an object")

        assertions: list[AssertionResult] = [
            _evaluate_assertion(workload_id, item, captures, capture_inputs)
            for item in oracle_view(workload).get("assertions", [])
        ]
        manifest = transcript.get("manifest_snapshot", {})
        if not isinstance(manifest, Mapping):
            harness_errors.append("worker manifest_snapshot is not an object")
            manifest = {}
        manifest_snapshot = copy.deepcopy(dict(manifest))
        boundary_axis, dishonest = _boundary_from_calls(calls, manifest_snapshot)
        explicit = [item for item in assertions if item.verdict_axis == "boundary"]
        if explicit:
            boundary_axis = (
                PASS
                if all(item.passed for item in explicit) and boundary_axis != FAIL
                else FAIL
            )

        hard_relevant = [item for item in assertions if item.hard_gate]
        hard_axis = (
            NOT_APPLICABLE
            if not hard_relevant
            else PASS
            if all(item.passed for item in hard_relevant)
            else FAIL
        )
        has_ineligible_reference = any(
            item.evidence_refs
            and not item.semantic_eligible
            and item.oracle_kind != "honesty"
            for item in assertions
        )
        if harness_errors:
            classification = "HARNESS_ERROR"
        elif dishonest:
            classification = "DISHONEST_CLAIM"
        elif any(call.result.get("status") == "numerical_failure" for call in calls):
            classification = "NUMERICAL_FAILURE"
        elif any(
            isinstance(call.result.get("diagnostics"), Mapping)
            and call.result.get("diagnostics", {}).get("candidate_raised")
            for call in calls
        ):
            classification = "INVALID_RESULT"
        elif (
            hard_axis == PASS
            and boundary_axis != FAIL
            and not has_ineligible_reference
        ):
            classification = "PASS"
        elif any(
            call.result.get("status")
            in {"unsupported", "insufficient", "out_of_model"}
            for call in calls
        ) and boundary_axis == PASS:
            classification = "HONEST_UNSUPPORTED"
        else:
            classification = "FAIL"

        verdict = VerdictVector(
            behavior=_axis(assertions, "behavior"),
            boundary=boundary_axis,
            trace=_axis(assertions, "trace"),
            numerical=_axis(assertions, "numerical"),
            hard=hard_axis,
            classification=classification,
        )
        return WorkloadRun(
            benchmark_version=f"{BENCHMARK_VERSION}+isolated-v1",
            workload_id=workload_id,
            candidate_id=str(transcript.get("candidate_id") or "unknown"),
            manifest_snapshot=manifest_snapshot,
            candidate_input_digest=expected_digest,
            calls=calls,
            captures=captures,
            assertions=assertions,
            verdict=verdict,
            harness_errors=harness_errors,
        )

    def run_panel(
        self, workloads: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, WorkloadRun]:
        return {
            workload_id: self.run(workload)
            for workload_id, workload in sorted(workloads.items())
        }


def run_isolated(
    candidate: str,
    workload: Mapping[str, Any],
    *,
    track: str = "native",
    timeout_seconds: float = 30.0,
) -> WorkloadRun:
    """Convenience function for one known candidate/workload pair."""

    if candidate not in KNOWN_CANDIDATES:
        raise ValueError(f"candidate must be one of {KNOWN_CANDIDATES!r}")
    return IsolatedBenchmarkRunner(
        candidate, track=track, timeout_seconds=timeout_seconds
    ).run(workload)


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Run VeSMed benchmark candidates in an oracle-free subprocess"
    )
    parser.add_argument("--candidate", choices=KNOWN_CANDIDATES, required=True)
    parser.add_argument("--track", choices=("native", "companion"), default="native")
    parser.add_argument("--panel", choices=("T", "E", "all"), default="all")
    parser.add_argument("--workload", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")

    workloads = load_workloads()
    if args.panel != "all":
        workloads = {
            key: value
            for key, value in workloads.items()
            if value["panel"] == args.panel
        }
    if args.workload:
        requested = set(args.workload)
        missing = requested - set(workloads)
        if missing:
            parser.error(f"unknown/not-selected workload IDs: {sorted(missing)}")
        workloads = {
            key: value for key, value in workloads.items() if key in requested
        }

    runner = IsolatedBenchmarkRunner(
        args.candidate, track=args.track, timeout_seconds=args.timeout
    )
    runs = runner.run_panel(workloads)
    summary = summarize_runs(runs)
    summary["benchmark_version"] = f"{BENCHMARK_VERSION}+isolated-v1"
    bundle = {
        "benchmark_version": f"{BENCHMARK_VERSION}+isolated-v1",
        "candidate": args.candidate,
        "track": args.track,
        "isolation": {
            "process": "fresh python -I -S",
            "stdin": "candidate_view only",
            "oracle_location": "parent judge only",
        },
        "summary": summary,
        "runs": {key: value.to_dict() for key, value in runs.items()},
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2)
                    + "\n"
                )
        except FileExistsError:
            parser.error(f"refusing to overwrite existing output: {args.output}")
    print(json.dumps(bundle["summary"], ensure_ascii=False, sort_keys=True, indent=2))
    return 2 if any(run.harness_errors for run in runs.values()) else 0


__all__ = [
    "ISOLATED_PROTOCOL",
    "KNOWN_CANDIDATES",
    "IsolationError",
    "IsolatedBenchmarkRunner",
    "run_isolated",
]


if __name__ == "__main__":  # pragma: no cover - integration entrypoint
    raise SystemExit(_cli())
