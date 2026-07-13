"""Independent implementation B for the evidence -> model bridge holdout.

This module deliberately does not import either holdout implementation A or a
shared model compiler.  It uses two physical representations that are useful
for an implementation-diversity test:

* a finite DBN is compiled to row-major transition blocks plus immutable
  evidence-likelihood columns; filtering uses forward messages and smoothing
  uses a distinct forward/backward operator;
* a finite SCM is compiled to a response-function world table.  Population
  intervention uses prior world weights, whereas an individual
  counterfactual performs factual abduction and then reuses the same world
  identities for action/prediction.

The original JSON-shaped bridge bundle is retained only as a typed path tape
needed by :func:`recover_bundle`.  Execution never decodes that tape: it reads
the compiled numeric IR and lineage sidecar.  This distinction is intentional
and is checked by :func:`self_test` by replacing the recovery tape before an
execution.

Public frozen interface
-----------------------

``compile_bundle(canonical, target_kernel)``
    Compile a closed canonical mapping to ``finite_dbn`` or ``finite_scm``.
``recover_bundle(native)``
    Losslessly recover the exact canonical mapping (including list/tuple and
    integer/float distinctions) after validating its digest.
``execute(native, query)``
    Execute a native closed query.  Supported tags are ``filter``, ``smooth``,
    ``condition``, ``do``/``intervene`` and ``aap``/``counterfactual``.
``apply_delta(native, delta)``
    Apply typed ``Corrects`` or ``Retracts`` evidence deltas to the immutable
    native IR.  A retraction only makes a prior column ineligible; it never
    becomes a negative observation.

The compiler accepts a small neutral canonical shape documented in the demo
builders at the end of this file.  A few harmless aliases are accepted at the
boundary so the adapter can consume the repository's public ``QuerySpec``
spelling without weakening the closed operator distinctions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from itertools import combinations, product
import json
from math import exp, isfinite, log, prod as math_prod
from typing import Any, Iterable, Mapping, Sequence

FORMAT_VERSION = "vesmed.bridge-holdout.impl-b.native/1"
CANONICAL_SCHEMA = "vesmed.evidence-model-bridge/1"
PROB_TOL = 1e-10
MAX_STATES = 4096
MAX_WORLDS = 4096
MAX_RESPONSE_CONTEXTS = 4096


class BridgeError(ValueError):
    """Closed boundary or native semantic validation failure."""


# Local name retained throughout the implementation; importantly, this is not
# imported from the repository's executable contract/compiler.
ContractError = BridgeError


def validate_json_like(
    value: Any,
    *,
    label: str = "value",
    max_depth: int = 64,
    max_nodes: int = 65_536,
    max_bytes: int = 1_048_576,
) -> None:
    """Implementation-B's own exact-builtin, bounded inert-tree validator."""

    if type(max_depth) is not int or max_depth < 0:
        raise BridgeError("max_depth must be a nonnegative exact int")
    if type(max_nodes) is not int or max_nodes < 1:
        raise BridgeError("max_nodes must be a positive exact int")
    if type(max_bytes) is not int or max_bytes < 1:
        raise BridgeError("max_bytes must be a positive exact int")
    nodes = 0
    bytes_used = 0
    active: set[int] = set()

    def charge(byte_count: int) -> None:
        nonlocal nodes, bytes_used
        nodes += 1
        bytes_used += byte_count
        if nodes > max_nodes:
            raise BridgeError(f"{label} exceeds node budget")
        if bytes_used > max_bytes:
            raise BridgeError(f"{label} exceeds byte budget")

    def visit(item: Any, depth: int, path: str) -> None:
        if depth > max_depth:
            raise BridgeError(f"{label} exceeds depth budget at {path}")
        t = type(item)
        if t is type(None):
            charge(4)
        elif t is bool:
            charge(5)
        elif t is int:
            charge(max(1, (item.bit_length() * 30103) // 100000 + 3))
        elif t is float:
            if not isfinite(item):
                raise BridgeError(f"{path} contains a non-finite float")
            charge(24)
        elif t is str:
            encoded = item.encode("utf-8")
            charge(len(encoded) + 2)
        elif t in {list, tuple, dict}:
            identity = id(item)
            if identity in active:
                raise BridgeError(f"{path} contains a cycle")
            active.add(identity)
            charge(2)
            try:
                if t is dict:
                    for index, (key, child) in enumerate(dict.items(item)):
                        if type(key) is not str:
                            raise BridgeError(f"{path} has a non-string key")
                        visit(key, depth + 1, f"{path}.<key:{index}>")
                        visit(child, depth + 1, f"{path}.{key}")
                else:
                    for index, child in enumerate(item):
                        visit(child, depth + 1, f"{path}[{index}]")
            finally:
                active.remove(identity)
        else:
            raise BridgeError(f"{path} is not exact-builtin JSON-like: {t.__name__}")

    visit(value, 0, label)


# ---------------------------------------------------------------------------
# Immutable physical IR
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RootRowB:
    root_id: str
    version: str
    logical_id: str
    active: bool
    metadata: tuple[Any, ...]


@dataclass(frozen=True)
class EvidenceColumnB:
    native_address: str
    record_id: str
    logical_id: str
    record_version: str
    active: bool
    slice_index: int
    slice_label: Any
    available_at: Any
    transaction_revision: Any
    variable: str
    value: Any
    likelihood: tuple[float, ...]
    root_ids: tuple[str, ...]
    uncertainty: tuple[Any, ...]
    raw_record: tuple[Any, ...]


@dataclass(frozen=True)
class DBNIRB:
    states: tuple[Any, ...]
    state_keys: tuple[str, ...]
    timeline: tuple[Any, ...]
    prior: tuple[float, ...]
    # One flattened row-major matrix per adjacent timeline edge.
    transition_blocks: tuple[tuple[float, ...], ...]
    evidence_columns: tuple[EvidenceColumnB, ...]


@dataclass(frozen=True)
class ResponseRowB:
    do_key: str
    do_set: tuple[Any, ...]
    values: tuple[Any, ...]


@dataclass(frozen=True)
class WorldRowB:
    world_id: str
    probability: float
    exogenous: tuple[Any, ...]
    responses: tuple[ResponseRowB, ...]


@dataclass(frozen=True)
class SCMIRB:
    variables: tuple[str, ...]
    worlds: tuple[WorldRowB, ...]
    evidence_columns: tuple[EvidenceColumnB, ...]


@dataclass(frozen=True)
class NativeBundleB:
    """Closed native implementation-B capsule.

    ``recovery_symbols``/``recovery_tape`` are an audit/recovery witness.  All
    fields used by ``execute`` are separate and immutable.
    """

    format_version: str
    target_kernel: str
    bundle_id: str
    semantic_digest: str
    recovery_symbols: tuple[str, ...]
    recovery_tape: tuple[tuple[Any, ...], ...]
    bridge_sidecar: tuple[Any, ...]
    temporal_cut_sidecar: tuple[Any, ...]
    versions_sidecar: tuple[Any, ...]
    uncertainty_sidecar: tuple[Any, ...]
    roots: tuple[RootRowB, ...]
    native_ir: DBNIRB | SCMIRB
    delta_history: tuple[tuple[Any, ...], ...] = ()


# ---------------------------------------------------------------------------
# Exact inert-tree codec used only for recovery/audit
# ---------------------------------------------------------------------------


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractError(f"{label} must be an exact dict")
    validate_json_like(value, label=label)
    return value


def _require_text(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise ContractError(f"{label} must be a non-empty exact str")
    return value


def _finite_number(value: Any, label: str) -> float:
    if type(value) not in {int, float} or not isfinite(float(value)):
        raise ContractError(f"{label} must be a finite exact number")
    return float(value)


def _freeze(value: Any) -> tuple[Any, ...]:
    """Freeze an exact JSON-like value while retaining every scalar type."""

    t = type(value)
    if t is type(None):
        return ("null",)
    if t is bool:
        return ("bool", 1 if value else 0)
    if t is int:
        return ("int", str(value))
    if t is float:
        if not isfinite(value):
            raise ContractError("non-finite float in frozen value")
        return ("float", value.hex())
    if t is str:
        return ("str", value)
    if t is list:
        return ("list", *(_freeze(item) for item in value))
    if t is tuple:
        return ("tuple", *(_freeze(item) for item in value))
    if t is dict:
        return (
            "dict",
            *((key, _freeze(child)) for key, child in dict.items(value)),
        )
    raise ContractError(f"cannot freeze non JSON-like type {t.__name__}")


def _thaw(node: tuple[Any, ...]) -> Any:
    if type(node) is not tuple or not node:
        raise ContractError("invalid frozen node")
    tag = node[0]
    if tag == "null":
        return None
    if tag == "bool":
        return bool(node[1])
    if tag == "int":
        return int(node[1])
    if tag == "float":
        return float.fromhex(node[1])
    if tag == "str":
        return node[1]
    if tag == "list":
        return [_thaw(item) for item in node[1:]]
    if tag == "tuple":
        return tuple(_thaw(item) for item in node[1:])
    if tag == "dict":
        return {pair[0]: _thaw(pair[1]) for pair in node[1:]}
    raise ContractError(f"unknown frozen tag {tag!r}")


def _collect_symbols(value: Any, out: set[str]) -> None:
    t = type(value)
    if t is str:
        out.add(value)
    elif t is dict:
        for key, child in dict.items(value):
            out.add(key)
            _collect_symbols(child, out)
    elif t in {list, tuple}:
        for child in value:
            _collect_symbols(child, out)


def _make_tape(value: dict[str, Any]) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
    """Encode a tree as an interned preorder path tape.

    This intentionally differs from a conventional nested JSON envelope.  Dict
    key order and list-vs-tuple are explicit nodes, so recovery is strict.
    """

    symbols_set: set[str] = set()
    _collect_symbols(value, symbols_set)
    symbols = tuple(sorted(symbols_set))
    index = {item: i for i, item in enumerate(symbols)}
    tape: list[tuple[Any, ...]] = []

    def visit(item: Any) -> None:
        t = type(item)
        if t is type(None):
            tape.append(("N",))
        elif t is bool:
            tape.append(("B", 1 if item else 0))
        elif t is int:
            tape.append(("I", str(item)))
        elif t is float:
            if not isfinite(item):
                raise ContractError("non-finite float cannot enter recovery tape")
            tape.append(("F", item.hex()))
        elif t is str:
            tape.append(("S", index[item]))
        elif t in {list, tuple}:
            tape.append(("L" if t is list else "T", len(item)))
            for child in item:
                visit(child)
        elif t is dict:
            tape.append(("D", len(item)))
            for key, child in dict.items(item):
                tape.append(("K", index[key]))
                visit(child)
        else:  # validated before this point; retained as a defensive guard
            raise ContractError(f"unsupported tape type {t.__name__}")

    visit(value)
    return symbols, tuple(tape)


def _read_tape(symbols: tuple[str, ...], tape: tuple[tuple[Any, ...], ...]) -> dict[str, Any]:
    pos = 0

    def read() -> Any:
        nonlocal pos
        if pos >= len(tape):
            raise ContractError("truncated recovery tape")
        node = tape[pos]
        pos += 1
        if type(node) is not tuple or not node:
            raise ContractError("malformed recovery tape node")
        tag = node[0]
        if tag == "N":
            return None
        if tag == "B":
            return bool(node[1])
        if tag == "I":
            return int(node[1])
        if tag == "F":
            return float.fromhex(node[1])
        if tag == "S":
            return symbols[node[1]]
        if tag in {"L", "T"}:
            children = [read() for _ in range(node[1])]
            return children if tag == "L" else tuple(children)
        if tag == "D":
            out: dict[str, Any] = {}
            for _ in range(node[1]):
                if pos >= len(tape) or tape[pos][0] != "K":
                    raise ContractError("dict entry is missing a key token")
                key_index = tape[pos][1]
                pos += 1
                key = symbols[key_index]
                if key in out:
                    raise ContractError("duplicate dict key in recovery tape")
                out[key] = read()
            return out
        raise ContractError(f"unknown tape opcode {tag!r}")

    value = read()
    if pos != len(tape):
        raise ContractError("trailing recovery tape nodes")
    if type(value) is not dict:
        raise ContractError("recovered bundle is not a dict")
    validate_json_like(value, label="recovered bundle")
    return value


def _tape_digest(symbols: tuple[str, ...], tape: tuple[tuple[Any, ...], ...]) -> str:
    payload = json.dumps(
        {"symbols": symbols, "tape": tape},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _value_key(value: Any) -> str:
    return json.dumps(_freeze(value), ensure_ascii=False, separators=(",", ":"))


def _mapping_from_frozen(value: tuple[Any, ...], label: str) -> dict[str, Any]:
    thawed = _thaw(value)
    if type(thawed) is not dict:
        raise ContractError(f"{label} sidecar is not a mapping")
    return thawed


# ---------------------------------------------------------------------------
# Canonical boundary helpers
# ---------------------------------------------------------------------------


def _first(data: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return default


def _canonical_parts(canonical: dict[str, Any], target_kernel: str) -> tuple[
    str, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    bundle_id = _first(canonical, "bundle_id", "id", "module_id")
    bundle_id = _require_text(bundle_id, "bundle_id")
    bridge = _first(canonical, "bridge", "bridge_contract", default={})
    cut = _first(canonical, "temporal_cut", "cut", default={})
    versions = _first(canonical, "versions", "version_vector", default={})
    uncertainty = _first(canonical, "uncertainty", "uncertainty_contract", default={})
    model = canonical.get("model")
    if model is None:
        model = canonical.get(target_kernel)
    for label, value in (
        ("bridge", bridge),
        ("temporal_cut", cut),
        ("versions", versions),
        ("uncertainty", uncertainty),
        ("model", model),
    ):
        if type(value) is not dict:
            raise ContractError(f"{label} must be an exact dict")
    if not bridge:
        raise ContractError("canonical bridge contract must be explicit")
    bridge_version = _first(bridge, "version", "bridge_version")
    _require_text(bridge_version, "bridge.version")
    if not cut:
        raise ContractError("canonical temporal_cut must be explicit")
    if not versions:
        raise ContractError("canonical versions vector must be explicit")
    if not uncertainty:
        raise ContractError("canonical uncertainty semantics must be explicit")
    return bundle_id, bridge, cut, versions, uncertainty, model


def _root_id(row: Any) -> str:
    if type(row) is str:
        return _require_text(row, "root id")
    if type(row) is not dict:
        raise ContractError("root rows must be strings or exact mappings")
    value = _first(row, "root_id", "root_occurrence", "source_id", "id")
    return _require_text(value, "root.root_id")


def _root_version(row: Any) -> str:
    if type(row) is str:
        return "unversioned"
    value = _first(row, "root_version", "version", "artifact_version", default="unversioned")
    return _require_text(value, "root.version")


def _record_roots(record: Mapping[str, Any]) -> tuple[str, ...]:
    raw = _first(record, "root_ids", "roots", "root_sources", default=())
    if type(raw) is str:
        raw = [raw]
    if type(raw) not in {list, tuple}:
        raise ContractError("evidence roots must be a string/list/tuple")
    values: list[str] = []
    for item in raw:
        rid = _root_id(item)
        if rid not in values:
            values.append(rid)
    return tuple(values)


def _evidence_container(canonical: Mapping[str, Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    roots_raw = canonical.get("roots", canonical.get("evidence_roots", []))
    evidence = canonical.get("evidence", canonical.get("observations", []))
    if type(evidence) is dict:
        roots_raw = evidence.get("roots", roots_raw)
        records = _first(evidence, "records", "slices", "observations", default=[])
    else:
        records = evidence
    if type(roots_raw) not in {list, tuple}:
        raise ContractError("roots must be a list/tuple")
    if type(records) not in {list, tuple}:
        raise ContractError("evidence records must be a list/tuple")
    normalized_records: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if type(record) is not dict:
            raise ContractError(f"evidence[{index}] must be an exact dict")
        normalized_records.append(record)
    return list(roots_raw), normalized_records


def _compile_roots(canonical: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> tuple[RootRowB, ...]:
    roots_raw, _ = _evidence_container(canonical)
    rows: list[RootRowB] = []
    seen: dict[str, tuple[Any, ...]] = {}
    for item in roots_raw:
        rid = _root_id(item)
        metadata_value = {"root_id": rid, "version": "unversioned"} if type(item) is str else item
        metadata = _freeze(metadata_value)
        if rid in seen and seen[rid] != metadata:
            raise ContractError(f"duplicate root {rid!r} has non-identical metadata")
        if rid in seen:
            continue
        seen[rid] = metadata
        logical = rid if type(item) is str else str(_first(item, "logical_id", default=rid))
        active = True if type(item) is str else bool(item.get("active", True))
        rows.append(RootRowB(rid, _root_version(item), logical, active, metadata))

    referenced: list[str] = []
    for record in records:
        for rid in _record_roots(record):
            if rid not in referenced:
                referenced.append(rid)
    if roots_raw:
        unknown = [rid for rid in referenced if rid not in seen]
        if unknown:
            raise ContractError(f"evidence references unknown roots: {unknown}")
    else:
        # Compatibility path for older projections whose root registry was
        # flattened into records.  Identity is still explicit and versioned.
        for rid in referenced:
            metadata = _freeze({"root_id": rid, "version": "unversioned"})
            rows.append(RootRowB(rid, "unversioned", rid, True, metadata))
    return tuple(rows)


def _record_id(record: Mapping[str, Any], index: int) -> str:
    value = _first(record, "record_id", "evidence_id", "statement_id", "observation_id", "claim_id")
    if value is None:
        return f"record-{index}"
    return _require_text(value, f"evidence[{index}].record_id")


def _record_variable(record: Mapping[str, Any]) -> str:
    value = _first(record, "variable", "target", "concept", "axis_id")
    return _require_text(value, "evidence.variable")


def _record_slice(record: Mapping[str, Any]) -> Any:
    value = _first(record, "slice", "slice_id", "time_index", "valid_at", "effective_start", "time")
    if value is None:
        raise ContractError("evidence record lacks a temporal slice")
    if type(value) not in {str, int, float}:
        raise ContractError("evidence slice must be a scalar")
    if type(value) is float and not isfinite(value):
        raise ContractError("evidence slice float must be finite")
    return value


def _time_sort_key(value: Any) -> tuple[int, Any]:
    if type(value) in {int, float}:
        return (0, float(value))
    if type(value) is str:
        try:
            text = value[:-1] + "+00:00" if value.endswith("Z") else value
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                raise ValueError
            return (1, dt.astimezone(timezone.utc).timestamp())
        except ValueError:
            return (2, value)
    return (3, _value_key(value))


def _not_after(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return True
    lk, rk = _time_sort_key(left), _time_sort_key(right)
    if lk[0] != rk[0]:
        # Incomparable clock domains must not be guessed.  Treat an explicitly
        # supplied mismatch as ineligible instead of silently coercing it.
        return False
    return lk[1] <= rk[1]


def _timeline_index(timeline: Sequence[Any], label: Any, *, label_name: str) -> int:
    key = _value_key(label)
    for index, item in enumerate(timeline):
        if _value_key(item) == key:
            return index
    raise ContractError(f"{label_name} {label!r} is not in the declared timeline")


def _prob_vector(raw: Any, states: Sequence[Any], label: str) -> tuple[float, ...]:
    if type(raw) in {list, tuple}:
        if len(raw) == len(states) and all(type(item) in {int, float} for item in raw):
            values = [_finite_number(item, label) for item in raw]
        elif all(type(item) is dict for item in raw):
            by_key = {
                _value_key(_first(item, "state", "value")): _finite_number(
                    _first(item, "probability", "weight"), label
                )
                for item in raw
            }
            values = [by_key.get(_value_key(state), 0.0) for state in states]
        else:
            raise ContractError(f"{label} has an invalid probability-vector shape")
    elif type(raw) is dict:
        values = []
        for state in states:
            candidates = (state, str(state), _value_key(state))
            found = None
            for candidate in candidates:
                if type(candidate) is str and candidate in raw:
                    found = raw[candidate]
                    break
            if found is None:
                raise ContractError(f"{label} is missing state {state!r}")
            values.append(_finite_number(found, label))
    else:
        raise ContractError(f"{label} must be a vector or state mapping")
    if any(value < -PROB_TOL for value in values):
        raise ContractError(f"{label} contains negative mass")
    total = sum(max(0.0, value) for value in values)
    if total <= PROB_TOL:
        raise ContractError(f"{label} has zero total mass")
    return tuple(max(0.0, value) / total for value in values)


def _likelihood_vector(raw: Any, states: Sequence[Any], label: str) -> tuple[float, ...]:
    if type(raw) in {list, tuple} and len(raw) == len(states):
        values = tuple(_finite_number(item, label) for item in raw)
    elif type(raw) is dict:
        values_list: list[float] = []
        for state in states:
            found = None
            for candidate in (state, str(state), _value_key(state)):
                if type(candidate) is str and candidate in raw:
                    found = raw[candidate]
                    break
            if found is None:
                raise ContractError(f"{label} is missing state {state!r}")
            values_list.append(_finite_number(found, label))
        values = tuple(values_list)
    else:
        raise ContractError(f"{label} must map every state to a likelihood")
    if any(value < 0.0 for value in values) or sum(values) <= PROB_TOL:
        raise ContractError(f"{label} must contain nonnegative, nonzero likelihoods")
    return values


def _matrix(raw: Any, states: Sequence[Any], label: str) -> tuple[float, ...]:
    n = len(states)
    rows: list[tuple[float, ...]] = []
    if type(raw) in {list, tuple}:
        if len(raw) != n:
            raise ContractError(f"{label} row count must equal state count")
        for i, row in enumerate(raw):
            rows.append(_prob_vector(row, states, f"{label}[{i}]"))
    elif type(raw) is dict:
        for state in states:
            row = None
            for candidate in (state, str(state), _value_key(state)):
                if type(candidate) is str and candidate in raw:
                    row = raw[candidate]
                    break
            if row is None:
                raise ContractError(f"{label} is missing previous state {state!r}")
            rows.append(_prob_vector(row, states, f"{label}[{state!r}]"))
    else:
        raise ContractError(f"{label} must be a matrix")
    return tuple(value for row in rows for value in row)


def _compile_transition_blocks(model: Mapping[str, Any], states: Sequence[Any], timeline: Sequence[Any]) -> tuple[tuple[float, ...], ...]:
    edge_count = max(0, len(timeline) - 1)
    if edge_count == 0:
        return ()
    raw = _first(model, "transition_blocks", "transitions", "transition_matrix", "transition")
    if raw == "identity":
        n = len(states)
        block = tuple(1.0 if i == j else 0.0 for i in range(n) for j in range(n))
        return tuple(block for _ in range(edge_count))
    if raw is None:
        raise ContractError("finite_dbn requires explicit transitions")

    # A raw numeric/mapping matrix is constant over all edges.
    if type(raw) is dict:
        if any(key in raw for key in ("matrix", "from", "to")):
            raw = [raw]
        else:
            state_spellings = {str(state) for state in states} | {_value_key(state) for state in states}
            if set(raw) <= state_spellings:
                block = _matrix(raw, states, "transition")
                return tuple(block for _ in range(edge_count))
            # Otherwise treat keys as destination slice labels.
            blocks: list[tuple[float, ...]] = []
            for edge in range(edge_count):
                destination = timeline[edge + 1]
                value = raw.get(str(destination), raw.get(_value_key(destination)))
                if value is None:
                    raise ContractError(f"transition is missing destination slice {destination!r}")
                blocks.append(_matrix(value, states, f"transition->{destination!r}"))
            return tuple(blocks)

    if type(raw) in {list, tuple}:
        # Distinguish a matrix (n rows of numeric vectors/mappings) from a list
        # of per-edge matrices/edge objects.
        looks_matrix = len(raw) == len(states) and all(
            type(row) in {list, tuple, dict}
            and not (type(row) is dict and "matrix" in row)
            for row in raw
        )
        if looks_matrix:
            try:
                block = _matrix(raw, states, "transition")
                return tuple(block for _ in range(edge_count))
            except ContractError:
                pass
        if len(raw) not in {1, edge_count}:
            raise ContractError("per-edge transition list has the wrong length")
        blocks = []
        for edge in range(edge_count):
            item = raw[0] if len(raw) == 1 else raw[edge]
            if type(item) is dict and "matrix" in item:
                expected_from, expected_to = timeline[edge], timeline[edge + 1]
                if "from" in item and _value_key(item["from"]) != _value_key(expected_from):
                    raise ContractError("transition.from does not match timeline")
                if "to" in item and _value_key(item["to"]) != _value_key(expected_to):
                    raise ContractError("transition.to does not match timeline")
                item = item["matrix"]
            blocks.append(_matrix(item, states, f"transition[{edge}]"))
        return tuple(blocks)
    raise ContractError("unsupported transition representation")


def _emission_likelihood(model: Mapping[str, Any], variable: str, value: Any, states: Sequence[Any]) -> tuple[float, ...]:
    emissions = _first(model, "emissions", "emission_models", default={})
    if type(emissions) is not dict or variable not in emissions:
        raise ContractError(f"record for {variable!r} lacks likelihood and no emission table exists")
    table = emissions[variable]
    if type(table) is not dict:
        raise ContractError(f"emission table for {variable!r} must be a mapping")
    out: list[float] = []
    for state in states:
        row = None
        for candidate in (state, str(state), _value_key(state)):
            if type(candidate) is str and candidate in table:
                row = table[candidate]
                break
        if row is None or type(row) is not dict:
            raise ContractError(f"emission table lacks state {state!r}")
        probability = None
        for candidate in (value, str(value), _value_key(value)):
            if type(candidate) is str and candidate in row:
                probability = row[candidate]
                break
        if probability is None:
            raise ContractError(f"emission row lacks value {value!r}")
        out.append(_finite_number(probability, "emission probability"))
    if any(item < 0 for item in out) or sum(out) <= PROB_TOL:
        raise ContractError("emission likelihood must be nonnegative and nonzero")
    return tuple(out)


def _common_column(
    record: Mapping[str, Any], index: int, timeline: Sequence[Any], likelihood: tuple[float, ...]
) -> EvidenceColumnB:
    record_id = _record_id(record, index)
    logical_id = str(_first(record, "logical_id", default=record_id))
    version = str(_first(record, "record_version", "version", default="unversioned"))
    slice_label = _record_slice(record)
    slice_index = _timeline_index(timeline, slice_label, label_name="evidence slice")
    available_at = _first(record, "available_at", "actor_available_at", default=slice_label)
    revision = _first(record, "transaction_revision", "revision", "committed_revision")
    uncertainty = record.get("uncertainty", {"kind": "not_provided"})
    if type(uncertainty) is not dict:
        raise ContractError("record uncertainty must be a mapping")
    return EvidenceColumnB(
        native_address=f"B:likelihood:{slice_index}:{index}:{record_id}",
        record_id=record_id,
        logical_id=logical_id,
        record_version=version,
        active=bool(record.get("active", True)),
        slice_index=slice_index,
        slice_label=slice_label,
        available_at=available_at,
        transaction_revision=revision,
        variable=_record_variable(record),
        value=record.get("value"),
        likelihood=likelihood,
        root_ids=_record_roots(record),
        uncertainty=_freeze(uncertainty),
        raw_record=_freeze(dict(record)),
    )


def _compile_dbn(canonical: Mapping[str, Any], model: Mapping[str, Any]) -> DBNIRB:
    states_raw = _first(model, "states", "state_domain")
    if type(states_raw) not in {list, tuple} or not states_raw:
        raise ContractError("finite_dbn model.states must be non-empty")
    if len(states_raw) > MAX_STATES:
        raise ContractError("finite_dbn state budget exceeded")
    states: list[Any] = []
    keys: set[str] = set()
    for state in states_raw:
        if type(state) not in {str, int, float, bool}:
            raise ContractError("finite_dbn states must be finite JSON scalars")
        if type(state) is float and not isfinite(state):
            raise ContractError("finite_dbn state must be finite")
        key = _value_key(state)
        if key in keys:
            raise ContractError("finite_dbn states must be unique with type identity")
        keys.add(key)
        states.append(state)

    _, records = _evidence_container(canonical)
    timeline_raw = _first(model, "timeline", "slices", "time_slices")
    if timeline_raw is None:
        timeline_raw = sorted({_record_slice(record) for record in records}, key=_time_sort_key)
    if type(timeline_raw) not in {list, tuple} or not timeline_raw:
        raise ContractError("finite_dbn timeline must be non-empty")
    timeline = tuple(timeline_raw)
    if len({_value_key(item) for item in timeline}) != len(timeline):
        raise ContractError("finite_dbn timeline labels must be unique")
    if list(timeline) != sorted(timeline, key=_time_sort_key):
        raise ContractError("finite_dbn timeline must be ordered")

    prior = _prob_vector(_first(model, "prior", "initial"), states, "prior")
    transitions = _compile_transition_blocks(model, states, timeline)
    columns: list[EvidenceColumnB] = []
    for index, record in enumerate(records):
        raw_likelihood = _first(record, "likelihood", "state_likelihood")
        if raw_likelihood is None:
            likelihood = _emission_likelihood(
                model, _record_variable(record), record.get("value"), states
            )
        else:
            likelihood = _likelihood_vector(raw_likelihood, states, f"evidence[{index}].likelihood")
        columns.append(_common_column(record, index, timeline, likelihood))
    return DBNIRB(tuple(states), tuple(_value_key(item) for item in states), timeline, prior, transitions, tuple(columns))


# ---------------------------------------------------------------------------
# Closed expression evaluator and SCM response-table compiler
# ---------------------------------------------------------------------------


_EXPR_ARITY = {
    "const": 0,
    "var": 0,
    "neg": 1,
    "exp": 1,
    "log": 1,
    "logistic": 1,
    "add": 2,
    "sub": 2,
    "mul": 2,
    "div": 2,
    "min": 2,
    "max": 2,
    "pow": 2,
    "clamp": 3,
    "if_gt": 4,
}


def _eval_expr(expr: Any, env: Mapping[str, Any], depth: int = 0) -> Any:
    if depth > 64:
        raise ContractError("expression depth budget exceeded")
    if type(expr) in {int, float, bool}:
        if type(expr) is float and not isfinite(expr):
            raise ContractError("non-finite expression constant")
        return expr
    if type(expr) is str:
        if expr not in env:
            raise ContractError(f"unknown expression variable {expr!r}")
        return env[expr]
    if type(expr) is not dict:
        raise ContractError("closed expression must be a scalar, variable name, or mapping")
    op = expr.get("op")
    if op not in _EXPR_ARITY:
        raise ContractError(f"unknown closed expression opcode {op!r}")
    args = expr.get("args", [])
    if type(args) not in {list, tuple} or len(args) != _EXPR_ARITY[op]:
        raise ContractError(f"expression opcode {op!r} has wrong arity")
    if op == "const":
        value = expr.get("value")
        return _finite_number(value, "const.value")
    if op == "var":
        name = expr.get("value")
        if type(name) is not str or name not in env:
            raise ContractError(f"unknown expression variable {name!r}")
        return env[name]
    xs = [_eval_expr(item, env, depth + 1) for item in args]
    if op == "neg": return -xs[0]
    if op == "exp": return exp(xs[0])
    if op == "log":
        if xs[0] <= 0: raise ContractError("log expression domain error")
        return log(xs[0])
    if op == "logistic": return 1.0 / (1.0 + exp(-max(-700.0, min(700.0, xs[0]))))
    if op == "add": return xs[0] + xs[1]
    if op == "sub": return xs[0] - xs[1]
    if op == "mul": return xs[0] * xs[1]
    if op == "div":
        if xs[1] == 0: raise ContractError("division by zero")
        return xs[0] / xs[1]
    if op == "min": return min(xs[0], xs[1])
    if op == "max": return max(xs[0], xs[1])
    if op == "pow": return xs[0] ** xs[1]
    if op == "clamp": return max(xs[1], min(xs[2], xs[0]))
    if op == "if_gt": return xs[2] if xs[0] > xs[1] else xs[3]
    raise ContractError("unreachable expression opcode")


def _eval_equation(equation: Mapping[str, Any], env: Mapping[str, Any]) -> Any:
    if "expression" in equation:
        return _eval_expr(equation["expression"], env)
    table = equation.get("table")
    if type(table) not in {list, tuple}:
        raise ContractError("SCM equation requires expression or table")
    default_marker = object()
    default: Any = default_marker
    for row in table:
        if type(row) is not dict:
            raise ContractError("SCM equation table rows must be mappings")
        when = row.get("when")
        if when is None:
            default = row.get("value")
            continue
        if type(when) is not dict:
            raise ContractError("SCM equation when clause must be a mapping")
        if all(name in env and _value_key(env[name]) == _value_key(value) for name, value in when.items()):
            return row.get("value")
    if default is not default_marker:
        return default
    raise ContractError("SCM equation table has no matching row")


def _do_key(do_set: Mapping[str, Any]) -> str:
    return json.dumps(
        [(name, _freeze(do_set[name])) for name in sorted(do_set)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _response_row(do_set: Mapping[str, Any], values: Mapping[str, Any]) -> ResponseRowB:
    return ResponseRowB(_do_key(do_set), _freeze(dict(do_set)), _freeze(dict(values)))


def _worlds_from_rows(model: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[WorldRowB, ...]]:
    rows = _first(model, "worlds", "response_worlds")
    if type(rows) not in {list, tuple} or not rows:
        raise ContractError("finite_scm world table must be non-empty")
    worlds: list[WorldRowB] = []
    variables: set[str] = set()
    for index, row in enumerate(rows):
        if type(row) is not dict:
            raise ContractError("SCM worlds must be mappings")
        world_id = str(_first(row, "world_id", "id", default=f"world-{index}"))
        probability = _finite_number(_first(row, "probability", "weight"), "world probability")
        if probability < 0:
            raise ContractError("world probability cannot be negative")
        exogenous = _first(row, "exogenous", "u", default={})
        if type(exogenous) is not dict:
            raise ContractError("world.exogenous must be a mapping")
        baseline = _first(row, "factual", "values", "baseline")
        if type(baseline) is not dict:
            raise ContractError("world must declare factual/baseline values")
        variables.update(baseline)
        responses: list[ResponseRowB] = [_response_row({}, baseline)]
        raw_responses = row.get("responses", [])
        if type(raw_responses) not in {list, tuple}:
            raise ContractError("world.responses must be a list/tuple")
        seen = {_do_key({})}
        for response in raw_responses:
            if type(response) is not dict:
                raise ContractError("world response must be a mapping")
            do_set = _first(response, "do_set", "intervention", "do", default={})
            values = _first(response, "values", "outcomes", "prediction")
            if type(do_set) is not dict or type(values) is not dict:
                raise ContractError("world response requires do_set and values mappings")
            key = _do_key(do_set)
            if key in seen:
                raise ContractError("world contains a duplicate intervention response")
            seen.add(key)
            variables.update(values)
            responses.append(_response_row(do_set, values))
        worlds.append(WorldRowB(world_id, probability, _freeze(exogenous), tuple(responses)))
    total = sum(item.probability for item in worlds)
    if total <= PROB_TOL:
        raise ContractError("SCM worlds have zero probability")
    worlds = [replace(item, probability=item.probability / total) for item in worlds]
    return tuple(sorted(variables)), tuple(worlds)


def _distribution_masses(raw: Any, domain: Sequence[Any], label: str) -> tuple[tuple[Any, float], ...]:
    if type(raw) is dict and "masses" in raw:
        raw = raw["masses"]
    if type(raw) in {list, tuple} and raw and all(type(item) is dict for item in raw):
        pairs = [
            (
                _first(item, "value", "state"),
                _finite_number(_eval_expr(_first(item, "probability", "weight"), {}), label),
            )
            for item in raw
        ]
    elif type(raw) in {list, tuple} and len(raw) == len(domain) and all(type(item) in {int, float} for item in raw):
        pairs = list(zip(domain, (_finite_number(item, label) for item in raw)))
    elif type(raw) is dict:
        pairs = []
        for value in domain:
            found = raw.get(str(value), raw.get(_value_key(value)))
            if found is None:
                raise ContractError(f"{label} missing value {value!r}")
            pairs.append((value, _finite_number(found, label)))
    else:
        raise ContractError(f"{label} has invalid mass representation")
    keys = {_value_key(item) for item in domain}
    if {_value_key(value) for value, _ in pairs} != keys:
        raise ContractError(f"{label} does not exactly cover its domain")
    total = sum(probability for _, probability in pairs)
    if total <= PROB_TOL or any(probability < 0 for _, probability in pairs):
        raise ContractError(f"{label} contains invalid probability mass")
    return tuple((value, probability / total) for value, probability in pairs)


def _worlds_from_structural(model: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[WorldRowB, ...]]:
    variables_raw = model.get("variables")
    if type(variables_raw) not in {list, tuple} or not variables_raw:
        raise ContractError("structural finite_scm requires variables")
    variables: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in variables_raw:
        if type(row) is not dict:
            raise ContractError("SCM variables must be mappings")
        name = _require_text(row.get("name"), "variable.name")
        domain = row.get("domain")
        if name in variables or type(domain) not in {list, tuple} or not domain:
            raise ContractError("SCM variable names/domains must be unique and non-empty")
        variables[name] = row
        order.append(name)

    exogenous_names = [name for name in order if variables[name].get("role") == "exogenous"]
    endogenous_names = [name for name in order if name not in exogenous_names]
    if not exogenous_names or not endogenous_names:
        raise ContractError("SCM requires exogenous and endogenous variables")
    raw_distributions = _first(model, "exogenous_distributions", "exogenous", default=[])
    distribution_map: dict[str, Any] = {}
    if type(raw_distributions) is dict:
        distribution_map = dict(raw_distributions)
    elif type(raw_distributions) in {list, tuple}:
        for row in raw_distributions:
            if type(row) is not dict:
                raise ContractError("exogenous distributions must be mappings")
            target = _require_text(_first(row, "target", "variable"), "exogenous target")
            distribution_map[target] = row
    else:
        raise ContractError("exogenous distributions have invalid shape")
    masses = {
        name: _distribution_masses(
            distribution_map.get(name, variables[name].get("probabilities")),
            variables[name]["domain"],
            f"P({name})",
        )
        for name in exogenous_names
    }

    equations_raw = model.get("equations")
    equations: list[dict[str, Any]] = []
    if type(equations_raw) is dict:
        equations = [{"target": target, "expression": expr} for target, expr in equations_raw.items()]
    elif type(equations_raw) in {list, tuple}:
        equations = list(equations_raw)
    else:
        raise ContractError("SCM equations must be a mapping/list")
    if [row.get("target") for row in equations] != endogenous_names:
        raise ContractError("SCM equations must be topologically ordered and cover endogenous variables")

    intervenable = [
        name for name in endogenous_names
        if bool(variables[name].get("intervenable", False)) or variables[name].get("role") == "action"
    ]
    contexts: list[dict[str, Any]] = [{}]
    for size in range(1, len(intervenable) + 1):
        for subset in combinations(intervenable, size):
            for values in product(*(variables[name]["domain"] for name in subset)):
                contexts.append(dict(zip(subset, values)))
                if len(contexts) > MAX_RESPONSE_CONTEXTS:
                    raise ContractError("SCM intervention context budget exceeded")

    def solve(exogenous: Mapping[str, Any], do_set: Mapping[str, Any]) -> dict[str, Any]:
        env = dict(exogenous)
        for equation in equations:
            target = equation["target"]
            value = do_set[target] if target in do_set else _eval_equation(equation, env)
            domain = variables[target]["domain"]
            match = next((item for item in domain if _value_key(item) == _value_key(value)), None)
            if match is None:
                # Numeric closed expressions often produce 1.0 for domain 1.
                if type(value) in {int, float}:
                    match = next(
                        (item for item in domain if type(item) in {int, float} and abs(float(item) - float(value)) <= 1e-9),
                        None,
                    )
            if match is None:
                raise ContractError(f"equation {target!r} produced out-of-domain value {value!r}")
            env[target] = match
        return {name: env[name] for name in endogenous_names}

    worlds: list[WorldRowB] = []
    mass_axes = [masses[name] for name in exogenous_names]
    for index, choices in enumerate(product(*mass_axes)):
        exo = {name: value_probability[0] for name, value_probability in zip(exogenous_names, choices)}
        probability = 1.0
        for _, p in choices:
            probability *= p
        responses = tuple(_response_row(context, solve(exo, context)) for context in contexts)
        worlds.append(WorldRowB(f"B-world-{index}", probability, _freeze(exo), responses))
        if len(worlds) > MAX_WORLDS:
            raise ContractError("SCM world budget exceeded")
    return tuple(order), tuple(worlds)


def _compile_scm(canonical: Mapping[str, Any], model: Mapping[str, Any]) -> SCMIRB:
    if _first(model, "worlds", "response_worlds") is not None:
        variables, worlds = _worlds_from_rows(model)
    else:
        variables, worlds = _worlds_from_structural(model)
    _, records = _evidence_container(canonical)
    timeline_raw = _first(model, "timeline", "slices", "time_slices")
    if timeline_raw is None:
        timeline_raw = sorted({_record_slice(record) for record in records}, key=_time_sort_key) or [0]
    if type(timeline_raw) not in {list, tuple} or not timeline_raw:
        raise ContractError("finite_scm timeline must be explicit or derivable")
    timeline = tuple(timeline_raw)
    columns: list[EvidenceColumnB] = []
    for index, record in enumerate(records):
        # SCM evidence is a deterministic factual constraint.  A one-element
        # likelihood vector is a placeholder for the shared column container;
        # execution matches variable/value against response worlds.
        columns.append(_common_column(record, index, timeline, (1.0,)))
    return SCMIRB(variables, worlds, tuple(columns))


# ---------------------------------------------------------------------------
# Public compile/recover API
# ---------------------------------------------------------------------------


def compile_bundle(canonical: Mapping[str, Any], target_kernel: str) -> NativeBundleB:
    """Compile one canonical evidence/model bridge bundle.

    ``target_kernel`` is closed to ``finite_dbn`` and ``finite_scm``.  The
    returned object contains a reversible witness, but its executor consumes
    only the independently compiled ``native_ir`` and semantic sidecars.
    """

    if type(canonical) is not dict:
        raise ContractError("canonical bundle must be an exact dict")
    validate_json_like(canonical, label="canonical bridge bundle")
    if target_kernel not in {"finite_dbn", "finite_scm"}:
        raise ContractError("target_kernel must be finite_dbn or finite_scm")
    bundle_id, bridge, cut, versions, uncertainty, model = _canonical_parts(canonical, target_kernel)
    declared_kind = _first(model, "kind", "model_kind")
    allowed_kinds = {
        "finite_dbn": {None, "finite_dbn", "dynamic", "dbn", "finite_hmm"},
        "finite_scm": {None, "finite_scm", "scm"},
    }[target_kernel]
    if declared_kind not in allowed_kinds:
        raise ContractError(f"model kind {declared_kind!r} conflicts with target_kernel={target_kernel}")
    _, records = _evidence_container(canonical)
    roots = _compile_roots(canonical, records)
    native_ir: DBNIRB | SCMIRB
    native_ir = _compile_dbn(canonical, model) if target_kernel == "finite_dbn" else _compile_scm(canonical, model)
    symbols, tape = _make_tape(canonical)
    return NativeBundleB(
        format_version=FORMAT_VERSION,
        target_kernel=target_kernel,
        bundle_id=bundle_id,
        semantic_digest=_tape_digest(symbols, tape),
        recovery_symbols=symbols,
        recovery_tape=tape,
        bridge_sidecar=_freeze(bridge),
        temporal_cut_sidecar=_freeze(cut),
        versions_sidecar=_freeze(versions),
        uncertainty_sidecar=_freeze(uncertainty),
        roots=roots,
        native_ir=native_ir,
    )


def recover_bundle(native: NativeBundleB) -> dict[str, Any]:
    if type(native) is not NativeBundleB:
        raise ContractError("recover_bundle requires exact NativeBundleB")
    if native.format_version != FORMAT_VERSION:
        raise ContractError("unsupported implementation-B native format")
    observed = _tape_digest(native.recovery_symbols, native.recovery_tape)
    if observed != native.semantic_digest:
        raise ContractError("reversible witness digest mismatch")
    return _read_tape(native.recovery_symbols, native.recovery_tape)


# ---------------------------------------------------------------------------
# Query parsing and shared lineage/cut eligibility
# ---------------------------------------------------------------------------


def _query_mapping(query: Mapping[str, Any]) -> dict[str, Any]:
    if type(query) is not dict:
        raise ContractError("query must be an exact inert mapping")
    validate_json_like(query, label="bridge query")
    return dict(query)


def _operator(query: Mapping[str, Any]) -> str:
    raw = _first(query, "kind", "operator", "query_kind")
    aliases = {
        "filter": "filter",
        "filter_state": "filter",
        "smooth": "smooth",
        "smooth_state": "smooth",
        "condition": "condition",
        "intervene": "do",
        "population_do": "do",
        "do": "do",
        "counterfactual": "aap",
        "individual_counterfactual": "aap",
        "aap": "aap",
    }
    if raw not in aliases:
        raise ContractError(f"unsupported closed bridge query operator {raw!r}")
    return aliases[raw]


def _cut(native: NativeBundleB, query: Mapping[str, Any]) -> dict[str, Any]:
    base = _mapping_from_frozen(native.temporal_cut_sidecar, "temporal_cut")
    override = _first(query, "temporal_cut", "cut")
    if override is not None:
        if type(override) is not dict:
            raise ContractError("query temporal_cut override must be a mapping")
        base = {**base, **override}
    if "as_known_at" in query:
        base["actor_visibility_cut"] = query["as_known_at"]
    if "transaction_revision_cut" in query:
        base["transaction_revision_cut"] = query["transaction_revision_cut"]
    return base


def _column_eligible(column: EvidenceColumnB, cut: Mapping[str, Any]) -> bool:
    if not column.active:
        return False
    visibility = _first(cut, "actor_visibility_cut", "as_known_at")
    if visibility is not None and not _not_after(column.available_at, visibility):
        return False
    revision_cut = _first(cut, "transaction_revision_cut", "revision")
    if revision_cut is not None and column.transaction_revision is not None:
        if not _not_after(column.transaction_revision, revision_cut):
            return False
    return True


def _root_witness(native: NativeBundleB, root_ids: Iterable[str]) -> list[dict[str, Any]]:
    wanted = set(root_ids)
    out: list[dict[str, Any]] = []
    for row in native.roots:
        if row.root_id in wanted:
            item = _thaw(row.metadata)
            if type(item) is not dict:
                item = {"root_id": row.root_id, "version": row.version}
            item = {**item, "root_id": row.root_id, "root_version": row.version, "active": row.active}
            out.append(item)
    return out


def _base_result(
    native: NativeBundleB,
    operator: str,
    operator_tag: str,
    cut: Mapping[str, Any],
    columns: Sequence[EvidenceColumnB],
    distribution: list[dict[str, Any]],
    *,
    target: str,
    extra_witness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_ids: list[str] = []
    for column in columns:
        for rid in column.root_ids:
            if rid not in root_ids:
                root_ids.append(rid)
    uncertainty = _mapping_from_frozen(native.uncertainty_sidecar, "uncertainty")
    versions = _mapping_from_frozen(native.versions_sidecar, "versions")
    witness = {
        "implementation": "B",
        "native_format": native.format_version,
        "bundle_digest": native.semantic_digest,
        "operator_tag": operator_tag,
        "native_addresses": [column.native_address for column in columns],
        "used_roots": _root_witness(native, root_ids),
        "used_cut": dict(cut),
        "versions": versions,
        "bridge": _mapping_from_frozen(native.bridge_sidecar, "bridge"),
        "uncertainty": uncertainty,
        "evidence_uncertainty": [
            {"native_address": column.native_address, "uncertainty": _thaw(column.uncertainty)}
            for column in columns
        ],
    }
    if extra_witness:
        witness.update(extra_witness)
    mean = None
    if distribution and all(type(row["value"]) in {int, float} for row in distribution):
        mean = sum(float(row["value"]) * row["probability"] for row in distribution)
    result = {
        "status": "ok",
        "operator": operator,
        "operator_tag": operator_tag,
        "target": target,
        "distribution": distribution,
        "used_cut": dict(cut),
        "used_roots": root_ids,
        "witness": witness,
        "numerics": {"kind": "exact_finite_enumeration", "normalization_error": abs(sum(row["probability"] for row in distribution) - 1.0)},
    }
    if mean is not None:
        result["mean"] = mean
    return result


def _normalize(weights: Sequence[float], label: str) -> tuple[float, ...]:
    if any(not isfinite(value) or value < -PROB_TOL for value in weights):
        raise ContractError(f"{label} produced invalid weights")
    total = sum(max(0.0, value) for value in weights)
    if total <= PROB_TOL:
        raise ContractError(f"{label} has zero compatible probability")
    return tuple(max(0.0, value) / total for value in weights)


def _distribution(values: Sequence[Any], weights: Sequence[float]) -> list[dict[str, Any]]:
    merged: dict[str, tuple[Any, float]] = {}
    for value, probability in zip(values, weights):
        key = _value_key(value)
        if key in merged:
            merged[key] = (value, merged[key][1] + probability)
        else:
            merged[key] = (value, probability)
    total = sum(probability for _, probability in merged.values())
    if total <= PROB_TOL:
        raise ContractError("output distribution has zero mass")
    return [
        {"value": value, "probability": probability / total}
        for _, (value, probability) in sorted(merged.items())
    ]


# ---------------------------------------------------------------------------
# Native DBN execution
# ---------------------------------------------------------------------------


def _transition(block: Sequence[float], vector: Sequence[float]) -> tuple[float, ...]:
    n = len(vector)
    return _normalize(
        [sum(vector[i] * block[i * n + j] for i in range(n)) for j in range(n)],
        "DBN transition",
    )


def _emission_by_slice(columns: Sequence[EvidenceColumnB], n_states: int) -> dict[int, tuple[float, ...]]:
    by_slice: dict[int, list[EvidenceColumnB]] = {}
    for column in columns:
        by_slice.setdefault(column.slice_index, []).append(column)
    out: dict[int, tuple[float, ...]] = {}
    for slice_index, rows in by_slice.items():
        out[slice_index] = tuple(
            math_prod(row.likelihood[state_index] for row in rows)
            for state_index in range(n_states)
        )
    return out


def _execute_dbn(native: NativeBundleB, query: Mapping[str, Any], operator: str) -> dict[str, Any]:
    ir = native.native_ir
    if type(ir) is not DBNIRB:
        raise ContractError("native finite_dbn capsule has the wrong IR")
    if operator not in {"filter", "smooth"}:
        raise ContractError("finite_dbn supports only filter and retrospective smooth in this holdout")
    cut = _cut(native, query)
    target_label = _first(query, "target_slice", "target_time", "valid_at")
    if target_label is None:
        target_label = ir.timeline[-1]
    target_index = _timeline_index(ir.timeline, target_label, label_name="query target slice")

    eligible = [column for column in ir.evidence_columns if _column_eligible(column, cut)]
    if operator == "filter":
        final_index = target_index
        used = [column for column in eligible if column.slice_index <= target_index]
    else:
        later_policy = _first(query, "later_evidence_policy", default=cut.get("later_evidence_policy"))
        if later_policy is None:
            raise ContractError("smooth requires an explicit later_evidence_policy")
        through_label = _first(query, "evidence_through", "smoothing_end", "through_slice")
        if through_label is None:
            final_index = max([target_index, *(column.slice_index for column in eligible)])
        else:
            final_index = _timeline_index(ir.timeline, through_label, label_name="smooth evidence_through")
        if final_index < target_index:
            raise ContractError("smooth evidence_through cannot precede target slice")
        used = [column for column in eligible if column.slice_index <= final_index]

    emissions = _emission_by_slice(used, len(ir.states))
    alpha = tuple(ir.prior)
    e0 = emissions.get(0, tuple(1.0 for _ in ir.states))
    alpha = _normalize([a * e for a, e in zip(alpha, e0)], "DBN initial evidence")
    for edge in range(target_index):
        alpha = _transition(ir.transition_blocks[edge], alpha)
        emission = emissions.get(edge + 1, tuple(1.0 for _ in ir.states))
        alpha = _normalize([a * e for a, e in zip(alpha, emission)], "DBN forward evidence")

    if operator == "filter":
        posterior = alpha
        tag = "finite_dbn/filter-forward/v1"
        extra = {"target_slice": target_label, "filter_evidence_horizon": target_label, "future_evidence_used": False}
    else:
        beta = tuple(1.0 for _ in ir.states)
        n = len(ir.states)
        for edge in range(final_index - 1, target_index - 1, -1):
            block = ir.transition_blocks[edge]
            next_emission = emissions.get(edge + 1, tuple(1.0 for _ in ir.states))
            beta = tuple(
                sum(block[i * n + j] * next_emission[j] * beta[j] for j in range(n))
                for i in range(n)
            )
        posterior = _normalize([a * b for a, b in zip(alpha, beta)], "DBN smoothing")
        tag = "finite_dbn/smooth-forward-backward/v1"
        extra = {
            "target_slice": target_label,
            "smoothing_evidence_through": ir.timeline[final_index],
            "later_evidence_policy": _first(query, "later_evidence_policy", default=cut.get("later_evidence_policy")),
            "future_evidence_used": any(column.slice_index > target_index for column in used),
        }
    target = str(_first(query, "target", "estimand", default="latent_state"))
    return _base_result(native, operator, tag, cut, used, _distribution(ir.states, posterior), target=target, extra_witness=extra)


# ---------------------------------------------------------------------------
# Native SCM execution
# ---------------------------------------------------------------------------


def _response(world: WorldRowB, do_set: Mapping[str, Any]) -> dict[str, Any]:
    key = _do_key(do_set)
    for row in world.responses:
        if row.do_key == key:
            value = _thaw(row.values)
            if type(value) is not dict:
                raise ContractError("compiled response values are not a mapping")
            return value
    raise ContractError(f"SCM response table lacks intervention context {dict(do_set)!r}")


def _condition_mapping(raw: Any, label: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if type(raw) is dict:
        return dict(raw)
    if type(raw) in {list, tuple}:
        out: dict[str, Any] = {}
        for item in raw:
            if type(item) is not dict:
                raise ContractError(f"{label} rows must be mappings")
            variable = _record_variable(item)
            if variable in out and _value_key(out[variable]) != _value_key(item.get("value")):
                raise ContractError(f"{label} contains conflicting values for {variable!r}")
            out[variable] = item.get("value")
        return out
    raise ContractError(f"{label} must be a mapping/list")


def _eligible_scm_columns(native: NativeBundleB, cut: Mapping[str, Any]) -> list[EvidenceColumnB]:
    ir = native.native_ir
    assert type(ir) is SCMIRB
    return [column for column in ir.evidence_columns if _column_eligible(column, cut)]


def _columns_for_condition(columns: Sequence[EvidenceColumnB], condition: Mapping[str, Any]) -> list[EvidenceColumnB]:
    used: list[EvidenceColumnB] = []
    for column in columns:
        if column.variable in condition and _value_key(column.value) == _value_key(condition[column.variable]):
            used.append(column)
    return used


def _bundle_factual(columns: Sequence[EvidenceColumnB]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in columns:
        if column.variable in out and _value_key(out[column.variable]) != _value_key(column.value):
            raise ContractError(f"active factual evidence conflicts for {column.variable!r}")
        out[column.variable] = column.value
    return out


def _world_matches(values: Mapping[str, Any], condition: Mapping[str, Any]) -> bool:
    return all(name in values and _value_key(values[name]) == _value_key(value) for name, value in condition.items())


def _execute_scm(native: NativeBundleB, query: Mapping[str, Any], operator: str) -> dict[str, Any]:
    ir = native.native_ir
    if type(ir) is not SCMIRB:
        raise ContractError("native finite_scm capsule has the wrong IR")
    if operator not in {"condition", "do", "aap"}:
        raise ContractError("finite_scm supports condition, population do, and same-patient AAP")
    cut = _cut(native, query)
    eligible_columns = _eligible_scm_columns(native, cut)
    target = _require_text(_first(query, "target", "estimand"), "SCM query target")
    if target not in ir.variables:
        raise ContractError(f"SCM target {target!r} is outside the compiled model")

    if operator == "condition":
        condition = _condition_mapping(_first(query, "observation_set", "condition", "given"), "condition")
        if not condition:
            condition = _bundle_factual(eligible_columns)
        weights: list[float] = []
        values: list[Any] = []
        for world in ir.worlds:
            factual = _response(world, {})
            if _world_matches(factual, condition):
                weights.append(world.probability)
                values.append(factual[target])
        normalized = _normalize(weights, "SCM conditioning")
        used = _columns_for_condition(eligible_columns, condition)
        return _base_result(
            native, operator, "finite_scm/condition-observational/v1", cut, used,
            _distribution(values, normalized), target=target,
            extra_witness={"observation_set": condition, "mechanism_replaced": False, "abduction": False},
        )

    do_set = _condition_mapping(_first(query, "do_set", "intervention", "do"), "do_set")
    if not do_set:
        raise ContractError(f"{operator} query requires a non-empty do_set")
    if operator == "do":
        population_condition = _condition_mapping(
            _first(query, "population_condition", "population_evidence"), "population condition"
        )
        weights = []
        values = []
        for world in ir.worlds:
            factual = _response(world, {})
            if population_condition and not _world_matches(factual, population_condition):
                continue
            counter = _response(world, do_set)
            weights.append(world.probability)
            values.append(counter[target])
        normalized = _normalize(weights, "SCM population intervention")
        used = _columns_for_condition(eligible_columns, population_condition)
        return _base_result(
            native, operator, "finite_scm/do-population-mechanism-replacement/v1", cut, used,
            _distribution(values, normalized), target=target,
            extra_witness={
                "do_set": do_set,
                "population_condition": population_condition,
                "mechanism_replaced": True,
                "abduction": False,
                "shared_world_identity": False,
            },
        )

    factual_condition = _condition_mapping(
        _first(query, "factual_evidence", "factual", "abduction_evidence"), "AAP factual evidence"
    )
    if not factual_condition:
        factual_condition = _bundle_factual(eligible_columns)
    if not factual_condition:
        raise ContractError("AAP requires factual evidence for abduction")
    shared_policy = _first(query, "shared_world_policy", "cross_world_policy")
    if shared_policy not in {"share_abduced_exogenous", "shared_exogenous", "same_world", "paired_world"}:
        raise ContractError("AAP requires an explicit shared-exogenous world policy")
    selected: list[WorldRowB] = []
    posterior_raw: list[float] = []
    for world in ir.worlds:
        if _world_matches(_response(world, {}), factual_condition):
            selected.append(world)
            posterior_raw.append(world.probability)
    posterior = _normalize(posterior_raw, "SCM factual abduction")
    predictions = [_response(world, do_set)[target] for world in selected]
    used = _columns_for_condition(eligible_columns, factual_condition)
    return _base_result(
        native, operator, "finite_scm/aap-shared-response-world/v1", cut, used,
        _distribution(predictions, posterior), target=target,
        extra_witness={
            "factual_evidence": factual_condition,
            "do_set": do_set,
            "mechanism_replaced": True,
            "abduction": True,
            "action": True,
            "prediction": True,
            "shared_world_identity": True,
            "shared_world_policy": shared_policy,
            "abduced_world_posterior": [
                {"world_id": world.world_id, "probability": probability}
                for world, probability in zip(selected, posterior)
            ],
        },
    )


def execute(native: NativeBundleB, query: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one closed query against compiled semantic fields only."""

    if type(native) is not NativeBundleB or native.format_version != FORMAT_VERSION:
        raise ContractError("execute requires an implementation-B native bundle")
    parsed = _query_mapping(query)
    operator = _operator(parsed)
    if native.target_kernel == "finite_dbn":
        return _execute_dbn(native, parsed, operator)
    if native.target_kernel == "finite_scm":
        return _execute_scm(native, parsed, operator)
    raise ContractError("native target kernel is unsupported")


# ---------------------------------------------------------------------------
# Typed evidence deltas
# ---------------------------------------------------------------------------


def _delta_kind(delta: Mapping[str, Any]) -> str:
    raw = _first(delta, "kind", "type", "delta_type")
    if raw in {"Corrects", "corrects", "CORRECTS"}:
        return "Corrects"
    if raw in {"Retracts", "retracts", "RETRACTS"}:
        return "Retracts"
    raise ContractError("delta kind must be typed Corrects or Retracts")


def _delta_old_id(delta: Mapping[str, Any]) -> str:
    old = _first(delta, "old", "old_record_id", "record_id", "root_id", "retracts")
    if type(old) is dict:
        old = _first(old, "record_id", "root_id", "id", "logical_id")
    return _require_text(old, "delta old identity")


def _column_matches_delta(column: EvidenceColumnB, identity: str) -> bool:
    return identity in {column.record_id, column.logical_id, *column.root_ids}


def _root_matches_delta(root: RootRowB, identity: str) -> bool:
    return identity in {root.root_id, root.logical_id}


def _active_canonical_after_delta(canonical: dict[str, Any], delta: Mapping[str, Any]) -> dict[str, Any]:
    """Update only the recovery witness's active projection.

    Numeric execution is updated separately from native columns below.  This
    helper must therefore never be called by ``execute``.
    """

    kind = _delta_kind(delta)
    identity = _delta_old_id(delta)
    roots_raw, records = _evidence_container(canonical)

    def record_matches(row: Mapping[str, Any]) -> bool:
        rid = _record_id(row, 0)
        logical = str(_first(row, "logical_id", default=rid))
        return identity in {rid, logical, *_record_roots(row)}

    active_records = [dict(row) for row in records if not record_matches(row)]
    active_roots = [item for item in roots_raw if not (_root_id(item) == identity or (type(item) is dict and str(_first(item, "logical_id", default="")) == identity))]
    if kind == "Corrects":
        new_record = _first(delta, "new_record", "new", "replacement")
        if type(new_record) is dict and "record" in new_record:
            new_record = new_record["record"]
        if type(new_record) is not dict:
            raise ContractError("Corrects delta requires a new_record mapping")
        active_records.append(dict(new_record))
        new_root = _first(delta, "new_root", "root")
        if new_root is not None:
            if type(new_root) not in {str, dict}:
                raise ContractError("Corrects new_root must be a string/mapping")
            active_roots.append(new_root)
        elif not roots_raw:
            pass

    if "evidence" in canonical and type(canonical["evidence"]) is dict:
        evidence = dict(canonical["evidence"])
        if "records" in evidence:
            evidence["records"] = active_records
        elif "slices" in evidence:
            evidence["slices"] = active_records
        else:
            evidence["observations"] = active_records
        if "roots" in evidence:
            evidence["roots"] = active_roots
        canonical["evidence"] = evidence
    elif "evidence" in canonical:
        canonical["evidence"] = active_records
    elif "observations" in canonical:
        canonical["observations"] = active_records
    if "roots" in canonical:
        canonical["roots"] = active_roots
    elif "evidence_roots" in canonical:
        canonical["evidence_roots"] = active_roots

    version_update = _first(delta, "versions", "version_vector")
    if type(version_update) is dict:
        key = "versions" if "versions" in canonical else "version_vector"
        current = canonical.get(key, {})
        canonical[key] = {**current, **version_update}
    cut_update = _first(delta, "temporal_cut", "cut")
    if type(cut_update) is dict:
        key = "temporal_cut" if "temporal_cut" in canonical else "cut"
        current = canonical.get(key, {})
        canonical[key] = {**current, **cut_update}
    return canonical


def _compile_correction_column(native: NativeBundleB, record: Mapping[str, Any], index: int) -> EvidenceColumnB:
    if type(native.native_ir) is DBNIRB:
        ir = native.native_ir
        model = None
        raw_likelihood = _first(record, "likelihood", "state_likelihood")
        if raw_likelihood is None:
            raise ContractError("incremental DBN correction must carry an explicit state likelihood")
        likelihood = _likelihood_vector(raw_likelihood, ir.states, "correction likelihood")
        return _common_column(record, index, ir.timeline, likelihood)
    ir = native.native_ir
    assert type(ir) is SCMIRB
    timeline = tuple(
        sorted(
            {_record_slice(record), *(column.slice_label for column in ir.evidence_columns)},
            key=_time_sort_key,
        )
    )
    # The existing compiled timeline addresses must remain stable.  New SCM
    # evidence may only use an already declared slice in this finite holdout.
    old_timeline = tuple(dict.fromkeys(column.slice_label for column in ir.evidence_columns))
    if old_timeline and _value_key(_record_slice(record)) not in {_value_key(item) for item in old_timeline}:
        raise ContractError("incremental SCM correction cannot introduce an undeclared temporal slice")
    return _common_column(record, index, old_timeline or timeline, (1.0,))


def apply_delta(native: NativeBundleB, delta: Mapping[str, Any]) -> NativeBundleB:
    """Apply a typed evidence correction/retraction to immutable native IR.

    The model tables/prior/mechanisms are retained byte-for-byte.  Only lineage
    rows and evidence columns are marked inactive/appended.  Thus retraction is
    eligibility removal, never a negative likelihood.
    """

    if type(native) is not NativeBundleB:
        raise ContractError("apply_delta requires exact NativeBundleB")
    if type(delta) is not dict:
        raise ContractError("delta must be an exact mapping")
    validate_json_like(delta, label="bridge delta")
    kind = _delta_kind(delta)
    identity = _delta_old_id(delta)
    ir = native.native_ir
    columns = list(ir.evidence_columns)
    matched = [index for index, column in enumerate(columns) if column.active and _column_matches_delta(column, identity)]
    if not matched:
        raise ContractError(f"delta identity {identity!r} has no active native evidence column")
    for index in matched:
        columns[index] = replace(columns[index], active=False)

    roots = list(native.roots)
    for index, root in enumerate(roots):
        if root.active and _root_matches_delta(root, identity):
            roots[index] = replace(root, active=False)

    if kind == "Corrects":
        new_record = _first(delta, "new_record", "new", "replacement")
        if type(new_record) is dict and "record" in new_record:
            new_record = new_record["record"]
        if type(new_record) is not dict:
            raise ContractError("Corrects delta requires new_record")
        column = _compile_correction_column(native, new_record, len(columns))
        columns.append(column)
        new_root = _first(delta, "new_root", "root")
        if new_root is not None:
            rid = _root_id(new_root)
            metadata_value = {"root_id": rid, "version": "unversioned"} if type(new_root) is str else new_root
            logical = rid if type(new_root) is str else str(_first(new_root, "logical_id", default=rid))
            roots.append(RootRowB(rid, _root_version(new_root), logical, True, _freeze(metadata_value)))
        elif any(rid not in {root.root_id for root in roots} for rid in column.root_ids):
            for rid in column.root_ids:
                if rid not in {root.root_id for root in roots}:
                    roots.append(RootRowB(rid, column.record_version, rid, True, _freeze({"root_id": rid, "version": column.record_version})))

    new_ir: DBNIRB | SCMIRB
    if type(ir) is DBNIRB:
        new_ir = replace(ir, evidence_columns=tuple(columns))
    else:
        new_ir = replace(ir, evidence_columns=tuple(columns))

    # Recovery/audit witness is updated independently of numeric IR mutation.
    recovered = recover_bundle(native)
    active = _active_canonical_after_delta(recovered, delta)
    symbols, tape = _make_tape(active)
    versions = _mapping_from_frozen(native.versions_sidecar, "versions")
    version_update = _first(delta, "versions", "version_vector")
    if type(version_update) is dict:
        versions.update(version_update)
    cut = _mapping_from_frozen(native.temporal_cut_sidecar, "temporal_cut")
    cut_update = _first(delta, "temporal_cut", "cut")
    if type(cut_update) is dict:
        cut.update(cut_update)
    return replace(
        native,
        semantic_digest=_tape_digest(symbols, tape),
        recovery_symbols=symbols,
        recovery_tape=tape,
        temporal_cut_sidecar=_freeze(cut),
        versions_sidecar=_freeze(versions),
        roots=tuple(roots),
        native_ir=new_ir,
        delta_history=(*native.delta_history, _freeze(dict(delta))),
    )


# ---------------------------------------------------------------------------
# Deterministic demos/self-test (not workload-ID dispatch)
# ---------------------------------------------------------------------------


def demo_dbn_bundle() -> dict[str, Any]:
    return {
        "schema_version": CANONICAL_SCHEMA,
        "bundle_id": "holdout-b-dbn-demo",
        "bridge": {"bridge_id": "lab-to-latent", "version": "bridge-7", "registered_at": "2026-01-01T00:00:00Z"},
        "temporal_cut": {
            "target_window": [0, 1],
            "actor_visibility_cut": 1,
            "transaction_revision_cut": 3,
            "evidence_use_policy": "query-specific",
            "evidence_snapshot_id": "snap-3",
            "later_evidence_policy": "allow-visible-later-evidence",
        },
        "versions": {"evidence_authority": "tel-4", "knowledge": "k-9", "model": "dbn-2", "solver": "exact-b-1"},
        "uncertainty": {"kind": "probability", "taints": {"coverage": "in_domain", "identification": "not_applicable"}},
        "roots": [
            {"root_id": "root-early", "root_version": "1", "logical_id": "early-lab", "dependence_families": ["specimen-A"]},
            {"root_id": "root-late", "root_version": "2", "logical_id": "late-lab", "dependence_families": ["specimen-B"]},
        ],
        "evidence": [
            {
                "record_id": "obs-early-v1", "logical_id": "obs-early", "version": "1",
                "slice": 0, "available_at": 0, "transaction_revision": 1,
                "variable": "marker", "value": "positive", "root_ids": ["root-early"],
                "likelihood": {"well": 0.9, "ill": 0.1},
                "uncertainty": {"kind": "assay_likelihood", "version": "u-1"},
            },
            {
                "record_id": "obs-late-v2", "logical_id": "obs-late", "version": "2",
                "slice": 1, "available_at": 1, "transaction_revision": 2,
                "variable": "marker", "value": "positive", "root_ids": ["root-late"],
                "likelihood": {"well": 0.1, "ill": 0.9},
                "uncertainty": {"kind": "assay_likelihood", "version": "u-2"},
            },
        ],
        "model": {
            "kind": "finite_dbn",
            "states": ["well", "ill"],
            "timeline": [0, 1],
            "prior": {"well": 0.5, "ill": 0.5},
            "transition_matrix": {"well": {"well": 0.8, "ill": 0.2}, "ill": {"well": 0.2, "ill": 0.8}},
        },
    }


def demo_scm_bundle() -> dict[str, Any]:
    return {
        "schema_version": CANONICAL_SCHEMA,
        "bundle_id": "holdout-b-scm-demo",
        "bridge": {"bridge_id": "factual-to-scm", "version": "bridge-11", "registered_at": "2026-01-01T00:00:00Z"},
        "temporal_cut": {"target_window": [0, 0], "actor_visibility_cut": 0, "transaction_revision_cut": 5, "evidence_snapshot_id": "scm-snap-5"},
        "versions": {"evidence_authority": "tel-4", "causal_model": "scm-3", "solver": "world-table-b-1"},
        "uncertainty": {"kind": "finite_probability", "identification": "assumption_dependent"},
        "roots": [
            {"root_id": "root-T", "root_version": "1", "logical_id": "performed-T"},
            {"root_id": "root-Y", "root_version": "1", "logical_id": "observed-Y"},
        ],
        "evidence": [
            {"record_id": "f-T", "slice": 0, "available_at": 0, "transaction_revision": 1, "variable": "T", "value": 1, "root_ids": ["root-T"], "uncertainty": {"kind": "exact"}},
            {"record_id": "f-Y", "slice": 0, "available_at": 0, "transaction_revision": 2, "variable": "Y", "value": 2, "root_ids": ["root-Y"], "uncertainty": {"kind": "exact"}},
        ],
        "model": {
            "kind": "finite_scm",
            "timeline": [0],
            "worlds": [
                {
                    "world_id": "R=0", "probability": 0.5, "exogenous": {"R": 0},
                    "factual": {"T": 1, "Y": -1},
                    "responses": [
                        {"do_set": {"T": 0}, "values": {"T": 0, "Y": 0}},
                        {"do_set": {"T": 1}, "values": {"T": 1, "Y": -1}},
                    ],
                },
                {
                    "world_id": "R=1", "probability": 0.5, "exogenous": {"R": 1},
                    "factual": {"T": 1, "Y": 2},
                    "responses": [
                        {"do_set": {"T": 0}, "values": {"T": 0, "Y": 1}},
                        {"do_set": {"T": 1}, "values": {"T": 1, "Y": 2}},
                    ],
                },
            ],
        },
    }


def self_test() -> dict[str, Any]:
    dbn_source = demo_dbn_bundle()
    dbn = compile_bundle(dbn_source, "finite_dbn")
    assert recover_bundle(dbn) == dbn_source
    filtered = execute(dbn, {"kind": "filter", "target": "state", "target_slice": 0})
    smoothed = execute(dbn, {"kind": "smooth", "target": "state", "target_slice": 0, "evidence_through": 1, "later_evidence_policy": "allow-visible-later-evidence"})
    assert filtered["operator_tag"] != smoothed["operator_tag"]
    assert filtered["used_roots"] == ["root-early"]
    assert smoothed["used_roots"] == ["root-early", "root-late"]
    assert filtered["distribution"] != smoothed["distribution"]

    # Prove execution does not decode/echo the reversible witness.
    poisoned = replace(dbn, recovery_symbols=(), recovery_tape=(), semantic_digest="poisoned")
    assert execute(poisoned, {"kind": "filter", "target": "state", "target_slice": 0})["distribution"] == filtered["distribution"]
    try:
        recover_bundle(poisoned)
    except ContractError:
        pass
    else:  # pragma: no cover - assertion documents the audit boundary
        raise AssertionError("tampered recovery witness was accepted")

    retracted = apply_delta(dbn, {"kind": "Retracts", "old": "root-late", "reason": "source correction", "versions": {"evidence_authority": "tel-5"}})
    smoothed_after = execute(retracted, {"kind": "smooth", "target": "state", "target_slice": 0, "evidence_through": 1, "later_evidence_policy": "allow-visible-later-evidence"})
    assert smoothed_after["used_roots"] == ["root-early"]
    assert all(row["value"] != "negative" for row in smoothed_after["distribution"])
    retracted_clean = compile_bundle(recover_bundle(retracted), "finite_dbn")
    assert execute(retracted_clean, {"kind": "smooth", "target": "state", "target_slice": 0, "evidence_through": 1, "later_evidence_policy": "allow-visible-later-evidence"})["distribution"] == smoothed_after["distribution"]

    corrected_record = {
        "record_id": "obs-late-v3", "logical_id": "obs-late", "version": "3",
        "slice": 1, "available_at": 1, "transaction_revision": 3,
        "variable": "marker", "value": "negative", "root_ids": ["root-late-v3"],
        "likelihood": {"well": 0.95, "ill": 0.05},
        "uncertainty": {"kind": "assay_likelihood", "version": "u-3"},
    }
    corrected = apply_delta(dbn, {
        "kind": "Corrects", "old": "root-late", "new_record": corrected_record,
        "new_root": {"root_id": "root-late-v3", "root_version": "3", "logical_id": "late-lab"},
        "versions": {"evidence_authority": "tel-6"},
    })
    corrected_result = execute(corrected, {"kind": "smooth", "target": "state", "target_slice": 0, "evidence_through": 1, "later_evidence_policy": "allow-visible-later-evidence"})
    assert corrected_result["used_roots"] == ["root-early", "root-late-v3"]
    corrected_clean = compile_bundle(recover_bundle(corrected), "finite_dbn")
    corrected_clean_result = execute(corrected_clean, {"kind": "smooth", "target": "state", "target_slice": 0, "evidence_through": 1, "later_evidence_policy": "allow-visible-later-evidence"})
    assert corrected_clean_result["distribution"] == corrected_result["distribution"]
    assert corrected_clean_result["used_roots"] == corrected_result["used_roots"]

    scm_source = demo_scm_bundle()
    scm = compile_bundle(scm_source, "finite_scm")
    assert recover_bundle(scm) == scm_source
    conditioned = execute(scm, {"kind": "condition", "target": "Y", "observation_set": {"T": 1}})
    population_do = execute(scm, {"kind": "do", "target": "Y", "do_set": {"T": 0}})
    aap = execute(scm, {
        "kind": "aap", "target": "Y", "factual_evidence": {"T": 1, "Y": 2},
        "do_set": {"T": 0}, "shared_world_policy": "share_abduced_exogenous",
    })
    assert len({conditioned["operator_tag"], population_do["operator_tag"], aap["operator_tag"]}) == 3
    assert abs(population_do["mean"] - 0.5) <= 1e-12
    assert aap["distribution"] == [{"value": 1, "probability": 1.0}]
    assert aap["witness"]["shared_world_identity"] is True
    assert population_do["witness"]["shared_world_identity"] is False
    return {
        "strict_round_trip": True,
        "filter_root_count": len(filtered["used_roots"]),
        "smooth_root_count": len(smoothed["used_roots"]),
        "retraction_is_not_negative": True,
        "delta_equals_clean_rebuild": True,
        "condition_tag": conditioned["operator_tag"],
        "do_tag": population_do["operator_tag"],
        "aap_tag": aap["operator_tag"],
        "aap_mean": aap["mean"],
    }


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, indent=2, sort_keys=True))


__all__ = [
    "CANONICAL_SCHEMA",
    "FORMAT_VERSION",
    "NativeBundleB",
    "apply_delta",
    "compile_bundle",
    "demo_dbn_bundle",
    "demo_scm_bundle",
    "execute",
    "recover_bundle",
    "self_test",
]
