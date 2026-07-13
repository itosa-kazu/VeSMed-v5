"""Executable, candidate-neutral benchmark runner.

The runner compiles only ``candidate_view`` objects into the frozen contract,
calls a real candidate, captures raw results, and evaluates runner-only oracles.
It never grants a pass from ``manifest`` claims.  Unsupported behavior is
reported on an independent boundary axis and does not become semantic coverage.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Callable, Mapping, Sequence

from .contract import (
    CapabilityResult,
    ClockSet,
    InfoState,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
)
from .reference_models import reference_output
from .workloads import candidate_view, oracle_view


BENCHMARK_VERSION = "archbench-runner-v1.1"
PASS = "pass"
FAIL = "fail"
NOT_APPLICABLE = "not_applicable"


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_finite": repr(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _digest(value: Any) -> str:
    encoded = json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class AssertionResult:
    assertion_id: str
    workload_id: str
    oracle_id: str
    oracle_kind: str
    dimension: str
    verdict_axis: str
    hard_gate: bool
    passed: bool
    semantic_eligible: bool = True
    ineligible_refs: list[str] = field(default_factory=list)
    observed: Any = None
    expected: Any = None
    evidence_refs: list[str] = field(default_factory=list)
    diagnostic: str = ""
    oracle_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class VerdictVector:
    behavior: str
    boundary: str
    trace: str
    numerical: str
    hard: str
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CallRecord:
    branch_id: str
    call_index: int
    op: str
    input_digest: str
    result: dict[str, Any]
    capture: str | None = None
    # Runner-owned request metadata.  In particular, query_kind must never be
    # injected into a candidate's result merely to help the harness classify a
    # refusal.
    query_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class WorkloadRun:
    benchmark_version: str
    workload_id: str
    candidate_id: str
    manifest_snapshot: dict[str, Any]
    candidate_input_digest: str
    calls: list[CallRecord]
    captures: dict[str, dict[str, Any]]
    assertions: list[AssertionResult]
    verdict: VerdictVector
    harness_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)


class HarnessError(RuntimeError):
    pass


def _compile_artifact(data: Mapping[str, Any]) -> SourceArtifact:
    scope_data = data["scope"]
    clocks_data = data["clocks"]
    return SourceArtifact(
        artifact_id=str(data["artifact_id"]),
        source_id=str(data["source_id"]),
        semantic_role=SemanticRole(data["semantic_role"]),
        concept=str(data["concept"]),
        scope=Scope(**scope_data),
        clocks=ClockSet(**clocks_data),
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
            "runner_synthesized": True,
        },
    ).to_dict()


def _normalize_result(result: Any) -> dict[str, Any]:
    if isinstance(result, CapabilityResult):
        out = result.to_dict()
    elif isinstance(result, Mapping):
        out = _plain(result)
    else:
        return _invalid_result(f"candidate returned non-result type {type(result).__name__}")
    if not isinstance(out.get("status"), str):
        return _invalid_result("candidate result lacks string status")
    # Orthogonal axes are mandatory in the frozen contract.  Missing axes are
    # recorded explicitly rather than silently inferred from status.
    defaults = {
        "validation": "unknown", "capability": "unknown", "epistemic": "unknown",
        "coverage_status": "unknown", "identification": "unknown", "computation": "unknown",
        "value_kind": "none", "value": None, "assumptions": [], "coverage": {}, "time_cut": {},
        "evidence_witness": {}, "native_witness": {}, "diagnostics": {}, "versions": {},
    }
    for key, value in defaults.items():
        out.setdefault(key, copy.deepcopy(value))
    return _plain(out)


def _instantiate(provider: Any, *, first: bool) -> Any:
    """Accept a zero-arg factory/class; object fallback is best-effort only."""

    if isinstance(provider, type):
        return provider()
    if callable(provider) and not hasattr(provider, "query"):
        return provider()
    if first:
        return provider
    cls = provider.__class__
    try:
        return cls(track=getattr(provider, "track", None))
    except Exception:
        try:
            return cls()
        except Exception as exc:
            raise HarnessError("multiple fresh branches require a candidate factory") from exc


def _manifest(candidate: Any) -> dict[str, Any]:
    try:
        manifest = candidate.manifest
        if callable(manifest):
            manifest = manifest()
        return _plain(manifest)
    except Exception as exc:
        return {"candidate_id": candidate.__class__.__name__, "manifest_error": f"{type(exc).__name__}: {exc}"}


def _candidate_id(manifest: Mapping[str, Any], candidate: Any) -> str:
    value = manifest.get("candidate_id")
    return str(value) if value else candidate.__class__.__name__


def _pointer(value: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return value
    current = value
    for part in pointer.lstrip("/").split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(key)]
        elif isinstance(current, Mapping):
            current = current[key]
        else:
            raise KeyError(pointer)
    return current


_ALWAYS_VOLATILE_KEYS = {"runtime_ms", "digest"}
_GENERATED_ID_KEYS = {
    "result_id", "claim_id", "claim_ids", "parent_claim_id", "support_claim_ids",
    "proof_id", "proof_ids", "premise_proof_ids", "derivation_id", "derivation_ids",
    "support_ids", "fact_id", "fact_ids",
}
_ROOT_ID_KEYS = {
    "artifact_id", "artifact_ids", "source_id", "source_ids", "root_sources", "root_ids",
    "root_artifacts", "root_source_ids", "roots",
}


def _id_role(key: str, *, ignore_roots: bool) -> str | None:
    """Return a schema role for opaque identifiers, never for versions.

    Dropping every ``*_id`` field made two unrelated proof graphs compare equal
    and, worse, could erase mapping/model-version evidence.  Instead we alpha-
    rename only identifiers whose schema declares them opaque.  Repeated IDs
    remain repeated, so proof connectivity and cardinality are preserved.
    """

    if key in _GENERATED_ID_KEYS:
        if "proof" in key:
            return "proof"
        if "claim" in key or "fact" in key or key == "support_ids":
            return "claim"
        return "generated"
    if ignore_roots and key in _ROOT_ID_KEYS:
        if "artifact" in key:
            return "artifact"
        return "source"
    return None


def _collect_ids(value: Any, *, ignore_roots: bool, current_key: str | None = None,
                 found: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    found = found if found is not None else {}
    role = _id_role(current_key, ignore_roots=ignore_roots) if current_key else None
    if role is not None:
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                if isinstance(item, (str, int)):
                    found.setdefault(role, set()).add(str(item))
        elif isinstance(value, (str, int)):
            found.setdefault(role, set()).add(str(value))
        # A mapping under an ID-bearing field is structure, not an opaque ID.
    if isinstance(value, Mapping):
        for key, item in value.items():
            _collect_ids(item, ignore_roots=ignore_roots, current_key=str(key), found=found)
    elif isinstance(value, (list, tuple, set, frozenset)) and role is None:
        for item in value:
            _collect_ids(item, ignore_roots=ignore_roots, current_key=current_key, found=found)
    return found


def _semantic(value: Any, *, ignore_roots: bool = False) -> Any:
    found = _collect_ids(value, ignore_roots=ignore_roots)
    aliases = {
        role: {identifier: f"<{role}:{index}>" for index, identifier in enumerate(sorted(identifiers))}
        for role, identifiers in found.items()
    }

    def normalize(item: Any, current_key: str | None = None) -> Any:
        role = _id_role(current_key, ignore_roots=ignore_roots) if current_key else None
        if role is not None and isinstance(item, (str, int)):
            return aliases.get(role, {}).get(str(item), f"<{role}:unknown>")
        if isinstance(item, Mapping):
            out: dict[str, Any] = {}
            for key, child in item.items():
                key = str(key)
                if key in _ALWAYS_VOLATILE_KEYS:
                    continue
                # Raw spelling is a property of a root artifact, not of the
                # normalized clinical meaning.  Preserve that a payload exists,
                # while keeping mapping_version/model_version untouched.
                if ignore_roots and key == "raw_payload":
                    out[key] = "<root-payload>"
                    continue
                out[key] = normalize(child, key)
            return out
        if isinstance(item, (list, tuple, set, frozenset)):
            normalized = [normalize(child, current_key) for child in item]
            try:
                return sorted(normalized, key=lambda child: json.dumps(child, sort_keys=True, ensure_ascii=False))
            except Exception:
                return normalized
        return item

    return normalize(value)


def _deep_strings(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [str(key) for key in value] + [item for child in value.values() for item in _deep_strings(child)]
    if isinstance(value, (list, tuple, set)):
        return [item for child in value for item in _deep_strings(child)]
    return [str(value)]


_SEMANTICALLY_INELIGIBLE_STATUSES = {"unsupported", "invalid", "out_of_model", "insufficient"}


def _semantically_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Mapping):
        return not value or all(_semantically_empty(child) for child in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return not value or all(_semantically_empty(child) for child in value)
    return False


def _leaf_scalars(value: Any) -> list[Any]:
    if isinstance(value, Mapping):
        return [leaf for child in value.values() for leaf in _leaf_scalars(child)]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [leaf for child in value for leaf in _leaf_scalars(child)]
    if value is None:
        return []
    return [value]


def _query_echo_only(result: Mapping[str, Any], request: Mapping[str, Any] | None) -> bool:
    """Reject an ``ok`` result that merely repeats its QuerySpec.

    This is intentionally conservative: a non-empty evidence/native witness is
    enough to avoid the echo label, as is any value not present in the request.
    It therefore catches red-team ``return query.to_dict()`` implementations
    without rejecting a genuine projection that happens to repeat its target.
    """

    if request is None or result.get("status") != "ok":
        return False
    value = result.get("value")
    if _semantically_empty(value):
        return True
    evidence = result.get("evidence_witness")
    native = result.get("native_witness")
    if not _semantically_empty(evidence) or not _semantically_empty(native):
        return False
    request_leaves = {_digest(leaf) for leaf in _leaf_scalars(request)}
    value_leaves = _leaf_scalars(value)
    return bool(value_leaves) and all(_digest(leaf) in request_leaves for leaf in value_leaves)


def _semantic_eligibility(
    result: Mapping[str, Any],
    *,
    request: Mapping[str, Any] | None = None,
    allowed_statuses: Sequence[str] = (),
    allow_unsupported_capability: bool = False,
) -> tuple[bool, str]:
    status = str(result.get("status", ""))
    capability = str(result.get("capability", ""))
    allowed = {str(item) for item in allowed_statuses}
    reasons: list[str] = []
    if status in _SEMANTICALLY_INELIGIBLE_STATUSES and status not in allowed:
        reasons.append(f"status={status}")
    if capability == "unsupported" and not allow_unsupported_capability:
        reasons.append("capability=unsupported")
    if result.get("validation") == "invalid":
        reasons.append("validation=invalid")
    if _query_echo_only(result, request):
        reasons.append("empty/query-echo result")
    return not reasons, ", ".join(reasons)


def _roots(result: Mapping[str, Any]) -> set[str]:
    roots: set[str] = set()
    witness = result.get("evidence_witness", {})
    if isinstance(witness, Mapping):
        for key in ("root_sources", "root_ids", "roots"):
            values = witness.get(key, [])
            if isinstance(values, (list, tuple, set)):
                roots.update(str(value) for value in values)
    value = result.get("value")
    if isinstance(value, Mapping):
        claims = value.get("claims", [])
        if isinstance(claims, list):
            for claim in claims:
                if isinstance(claim, Mapping):
                    for item in claim.get("root_sources", []):
                        roots.add(str(item))
    return roots


def _information_states(result: Mapping[str, Any]) -> set[str]:
    states: set[str] = set()
    for key in ("epistemic", "information_state"):
        value = result.get(key)
        if isinstance(value, str):
            states.add(value)

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in {"information_state", "epistemic"} and isinstance(child, str):
                    states.add(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result.get("value"))
    if result.get("status") == "conflicting":
        states.add("conflicting")
    if result.get("status") == "insufficient":
        states.update({"insufficient", "unknown"})
    return states


_BOUNDARY_DIAGNOSTIC_METADATA = {
    # Identifiers and request echoes are useful for correlation, but do not
    # explain why the candidate refused the operation.
    "result_id", "query_id", "target", "task", "query_kind",
    "operation", "state_mutated", "rebuild_origin",
}


def _candidate_boundary_explanation(result: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Return whether a refusal carries a candidate-authored explanation.

    Candidates use different, still typed diagnostic vocabularies (``reason``,
    ``error``, ``missing_capability``, ``unsupported_guarantees`` ...).  Requiring
    the literal key ``reason`` created a family-specific false negative.  We
    accept non-empty candidate diagnostics after removing correlation-only
    metadata, and also inspect a value-local diagnostics block.  Runner-created
    exception wrappers remain ineligible.

    Some orthogonal result axes are themselves a complete structured reason:
    e.g. ``insufficient + masked``, ``insufficient + in_domain`` or
    ``out_of_model + coverage=out_of_model``.  This keeps a prose field from
    becoming a hidden mandatory API while still rejecting a bare status enum.
    """

    diagnostic = result.get("diagnostics")
    if not isinstance(diagnostic, Mapping):
        diagnostic = {}
    if diagnostic.get("runner_synthesized") or diagnostic.get("candidate_raised"):
        return False, []

    blocks: list[Mapping[str, Any]] = [diagnostic]
    value = result.get("value")
    if isinstance(value, Mapping) and isinstance(value.get("diagnostics"), Mapping):
        blocks.append(value["diagnostics"])

    keys: list[str] = []
    for block in blocks:
        for key, item in block.items():
            key = str(key)
            if key in _BOUNDARY_DIAGNOSTIC_METADATA or _semantically_empty(item):
                continue
            keys.append(key)

    status = str(result.get("status"))
    epistemic = str(result.get("epistemic"))
    coverage = str(result.get("coverage_status"))
    computation = str(result.get("computation"))
    structured_reason = (
        (
            status == "insufficient"
            and (
                epistemic not in {"", "unknown", "insufficient", "not_applicable"}
                or coverage not in {"", "unknown", "not_evaluated", "not_applicable"}
            )
        )
        or (status == "out_of_model" and coverage == "out_of_model")
        or (
            status == "numerical_failure"
            and computation in {"not_converged", "no_solution", "multiple_solutions", "numerical_failure"}
        )
        or (status == "conflicting" and epistemic == "conflicting")
    )
    if structured_reason:
        keys.append("structured_result_axes")
    return bool(keys), sorted(set(keys))


def _typed_boundary(result: Mapping[str, Any], allowed: Sequence[str]) -> tuple[bool, str]:
    status = str(result.get("status"))
    if status not in allowed:
        return False, f"status={status!r} not in {list(allowed)!r}"
    validation = result.get("validation")
    capability = result.get("capability")
    epistemic = result.get("epistemic")
    coverage = result.get("coverage_status")
    identification = result.get("identification")
    computation = result.get("computation")
    typed = False
    if status == "invalid":
        typed = validation == "invalid"
    elif status == "unsupported":
        typed = capability == "unsupported"
    elif status == "insufficient":
        typed = epistemic in {
            "unknown", "insufficient", "not_asked", "not_tested", "unable_to_assess",
            "masked", "censored_low", "censored_high",
        } or coverage in {"partial", "unknown"}
    elif status == "out_of_model":
        typed = coverage == "out_of_model"
    elif status == "numerical_failure":
        typed = computation in {"not_converged", "no_solution", "multiple_solutions", "numerical_failure"}
    elif status == "conflicting":
        typed = epistemic == "conflicting"
    has_reason, reason_keys = _candidate_boundary_explanation(result)
    return typed and has_reason, (
        f"status={status}, validation={validation}, capability={capability}, epistemic={epistemic}, "
        f"coverage={coverage}, identification={identification}, computation={computation}, "
        f"candidate_reason={has_reason}, reason_keys={reason_keys}"
    )


def _numeric_candidate(result: Mapping[str, Any], paths: Sequence[str]) -> float:
    def convert(value: Any) -> float:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        if isinstance(value, list):
            # Probability of the positive/high value is the common finite-model
            # readout used by the E02/E03 exact references.
            rows = [row for row in value if isinstance(row, Mapping) and "probability" in row]
            if rows:
                positive = [row for row in rows if row.get("value", row.get("state")) in (1, 1.0, True)]
                row = positive[0] if positive else max(rows, key=lambda item: float(item.get("value", item.get("state", 0))))
                return float(row["probability"])
        if isinstance(value, Mapping):
            for key in ("mean", "probability", "value", "state", "result"):
                if key in value:
                    return convert(value[key])
        raise TypeError(f"not a numeric result: {value!r}")

    errors = []
    for path in paths:
        try:
            return convert(_pointer(result, path))
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    raise TypeError("; ".join(errors))


def _trajectory_numbers(value: Any) -> tuple[dict[tuple[Any, str], float], list[tuple[Any, str]]]:
    rows = value if isinstance(value, list) else value.get("trajectory", []) if isinstance(value, Mapping) else []
    out: dict[tuple[Any, str], float] = {}
    duplicates: list[tuple[Any, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        time = row.get("hour", row.get("time", row.get("step", index)))
        for key, item in row.items():
            if key in {"hour", "time", "step"}:
                continue
            if isinstance(item, (int, float)) and math.isfinite(float(item)):
                coordinate = (time, str(key))
                if coordinate in out:
                    duplicates.append(coordinate)
                else:
                    out[coordinate] = float(item)
    return out, duplicates


def _closed_linear_recurrence_rows(spec: Mapping[str, Any]) -> list[dict[str, float]]:
    """Evaluate the frozen scalar recurrence IR without fixture-ID dispatch.

    The benchmark-side interpreter is deliberately tiny and closed.  It is an
    oracle for a public mathematical commitment, not a clinical model and not
    candidate code.  Full coordinates from t=0 through the requested horizon
    are returned so a single correct/fixed number cannot satisfy the test.
    """

    allowed = {
        "op", "state", "coefficient", "input", "initial", "step_hours", "horizon_hours",
    }
    unknown = set(spec) - allowed
    if unknown:
        raise ValueError(f"closed recurrence has unknown fields: {sorted(unknown)}")
    if spec.get("op") != "linear_recurrence":
        raise ValueError("closed recurrence op must be linear_recurrence")
    state = spec.get("state")
    if not isinstance(state, str) or not state:
        raise ValueError("closed recurrence state must be a non-empty string")

    def finite_number(name: str) -> float:
        value = spec.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"closed recurrence {name} must be finite numeric")
        return float(value)

    coefficient = finite_number("coefficient")
    forcing = finite_number("input")
    value = finite_number("initial")
    step_hours = finite_number("step_hours")
    horizon_hours = finite_number("horizon_hours")
    if step_hours <= 0 or horizon_hours < 0:
        raise ValueError("step_hours must be positive and horizon_hours non-negative")
    raw_steps = horizon_hours / step_hours
    steps = round(raw_steps)
    if not math.isclose(raw_steps, steps, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("horizon_hours must be an integer multiple of step_hours")
    if steps > 10_000:
        raise ValueError("closed recurrence exceeds benchmark coordinate budget")

    rows: list[dict[str, float]] = [{"hour": 0.0, state: value}]
    for index in range(1, steps + 1):
        value = coefficient * value + forcing
        rows.append({"hour": index * step_hours, state: value})
    return rows


def _oracle_axis(oracle_id: str) -> str:
    if oracle_id.startswith("reference.") or oracle_id in {
        "result.numeric_diagnostics@1", "result.computation@1", "result.numeric_contract@1",
    }:
        return "numerical"
    if oracle_id.startswith("evidence."):
        return "trace"
    if oracle_id in {"result.typed_boundary@1", "result.axis@1", "result.identification_boundary@1"}:
        return "boundary"
    return "behavior"


def _oracle_kind(oracle_id: str) -> str:
    if oracle_id.startswith("reference."):
        return "reference"
    if oracle_id in {"result.equivalent@1", "result.distinct@1", "evidence.same_roots@1"}:
        return "metamorphic"
    if (
        oracle_id.startswith("result.typed_boundary")
        or oracle_id.startswith("result.axis")
        or oracle_id.startswith("result.identification_boundary")
    ):
        return "honesty"
    return "behavior"


def _mapping_nodes(value: Any) -> list[Mapping[str, Any]]:
    nodes: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        nodes.append(value)
        for child in value.values():
            nodes.extend(_mapping_nodes(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            nodes.extend(_mapping_nodes(child))
    return nodes


def _direct_identity_values(node: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in _ROOT_ID_KEYS:
        if key not in node:
            continue
        value = node[key]
        if isinstance(value, (list, tuple, set, frozenset)):
            values.update(str(item) for item in value if isinstance(item, (str, int)))
        elif isinstance(value, (str, int)):
            values.add(str(value))
    return values


def _field_values(value: Any, names: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in names:
                found.append(child)
            found.extend(_field_values(child, names))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.extend(_field_values(child, names))
    return found


def _raw_roundtrip(result: Mapping[str, Any], args: Mapping[str, Any]) -> tuple[bool, Any, Any, str]:
    expected = copy.deepcopy(args.get("expected", {}))
    if not expected:
        expected = {
            str(key): copy.deepcopy(value)
            for key, value in args.items()
            if key not in {"result", "root"}
        }
    if not isinstance(expected, Mapping):
        return False, None, expected, "expected must be a mapping"
    root = args.get("root", expected.get("root", expected.get("source_id", expected.get("artifact_id"))))
    if root is None:
        return False, None, expected, "raw-roundtrip oracle requires root/source_id/artifact_id"
    root = str(root)
    nodes = [node for node in _mapping_nodes(result) if root in _direct_identity_values(node)]
    if not nodes:
        return False, {"root": root, "associated_nodes": 0}, expected, "no record directly links the requested root"

    aliases = {
        "root": _ROOT_ID_KEYS,
        "source_id": {"source_id", "root_source_id"},
        "artifact_id": {"artifact_id", "root_artifact_id"},
        "raw_value": {"raw_value", "value"},
        "raw_unit": {"raw_unit", "unit"},
        "mapping_version": {"mapping_version", "mapping"},
        "span": {"span"},
        "raw_payload": {"raw_payload"},
    }
    missing: list[str] = []
    observed: dict[str, Any] = {"root": root, "associated_nodes": len(nodes)}
    for key, wanted in expected.items():
        if key == "root":
            continue
        names = aliases.get(str(key), {str(key)})
        values = [item for node in nodes for item in _field_values(node, set(names))]
        observed[str(key)] = values
        if not any(_semantic(item) == _semantic(wanted) for item in values):
            missing.append(str(key))
    return not missing, observed, expected, f"missing_or_mismatched={missing}"


def _evaluate_assertion(
    workload_id: str,
    assertion: Mapping[str, Any],
    captures: Mapping[str, dict[str, Any]],
    capture_inputs: Mapping[str, Mapping[str, Any]] | None = None,
) -> AssertionResult:
    assertion_id = str(assertion["assertion_id"])
    oracle_id = str(assertion["oracle_id"])
    args = assertion.get("args", {})
    observed: Any = None
    expected: Any = None
    passed = False
    diagnostic = ""
    evidence_refs: list[str] = []
    semantic_eligible = True
    ineligible_refs: list[str] = []
    capture_inputs = capture_inputs or {}

    def result(ref: str) -> dict[str, Any]:
        evidence_refs.append(ref)
        try:
            return captures[ref]
        except KeyError as exc:
            raise KeyError(f"missing capture {ref}") from exc

    try:
        if oracle_id == "result.status@1":
            item = result(args["result"]); observed = item.get("status"); expected = args["expected"]
            passed = observed in expected
        elif oracle_id == "result.contains_all@1":
            item = result(args["result"]); tokens = set(_deep_strings(item.get("value"))); expected = args["expected"]
            missing = [str(value) for value in expected if str(value) not in tokens]
            observed = sorted(tokens); passed = not missing; diagnostic = f"missing={missing}"
        elif oracle_id == "result.not_contains@1":
            item = result(args["result"]); tokens = set(_deep_strings(item.get("value"))); expected = args["forbidden"]
            observed = sorted(tokens); passed = str(expected) not in tokens
        elif oracle_id in {"result.distinct@1", "result.equivalent@1"}:
            left = result(args["left"]); right = result(args["right"])
            semantic_only = bool(args.get("semantic_only"))
            left_value = left.get("value") if semantic_only else left
            right_value = right.get("value") if semantic_only else right
            left_norm = _semantic(left_value, ignore_roots=bool(args.get("ignore_roots")))
            right_norm = _semantic(right_value, ignore_roots=bool(args.get("ignore_roots")))
            equal = left_norm == right_norm
            passed = not equal if oracle_id == "result.distinct@1" else equal
            observed = {"left_digest": _digest(left_norm), "right_digest": _digest(right_norm), "equal": equal}
            expected = "distinct" if oracle_id == "result.distinct@1" else "equivalent"
        elif oracle_id == "result.information_state@1":
            item = result(args["result"]); observed = sorted(_information_states(item)); expected = args["expected"]
            passed = bool(set(observed) & set(expected))
        elif oracle_id == "result.typed_boundary@1":
            item = result(args["result"]); passed, diagnostic = _typed_boundary(item, args["allowed"])
            observed = {key: item.get(key) for key in ("status", "validation", "capability", "epistemic", "coverage_status", "identification", "computation", "diagnostics")}
            expected = args["allowed"]
        elif oracle_id == "result.identification_boundary@1":
            item = result(args["result"])
            identification = item.get("identification")
            typed_insufficient, typed_diagnostic = _typed_boundary(item, ["insufficient"])
            passed = identification == "not_identified" or (
                item.get("status") == "insufficient" and typed_insufficient
            )
            observed = {
                "status": item.get("status"),
                "identification": identification,
                "diagnostics": item.get("diagnostics"),
            }
            expected = "identification=not_identified or typed insufficient"
            diagnostic = typed_diagnostic if item.get("status") == "insufficient" else f"identification={identification}"
        elif oracle_id == "result.axis@1":
            item = result(args["result"]); axis = args["axis"]; observed = item.get(axis); expected = args["expected"]
            passed = observed in expected
        elif oracle_id == "result.computation@1":
            item = result(args["result"]); observed = item.get("computation"); expected = args["expected"]
            passed = observed in expected
        elif oracle_id == "result.numeric_diagnostics@1":
            item = result(args["result"]); computation = item.get("computation"); diagnostics = item.get("diagnostics", {})
            observed = {"computation": computation, "diagnostics": diagnostics}
            passed = computation not in {None, "unknown", "not_applicable"} and isinstance(diagnostics, Mapping) and bool(diagnostics)
        elif oracle_id == "result.numeric_contract@1":
            item = result(args["result"])
            computation = item.get("computation")
            diagnostics = item.get("diagnostics", {})
            keys = set(_deep_strings(diagnostics)) if isinstance(diagnostics, Mapping) else set()
            accepted = set(args.get(
                "allowed_computation",
                ["exact", "approximate", "approx", "not_converged", "numerical_failure"],
            ))
            required = args.get("required_diagnostics", {})
            has_seed = (
                isinstance(diagnostics, Mapping)
                and ("seed" in diagnostics if required.get("seed", True) else True)
            )
            error_keys = set(required.get("error_any_of", ["error", "error_bound", "tolerance", "residual"]))
            has_error_control = bool(keys & error_keys)
            passed = computation in accepted and has_seed and has_error_control
            observed = {"computation": computation, "has_seed": has_seed, "error_control_keys": sorted(keys & error_keys)}
            expected = {"computation": sorted(accepted), "diagnostics": ["seed", "error|error_bound|tolerance|residual"]}
            diagnostic = f"has_seed={has_seed}, has_error_control={has_error_control}"
        elif oracle_id in {"evidence.root_count@1", "evidence.root_present@1"}:
            item = result(args["result"]); roots = _roots(item); observed = sorted(roots)
            if oracle_id == "evidence.root_count@1":
                expected = int(args["expected"]); passed = len(roots) == expected
            else:
                expected = args["root"]; passed = str(expected) in roots
        elif oracle_id == "evidence.same_roots@1":
            left = _roots(result(args["left"])); right = _roots(result(args["right"])); observed = {"left": sorted(left), "right": sorted(right)}
            passed = left == right; expected = "same root set"
        elif oracle_id == "evidence.raw_roundtrip@1":
            item = result(args["result"])
            passed, observed, expected, diagnostic = _raw_roundtrip(item, args)
        elif oracle_id == "evidence.no_unasserted_independence@1":
            item = result(args["result"]); witness = item.get("evidence_witness", {})
            asserted = witness.get("statistical_independence_assumed") if isinstance(witness, Mapping) else None
            observed = asserted; expected = False; passed = asserted is False
        elif oracle_id == "temporal.root_visibility@1":
            item = result(args["result"]); visible = str(args["root"]) in _roots(item); observed = visible; expected = bool(args["visible"]); passed = visible is expected
        elif oracle_id == "reference.scalar@1":
            item = result(args["result"]); reference = reference_output(args["reference_id"])
            expected = float(_pointer(reference, args["reference_path"]))
            observed = _numeric_candidate(item, args["candidate_paths"])
            passed = abs(observed - expected) <= float(args.get("absolute_tolerance", 0.0))
            diagnostic = f"abs_error={abs(observed - expected):.6g}"
        elif oracle_id == "reference.trajectory@1":
            item = result(args["result"]); reference = reference_output(args["reference_id"])
            expected_rows = _pointer(reference, args["reference_path"])
            candidate_rows = item.get("value", {}).get("trajectory", []) if isinstance(item.get("value"), Mapping) else item.get("value")
            expected_numbers, expected_duplicates = _trajectory_numbers(expected_rows)
            observed_numbers, observed_duplicates = _trajectory_numbers(candidate_rows)
            common = sorted(set(expected_numbers) & set(observed_numbers), key=repr)
            missing = sorted(set(expected_numbers) - set(observed_numbers), key=repr)
            coverage = len(common) / len(expected_numbers) if expected_numbers else 0.0
            if expected_duplicates:
                passed = False; diagnostic = f"invalid reference duplicate coordinates={expected_duplicates!r}"
            elif observed_duplicates:
                passed = False; diagnostic = f"candidate duplicate coordinates={observed_duplicates!r}"
            elif not expected_numbers:
                passed = False; diagnostic = "reference has no numeric trajectory coordinates"
            elif missing:
                passed = False; diagnostic = f"coverage={coverage:.6f}, missing={missing!r}"
            else:
                errors = [observed_numbers[key] - expected_numbers[key] for key in expected_numbers]
                rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
                scale = max((abs(expected_numbers[key]) for key in expected_numbers), default=1.0)
                tolerance = float(args.get("absolute_tolerance", 0.0)) + float(args.get("relative_tolerance", 0.0)) * scale
                passed = coverage == 1.0 and rmse <= tolerance
                diagnostic = f"coverage={coverage:.6f}, coordinates={len(common)}, rmse={rmse:.6g}, tolerance={tolerance:.6g}"
            observed = {
                "coordinates": len(observed_numbers), "matched": len(common), "coverage": coverage,
                "duplicates": _plain(observed_duplicates), "digest": _digest(observed_numbers),
            }
            expected = {"coordinates": len(expected_numbers), "coverage": 1.0, "digest": _digest(expected_numbers)}
        elif oracle_id == "reference.closed_recurrence@1":
            item = result(args["result"])
            recurrence = args["closed_recurrence"]
            if not isinstance(recurrence, Mapping):
                raise TypeError("closed_recurrence must be a mapping")
            target = str(args["target"])
            horizon_hours = float(args["horizon_hours"])
            if recurrence.get("state") != target:
                raise ValueError("reference target does not match recurrence state")
            if not math.isclose(float(recurrence.get("horizon_hours")), horizon_hours, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("reference horizon does not match query horizon")
            expected_rows = _closed_linear_recurrence_rows(recurrence)
            candidate_rows = item.get("value", {}).get("trajectory", []) if isinstance(item.get("value"), Mapping) else item.get("value")
            expected_numbers, expected_duplicates = _trajectory_numbers(expected_rows)
            observed_numbers, observed_duplicates = _trajectory_numbers(candidate_rows)
            common = sorted(set(expected_numbers) & set(observed_numbers), key=repr)
            missing = sorted(set(expected_numbers) - set(observed_numbers), key=repr)
            coverage = len(common) / len(expected_numbers) if expected_numbers else 0.0
            if expected_duplicates:
                passed = False; diagnostic = f"invalid closed reference duplicate coordinates={expected_duplicates!r}"
            elif observed_duplicates:
                passed = False; diagnostic = f"candidate duplicate coordinates={observed_duplicates!r}"
            elif not expected_numbers:
                passed = False; diagnostic = "closed recurrence produced no numeric coordinates"
            elif missing:
                passed = False; diagnostic = f"coverage={coverage:.6f}, missing={missing!r}"
            else:
                errors = [observed_numbers[key] - expected_numbers[key] for key in expected_numbers]
                rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
                scale = max((abs(expected_numbers[key]) for key in expected_numbers), default=1.0)
                tolerance = float(args.get("absolute_tolerance", 0.0)) + float(args.get("relative_tolerance", 0.0)) * scale
                passed = coverage == 1.0 and rmse <= tolerance
                diagnostic = (
                    f"target={target}, horizon_hours={horizon_hours:g}, coverage={coverage:.6f}, "
                    f"coordinates={len(common)}, rmse={rmse:.6g}, tolerance={tolerance:.6g}"
                )
            observed = {
                "target": target, "horizon_hours": horizon_hours,
                "coordinates": len(observed_numbers), "matched": len(common), "coverage": coverage,
                "duplicates": _plain(observed_duplicates), "digest": _digest(observed_numbers),
            }
            expected = {
                "target": target, "horizon_hours": horizon_hours,
                "coordinates": len(expected_numbers), "coverage": 1.0, "digest": _digest(expected_numbers),
            }
        else:
            raise KeyError(f"unregistered oracle: {oracle_id}")
    except Exception as exc:
        passed = False
        diagnostic = f"oracle evaluation error: {type(exc).__name__}: {exc}"

    # A correct-looking payload attached to an unsupported/invalid result is
    # not semantic evidence.  Honesty/boundary assertions are the sole default
    # exception; a workload may explicitly allow a status for a specialised
    # semantic assertion via ``allow_ineligible_statuses``.
    if _oracle_kind(oracle_id) != "honesty":
        allowed_statuses = args.get("allow_ineligible_statuses", args.get("allow_semantic_statuses", ()))
        allow_unsupported_capability = bool(args.get("allow_unsupported_capability", False))
        for ref in evidence_refs:
            if ref not in captures:
                continue
            eligible, why = _semantic_eligibility(
                captures[ref],
                request=capture_inputs.get(ref),
                allowed_statuses=allowed_statuses,
                allow_unsupported_capability=allow_unsupported_capability,
            )
            if not eligible:
                semantic_eligible = False
                ineligible_refs.append(ref)
                passed = False
                diagnostic = (diagnostic + "; " if diagnostic else "") + f"semantic-ineligible {ref}: {why}"

    return AssertionResult(
        assertion_id=assertion_id,
        workload_id=workload_id,
        oracle_id=oracle_id,
        oracle_kind=_oracle_kind(oracle_id),
        dimension=str(assertion.get("dimension", "unknown")),
        verdict_axis=_oracle_axis(oracle_id),
        hard_gate=bool(assertion.get("hard_gate", False)),
        passed=passed,
        semantic_eligible=semantic_eligible,
        ineligible_refs=ineligible_refs,
        observed=_plain(observed),
        expected=_plain(expected),
        evidence_refs=evidence_refs,
        diagnostic=diagnostic,
    )


def _axis(assertions: Sequence[AssertionResult], axis: str) -> str:
    relevant = [item for item in assertions if item.verdict_axis == axis]
    if not relevant:
        return NOT_APPLICABLE
    return PASS if all(item.passed for item in relevant) else FAIL


def _manifest_claims(manifest: Mapping[str, Any]) -> set[str]:
    values = manifest.get("declared_query_capabilities", [])
    return {str(value) for value in values} if isinstance(values, list) else set()


def _explicit_manifest_contradiction(call: CallRecord, manifest: Mapping[str, Any]) -> bool:
    """Detect only an explicit contradiction, not contextual non-coverage.

    A manifest declaration for ``project`` does not promise every target,
    knowledge/model version, task or requested guarantee.  Treating any
    contextual ``unsupported`` as dishonesty made honest scoped refusals look
    deceptive.  A contradiction is mechanical only when the candidate says
    that the *query kind itself* is missing despite declaring it, or when a
    manifest explicitly marks the kind unconditional.
    """

    query_kind = str(call.query_kind) if call.query_kind else None
    if not query_kind or query_kind not in _manifest_claims(manifest):
        return False
    if call.result.get("status") != "unsupported":
        return False
    unconditional = manifest.get("unconditional_query_capabilities", [])
    if isinstance(unconditional, list) and query_kind in {str(item) for item in unconditional}:
        return True
    diagnostics = call.result.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        return False
    if diagnostics.get("contradicts_manifest") is True:
        return True
    for key in ("unsupported_query_kind", "missing_query_kind", "missing_capability"):
        value = diagnostics.get(key)
        if isinstance(value, str) and value == query_kind:
            return True
    return False


def _boundary_from_calls(calls: Sequence[CallRecord], manifest: Mapping[str, Any]) -> tuple[str, bool]:
    refusals = [call for call in calls if call.result.get("status") in {"unsupported", "insufficient", "out_of_model", "invalid", "numerical_failure"}]
    if not refusals:
        return NOT_APPLICABLE, False
    explicit = True
    dishonest = False
    for call in refusals:
        status = call.result.get("status")
        typed, _ = _typed_boundary(call.result, [status])
        explicit &= typed
        dishonest |= _explicit_manifest_contradiction(call, manifest)
    return (PASS if explicit else FAIL), dishonest


class BenchmarkRunner:
    """Run one candidate factory against one or more frozen workloads."""

    def __init__(self, candidate_provider: Any) -> None:
        self.candidate_provider = candidate_provider

    def run(self, workload: Mapping[str, Any]) -> WorkloadRun:
        workload_id = str(workload["workload_id"])
        view = candidate_view(workload)
        # Re-serialize the candidate view before execution.  This both proves
        # JSON transportability and avoids sharing mutable oracle-side objects.
        view = json.loads(json.dumps(view, ensure_ascii=False, sort_keys=True))
        fixtures = view["fixtures"]
        artifact_data = {item["artifact_id"]: item for item in fixtures.get("artifacts", [])}
        query_data = {item["query_id"]: item for item in fixtures.get("queries", [])}
        module_data = {item["module_id"]: item for item in fixtures.get("modules", [])}
        calls: list[CallRecord] = []
        captures: dict[str, dict[str, Any]] = {}
        capture_inputs: dict[str, Mapping[str, Any]] = {}
        harness_errors: list[str] = []
        manifest_snapshot: dict[str, Any] = {}
        candidate_id = "unknown"
        first = True

        for branch in view.get("branches", []):
            branch_id = str(branch["branch_id"])
            try:
                session = _instantiate(self.candidate_provider, first=first)
                first = False
            except Exception as exc:
                harness_errors.append(f"branch {branch_id} instantiation: {type(exc).__name__}: {exc}")
                continue
            if not manifest_snapshot:
                manifest_snapshot = _manifest(session)
                candidate_id = _candidate_id(manifest_snapshot, session)

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
                    raw = function()
                    normalized = _normalize_result(raw)
                except Exception as exc:
                    normalized = _invalid_result(str(exc), exception_type=type(exc).__name__)
                record = CallRecord(branch_id, call_index, op, _digest(input_value), normalized, capture, query_kind)
                calls.append(record)
                if capture:
                    ref = f"{branch_id}:{capture}"
                    captures[ref] = normalized
                    capture_inputs[ref] = copy.deepcopy(input_value) if isinstance(input_value, Mapping) else {"input": _plain(input_value)}
                return normalized

            for step in branch.get("steps", []):
                op = step.get("op")
                try:
                    if op == "ingest":
                        ids = step.get("artifact_ids", [])
                        last: dict[str, Any] | None = None
                        for artifact_id in ids:
                            artifact_payload = copy.deepcopy(artifact_data[artifact_id])
                            artifact = _compile_artifact(artifact_payload)
                            last = invoke("ingest", artifact_payload, lambda artifact=artifact: session.ingest(artifact))
                            operation_journal.append(("ingest", artifact_payload))
                        if step.get("capture") and last is not None:
                            ref = f"{branch_id}:{step['capture']}"
                            captures[ref] = last
                            capture_inputs[ref] = copy.deepcopy(artifact_payload)
                    elif op == "query":
                        data = query_data[step["query_id"]]
                        spec = _compile_query(data)
                        invoke(
                            "query", data, lambda spec=spec: session.query(spec), step.get("capture"),
                            query_kind=spec.kind.value,
                        )
                    elif op == "retract":
                        retract_payload = {"source_id": str(step["source_id"]), "known_at": str(step["known_at"])}
                        invoke(
                            "retract", retract_payload,
                            lambda: session.retract(retract_payload["source_id"], retract_payload["known_at"]),
                            step.get("capture"),
                        )
                        operation_journal.append(("retract", retract_payload))
                    elif op == "register_module":
                        module = copy.deepcopy(module_data[step["module_id"]])
                        invoke("register_module", module, lambda module=module: session.register_module(module), step.get("capture"))
                        operation_journal.append(("register_module", module))
                    elif op == "clean_rebuild":
                        # The clean oracle must not trust candidate.clean_rebuild:
                        # create a genuinely fresh instance and replay only the
                        # externally observed mutation journal.
                        rebuilt = _instantiate(self.candidate_provider, first=False)
                        replay_outcomes: list[dict[str, Any]] = []
                        for replay_op, payload in operation_journal:
                            if replay_op == "ingest":
                                artifact = _compile_artifact(payload)
                                replay_outcomes.append(invoke(
                                    "rebuild_replay_ingest", payload,
                                    lambda artifact=artifact, rebuilt=rebuilt: rebuilt.ingest(artifact),
                                ))
                            elif replay_op == "register_module":
                                module = copy.deepcopy(payload)
                                replay_outcomes.append(invoke(
                                    "rebuild_replay_register_module", payload,
                                    lambda module=module, rebuilt=rebuilt: rebuilt.register_module(module),
                                ))
                            elif replay_op == "retract":
                                replay_outcomes.append(invoke(
                                    "rebuild_replay_retract", payload,
                                    lambda payload=payload, rebuilt=rebuilt: rebuilt.retract(
                                        str(payload["source_id"]), str(payload["known_at"])
                                    ),
                                ))
                        session = rebuilt
                        rebuild_result = _normalize_result(CapabilityResult(
                            status=ResultStatus.OK,
                            validation="valid",
                            capability="runner_replay",
                            epistemic="not_applicable",
                            coverage_status="in_domain",
                            identification="not_applicable",
                            computation="exact",
                            value_kind="rebuild_receipt",
                            value={"replayed_operations": len(operation_journal)},
                            diagnostics={
                                "external_replay": True,
                                "replay_statuses": [item.get("status") for item in replay_outcomes],
                            },
                        ))
                        call_index += 1
                        calls.append(CallRecord(
                            branch_id, call_index, "clean_rebuild", _digest({"journal": operation_journal}),
                            rebuild_result, step.get("capture"), None,
                        ))
                        if step.get("capture"):
                            ref = f"{branch_id}:{step['capture']}"
                            captures[ref] = rebuild_result
                            capture_inputs[ref] = {"op": "clean_rebuild"}
                    elif op == "explain":
                        invoke("explain", step, lambda: session.explain(str(step["result_id"])), step.get("capture"))
                    else:
                        raise HarnessError(f"unknown workload operation: {op!r}")
                except HarnessError as exc:
                    harness_errors.append(f"branch {branch_id}: {exc}")
                except Exception as exc:
                    # Fixture compilation/lookup failures are harness errors;
                    # exceptions raised *inside* candidate calls are handled by
                    # invoke and remain candidate invalid results.
                    harness_errors.append(f"branch {branch_id} step {op}: {type(exc).__name__}: {exc}")

        assertions = [
            _evaluate_assertion(workload_id, item, captures, capture_inputs)
            for item in oracle_view(workload).get("assertions", [])
        ]
        boundary_axis, dishonest = _boundary_from_calls(calls, manifest_snapshot)
        explicit_boundary_assertions = [item for item in assertions if item.verdict_axis == "boundary"]
        if explicit_boundary_assertions:
            boundary_axis = PASS if all(item.passed for item in explicit_boundary_assertions) and boundary_axis != FAIL else FAIL

        hard_relevant = [item for item in assertions if item.hard_gate]
        hard_axis = (
            NOT_APPLICABLE if not hard_relevant
            else PASS if all(item.passed for item in hard_relevant)
            else FAIL
        )
        has_ineligible_reference = any(
            item.evidence_refs and not item.semantic_eligible and item.oracle_kind != "honesty"
            for item in assertions
        )
        if harness_errors:
            classification = "HARNESS_ERROR"
        elif dishonest:
            classification = "DISHONEST_CLAIM"
        elif any(call.result.get("status") == "numerical_failure" for call in calls):
            classification = "NUMERICAL_FAILURE"
        elif any(call.result.get("diagnostics", {}).get("candidate_raised") for call in calls):
            classification = "INVALID_RESULT"
        elif hard_axis == PASS and boundary_axis != FAIL and not has_ineligible_reference:
            classification = "PASS"
        elif any(call.result.get("status") in {"unsupported", "insufficient", "out_of_model"} for call in calls) and boundary_axis == PASS:
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
            benchmark_version=BENCHMARK_VERSION,
            workload_id=workload_id,
            candidate_id=candidate_id,
            manifest_snapshot=manifest_snapshot,
            candidate_input_digest=_digest(view),
            calls=calls,
            captures=captures,
            assertions=assertions,
            verdict=verdict,
            harness_errors=harness_errors,
        )

    def run_panel(self, workloads: Mapping[str, Mapping[str, Any]]) -> dict[str, WorkloadRun]:
        return {workload_id: self.run(workload) for workload_id, workload in sorted(workloads.items())}


def summarize_runs(runs: Mapping[str, WorkloadRun]) -> dict[str, Any]:
    classifications: dict[str, int] = {}
    axes = {axis: {PASS: 0, FAIL: 0, NOT_APPLICABLE: 0} for axis in ("behavior", "boundary", "trace", "numerical", "hard")}
    for run in runs.values():
        classifications[run.verdict.classification] = classifications.get(run.verdict.classification, 0) + 1
        for axis in axes:
            value = getattr(run.verdict, axis)
            axes[axis][value] = axes[axis].get(value, 0) + 1
    return {"benchmark_version": BENCHMARK_VERSION, "workload_count": len(runs), "classifications": classifications, "axes": axes}


__all__ = [
    "AssertionResult", "BENCHMARK_VERSION", "BenchmarkRunner", "HarnessError", "VerdictVector",
    "WorkloadRun", "summarize_runs",
]


def _cli() -> int:
    import argparse
    from pathlib import Path

    from .contract import Track
    from .workloads import load_workloads

    parser = argparse.ArgumentParser(description="Run the candidate-neutral VeSMed architecture benchmark")
    parser.add_argument("--candidate", choices=("tel", "causal", "rewrite"), required=True)
    parser.add_argument("--track", choices=("native", "companion"), default="native")
    parser.add_argument("--panel", choices=("T", "E", "all"), default="all")
    parser.add_argument("--workload", action="append", default=[], help="specific workload ID; repeatable")
    parser.add_argument("--output", type=Path, help="write immutable-style raw run bundle JSON")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")

    track = Track(args.track)
    if args.candidate == "tel":
        from .candidates.temporal_ledger import TemporalEvidenceLedger

        provider = lambda: TemporalEvidenceLedger(track=track)
    elif args.candidate == "causal":
        from .candidates.causal_state import build_candidate

        provider = lambda: build_candidate(track=track)
    else:
        from .candidates.rewrite_open import build_candidate

        provider = lambda: build_candidate(track=track)

    workloads = load_workloads()
    if args.panel != "all":
        workloads = {key: value for key, value in workloads.items() if value["panel"] == args.panel}
    if args.workload:
        requested = set(args.workload)
        missing = requested - set(workloads)
        if missing:
            parser.error(f"unknown/not-selected workload IDs: {sorted(missing)}")
        workloads = {key: value for key, value in workloads.items() if key in requested}

    runs = BenchmarkRunner(provider).run_panel(workloads)
    bundle = {
        "benchmark_version": BENCHMARK_VERSION,
        "candidate": args.candidate,
        "track": args.track,
        "summary": summarize_runs(runs),
        "runs": {key: value.to_dict() for key, value in runs.items()},
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        except FileExistsError:
            parser.error(f"refusing to overwrite existing output: {args.output}")
    print(json.dumps(bundle["summary"], ensure_ascii=False, sort_keys=True, indent=2))
    # Benchmark failures are experiment results, not CLI execution failures.
    # Only harness errors make the command non-zero.
    return 2 if any(run.harness_errors for run in runs.values()) else 0


if __name__ == "__main__":  # pragma: no cover - exercised by integration command
    raise SystemExit(_cli())
