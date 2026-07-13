"""Independent implementation A for the evidence -> model bridge holdout.

This module deliberately does not import the other holdout implementation, the
benchmark reference models, or the existing model executor.  It implements a
small, closed protocol directly from ``FORMAL_SPEC.md``:

* evidence occurrence roots, raw/source anchors and dependence families are
  kept in a root table and referenced (never copied into extra "votes");
* record clocks, the frozen temporal cut and every version vector component are
  first-class data;
* measurement uncertainty is a tagged union, distinct from evidence
  unknown/conflict and from nondeterministic model state;
* query intent is a closed tagged union.  ``filter``, retrospective ``smooth``,
  ``condition``, population ``intervene`` and same-patient ``aap`` never share
  an operator implementation;
* compilation produces executable finite DBN or finite SCM IR.  Recovery is
  from semantic IR tables plus a lineage sidecar, not from an opaque copy of the
  input envelope;
* corrections/retractions are append-only deltas.  A retraction removes an
  eligible root; it never creates a negative observation.

The canonical bundle accepted by :func:`compile_bundle` is JSON-shaped and has
exactly these top-level fields::

    {
      "schema_version": "vesmed.bridge-holdout.canonical/1",
      "bridge": {...}, "scope": {...}, "temporal_cut": {...},
      "version_vector": {...}, "roots": [...],
      "evidence_history": [...], "deltas": [...],
      "models": {"finite_dbn": {...}, "finite_scm": {...}},
      "queries": [...], "uncertainty_contract": {...}
    }

``self_test()`` below is an executable example of the complete schema.  The
models are intentionally finite architecture probes, not clinical models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isclose, isfinite
from typing import Any, Mapping, Sequence

CANONICAL_SCHEMA = "vesmed.bridge-holdout.canonical/1"
NATIVE_SCHEMA = "vesmed.bridge-holdout.native-a/1"
COMPILER_ID = "impl-a-closed-finite/1"
TARGET_KERNELS = frozenset({"finite_dbn", "finite_scm"})
QUERY_KINDS = frozenset({"filter", "smooth", "condition", "intervene", "aap"})


class ContractError(ValueError):
    """Implementation-A-local closed-protocol validation failure."""


class SemanticLossError(ContractError):
    """A conversion would erase or conflate a required semantic distinction."""


def parse_time(value: str | datetime | None) -> datetime | None:
    """Parse an aware ISO-8601 instant without any repository helper code."""

    if value is None:
        return None
    if type(value) is datetime:
        parsed = value
    elif type(value) is str and value and len(value) <= 128:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractError(f"invalid ISO-8601 time {value!r}") from exc
    else:
        raise ContractError("time must be an exact non-empty str or datetime")
    if parsed.tzinfo is None:
        raise ContractError(f"time must include a timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def validate_json_like(
    value: Any,
    *,
    label: str = "value",
    allow_tuple: bool = False,
    max_depth: int = 64,
    max_nodes: int = 65_536,
    max_bytes: int = 1_048_576,
) -> None:
    """Validate an inert exact-builtin JSON tree with finite resource bounds."""

    if type(max_depth) is not int or max_depth < 0:
        raise ContractError("max_depth must be a non-negative exact int")
    if type(max_nodes) is not int or max_nodes < 1:
        raise ContractError("max_nodes must be a positive exact int")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ContractError("max_bytes must be a positive exact int")
    active: set[int] = set()
    nodes = 0
    bytes_used = 0

    def charge(node_count: int, byte_count: int) -> None:
        nonlocal nodes, bytes_used
        nodes += node_count
        bytes_used += byte_count
        if nodes > max_nodes or bytes_used > max_bytes:
            raise ContractError(f"{label} exceeds inert JSON resource budget")

    def visit(item: Any, depth: int, path: str) -> None:
        if depth > max_depth:
            raise ContractError(f"{label} exceeds depth budget at {path}")
        kind = type(item)
        if kind is type(None):
            charge(1, 4)
        elif kind is bool:
            charge(1, 5)
        elif kind is int:
            bits = item.bit_length()
            decimal_bound = 1 if bits == 0 else (bits * 30103) // 100000 + 3
            charge(1, decimal_bound)
        elif kind is float:
            if not isfinite(item):
                raise ContractError(f"{path} must not contain a non-finite float")
            charge(1, 24)
        elif kind is str:
            encoded = item.encode("utf-8")
            charge(1, len(encoded) + 2)
        elif kind is dict:
            marker = id(item)
            if marker in active:
                raise ContractError(f"{path} contains a cycle")
            active.add(marker)
            try:
                charge(1, 2)
                for index, (key, child) in enumerate(dict.items(item)):
                    if type(key) is not str:
                        raise ContractError(f"{path} has a non-string object key")
                    visit(key, depth + 1, f"{path}.<key:{index}>")
                    visit(child, depth + 1, f"{path}.{key}")
                    charge(0, 2 if index == 0 else 3)
            finally:
                active.remove(marker)
        elif kind is list or (allow_tuple and kind is tuple):
            marker = id(item)
            if marker in active:
                raise ContractError(f"{path} contains a cycle")
            active.add(marker)
            try:
                charge(1, 2)
                for index in range(len(item)):
                    visit(item[index], depth + 1, f"{path}[{index}]")
                    if index:
                        charge(0, 1)
            finally:
                active.remove(marker)
        else:
            raise ContractError(
                f"{path} contains non-inert type {kind.__name__}; exact JSON builtins required"
            )

    visit(value, 0, label)


def _strict_fields(
    value: Mapping[str, Any],
    required: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> None:
    if type(value) is not dict:
        raise ContractError(f"{label} must be an exact dict")
    optional = optional or set()
    keys = set(value)
    missing = required - keys
    extra = keys - required - optional
    if missing or extra:
        raise ContractError(
            f"{label} fields mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise ContractError(f"{label} must be a non-empty exact str")
    return value


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _number(value: Any, label: str) -> float:
    if type(value) not in {int, float} or not isfinite(float(value)):
        raise ContractError(f"{label} must be a finite exact number")
    return float(value)


def _probability(value: Any, label: str) -> float:
    number = _number(value, label)
    if number < 0.0 or number > 1.0:
        raise ContractError(f"{label} must be in [0,1]")
    return number


def _iso(value: Any, label: str) -> str:
    text = _text(value, label)
    parse_time(text)
    return text


def _dt(value: str) -> datetime:
    parsed = parse_time(value)
    assert parsed is not None
    return parsed


def _canonical_json(value: Any) -> str:
    validate_json_like(value, label="bridge payload", allow_tuple=False)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:  # validate_json_like should preclude this.
        raise ContractError(f"payload is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    return "sha256:" + sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_key(value: Any) -> str:
    return _canonical_json(value)


def _clone_json(value: Any) -> Any:
    validate_json_like(value, label="bridge payload", allow_tuple=False)
    return json.loads(_canonical_json(value))


def _pairs_to_dict(
    rows: Sequence[Mapping[str, Any]],
    *,
    key_name: str,
    value_name: str,
    label: str,
) -> dict[str, tuple[Any, float]]:
    out: dict[str, tuple[Any, float]] = {}
    for index, row in enumerate(rows):
        _strict_fields(row, {key_name, value_name}, f"{label}[{index}]")
        key_value = row[key_name]
        key = _json_key(key_value)
        if key in out:
            raise ContractError(f"{label} contains duplicate key {key_value!r}")
        out[key] = (_clone_json(key_value), _probability(row[value_name], f"{label}[{index}].{value_name}"))
    return out


def _require_mass_one(values: Sequence[float], label: str, *, tolerance: float = 1e-12) -> None:
    total = sum(values)
    if not isclose(total, 1.0, rel_tol=0.0, abs_tol=tolerance):
        raise ContractError(f"{label} probability mass sums to {total}, not 1")


def _normalize(weights: Mapping[str, float], label: str) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0.0 or not isfinite(total):
        raise SemanticLossError(f"{label} has zero/non-finite conditioning mass")
    return {key: value / total for key, value in weights.items()}


def _root_ref_key(ref: Mapping[str, Any]) -> tuple[str, str]:
    _strict_fields(ref, {"occurrence_id", "version"}, "root_ref")
    return _text(ref["occurrence_id"], "root_ref.occurrence_id"), _text(
        ref["version"], "root_ref.version"
    )


def _root_identity(value: Mapping[str, Any], label: str) -> tuple[str, str]:
    """Read identity from either a full root row or an exact root reference."""

    if type(value) is not dict:
        raise ContractError(f"{label} must be an exact dict")
    return _text(value.get("occurrence_id"), f"{label}.occurrence_id"), _text(
        value.get("version"), f"{label}.version"
    )


def _statement_ref_key(ref: Mapping[str, Any]) -> tuple[str, str]:
    _strict_fields(ref, {"logical_id", "version"}, "statement_ref")
    return _text(ref["logical_id"], "statement_ref.logical_id"), _text(
        ref["version"], "statement_ref.version"
    )


def _statement_identity(value: Mapping[str, Any], label: str) -> tuple[str, str]:
    """Read identity from either a full statement row or an exact reference."""

    if type(value) is not dict:
        raise ContractError(f"{label} must be an exact dict")
    return _text(value.get("logical_id"), f"{label}.logical_id"), _text(
        value.get("version"), f"{label}.version"
    )


def _validate_scope(scope: Mapping[str, Any], label: str = "scope") -> None:
    required = {"subject_id"}
    optional = {"encounter_id", "specimen_id", "device_id", "site_id", "body_site"}
    _strict_fields(scope, required, label, optional=optional)
    _text(scope["subject_id"], f"{label}.subject_id")
    for field in optional:
        _optional_text(scope.get(field), f"{label}.{field}")


def _validate_clock_set(clocks: Mapping[str, Any], label: str) -> None:
    required = {"effective_start", "available_at", "recorded_at"}
    optional = {
        "effective_end",
        "collected_at",
        "expires_at",
        "kernel_committed_at",
        "slice_id",
    }
    _strict_fields(clocks, required, label, optional=optional)
    start = _dt(_iso(clocks["effective_start"], f"{label}.effective_start"))
    available = _dt(_iso(clocks["available_at"], f"{label}.available_at"))
    recorded = _dt(_iso(clocks["recorded_at"], f"{label}.recorded_at"))
    if recorded < available:
        raise ContractError(f"{label}.recorded_at precedes available_at")
    for field in ("effective_end", "collected_at", "expires_at", "kernel_committed_at"):
        value = clocks.get(field)
        if value is not None:
            _iso(value, f"{label}.{field}")
    end = clocks.get("effective_end")
    if end is not None and _dt(end) <= start:
        raise ContractError(f"{label}.effective_end must be after effective_start")
    expires = clocks.get("expires_at")
    if expires is not None and _dt(expires) <= start:
        raise ContractError(f"{label}.expires_at must be after effective_start")
    _optional_text(clocks.get("slice_id"), f"{label}.slice_id")


def _validate_measurement(measurement: Mapping[str, Any], label: str) -> None:
    if type(measurement) is not dict:
        raise ContractError(f"{label} must be an exact dict")
    kind = _text(measurement.get("kind"), f"{label}.kind")
    if kind == "exact":
        _strict_fields(measurement, {"kind", "value"}, label)
        validate_json_like(measurement["value"], label=f"{label}.value", allow_tuple=False)
        return
    if kind == "categorical_likelihood":
        _strict_fields(measurement, {"kind", "entries"}, label)
        entries = measurement["entries"]
        if type(entries) is not list or not entries:
            raise ContractError(f"{label}.entries must be a non-empty exact list")
        pairs = _pairs_to_dict(
            entries, key_name="value", value_name="likelihood", label=f"{label}.entries"
        )
        if max(value for _, value in pairs.values()) <= 0.0:
            raise ContractError(f"{label} categorical likelihood is identically zero")
        return
    if kind == "interval":
        _strict_fields(measurement, {"kind", "low", "high", "closure"}, label)
        low = _number(measurement["low"], f"{label}.low")
        high = _number(measurement["high"], f"{label}.high")
        if low > high:
            raise ContractError(f"{label}.low exceeds high")
        if measurement["closure"] not in {"[]", "[)", "(]", "()"}:
            raise ContractError(f"{label}.closure is invalid")
        return
    if kind in {"below_detection", "above_detection"}:
        _strict_fields(measurement, {"kind", "limit"}, label)
        _number(measurement["limit"], f"{label}.limit")
        return
    if kind == "explicit_no_value":
        _strict_fields(measurement, {"kind", "reason"}, label)
        if measurement["reason"] not in {
            "not_asked",
            "not_observed",
            "not_recorded",
            "unable_to_assess",
            "not_applicable",
            "withheld",
            "masked",
        }:
            raise ContractError(f"{label}.reason is invalid")
        return
    raise ContractError(f"{label}.kind={kind!r} is not a closed measurement variant")


def _measurement_likelihood(measurement: Mapping[str, Any], predicted: Any) -> float:
    """Likelihood of a finite predicted value under a declared measurement."""

    kind = measurement["kind"]
    if kind == "exact":
        return 1.0 if _json_key(measurement["value"]) == _json_key(predicted) else 0.0
    if kind == "categorical_likelihood":
        key = _json_key(predicted)
        for entry in measurement["entries"]:
            if _json_key(entry["value"]) == key:
                return float(entry["likelihood"])
        return 0.0
    if kind == "interval":
        if type(predicted) not in {int, float} or not isfinite(float(predicted)):
            return 0.0
        value = float(predicted)
        low = float(measurement["low"])
        high = float(measurement["high"])
        closure = measurement["closure"]
        lower = value >= low if closure[0] == "[" else value > low
        upper = value <= high if closure[1] == "]" else value < high
        return 1.0 if lower and upper else 0.0
    if kind == "below_detection":
        return 1.0 if type(predicted) in {int, float} and float(predicted) < float(measurement["limit"]) else 0.0
    if kind == "above_detection":
        return 1.0 if type(predicted) in {int, float} and float(predicted) > float(measurement["limit"]) else 0.0
    raise SemanticLossError("explicit_no_value cannot be coerced into a model likelihood")


def _validate_bridge(bridge: Mapping[str, Any]) -> None:
    required = {
        "bridge_id",
        "version",
        "registered_at",
        "source_kernel",
        "source_role",
        "target_role",
        "transform",
    }
    optional = {"source_concept", "target_concept", "source_unit", "target_unit"}
    _strict_fields(bridge, required, "bridge", optional=optional)
    for field in required - {"registered_at"}:
        _text(bridge[field], f"bridge.{field}")
    _iso(bridge["registered_at"], "bridge.registered_at")
    if bridge["source_kernel"] != "evidence_authority":
        raise ContractError("bridge.source_kernel must be evidence_authority")
    if bridge["transform"] not in {"identity", "boolean_to_binary"}:
        raise ContractError("bridge.transform is not a closed transform")
    for field in optional:
        _optional_text(bridge.get(field), f"bridge.{field}")
    if bridge["transform"] == "identity" and bridge.get("source_unit") != bridge.get("target_unit"):
        raise SemanticLossError("identity bridge cannot silently change units")
    action_roles = {"performed_intervention", "stopped_intervention"}
    if bridge["target_role"] in action_roles and bridge["source_role"] not in action_roles:
        raise SemanticLossError("an observation/plan bridge cannot manufacture a performed action")


def _validate_temporal_cut(cut: Mapping[str, Any]) -> None:
    required = {
        "target_window",
        "actor_visibility_cut",
        "transaction_revision_cut",
        "evidence_use_policy",
        "evidence_snapshot_id",
        "external_response_snapshot",
        "randomness_policy",
        "principal_authorization_snapshot",
    }
    _strict_fields(cut, required, "temporal_cut")
    window = cut["target_window"]
    _strict_fields(window, {"start", "end"}, "temporal_cut.target_window")
    start = _dt(_iso(window["start"], "temporal_cut.target_window.start"))
    end = _dt(_iso(window["end"], "temporal_cut.target_window.end"))
    if end < start:
        raise ContractError("temporal_cut target window is reversed")
    _iso(cut["actor_visibility_cut"], "temporal_cut.actor_visibility_cut")
    _iso(cut["transaction_revision_cut"], "temporal_cut.transaction_revision_cut")
    _text(cut["evidence_use_policy"], "temporal_cut.evidence_use_policy")
    _text(cut["evidence_snapshot_id"], "temporal_cut.evidence_snapshot_id")
    for field in (
        "external_response_snapshot",
        "randomness_policy",
        "principal_authorization_snapshot",
    ):
        if type(cut[field]) is not dict:
            raise ContractError(f"temporal_cut.{field} must be an exact dict")
        validate_json_like(cut[field], label=f"temporal_cut.{field}", allow_tuple=False)


def _validate_version_vector(versions: Mapping[str, Any]) -> None:
    if type(versions) is not dict or not versions:
        raise ContractError("version_vector must be a non-empty exact dict")
    required = {"bridge", "adapter", "terminology", "knowledge", "model", "policy", "solver"}
    if not required <= set(versions):
        raise ContractError(f"version_vector missing {sorted(required - set(versions))}")
    for key, value in versions.items():
        _text(key, "version_vector key")
        _text(value, f"version_vector.{key}")


def _validate_root(root: Mapping[str, Any], index: int) -> tuple[str, str]:
    label = f"roots[{index}]"
    required = {
        "occurrence_id",
        "version",
        "artifact_id",
        "artifact_version",
        "source_span",
        "raw_payload",
        "raw_digest",
        "dependence_families",
    }
    _strict_fields(root, required, label)
    for field in ("occurrence_id", "version", "artifact_id", "artifact_version"):
        _text(root[field], f"{label}.{field}")
    span = root["source_span"]
    if span is not None:
        _strict_fields(span, {"start", "end"}, f"{label}.source_span")
        if type(span["start"]) is not int or type(span["end"]) is not int:
            raise ContractError(f"{label}.source_span offsets must be exact int")
        if span["start"] < 0 or span["end"] < span["start"]:
            raise ContractError(f"{label}.source_span is invalid")
    validate_json_like(root["raw_payload"], label=f"{label}.raw_payload", allow_tuple=False)
    if root["raw_digest"] != _digest(root["raw_payload"]):
        raise SemanticLossError(f"{label}.raw_digest does not match raw_payload")
    families = root["dependence_families"]
    if type(families) is not list or any(type(item) is not str or not item for item in families):
        raise ContractError(f"{label}.dependence_families must be exact non-empty strings")
    if len(families) != len(set(families)):
        raise ContractError(f"{label}.dependence_families contains duplicates")
    return root["occurrence_id"], root["version"]


def _validate_record(
    record: Mapping[str, Any],
    index: int,
    root_keys: set[tuple[str, str]],
    bundle_scope: Mapping[str, Any],
) -> tuple[str, str]:
    label = f"evidence_history[{index}]"
    required = {
        "statement_id",
        "logical_id",
        "version",
        "concept",
        "semantic_role",
        "information_state",
        "scope",
        "clocks",
        "measurement",
        "unit",
        "method",
        "mapping_versions",
        "root_refs",
        "proof",
    }
    optional = {"supersedes"}
    _strict_fields(record, required, label, optional=optional)
    for field in ("statement_id", "logical_id", "version", "concept", "semantic_role", "information_state"):
        _text(record[field], f"{label}.{field}")
    if record["information_state"] not in {
        "present",
        "absent",
        "not_asked",
        "not_observed",
        "not_recorded",
        "unable_to_assess",
        "insufficient",
        "conflicting",
        "not_applicable",
        "out_of_model",
        "masked",
        "censored_low",
        "censored_high",
    }:
        raise ContractError(f"{label}.information_state is invalid")
    _validate_scope(record["scope"], f"{label}.scope")
    if record["scope"]["subject_id"] != bundle_scope["subject_id"]:
        raise SemanticLossError(f"{label} crosses subject identity")
    _validate_clock_set(record["clocks"], f"{label}.clocks")
    _validate_measurement(record["measurement"], f"{label}.measurement")
    _optional_text(record["unit"], f"{label}.unit")
    _optional_text(record["method"], f"{label}.method")
    mappings = record["mapping_versions"]
    if type(mappings) is not list or not mappings or any(type(item) is not str or not item for item in mappings):
        raise ContractError(f"{label}.mapping_versions must be a non-empty exact list")
    if len(mappings) != len(set(mappings)):
        raise ContractError(f"{label}.mapping_versions contains duplicates")
    refs = record["root_refs"]
    if type(refs) is not list or not refs:
        raise ContractError(f"{label}.root_refs must be a non-empty exact list")
    parsed_refs = [_root_ref_key(ref) for ref in refs]
    if len(parsed_refs) != len(set(parsed_refs)):
        raise ContractError(f"{label}.root_refs contains duplicates")
    missing = set(parsed_refs) - root_keys
    if missing:
        raise SemanticLossError(f"{label} references missing roots {sorted(missing)}")
    validate_json_like(record["proof"], label=f"{label}.proof", allow_tuple=False)
    if "supersedes" in record and record["supersedes"] is not None:
        _statement_ref_key(record["supersedes"])
    return record["logical_id"], record["version"]


def _validate_delta(delta: Mapping[str, Any], index: int) -> None:
    label = f"deltas[{index}]"
    kind = _text(delta.get("kind"), f"{label}.kind")
    common = {"kind", "delta_id", "registered_at", "reason"}
    if kind == "retract":
        _strict_fields(delta, common | {"target_root"}, label)
        _root_ref_key(delta["target_root"])
    elif kind == "correct":
        _strict_fields(delta, common | {"old_statement", "new_root", "new_record"}, label)
        _statement_ref_key(delta["old_statement"])
        # The new root/record receive full validation after being merged into a bundle.
        if type(delta["new_root"]) is not dict or type(delta["new_record"]) is not dict:
            raise ContractError(f"{label} correction must carry exact new_root/new_record")
        _root_identity(delta["new_root"], f"{label}.new_root")
        _statement_identity(delta["new_record"], f"{label}.new_record")
    else:
        raise ContractError(f"{label}.kind must be retract or correct")
    _text(delta["delta_id"], f"{label}.delta_id")
    _iso(delta["registered_at"], f"{label}.registered_at")
    _text(delta["reason"], f"{label}.reason")


def _validate_query(query: Mapping[str, Any], index: int, subject_id: str) -> None:
    label = f"queries[{index}]"
    kind = _text(query.get("kind"), f"{label}.kind")
    if kind not in QUERY_KINDS:
        raise ContractError(f"{label}.kind is not a closed query variant")
    if kind in {"filter", "smooth"}:
        required = {"query_id", "kind", "target", "at"}
        if kind == "smooth":
            required.add("later_evidence_cut")
        _strict_fields(query, required, label)
        for field in ("query_id", "target"):
            _text(query[field], f"{label}.{field}")
        _iso(query["at"], f"{label}.at")
        if kind == "smooth":
            later = _dt(_iso(query["later_evidence_cut"], f"{label}.later_evidence_cut"))
            if later < _dt(query["at"]):
                raise SemanticLossError("smooth later_evidence_cut precedes target time")
        return
    if kind == "condition":
        _strict_fields(query, {"query_id", "kind", "estimand", "observation_ids"}, label)
        _text(query["query_id"], f"{label}.query_id")
        _text(query["estimand"], f"{label}.estimand")
        _validate_string_list(query["observation_ids"], f"{label}.observation_ids", nonempty=True)
        return
    if kind == "intervene":
        required = {
            "query_id",
            "kind",
            "estimand",
            "do_set",
            "conditioning_observation_ids",
            "population",
            "identification_contract",
            "mechanism_replacement",
        }
        _strict_fields(query, required, label)
        _text(query["query_id"], f"{label}.query_id")
        _text(query["estimand"], f"{label}.estimand")
        _text(query["population"], f"{label}.population")
        _text(query["identification_contract"], f"{label}.identification_contract")
        if query["mechanism_replacement"] is not True:
            raise SemanticLossError("intervene requires mechanism_replacement=true")
        _validate_do_set(query["do_set"], f"{label}.do_set")
        _validate_string_list(
            query["conditioning_observation_ids"],
            f"{label}.conditioning_observation_ids",
            nonempty=False,
        )
        return
    required = {
        "query_id",
        "kind",
        "unit",
        "estimand",
        "factual_observation_ids",
        "do_set",
        "shared_world_policy",
        "stages",
    }
    _strict_fields(query, required, label)
    _text(query["query_id"], f"{label}.query_id")
    _text(query["unit"], f"{label}.unit")
    if query["unit"] != subject_id:
        raise SemanticLossError("AAP unit does not match bundle subject")
    _text(query["estimand"], f"{label}.estimand")
    _validate_string_list(query["factual_observation_ids"], f"{label}.factual_observation_ids", nonempty=True)
    _validate_do_set(query["do_set"], f"{label}.do_set")
    if query["shared_world_policy"] != "share_abduced_exogenous":
        raise SemanticLossError("AAP requires share_abduced_exogenous")
    if query["stages"] != ["abduction", "action", "prediction"]:
        raise SemanticLossError("AAP stages must be abduction -> action -> prediction")


def _validate_string_list(value: Any, label: str, *, nonempty: bool) -> None:
    if type(value) is not list or (nonempty and not value):
        raise ContractError(f"{label} must be an exact {'non-empty ' if nonempty else ''}list")
    if any(type(item) is not str or not item for item in value):
        raise ContractError(f"{label} must contain non-empty exact strings")
    if len(value) != len(set(value)):
        raise ContractError(f"{label} contains duplicates")


def _validate_do_set(value: Any, label: str) -> None:
    if type(value) is not dict or not value:
        raise ContractError(f"{label} must be a non-empty exact dict")
    for variable, assigned in value.items():
        _text(variable, f"{label} variable")
        validate_json_like(assigned, label=f"{label}.{variable}", allow_tuple=False)


def _validate_dbn_model(model: Mapping[str, Any]) -> None:
    required = {
        "model_id",
        "version",
        "kernel",
        "state_variable",
        "states",
        "slices",
        "prior",
        "transitions",
        "emissions",
        "uncertainty_semantics",
        "coverage_contract",
    }
    _strict_fields(model, required, "models.finite_dbn")
    for field in ("model_id", "version", "state_variable", "uncertainty_semantics"):
        _text(model[field], f"models.finite_dbn.{field}")
    if model["kernel"] != "finite_dbn":
        raise ContractError("finite_dbn model kernel tag mismatch")
    states = model["states"]
    if type(states) is not list or len(states) < 2:
        raise ContractError("finite_dbn.states must contain at least two states")
    state_keys = [_json_key(value) for value in states]
    if len(state_keys) != len(set(state_keys)):
        raise ContractError("finite_dbn.states contains duplicates")
    slices = model["slices"]
    if type(slices) is not list or not slices:
        raise ContractError("finite_dbn.slices must be a non-empty exact list")
    parsed_slices = [_dt(_iso(value, f"finite_dbn.slices[{i}]")) for i, value in enumerate(slices)]
    if parsed_slices != sorted(parsed_slices) or len(parsed_slices) != len(set(parsed_slices)):
        raise ContractError("finite_dbn.slices must be strictly increasing")
    prior = _pairs_to_dict(
        model["prior"], key_name="state", value_name="probability", label="finite_dbn.prior"
    )
    if set(prior) != set(state_keys):
        raise ContractError("finite_dbn.prior must cover every state exactly once")
    _require_mass_one([p for _, p in prior.values()], "finite_dbn.prior")
    transitions = model["transitions"]
    if type(transitions) is not list or not transitions:
        raise ContractError("finite_dbn.transitions must be a non-empty exact list")
    grouped: dict[tuple[str, str], dict[str, float]] = {}
    slice_pairs = {(slices[i], slices[i + 1]) for i in range(len(slices) - 1)}
    for index, row in enumerate(transitions):
        label = f"finite_dbn.transitions[{index}]"
        _strict_fields(row, {"from_slice", "to_slice", "from_state", "to_state", "probability"}, label)
        pair = (row["from_slice"], row["to_slice"])
        if pair not in slice_pairs:
            raise ContractError(f"{label} references a non-adjacent slice pair")
        from_key, to_key = _json_key(row["from_state"]), _json_key(row["to_state"])
        if from_key not in state_keys or to_key not in state_keys:
            raise ContractError(f"{label} references an unknown state")
        bucket = grouped.setdefault((pair[0] + "\0" + pair[1], from_key), {})
        if to_key in bucket:
            raise ContractError(f"{label} duplicates a transition cell")
        bucket[to_key] = _probability(row["probability"], f"{label}.probability")
    expected_groups = max(0, len(slices) - 1) * len(states)
    if len(grouped) != expected_groups:
        raise ContractError("finite_dbn.transitions does not cover every slice/state row")
    for group, values in grouped.items():
        if set(values) != set(state_keys):
            raise ContractError(f"finite_dbn transition row {group} is incomplete")
        _require_mass_one(list(values.values()), f"finite_dbn transition row {group}")
    emissions = model["emissions"]
    if type(emissions) is not list or not emissions:
        raise ContractError("finite_dbn.emissions must be a non-empty exact list")
    emission_groups: dict[tuple[str, str], list[float]] = {}
    seen_cells: set[tuple[str, str, str]] = set()
    for index, row in enumerate(emissions):
        label = f"finite_dbn.emissions[{index}]"
        _strict_fields(row, {"concept", "state", "observed_value", "probability"}, label)
        concept = _text(row["concept"], f"{label}.concept")
        state_key = _json_key(row["state"])
        if state_key not in state_keys:
            raise ContractError(f"{label} references unknown state")
        observed_key = _json_key(row["observed_value"])
        cell = (concept, state_key, observed_key)
        if cell in seen_cells:
            raise ContractError(f"{label} duplicates an emission cell")
        seen_cells.add(cell)
        emission_groups.setdefault((concept, state_key), []).append(
            _probability(row["probability"], f"{label}.probability")
        )
    concepts = {concept for concept, _ in emission_groups}
    for concept in concepts:
        for state_key in state_keys:
            values = emission_groups.get((concept, state_key))
            if not values:
                raise ContractError(f"emission concept {concept!r} is not defined for every state")
            _require_mass_one(values, f"emission {concept}/{state_key}")
    if type(model["coverage_contract"]) is not dict:
        raise ContractError("finite_dbn.coverage_contract must be an exact dict")


def _validate_scm_model(model: Mapping[str, Any]) -> None:
    required = {
        "model_id",
        "version",
        "kernel",
        "endogenous_order",
        "domains",
        "exogenous_worlds",
        "equations",
        "observation_bindings",
        "uncertainty_semantics",
        "coverage_contract",
        "identification_contracts",
    }
    _strict_fields(model, required, "models.finite_scm")
    for field in ("model_id", "version", "uncertainty_semantics"):
        _text(model[field], f"models.finite_scm.{field}")
    if model["kernel"] != "finite_scm":
        raise ContractError("finite_scm model kernel tag mismatch")
    order = model["endogenous_order"]
    _validate_string_list(order, "finite_scm.endogenous_order", nonempty=True)
    domains = model["domains"]
    if type(domains) is not dict or set(domains) != set(order):
        raise ContractError("finite_scm.domains must exactly cover endogenous_order")
    domain_keys: dict[str, set[str]] = {}
    for variable in order:
        values = domains[variable]
        if type(values) is not list or not values:
            raise ContractError(f"finite_scm.domains.{variable} must be non-empty")
        keys = [_json_key(value) for value in values]
        if len(keys) != len(set(keys)):
            raise ContractError(f"finite_scm.domains.{variable} contains duplicates")
        domain_keys[variable] = set(keys)
    worlds = model["exogenous_worlds"]
    if type(worlds) is not list or not worlds:
        raise ContractError("finite_scm.exogenous_worlds must be non-empty")
    world_ids: set[str] = set()
    probabilities: list[float] = []
    for index, world in enumerate(worlds):
        label = f"finite_scm.exogenous_worlds[{index}]"
        _strict_fields(world, {"world_id", "probability", "values"}, label)
        world_id = _text(world["world_id"], f"{label}.world_id")
        if world_id in world_ids:
            raise ContractError("duplicate SCM world_id")
        world_ids.add(world_id)
        probabilities.append(_probability(world["probability"], f"{label}.probability"))
        if type(world["values"]) is not dict:
            raise ContractError(f"{label}.values must be exact dict")
        validate_json_like(world["values"], label=f"{label}.values", allow_tuple=False)
    _require_mass_one(probabilities, "finite_scm.exogenous_worlds")
    equations = model["equations"]
    if type(equations) is not list or len(equations) != len(order):
        raise ContractError("finite_scm.equations must define every endogenous variable once")
    seen_variables: set[str] = set()
    available_names: set[str] = set()
    exogenous_names = set().union(*(set(world["values"]) for world in worlds))
    for index, equation in enumerate(equations):
        label = f"finite_scm.equations[{index}]"
        _strict_fields(equation, {"variable", "cases"}, label)
        variable = _text(equation["variable"], f"{label}.variable")
        if variable != order[index] or variable in seen_variables:
            raise ContractError("SCM equations must follow endogenous_order exactly")
        seen_variables.add(variable)
        cases = equation["cases"]
        if type(cases) is not list or not cases:
            raise ContractError(f"{label}.cases must be non-empty")
        for case_index, case in enumerate(cases):
            case_label = f"{label}.cases[{case_index}]"
            _strict_fields(case, {"when", "value"}, case_label)
            if type(case["when"]) is not dict:
                raise ContractError(f"{case_label}.when must be exact dict")
            unknown_names = set(case["when"]) - available_names - exogenous_names
            if unknown_names:
                raise ContractError(f"{case_label} uses future/unknown names {sorted(unknown_names)}")
            if _json_key(case["value"]) not in domain_keys[variable]:
                raise ContractError(f"{case_label}.value is outside variable domain")
        available_names.add(variable)
    bindings = model["observation_bindings"]
    if type(bindings) is not list or not bindings:
        raise ContractError("finite_scm.observation_bindings must be non-empty")
    seen_concepts: set[str] = set()
    for index, binding in enumerate(bindings):
        label = f"finite_scm.observation_bindings[{index}]"
        _strict_fields(binding, {"concept", "variable"}, label)
        concept = _text(binding["concept"], f"{label}.concept")
        variable = _text(binding["variable"], f"{label}.variable")
        if concept in seen_concepts or variable not in domains:
            raise ContractError(f"{label} duplicate concept or unknown variable")
        seen_concepts.add(concept)
    contracts = model["identification_contracts"]
    _validate_string_list(contracts, "finite_scm.identification_contracts", nonempty=True)
    if type(model["coverage_contract"]) is not dict:
        raise ContractError("finite_scm.coverage_contract must be exact dict")


def _validate_bundle(bundle: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "bridge",
        "scope",
        "temporal_cut",
        "version_vector",
        "roots",
        "evidence_history",
        "deltas",
        "models",
        "queries",
        "uncertainty_contract",
    }
    _strict_fields(bundle, required, "canonical bundle")
    if bundle["schema_version"] != CANONICAL_SCHEMA:
        raise ContractError(f"unsupported canonical schema {bundle['schema_version']!r}")
    _validate_bridge(bundle["bridge"])
    _validate_scope(bundle["scope"])
    _validate_temporal_cut(bundle["temporal_cut"])
    _validate_version_vector(bundle["version_vector"])
    if bundle["version_vector"]["bridge"] != bundle["bridge"]["version"]:
        raise SemanticLossError("bridge version disagrees with version_vector")
    if _dt(bundle["bridge"]["registered_at"]) > _dt(bundle["temporal_cut"]["transaction_revision_cut"]):
        raise SemanticLossError("bridge version was not registered at the frozen cut")

    roots = bundle["roots"]
    if type(roots) is not list or not roots:
        raise ContractError("roots must be a non-empty exact list")
    root_keys = [_validate_root(root, index) for index, root in enumerate(roots)]
    if len(root_keys) != len(set(root_keys)):
        raise ContractError("duplicate root occurrence/version")

    history = bundle["evidence_history"]
    if type(history) is not list or not history:
        raise ContractError("evidence_history must be a non-empty exact list")
    record_keys = [
        _validate_record(record, index, set(root_keys), bundle["scope"])
        for index, record in enumerate(history)
    ]
    if len(record_keys) != len(set(record_keys)):
        raise ContractError("duplicate logical_id/version")
    statement_ids = [record["statement_id"] for record in history]
    if len(statement_ids) != len(set(statement_ids)):
        raise ContractError("duplicate statement_id")

    deltas = bundle["deltas"]
    if type(deltas) is not list:
        raise ContractError("deltas must be an exact list")
    for index, delta in enumerate(deltas):
        _validate_delta(delta, index)
    delta_ids = [delta["delta_id"] for delta in deltas]
    if len(delta_ids) != len(set(delta_ids)):
        raise ContractError("duplicate delta_id")
    # A canonical stored correction is expanded into roots/history already.
    for delta in deltas:
        if delta["kind"] == "correct":
            new_root_key = _root_identity(delta["new_root"], "delta.new_root")
            new_record_key = _statement_identity(delta["new_record"], "delta.new_record")
            if new_root_key not in set(root_keys) or new_record_key not in set(record_keys):
                raise SemanticLossError("stored correction new root/record is absent from authority history")
            stored_root = next(root for root in roots if _root_identity(root, "root") == new_root_key)
            stored_record = next(
                record for record in history if _statement_identity(record, "record") == new_record_key
            )
            if stored_root != delta["new_root"] or stored_record != delta["new_record"]:
                raise SemanticLossError("stored correction payload disagrees with authority history")

    models = bundle["models"]
    _strict_fields(models, {"finite_dbn", "finite_scm"}, "models")
    _validate_dbn_model(models["finite_dbn"])
    _validate_scm_model(models["finite_scm"])
    if bundle["version_vector"]["model"] not in {
        models["finite_dbn"]["version"],
        models["finite_scm"]["version"],
        f"{models['finite_dbn']['version']}+{models['finite_scm']['version']}",
    }:
        raise SemanticLossError("version_vector.model does not name the registered model versions")

    queries = bundle["queries"]
    if type(queries) is not list or not queries:
        raise ContractError("queries must be a non-empty exact list")
    for index, query in enumerate(queries):
        _validate_query(query, index, bundle["scope"]["subject_id"])
    query_ids = [query["query_id"] for query in queries]
    if len(query_ids) != len(set(query_ids)):
        raise ContractError("duplicate query_id")

    contract = bundle["uncertainty_contract"]
    _strict_fields(
        contract,
        {"belief_semantics", "unknown_policy", "conflict_policy", "dependence_policy", "version"},
        "uncertainty_contract",
    )
    if contract["belief_semantics"] != "finite_probability_mass":
        raise ContractError("implementation A only supports finite_probability_mass")
    if contract["unknown_policy"] != "preserve_not_zero":
        raise SemanticLossError("unknown must not be coerced to zero")
    if contract["conflict_policy"] != "reject_before_model":
        raise SemanticLossError("conflict must not be silently selected")
    if contract["dependence_policy"] != "model_declared_not_root_count":
        raise SemanticLossError("root count must not be treated as independent mass")
    _text(contract["version"], "uncertainty_contract.version")

    # Query references must resolve against statement ids.  This is checked at
    # bundle level so a tag cannot be preserved while its factual set is lost.
    statement_set = set(statement_ids)
    for query in queries:
        for field in ("observation_ids", "conditioning_observation_ids", "factual_observation_ids"):
            missing = set(query.get(field, [])) - statement_set
            if missing:
                raise SemanticLossError(f"query {query['query_id']} references missing observations {sorted(missing)}")


def _normalized_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize only semantically unordered registry lists."""

    candidate = _clone_json(bundle)
    _validate_bundle(candidate)
    candidate["roots"] = sorted(
        candidate["roots"], key=lambda root: (root["occurrence_id"], root["version"])
    )
    candidate["evidence_history"] = sorted(
        candidate["evidence_history"], key=lambda record: (record["logical_id"], record["version"])
    )
    candidate["deltas"] = sorted(
        candidate["deltas"], key=lambda delta: (delta["registered_at"], delta["delta_id"])
    )
    candidate["queries"] = sorted(candidate["queries"], key=lambda query: query["query_id"])
    for root in candidate["roots"]:
        root["dependence_families"] = sorted(root["dependence_families"])
    for record in candidate["evidence_history"]:
        record["mapping_versions"] = sorted(record["mapping_versions"])
        record["root_refs"] = sorted(
            record["root_refs"], key=lambda ref: (ref["occurrence_id"], ref["version"])
        )
    _validate_bundle(candidate)
    return candidate


class CodecA:
    """Deterministic, strict JSON codec for the canonical bridge contract."""

    @staticmethod
    def encode(bundle: Mapping[str, Any]) -> bytes:
        normalized = _normalized_bundle(bundle)
        return _canonical_json(normalized).encode("utf-8")

    @staticmethod
    def decode(payload: bytes | str) -> dict[str, Any]:
        if type(payload) is bytes:
            try:
                text = payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ContractError("bridge payload is not strict UTF-8") from exc
        elif type(payload) is str:
            text = payload
        else:
            raise ContractError("CodecA.decode accepts exact bytes or str")

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for key, value in pairs:
                if key in out:
                    raise ContractError(f"duplicate JSON key {key!r}")
                out[key] = value
            return out

        try:
            decoded = json.loads(
                text,
                object_pairs_hook=reject_duplicates,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ContractError(f"non-finite JSON constant {value}")
                ),
            )
        except ContractError:
            raise
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ContractError(f"invalid bridge JSON: {exc}") from exc
        if type(decoded) is not dict:
            raise ContractError("bridge payload root must be an exact object")
        return _normalized_bundle(decoded)

    @classmethod
    def round_trip(cls, bundle: Mapping[str, Any]) -> dict[str, Any]:
        return cls.decode(cls.encode(bundle))

    @staticmethod
    def semantic_digest(bundle: Mapping[str, Any]) -> str:
        return _digest(_normalized_bundle(bundle))

    @classmethod
    def assert_semantically_equal(cls, left: Mapping[str, Any], right: Mapping[str, Any]) -> None:
        left_normal = _normalized_bundle(left)
        right_normal = _normalized_bundle(right)
        if _canonical_json(left_normal) != _canonical_json(right_normal):
            raise SemanticLossError(
                f"bridge bundles differ: {cls.semantic_digest(left_normal)} != {cls.semantic_digest(right_normal)}"
            )


def _delta_at_cut(delta: Mapping[str, Any], cut: Mapping[str, Any]) -> bool:
    return _dt(delta["registered_at"]) <= _dt(cut["transaction_revision_cut"])


def _record_at_cut(record: Mapping[str, Any], cut: Mapping[str, Any]) -> bool:
    clocks = record["clocks"]
    tx = _dt(cut["transaction_revision_cut"])
    visibility = _dt(cut["actor_visibility_cut"])
    if _dt(clocks["recorded_at"]) > tx or _dt(clocks["available_at"]) > visibility:
        return False
    expires = clocks.get("expires_at")
    valid_at = _dt(cut["target_window"]["end"])
    if _dt(clocks["effective_start"]) > valid_at:
        # Future-effective evidence can still be used by smoothing, but not as
        # a generally active current record.  Query-specific selection below
        # re-admits it only under an explicit later-evidence policy.
        return True
    if expires is not None and _dt(expires) <= valid_at:
        return False
    return True


def _active_statement_ids(
    roots: Sequence[Mapping[str, Any]],
    history: Sequence[Mapping[str, Any]],
    deltas: Sequence[Mapping[str, Any]],
    cut: Mapping[str, Any],
) -> list[str]:
    root_keys = {(root["occurrence_id"], root["version"]) for root in roots}
    eligible_deltas = [delta for delta in deltas if _delta_at_cut(delta, cut)]
    retracted = {
        _root_ref_key(delta["target_root"])
        for delta in eligible_deltas
        if delta["kind"] == "retract"
    }
    unknown_retractions = retracted - root_keys
    if unknown_retractions:
        raise SemanticLossError(f"retraction targets unknown roots {sorted(unknown_retractions)}")

    records = [record for record in history if _record_at_cut(record, cut)]
    by_ref = {(record["logical_id"], record["version"]): record for record in records}
    removed: set[tuple[str, str]] = set()
    successors: dict[tuple[str, str], tuple[str, str]] = {}

    # Explicit record-level supersession and correction deltas are one typed
    # version graph.  Forks are conflicts, never last-write-wins.
    for record in records:
        if record.get("supersedes") is not None:
            old = _statement_ref_key(record["supersedes"])
            new = (record["logical_id"], record["version"])
            previous = successors.get(old)
            if previous is not None and previous != new:
                raise SemanticLossError(f"conflicting version successors for {old}")
            successors[old] = new
    for delta in eligible_deltas:
        if delta["kind"] != "correct":
            continue
        old = _statement_ref_key(delta["old_statement"])
        new = _statement_identity(delta["new_record"], "delta.new_record")
        previous = successors.get(old)
        if previous is not None and previous != new:
            raise SemanticLossError(f"conflicting correction successors for {old}")
        successors[old] = new
    for old, new in successors.items():
        if old not in by_ref or new not in by_ref:
            raise SemanticLossError(f"version edge {old}->{new} is unavailable at cut")
        removed.add(old)

    active: list[str] = []
    logical_seen: dict[str, tuple[str, str]] = {}
    for ref, record in by_ref.items():
        if ref in removed:
            continue
        refs = {_root_ref_key(root_ref) for root_ref in record["root_refs"]}
        if refs & retracted:
            continue
        prior = logical_seen.get(record["logical_id"])
        if prior is not None and prior != ref:
            raise SemanticLossError(
                f"unresolved active versions for logical_id={record['logical_id']!r}"
            )
        logical_seen[record["logical_id"]] = ref
        active.append(record["statement_id"])
    return sorted(active)


def _lineage_rows(bundle: Mapping[str, Any], active_ids: Sequence[str]) -> list[dict[str, Any]]:
    active = set(active_ids)
    rows: list[dict[str, Any]] = []
    for record in bundle["evidence_history"]:
        address = f"obs:{record['logical_id']}@{record['version']}"
        rows.append(
            {
                "native_address": address,
                "statement_id": record["statement_id"],
                "statement_ref": {"logical_id": record["logical_id"], "version": record["version"]},
                "root_refs": _clone_json(record["root_refs"]),
                "clock_witness": _clone_json(record["clocks"]),
                "mapping_versions": list(record["mapping_versions"]),
                "active_at_compile_cut": record["statement_id"] in active,
            }
        )
    return sorted(rows, key=lambda row: row["native_address"])


def _transform_measurement_for_bridge(
    measurement: Mapping[str, Any], transform: str
) -> dict[str, Any]:
    transformed = _clone_json(measurement)
    if transform == "identity":
        return transformed
    if transform != "boolean_to_binary":  # defended by bridge validation too.
        raise ContractError(f"unknown bridge transform {transform!r}")
    if transformed["kind"] == "exact":
        value = transformed["value"]
        if type(value) is not bool:
            raise SemanticLossError("boolean_to_binary requires an exact boolean value")
        transformed["value"] = 1 if value else 0
        return transformed
    if transformed["kind"] == "categorical_likelihood":
        for entry in transformed["entries"]:
            if type(entry["value"]) is not bool:
                raise SemanticLossError(
                    "boolean_to_binary categorical likelihood has a non-boolean support value"
                )
            entry["value"] = 1 if entry["value"] else 0
        # True/False cannot collide after this bijection, but retain the check
        # rather than relying on the Python bool/int equality relation.
        keys = [_json_key(entry["value"]) for entry in transformed["entries"]]
        if len(keys) != len(set(keys)):
            raise SemanticLossError("boolean_to_binary collapsed distinct uncertainty support")
        return transformed
    raise SemanticLossError(
        f"boolean_to_binary cannot preserve measurement variant {transformed['kind']!r}"
    )


def _model_input_rows(bundle: Mapping[str, Any], active_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Materialize active evidence through the declared closed bridge."""

    active = set(active_ids)
    bridge = bundle["bridge"]
    source_concept = bridge.get("source_concept")
    target_concept = bridge.get("target_concept")
    rows: list[dict[str, Any]] = []
    for record in bundle["evidence_history"]:
        if record["statement_id"] not in active:
            continue
        if source_concept is not None and record["concept"] != source_concept:
            # A single EvidenceModelBridge maps one declared source channel.  A
            # record from another channel remains in authority history but does
            # not silently bypass the bridge into this model run.
            continue
        if record["semantic_role"] != bridge["source_role"]:
            raise SemanticLossError(
                f"record {record['statement_id']} role does not match bridge source_role"
            )
        if bridge["transform"] == "boolean_to_binary":
            if record["unit"] is not None:
                raise SemanticLossError("boolean_to_binary input must be unitless")
            output_unit = None
        elif bridge.get("source_unit") is not None:
            if record["unit"] != bridge["source_unit"]:
                raise SemanticLossError(
                    f"record {record['statement_id']} unit does not match bridge source_unit"
                )
            output_unit = bridge.get("target_unit")
        else:
            # A wildcard identity bridge preserves, rather than deletes, each
            # record's unit.  It is useful only for holdout bundles whose model
            # channels already use the authority concepts.
            output_unit = record["unit"]
        rows.append(
            {
                "native_address": f"obs:{record['logical_id']}@{record['version']}",
                "statement_id": record["statement_id"],
                "source_statement_ref": {
                    "logical_id": record["logical_id"],
                    "version": record["version"],
                },
                "source_concept": record["concept"],
                "concept": target_concept if target_concept is not None else record["concept"],
                "semantic_role": bridge["target_role"],
                "information_state": record["information_state"],
                "scope": _clone_json(record["scope"]),
                "clocks": _clone_json(record["clocks"]),
                "measurement": _transform_measurement_for_bridge(
                    record["measurement"], bridge["transform"]
                ),
                "unit": output_unit,
                "method": record["method"],
                "mapping_versions": [
                    *record["mapping_versions"],
                    f"bridge:{bridge['bridge_id']}@{bridge['version']}",
                ],
                "root_refs": _clone_json(record["root_refs"]),
            }
        )
    return sorted(rows, key=lambda row: row["native_address"])


def compile_bundle(canonical: Mapping[str, Any], target_kernel: str) -> dict[str, Any]:
    """Compile canonical evidence/model data into executable finite native IR.

    The compiler performs no disease-specific mapping.  Every model-facing
    observation remains an explicit row with a root/clock/version address.
    """

    if type(target_kernel) is not str or target_kernel not in TARGET_KERNELS:
        raise ContractError(f"target_kernel must be one of {sorted(TARGET_KERNELS)}")
    bundle = _normalized_bundle(canonical)
    active_ids = _active_statement_ids(
        bundle["roots"], bundle["evidence_history"], bundle["deltas"], bundle["temporal_cut"]
    )
    native = {
        "ir_schema": NATIVE_SCHEMA,
        "compiler": COMPILER_ID,
        "target_kernel": target_kernel,
        "bridge_contract": _clone_json(bundle["bridge"]),
        "scope_binding": _clone_json(bundle["scope"]),
        "frozen_cut": _clone_json(bundle["temporal_cut"]),
        "version_vector": _clone_json(bundle["version_vector"]),
        "root_table": _clone_json(bundle["roots"]),
        "evidence_table": _clone_json(bundle["evidence_history"]),
        "delta_log": _clone_json(bundle["deltas"]),
        "active_statement_ids": active_ids,
        "model_input_table": _model_input_rows(bundle, active_ids),
        "native_model": _clone_json(bundle["models"][target_kernel]),
        "other_model_registry_entry": _clone_json(
            bundle["models"]["finite_scm" if target_kernel == "finite_dbn" else "finite_dbn"]
        ),
        "query_registry": _clone_json(bundle["queries"]),
        "uncertainty_contract": _clone_json(bundle["uncertainty_contract"]),
        "lineage_map": _lineage_rows(bundle, active_ids),
        "semantic_digest": _digest(bundle),
    }
    _validate_native(native)
    return native


def _recover_unchecked(native: Mapping[str, Any]) -> dict[str, Any]:
    other_key = "finite_scm" if native["target_kernel"] == "finite_dbn" else "finite_dbn"
    models = {
        native["target_kernel"]: _clone_json(native["native_model"]),
        other_key: _clone_json(native["other_model_registry_entry"]),
    }
    return {
        "schema_version": CANONICAL_SCHEMA,
        "bridge": _clone_json(native["bridge_contract"]),
        "scope": _clone_json(native["scope_binding"]),
        "temporal_cut": _clone_json(native["frozen_cut"]),
        "version_vector": _clone_json(native["version_vector"]),
        "roots": _clone_json(native["root_table"]),
        "evidence_history": _clone_json(native["evidence_table"]),
        "deltas": _clone_json(native["delta_log"]),
        "models": models,
        "queries": _clone_json(native["query_registry"]),
        "uncertainty_contract": _clone_json(native["uncertainty_contract"]),
    }


def _validate_native(native: Mapping[str, Any]) -> None:
    required = {
        "ir_schema",
        "compiler",
        "target_kernel",
        "bridge_contract",
        "scope_binding",
        "frozen_cut",
        "version_vector",
        "root_table",
        "evidence_table",
        "delta_log",
        "active_statement_ids",
        "model_input_table",
        "native_model",
        "other_model_registry_entry",
        "query_registry",
        "uncertainty_contract",
        "lineage_map",
        "semantic_digest",
    }
    _strict_fields(native, required, "native IR")
    if native["ir_schema"] != NATIVE_SCHEMA or native["compiler"] != COMPILER_ID:
        raise ContractError("native IR schema/compiler mismatch")
    if native["target_kernel"] not in TARGET_KERNELS:
        raise ContractError("native target_kernel is invalid")
    recovered = _normalized_bundle(_recover_unchecked(native))
    if recovered["models"][native["target_kernel"]] != native["native_model"]:
        raise SemanticLossError("native model target tag mismatch")
    expected_active = _active_statement_ids(
        recovered["roots"],
        recovered["evidence_history"],
        recovered["deltas"],
        recovered["temporal_cut"],
    )
    if native["active_statement_ids"] != expected_active:
        raise SemanticLossError("native active observation index disagrees with authority history")
    expected_inputs = _model_input_rows(recovered, expected_active)
    if native["model_input_table"] != expected_inputs:
        raise SemanticLossError("native model input table disagrees with the closed bridge transform")
    expected_lineage = _lineage_rows(recovered, expected_active)
    if native["lineage_map"] != expected_lineage:
        raise SemanticLossError("native lineage map lost root/clock/version identity")
    if native["semantic_digest"] != _digest(recovered):
        raise SemanticLossError("native semantic digest does not match recoverable IR tables")


def recover_bundle(native: Mapping[str, Any]) -> dict[str, Any]:
    """Recover the canonical bundle from semantic IR tables and lineage."""

    if type(native) is not dict:
        raise ContractError("recover_bundle requires an exact native dict")
    validate_json_like(native, label="native IR", allow_tuple=False)
    _validate_native(native)
    return _normalized_bundle(_recover_unchecked(native))


def _query_from(native: Mapping[str, Any], query: str | Mapping[str, Any]) -> dict[str, Any]:
    if type(query) is str:
        matches = [item for item in native["query_registry"] if item["query_id"] == query]
        if len(matches) != 1:
            raise ContractError(f"unknown/ambiguous query_id {query!r}")
        return _clone_json(matches[0])
    if type(query) is dict:
        candidate = _clone_json(query)
        _validate_query(candidate, 0, native["scope_binding"]["subject_id"])
        return candidate
    raise ContractError("query must be an exact query_id str or query dict")


def _record_map(native: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        record["statement_id"]: record
        for record in native["model_input_table"]
    }


def _roots_for(records: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    roots = {
        _root_ref_key(ref)
        for record in records
        for ref in record["root_refs"]
    }
    return [
        {"occurrence_id": occurrence, "version": version}
        for occurrence, version in sorted(roots)
    ]


def _result_envelope(
    native: Mapping[str, Any],
    query: Mapping[str, Any],
    distribution: Sequence[Mapping[str, Any]],
    used_records: Sequence[Mapping[str, Any]],
    *,
    native_witness: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    out = {
        "query_id": query["query_id"],
        "operator": query["kind"],
        "value_kind": "finite_probability_mass",
        "distribution": _clone_json(list(distribution)),
        "used_evidence": {
            "statement_ids": sorted(record["statement_id"] for record in used_records),
            "root_refs": _roots_for(used_records),
            "temporal_cut": _clone_json(native["frozen_cut"]),
            "version_vector": _clone_json(native["version_vector"]),
        },
        "uncertainty": {
            "semantics": native["uncertainty_contract"]["belief_semantics"],
            "unknown_policy": native["uncertainty_contract"]["unknown_policy"],
            "dependence_policy": native["uncertainty_contract"]["dependence_policy"],
        },
        "native_witness": _clone_json(native_witness),
    }
    if extra:
        out.update(_clone_json(extra))
    validate_json_like(out, label="execution result", allow_tuple=False)
    return out


def _dbn_tables(model: Mapping[str, Any]) -> tuple[list[Any], list[str], dict[str, float], dict[tuple[int, str, str], float], dict[tuple[str, str, str], float]]:
    states = model["states"]
    state_keys = [_json_key(state) for state in states]
    prior = {_json_key(row["state"]): float(row["probability"]) for row in model["prior"]}
    slice_index = {value: index for index, value in enumerate(model["slices"])}
    transitions: dict[tuple[int, str, str], float] = {}
    for row in model["transitions"]:
        transitions[(slice_index[row["from_slice"]], _json_key(row["from_state"]), _json_key(row["to_state"]))] = float(row["probability"])
    emissions: dict[tuple[str, str, str], float] = {}
    for row in model["emissions"]:
        emissions[(row["concept"], _json_key(row["state"]), _json_key(row["observed_value"]))] = float(row["probability"])
    return states, state_keys, prior, transitions, emissions


def _dbn_observation_likelihood(
    record: Mapping[str, Any],
    state_key: str,
    emissions: Mapping[tuple[str, str, str], float],
) -> float:
    concept = record["concept"]
    measurement = record["measurement"]
    if measurement["kind"] == "explicit_no_value":
        raise SemanticLossError("explicit_no_value cannot become a DBN observation")
    possible = [
        (observed_key, probability)
        for (candidate_concept, candidate_state, observed_key), probability in emissions.items()
        if candidate_concept == concept and candidate_state == state_key
    ]
    if not possible:
        raise SemanticLossError(f"DBN has no observation model for concept {concept!r}")
    total = 0.0
    for observed_key, probability in possible:
        observed = json.loads(observed_key)
        total += probability * _measurement_likelihood(measurement, observed)
    return total


def _dbn_selected_records(
    native: Mapping[str, Any], query: Mapping[str, Any], model: Mapping[str, Any]
) -> tuple[list[Mapping[str, Any]], int, int]:
    slice_index = {value: index for index, value in enumerate(model["slices"])}
    if query["at"] not in slice_index:
        raise SemanticLossError("DBN query target is not an explicit temporal slice")
    target_index = slice_index[query["at"]]
    if query["kind"] == "filter":
        availability_cut = min(_dt(query["at"]), _dt(native["frozen_cut"]["actor_visibility_cut"]))
    else:
        availability_cut = _dt(query["later_evidence_cut"])
        if availability_cut > _dt(native["frozen_cut"]["actor_visibility_cut"]):
            raise SemanticLossError("smooth asks for evidence beyond frozen actor visibility")
    emission_concepts = {row["concept"] for row in model["emissions"]}
    selected: list[Mapping[str, Any]] = []
    max_index = target_index
    for record in _record_map(native).values():
        if record["concept"] not in emission_concepts:
            continue
        if record["information_state"] != "present":
            if record["information_state"] in {"conflicting", "masked", "insufficient"}:
                raise SemanticLossError("non-present epistemic state cannot be coerced to a DBN likelihood")
            continue
        if _dt(record["clocks"]["available_at"]) > availability_cut:
            continue
        slice_id = record["clocks"].get("slice_id") or record["clocks"]["effective_start"]
        if slice_id not in slice_index:
            raise SemanticLossError(f"observation {record['statement_id']} has no DBN slice")
        index = slice_index[slice_id]
        if query["kind"] == "filter" and index > target_index:
            continue
        selected.append(record)
        max_index = max(max_index, index)
    return selected, target_index, max_index


def _execute_dbn(native: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    if query["kind"] not in {"filter", "smooth"}:
        raise SemanticLossError(f"finite_dbn does not provide {query['kind']} semantics")
    model = native["native_model"]
    states, state_keys, prior, transitions, emissions = _dbn_tables(model)
    records, target_index, max_index = _dbn_selected_records(native, query, model)
    records_by_slice: dict[int, list[Mapping[str, Any]]] = {}
    slice_index = {value: index for index, value in enumerate(model["slices"])}
    for record in records:
        slice_id = record["clocks"].get("slice_id") or record["clocks"]["effective_start"]
        records_by_slice.setdefault(slice_index[slice_id], []).append(record)

    filtered: list[dict[str, float]] = []
    current = dict(prior)
    for index in range(max_index + 1):
        if index > 0:
            predicted = {
                to_key: sum(
                    current[from_key] * transitions[(index - 1, from_key, to_key)]
                    for from_key in state_keys
                )
                for to_key in state_keys
            }
            current = predicted
        for record in records_by_slice.get(index, []):
            current = {
                state_key: current[state_key]
                * _dbn_observation_likelihood(record, state_key, emissions)
                for state_key in state_keys
            }
            current = _normalize(current, f"DBN evidence at slice {index}")
        filtered.append(dict(current))

    if query["kind"] == "filter":
        posterior = filtered[target_index]
        witness = {
            "algorithm": "finite_forward_filter",
            "target_slice": model["slices"][target_index],
            "evidence_policy": "available_by_target",
            "future_evidence_used": False,
        }
    else:
        backward = {key: 1.0 for key in state_keys}
        for index in range(max_index - 1, target_index - 1, -1):
            next_likelihood: dict[str, float] = {}
            for to_key in state_keys:
                value = backward[to_key]
                for record in records_by_slice.get(index + 1, []):
                    value *= _dbn_observation_likelihood(record, to_key, emissions)
                next_likelihood[to_key] = value
            backward = {
                from_key: sum(
                    transitions[(index, from_key, to_key)] * next_likelihood[to_key]
                    for to_key in state_keys
                )
                for from_key in state_keys
            }
        posterior = _normalize(
            {key: filtered[target_index][key] * backward[key] for key in state_keys},
            "DBN retrospective smoothing",
        )
        witness = {
            "algorithm": "finite_forward_backward_smoother",
            "target_slice": model["slices"][target_index],
            "later_evidence_cut": query["later_evidence_cut"],
            "future_evidence_used": any(
                (record["clocks"].get("slice_id") or record["clocks"]["effective_start"])
                > query["at"]
                for record in records
            ),
        }
    distribution = [
        {"value": _clone_json(state), "probability": posterior[key]}
        for state, key in zip(states, state_keys)
    ]
    return _result_envelope(native, query, distribution, records, native_witness=witness)


def _scm_evaluate_world(
    model: Mapping[str, Any], world: Mapping[str, Any], do_set: Mapping[str, Any]
) -> dict[str, Any]:
    domains = {variable: {_json_key(value) for value in values} for variable, values in model["domains"].items()}
    for variable, value in do_set.items():
        if variable not in domains or _json_key(value) not in domains[variable]:
            raise SemanticLossError(f"do assignment {variable}={value!r} is outside SCM domain")
    env = _clone_json(world["values"])
    endogenous: dict[str, Any] = {}
    equations = {equation["variable"]: equation for equation in model["equations"]}
    for variable in model["endogenous_order"]:
        if variable in do_set:
            value = _clone_json(do_set[variable])
        else:
            matches: list[Any] = []
            available = {**env, **endogenous}
            for case in equations[variable]["cases"]:
                if all(
                    key in available and _json_key(available[key]) == _json_key(expected)
                    for key, expected in case["when"].items()
                ):
                    matches.append(case["value"])
            if len(matches) != 1:
                raise SemanticLossError(
                    f"SCM equation {variable!r} has {len(matches)} matching cases in world {world['world_id']}"
                )
            value = _clone_json(matches[0])
        endogenous[variable] = value
    return endogenous


def _scm_observation_likelihood(
    record: Mapping[str, Any], assignment: Mapping[str, Any], bindings: Mapping[str, str]
) -> float:
    variable = bindings.get(record["concept"])
    if variable is None:
        raise SemanticLossError(f"SCM has no binding for concept {record['concept']!r}")
    if record["information_state"] != "present":
        raise SemanticLossError("SCM factual observation must be present; unknown/conflict is not probability")
    return _measurement_likelihood(record["measurement"], assignment[variable])


def _scm_posterior_worlds(
    native: Mapping[str, Any],
    observation_ids: Sequence[str],
    *,
    do_set_for_likelihood: Mapping[str, Any] | None = None,
) -> tuple[dict[str, float], list[Mapping[str, Any]], dict[str, dict[str, Any]]]:
    model = native["native_model"]
    records_by_id = _record_map(native)
    records: list[Mapping[str, Any]] = []
    for statement_id in observation_ids:
        record = records_by_id.get(statement_id)
        if record is None:
            raise SemanticLossError(f"factual observation {statement_id!r} is not active at cut")
        records.append(record)
    bindings = {row["concept"]: row["variable"] for row in model["observation_bindings"]}
    assignments: dict[str, dict[str, Any]] = {}
    weights: dict[str, float] = {}
    for world in model["exogenous_worlds"]:
        assignment = _scm_evaluate_world(model, world, do_set_for_likelihood or {})
        assignments[world["world_id"]] = assignment
        likelihood = 1.0
        for record in records:
            likelihood *= _scm_observation_likelihood(record, assignment, bindings)
        weights[world["world_id"]] = float(world["probability"]) * likelihood
    return _normalize(weights, "SCM conditioning/abduction"), records, assignments


def _distribution_from_worlds(
    model: Mapping[str, Any],
    world_weights: Mapping[str, float],
    assignments: Mapping[str, Mapping[str, Any]],
    estimand: str,
) -> list[dict[str, Any]]:
    if estimand not in model["domains"]:
        raise SemanticLossError(f"SCM estimand {estimand!r} is outside model")
    mass = {_json_key(value): 0.0 for value in model["domains"][estimand]}
    originals = {_json_key(value): value for value in model["domains"][estimand]}
    for world_id, weight in world_weights.items():
        mass[_json_key(assignments[world_id][estimand])] += weight
    return [
        {"value": _clone_json(originals[key]), "probability": mass[key]}
        for key in [_json_key(value) for value in model["domains"][estimand]]
    ]


def _execute_scm(native: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    if query["kind"] not in {"condition", "intervene", "aap"}:
        raise SemanticLossError(f"finite_scm does not provide {query['kind']} semantics")
    model = native["native_model"]
    worlds = {world["world_id"]: world for world in model["exogenous_worlds"]}

    if query["kind"] == "condition":
        weights, records, assignments = _scm_posterior_worlds(native, query["observation_ids"])
        distribution = _distribution_from_worlds(model, weights, assignments, query["estimand"])
        return _result_envelope(
            native,
            query,
            distribution,
            records,
            native_witness={
                "algorithm": "finite_world_conditioning",
                "operator_semantics": "condition_on_observations",
                "posterior_world_mass": weights,
            },
        )

    if query["kind"] == "intervene":
        if query["identification_contract"] not in model["identification_contracts"]:
            raise SemanticLossError("requested intervention identification contract is unavailable")
        conditioning = query["conditioning_observation_ids"]
        if conditioning:
            weights, records, _ = _scm_posterior_worlds(native, conditioning)
        else:
            weights = {world_id: float(world["probability"]) for world_id, world in worlds.items()}
            records = []
        intervened = {
            world_id: _scm_evaluate_world(model, world, query["do_set"])
            for world_id, world in worlds.items()
        }
        distribution = _distribution_from_worlds(model, weights, intervened, query["estimand"])
        return _result_envelope(
            native,
            query,
            distribution,
            records,
            native_witness={
                "algorithm": "finite_structural_mechanism_replacement",
                "operator_semantics": "population_do",
                "replaced_mechanisms": sorted(query["do_set"]),
                "shared_abduced_world": False,
            },
        )

    # AAP is intentionally a separate path: first abduce factual world mass,
    # then apply the mechanism replacement to those *same* world identities.
    weights, records, factual_assignments = _scm_posterior_worlds(
        native, query["factual_observation_ids"]
    )
    counterfactual_assignments = {
        world_id: _scm_evaluate_world(model, world, query["do_set"])
        for world_id, world in worlds.items()
    }
    distribution = _distribution_from_worlds(
        model, weights, counterfactual_assignments, query["estimand"]
    )
    factual_estimand = _distribution_from_worlds(
        model, weights, factual_assignments, query["estimand"]
    )
    return _result_envelope(
        native,
        query,
        distribution,
        records,
        native_witness={
            "algorithm": "finite_aap_shared_world",
            "operator_semantics": "same_patient_counterfactual",
            "stages": ["abduction", "action", "prediction"],
            "abduced_world_mass": weights,
            "world_ids_reused_after_action": sorted(
                world_id for world_id, probability in weights.items() if probability > 0.0
            ),
            "replaced_mechanisms": sorted(query["do_set"]),
        },
        extra={"factual_estimand_distribution": factual_estimand},
    )


def execute(native: Mapping[str, Any], query: str | Mapping[str, Any]) -> dict[str, Any]:
    """Execute one closed query using only native semantic fields."""

    _validate_native(native)
    parsed = _query_from(native, query)
    if native["target_kernel"] == "finite_dbn":
        return _execute_dbn(native, parsed)
    return _execute_scm(native, parsed)


def apply_delta(native: Mapping[str, Any], delta: Mapping[str, Any]) -> dict[str, Any]:
    """Append a typed correction/retraction and refresh native eligibility.

    No negative observation is synthesized.  The returned IR retains the old
    root/record versions for historical recovery and carries the appended delta.
    """

    _validate_native(native)
    if type(delta) is not dict:
        raise ContractError("delta must be an exact dict")
    candidate_delta = _clone_json(delta)
    _validate_delta(candidate_delta, len(native["delta_log"]))
    if candidate_delta["delta_id"] in {item["delta_id"] for item in native["delta_log"]}:
        raise ContractError("duplicate delta_id")
    updated = _clone_json(native)

    if candidate_delta["kind"] == "retract":
        target = _root_ref_key(candidate_delta["target_root"])
        roots = {(root["occurrence_id"], root["version"]) for root in updated["root_table"]}
        if target not in roots:
            raise SemanticLossError("retraction targets an unknown root occurrence/version")
    else:
        old = _statement_ref_key(candidate_delta["old_statement"])
        record_refs = {(record["logical_id"], record["version"]) for record in updated["evidence_table"]}
        if old not in record_refs:
            raise SemanticLossError("correction targets an unknown statement version")
        new_root = candidate_delta["new_root"]
        # Correction payload stores full root/record, not a lossy reference.
        root_key = _validate_root(new_root, len(updated["root_table"]))
        if root_key in {(root["occurrence_id"], root["version"]) for root in updated["root_table"]}:
            raise ContractError("correction new root already exists")
        provisional_roots = {
            (root["occurrence_id"], root["version"]) for root in updated["root_table"]
        } | {root_key}
        new_record = candidate_delta["new_record"]
        record_key = _validate_record(
            new_record,
            len(updated["evidence_table"]),
            provisional_roots,
            updated["scope_binding"],
        )
        if record_key in record_refs:
            raise ContractError("correction new statement version already exists")
        if new_record.get("supersedes") != candidate_delta["old_statement"]:
            raise SemanticLossError("correction new record must explicitly supersede old_statement")
        updated["root_table"].append(new_root)
        updated["evidence_table"].append(new_record)

    updated["delta_log"].append(candidate_delta)
    # These are derived indexes, recomputed from the append-only semantic tables.
    recovered = _recover_unchecked(updated)
    recovered["roots"] = updated["root_table"]
    recovered["evidence_history"] = updated["evidence_table"]
    recovered["deltas"] = updated["delta_log"]
    recovered = _normalized_bundle(recovered)
    updated["root_table"] = _clone_json(recovered["roots"])
    updated["evidence_table"] = _clone_json(recovered["evidence_history"])
    updated["delta_log"] = _clone_json(recovered["deltas"])
    updated["active_statement_ids"] = _active_statement_ids(
        updated["root_table"], updated["evidence_table"], updated["delta_log"], updated["frozen_cut"]
    )
    updated["model_input_table"] = _model_input_rows(recovered, updated["active_statement_ids"])
    updated["lineage_map"] = _lineage_rows(recovered, updated["active_statement_ids"])
    updated["semantic_digest"] = _digest(recovered)
    _validate_native(updated)
    return updated


def _fixture() -> dict[str, Any]:
    """Small independent fixture used only by :func:`self_test`."""

    t0, t1, t2, t3 = (
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
        "2026-01-01T02:00:00Z",
        "2026-01-01T03:00:00Z",
    )
    scope = {"subject_id": "patient-a", "encounter_id": "enc-a"}

    def root(root_id: str, raw: Any) -> dict[str, Any]:
        return {
            "occurrence_id": root_id,
            "version": "1",
            "artifact_id": f"artifact-{root_id}",
            "artifact_version": "1",
            "source_span": {"start": 0, "end": 1},
            "raw_payload": raw,
            "raw_digest": _digest(raw),
            "dependence_families": [f"family-{root_id}"],
        }

    roots = [root("r-y0", {"Y": 1}), root("r-y2", {"Y": 0}), root("r-t", {"T": 1}), root("r-o", {"O": 1})]

    def record(statement: str, concept: str, value: Any, when: str, available: str, root_id: str) -> dict[str, Any]:
        return {
            "statement_id": statement,
            "logical_id": statement,
            "version": "1",
            "concept": concept,
            "semantic_role": "raw_observation",
            "information_state": "present",
            "scope": _clone_json(scope),
            "clocks": {
                "effective_start": when,
                "available_at": available,
                "recorded_at": available,
                "slice_id": when,
            },
            "measurement": {"kind": "exact", "value": value},
            "unit": None,
            "method": "fixture",
            "mapping_versions": ["map-v1"],
            "root_refs": [{"occurrence_id": root_id, "version": "1"}],
            "proof": {"kind": "root", "root": root_id},
        }

    history = [
        record("s-y0", "sensor_y", 1, t0, t0, "r-y0"),
        record("s-y2", "sensor_y", 0, t2, t2, "r-y2"),
        record("s-t", "treatment", 1, t0, t0, "r-t"),
        record("s-o", "outcome", 1, t0, t0, "r-o"),
    ]

    states = [0, 1]
    transitions: list[dict[str, Any]] = []
    for left, right in ((t0, t1), (t1, t2), (t2, t3)):
        for old in states:
            for new in states:
                transitions.append(
                    {
                        "from_slice": left,
                        "to_slice": right,
                        "from_state": old,
                        "to_state": new,
                        "probability": 0.8 if old == new else 0.2,
                    }
                )
    emissions = [
        {"concept": "sensor_y", "state": state, "observed_value": observed, "probability": 0.9 if state == observed else 0.1}
        for state in states
        for observed in states
    ]
    dbn = {
        "model_id": "dbn-a",
        "version": "model-a1",
        "kernel": "finite_dbn",
        "state_variable": "X",
        "states": states,
        "slices": [t0, t1, t2, t3],
        "prior": [{"state": 0, "probability": 0.5}, {"state": 1, "probability": 0.5}],
        "transitions": transitions,
        "emissions": emissions,
        "uncertainty_semantics": "finite_probability_mass/v1",
        "coverage_contract": {"concepts": ["sensor_y"]},
    }
    scm = {
        "model_id": "scm-a",
        "version": "model-a2",
        "kernel": "finite_scm",
        "endogenous_order": ["H", "T", "Y"],
        "domains": {"H": [0, 1], "T": [0, 1], "Y": [0, 1]},
        "exogenous_worlds": [
            {"world_id": "u0", "probability": 0.5, "values": {"U": 0}},
            {"world_id": "u1", "probability": 0.5, "values": {"U": 1}},
        ],
        "equations": [
            {"variable": "H", "cases": [{"when": {"U": 0}, "value": 0}, {"when": {"U": 1}, "value": 1}]},
            {"variable": "T", "cases": [{"when": {"H": 0}, "value": 0}, {"when": {"H": 1}, "value": 1}]},
            {
                "variable": "Y",
                "cases": [
                    {"when": {"H": 0, "T": 0}, "value": 0},
                    {"when": {"H": 0, "T": 1}, "value": 1},
                    {"when": {"H": 1, "T": 0}, "value": 1},
                    {"when": {"H": 1, "T": 1}, "value": 1},
                ],
            },
        ],
        "observation_bindings": [
            {"concept": "treatment", "variable": "T"},
            {"concept": "outcome", "variable": "Y"},
        ],
        "uncertainty_semantics": "finite_probability_mass/v1",
        "coverage_contract": {"population": "fixture-population"},
        "identification_contracts": ["structural-enumeration-v1"],
    }
    return {
        "schema_version": CANONICAL_SCHEMA,
        "bridge": {
            "bridge_id": "bridge-a",
            "version": "bridge-v1",
            "registered_at": t0,
            "source_kernel": "evidence_authority",
            "source_role": "raw_observation",
            "target_role": "raw_observation",
            "transform": "identity",
            "source_concept": None,
            "target_concept": None,
            "source_unit": None,
            "target_unit": None,
        },
        "scope": scope,
        "temporal_cut": {
            "target_window": {"start": t0, "end": t3},
            "actor_visibility_cut": t3,
            "transaction_revision_cut": t3,
            "evidence_use_policy": "query_variant_explicit",
            "evidence_snapshot_id": "snapshot-a",
            "external_response_snapshot": {"id": "none"},
            "randomness_policy": {"kind": "exact_enumeration"},
            "principal_authorization_snapshot": {"principal": "test"},
        },
        "version_vector": {
            "bridge": "bridge-v1",
            "adapter": "impl-a-v1",
            "terminology": "term-v1",
            "knowledge": "knowledge-v1",
            "model": "model-a1+model-a2",
            "policy": "policy-v1",
            "solver": "finite-enumerator-v1",
        },
        "roots": roots,
        "evidence_history": history,
        "deltas": [],
        "models": {"finite_dbn": dbn, "finite_scm": scm},
        "queries": [
            {"query_id": "q-filter", "kind": "filter", "target": "X", "at": t1},
            {"query_id": "q-smooth", "kind": "smooth", "target": "X", "at": t1, "later_evidence_cut": t3},
            {"query_id": "q-condition", "kind": "condition", "estimand": "H", "observation_ids": ["s-t"]},
            {
                "query_id": "q-do",
                "kind": "intervene",
                "estimand": "Y",
                "do_set": {"T": 0},
                "conditioning_observation_ids": [],
                "population": "fixture-population",
                "identification_contract": "structural-enumeration-v1",
                "mechanism_replacement": True,
            },
            {
                "query_id": "q-aap",
                "kind": "aap",
                "unit": "patient-a",
                "estimand": "Y",
                "factual_observation_ids": ["s-t", "s-o"],
                "do_set": {"T": 0},
                "shared_world_policy": "share_abduced_exogenous",
                "stages": ["abduction", "action", "prediction"],
            },
        ],
        "uncertainty_contract": {
            "belief_semantics": "finite_probability_mass",
            "unknown_policy": "preserve_not_zero",
            "conflict_policy": "reject_before_model",
            "dependence_policy": "model_declared_not_root_count",
            "version": "uncertainty-v1",
        },
    }


@dataclass(frozen=True)
class SelfTestReport:
    passed: bool
    checks: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": dict(self.checks)}


def self_test() -> SelfTestReport:
    bundle = _fixture()
    checks: dict[str, bool] = {}
    decoded = CodecA.round_trip(bundle)
    checks["codec_round_trip"] = CodecA.semantic_digest(bundle) == CodecA.semantic_digest(decoded)

    dbn = compile_bundle(decoded, "finite_dbn")
    scm = compile_bundle(decoded, "finite_scm")
    checks["dbn_recover"] = recover_bundle(dbn) == decoded
    checks["scm_recover"] = recover_bundle(scm) == decoded

    filtered = execute(dbn, "q-filter")
    smoothed = execute(dbn, "q-smooth")
    checks["filter_not_smooth"] = filtered["distribution"] != smoothed["distribution"]
    checks["filter_future_safe"] = filtered["native_witness"]["future_evidence_used"] is False
    checks["smooth_uses_later"] = smoothed["native_witness"]["future_evidence_used"] is True

    conditioned = execute(scm, "q-condition")
    intervened = execute(scm, "q-do")
    aap = execute(scm, "q-aap")
    checks["operator_tags_distinct"] = [
        conditioned["operator"], intervened["operator"], aap["operator"]
    ] == ["condition", "intervene", "aap"]
    checks["condition_identifies_h1"] = conditioned["distribution"][1]["probability"] == 1.0
    checks["do_not_aap"] = intervened["distribution"] != aap["distribution"]
    checks["aap_reuses_world"] = aap["native_witness"]["world_ids_reused_after_action"] == ["u1"]

    # Retraction removes the late root; it does not add value=1/negative evidence.
    retracted = apply_delta(
        dbn,
        {
            "kind": "retract",
            "delta_id": "delta-r-y2",
            "registered_at": "2026-01-01T02:30:00Z",
            "reason": "source correction",
            "target_root": {"occurrence_id": "r-y2", "version": "1"},
        },
    )
    retracted_smooth = execute(retracted, "q-smooth")
    checks["retract_not_negative"] = "s-y2" not in retracted_smooth["used_evidence"]["statement_ids"]
    clean = compile_bundle(recover_bundle(retracted), "finite_dbn")
    checks["delta_equals_clean_rebuild"] = execute(retracted, "q-smooth") == execute(clean, "q-smooth")

    # Tampering with lineage must fail recovery.
    tampered = _clone_json(dbn)
    tampered["lineage_map"][0]["root_refs"] = []
    try:
        recover_bundle(tampered)
    except SemanticLossError:
        checks["lineage_tamper_rejected"] = True
    else:
        checks["lineage_tamper_rejected"] = False
    return SelfTestReport(all(checks.values()), checks)


__all__ = [
    "CANONICAL_SCHEMA",
    "COMPILER_ID",
    "CodecA",
    "NATIVE_SCHEMA",
    "SelfTestReport",
    "SemanticLossError",
    "apply_delta",
    "compile_bundle",
    "execute",
    "recover_bundle",
    "self_test",
]


if __name__ == "__main__":  # pragma: no cover - manual smoke entry point.
    print(json.dumps(self_test().to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
