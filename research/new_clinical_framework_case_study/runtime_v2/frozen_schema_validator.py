"""Small dependency-free validator for the frozen SharedPatientState schema.

The runtime cannot treat an external ``Test-Json`` invocation as its
deserialization boundary.  This module implements exactly the JSON-Schema
keywords used by ``architecture_final_v1.schema.json`` so malformed nested
state is rejected by ``SharedPatientState.from_dict`` itself.

It is intentionally not advertised as a general JSON-Schema implementation.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "architecture_final_v1.schema.json"


@lru_cache(maxsize=1)
def _root_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _fail(path: str, message: str) -> None:
    raise ValueError(f"frozen architecture schema violation at {path}: {message}")


def _resolve_ref(root: Mapping[str, Any], ref: str, path: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        _fail(path, f"unsupported non-local $ref {ref!r}")
    node: Any = root
    for raw in ref[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or token not in node:
            _fail(path, f"unresolvable $ref {ref!r}")
        node = node[token]
    if not isinstance(node, Mapping):
        _fail(path, f"$ref {ref!r} does not resolve to a schema object")
    return node


def _is_type(value: Any, declared: str) -> bool:
    if declared == "null":
        return value is None
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if declared == "string":
        return isinstance(value, str)
    if declared == "array":
        return isinstance(value, list)
    if declared == "object":
        return isinstance(value, Mapping)
    return False


def _canonical_item(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


_RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _validate_format(value: str, declared_format: str, path: str) -> None:
    if declared_format != "date-time":
        _fail(path, f"unsupported frozen-schema format {declared_format!r}")
    if _RFC3339_DATE_TIME.fullmatch(value) is None:
        _fail(path, "string is not an RFC3339 date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        _fail(path, f"invalid RFC3339 date-time: {exc}")
    if parsed.tzinfo is None:
        _fail(path, "RFC3339 date-time must include a UTC offset")


def _validate(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any], path: str) -> None:
    if "$ref" in schema:
        _validate(value, _resolve_ref(root, str(schema["$ref"]), path), root, path)
        return

    if "oneOf" in schema:
        matches = 0
        errors: list[str] = []
        for candidate in schema["oneOf"]:
            try:
                _validate(value, candidate, root, path)
                matches += 1
            except ValueError as exc:
                errors.append(str(exc))
        if matches != 1:
            _fail(path, f"oneOf matched {matches} alternatives")
        return

    if "const" in schema and value != schema["const"]:
        _fail(path, f"expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        _fail(path, f"value {value!r} is not in the declared enum")

    declared = schema.get("type")
    if declared is not None:
        allowed = [declared] if isinstance(declared, str) else list(declared)
        if not any(_is_type(value, kind) for kind in allowed):
            _fail(path, f"expected type {allowed!r}, got {type(value).__name__}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            _fail(path, f"string shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            _fail(path, f"string longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and re.search(str(schema["pattern"]), value) is None:
            _fail(path, f"string does not match pattern {schema['pattern']!r}")
        if "format" in schema:
            _validate_format(value, str(schema["format"]), path)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            _fail(path, "number must be finite")
        if "minimum" in schema and number < float(schema["minimum"]):
            _fail(path, f"number is below minimum {schema['minimum']}")
        if "maximum" in schema and number > float(schema["maximum"]):
            _fail(path, f"number is above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and number <= float(schema["exclusiveMinimum"]):
            _fail(path, f"number is not above exclusiveMinimum {schema['exclusiveMinimum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            _fail(path, f"array shorter than minItems {schema['minItems']}")
        if schema.get("uniqueItems"):
            rendered = [_canonical_item(item) for item in value]
            if len(rendered) != len(set(rendered)):
                _fail(path, "array items are not unique")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(item, schema["items"], root, f"{path}[{index}]")

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            _fail(path, f"missing required properties {missing!r}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                _validate(item, properties[key], root, child_path)
            elif additional is False:
                _fail(child_path, "additional property is forbidden")
            elif isinstance(additional, Mapping):
                _validate(item, additional, root, child_path)
        property_names = schema.get("propertyNames")
        if isinstance(property_names, Mapping):
            for key in value:
                _validate(str(key), property_names, root, f"{path}.<property-name>")


def validate_frozen_architecture_schema(value: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` unless ``value`` satisfies the frozen state schema."""

    _validate(value, _root_schema(), _root_schema(), "$")


__all__ = ["validate_frozen_architecture_schema"]
