"""Fail-closed PRE-FREEZE producer for the future UCM formal scope.

The producer consumes seven exact, code-owned predecessor artifacts in one
fixed order.  It records their complete canonical bytes and native semantic
digests, but it cannot turn an incomplete semantic registry into a
``ScopeManifest``.  The currently live predecessors deliberately produce a
canonical build report containing their exact gap inventories instead.

This module is evidence machinery only.  Neither a gap-free scope build nor a
``PRE-FREEZE_SCOPE_CLOSED`` report is a benchmark freeze or freeze authority.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    domain_digest,
    validate_json_like,
)
from .metric_configuration import (
    METRIC_TARGET_DOMAIN,
    parse_metric_target_registry_bytes,
)
from .scope_manifest import (
    SCOPE_AXES,
    ScopeAxisDeclarations,
    ScopeDeclaration,
    ScopeManifest,
    parse_scope_manifest_bytes,
)
from .seed_protocol import (
    SEED_PROTOCOL_MANIFEST_BYTES,
    SEED_PROTOCOL_VERSION,
)
from .task_protocol import parse_task_execution_manifest_bytes
from .world_scope_fragments import (
    WORLD_SCOPE_FRAGMENT_DOMAIN,
    ScopeGapCode,
    inspect_world_scope_fragments,
    parse_world_scope_fragment_set_bytes,
)


FORMAL_SCOPE_BUILD_REPORT_SCHEMA = "ucm-formal-scope-build-report/1"
FORMAL_SCOPE_SOURCE_CLOSURE_SCHEMA = "ucm-formal-scope-source-closure/1"
FORMAL_SCOPE_BENCHMARK_ID = "UCM-BENCHMARK-v1"
FORMAL_SCOPE_INCOMPLETE_STATUS = "PRE-FREEZE"
FORMAL_SCOPE_CLOSED_STATUS = "PRE-FREEZE_SCOPE_CLOSED"

PREDECESSOR_ROOT_DOMAIN = b"UCM_FORMAL_SCOPE_PREDECESSOR_ROOT_V1\0"
SCOPE_BUILD_ROOT_DOMAIN = b"UCM_FORMAL_SCOPE_BUILD_ROOT_V1\0"
SOURCE_TREE_ROOT_DOMAIN = b"UCM_FORMAL_SCOPE_SOURCE_TREE_ROOT_V1\0"
SOURCE_CLOSURE_SEMANTIC_DOMAIN = b"UCM_FORMAL_SCOPE_SOURCE_CLOSURE_V1\0"
TASK_EXECUTION_SEMANTIC_DOMAIN = b"UCM_FORMAL_SCOPE_TASK_EXECUTION_V1\0"
SEED_PROTOCOL_SEMANTIC_DOMAIN = b"UCM_FORMAL_SCOPE_SEED_PROTOCOL_V1\0"

PREDECESSOR_ORDER = (
    "world_scope_fragment",
    "metric_semantic_registry",
    "task_execution_manifest",
    "seed_protocol_manifest",
    "split_derivation_protocol",
    "extension_template_set",
    "producer_source_closure_manifest",
)

_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "benchmark_id",
        "status",
        "scope_manifest_emitted",
        "benchmark_freeze_eligible",
        "freeze_authority",
        "predecessors",
        "predecessor_root",
        "gap_count",
        "gaps",
        "scope_manifest",
        "scope_build_root",
    }
)
_PREDECESSOR_KEYS = frozenset(
    {
        "predecessor_id",
        "canonical_bytes_base64",
        "canonical_byte_length",
        "artifact_digest",
        "semantic_domain",
        "domain_semantic_digest",
    }
)
_GAP_KEYS = frozenset({"source_id", "source_gap_index", "gap_id", "gap_wire"})
_SOURCE_CLOSURE_KEYS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "source_files",
        "source_tree_root",
        "loaded_live_attestation",
        "authoritative_process_requirement",
    }
)
_SOURCE_FILE_KEYS = frozenset({"relative_path", "byte_length", "sha256"})
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# This is the complete execution closure of this producer.  The semantic
# predecessors bind the much larger world/runtime closure through their own
# live rebuilds; this list binds the code that parses, joins and emits them.
_SOURCE_PATHS = (
    "prototype/unified_map/canonical.py",
    "prototype/unified_map/formal_scope_producer.py",
    "prototype/unified_map/metric_configuration.py",
    "prototype/unified_map/scope_manifest.py",
    "prototype/unified_map/scope_transition_protocols.py",
    "prototype/unified_map/seed_protocol.py",
    "prototype/unified_map/task_protocol.py",
    "prototype/unified_map/world_scope_fragments.py",
)


def _exact_object(
    value: object, expected_keys: frozenset[str], label: str
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    validate_json_like(value, path=label)
    actual = frozenset(value)
    if actual != expected_keys:
        raise ProtocolViolation(
            f"{label} has missing/extra fields; "
            f"missing={sorted(expected_keys - actual)!r}, "
            f"extra={sorted(actual - expected_keys)!r}"
        )
    return value


def _canonical_name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ProtocolViolation(f"{label} must be strict UTF-8") from exc
    return value


def _exact_nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProtocolViolation(f"{label} must be an exact nonnegative integer")
    return value


def _decode_exact_canonical_object(payload: object, label: str) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation(f"{label} must be exact bytes")

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicate_pairs,
        )
    except ProtocolViolation:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise ProtocolViolation(f"{label} is not strict UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must encode an exact object")
    validate_json_like(value, path=label)
    if canonical_json_bytes(value) != payload:
        raise ProtocolViolation(
            f"{label} is not canonical sorted compact JSON plus one LF"
        )
    return value


def _decode_base64(value: object, label: str) -> bytes:
    if type(value) is not str:
        raise ProtocolViolation(f"{label} must be an exact base64 string")
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ProtocolViolation(f"{label} is not canonical base64") from exc
    if base64.b64encode(raw).decode("ascii") != value:
        raise ProtocolViolation(f"{label} is not canonical base64")
    return raw


def _semantic_digest(domain: bytes, payload: bytes) -> str:
    return domain_digest(domain, (payload,))


@dataclass(frozen=True, slots=True)
class FormalScopePredecessor:
    """One exact predecessor record in the fixed producer chain."""

    predecessor_id: str
    canonical_bytes: bytes
    semantic_domain: str
    domain_semantic_digest: str

    def __post_init__(self) -> None:
        _canonical_name(self.predecessor_id, "predecessor_id")
        if self.predecessor_id not in PREDECESSOR_ORDER:
            raise ProtocolViolation("predecessor_id is not code-owned")
        if type(self.canonical_bytes) is not bytes:
            raise ProtocolViolation("predecessor canonical bytes must be exact bytes")
        _canonical_name(self.semantic_domain, "predecessor semantic_domain")
        expected = self.domain_semantic_digest
        if type(expected) is not str or _DIGEST_RE.fullmatch(expected) is None:
            raise ProtocolViolation("predecessor semantic digest is malformed")

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    def to_wire(self) -> dict[str, Any]:
        return {
            "predecessor_id": self.predecessor_id,
            "canonical_bytes_base64": base64.b64encode(self.canonical_bytes).decode(
                "ascii"
            ),
            "canonical_byte_length": len(self.canonical_bytes),
            "artifact_digest": self.artifact_digest,
            "semantic_domain": self.semantic_domain,
            "domain_semantic_digest": self.domain_semantic_digest,
        }

    @property
    def record_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class FormalScopeGap:
    """An exact source gap with its original typed wire payload."""

    source_id: str
    source_gap_index: int
    gap_id: str
    gap_wire_bytes: bytes

    def __post_init__(self) -> None:
        if self.source_id not in PREDECESSOR_ORDER:
            raise ProtocolViolation("formal scope gap source is not code-owned")
        _exact_nonnegative_int(self.source_gap_index, "source_gap_index")
        _canonical_name(self.gap_id, "formal scope gap_id")
        _decode_exact_canonical_object(self.gap_wire_bytes, "formal scope gap_wire")

    @property
    def gap_wire(self) -> dict[str, Any]:
        # Return fresh inert data; callers cannot mutate the gap identity held
        # by a frozen build report after its roots have been calculated.
        return json.loads(self.gap_wire_bytes)

    def to_wire(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_gap_index": self.source_gap_index,
            "gap_id": self.gap_id,
            "gap_wire": self.gap_wire,
        }


def _formal_gap(
    source_id: str,
    source_gap_index: int,
    gap_id: str,
    gap_wire: dict[str, Any],
) -> FormalScopeGap:
    return FormalScopeGap(
        source_id,
        source_gap_index,
        gap_id,
        canonical_json_bytes(gap_wire),
    )


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_source_rows() -> tuple[dict[str, Any], ...]:
    root = _source_root()
    rows: list[dict[str, Any]] = []
    for relative_path in _SOURCE_PATHS:
        path = root / Path(relative_path)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ProtocolViolation(
                f"producer source closure member is unreadable: {relative_path}"
            ) from exc
        rows.append(
            {
                "relative_path": relative_path,
                "byte_length": len(payload),
                "sha256": digest_bytes(payload),
            }
        )
    return tuple(rows)


def _source_tree_root(rows: tuple[dict[str, Any], ...]) -> str:
    return domain_digest(
        SOURCE_TREE_ROOT_DOMAIN,
        tuple(canonical_json_bytes(row) for row in rows),
    )


def _source_closure_wire(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    return {
        "schema_version": FORMAL_SCOPE_SOURCE_CLOSURE_SCHEMA,
        "artifact_type": "UCM_FORMAL_SCOPE_PRODUCER_SOURCE_CLOSURE",
        "source_files": list(rows),
        "source_tree_root": _source_tree_root(rows),
        "loaded_live_attestation": (
            "producer_import_snapshot_plus_post_execution_live_rehash"
        ),
        "authoritative_process_requirement": (
            "fresh_process_import_and_materialization_required"
        ),
    }


# Captured after Python has loaded the module source.  A long-lived process
# cannot silently attest newly changed on-disk code with stale loaded code.
_LOADED_SOURCE_ROWS = _read_source_rows()


def build_code_owned_producer_source_closure_manifest_bytes() -> bytes:
    """Rehash the complete producer closure and reject loaded/live drift."""

    live_rows = _read_source_rows()
    if live_rows != _LOADED_SOURCE_ROWS:
        raise ProtocolViolation(
            "producer source closure drifted after module load; use a fresh process"
        )
    return canonical_json_bytes(_source_closure_wire(live_rows))


def parse_producer_source_closure_manifest_bytes(payload: bytes) -> dict[str, Any]:
    """Strictly parse and live-rebuild the producer/source closure."""

    body = _exact_object(
        _decode_exact_canonical_object(payload, "producer source closure manifest"),
        _SOURCE_CLOSURE_KEYS,
        "producer source closure manifest",
    )
    if (
        body["schema_version"] != FORMAL_SCOPE_SOURCE_CLOSURE_SCHEMA
        or body["artifact_type"] != "UCM_FORMAL_SCOPE_PRODUCER_SOURCE_CLOSURE"
    ):
        raise ProtocolViolation("producer source closure identity is not code-owned")
    source_files = body["source_files"]
    if type(source_files) is not list:
        raise ProtocolViolation("producer source_files must be an exact list")
    for index, row in enumerate(source_files):
        _exact_object(row, _SOURCE_FILE_KEYS, f"producer source file {index}")
    expected = build_code_owned_producer_source_closure_manifest_bytes()
    if payload != expected:
        raise ProtocolViolation(
            "producer source closure contradicts fresh code-owned source bytes"
        )
    return body


def producer_source_closure_artifact_digest_from_bytes(payload: bytes) -> str:
    parse_producer_source_closure_manifest_bytes(payload)
    return digest_bytes(payload)


def producer_source_closure_semantic_digest_from_bytes(payload: bytes) -> str:
    parse_producer_source_closure_manifest_bytes(payload)
    return _semantic_digest(SOURCE_CLOSURE_SEMANTIC_DOMAIN, payload)


def _strict_seed_protocol(payload: bytes) -> None:
    body = _decode_exact_canonical_object(payload, "seed protocol manifest")
    if body.get("schema_version") != SEED_PROTOCOL_VERSION:
        raise ProtocolViolation("seed protocol schema is not code-owned")
    # The code-owned semantics describe future commitment protocols, but never
    # contain a run-specific precommit, commitment, or raw seed value.
    if payload != SEED_PROTOCOL_MANIFEST_BYTES:
        raise ProtocolViolation("seed protocol differs from code-owned semantics")


def _transition_module() -> Any:
    try:
        from . import scope_transition_protocols
    except ImportError as exc:
        raise ProtocolViolation(
            "scope transition protocol module is unavailable"
        ) from exc
    return scope_transition_protocols


def _build_predecessors(
    world_scope_fragment_bytes: bytes,
    metric_semantic_registry_bytes: bytes,
    task_execution_manifest_bytes: bytes,
    seed_protocol_manifest_bytes: bytes,
    split_derivation_protocol_bytes: bytes,
    extension_template_set_bytes: bytes,
    producer_source_closure_manifest_bytes: bytes,
) -> tuple[FormalScopePredecessor, ...]:
    world = parse_world_scope_fragment_set_bytes(world_scope_fragment_bytes)
    metric = parse_metric_target_registry_bytes(metric_semantic_registry_bytes)
    parse_task_execution_manifest_bytes(task_execution_manifest_bytes)
    _strict_seed_protocol(seed_protocol_manifest_bytes)

    transitions = _transition_module()
    split = transitions.parse_split_derivation_protocol_bytes(
        split_derivation_protocol_bytes
    )
    extension = transitions.parse_extension_template_set_bytes(
        extension_template_set_bytes
    )
    if (
        split.canonical_bytes != split_derivation_protocol_bytes
        or transitions.build_split_derivation_protocol().canonical_bytes
        != split_derivation_protocol_bytes
    ):
        raise ProtocolViolation("split derivation protocol failed code-owned rebuild")
    if (
        extension.canonical_bytes != extension_template_set_bytes
        or transitions.build_extension_template_set().canonical_bytes
        != extension_template_set_bytes
    ):
        raise ProtocolViolation("extension template set failed code-owned rebuild")

    parse_producer_source_closure_manifest_bytes(producer_source_closure_manifest_bytes)

    result = (
        FormalScopePredecessor(
            "world_scope_fragment",
            world_scope_fragment_bytes,
            "hex:" + WORLD_SCOPE_FRAGMENT_DOMAIN.hex(),
            world.semantic_digest,
        ),
        FormalScopePredecessor(
            "metric_semantic_registry",
            metric_semantic_registry_bytes,
            "hex:" + METRIC_TARGET_DOMAIN.hex(),
            metric.metric_target_digest,
        ),
        FormalScopePredecessor(
            "task_execution_manifest",
            task_execution_manifest_bytes,
            "hex:" + TASK_EXECUTION_SEMANTIC_DOMAIN.hex(),
            _semantic_digest(
                TASK_EXECUTION_SEMANTIC_DOMAIN, task_execution_manifest_bytes
            ),
        ),
        FormalScopePredecessor(
            "seed_protocol_manifest",
            seed_protocol_manifest_bytes,
            "hex:" + SEED_PROTOCOL_SEMANTIC_DOMAIN.hex(),
            _semantic_digest(
                SEED_PROTOCOL_SEMANTIC_DOMAIN, seed_protocol_manifest_bytes
            ),
        ),
        FormalScopePredecessor(
            "split_derivation_protocol",
            split_derivation_protocol_bytes,
            "hex:" + transitions.SPLIT_DERIVATION_DOMAIN.hex(),
            split.semantic_digest,
        ),
        FormalScopePredecessor(
            "extension_template_set",
            extension_template_set_bytes,
            "hex:" + transitions.EXTENSION_TEMPLATE_SET_DOMAIN.hex(),
            extension.semantic_digest,
        ),
        FormalScopePredecessor(
            "producer_source_closure_manifest",
            producer_source_closure_manifest_bytes,
            "hex:" + SOURCE_CLOSURE_SEMANTIC_DOMAIN.hex(),
            _semantic_digest(
                SOURCE_CLOSURE_SEMANTIC_DOMAIN,
                producer_source_closure_manifest_bytes,
            ),
        ),
    )
    if tuple(record.predecessor_id for record in result) != PREDECESSOR_ORDER:
        raise ProtocolViolation("formal scope predecessor order drifted")
    return result


def _world_gaps(
    *, exclude_metric_registry_owned: bool = False
) -> tuple[FormalScopeGap, ...]:
    report = inspect_world_scope_fragments()
    result: list[FormalScopeGap] = []
    retained = tuple(
        gap
        for gap in report.gaps
        if not (
            exclude_metric_registry_owned
            and gap.code is ScopeGapCode.D_METRIC_TARGET_GAP
        )
    )
    for index, gap in enumerate(retained):
        wire = {
            "scope_level": gap.scope_level.value,
            "world_slot": gap.world_slot,
            "panel_id": gap.panel_id,
            "axis": gap.axis,
            "subject_id": gap.subject_id,
            "code": gap.code.value,
            "detail": gap.detail,
        }
        identity = ":".join(
            (
                gap.scope_level.value,
                gap.world_slot or "global",
                gap.panel_id or "global",
                gap.axis,
                gap.subject_id,
                gap.code.value,
            )
        )
        result.append(_formal_gap("world_scope_fragment", index, identity, wire))
    return tuple(result)


def _metric_gaps(metric_wire: dict[str, Any]) -> tuple[FormalScopeGap, ...]:
    raw: list[dict[str, Any]] = []
    global_gaps = metric_wire["global_target_gaps"]
    if type(global_gaps) is not list:
        raise ProtocolViolation("metric global_target_gaps must be a list")
    raw.extend(global_gaps)
    contracts = metric_wire["measurement_contracts"]
    if type(contracts) is not list:
        raise ProtocolViolation("metric measurement_contracts must be a list")
    for measurement in contracts:
        outputs = measurement["outputs"]
        if type(outputs) is not list:
            raise ProtocolViolation("metric outputs must be a list")
        for output in outputs:
            gap = output["unresolved_target_gap"]
            if gap is not None:
                if type(gap) is not dict:
                    raise ProtocolViolation("metric target gap must be an object")
                raw.append(gap)
    expected = metric_wire["target_gap_count"]
    if type(expected) is not int or expected != len(raw):
        raise ProtocolViolation("metric target gap count is stale")
    return tuple(
        _formal_gap("metric_semantic_registry", index, gap["gap_id"], dict(gap))
        for index, gap in enumerate(raw)
    )


def _transition_gaps(source_id: str, transition: Any) -> tuple[FormalScopeGap, ...]:
    gaps = transition.gaps
    if type(gaps) is not tuple or transition.gap_count != len(gaps):
        raise ProtocolViolation(f"{source_id} gap inventory is stale")
    result: list[FormalScopeGap] = []
    for index, gap in enumerate(gaps):
        wire = gap.to_wire()
        if type(wire) is not dict:
            raise ProtocolViolation(f"{source_id} gap wire must be an object")
        result.append(_formal_gap(source_id, index, gap.gap_id, wire))
    return tuple(result)


def _assert_world_metric_gap_join(metric_wire: dict[str, Any]) -> None:
    """Prove WFS cross-reference coverage without double-counting ownership."""

    world_rows = tuple(
        gap
        for gap in inspect_world_scope_fragments().gaps
        if gap.code is ScopeGapCode.D_METRIC_TARGET_GAP
    )
    metric_rows = _metric_gaps(metric_wire)
    world_projection = tuple(
        (
            gap.subject_id,
            gap.detail,
        )
        for gap in world_rows
    )
    metric_projection = tuple(
        (
            gap.gap_id,
            "metric target registry unresolved dimensions: "
            + ",".join(gap.gap_wire["missing_dimensions"]),
        )
        for gap in metric_rows
    )
    if world_projection != metric_projection:
        raise ProtocolViolation(
            "world/metric semantic gap cross-reference is missing, reordered, or stale"
        )


def _collect_gaps(
    metric: Any, split: Any, extension: Any
) -> tuple[FormalScopeGap, ...]:
    metric_wire = metric.to_wire()
    _assert_world_metric_gap_join(metric_wire)
    return (
        *_world_gaps(exclude_metric_registry_owned=True),
        *_metric_gaps(metric_wire),
        *_transition_gaps("split_derivation_protocol", split),
        *_transition_gaps("extension_template_set", extension),
    )


def _predecessor_root(
    predecessors: tuple[FormalScopePredecessor, ...],
) -> str:
    if tuple(item.predecessor_id for item in predecessors) != PREDECESSOR_ORDER:
        raise ProtocolViolation("formal scope predecessors are reordered")
    return domain_digest(
        PREDECESSOR_ROOT_DOMAIN,
        tuple(item.record_bytes for item in predecessors),
    )


def _closed_scope_manifest(
    world: Any,
    predecessors: tuple[FormalScopePredecessor, ...],
    predecessor_root: str,
    gaps: tuple[FormalScopeGap, ...],
) -> ScopeManifest:
    """Materialize a scope only after every predecessor proves zero gaps."""

    if gaps:
        raise ProtocolViolation("closed scope materialization requires exact zero gaps")

    declarations: dict[str, list[ScopeDeclaration]] = {
        axis_id: [] for axis_id in SCOPE_AXES
    }
    for panel in world.panels:
        axes_wire = panel.axes.to_wire()
        for axis_id in SCOPE_AXES:
            declarations[axis_id].append(
                ScopeDeclaration(
                    f"panel:{panel.world_slot}:{panel.panel_id}",
                    axes_wire[axis_id],
                )
            )

    by_id = {item.predecessor_id: item for item in predecessors}
    global_bindings = {
        "D": ("metric_semantic_registry",),
        "R": (
            "world_scope_fragment",
            "task_execution_manifest",
            "seed_protocol_manifest",
            "split_derivation_protocol",
            "extension_template_set",
            "producer_source_closure_manifest",
        ),
    }
    for axis_id, predecessor_ids in global_bindings.items():
        for predecessor_id in predecessor_ids:
            record = by_id[predecessor_id]
            declarations[axis_id].append(
                ScopeDeclaration(
                    f"global:{predecessor_id}",
                    {
                        "artifact_digest": record.artifact_digest,
                        "domain_semantic_digest": record.domain_semantic_digest,
                        "semantic_domain": record.semantic_domain,
                    },
                )
            )

    axes = {
        axis_id: ScopeAxisDeclarations(
            tuple(
                sorted(
                    declarations[axis_id],
                    key=lambda item: item.declaration_id.encode("utf-8"),
                )
            )
        )
        for axis_id in SCOPE_AXES
    }
    return ScopeManifest(
        benchmark_id=FORMAL_SCOPE_BENCHMARK_ID,
        scope_id="UCM-SCOPE-v1-" + predecessor_root.removeprefix("sha256:"),
        axes=axes,
    )


@dataclass(frozen=True, slots=True)
class FormalScopeBuildReport:
    """Canonical PRE-FREEZE result of joining all formal-scope predecessors."""

    predecessors: tuple[FormalScopePredecessor, ...]
    gaps: tuple[FormalScopeGap, ...]
    scope_manifest_bytes: bytes | None

    def __post_init__(self) -> None:
        if (
            tuple(item.predecessor_id for item in self.predecessors)
            != PREDECESSOR_ORDER
        ):
            raise ProtocolViolation("formal scope report predecessor order is invalid")
        if type(self.gaps) is not tuple or any(
            type(gap) is not FormalScopeGap for gap in self.gaps
        ):
            raise ProtocolViolation("formal scope gaps must be a typed tuple")
        expected_positions: dict[str, int] = {}
        source_ordinals: list[int] = []
        gap_identities: set[tuple[str, str]] = set()
        for gap in self.gaps:
            source_ordinals.append(PREDECESSOR_ORDER.index(gap.source_id))
            expected = expected_positions.get(gap.source_id, 0)
            if gap.source_gap_index != expected:
                raise ProtocolViolation("formal scope source gap order is not exact")
            expected_positions[gap.source_id] = expected + 1
            identity = (gap.source_id, gap.gap_id)
            if identity in gap_identities:
                raise ProtocolViolation("formal scope source gap_ids must be unique")
            gap_identities.add(identity)
        if source_ordinals != sorted(source_ordinals):
            raise ProtocolViolation("formal scope gap source groups are reordered")
        if self.gaps and self.scope_manifest_bytes is not None:
            raise ProtocolViolation("incomplete scope cannot emit ScopeManifest")
        if not self.gaps and self.scope_manifest_bytes is None:
            raise ProtocolViolation("zero-gap scope must emit ScopeManifest")
        if self.scope_manifest_bytes is not None:
            parse_scope_manifest_bytes(self.scope_manifest_bytes)

    @property
    def status(self) -> str:
        return (
            FORMAL_SCOPE_INCOMPLETE_STATUS if self.gaps else FORMAL_SCOPE_CLOSED_STATUS
        )

    @property
    def predecessor_root(self) -> str:
        return _predecessor_root(self.predecessors)

    @property
    def scope_manifest_emitted(self) -> bool:
        return self.scope_manifest_bytes is not None

    @property
    def benchmark_freeze_eligible(self) -> bool:
        return False

    @property
    def freeze_authority(self) -> bool:
        return False

    def _scope_emission_wire(self) -> dict[str, Any] | None:
        if self.scope_manifest_bytes is None:
            return None
        manifest = parse_scope_manifest_bytes(self.scope_manifest_bytes)
        return {
            "canonical_bytes_base64": base64.b64encode(
                self.scope_manifest_bytes
            ).decode("ascii"),
            "canonical_byte_length": len(self.scope_manifest_bytes),
            "manifest_digest": manifest.manifest_digest,
            "scope_digest": manifest.scope_digest,
        }

    def _root_preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": FORMAL_SCOPE_BUILD_REPORT_SCHEMA,
            "benchmark_id": FORMAL_SCOPE_BENCHMARK_ID,
            "status": self.status,
            "scope_manifest_emitted": self.scope_manifest_emitted,
            "benchmark_freeze_eligible": self.benchmark_freeze_eligible,
            "freeze_authority": self.freeze_authority,
            "predecessors": [item.to_wire() for item in self.predecessors],
            "predecessor_root": self.predecessor_root,
            "gap_count": len(self.gaps),
            "gaps": [gap.to_wire() for gap in self.gaps],
            "scope_manifest": self._scope_emission_wire(),
        }

    @property
    def scope_build_root(self) -> str:
        return domain_digest(
            SCOPE_BUILD_ROOT_DOMAIN,
            (canonical_json_bytes(self._root_preimage_wire()),),
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self._root_preimage_wire(), "scope_build_root": self.scope_build_root}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


def produce_formal_scope_build_report(
    world_scope_fragment_bytes: bytes,
    metric_semantic_registry_bytes: bytes,
    task_execution_manifest_bytes: bytes,
    seed_protocol_manifest_bytes: bytes,
    split_derivation_protocol_bytes: bytes,
    extension_template_set_bytes: bytes,
    producer_source_closure_manifest_bytes: bytes,
    /,
) -> FormalScopeBuildReport:
    """Join seven exact predecessors; fail closed while any base gap remains."""

    predecessors = _build_predecessors(
        world_scope_fragment_bytes,
        metric_semantic_registry_bytes,
        task_execution_manifest_bytes,
        seed_protocol_manifest_bytes,
        split_derivation_protocol_bytes,
        extension_template_set_bytes,
        producer_source_closure_manifest_bytes,
    )
    world = parse_world_scope_fragment_set_bytes(world_scope_fragment_bytes)
    metric = parse_metric_target_registry_bytes(metric_semantic_registry_bytes)
    transitions = _transition_module()
    split = transitions.parse_split_derivation_protocol_bytes(
        split_derivation_protocol_bytes
    )
    extension = transitions.parse_extension_template_set_bytes(
        extension_template_set_bytes
    )
    gaps = _collect_gaps(metric, split, extension)
    predecessor_root = _predecessor_root(predecessors)
    manifest_bytes: bytes | None = None
    if not gaps:
        manifest_bytes = _closed_scope_manifest(
            world, predecessors, predecessor_root, gaps
        ).canonical_bytes
    # Close the most important loaded/live TOCTOU window: source closure is
    # rehashed after every semantic parser, gap extractor, and optional scope
    # materializer has run.
    parse_producer_source_closure_manifest_bytes(producer_source_closure_manifest_bytes)
    return FormalScopeBuildReport(predecessors, gaps, manifest_bytes)


def _predecessor_payloads_from_report(body: dict[str, Any]) -> tuple[bytes, ...]:
    rows = body["predecessors"]
    if type(rows) is not list or len(rows) != len(PREDECESSOR_ORDER):
        raise ProtocolViolation("formal scope predecessor list has wrong length")
    payloads: list[bytes] = []
    for index, (row, expected_id) in enumerate(
        zip(rows, PREDECESSOR_ORDER, strict=True)
    ):
        item = _exact_object(
            row, _PREDECESSOR_KEYS, f"formal scope predecessor {index}"
        )
        if item["predecessor_id"] != expected_id:
            raise ProtocolViolation("formal scope predecessor order is invalid")
        payload = _decode_base64(
            item["canonical_bytes_base64"],
            f"formal scope predecessor {index} bytes",
        )
        if item["canonical_byte_length"] != len(payload):
            raise ProtocolViolation("formal scope predecessor byte length is stale")
        if item["artifact_digest"] != digest_bytes(payload):
            raise ProtocolViolation("formal scope predecessor artifact digest is stale")
        payloads.append(payload)
    return tuple(payloads)


def parse_formal_scope_build_report_bytes(payload: bytes) -> FormalScopeBuildReport:
    """Parse a report by replaying all seven code-owned predecessor parsers."""

    body = _exact_object(
        _decode_exact_canonical_object(payload, "formal scope build report"),
        _REPORT_KEYS,
        "formal scope build report",
    )
    predecessor_payloads = _predecessor_payloads_from_report(body)
    rebuilt = produce_formal_scope_build_report(*predecessor_payloads)
    if rebuilt.canonical_bytes != payload:
        raise ProtocolViolation(
            "formal scope build report contradicts code-owned rebuild"
        )
    return rebuilt


__all__ = [
    "FORMAL_SCOPE_BENCHMARK_ID",
    "FORMAL_SCOPE_BUILD_REPORT_SCHEMA",
    "FORMAL_SCOPE_CLOSED_STATUS",
    "FORMAL_SCOPE_INCOMPLETE_STATUS",
    "FORMAL_SCOPE_SOURCE_CLOSURE_SCHEMA",
    "FormalScopeBuildReport",
    "FormalScopeGap",
    "FormalScopePredecessor",
    "PREDECESSOR_ORDER",
    "PREDECESSOR_ROOT_DOMAIN",
    "SCOPE_BUILD_ROOT_DOMAIN",
    "build_code_owned_producer_source_closure_manifest_bytes",
    "parse_formal_scope_build_report_bytes",
    "parse_producer_source_closure_manifest_bytes",
    "produce_formal_scope_build_report",
    "producer_source_closure_artifact_digest_from_bytes",
    "producer_source_closure_semantic_digest_from_bytes",
]
