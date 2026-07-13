"""Candidate-side worker for the adversarial benchmark sandbox.

This file is copied into a temporary, allow-listed ``prototype`` package and
started with ``python -I -S``.  It deliberately contains no oracle evaluator
and imports neither workloads nor reference models.  Its stdin is exactly one
JSON ``candidate_view``.  Its stdout is exactly one JSON execution transcript;
candidate prints are swallowed so they cannot corrupt the protocol.

The parent process is the judge.  This process only compiles public fixtures,
invokes a candidate, and returns normalized raw call results/captures.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
from dataclasses import asdict, is_dataclass
from enum import Enum
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


# ``-I`` intentionally omits the script directory from sys.path on some
# Python/Windows combinations.  Add only the temporary package root.  No
# original repository path is supplied by the parent.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))

from prototype.contract import (  # noqa: E402 - after isolated path setup
    CapabilityResult,
    ClockSet,
    InfoState,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
    Track,
)


PROTOCOL = "vesmed-isolated-candidate/3"
_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {"oracle_view", "assertion_id", "oracle_id", "reference_path", "expected"}
)


# This is deliberately a Python-level confinement boundary, not an operating-
# system sandbox.  It prevents an audited pure-Python candidate from escaping
# the copied allow-list by simply opening a known repository path, spawning a
# helper, loading native code, or using the network.  Native machine code and
# CPython vulnerabilities remain outside the stated threat model.
_CONFINEMENT_INSTALLED = False
_BLOCKED_IMPORT_ROOTS = frozenset(
    {
        "ctypes",
        "multiprocessing",
        "socket",
        "subprocess",
        "winreg",
    }
)
_BLOCKED_AUDIT_EVENTS = frozenset(
    {
        "ctypes.dlopen",
        "os.chdir",
        "os.fchdir",
        "os.fork",
        "os.forkpty",
        "os.kill",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.startfile",
        "os.system",
        "pty.spawn",
        "socket.__new__",
        "socket.bind",
        "socket.connect",
        "socket.getaddrinfo",
        "subprocess.Popen",
    }
)


def _within(path: Path, root: Path) -> bool:
    """Return whether *path* is root or a descendant, without string-prefix bugs."""

    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _canonical_audit_path(value: Any) -> Path | None:
    if isinstance(value, int):
        # Existing standard streams/pipes are the only inherited descriptors.
        return None
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    if not isinstance(value, (str, os.PathLike)):
        return None
    return Path(os.path.abspath(os.fspath(value))).resolve(strict=False)


def _read_only_open(mode: Any, flags: Any) -> bool:
    mode_text = str(mode or "r")
    if any(marker in mode_text for marker in ("w", "a", "x", "+")):
        return False
    if isinstance(flags, int):
        forbidden = 0
        for name in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"):
            forbidden |= int(getattr(os, name, 0))
        if flags & forbidden:
            return False
    return True


def _install_python_confinement() -> None:
    """Install a one-way CPython audit hook before candidate imports.

    The copied sandbox is read/write.  The interpreter installation is read-
    only so normal stdlib imports continue to work.  Every other filesystem
    path is denied.  CPython exposes no API for removing an audit hook.
    """

    global _CONFINEMENT_INSTALLED
    if _CONFINEMENT_INSTALLED:
        return
    sandbox_root = _PACKAGE_ROOT.resolve(strict=False)
    runtime_roots = tuple(
        dict.fromkeys(
            Path(item).resolve(strict=False)
            for item in (sys.base_prefix, sys.exec_prefix)
            if item
        )
    )

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "import" and args:
            root = str(args[0]).split(".", 1)[0]
            if root in _BLOCKED_IMPORT_ROOTS:
                raise PermissionError(f"candidate import blocked by confinement: {root}")
            return
        if event == "open":
            path = _canonical_audit_path(args[0] if args else None)
            if path is None or _within(path, sandbox_root):
                return
            if any(_within(path, root) for root in runtime_roots) and _read_only_open(
                args[1] if len(args) > 1 else "r",
                args[2] if len(args) > 2 else 0,
            ):
                return
            raise PermissionError("candidate filesystem access outside isolated roots")
        if event in _BLOCKED_AUDIT_EVENTS or event.startswith("os.spawn"):
            raise PermissionError(f"candidate operation blocked by confinement: {event}")
        if event in {"os.listdir", "os.scandir"} and args:
            path = _canonical_audit_path(args[0])
            if path is not None and not _within(path, sandbox_root):
                raise PermissionError("candidate directory enumeration outside sandbox")
        if event in {
            "os.chmod",
            "os.chown",
            "os.link",
            "os.mkdir",
            "os.remove",
            "os.rename",
            "os.replace",
            "os.rmdir",
            "os.symlink",
            "os.truncate",
            "os.unlink",
        }:
            for value in args[:2]:
                path = _canonical_audit_path(value)
                if path is not None and not _within(path, sandbox_root):
                    raise PermissionError("candidate mutation outside sandbox")

    sys.addaudithook(audit)
    _CONFINEMENT_INSTALLED = True


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_finite": repr(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _digest(value: Any) -> str:
    payload = json.dumps(
        _plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def _assert_public_view(value: Any, path: str = "$") -> None:
    """Fail closed if runner-only keys somehow cross the process boundary."""

    if isinstance(value, Mapping):
        forbidden = _FORBIDDEN_PUBLIC_KEYS.intersection(str(key) for key in value)
        if forbidden:
            raise ValueError(f"runner-only key(s) at {path}: {sorted(forbidden)}")
        for key, item in value.items():
            _assert_public_view(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_public_view(item, f"{path}[{index}]")


def _compile_artifact(data: Mapping[str, Any]) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=str(data["artifact_id"]),
        source_id=str(data["source_id"]),
        semantic_role=SemanticRole(data["semantic_role"]),
        concept=str(data["concept"]),
        scope=Scope(**data["scope"]),
        clocks=ClockSet(**data["clocks"]),
        information_state=InfoState(data.get("information_state", "present")),
        value=copy.deepcopy(data.get("value")),
        unit=data.get("unit"),
        method=data.get("method"),
        context=copy.deepcopy(data.get("context", {})),
        reliability=data.get("reliability"),
        source_family=data.get("source_family"),
        supersedes=data.get("supersedes"),
        raw_payload=copy.deepcopy(data.get("raw_payload", {})),
        mapping_version=str(data.get("mapping_version", "canonical-v1")),
    )


def _compile_query(data: Mapping[str, Any]) -> QuerySpec:
    return QuerySpec(
        query_id=str(data["query_id"]),
        kind=QueryKind(data["kind"]),
        target=str(data["target"]),
        subject_id=str(data["subject_id"]),
        as_known_at=str(data["as_known_at"]),
        valid_at=data.get("valid_at"),
        task=data.get("task"),
        knowledge_version=str(data.get("knowledge_version", "knowledge-v1")),
        model_version=data.get("model_version"),
        intervention=copy.deepcopy(data.get("intervention")),
        horizon_hours=data.get("horizon_hours"),
        requested_guarantees=tuple(data.get("requested_guarantees", ())),
        assumptions=tuple(data.get("assumptions", ())),
        seed=int(data.get("seed", 0)),
    )


def _invalid_result(reason: str, *, exception_type: str | None = None) -> dict[str, Any]:
    return CapabilityResult(
        status=ResultStatus.INVALID,
        validation="invalid",
        capability="unsupported",
        epistemic="not_applicable",
        coverage_status="unknown",
        identification="not_applicable",
        computation="not_applicable",
        diagnostics={
            "reason": reason,
            "exception_type": exception_type,
            "candidate_raised": True,
        },
    ).to_dict()


def _normalize_result(result: Any) -> dict[str, Any]:
    if isinstance(result, CapabilityResult):
        out = result.to_dict()
    elif isinstance(result, Mapping):
        out = _plain(result)
    else:
        return _invalid_result(
            f"candidate returned non-result type {type(result).__name__}"
        )
    if not isinstance(out.get("status"), str):
        return _invalid_result("candidate result lacks string status")
    defaults = {
        "validation": "unknown",
        "capability": "unknown",
        "epistemic": "unknown",
        "coverage_status": "unknown",
        "identification": "unknown",
        "computation": "unknown",
        "value_kind": "none",
        "value": None,
        "assumptions": [],
        "coverage": {},
        "time_cut": {},
        "evidence_witness": {},
        "native_witness": {},
        "diagnostics": {},
        "versions": {},
    }
    for key, default in defaults.items():
        out.setdefault(key, copy.deepcopy(default))
    return _plain(out)


def _load_provider(candidate_name: str, track_name: str) -> Callable[[], Any]:
    track = Track(track_name)
    if candidate_name == "tel":
        from prototype.candidates.temporal_ledger import TemporalEvidenceLedger

        return lambda: TemporalEvidenceLedger(track=track)
    if candidate_name == "causal":
        from prototype.candidates.causal_state import build_candidate

        return lambda: build_candidate(track=track)
    if candidate_name == "rewrite":
        from prototype.candidates.rewrite_open import build_candidate

        return lambda: build_candidate(track=track)
    if candidate_name == "kernel":
        from prototype.kernel import build_candidate

        return lambda: build_candidate(track=track)
    if candidate_name == "model":
        from prototype.model_subkernel import ExperimentalModelSubkernel

        return lambda: ExperimentalModelSubkernel(track=track)
    if candidate_name == "custom":
        from prototype.sandbox_candidate import build_candidate

        return lambda: build_candidate(track=track)
    raise ValueError(f"unknown candidate: {candidate_name!r}")


def _manifest(candidate: Any) -> dict[str, Any]:
    try:
        manifest = candidate.manifest
        if callable(manifest):
            manifest = manifest()
        return _plain(manifest)
    except Exception as exc:  # candidate-controlled boundary
        return {
            "candidate_id": candidate.__class__.__name__,
            "manifest_error": f"{type(exc).__name__}: {exc}",
        }


def execute(candidate_name: str, track_name: str, view: Mapping[str, Any]) -> dict[str, Any]:
    """Execute public branch operations without evaluating a single oracle."""

    _install_python_confinement()
    _assert_public_view(view)
    # JSON round trip ensures no shared object/callable can enter execution.
    public_view = json.loads(json.dumps(view, ensure_ascii=False, sort_keys=True))
    fixtures = public_view["fixtures"]
    artifact_data = {
        item["artifact_id"]: item for item in fixtures.get("artifacts", [])
    }
    query_data = {item["query_id"]: item for item in fixtures.get("queries", [])}
    module_data = {item["module_id"]: item for item in fixtures.get("modules", [])}
    calls: list[dict[str, Any]] = []
    captures: dict[str, dict[str, Any]] = {}
    capture_inputs: dict[str, dict[str, Any]] = {}
    harness_errors: list[str] = []
    manifest_snapshot: dict[str, Any] = {}
    candidate_id = "unknown"

    # Imports, constructors and candidate calls are all inside a redirected
    # console.  The JSON protocol remains the only stdout channel.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        provider = _load_provider(candidate_name, track_name)
        for branch in public_view.get("branches", []):
            branch_id = str(branch["branch_id"])
            try:
                session = provider()
            except Exception as exc:
                harness_errors.append(
                    f"branch {branch_id} instantiation: {type(exc).__name__}: {exc}"
                )
                continue
            if not manifest_snapshot:
                manifest_snapshot = _manifest(session)
                candidate_id = str(
                    manifest_snapshot.get("candidate_id")
                    or session.__class__.__name__
                )

            call_index = 0
            operation_journal: list[tuple[str, dict[str, Any]]] = []

            def invoke(
                op: str,
                input_value: Any,
                function: Callable[[], Any],
                capture: str | None = None,
                *,
                query_kind: str | None = None,
            ) -> dict[str, Any]:
                nonlocal call_index
                call_index += 1
                try:
                    normalized = _normalize_result(function())
                except Exception as exc:
                    normalized = _invalid_result(
                        str(exc), exception_type=type(exc).__name__
                    )
                calls.append(
                    {
                        "branch_id": branch_id,
                        "call_index": call_index,
                        "op": op,
                        "input_digest": _digest(input_value),
                        "result": normalized,
                        "capture": capture,
                        "query_kind": query_kind,
                    }
                )
                if capture:
                    ref = f"{branch_id}:{capture}"
                    captures[ref] = normalized
                    capture_inputs[ref] = (
                        copy.deepcopy(dict(input_value))
                        if isinstance(input_value, Mapping)
                        else {"input": _plain(input_value)}
                    )
                return normalized

            for step in branch.get("steps", []):
                op = step.get("op")
                try:
                    if op == "ingest":
                        last: dict[str, Any] | None = None
                        for artifact_id in step.get("artifact_ids", []):
                            data = artifact_data[artifact_id]
                            artifact = _compile_artifact(data)
                            last = invoke(
                                "ingest",
                                data,
                                lambda artifact=artifact: session.ingest(artifact),
                            )
                            operation_journal.append(("ingest", copy.deepcopy(data)))
                        if step.get("capture") and last is not None:
                            ref = f"{branch_id}:{step['capture']}"
                            captures[ref] = last
                            capture_inputs[ref] = copy.deepcopy(data)
                    elif op == "query":
                        data = query_data[step["query_id"]]
                        spec = _compile_query(data)
                        result = invoke(
                            "query",
                            data,
                            lambda spec=spec: session.query(spec),
                            step.get("capture"),
                            query_kind=spec.kind.value,
                        )
                    elif op == "retract":
                        retract_payload = {
                            "source_id": str(step["source_id"]),
                            "known_at": str(step["known_at"]),
                        }
                        invoke(
                            "retract",
                            retract_payload,
                            lambda: session.retract(
                                retract_payload["source_id"],
                                retract_payload["known_at"],
                            ),
                            step.get("capture"),
                        )
                        operation_journal.append(("retract", retract_payload))
                    elif op == "register_module":
                        module = copy.deepcopy(module_data[step["module_id"]])
                        invoke(
                            "register_module",
                            module,
                            lambda module=module: session.register_module(module),
                            step.get("capture"),
                        )
                        operation_journal.append(
                            ("register_module", copy.deepcopy(module))
                        )
                    elif op == "clean_rebuild":
                        # Never trust candidate.clean_rebuild for a clean-oracle
                        # test.  Instantiate a genuinely fresh candidate and
                        # replay only runner-observed mutations.
                        rebuilt = provider()
                        replay_outcomes: list[dict[str, Any]] = []
                        for replay_op, payload in operation_journal:
                            if replay_op == "ingest":
                                artifact = _compile_artifact(payload)
                                replay_outcomes.append(
                                    invoke(
                                        "rebuild_replay_ingest",
                                        payload,
                                        lambda artifact=artifact, rebuilt=rebuilt: rebuilt.ingest(
                                            artifact
                                        ),
                                    )
                                )
                            elif replay_op == "register_module":
                                replay_module = copy.deepcopy(payload)
                                replay_outcomes.append(
                                    invoke(
                                        "rebuild_replay_register_module",
                                        payload,
                                        lambda module=replay_module, rebuilt=rebuilt: rebuilt.register_module(
                                            module
                                        ),
                                    )
                                )
                            elif replay_op == "retract":
                                replay_outcomes.append(
                                    invoke(
                                        "rebuild_replay_retract",
                                        payload,
                                        lambda payload=payload, rebuilt=rebuilt: rebuilt.retract(
                                            str(payload["source_id"]),
                                            str(payload["known_at"]),
                                        ),
                                    )
                                )
                        session = rebuilt
                        rebuild_result = _normalize_result(
                            CapabilityResult(
                                status=ResultStatus.OK,
                                validation="valid",
                                capability="runner_replay",
                                epistemic="not_applicable",
                                coverage_status="in_domain",
                                identification="not_applicable",
                                computation="exact",
                                value_kind="rebuild_receipt",
                                value={
                                    "replayed_operations": len(operation_journal)
                                },
                                diagnostics={
                                    "external_replay": True,
                                    "replay_statuses": [
                                        item.get("status")
                                        for item in replay_outcomes
                                    ],
                                },
                            )
                        )
                        call_index += 1
                        calls.append(
                            {
                                "branch_id": branch_id,
                                "call_index": call_index,
                                "op": "clean_rebuild",
                                "input_digest": _digest(
                                    {"journal": operation_journal}
                                ),
                                "result": rebuild_result,
                                "capture": step.get("capture"),
                                "query_kind": None,
                            }
                        )
                        if step.get("capture"):
                            ref = f"{branch_id}:{step['capture']}"
                            captures[ref] = rebuild_result
                            capture_inputs[ref] = {"op": "clean_rebuild"}
                    elif op == "explain":
                        invoke(
                            "explain",
                            step,
                            lambda: session.explain(str(step["result_id"])),
                            step.get("capture"),
                        )
                    else:
                        raise ValueError(f"unknown workload operation: {op!r}")
                except Exception as exc:
                    # Candidate exceptions are normalized by ``invoke``;
                    # fixture/protocol failures remain worker harness errors.
                    harness_errors.append(
                        f"branch {branch_id} step {op}: {type(exc).__name__}: {exc}"
                    )

    return {
        "protocol": PROTOCOL,
        "candidate_id": candidate_id,
        "manifest_snapshot": manifest_snapshot,
        "candidate_input_digest": _digest(public_view),
        "calls": calls,
        "captures": captures,
        "capture_inputs": capture_inputs,
        "harness_errors": harness_errors,
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--track", choices=("native", "companion"), required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.read()
        view = json.loads(raw)
        if not isinstance(view, Mapping):
            raise TypeError("candidate_view must be a JSON object")
        transcript = execute(args.candidate, args.track, view)
        # ASCII-only framing is intentional.  ``-I`` may ignore
        # PYTHONIOENCODING and Windows can otherwise encode non-ASCII candidate
        # diagnostics with the active console code page.
        sys.stdout.write(
            json.dumps(transcript, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        )
        sys.stdout.flush()
        return 0
    except Exception as exc:
        # Still emit only protocol JSON.  Do not print a traceback containing
        # host paths into the candidate channel.
        sys.stdout.write(
            json.dumps(
                {
                    "protocol": PROTOCOL,
                    "candidate_id": "unknown",
                    "manifest_snapshot": {},
                    "candidate_input_digest": None,
                    "calls": [],
                    "captures": {},
                    "capture_inputs": {},
                    "harness_errors": [
                        f"worker fatal: {type(exc).__name__}: {exc}"
                    ],
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        sys.stdout.flush()
        return 2


if __name__ == "__main__":  # pragma: no cover - always a subprocess entry
    raise SystemExit(_cli())
