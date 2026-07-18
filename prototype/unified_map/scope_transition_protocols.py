"""Scope-independent PRE-FREEZE split and extension transition protocols.

These artifacts describe *how* later scope-bound artifacts must be derived.
They intentionally contain no benchmark scope digest, runtime
assignment/partition, runtime raw seed or commitment value, primary seal,
revealed extension pack, expanded scope digest, or freeze authorization.  A
synthetic literal known-answer vector is embedded only to make the algorithm
executable and drift-detecting.  Exact code-owned predecessor bytes and live
source fingerprints make these auditable protocol inputs, not authority to
freeze a benchmark.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import hmac
import inspect
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    domain_digest,
    validate_json_like,
)
from . import canonical as _canonical_module
from . import extensions as _extensions_module
from . import metric_configuration as _metric_configuration_module
from . import metric_runtime_bindings as _metric_runtime_bindings_module
from . import panel_split_authority as _panel_split_authority_module
from . import scope_manifest as _scope_manifest_module
from . import seed_protocol as _seed_protocol_module
from . import world_registry as _world_registry_module
from .extensions import (
    COMMIT_PROTOCOL,
    FIRST_QUERY_PROTOCOL,
    MIGRATION_PROTOCOL,
    PRIMARY_SEAL_PROTOCOL,
    REVEAL_PROTOCOL,
)
from .metric_configuration import (
    METRIC_TARGET_DOMAIN,
    benchmark_v1_metric_target_registry,
    parse_metric_target_registry_bytes,
)
from .metric_runtime_bindings import (
    ARTIFACT_DOMAIN as METRIC_RUNTIME_ARTIFACT_DOMAIN,
    benchmark_v1_metric_runtime_bindings,
    parse_metric_runtime_bindings_bytes,
)
from .panel_split_authority import (
    CODE_OWNED_ZIPPED_SEED_PAIRING_CONTEXT,
    EXPECTED_PANEL_TASK_KEYS,
    FAMILY_DEFINITION_PROTOCOL,
    GENERATOR_INTENT_PROTOCOL,
    INTENT_POLICY_PROTOCOL,
    PANEL_COUNT,
    PARTITIONS_PER_AUTHORITY,
    SPLIT_POLICY_PROTOCOL,
    SPLIT_SEED_CONTEXT_PROTOCOL,
    TASK_COUNT,
    ZIPPED_SHARD_SLOTS_PER_PARTITION,
    AuthoritySplit,
    FamilyDefinitionIntent,
    FamilyIntentPolicy,
    GeneratorIntent,
    PanelPhysicalIdentity,
    SplitNeutralFamilyUnitIntent,
    SplitPolicyContext,
    SplitSeedCommitmentContext,
)
from .seed_protocol import (
    SEED_PROTOCOL_DIGEST,
    SEED_PROTOCOL_MANIFEST_BYTES,
    ZIPPED_REPLICATE_IDS,
)
from .scope_manifest import (
    SCOPE_AXES,
    SCOPE_DOMAIN,
    SCOPE_MANIFEST_SCHEMA,
    ScopeAxisDeclarations,
    ScopeDeclaration,
    ScopeManifest,
    parse_scope_manifest_bytes,
)
from .world_registry import EXTENSION_WORLD_REGISTRY, WORLD_REGISTRY


SPLIT_DERIVATION_PROTOCOL_SCHEMA = "ucm-scope-independent-split-derivation/1"
EXTENSION_TEMPLATE_SET_SCHEMA = "ucm-scope-independent-extension-template-set/1"
EXTENSION_TEMPLATE_SCHEMA = "ucm-scope-independent-extension-template/1"
PROTOCOL_GAP_SCHEMA = "ucm-pre-freeze-protocol-gap/1"
EXACT_BYTE_PREIMAGE_SCHEMA = "ucm-exact-byte-preimage/1"
SOURCE_CLOSURE_SCHEMA = "ucm-protocol-source-closure/1"
POST_SCOPE_REQUIREMENT_SCHEMA = "ucm-post-scope-requirement/1"
SUCCESSOR_BLOCKER_SCHEMA = "ucm-successor-runtime-blocker/1"
ACTUAL_SCOPE_DIFF_SCHEMA = "ucm-actual-scope-diff/2"
SUCCESSOR_RECEIPT_SCHEMA = "ucm-successor-scope-receipt/2"
EXTENSION_TRANSITION_SEAL_SCHEMA = "ucm-extension-transition-seal/1"
EXTENSION_SCOPE_REVEAL_SCHEMA = "ucm-extension-scope-reveal/1"
EXTENSION_SCOPE_REQUEST_SCHEMA = "ucm-extension-scope-request/1"
EXTENSION_SCOPE_TRANSCRIPT_SCHEMA = "ucm-extension-scope-transcript/1"
DISTANCE_DERIVATION_SCHEMA = "ucm-extension-distance-derivation/1"
EXTENSION_SCOPE_SPEC_SCHEMA = "ucm-extension-scope-spec/1"
EXTENSION_FIRST_QUERY_SCHEMA = "ucm-extension-first-query-envelope/1"
EXTENSION_FIRST_RESULT_SCHEMA = "ucm-extension-first-result-envelope/1"

SPLIT_DERIVATION_DOMAIN = b"UCM\0SCOPE_INDEPENDENT_SPLIT_DERIVATION_V1\0"
EXTENSION_TEMPLATE_SET_DOMAIN = b"UCM\0SCOPE_INDEPENDENT_EXTENSION_SET_V1\0"
SOURCE_CLOSURE_DOMAIN = b"UCM\0PROTOCOL_SOURCE_CLOSURE_V1\0"
SPLIT_SEED_COMMITMENT_DOMAIN = b"UCM\0SPLIT_SEED_COMMITMENT_V1\0"
SPLIT_GROUP_PRIORITY_DOMAIN = b"UCM\0SPLIT_GROUP_PRIORITY_V1\0"
SPLIT_ASSIGNMENT_ROOT_DOMAIN = b"UCM\0SPLIT_ASSIGNMENT_ROOT_V1\0"
ACTUAL_SCOPE_DIFF_DOMAIN = b"UCM\0ACTUAL_SCOPE_DIFF_V2\0"
EXTENSION_TRANSITION_SEAL_DOMAIN = b"UCM\0EXTENSION_TRANSITION_SEAL_V1\0"
EXTENSION_SCOPE_COMMITMENT_DOMAIN = b"UCM\0EXTENSION_SCOPE_COMMITMENT_V1\0"
EXTENSION_SCOPE_REVEAL_DOMAIN = b"UCM\0EXTENSION_SCOPE_REVEAL_V1\0"
EXTENSION_SCOPE_REQUEST_DOMAIN = b"UCM\0EXTENSION_SCOPE_REQUEST_V1\0"
EXTENSION_SCOPE_TRANSCRIPT_DOMAIN = b"UCM\0EXTENSION_SCOPE_TRANSCRIPT_V1\0"
SUCCESSOR_RECEIPT_DOMAIN = b"UCM\0SUCCESSOR_SCOPE_RECEIPT_V2\0"
DISTANCE_DERIVATION_DOMAIN = b"UCM\0EXTENSION_DISTANCE_DERIVATION_V1\0"
EXTENSION_SCOPE_SPEC_DOMAIN = b"UCM\0EXTENSION_SCOPE_SPEC_V1\0"
EXTENSION_FIRST_QUERY_DOMAIN = b"UCM\0EXTENSION_FIRST_QUERY_ENVELOPE_V1\0"
EXTENSION_FIRST_RESULT_DOMAIN = b"UCM\0EXTENSION_FIRST_RESULT_ENVELOPE_V1\0"
PRIMARY_STATE_SET_DOMAIN = b"UCM\0EXTENSION_PRIMARY_STATE_SET_V1\0"

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_QUERY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_FINAL_WRAPPED_ENTRYPOINT_NAMES = frozenset(
    {
        "build_actual_scope_diff",
        "build_extension_template_set",
        "build_split_derivation_protocol",
        "compute_extension_scope_commitment",
        "compute_split_seed_commitment",
        "derive_panel_family_assignments",
        "derive_panel_split_seed",
        "derive_successor_distance_axis",
        "derive_successor_scope_from_spec",
        "distance_derivation_contract_bytes",
        "distance_derivation_contract_digest",
        "extension_template_set_artifact_digest_from_bytes",
        "extension_template_set_semantic_digest_from_bytes",
        "parse_actual_scope_diff_bytes",
        "parse_extension_first_query_bytes",
        "parse_extension_first_result_bytes",
        "parse_extension_scope_spec_bytes",
        "parse_extension_template_set_bytes",
        "parse_split_derivation_protocol_bytes",
        "parse_successor_receipt_bytes",
        "split_derivation_artifact_digest_from_bytes",
        "split_derivation_known_answer",
        "split_derivation_semantic_digest_from_bytes",
        "verify_panel_family_assignments",
        "verify_successor_distance_axis",
    }
)
_SPLIT_KDF_SALT_DOMAIN = b"UCM\0SPLIT_SEED_HKDF_SALT_V1\0"
_SPLIT_KDF_INFO = b"UCM\0SPLIT_SEED_HKDF_INFO_V1\0"
_SPLIT_KNOWN_SEED = bytes(range(32))
_SPLIT_KNOWN_NONCE = bytes(range(32, 64))
_SPLIT_KNOWN_ANSWER_EXPECTED = {
    "protocol": "ucm-executable-split-assignment/1",
    "commitment": "sha256:d5855469bcaa6461edb534ad30cfca683933e34f5c0f846f7b34d877543683a7",
    "commitment_context_digest": "sha256:f11e9dcd1f5967d438fe525d145fb02fe90efd886f58c23a7043e772987af38c",
    "panel_identity_digest": "sha256:0bddc7b7ed9906e41a0a33a0833ab1de8da7fb70c95016e205e54655b99bf4c9",
    "panel_seed_digest": "sha256:e1ad929a71b06676b43d0a921811a7ff5239963324386de2cd3f7923736b835f",
    "input_set_root": "sha256:1e74941249c2e41ff18a7506cfce672e5eaf25b178a59068c265be233ac6ae79",
    "assignments": [
        {
            "unit_intent_digest": "sha256:01b106845337d9607efcfb589f288e70314f063f692b533b916d6a61ff027e92",
            "split": "validation",
        },
        {
            "unit_intent_digest": "sha256:12522e33645147c67f0f8d2d6d374d1824be017d1a8916d21df807ec7c78d026",
            "split": "test",
        },
        {
            "unit_intent_digest": "sha256:15ea9dc6c8fcdfda9d23edcc4d2f713d7a13b10b0aef1a71267dfee74b14c492",
            "split": "train",
        },
        {
            "unit_intent_digest": "sha256:6ed4b5afaf9d4c30defb0f2923b6b9ac9501a01559b00dd08c8eadb6c37e85d3",
            "split": "train",
        },
        {
            "unit_intent_digest": "sha256:fa1558e984adb059d227135e64305f8c680e9b12c6080bee98d834d1061b4501",
            "split": "validation",
        },
    ],
    "assignment_root": "sha256:92a3d28bd4cef2837d36b216e56b26e81edadd2f5e74bb3b6cf1c40fe47cec5c",
}

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PROTOCOL_TRANSITIVE_SOURCE_PATHS = (
    "prototype/__init__.py",
    "prototype/contract.py",
    "prototype/unified_map/__init__.py",
    "prototype/unified_map/candidate_protocol.py",
    "prototype/unified_map/canonical.py",
    "prototype/unified_map/evaluator.py",
    "prototype/unified_map/extensions.py",
    "prototype/unified_map/family_manifest.py",
    "prototype/unified_map/metric_configuration.py",
    "prototype/unified_map/metric_runtime_bindings.py",
    "prototype/unified_map/metrics.py",
    "prototype/unified_map/metrics_diagnosis_forecast.py",
    "prototype/unified_map/metrics_intervention_regret.py",
    "prototype/unified_map/metrics_m09_m11.py",
    "prototype/unified_map/metrics_state_resource_stability.py",
    "prototype/unified_map/metrics_update_transfer.py",
    "prototype/unified_map/panel_split_authority.py",
    "prototype/unified_map/pre_freeze_metrics_m05_m08.py",
    "prototype/unified_map/schema.py",
    "prototype/unified_map/scope_manifest.py",
    "prototype/unified_map/scope_transition_protocols.py",
    "prototype/unified_map/seed_protocol.py",
    "prototype/unified_map/state.py",
    "prototype/unified_map/strata_manifest.py",
    "prototype/unified_map/world_registry.py",
    "prototype/unified_map/worlds/__init__.py",
    "prototype/unified_map/worlds/base.py",
    "prototype/unified_map/worlds/randomness.py",
    "prototype/unified_map/worlds/w01.py",
    "prototype/unified_map/worlds/w02.py",
    "prototype/unified_map/worlds/w03.py",
    "prototype/unified_map/worlds/w04.py",
    "prototype/unified_map/worlds/w05.py",
    "prototype/unified_map/worlds/w06.py",
    "prototype/unified_map/worlds/w07.py",
    "prototype/unified_map/worlds/w08.py",
    "prototype/unified_map/worlds/w09.py",
    "prototype/unified_map/worlds/w10.py",
    "prototype/unified_map/worlds/w11.py",
    "prototype/unified_map/worlds/w12.py",
    "prototype/unified_map/worlds/w13.py",
    "prototype/unified_map/worlds/w14.py",
    "prototype/unified_map/worlds/w15.py",
    "prototype/unified_map/worlds/w16.py",
    "prototype/unified_map/worlds/w17.py",
    "prototype/unified_map/worlds/w18.py",
    "prototype/unified_map/worlds/w19.py",
    "prototype/unified_map/worlds/w20.py",
)
_SPLIT_SOURCE_PATHS = _PROTOCOL_TRANSITIVE_SOURCE_PATHS
_EXTENSION_SOURCE_PATHS = _PROTOCOL_TRANSITIVE_SOURCE_PATHS
_DISTANCE_SOURCE_PATHS = _PROTOCOL_TRANSITIVE_SOURCE_PATHS

_COMMON_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "benchmark_status",
        "authority_claim",
        "scope_binding_status",
        "freeze_authority_status",
        "protocol",
        "gap_count",
        "gaps",
    }
)
_SPLIT_TOP_LEVEL_KEYS = _COMMON_TOP_LEVEL_KEYS | frozenset(
    {"post_scope_requirement_count", "post_scope_requirements"}
)
_EXTENSION_TOP_LEVEL_KEYS = _COMMON_TOP_LEVEL_KEYS | frozenset(
    {"successor_blocker_count", "successor_blockers"}
)
_GAP_KEYS = frozenset({"schema_version", "gap_id", "detail"})
_FOLLOWUP_KEYS = frozenset(
    {"schema_version", "requirement_id", "stage", "detail", "blocks_base_scope"}
)
_PREIMAGE_KEYS = frozenset(
    {"schema_version", "label", "encoding", "byte_count", "digest", "payload_b64"}
)


def _read_source_bytes(relative_path: str) -> bytes:
    try:
        return (_REPOSITORY_ROOT / relative_path).read_bytes()
    except OSError as exc:
        raise ProtocolViolation(
            f"protocol source is unavailable: {relative_path}"
        ) from exc


_ALL_SOURCE_PATHS = tuple(
    dict.fromkeys(
        _SPLIT_SOURCE_PATHS + _EXTENSION_SOURCE_PATHS + _DISTANCE_SOURCE_PATHS
    )
)
_IMPORTED_SOURCE_BYTES = MappingProxyType(
    {
        relative_path: _read_source_bytes(relative_path)
        for relative_path in _ALL_SOURCE_PATHS
    }
)
_CODE_OWNED_SPLIT_SOURCE_PATHS = _SPLIT_SOURCE_PATHS
_CODE_OWNED_EXTENSION_SOURCE_PATHS = _EXTENSION_SOURCE_PATHS
_CODE_OWNED_DISTANCE_SOURCE_PATHS = _DISTANCE_SOURCE_PATHS
_CODE_OWNED_IMPORTED_SOURCE_DIGESTS = MappingProxyType(
    {path: digest_bytes(payload) for path, payload in _IMPORTED_SOURCE_BYTES.items()}
)
_CODE_OWNED_PROTOCOL_CONSTANTS = MappingProxyType(
    {
        "SPLIT_DERIVATION_PROTOCOL_SCHEMA": SPLIT_DERIVATION_PROTOCOL_SCHEMA,
        "EXTENSION_TEMPLATE_SET_SCHEMA": EXTENSION_TEMPLATE_SET_SCHEMA,
        "EXTENSION_TEMPLATE_SCHEMA": EXTENSION_TEMPLATE_SCHEMA,
        "PROTOCOL_GAP_SCHEMA": PROTOCOL_GAP_SCHEMA,
        "EXACT_BYTE_PREIMAGE_SCHEMA": EXACT_BYTE_PREIMAGE_SCHEMA,
        "SOURCE_CLOSURE_SCHEMA": SOURCE_CLOSURE_SCHEMA,
        "POST_SCOPE_REQUIREMENT_SCHEMA": POST_SCOPE_REQUIREMENT_SCHEMA,
        "SUCCESSOR_BLOCKER_SCHEMA": SUCCESSOR_BLOCKER_SCHEMA,
        "ACTUAL_SCOPE_DIFF_SCHEMA": ACTUAL_SCOPE_DIFF_SCHEMA,
        "SUCCESSOR_RECEIPT_SCHEMA": SUCCESSOR_RECEIPT_SCHEMA,
        "EXTENSION_TRANSITION_SEAL_SCHEMA": EXTENSION_TRANSITION_SEAL_SCHEMA,
        "EXTENSION_SCOPE_REVEAL_SCHEMA": EXTENSION_SCOPE_REVEAL_SCHEMA,
        "EXTENSION_SCOPE_REQUEST_SCHEMA": EXTENSION_SCOPE_REQUEST_SCHEMA,
        "EXTENSION_SCOPE_TRANSCRIPT_SCHEMA": EXTENSION_SCOPE_TRANSCRIPT_SCHEMA,
        "EXTENSION_SCOPE_SPEC_SCHEMA": EXTENSION_SCOPE_SPEC_SCHEMA,
        "EXTENSION_FIRST_QUERY_SCHEMA": EXTENSION_FIRST_QUERY_SCHEMA,
        "EXTENSION_FIRST_RESULT_SCHEMA": EXTENSION_FIRST_RESULT_SCHEMA,
        "DISTANCE_DERIVATION_SCHEMA": DISTANCE_DERIVATION_SCHEMA,
        "SPLIT_DERIVATION_DOMAIN": SPLIT_DERIVATION_DOMAIN,
        "EXTENSION_TEMPLATE_SET_DOMAIN": EXTENSION_TEMPLATE_SET_DOMAIN,
        "SOURCE_CLOSURE_DOMAIN": SOURCE_CLOSURE_DOMAIN,
        "SPLIT_SEED_COMMITMENT_DOMAIN": SPLIT_SEED_COMMITMENT_DOMAIN,
        "SPLIT_GROUP_PRIORITY_DOMAIN": SPLIT_GROUP_PRIORITY_DOMAIN,
        "SPLIT_ASSIGNMENT_ROOT_DOMAIN": SPLIT_ASSIGNMENT_ROOT_DOMAIN,
        "ACTUAL_SCOPE_DIFF_DOMAIN": ACTUAL_SCOPE_DIFF_DOMAIN,
        "EXTENSION_TRANSITION_SEAL_DOMAIN": EXTENSION_TRANSITION_SEAL_DOMAIN,
        "EXTENSION_SCOPE_COMMITMENT_DOMAIN": EXTENSION_SCOPE_COMMITMENT_DOMAIN,
        "EXTENSION_SCOPE_REVEAL_DOMAIN": EXTENSION_SCOPE_REVEAL_DOMAIN,
        "EXTENSION_SCOPE_REQUEST_DOMAIN": EXTENSION_SCOPE_REQUEST_DOMAIN,
        "EXTENSION_SCOPE_TRANSCRIPT_DOMAIN": EXTENSION_SCOPE_TRANSCRIPT_DOMAIN,
        "SUCCESSOR_RECEIPT_DOMAIN": SUCCESSOR_RECEIPT_DOMAIN,
        "DISTANCE_DERIVATION_DOMAIN": DISTANCE_DERIVATION_DOMAIN,
        "EXTENSION_SCOPE_SPEC_DOMAIN": EXTENSION_SCOPE_SPEC_DOMAIN,
        "EXTENSION_FIRST_QUERY_DOMAIN": EXTENSION_FIRST_QUERY_DOMAIN,
        "EXTENSION_FIRST_RESULT_DOMAIN": EXTENSION_FIRST_RESULT_DOMAIN,
        "PRIMARY_STATE_SET_DOMAIN": PRIMARY_STATE_SET_DOMAIN,
        "_SPLIT_KDF_SALT_DOMAIN": _SPLIT_KDF_SALT_DOMAIN,
        "_SPLIT_KDF_INFO": _SPLIT_KDF_INFO,
        "COMMIT_PROTOCOL": COMMIT_PROTOCOL,
        "FIRST_QUERY_PROTOCOL": FIRST_QUERY_PROTOCOL,
        "MIGRATION_PROTOCOL": MIGRATION_PROTOCOL,
        "PRIMARY_SEAL_PROTOCOL": PRIMARY_SEAL_PROTOCOL,
        "REVEAL_PROTOCOL": REVEAL_PROTOCOL,
        "SCOPE_DOMAIN": SCOPE_DOMAIN,
        "SCOPE_AXES": SCOPE_AXES,
        "SCOPE_MANIFEST_SCHEMA": SCOPE_MANIFEST_SCHEMA,
        "METRIC_TARGET_DOMAIN": METRIC_TARGET_DOMAIN,
        "METRIC_RUNTIME_ARTIFACT_DOMAIN": METRIC_RUNTIME_ARTIFACT_DOMAIN,
        "_DIGEST_RE": _DIGEST_RE,
        "_QUERY_ID_RE": _QUERY_ID_RE,
        "_FINAL_WRAPPED_ENTRYPOINT_NAMES": _FINAL_WRAPPED_ENTRYPOINT_NAMES,
        "_REPOSITORY_ROOT": _REPOSITORY_ROOT,
        "_PROTOCOL_TRANSITIVE_SOURCE_PATHS": _PROTOCOL_TRANSITIVE_SOURCE_PATHS,
        "_ALL_SOURCE_PATHS": _ALL_SOURCE_PATHS,
        "_COMMON_TOP_LEVEL_KEYS": _COMMON_TOP_LEVEL_KEYS,
        "_SPLIT_TOP_LEVEL_KEYS": _SPLIT_TOP_LEVEL_KEYS,
        "_EXTENSION_TOP_LEVEL_KEYS": _EXTENSION_TOP_LEVEL_KEYS,
        "_GAP_KEYS": _GAP_KEYS,
        "_FOLLOWUP_KEYS": _FOLLOWUP_KEYS,
        "_PREIMAGE_KEYS": _PREIMAGE_KEYS,
    }
)


class _FinalArtifactCache:
    __slots__ = (
        "_sealed",
        "_split_bytes",
        "_split_artifact_digest",
        "_split_semantic_digest",
        "_extension_bytes",
        "_extension_artifact_digest",
        "_extension_semantic_digest",
    )

    def __init__(self) -> None:
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "_split_bytes", None)
        object.__setattr__(self, "_split_artifact_digest", None)
        object.__setattr__(self, "_split_semantic_digest", None)
        object.__setattr__(self, "_extension_bytes", None)
        object.__setattr__(self, "_extension_artifact_digest", None)
        object.__setattr__(self, "_extension_semantic_digest", None)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise ProtocolViolation("final artifact cache is immutable")

    @property
    def sealed(self) -> bool:
        return self._sealed

    @property
    def split_bytes(self) -> bytes | None:
        return self._split_bytes

    @property
    def extension_bytes(self) -> bytes | None:
        return self._extension_bytes

    def seal(
        self,
        split_bytes: bytes,
        split_artifact_digest: str,
        split_semantic_digest: str,
        extension_bytes: bytes,
        extension_artifact_digest: str,
        extension_semantic_digest: str,
    ) -> None:
        if self._sealed:
            raise ProtocolViolation("final artifact cache was already sealed")
        if (
            type(split_bytes) is not bytes
            or type(extension_bytes) is not bytes
            or split_artifact_digest != digest_bytes(split_bytes)
            or split_semantic_digest
            != domain_digest(SPLIT_DERIVATION_DOMAIN, (split_bytes,))
            or extension_artifact_digest != digest_bytes(extension_bytes)
            or extension_semantic_digest
            != domain_digest(EXTENSION_TEMPLATE_SET_DOMAIN, (extension_bytes,))
        ):
            raise ProtocolViolation("final artifact cache inputs are inconsistent")
        object.__setattr__(self, "_split_bytes", split_bytes)
        object.__setattr__(self, "_split_artifact_digest", split_artifact_digest)
        object.__setattr__(self, "_split_semantic_digest", split_semantic_digest)
        object.__setattr__(self, "_extension_bytes", extension_bytes)
        object.__setattr__(
            self, "_extension_artifact_digest", extension_artifact_digest
        )
        object.__setattr__(
            self, "_extension_semantic_digest", extension_semantic_digest
        )
        object.__setattr__(self, "_sealed", True)

    def validate_live_globals(self, namespace: dict[str, Any]) -> None:
        if not self._sealed:
            return
        if (
            namespace.get("SPLIT_DERIVATION_PROTOCOL_BYTES") is not self._split_bytes
            or namespace.get("SPLIT_DERIVATION_ARTIFACT_DIGEST")
            != self._split_artifact_digest
            or namespace.get("SPLIT_DERIVATION_SEMANTIC_DIGEST")
            != self._split_semantic_digest
            or namespace.get("EXTENSION_TEMPLATE_SET_BYTES")
            is not self._extension_bytes
            or namespace.get("EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST")
            != self._extension_artifact_digest
            or namespace.get("EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST")
            != self._extension_semantic_digest
            or digest_bytes(self._split_bytes) != self._split_artifact_digest
            or domain_digest(SPLIT_DERIVATION_DOMAIN, (self._split_bytes,))
            != self._split_semantic_digest
            or digest_bytes(self._extension_bytes) != self._extension_artifact_digest
            or domain_digest(EXTENSION_TEMPLATE_SET_DOMAIN, (self._extension_bytes,))
            != self._extension_semantic_digest
        ):
            raise ProtocolViolation("final artifact cache/global control plane drifted")


_FINAL_ARTIFACT_CACHE = _FinalArtifactCache()


def _validate_protocol_control_plane(
    expected_split_paths: tuple[str, ...] = _SPLIT_SOURCE_PATHS,
    expected_extension_paths: tuple[str, ...] = _EXTENSION_SOURCE_PATHS,
    expected_distance_paths: tuple[str, ...] = _DISTANCE_SOURCE_PATHS,
    expected_imported_map: MappingProxyType = _IMPORTED_SOURCE_BYTES,
    expected_source_digests: tuple[tuple[str, str], ...] = tuple(
        _CODE_OWNED_IMPORTED_SOURCE_DIGESTS.items()
    ),
    expected_protocol_constants: tuple[tuple[str, object], ...] = tuple(
        _CODE_OWNED_PROTOCOL_CONSTANTS.items()
    ),
) -> None:
    if (
        _SPLIT_SOURCE_PATHS != expected_split_paths
        or _EXTENSION_SOURCE_PATHS != expected_extension_paths
        or _DISTANCE_SOURCE_PATHS != expected_distance_paths
    ):
        raise ProtocolViolation("protocol source-path control plane drifted")
    if (
        _IMPORTED_SOURCE_BYTES is not expected_imported_map
        or type(_IMPORTED_SOURCE_BYTES) is not MappingProxyType
    ):
        raise ProtocolViolation("imported protocol source map is not immutable")
    expected_digest_map = dict(expected_source_digests)
    if frozenset(_IMPORTED_SOURCE_BYTES) != frozenset(expected_digest_map):
        raise ProtocolViolation("imported protocol source inventory drifted")
    for path, expected_digest in expected_source_digests:
        if digest_bytes(_IMPORTED_SOURCE_BYTES[path]) != expected_digest:
            raise ProtocolViolation("imported protocol source bytes drifted")
    for name, expected in expected_protocol_constants:
        if globals().get(name) != expected:
            raise ProtocolViolation(f"protocol constant control plane drifted: {name}")


def _validate_live_extension_protocol_constants(
    expected_items: tuple[tuple[str, str], ...] = (
        ("COMMIT_PROTOCOL", COMMIT_PROTOCOL),
        ("FIRST_QUERY_PROTOCOL", FIRST_QUERY_PROTOCOL),
        ("MIGRATION_PROTOCOL", MIGRATION_PROTOCOL),
        ("PRIMARY_SEAL_PROTOCOL", PRIMARY_SEAL_PROTOCOL),
        ("REVEAL_PROTOCOL", REVEAL_PROTOCOL),
    ),
) -> None:
    from . import extensions as live

    _validate_protocol_control_plane()
    for name, expected_value in expected_items:
        if getattr(live, name, None) != expected_value:
            raise ProtocolViolation(
                f"live extensions protocol constant drifted after import: {name}"
            )


def _exact_object(
    value: object, expected: frozenset[str], label: str
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    validate_json_like(value, path=label)
    actual = frozenset(value)
    if actual != expected:
        raise ProtocolViolation(
            f"{label} keys mismatch: missing={sorted(expected - actual)!r}, "
            f"extra={sorted(actual - expected)!r}"
        )
    return value


def _decode_canonical_object(payload: object, label: str) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation(f"{label} must be exact bytes")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
    except ProtocolViolation:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ProtocolViolation(f"{label} is not strict canonical JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must encode an exact object")
    validate_json_like(value, path=label)
    if canonical_json_bytes(value) != payload:
        raise ProtocolViolation(f"{label} must be canonical JSON plus one LF")
    return value


def _exact_byte_preimage(label: str, payload: bytes) -> dict[str, Any]:
    if type(label) is not str or not label:
        raise ProtocolViolation("preimage label must be a non-empty exact string")
    if type(payload) is not bytes:
        raise ProtocolViolation("preimage payload must be exact bytes")
    return {
        "schema_version": EXACT_BYTE_PREIMAGE_SCHEMA,
        "label": label,
        "encoding": "base64",
        "byte_count": len(payload),
        "digest": digest_bytes(payload),
        "payload_b64": base64.b64encode(payload).decode("ascii"),
    }


def _decode_exact_byte_preimage(value: object, label: str) -> bytes:
    row = _exact_object(value, _PREIMAGE_KEYS, label)
    if (
        row["schema_version"] != EXACT_BYTE_PREIMAGE_SCHEMA
        or row["encoding"] != "base64"
        or type(row["label"]) is not str
        or not row["label"]
        or type(row["payload_b64"]) is not str
        or type(row["byte_count"]) is not int
        or type(row["digest"]) is not str
    ):
        raise ProtocolViolation(f"{label} exact-byte metadata is invalid")
    try:
        payload = base64.b64decode(row["payload_b64"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolViolation(f"{label} payload_b64 is not strict base64") from exc
    if base64.b64encode(payload).decode("ascii") != row["payload_b64"]:
        raise ProtocolViolation(f"{label} base64 is not canonical")
    if row["byte_count"] != len(payload) or row["digest"] != digest_bytes(payload):
        raise ProtocolViolation(f"{label} exact-byte length/digest mismatch")
    return payload


def _source_closure(relative_paths: tuple[str, ...]) -> dict[str, Any]:
    _validate_protocol_control_plane()
    if not relative_paths or relative_paths != tuple(sorted(set(relative_paths))):
        raise ProtocolViolation("source closure paths must be unique canonical order")
    _validate_live_source_inventory(relative_paths)
    members: list[dict[str, Any]] = []
    for relative_path in relative_paths:
        live = _IMPORTED_SOURCE_BYTES[relative_path]
        members.append(
            {
                "relative_path": relative_path,
                "byte_count": len(live),
                "digest": digest_bytes(live),
                "encoding": "base64",
                "payload_b64": base64.b64encode(live).decode("ascii"),
                "embedded_bytes_match_import_and_live": True,
            }
        )
    member_bytes = canonical_json_bytes(
        {"schema_version": SOURCE_CLOSURE_SCHEMA, "members": members}
    )
    return {
        "schema_version": SOURCE_CLOSURE_SCHEMA,
        "members": members,
        "member_count": len(members),
        "closure_root": domain_digest(SOURCE_CLOSURE_DOMAIN, (member_bytes,)),
        "exact_live_bytes_bound_by_digest": True,
        "raw_source_bytes_embedded": True,
        "self_contained_replay": True,
    }


def _validate_live_source_inventory(relative_paths: tuple[str, ...]) -> None:
    if type(relative_paths) is not tuple:
        raise ProtocolViolation("source inventory must be an exact tuple")
    for relative_path in relative_paths:
        imported = _IMPORTED_SOURCE_BYTES.get(relative_path)
        if imported is None:
            raise ProtocolViolation(
                f"source was not captured at import: {relative_path}"
            )
        if _read_source_bytes(relative_path) != imported:
            raise ProtocolViolation(
                f"protocol source changed after import: {relative_path}"
            )


def _validate_source_closure(value: object, label: str) -> None:
    expected_keys = {
        "schema_version",
        "members",
        "member_count",
        "closure_root",
        "exact_live_bytes_bound_by_digest",
        "raw_source_bytes_embedded",
        "self_contained_replay",
    }
    if (
        type(value) is not dict
        or set(value) != expected_keys
        or type(value.get("members")) is not list
    ):
        raise ProtocolViolation(f"{label} source closure must be typed")
    if (
        value["schema_version"] != SOURCE_CLOSURE_SCHEMA
        or type(value["member_count"]) is not int
        or value["member_count"] != len(value["members"])
        or value["exact_live_bytes_bound_by_digest"] is not True
        or value["raw_source_bytes_embedded"] is not True
        or value["self_contained_replay"] is not True
    ):
        raise ProtocolViolation(f"{label} source closure metadata mismatch")
    relative_paths: list[str] = []
    for member in value["members"]:
        if type(member) is not dict or set(member) != {
            "relative_path",
            "byte_count",
            "digest",
            "encoding",
            "payload_b64",
            "embedded_bytes_match_import_and_live",
        }:
            raise ProtocolViolation(f"{label} source member shape mismatch")
        if (
            type(member["relative_path"]) is not str
            or not member["relative_path"]
            or type(member["byte_count"]) is not int
            or type(member["digest"]) is not str
            or member["encoding"] != "base64"
            or type(member["payload_b64"]) is not str
        ):
            raise ProtocolViolation(f"{label} source member encoding mismatch")
        relative_paths.append(member["relative_path"])
        try:
            payload = base64.b64decode(member["payload_b64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProtocolViolation(f"{label} source member base64 invalid") from exc
        if (
            base64.b64encode(payload).decode("ascii") != member["payload_b64"]
            or len(payload) != member["byte_count"]
            or digest_bytes(payload) != member["digest"]
            or member["embedded_bytes_match_import_and_live"] is not True
        ):
            raise ProtocolViolation(f"{label} source member exact bytes mismatch")
    if relative_paths != sorted(set(relative_paths)):
        raise ProtocolViolation(f"{label} source member paths are not canonical")
    member_bytes = canonical_json_bytes(
        {"schema_version": SOURCE_CLOSURE_SCHEMA, "members": value["members"]}
    )
    expected_root = domain_digest(SOURCE_CLOSURE_DOMAIN, (member_bytes,))
    if value["closure_root"] != expected_root:
        raise ProtocolViolation(f"{label} source closure root mismatch")


@dataclass(frozen=True, slots=True)
class ProtocolGap:
    gap_id: str
    detail: str

    def __post_init__(self) -> None:
        if (
            type(self.gap_id) is not str
            or not self.gap_id.startswith("UCM-")
            or type(self.detail) is not str
            or not self.detail
        ):
            raise ProtocolViolation("protocol gap must have stable id and detail")

    def to_wire(self) -> dict[str, str]:
        return {
            "schema_version": PROTOCOL_GAP_SCHEMA,
            "gap_id": self.gap_id,
            "detail": self.detail,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ProtocolGap":
        row = _exact_object(value, _GAP_KEYS, "protocol gap")
        if row["schema_version"] != PROTOCOL_GAP_SCHEMA:
            raise ProtocolViolation("protocol gap schema mismatch")
        return cls(row["gap_id"], row["detail"])


@dataclass(frozen=True, slots=True)
class PostScopeRequirement:
    requirement_id: str
    stage: str
    detail: str
    blocks_base_scope: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.requirement_id) is not str
            or not self.requirement_id.startswith("UCM-")
            or type(self.stage) is not str
            or not self.stage
            or type(self.detail) is not str
            or not self.detail
            or self.blocks_base_scope is not False
        ):
            raise ProtocolViolation(
                "post-scope requirement must be typed and non-blocking for base scope"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": POST_SCOPE_REQUIREMENT_SCHEMA,
            "requirement_id": self.requirement_id,
            "stage": self.stage,
            "detail": self.detail,
            "blocks_base_scope": self.blocks_base_scope,
        }

    @classmethod
    def from_wire(cls, value: object) -> "PostScopeRequirement":
        row = _exact_object(value, _FOLLOWUP_KEYS, "post-scope requirement")
        if row["schema_version"] != POST_SCOPE_REQUIREMENT_SCHEMA:
            raise ProtocolViolation("post-scope requirement schema mismatch")
        return cls(
            row["requirement_id"],
            row["stage"],
            row["detail"],
            row["blocks_base_scope"],
        )


@dataclass(frozen=True, slots=True)
class SuccessorRuntimeBlocker:
    requirement_id: str
    stage: str
    detail: str
    blocks_base_scope: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.requirement_id) is not str
            or not self.requirement_id.startswith("UCM-")
            or type(self.stage) is not str
            or not self.stage
            or type(self.detail) is not str
            or not self.detail
            or self.blocks_base_scope is not False
        ):
            raise ProtocolViolation(
                "successor blocker must be typed and non-blocking for base scope"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": SUCCESSOR_BLOCKER_SCHEMA,
            "requirement_id": self.requirement_id,
            "stage": self.stage,
            "detail": self.detail,
            "blocks_base_scope": self.blocks_base_scope,
        }

    @classmethod
    def from_wire(cls, value: object) -> "SuccessorRuntimeBlocker":
        row = _exact_object(value, _FOLLOWUP_KEYS, "successor runtime blocker")
        if row["schema_version"] != SUCCESSOR_BLOCKER_SCHEMA:
            raise ProtocolViolation("successor runtime blocker schema mismatch")
        return cls(
            row["requirement_id"],
            row["stage"],
            row["detail"],
            row["blocks_base_scope"],
        )


_SPLIT_GAPS: tuple[ProtocolGap, ...] = ()
_EXTENSION_GAPS: tuple[ProtocolGap, ...] = ()
_SPLIT_POST_SCOPE_REQUIREMENTS = (
    PostScopeRequirement(
        "UCM-SPLIT-POST-SCOPE-R001",
        "post_scope_materialization",
        "formal scope has not materialized the family definitions and generator intents consumed by this protocol",
    ),
    PostScopeRequirement(
        "UCM-SPLIT-POST-SCOPE-R002",
        "post_scope_randomness_and_assignment",
        "hidden split-seed custody, reveal, deterministic execution, and atomic publication are not closed",
    ),
)
_EXTENSION_SUCCESSOR_BLOCKERS = (
    SuccessorRuntimeBlocker(
        "UCM-EXTENSION-SUCCESSOR-B001",
        "successor_scope_materialization",
        "actual eleven-axis expanded scope and its distance-axis consequence have not been materialized",
    ),
    SuccessorRuntimeBlocker(
        "UCM-EXTENSION-SUCCESSOR-B002",
        "successor_runtime_isolation",
        "candidate, model, and state seal chronology is not backed by fresh-process execution isolation",
    ),
    SuccessorRuntimeBlocker(
        "UCM-EXTENSION-SUCCESSOR-B003",
        "successor_source_custody",
        "extension sources and hidden literals have not been externalized from repository-visible runtime source",
    ),
    SuccessorRuntimeBlocker(
        "UCM-EXTENSION-SUCCESSOR-B004",
        "successor_atomic_publication",
        "judge custody and cross-root expanded-scope publication are not an atomic transaction",
    ),
)


def _require_digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a lowercase sha256 digest")
    return value


def _canonical_protocol_bytes(value: object, label: str) -> bytes:
    if type(value) is not bytes:
        raise ProtocolViolation(f"{label} must be exact bytes")
    _decode_canonical_object(value, label)
    return value


def _exact_32_bytes(value: object, label: str) -> bytes:
    if type(value) is not bytes or len(value) != 32:
        raise ProtocolViolation(f"{label} must be exactly 32 bytes")
    return value


def _length_frame(parts: tuple[bytes, ...]) -> bytes:
    if type(parts) is not tuple or any(type(part) is not bytes for part in parts):
        raise ProtocolViolation("framed parts must be an exact tuple of bytes")
    return b"".join(len(part).to_bytes(8, "big") + part for part in parts)


def _validated_split_context(
    context: SplitSeedCommitmentContext,
) -> SplitSeedCommitmentContext:
    if type(context) is not SplitSeedCommitmentContext:
        raise ProtocolViolation("split context must use the code-owned exact type")
    wire = context.to_wire()
    parsed = SplitSeedCommitmentContext.from_wire(
        _decode_canonical_object(canonical_json_bytes(wire), "split seed context")
    )
    if canonical_json_bytes(parsed.to_wire()) != canonical_json_bytes(wire):
        raise ProtocolViolation("split context exact round-trip mismatch")
    return parsed


def compute_split_seed_commitment(
    context: SplitSeedCommitmentContext,
    hidden_seed: bytes,
    nonce: bytes,
) -> str:
    """Commit exact context, nonce, and 256-bit seed under a fixed domain."""

    _validate_executable_control_plane()
    checked_context = _validated_split_context(context)
    context_bytes = canonical_json_bytes(checked_context.to_wire())
    seed = _exact_32_bytes(hidden_seed, "hidden split seed")
    nonce_bytes = _exact_32_bytes(nonce, "split commitment nonce")
    preimage = SPLIT_SEED_COMMITMENT_DOMAIN + _length_frame(
        (context_bytes, nonce_bytes, seed)
    )
    return "sha256:" + hashlib.sha256(preimage).hexdigest()


def _hkdf_sha256_extract_expand(
    input_key_material: bytes, raw_salt: bytes, info: bytes, length: int
) -> bytes:
    """RFC 5869 HKDF-Extract/HKDF-Expand with SHA-256."""

    if (
        type(input_key_material) is not bytes
        or type(raw_salt) is not bytes
        or type(info) is not bytes
        or type(length) is not int
        or length <= 0
        or length > 255 * hashlib.sha256().digest_size
    ):
        raise ProtocolViolation("HKDF inputs are invalid")
    prk = hmac.new(raw_salt, input_key_material, hashlib.sha256).digest()
    output = bytearray()
    previous = b""
    counter = 1
    while len(output) < length:
        previous = hmac.new(
            prk, previous + info + bytes((counter,)), hashlib.sha256
        ).digest()
        output.extend(previous)
        counter += 1
    return bytes(output[:length])


def derive_panel_split_seed(
    hidden_seed: bytes, context: SplitSeedCommitmentContext
) -> bytes:
    """Derive one panel-shared key; task identity is deliberately absent."""

    _validate_executable_control_plane()
    seed = _exact_32_bytes(hidden_seed, "hidden split seed")
    checked_context = _validated_split_context(context)
    context_bytes = canonical_json_bytes(checked_context.to_wire())
    raw_salt = hashlib.sha256(
        _SPLIT_KDF_SALT_DOMAIN + _length_frame((context_bytes,))
    ).digest()
    return _hkdf_sha256_extract_expand(seed, raw_salt, _SPLIT_KDF_INFO, 32)


@dataclass(frozen=True, slots=True)
class SplitDerivationUnit:
    unit_intent_bytes: bytes

    def __post_init__(self) -> None:
        SplitNeutralFamilyUnitIntent.from_wire(
            _decode_canonical_object(
                self.unit_intent_bytes, "split-neutral family unit intent"
            )
        )

    @property
    def intent(self) -> SplitNeutralFamilyUnitIntent:
        return SplitNeutralFamilyUnitIntent.from_wire(
            _decode_canonical_object(
                self.unit_intent_bytes, "split-neutral family unit intent"
            )
        )

    @property
    def unit_intent_digest(self) -> str:
        return self.intent.unit_intent_digest

    @property
    def atomic_group_id(self) -> str:
        return self.intent.atomic_group_id

    @property
    def weight(self) -> int:
        return self.intent.weight

    def to_wire(self) -> dict[str, Any]:
        return {
            "unit_intent": _exact_byte_preimage(
                "split-neutral-family-unit-intent", self.unit_intent_bytes
            ),
            "unit_intent_digest": self.unit_intent_digest,
            "atomic_group_id": self.atomic_group_id,
            "weight": self.weight,
        }


def _split_input_set_wire(
    units: tuple[SplitDerivationUnit, ...],
) -> dict[str, Any]:
    return {
        "schema_version": "ucm-split-derivation-input-set/1",
        "unit_count": len(units),
        "units": [unit.to_wire() for unit in units],
    }


def _split_input_set_root(units: tuple[SplitDerivationUnit, ...]) -> str:
    return domain_digest(
        b"UCM\0SPLIT_DERIVATION_INPUT_SET_V1\0",
        (canonical_json_bytes(_split_input_set_wire(units)),),
    )


@dataclass(frozen=True, slots=True)
class SplitUnitAssignment:
    unit_intent_digest: str
    split: AuthoritySplit

    def __post_init__(self) -> None:
        _require_digest(self.unit_intent_digest, "assigned unit_intent_digest")
        if type(self.split) is not AuthoritySplit:
            raise ProtocolViolation("assigned split must be AuthoritySplit")

    def to_wire(self) -> dict[str, str]:
        return {
            "unit_intent_digest": self.unit_intent_digest,
            "split": self.split.value,
        }


@dataclass(frozen=True, slots=True)
class SplitAssignmentDerivation:
    commitment: str
    commitment_context_digest: str
    panel_identity_digest: str
    panel_seed_digest: str
    input_units: tuple[SplitDerivationUnit, ...]
    input_set_root: str
    assignments: tuple[SplitUnitAssignment, ...]
    assignment_root: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.commitment, "split commitment"),
            (self.commitment_context_digest, "commitment context digest"),
            (self.panel_identity_digest, "panel identity digest"),
            (self.panel_seed_digest, "panel seed digest"),
            (self.input_set_root, "split input set root"),
            (self.assignment_root, "assignment root"),
        ):
            _require_digest(value, label)
        if (
            type(self.assignments) is not tuple
            or not self.assignments
            or any(type(item) is not SplitUnitAssignment for item in self.assignments)
        ):
            raise ProtocolViolation("assignments must be a non-empty typed tuple")
        checked_units = _validate_split_units(self.input_units)
        if self.input_set_root != _split_input_set_root(checked_units):
            raise ProtocolViolation("split input set root mismatch")
        if tuple(item.unit_intent_digest for item in self.assignments) != tuple(
            item.unit_intent_digest for item in checked_units
        ):
            raise ProtocolViolation(
                "assignments do not cover the exact ordered input set"
            )
        if self.assignment_root != domain_digest(
            SPLIT_ASSIGNMENT_ROOT_DOMAIN,
            (canonical_json_bytes(self.preimage_wire()),),
        ):
            raise ProtocolViolation("split assignment root mismatch")

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-executable-split-assignment/1",
            "commitment": self.commitment,
            "commitment_context_digest": self.commitment_context_digest,
            "panel_identity_digest": self.panel_identity_digest,
            "panel_seed_digest": self.panel_seed_digest,
            "input_set": _split_input_set_wire(self.input_units),
            "input_set_root": self.input_set_root,
            "assignments": [item.to_wire() for item in self.assignments],
        }

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "assignment_root": self.assignment_root}


def _validate_split_units(
    units: tuple[SplitDerivationUnit, ...],
) -> tuple[SplitDerivationUnit, ...]:
    if (
        type(units) is not tuple
        or not units
        or any(type(unit) is not SplitDerivationUnit for unit in units)
    ):
        raise ProtocolViolation(
            "split derivation units must be a non-empty typed tuple"
        )
    digests = tuple(unit.unit_intent_digest for unit in units)
    if digests != tuple(sorted(set(digests))):
        raise ProtocolViolation("split units must be unique canonical digest order")
    if len({unit.atomic_group_id for unit in units}) < len(AuthoritySplit):
        raise ProtocolViolation(
            "split derivation requires at least three atomic groups"
        )
    return units


def _group_priority(
    panel_seed: bytes,
    context_bytes: bytes,
    atomic_group_id: str,
    unit_digests: tuple[str, ...],
) -> bytes:
    group_ascii = atomic_group_id.encode("ascii", errors="strict")
    member_bytes = canonical_json_bytes(
        {
            "schema_version": "ucm-atomic-group-member-digests/1",
            "unit_intent_digests": list(unit_digests),
        }
    )
    message = SPLIT_GROUP_PRIORITY_DOMAIN + _length_frame(
        (context_bytes, group_ascii, member_bytes)
    )
    return hmac.new(panel_seed, message, hashlib.sha256).digest()


def derive_panel_family_assignments(
    units: tuple[SplitDerivationUnit, ...],
    *,
    expected_commitment: str,
    context: SplitSeedCommitmentContext,
    hidden_seed: bytes,
    nonce: bytes,
) -> SplitAssignmentDerivation:
    """Open commitment, derive panel key, and assign whole atomic groups."""

    _validate_executable_control_plane()
    checked_units = _validate_split_units(units)
    expected = _require_digest(expected_commitment, "expected split commitment")
    checked_context = _validated_split_context(context)
    opened = compute_split_seed_commitment(context, hidden_seed, nonce)
    if not hmac.compare_digest(expected, opened):
        raise ProtocolViolation("hidden split seed reveal does not open commitment")
    context_bytes = canonical_json_bytes(checked_context.to_wire())
    panel_seed = derive_panel_split_seed(hidden_seed, checked_context)

    grouped: dict[str, list[SplitDerivationUnit]] = {}
    for unit in checked_units:
        grouped.setdefault(unit.atomic_group_id, []).append(unit)
    ordered_groups: list[tuple[bytes, str, int]] = []
    for group_id, members in grouped.items():
        member_digests = tuple(member.unit_intent_digest for member in members)
        ordered_groups.append(
            (
                _group_priority(panel_seed, context_bytes, group_id, member_digests),
                group_id,
                sum(member.weight for member in members),
            )
        )
    ordered_groups.sort(key=lambda row: (row[0], row[1].encode("ascii")))

    loads = {split: 0 for split in AuthoritySplit}
    split_order = {split: index for index, split in enumerate(AuthoritySplit)}
    group_split: dict[str, AuthoritySplit] = {}
    for _, group_id, group_weight in ordered_groups:
        selected = min(
            AuthoritySplit, key=lambda split: (loads[split], split_order[split])
        )
        group_split[group_id] = selected
        loads[selected] += group_weight
    assignments = tuple(
        SplitUnitAssignment(unit.unit_intent_digest, group_split[unit.atomic_group_id])
        for unit in checked_units
    )
    context_digest = digest_bytes(context_bytes)
    panel_digest = digest_bytes(
        canonical_json_bytes(checked_context.panel_identity.to_wire())
    )
    panel_seed_digest = digest_bytes(panel_seed)
    input_set_root = _split_input_set_root(checked_units)
    preimage = {
        "protocol": "ucm-executable-split-assignment/1",
        "commitment": expected,
        "commitment_context_digest": context_digest,
        "panel_identity_digest": panel_digest,
        "panel_seed_digest": panel_seed_digest,
        "input_set": _split_input_set_wire(checked_units),
        "input_set_root": input_set_root,
        "assignments": [item.to_wire() for item in assignments],
    }
    root = domain_digest(
        SPLIT_ASSIGNMENT_ROOT_DOMAIN, (canonical_json_bytes(preimage),)
    )
    return SplitAssignmentDerivation(
        expected,
        context_digest,
        panel_digest,
        panel_seed_digest,
        checked_units,
        input_set_root,
        assignments,
        root,
    )


def verify_panel_family_assignments(
    derivation: SplitAssignmentDerivation,
    units: tuple[SplitDerivationUnit, ...],
    *,
    expected_commitment: str,
    context: SplitSeedCommitmentContext,
    hidden_seed: bytes,
    nonce: bytes,
) -> None:
    """Recompute commit -> reveal -> KDF -> assignment and compare exact wire."""

    _validate_executable_control_plane()
    if type(derivation) is not SplitAssignmentDerivation:
        raise ProtocolViolation("split derivation evidence must be typed")
    expected = derive_panel_family_assignments(
        units,
        expected_commitment=expected_commitment,
        context=context,
        hidden_seed=hidden_seed,
        nonce=nonce,
    )
    if canonical_json_bytes(derivation.to_wire()) != canonical_json_bytes(
        expected.to_wire()
    ):
        raise ProtocolViolation("split assignment derivation does not exact-replay")


def split_derivation_known_answer() -> SplitAssignmentDerivation:
    """Recompute and verify the literal code-owned non-benchmark KAT."""

    _validate_executable_control_plane()
    context = SplitSeedCommitmentContext(
        PanelPhysicalIdentity(
            "ucm-kat",
            "PRE-FREEZE-kat",
            "sha256:" + "00" * 32,
            "W01",
            "primary",
        ),
        SplitPolicyContext("weighted-greedy", "1"),
    )
    raw_units = tuple(
        SplitDerivationUnit(
            canonical_json_bytes(
                SplitNeutralFamilyUnitIntent(
                    f"kat-unit-{index}",
                    FamilyDefinitionIntent(
                        f"kat-definition-{index}", (f"kat-member-{index}",)
                    ),
                    GeneratorIntent(
                        f"kat-generator-{index}",
                        "1",
                        "kat-generator-protocol",
                        f"kat-population-{index}",
                    ),
                    group_id,
                    weight,
                ).to_wire()
            )
        )
        for index, (group_id, weight) in enumerate(
            (
                ("group-a", 1),
                ("group-a", 2),
                ("group-b", 5),
                ("group-c", 3),
                ("group-d", 1),
            ),
            start=1,
        )
    )
    units = tuple(sorted(raw_units, key=lambda item: item.unit_intent_digest))
    commitment = compute_split_seed_commitment(
        context, _SPLIT_KNOWN_SEED, _SPLIT_KNOWN_NONCE
    )
    result = derive_panel_family_assignments(
        units,
        expected_commitment=commitment,
        context=context,
        hidden_seed=_SPLIT_KNOWN_SEED,
        nonce=_SPLIT_KNOWN_NONCE,
    )
    summary = {
        "protocol": result.preimage_wire()["protocol"],
        "commitment": result.commitment,
        "commitment_context_digest": result.commitment_context_digest,
        "panel_identity_digest": result.panel_identity_digest,
        "panel_seed_digest": result.panel_seed_digest,
        "input_set_root": result.input_set_root,
        "assignments": [item.to_wire() for item in result.assignments],
        "assignment_root": result.assignment_root,
    }
    if summary != _SPLIT_KNOWN_ANSWER_EXPECTED:
        raise ProtocolViolation("split derivation known-answer vector mismatch")
    return result


def _split_algorithm_semantics() -> dict[str, Any]:
    """Exact executable intent, without a runtime seed or assignment result."""

    return {
        "algorithm_id": "atomic-family-weighted-hash-greedy",
        "algorithm_version": "1",
        "deterministic": True,
        "runtime_inputs": [
            "typed_split_seed_commitment_context",
            "exact_canonical_SplitNeutralFamilyUnitIntent_bytes",
            "revealed_hidden_split_seed",
            "commitment_nonce",
            "expected_commitment",
        ],
        "protocol_embedded_runtime_inputs": [],
        "preconditions": [
            "parse_every_exact_unit_intent_preimage_with_SplitNeutralFamilyUnitIntent.from_wire",
            "recompute_every_unit_intent_digest_and_derive_group_and_weight_only_from_the_parsed_intent",
            "family_units_are_in_recomputed_unit_intent_digest_order",
            "at_least_three_atomic_groups",
            "every_unit_weight_is_positive_integer",
        ],
        "steps": [
            "build_the_full_ordered_exact_intent_input_set_and_domain_separated_input_set_root",
            "group_units_by_atomic_group_id_without_splitting_a_group",
            "sum_family_unit_weight_within_each_atomic_group",
            "constant_time_verify_domain_framed_context_nonce_seed_commitment_before_KDF",
            "derive_panel_shared_key_with_RFC5869_HKDF_SHA256",
            "derive_raw_group_priority_with_HMAC_SHA256_over_domain_and_uint64_length_framed_context_group_ascii_member_bytes",
            "sort_groups_by_raw_priority_bytes_then_atomic_group_ascii_bytes",
            "assign_each_group_to_the_current_minimum_total_weight_split_with_train_validation_test_tie_order",
            "emit_one_split_label_per_unit_in_original_unit_intent_digest_order",
            "bind_the_full_exact_input_set_and_input_set_root_into_the_assignment_root_preimage",
        ],
        "balance_weight": "family_unit_weight",
        "assignment_unit": "atomic_family_group",
        "split_order": [split.value for split in AuthoritySplit],
        "priority_domain_hex": SPLIT_GROUP_PRIORITY_DOMAIN.hex(),
        "priority_framing": "uint64_be_byte_length_then_exact_bytes",
        "group_id_encoding": "strict_ascii",
        "unit_digest_encoding": "lowercase_sha256_ascii_inside_canonical_JSON_member_preimage",
        "verification": "full_commit_reveal_KDF_priority_greedy_exact_replay",
        "known_answer": {
            "vector_id": "split-kat-v1",
            "synthetic_only": True,
            "raw_seed_and_nonce": "source_closure_only_not_protocol_payload",
            "literal_expected_output": copy.deepcopy(_SPLIT_KNOWN_ANSWER_EXPECTED),
            "verification_entrypoint": "split_derivation_known_answer",
        },
        "raw_seed_serialization": "forbidden",
        "assignment_serialization": "benchmark_assignments_forbidden_synthetic_KAT_expected_output_only",
    }


def _split_seed_kdf_semantics() -> dict[str, Any]:
    """Scope-independent per-panel KDF recipe; no key material is serialized."""

    return {
        "schema_version": "ucm-split-seed-kdf/1",
        "algorithm": "RFC5869-HKDF-SHA256",
        "input_key_material": "revealed_hidden_split_seed_runtime_input",
        "extract": "PRK=HMAC_SHA256(raw_salt,input_key_material)",
        "expand": "T_i=HMAC_SHA256(PRK,T_previous||info||single_octet_counter)",
        "raw_salt": "SHA256(split_kdf_salt_domain||uint64_be_length_frame(canonical_context_bytes)).digest",
        "salt_domain_hex": _SPLIT_KDF_SALT_DOMAIN.hex(),
        "info_hex": _SPLIT_KDF_INFO.hex(),
        "output_length_bytes": 32,
        "panel_physical_identity_source": "typed_context.panel_identity",
        "task_identity_in_context_or_KDF": False,
        "raw_seed_serialization": "forbidden",
        "derived_seed_serialization": "forbidden_in_protocol_template",
    }


def _split_commit_reveal_semantics() -> dict[str, Any]:
    """Exact stage order for later judge-custodied split randomness."""

    return {
        "schema_version": "ucm-hidden-split-seed-commit-reveal/1",
        "commitment_context_schema": SPLIT_SEED_CONTEXT_PROTOCOL,
        "context_declared_commitment_scheme": SplitSeedCommitmentContext.__dataclass_fields__[
            "commitment_scheme"
        ].default,
        "executable_commitment_scheme": "sha256_domain_framed_context_nonce_seed_v1",
        "commitment_domain_hex": SPLIT_SEED_COMMITMENT_DOMAIN.hex(),
        "commitment_preimage_order": [
            "canonical_typed_context_bytes",
            "exact_32_byte_nonce",
            "exact_32_byte_hidden_seed",
        ],
        "framing": "uint64_be_byte_length_then_exact_bytes",
        "opening_comparison": "hmac_compare_digest_before_any_KDF_or_assignment",
        "stages": [
            "freeze_split_neutral_family_intents",
            "publish_hidden_split_seed_commitment_before_family_assignment",
            "seal_commitment_in_judge_custody",
            "reveal_hidden_split_seed_only_to_the_authorized_derivation_runner",
            "verify_reveal_opens_exact_commitment_context",
            "derive_panel_seed_with_the_bound_KDF",
            "derive_atomic_family_assignments",
            "publish_assignments_and_partitions_atomically",
        ],
        "commitment_value": "excluded",
        "reveal_value": "excluded",
        "hidden_seed_value": "excluded",
        "nonce_value": "excluded",
    }


def _family_schema_preimages() -> dict[str, Any]:
    definition_probe = FamilyDefinitionIntent("definition", ("member",)).to_wire()
    generator_probe = GeneratorIntent(
        "generator", "1", "generator-protocol", "population-recipe"
    ).to_wire()
    unit_probe = SplitNeutralFamilyUnitIntent(
        "family-unit",
        FamilyDefinitionIntent("definition", ("member",)),
        GeneratorIntent("generator", "1", "generator-protocol", "population-recipe"),
        "atomic-group",
        1,
    ).to_wire()
    family_policy = FamilyIntentPolicy("family-policy", "1").to_wire()
    split_policy = SplitPolicyContext("split-policy", "1").to_wire()

    definition_schema = {
        "schema_version": FAMILY_DEFINITION_PROTOCOL,
        "required_fields": sorted(definition_probe),
        "source_unit_semantic": definition_probe["source_unit_semantic"],
        "member_intent_ids": "non_empty_unique_canonical_order",
    }
    generator_schema = {
        "schema_version": GENERATOR_INTENT_PROTOCOL,
        "required_fields": sorted(generator_probe),
        "identity_fields": [
            "generator_id",
            "generator_version",
            "generator_protocol",
            "population_recipe_id",
        ],
    }
    unit_schema = {
        "required_fields": sorted(unit_probe),
        "family_definition_schema": FAMILY_DEFINITION_PROTOCOL,
        "generator_intent_schema": GENERATOR_INTENT_PROTOCOL,
        "atomic_group_field": "atomic_group_id",
        "balance_weight_field": "weight",
        "unit_digest_domain_separated": True,
    }
    policy_schema = {
        "family_intent_schema": INTENT_POLICY_PROTOCOL,
        "family_authority_stage": family_policy["authority_stage"],
        "row_payload_binding": family_policy["row_payload_binding"],
        "split_policy_schema": SPLIT_POLICY_PROTOCOL,
        "assignment_unit": split_policy["assignment_unit"],
        "balance_weight": split_policy["balance_weight"],
        "split_order": split_policy["split_order"],
    }
    return {
        "family_definition_intent": _exact_byte_preimage(
            "family-definition-intent-schema", canonical_json_bytes(definition_schema)
        ),
        "generator_intent": _exact_byte_preimage(
            "generator-intent-schema", canonical_json_bytes(generator_schema)
        ),
        "family_unit_intent": _exact_byte_preimage(
            "split-neutral-family-unit-schema", canonical_json_bytes(unit_schema)
        ),
        "intent_and_split_policy": _exact_byte_preimage(
            "intent-and-split-policy-schema", canonical_json_bytes(policy_schema)
        ),
    }


def _split_protocol_wire(
    gaps: tuple[ProtocolGap, ...],
    post_scope_requirements: tuple[PostScopeRequirement, ...],
) -> dict[str, Any]:
    _validate_executable_control_plane()
    panel_identities = {(world, panel) for world, panel, _ in EXPECTED_PANEL_TASK_KEYS}
    tasks = {task.value for _, _, task in EXPECTED_PANEL_TASK_KEYS}
    if (
        len(panel_identities) != PANEL_COUNT
        or len(tasks) != TASK_COUNT
        or len(EXPECTED_PANEL_TASK_KEYS) != PANEL_COUNT * TASK_COUNT
        or PARTITIONS_PER_AUTHORITY != len(AuthoritySplit)
        or ZIPPED_SHARD_SLOTS_PER_PARTITION != len(ZIPPED_REPLICATE_IDS)
    ):
        raise ProtocolViolation("live panel/task/split/seed inventory drifted")

    seed_context_bytes = canonical_json_bytes(
        CODE_OWNED_ZIPPED_SEED_PAIRING_CONTEXT.to_wire()
    )
    if SEED_PROTOCOL_DIGEST != digest_bytes(SEED_PROTOCOL_MANIFEST_BYTES):
        raise ProtocolViolation("live seed protocol digest drifted")
    commitment_scheme = SplitSeedCommitmentContext.__dataclass_fields__[
        "commitment_scheme"
    ].default
    commitment_stage = SplitSeedCommitmentContext.__dataclass_fields__[
        "commitment_stage"
    ].default
    algorithm_source = canonical_json_bytes(_split_algorithm_semantics())

    protocol = {
        "family_and_generator_intent_schemas": _family_schema_preimages(),
        "atomic_grouping": {
            "source_unit_semantic": "patient_family",
            "atomic_group_field": "atomic_group_id",
            "assignment_unit": "atomic_family_group",
            "balance_weight": "family_unit_weight",
            "row_payload_binding": "forbidden",
        },
        "inventory_semantics": {
            "panel_count": PANEL_COUNT,
            "task_count": TASK_COUNT,
            "split_count": PARTITIONS_PER_AUTHORITY,
            "physical_assignment_count": PANEL_COUNT,
            "panel_task_projection_count": PANEL_COUNT * TASK_COUNT,
            "task_projection_count": PANEL_COUNT * TASK_COUNT,
            "panel_task_split_projection_count": (
                PANEL_COUNT * TASK_COUNT * PARTITIONS_PER_AUTHORITY
            ),
            "physical_panel_split_count": PANEL_COUNT * PARTITIONS_PER_AUTHORITY,
            "physical_partition_count": PANEL_COUNT * PARTITIONS_PER_AUTHORITY,
            "zipped_slot_count_per_panel_split": ZIPPED_SHARD_SLOTS_PER_PARTITION,
            "zipped_slot_count": (
                PANEL_COUNT
                * PARTITIONS_PER_AUTHORITY
                * ZIPPED_SHARD_SLOTS_PER_PARTITION
            ),
            "physical_zipped_slot_count": (
                PANEL_COUNT
                * PARTITIONS_PER_AUTHORITY
                * ZIPPED_SHARD_SLOTS_PER_PARTITION
            ),
            "task_is_logical_projection_not_physical_shard_dimension": True,
        },
        "deterministic_derivation": {
            "algorithm_source": _exact_byte_preimage(
                "split-derivation-algorithm-semantics", algorithm_source
            ),
            "source_closure": _source_closure(_SPLIT_SOURCE_PATHS),
            "materialized_assignments": "excluded",
            "materialized_partitions": "excluded",
        },
        "commitment_protocol": {
            "context_schema": SPLIT_SEED_CONTEXT_PROTOCOL,
            "context_declared_commitment_scheme": commitment_scheme,
            "commitment_scheme": "sha256_domain_framed_context_nonce_seed_v1",
            "commitment_stage": commitment_stage,
            "commit_reveal_protocol": _exact_byte_preimage(
                "split-seed-commit-reveal-semantics",
                canonical_json_bytes(_split_commit_reveal_semantics()),
            ),
            "per_panel_seed_kdf": _exact_byte_preimage(
                "split-seed-kdf-semantics",
                canonical_json_bytes(_split_seed_kdf_semantics()),
            ),
            "commitment_value": "excluded",
            "precommit_value": "excluded",
        },
        "zipped_seed_semantics": {
            "seed_protocol_preimage": _exact_byte_preimage(
                "seed-protocol-manifest", SEED_PROTOCOL_MANIFEST_BYTES
            ),
            "zipped_pairing_context_preimage": _exact_byte_preimage(
                "zipped-seed-pairing-context", seed_context_bytes
            ),
            "pair_count": len(ZIPPED_REPLICATE_IDS),
            "pairing": [
                {
                    "training_replicate_id": training_id,
                    "evaluation_replicate_id": evaluation_id,
                }
                for training_id, evaluation_id in ZIPPED_REPLICATE_IDS
            ],
            "composition": "five_zipped_slots_not_five_by_five_cartesian",
            "raw_seed_values": "excluded",
        },
    }
    return {
        "schema_version": SPLIT_DERIVATION_PROTOCOL_SCHEMA,
        "artifact_type": "UCM_SPLIT_DERIVATION_PROTOCOL",
        "benchmark_status": "PRE-FREEZE",
        "authority_claim": "scope_independent_protocol_semantics_only",
        "scope_binding_status": "not_bound",
        "freeze_authority_status": "not_claimed",
        "protocol": protocol,
        "gap_count": len(gaps),
        "gaps": [gap.to_wire() for gap in gaps],
        "post_scope_requirement_count": len(post_scope_requirements),
        "post_scope_requirements": [
            requirement.to_wire() for requirement in post_scope_requirements
        ],
    }


def _extension_axis_contract(world_slot: str) -> dict[str, tuple[str, ...]]:
    contracts = {
        "W16": {
            "required_changed_axes": ("Q",),
            "role_specific_allowed_changed_axes": (
                "O",
                "Q",
                "Pi",
                "Gamma",
                "Y",
                "U",
                "R",
            ),
        },
        "W17": {
            "required_changed_axes": ("A",),
            "role_specific_allowed_changed_axes": ("A", "Pi", "U", "R"),
        },
    }
    try:
        return contracts[world_slot]
    except KeyError as exc:
        raise ProtocolViolation("only W16/W17 have extension axis contracts") from exc


def _distance_derivation_contract_wire() -> dict[str, Any]:
    registry = benchmark_v1_metric_target_registry()
    runtime = benchmark_v1_metric_runtime_bindings(registry.canonical_bytes)
    return {
        "schema_version": "ucm-extension-distance-derivation-contract/1",
        "metric_registry_schema": registry.to_wire()["schema_version"],
        "metric_registry_domain_hex": METRIC_TARGET_DOMAIN.hex(),
        "metric_registry_artifact_digest": registry.artifact_digest,
        "metric_registry_semantic_digest": registry.metric_target_digest,
        "metric_runtime_bindings": _exact_byte_preimage(
            "metric-runtime-bindings", runtime.canonical_bytes
        ),
        "metric_runtime_binding_artifact_digest": runtime.binding_artifact_digest,
        "equivalence_source_closure": _source_closure(_DISTANCE_SOURCE_PATHS),
        "derivation": [
            "parse_exact_base_and_successor_scope_manifests_with_all_eleven_axes",
            "compute_non_D_changed_axes_and_per_axis_base_successor_digests_by_exact_canonical_axis_bytes",
            "domain_hash_the_ordered_actual_non_D_diff_rows",
            "parse_exact_code_owned_metric_registry_and_runtime_binding_bytes",
            "drop_any_prior_extension_distance_derivation_declaration_from_base_D",
            "append_one_code_owned_derivation_declaration_bound_to_base_D_non_D_diff_metric_registry_contract_and_equivalence_source",
            "sort_D_declarations_by_exact_UTF8_declaration_id",
        ],
        "verification": [
            "rederive_expected_successor_D_from_exact_inputs",
            "compare_expected_and_supplied_D_canonical_bytes",
            "reject_missing_extra_reordered_or_resigned_alternate_D_semantics",
        ],
    }


_CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_WIRE = _distance_derivation_contract_wire()
_CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_BYTES = canonical_json_bytes(
    _CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_WIRE
)
_CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_DIGEST = domain_digest(
    DISTANCE_DERIVATION_DOMAIN,
    (_CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_BYTES,),
)
_CODE_OWNED_DISTANCE_EQUIVALENCE_SOURCE_CLOSURE_ROOT = (
    _CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_WIRE["equivalence_source_closure"][
        "closure_root"
    ]
)


def distance_derivation_contract_bytes(
    expected_bytes: bytes = _CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_BYTES,
) -> bytes:
    _validate_executable_control_plane()
    _validate_live_source_inventory(_DISTANCE_SOURCE_PATHS)
    if expected_bytes is not _CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_BYTES:
        raise ProtocolViolation("distance derivation contract cache drifted")
    return expected_bytes


def distance_derivation_contract_digest(
    expected_digest: str = _CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_DIGEST,
) -> str:
    _validate_executable_control_plane()
    if expected_digest != _CODE_OWNED_DISTANCE_DERIVATION_CONTRACT_DIGEST:
        raise ProtocolViolation("distance derivation contract digest drifted")
    return expected_digest


def _distance_equivalence_source_closure_root(
    expected_root: str = _CODE_OWNED_DISTANCE_EQUIVALENCE_SOURCE_CLOSURE_ROOT,
) -> str:
    _validate_executable_control_plane()
    _validate_live_source_inventory(_DISTANCE_SOURCE_PATHS)
    if expected_root != _CODE_OWNED_DISTANCE_EQUIVALENCE_SOURCE_CLOSURE_ROOT:
        raise ProtocolViolation("distance equivalence source closure root drifted")
    return expected_root


def _ordered_axis_subset(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(axis) is not str for axis in values):
        raise ProtocolViolation(f"{label} must be an exact tuple of axis ids")
    if len(values) != len(set(values)) or any(
        axis not in SCOPE_AXES for axis in values
    ):
        raise ProtocolViolation(f"{label} contains duplicate or unknown axes")
    expected = tuple(axis for axis in SCOPE_AXES if axis in values)
    if values != expected:
        raise ProtocolViolation(f"{label} must use formal eleven-axis order")
    return values


def _scope_axis_bytes(manifest: ScopeManifest, axis: str) -> bytes:
    return canonical_json_bytes(manifest.axes[axis].to_wire())


def _validated_scope_manifest(manifest: ScopeManifest, label: str) -> ScopeManifest:
    if type(manifest) is not ScopeManifest:
        raise ProtocolViolation(f"{label} must use the code-owned exact type")
    payload = manifest.canonical_bytes
    parsed = parse_scope_manifest_bytes(payload)
    if parsed.canonical_bytes != payload:
        raise ProtocolViolation(f"{label} exact round-trip mismatch")
    return parsed


def _validated_scope_axis_declarations(
    declarations: ScopeAxisDeclarations, axis_id: str, label: str
) -> ScopeAxisDeclarations:
    if type(declarations) is not ScopeAxisDeclarations:
        raise ProtocolViolation(f"{label} must use the code-owned exact type")
    payload = canonical_json_bytes(declarations.to_wire())
    parsed = ScopeAxisDeclarations.from_wire(
        _decode_canonical_object(payload, label), axis_id=axis_id
    )
    if canonical_json_bytes(parsed.to_wire()) != payload:
        raise ProtocolViolation(f"{label} exact round-trip mismatch")
    return parsed


def derive_successor_distance_axis(
    base_scope: ScopeManifest,
    non_distance_changed_axes: tuple[str, ...],
    successor_axis_declarations: tuple[ScopeAxisDeclarations, ...],
    metric_registry_bytes: bytes,
    metric_runtime_binding_bytes: bytes,
) -> ScopeAxisDeclarations:
    """Derive exact successor D from base D, actual non-D diff, and registry."""

    _validate_executable_control_plane()
    base = _validated_scope_manifest(base_scope, "distance derivation base scope")
    changed = _ordered_axis_subset(
        non_distance_changed_axes, "non-distance changed axes"
    )
    if not changed or "D" in changed:
        raise ProtocolViolation("distance derivation requires a non-empty non-D diff")
    if (
        type(successor_axis_declarations) is not tuple
        or len(successor_axis_declarations) != len(changed)
        or any(
            type(item) is not ScopeAxisDeclarations
            for item in successor_axis_declarations
        )
    ):
        raise ProtocolViolation(
            "distance derivation successor axes must exactly match changed axes"
        )
    checked_successor_axes = tuple(
        _validated_scope_axis_declarations(
            declarations,
            axis,
            f"distance derivation successor axis {axis}",
        )
        for axis, declarations in zip(changed, successor_axis_declarations, strict=True)
    )
    metric = parse_metric_target_registry_bytes(metric_registry_bytes)
    runtime = parse_metric_runtime_bindings_bytes(
        metric_runtime_binding_bytes, metric_registry_bytes
    )
    contract_digest = distance_derivation_contract_digest()
    equivalence_closure_root = _distance_equivalence_source_closure_root()
    actual_diff_rows = [
        {
            "axis_id": axis,
            "base_axis_digest": digest_bytes(_scope_axis_bytes(base, axis)),
            "successor_axis_digest": digest_bytes(
                canonical_json_bytes(successor_axis.to_wire())
            ),
        }
        for axis, successor_axis in zip(changed, checked_successor_axes, strict=True)
    ]
    if any(
        row["base_axis_digest"] == row["successor_axis_digest"]
        for row in actual_diff_rows
    ):
        raise ProtocolViolation("distance derivation received a no-op changed axis")
    actual_diff_digest = domain_digest(
        b"UCM\0EXTENSION_ACTUAL_NON_D_DIFF_V1\0",
        (canonical_json_bytes(actual_diff_rows),),
    )
    derivation = ScopeDeclaration(
        "extension-distance-derivation",
        {
            "schema_version": DISTANCE_DERIVATION_SCHEMA,
            "base_distance_axis_digest": digest_bytes(_scope_axis_bytes(base, "D")),
            "non_distance_changed_axes": list(changed),
            "actual_non_distance_diff": actual_diff_rows,
            "actual_non_distance_diff_digest": actual_diff_digest,
            "metric_registry_artifact_digest": metric.artifact_digest,
            "metric_registry_semantic_digest": metric.metric_target_digest,
            "metric_registry_domain_hex": METRIC_TARGET_DOMAIN.hex(),
            "metric_runtime_binding_artifact_digest": runtime.binding_artifact_digest,
            "metric_runtime_binding_bytes_digest": runtime.artifact_digest,
            "distance_derivation_contract_digest": contract_digest,
            "equivalence_source_closure_root": equivalence_closure_root,
        },
    )
    retained = tuple(
        declaration
        for declaration in base.axes["D"].declarations
        if declaration.declaration_id != derivation.declaration_id
    )
    return ScopeAxisDeclarations(
        tuple(
            sorted(
                (*retained, derivation),
                key=lambda item: item.declaration_id.encode("utf-8"),
            )
        )
    )


def verify_successor_distance_axis(
    base_scope: ScopeManifest,
    successor_distance_axis: ScopeAxisDeclarations,
    non_distance_changed_axes: tuple[str, ...],
    successor_axis_declarations: tuple[ScopeAxisDeclarations, ...],
    metric_registry_bytes: bytes,
    metric_runtime_binding_bytes: bytes,
) -> None:
    _validate_executable_control_plane()
    if type(successor_distance_axis) is not ScopeAxisDeclarations:
        raise ProtocolViolation("successor distance axis must be typed")
    expected = derive_successor_distance_axis(
        base_scope,
        non_distance_changed_axes,
        successor_axis_declarations,
        metric_registry_bytes,
        metric_runtime_binding_bytes,
    )
    if canonical_json_bytes(successor_distance_axis.to_wire()) != canonical_json_bytes(
        expected.to_wire()
    ):
        raise ProtocolViolation("successor D does not exact-replay derivation contract")


@dataclass(frozen=True, slots=True)
class ExtensionAxisPatch:
    axis_id: str
    declarations: ScopeAxisDeclarations

    def __post_init__(self) -> None:
        if self.axis_id not in SCOPE_AXES or self.axis_id == "D":
            raise ProtocolViolation("extension axis patch must target one non-D axis")
        if type(self.declarations) is not ScopeAxisDeclarations:
            raise ProtocolViolation("extension axis patch declarations must be typed")

    def to_wire(self) -> dict[str, Any]:
        return {
            "axis_id": self.axis_id,
            "axis_declarations": self.declarations.to_wire(),
        }

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionAxisPatch":
        row = _exact_object(
            value,
            frozenset({"axis_id", "axis_declarations"}),
            "extension axis patch",
        )
        if type(row["axis_id"]) is not str:
            raise ProtocolViolation("extension axis patch id must be a string")
        return cls(
            row["axis_id"],
            ScopeAxisDeclarations.from_wire(
                row["axis_declarations"], axis_id=row["axis_id"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ExtensionScopeSpec:
    world_slot: str
    source_scope_digest: str
    successor_scope_id: str
    axis_patches: tuple[ExtensionAxisPatch, ...]

    def __post_init__(self) -> None:
        contract = _extension_axis_contract(self.world_slot)
        _require_digest(self.source_scope_digest, "extension spec source scope")
        if (
            type(self.successor_scope_id) is not str
            or not self.successor_scope_id
            or self.successor_scope_id.strip() != self.successor_scope_id
        ):
            raise ProtocolViolation("successor_scope_id must be a canonical string")
        try:
            self.successor_scope_id.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ProtocolViolation("successor_scope_id must be strict UTF-8") from exc
        if (
            type(self.axis_patches) is not tuple
            or not self.axis_patches
            or any(type(item) is not ExtensionAxisPatch for item in self.axis_patches)
        ):
            raise ProtocolViolation("extension spec axis_patches must be typed")
        patch_axes = tuple(item.axis_id for item in self.axis_patches)
        if patch_axes != tuple(axis for axis in SCOPE_AXES if axis in patch_axes):
            raise ProtocolViolation("extension spec patches must use formal axis order")
        if len(patch_axes) != len(set(patch_axes)):
            raise ProtocolViolation("extension spec patch axes must be unique")
        required = set(contract["required_changed_axes"])
        allowed = set(contract["role_specific_allowed_changed_axes"])
        if not required.issubset(patch_axes):
            raise ProtocolViolation("extension spec omits a required changed axis")
        if not set(patch_axes).issubset(allowed):
            raise ProtocolViolation("extension spec patches an axis outside template")

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": EXTENSION_SCOPE_SPEC_SCHEMA,
            "world_slot": self.world_slot,
            "source_scope_digest": self.source_scope_digest,
            "successor_scope_id": self.successor_scope_id,
            "axis_patches": [item.to_wire() for item in self.axis_patches],
        }

    @property
    def spec_digest(self) -> str:
        return domain_digest(
            EXTENSION_SCOPE_SPEC_DOMAIN,
            (canonical_json_bytes(self.preimage_wire()),),
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "spec_digest": self.spec_digest}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionScopeSpec":
        row = _exact_object(
            value,
            frozenset(
                {
                    "schema_version",
                    "world_slot",
                    "source_scope_digest",
                    "successor_scope_id",
                    "axis_patches",
                    "spec_digest",
                }
            ),
            "extension scope spec",
        )
        if row["schema_version"] != EXTENSION_SCOPE_SPEC_SCHEMA:
            raise ProtocolViolation("extension scope spec schema mismatch")
        if type(row["axis_patches"]) is not list:
            raise ProtocolViolation("extension scope spec axis_patches must be a list")
        result = cls(
            row["world_slot"],
            row["source_scope_digest"],
            row["successor_scope_id"],
            tuple(ExtensionAxisPatch.from_wire(item) for item in row["axis_patches"]),
        )
        if canonical_json_bytes(row) != result.canonical_bytes:
            raise ProtocolViolation("extension scope spec reconstruction mismatch")
        return result


def parse_extension_scope_spec_bytes(payload: bytes) -> ExtensionScopeSpec:
    _validate_executable_control_plane()
    return ExtensionScopeSpec.from_wire(
        _decode_canonical_object(payload, "extension scope spec")
    )


def _validated_extension_scope_spec(spec: ExtensionScopeSpec) -> ExtensionScopeSpec:
    if type(spec) is not ExtensionScopeSpec:
        raise ProtocolViolation(
            "extension scope spec must use the code-owned exact type"
        )
    payload = spec.canonical_bytes
    parsed = ExtensionScopeSpec.from_wire(
        _decode_canonical_object(payload, "extension scope spec")
    )
    if parsed.canonical_bytes != payload:
        raise ProtocolViolation("extension scope spec exact round-trip mismatch")
    return parsed


def derive_successor_scope_from_spec(
    base_scope: ScopeManifest,
    spec: ExtensionScopeSpec,
    metric_registry_bytes: bytes,
    metric_runtime_binding_bytes: bytes,
) -> ScopeManifest:
    _validate_executable_control_plane()
    base = _validated_scope_manifest(base_scope, "successor derivation base scope")
    checked_spec = _validated_extension_scope_spec(spec)
    if checked_spec.source_scope_digest != base.scope_digest:
        raise ProtocolViolation("extension spec source scope does not match base S")
    if checked_spec.successor_scope_id == base.scope_id:
        raise ProtocolViolation("successor scope id must be distinct from base S")
    axes = dict(base.axes)
    for patch in checked_spec.axis_patches:
        axes[patch.axis_id] = patch.declarations
    actual_non_distance = tuple(
        axis
        for axis in SCOPE_AXES
        if axis != "D"
        and _scope_axis_bytes(base, axis) != canonical_json_bytes(axes[axis].to_wire())
    )
    claimed = tuple(item.axis_id for item in checked_spec.axis_patches)
    if actual_non_distance != claimed:
        raise ProtocolViolation(
            "extension spec contains a no-op or does not equal the actual non-D diff"
        )
    axes["D"] = derive_successor_distance_axis(
        base,
        actual_non_distance,
        tuple(axes[axis] for axis in actual_non_distance),
        metric_registry_bytes,
        metric_runtime_binding_bytes,
    )
    return ScopeManifest(base.benchmark_id, checked_spec.successor_scope_id, axes)


@dataclass(frozen=True, slots=True)
class ActualScopeDiff:
    world_slot: str
    template_set_semantic_digest: str
    extension_spec_bytes: bytes
    base_scope_manifest_bytes: bytes
    successor_scope_manifest_bytes: bytes
    metric_registry_bytes: bytes
    metric_runtime_binding_bytes: bytes
    changed_axes: tuple[str, ...]

    def __post_init__(self) -> None:
        contract = _extension_axis_contract(self.world_slot)
        _require_digest(
            self.template_set_semantic_digest, "template set semantic digest"
        )
        if (
            self.template_set_semantic_digest
            != build_extension_template_set().semantic_digest
        ):
            raise ProtocolViolation(
                "actual diff is not bound to live template semantics"
            )
        spec = parse_extension_scope_spec_bytes(self.extension_spec_bytes)
        if spec.world_slot != self.world_slot:
            raise ProtocolViolation("actual diff/spec world mismatch")
        base = parse_scope_manifest_bytes(self.base_scope_manifest_bytes)
        successor = parse_scope_manifest_bytes(self.successor_scope_manifest_bytes)
        parse_metric_target_registry_bytes(self.metric_registry_bytes)
        parse_metric_runtime_bindings_bytes(
            self.metric_runtime_binding_bytes, self.metric_registry_bytes
        )
        expected_successor = derive_successor_scope_from_spec(
            base,
            spec,
            self.metric_registry_bytes,
            self.metric_runtime_binding_bytes,
        )
        if expected_successor.canonical_bytes != self.successor_scope_manifest_bytes:
            raise ProtocolViolation(
                "successor S-prime does not exact-replay the revealed typed extension spec"
            )
        if (
            base.benchmark_id != successor.benchmark_id
            or base.scope_id == successor.scope_id
        ):
            raise ProtocolViolation(
                "successor scope must share benchmark and use a distinct scope_id"
            )
        actual = tuple(
            axis
            for axis in SCOPE_AXES
            if _scope_axis_bytes(base, axis) != _scope_axis_bytes(successor, axis)
        )
        _ordered_axis_subset(self.changed_axes, "actual changed axes")
        if self.changed_axes != actual:
            raise ProtocolViolation(
                "claimed actual scope diff differs from exact bytes"
            )
        required = set(contract["required_changed_axes"])
        allowed = set(contract["role_specific_allowed_changed_axes"]) | {"D"}
        if not required.issubset(actual):
            raise ProtocolViolation("actual scope diff omits a required changed axis")
        if not set(actual).issubset(allowed):
            raise ProtocolViolation(
                "actual scope diff changes an axis outside template"
            )
        non_distance = tuple(axis for axis in actual if axis != "D")
        verify_successor_distance_axis(
            base,
            successor.axes["D"],
            non_distance,
            tuple(successor.axes[axis] for axis in non_distance),
            self.metric_registry_bytes,
            self.metric_runtime_binding_bytes,
        )
        if "D" not in actual:
            raise ProtocolViolation("actual extension diff must include derived D")

    @property
    def base_scope(self) -> ScopeManifest:
        return parse_scope_manifest_bytes(self.base_scope_manifest_bytes)

    @property
    def successor_scope(self) -> ScopeManifest:
        return parse_scope_manifest_bytes(self.successor_scope_manifest_bytes)

    @property
    def extension_spec(self) -> ExtensionScopeSpec:
        return parse_extension_scope_spec_bytes(self.extension_spec_bytes)

    def preimage_wire(self) -> dict[str, Any]:
        non_distance = tuple(axis for axis in self.changed_axes if axis != "D")
        return {
            "schema_version": ACTUAL_SCOPE_DIFF_SCHEMA,
            "world_slot": self.world_slot,
            "template_set_semantic_digest": self.template_set_semantic_digest,
            "extension_spec": _exact_byte_preimage(
                "extension-scope-spec", self.extension_spec_bytes
            ),
            "extension_spec_digest": self.extension_spec.spec_digest,
            "base_scope_manifest": _exact_byte_preimage(
                "base-scope-manifest", self.base_scope_manifest_bytes
            ),
            "successor_scope_manifest": _exact_byte_preimage(
                "successor-scope-manifest", self.successor_scope_manifest_bytes
            ),
            "metric_registry": _exact_byte_preimage(
                "metric-target-registry", self.metric_registry_bytes
            ),
            "metric_runtime_bindings": _exact_byte_preimage(
                "metric-runtime-bindings", self.metric_runtime_binding_bytes
            ),
            "base_scope_digest": self.base_scope.scope_digest,
            "successor_scope_digest": self.successor_scope.scope_digest,
            "changed_axes": list(self.changed_axes),
            "non_distance_changed_axes": list(non_distance),
            "distance_derivation_contract_digest": distance_derivation_contract_digest(),
        }

    @property
    def diff_digest(self) -> str:
        return domain_digest(
            ACTUAL_SCOPE_DIFF_DOMAIN, (canonical_json_bytes(self.preimage_wire()),)
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "diff_digest": self.diff_digest}

    @classmethod
    def from_wire(cls, value: object) -> "ActualScopeDiff":
        expected_keys = frozenset(
            {
                "schema_version",
                "world_slot",
                "template_set_semantic_digest",
                "extension_spec",
                "extension_spec_digest",
                "base_scope_manifest",
                "successor_scope_manifest",
                "metric_registry",
                "metric_runtime_bindings",
                "base_scope_digest",
                "successor_scope_digest",
                "changed_axes",
                "non_distance_changed_axes",
                "distance_derivation_contract_digest",
                "diff_digest",
            }
        )
        row = _exact_object(value, expected_keys, "actual scope diff")
        if row["schema_version"] != ACTUAL_SCOPE_DIFF_SCHEMA:
            raise ProtocolViolation("actual scope diff schema mismatch")
        if type(row["changed_axes"]) is not list:
            raise ProtocolViolation("actual scope changed_axes must be a list")
        result = cls(
            row["world_slot"],
            row["template_set_semantic_digest"],
            _decode_exact_byte_preimage(row["extension_spec"], "extension scope spec"),
            _decode_exact_byte_preimage(
                row["base_scope_manifest"], "base scope manifest"
            ),
            _decode_exact_byte_preimage(
                row["successor_scope_manifest"], "successor scope manifest"
            ),
            _decode_exact_byte_preimage(row["metric_registry"], "metric registry"),
            _decode_exact_byte_preimage(
                row["metric_runtime_bindings"], "metric runtime bindings"
            ),
            tuple(row["changed_axes"]),
        )
        if canonical_json_bytes(row) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("actual scope diff reconstruction mismatch")
        return result


def build_actual_scope_diff(
    extension_spec_bytes: bytes,
    base_scope_manifest_bytes: bytes,
    metric_registry_bytes: bytes | None = None,
    metric_runtime_binding_bytes: bytes | None = None,
) -> ActualScopeDiff:
    _validate_executable_control_plane()
    spec = parse_extension_scope_spec_bytes(extension_spec_bytes)
    base = parse_scope_manifest_bytes(base_scope_manifest_bytes)
    metric_bytes = (
        benchmark_v1_metric_target_registry().canonical_bytes
        if metric_registry_bytes is None
        else metric_registry_bytes
    )
    runtime_bytes = (
        benchmark_v1_metric_runtime_bindings(metric_bytes).canonical_bytes
        if metric_runtime_binding_bytes is None
        else metric_runtime_binding_bytes
    )
    successor = derive_successor_scope_from_spec(
        base, spec, metric_bytes, runtime_bytes
    )
    changed = tuple(
        axis
        for axis in SCOPE_AXES
        if _scope_axis_bytes(base, axis) != _scope_axis_bytes(successor, axis)
    )
    return ActualScopeDiff(
        spec.world_slot,
        build_extension_template_set().semantic_digest,
        extension_spec_bytes,
        base_scope_manifest_bytes,
        successor.canonical_bytes,
        metric_bytes,
        runtime_bytes,
        changed,
    )


def compute_extension_scope_commitment(
    world_slot: str, extension_spec_bytes: bytes, nonce: bytes
) -> str:
    _validate_executable_control_plane()
    spec = parse_extension_scope_spec_bytes(extension_spec_bytes)
    if spec.world_slot != world_slot:
        raise ProtocolViolation("extension commitment world/spec mismatch")
    nonce_bytes = _exact_32_bytes(nonce, "extension commitment nonce")
    return domain_digest(
        EXTENSION_SCOPE_COMMITMENT_DOMAIN,
        (world_slot.encode("ascii"), spec.canonical_bytes, nonce_bytes),
    )


def _primary_state_set_root(state_hashes: tuple[str, ...]) -> str:
    if (
        type(state_hashes) is not tuple
        or not state_hashes
        or any(type(item) is not str for item in state_hashes)
    ):
        raise ProtocolViolation("primary state hashes must be a non-empty tuple")
    for item in state_hashes:
        _require_digest(item, "primary state hash")
    if state_hashes != tuple(sorted(set(state_hashes))):
        raise ProtocolViolation("primary state hashes must be unique canonical order")
    return domain_digest(
        PRIMARY_STATE_SET_DOMAIN,
        (canonical_json_bytes(list(state_hashes)),),
    )


@dataclass(frozen=True, slots=True)
class ExtensionTransitionSeal:
    world_slot: str
    template_set_semantic_digest: str
    source_scope_digest: str
    extension_commitment: str
    candidate_bundle_digest: str
    model_digest: str
    primary_state_hashes: tuple[str, ...]
    primary_state_root: str
    primary_state_snapshot_digest: str
    primary_result_root: str

    def __post_init__(self) -> None:
        _extension_axis_contract(self.world_slot)
        for value, label in (
            (self.template_set_semantic_digest, "template semantic digest"),
            (self.source_scope_digest, "source scope digest"),
            (self.extension_commitment, "extension commitment"),
            (self.candidate_bundle_digest, "candidate bundle digest"),
            (self.model_digest, "model digest"),
            (self.primary_state_root, "primary state root"),
            (self.primary_state_snapshot_digest, "primary state snapshot digest"),
            (self.primary_result_root, "primary result root"),
        ):
            _require_digest(value, label)
        if (
            self.template_set_semantic_digest
            != build_extension_template_set().semantic_digest
        ):
            raise ProtocolViolation("transition seal template digest mismatch")
        if self.primary_state_root != _primary_state_set_root(
            self.primary_state_hashes
        ):
            raise ProtocolViolation("transition seal primary state root mismatch")

    def preimage_wire(self) -> dict[str, str]:
        return {
            "schema_version": EXTENSION_TRANSITION_SEAL_SCHEMA,
            "world_slot": self.world_slot,
            "template_set_semantic_digest": self.template_set_semantic_digest,
            "source_scope_digest": self.source_scope_digest,
            "extension_commitment": self.extension_commitment,
            "candidate_bundle_digest": self.candidate_bundle_digest,
            "model_digest": self.model_digest,
            "primary_state_hashes": list(self.primary_state_hashes),
            "primary_state_root": self.primary_state_root,
            "primary_state_snapshot_digest": self.primary_state_snapshot_digest,
            "primary_result_root": self.primary_result_root,
        }

    @property
    def seal_digest(self) -> str:
        return domain_digest(
            EXTENSION_TRANSITION_SEAL_DOMAIN,
            (canonical_json_bytes(self.preimage_wire()),),
        )

    def to_wire(self) -> dict[str, str]:
        return {**self.preimage_wire(), "seal_digest": self.seal_digest}

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionTransitionSeal":
        keys = frozenset(
            {
                "schema_version",
                "world_slot",
                "template_set_semantic_digest",
                "source_scope_digest",
                "extension_commitment",
                "candidate_bundle_digest",
                "model_digest",
                "primary_state_hashes",
                "primary_state_root",
                "primary_state_snapshot_digest",
                "primary_result_root",
                "seal_digest",
            }
        )
        row = _exact_object(value, keys, "extension transition seal")
        if row["schema_version"] != EXTENSION_TRANSITION_SEAL_SCHEMA:
            raise ProtocolViolation("extension transition seal schema mismatch")
        if type(row["primary_state_hashes"]) is not list:
            raise ProtocolViolation("transition seal state hashes must be a list")
        result = cls(
            row["world_slot"],
            row["template_set_semantic_digest"],
            row["source_scope_digest"],
            row["extension_commitment"],
            row["candidate_bundle_digest"],
            row["model_digest"],
            tuple(row["primary_state_hashes"]),
            row["primary_state_root"],
            row["primary_state_snapshot_digest"],
            row["primary_result_root"],
        )
        if canonical_json_bytes(row) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("transition seal reconstruction mismatch")
        return result


@dataclass(frozen=True, slots=True)
class ExtensionScopeReveal:
    world_slot: str
    extension_commitment: str
    extension_spec_bytes: bytes
    nonce: bytes
    transition_seal_digest: str
    primary_result_root: str

    def __post_init__(self) -> None:
        _require_digest(self.extension_commitment, "extension commitment")
        _require_digest(self.transition_seal_digest, "transition seal digest")
        _require_digest(self.primary_result_root, "reveal primary result root")
        opened = compute_extension_scope_commitment(
            self.world_slot, self.extension_spec_bytes, self.nonce
        )
        if not hmac.compare_digest(opened, self.extension_commitment):
            raise ProtocolViolation("extension reveal does not open commitment")

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": EXTENSION_SCOPE_REVEAL_SCHEMA,
            "world_slot": self.world_slot,
            "extension_commitment": self.extension_commitment,
            "extension_spec": _exact_byte_preimage(
                "extension-specification", self.extension_spec_bytes
            ),
            "nonce_hex": self.nonce.hex(),
            "transition_seal_digest": self.transition_seal_digest,
            "primary_result_root": self.primary_result_root,
        }

    @property
    def reveal_digest(self) -> str:
        return domain_digest(
            EXTENSION_SCOPE_REVEAL_DOMAIN,
            (canonical_json_bytes(self.preimage_wire()),),
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "reveal_digest": self.reveal_digest}

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionScopeReveal":
        keys = frozenset(
            {
                "schema_version",
                "world_slot",
                "extension_commitment",
                "extension_spec",
                "nonce_hex",
                "transition_seal_digest",
                "primary_result_root",
                "reveal_digest",
            }
        )
        row = _exact_object(value, keys, "extension scope reveal")
        if row["schema_version"] != EXTENSION_SCOPE_REVEAL_SCHEMA:
            raise ProtocolViolation("extension scope reveal schema mismatch")
        if type(row["nonce_hex"]) is not str:
            raise ProtocolViolation("extension reveal nonce_hex must be string")
        try:
            nonce = bytes.fromhex(row["nonce_hex"])
        except ValueError as exc:
            raise ProtocolViolation("extension reveal nonce is invalid hex") from exc
        result = cls(
            row["world_slot"],
            row["extension_commitment"],
            _decode_exact_byte_preimage(
                row["extension_spec"], "extension specification"
            ),
            nonce,
            row["transition_seal_digest"],
            row["primary_result_root"],
        )
        if canonical_json_bytes(row) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("extension reveal reconstruction mismatch")
        return result


@dataclass(frozen=True, slots=True)
class ExtensionFirstQueryEnvelope:
    world_slot: str
    source_scope_digest: str
    target_scope_digest: str
    actual_scope_diff_digest: str
    extension_spec_digest: str
    primary_state_hash: str
    query_bytes: bytes

    def __post_init__(self) -> None:
        _extension_axis_contract(self.world_slot)
        for value, label in (
            (self.source_scope_digest, "first query source scope"),
            (self.target_scope_digest, "first query target scope"),
            (self.actual_scope_diff_digest, "first query actual diff"),
            (self.extension_spec_digest, "first query extension spec"),
            (self.primary_state_hash, "first query primary state"),
        ):
            _require_digest(value, label)
        if self.source_scope_digest == self.target_scope_digest:
            raise ProtocolViolation("first query source/target scopes must differ")
        query = _exact_object(
            _decode_canonical_object(self.query_bytes, "extension first query"),
            frozenset({"schema_version", "query_type", "readout_id"}),
            "extension state-only first query payload",
        )
        if (
            query["schema_version"] != "ucm-extension-state-only-readout-query/1"
            or query["query_type"] != "extension_readout"
            or type(query["readout_id"]) is not str
            or _QUERY_ID_RE.fullmatch(query["readout_id"]) is None
        ):
            raise ProtocolViolation(
                "extension first query must use the exact state-only readout schema"
            )

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": EXTENSION_FIRST_QUERY_SCHEMA,
            "world_slot": self.world_slot,
            "source_scope_digest": self.source_scope_digest,
            "target_scope_digest": self.target_scope_digest,
            "actual_scope_diff_digest": self.actual_scope_diff_digest,
            "extension_spec_digest": self.extension_spec_digest,
            "primary_state_hash": self.primary_state_hash,
            "query": _exact_byte_preimage(
                "extension-first-query-payload", self.query_bytes
            ),
        }

    @property
    def request_digest(self) -> str:
        return domain_digest(
            EXTENSION_FIRST_QUERY_DOMAIN,
            (canonical_json_bytes(self.preimage_wire()),),
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "request_digest": self.request_digest}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionFirstQueryEnvelope":
        row = _exact_object(
            value,
            frozenset(
                {
                    "schema_version",
                    "world_slot",
                    "source_scope_digest",
                    "target_scope_digest",
                    "actual_scope_diff_digest",
                    "extension_spec_digest",
                    "primary_state_hash",
                    "query",
                    "request_digest",
                }
            ),
            "extension first query envelope",
        )
        if row["schema_version"] != EXTENSION_FIRST_QUERY_SCHEMA:
            raise ProtocolViolation("extension first query schema mismatch")
        result = cls(
            row["world_slot"],
            row["source_scope_digest"],
            row["target_scope_digest"],
            row["actual_scope_diff_digest"],
            row["extension_spec_digest"],
            row["primary_state_hash"],
            _decode_exact_byte_preimage(row["query"], "extension first query"),
        )
        if canonical_json_bytes(row) != result.canonical_bytes:
            raise ProtocolViolation("extension first query reconstruction mismatch")
        return result


def parse_extension_first_query_bytes(payload: bytes) -> ExtensionFirstQueryEnvelope:
    _validate_executable_control_plane()
    return ExtensionFirstQueryEnvelope.from_wire(
        _decode_canonical_object(payload, "extension first query envelope")
    )


@dataclass(frozen=True, slots=True)
class ExtensionFirstResultEnvelope:
    request_digest: str
    status: str
    prediction_bytes: bytes | None

    def __post_init__(self) -> None:
        _require_digest(self.request_digest, "first result request digest")
        if self.status not in {"ok", "scope_insufficient"}:
            raise ProtocolViolation("extension first result status is invalid")
        if self.status == "ok":
            if type(self.prediction_bytes) is not bytes:
                raise ProtocolViolation(
                    "ok first result requires exact prediction bytes"
                )
            prediction = _decode_canonical_object(
                self.prediction_bytes, "extension first result prediction"
            )
            if not prediction:
                raise ProtocolViolation("ok first result prediction cannot be empty")
        elif self.prediction_bytes is not None:
            raise ProtocolViolation(
                "scope_insufficient first result cannot claim a prediction"
            )

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": EXTENSION_FIRST_RESULT_SCHEMA,
            "request_digest": self.request_digest,
            "status": self.status,
            "prediction": (
                None
                if self.prediction_bytes is None
                else _exact_byte_preimage(
                    "extension-first-result-prediction", self.prediction_bytes
                )
            ),
        }

    @property
    def result_digest(self) -> str:
        return domain_digest(
            EXTENSION_FIRST_RESULT_DOMAIN,
            (canonical_json_bytes(self.preimage_wire()),),
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "result_digest": self.result_digest}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionFirstResultEnvelope":
        row = _exact_object(
            value,
            frozenset(
                {
                    "schema_version",
                    "request_digest",
                    "status",
                    "prediction",
                    "result_digest",
                }
            ),
            "extension first result envelope",
        )
        if row["schema_version"] != EXTENSION_FIRST_RESULT_SCHEMA:
            raise ProtocolViolation("extension first result schema mismatch")
        prediction = (
            None
            if row["prediction"] is None
            else _decode_exact_byte_preimage(
                row["prediction"], "extension first result prediction"
            )
        )
        result = cls(row["request_digest"], row["status"], prediction)
        if canonical_json_bytes(row) != result.canonical_bytes:
            raise ProtocolViolation("extension first result reconstruction mismatch")
        return result


def parse_extension_first_result_bytes(
    payload: bytes,
) -> ExtensionFirstResultEnvelope:
    _validate_executable_control_plane()
    return ExtensionFirstResultEnvelope.from_wire(
        _decode_canonical_object(payload, "extension first result envelope")
    )


@dataclass(frozen=True, slots=True)
class ExtensionScopeRequest:
    world_slot: str
    transition_seal_digest: str
    actual_scope_diff_digest: str
    source_scope_digest: str
    target_scope_digest: str
    first_query_bytes: bytes

    def __post_init__(self) -> None:
        _extension_axis_contract(self.world_slot)
        for value, label in (
            (self.transition_seal_digest, "request transition seal"),
            (self.actual_scope_diff_digest, "request actual diff"),
            (self.source_scope_digest, "request source scope"),
            (self.target_scope_digest, "request target scope"),
        ):
            _require_digest(value, label)
        if self.source_scope_digest == self.target_scope_digest:
            raise ProtocolViolation(
                "extension request source/target scopes must differ"
            )
        query = parse_extension_first_query_bytes(self.first_query_bytes)
        if (
            query.world_slot != self.world_slot
            or query.source_scope_digest != self.source_scope_digest
            or query.target_scope_digest != self.target_scope_digest
            or query.actual_scope_diff_digest != self.actual_scope_diff_digest
        ):
            raise ProtocolViolation("extension request/first-query exact join mismatch")

    @property
    def first_query(self) -> ExtensionFirstQueryEnvelope:
        return parse_extension_first_query_bytes(self.first_query_bytes)

    @property
    def primary_state_hash(self) -> str:
        return self.first_query.primary_state_hash

    @property
    def query_digest(self) -> str:
        return self.first_query.request_digest

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": EXTENSION_SCOPE_REQUEST_SCHEMA,
            "world_slot": self.world_slot,
            "transition_seal_digest": self.transition_seal_digest,
            "actual_scope_diff_digest": self.actual_scope_diff_digest,
            "source_scope_digest": self.source_scope_digest,
            "target_scope_digest": self.target_scope_digest,
            "first_query": _exact_byte_preimage(
                "extension-first-query-envelope", self.first_query_bytes
            ),
            "first_query_digest": self.first_query.request_digest,
        }

    @property
    def request_digest(self) -> str:
        return domain_digest(
            EXTENSION_SCOPE_REQUEST_DOMAIN,
            (canonical_json_bytes(self.preimage_wire()),),
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "request_digest": self.request_digest}

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionScopeRequest":
        keys = frozenset(
            {
                "schema_version",
                "world_slot",
                "transition_seal_digest",
                "actual_scope_diff_digest",
                "source_scope_digest",
                "target_scope_digest",
                "first_query",
                "first_query_digest",
                "request_digest",
            }
        )
        row = _exact_object(value, keys, "extension scope request")
        if row["schema_version"] != EXTENSION_SCOPE_REQUEST_SCHEMA:
            raise ProtocolViolation("extension scope request schema mismatch")
        result = cls(
            row["world_slot"],
            row["transition_seal_digest"],
            row["actual_scope_diff_digest"],
            row["source_scope_digest"],
            row["target_scope_digest"],
            _decode_exact_byte_preimage(
                row["first_query"], "extension first query envelope"
            ),
        )
        if canonical_json_bytes(row) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("extension request reconstruction mismatch")
        return result


@dataclass(frozen=True, slots=True)
class ExtensionScopeTranscript:
    request_digest: str
    transition_seal_digest: str
    actual_scope_diff_digest: str
    source_scope_digest: str
    target_scope_digest: str
    first_result_bytes: bytes
    migration_authorized: bool

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_digest, "transcript request"),
            (self.transition_seal_digest, "transcript transition seal"),
            (self.actual_scope_diff_digest, "transcript actual diff"),
            (self.source_scope_digest, "transcript source scope"),
            (self.target_scope_digest, "transcript target scope"),
        ):
            _require_digest(value, label)
        if type(self.migration_authorized) is not bool:
            raise ProtocolViolation("migration_authorized must be exact bool")
        result = parse_extension_first_result_bytes(self.first_result_bytes)
        if result.request_digest != self.request_digest:
            raise ProtocolViolation(
                "extension transcript first-result request mismatch"
            )
        if result.status == "ok":
            if self.migration_authorized:
                raise ProtocolViolation("ok transcript cannot authorize migration")
        if self.source_scope_digest == self.target_scope_digest:
            raise ProtocolViolation("transcript source/target scopes must differ")

    @property
    def first_result(self) -> ExtensionFirstResultEnvelope:
        return parse_extension_first_result_bytes(self.first_result_bytes)

    @property
    def status(self) -> str:
        return self.first_result.status

    @property
    def extension_result_digest(self) -> str | None:
        return self.first_result.result_digest if self.status == "ok" else None

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": EXTENSION_SCOPE_TRANSCRIPT_SCHEMA,
            "request_digest": self.request_digest,
            "transition_seal_digest": self.transition_seal_digest,
            "actual_scope_diff_digest": self.actual_scope_diff_digest,
            "source_scope_digest": self.source_scope_digest,
            "target_scope_digest": self.target_scope_digest,
            "first_result": _exact_byte_preimage(
                "extension-first-result-envelope", self.first_result_bytes
            ),
            "first_result_digest": self.first_result.result_digest,
            "status": self.status,
            "migration_authorized": self.migration_authorized,
        }

    @property
    def transcript_digest(self) -> str:
        return domain_digest(
            EXTENSION_SCOPE_TRANSCRIPT_DOMAIN,
            (canonical_json_bytes(self.preimage_wire()),),
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "transcript_digest": self.transcript_digest}

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionScopeTranscript":
        keys = frozenset(
            {
                "schema_version",
                "request_digest",
                "transition_seal_digest",
                "actual_scope_diff_digest",
                "source_scope_digest",
                "target_scope_digest",
                "first_result",
                "first_result_digest",
                "status",
                "migration_authorized",
                "transcript_digest",
            }
        )
        row = _exact_object(value, keys, "extension scope transcript")
        if row["schema_version"] != EXTENSION_SCOPE_TRANSCRIPT_SCHEMA:
            raise ProtocolViolation("extension scope transcript schema mismatch")
        result = cls(
            row["request_digest"],
            row["transition_seal_digest"],
            row["actual_scope_diff_digest"],
            row["source_scope_digest"],
            row["target_scope_digest"],
            _decode_exact_byte_preimage(
                row["first_result"], "extension first result envelope"
            ),
            row["migration_authorized"],
        )
        if canonical_json_bytes(row) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("extension transcript reconstruction mismatch")
        return result


def _validated_transition_component(
    value: object, expected_type: type[Any], label: str
) -> Any:
    if type(value) is not expected_type:
        raise ProtocolViolation(f"{label} must use the code-owned exact type")
    wire = value.to_wire()
    parsed = expected_type.from_wire(wire)
    if canonical_json_bytes(wire) != canonical_json_bytes(parsed.to_wire()):
        raise ProtocolViolation(f"{label} exact round-trip mismatch")
    return parsed


@dataclass(frozen=True, slots=True)
class SuccessorReceipt:
    transition_seal: ExtensionTransitionSeal
    reveal: ExtensionScopeReveal
    actual_scope_diff: ActualScopeDiff
    request: ExtensionScopeRequest
    transcript: ExtensionScopeTranscript
    primary_result_root_before_extension: str
    primary_result_root_after_extension: str
    extension_result_root: str | None
    extension_result_namespace: str = "extension_only"
    primary_aggregate_eligible: bool = False
    mixed_scope_aggregation: str = "forbidden"
    successor_runtime_trust_status: str = "UNVERIFIED_SUCCESSOR_RUNTIME"
    successor_runtime_eligible: bool = False

    def __post_init__(self) -> None:
        seal = _validated_transition_component(
            self.transition_seal,
            ExtensionTransitionSeal,
            "successor receipt transition seal",
        )
        reveal = _validated_transition_component(
            self.reveal,
            ExtensionScopeReveal,
            "successor receipt reveal",
        )
        diff = _validated_transition_component(
            self.actual_scope_diff,
            ActualScopeDiff,
            "successor receipt actual scope diff",
        )
        request = _validated_transition_component(
            self.request,
            ExtensionScopeRequest,
            "successor receipt request",
        )
        transcript = _validated_transition_component(
            self.transcript,
            ExtensionScopeTranscript,
            "successor receipt transcript",
        )
        object.__setattr__(self, "transition_seal", seal)
        object.__setattr__(self, "reveal", reveal)
        object.__setattr__(self, "actual_scope_diff", diff)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "transcript", transcript)
        if (
            len(
                {
                    seal.world_slot,
                    diff.world_slot,
                    request.world_slot,
                    reveal.world_slot,
                }
            )
            != 1
        ):
            raise ProtocolViolation("successor receipt cross-splices world slots")
        if (
            seal.seal_digest != reveal.transition_seal_digest
            or seal.seal_digest != request.transition_seal_digest
            or seal.seal_digest != transcript.transition_seal_digest
            or seal.extension_commitment != reveal.extension_commitment
        ):
            raise ProtocolViolation("successor receipt seal/reveal join mismatch")
        if (
            reveal.extension_spec_bytes != diff.extension_spec_bytes
            or request.first_query.extension_spec_digest
            != diff.extension_spec.spec_digest
        ):
            raise ProtocolViolation("successor receipt reveal/spec/diff join mismatch")
        if (
            seal.source_scope_digest != diff.base_scope.scope_digest
            or request.source_scope_digest != diff.base_scope.scope_digest
            or transcript.source_scope_digest != diff.base_scope.scope_digest
            or request.target_scope_digest != diff.successor_scope.scope_digest
            or transcript.target_scope_digest != diff.successor_scope.scope_digest
            or request.actual_scope_diff_digest != diff.diff_digest
            or transcript.actual_scope_diff_digest != diff.diff_digest
            or transcript.request_digest != request.request_digest
        ):
            raise ProtocolViolation(
                "successor receipt source/target exact join mismatch"
            )
        if request.primary_state_hash not in seal.primary_state_hashes:
            raise ProtocolViolation(
                "extension request state is not a member of the sealed primary state set"
            )
        for value, label in (
            (self.primary_result_root_before_extension, "primary result before"),
            (self.primary_result_root_after_extension, "primary result after"),
        ):
            _require_digest(value, label)
        if not (
            self.primary_result_root_before_extension
            == self.primary_result_root_after_extension
            == seal.primary_result_root
            == reveal.primary_result_root
        ):
            raise ProtocolViolation("primary result root changed across extension")
        if transcript.status == "ok":
            if self.extension_result_root != transcript.extension_result_digest:
                raise ProtocolViolation("extension result root/transcript mismatch")
        elif self.extension_result_root is not None:
            raise ProtocolViolation(
                "scope_insufficient receipt cannot claim result root"
            )
        if (
            self.extension_result_namespace != "extension_only"
            or self.primary_aggregate_eligible is not False
            or self.mixed_scope_aggregation != "forbidden"
            or self.successor_runtime_trust_status != "UNVERIFIED_SUCCESSOR_RUNTIME"
            or self.successor_runtime_eligible is not False
        ):
            raise ProtocolViolation("successor receipt aggregation isolation mismatch")

    def preimage_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "schema_version": SUCCESSOR_RECEIPT_SCHEMA,
            "transition_seal": self.transition_seal.to_wire(),
            "reveal": self.reveal.to_wire(),
            "actual_scope_diff": self.actual_scope_diff.to_wire(),
            "request": self.request.to_wire(),
            "transcript": self.transcript.to_wire(),
            "primary_result_root_before_extension": self.primary_result_root_before_extension,
            "primary_result_root_after_extension": self.primary_result_root_after_extension,
            "extension_result_root": self.extension_result_root,
            "extension_result_namespace": self.extension_result_namespace,
            "primary_aggregate_eligible": self.primary_aggregate_eligible,
            "mixed_scope_aggregation": self.mixed_scope_aggregation,
            "successor_runtime_trust_status": self.successor_runtime_trust_status,
            "successor_runtime_eligible": self.successor_runtime_eligible,
        }

    @property
    def receipt_digest(self) -> str:
        return domain_digest(
            SUCCESSOR_RECEIPT_DOMAIN, (canonical_json_bytes(self.preimage_wire()),)
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "receipt_digest": self.receipt_digest}

    @classmethod
    def from_wire(cls, value: object) -> "SuccessorReceipt":
        keys = frozenset(
            {
                "schema_version",
                "transition_seal",
                "reveal",
                "actual_scope_diff",
                "request",
                "transcript",
                "primary_result_root_before_extension",
                "primary_result_root_after_extension",
                "extension_result_root",
                "extension_result_namespace",
                "primary_aggregate_eligible",
                "mixed_scope_aggregation",
                "successor_runtime_trust_status",
                "successor_runtime_eligible",
                "receipt_digest",
            }
        )
        row = _exact_object(value, keys, "successor receipt")
        if row["schema_version"] != SUCCESSOR_RECEIPT_SCHEMA:
            raise ProtocolViolation("successor receipt schema mismatch")
        result = cls(
            ExtensionTransitionSeal.from_wire(row["transition_seal"]),
            ExtensionScopeReveal.from_wire(row["reveal"]),
            ActualScopeDiff.from_wire(row["actual_scope_diff"]),
            ExtensionScopeRequest.from_wire(row["request"]),
            ExtensionScopeTranscript.from_wire(row["transcript"]),
            row["primary_result_root_before_extension"],
            row["primary_result_root_after_extension"],
            row["extension_result_root"],
            row["extension_result_namespace"],
            row["primary_aggregate_eligible"],
            row["mixed_scope_aggregation"],
            row["successor_runtime_trust_status"],
            row["successor_runtime_eligible"],
        )
        if canonical_json_bytes(row) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("successor receipt reconstruction mismatch")
        return result


def parse_actual_scope_diff_bytes(payload: bytes) -> ActualScopeDiff:
    _validate_executable_control_plane()
    return ActualScopeDiff.from_wire(
        _decode_canonical_object(payload, "actual scope diff")
    )


def parse_successor_receipt_bytes(payload: bytes) -> SuccessorReceipt:
    _validate_executable_control_plane()
    return SuccessorReceipt.from_wire(
        _decode_canonical_object(payload, "successor receipt")
    )


def _extension_protocol_schema_preimage() -> dict[str, Any]:
    _validate_live_extension_protocol_constants()
    descriptor = {
        "opaque_commitment_schema": COMMIT_PROTOCOL,
        "reveal_schema": REVEAL_PROTOCOL,
        "primary_seal_schema": PRIMARY_SEAL_PROTOCOL,
        "first_state_only_query_schema": FIRST_QUERY_PROTOCOL,
        "measured_migration_schema": MIGRATION_PROTOCOL,
        "typed_extension_scope_spec_schema": EXTENSION_SCOPE_SPEC_SCHEMA,
        "typed_first_query_envelope_schema": EXTENSION_FIRST_QUERY_SCHEMA,
        "typed_first_result_envelope_schema": EXTENSION_FIRST_RESULT_SCHEMA,
        "candidate_visible_pre_reveal_fields": [
            "protocol",
            "commitment",
            "ciphertext_digest",
            "ciphertext_size_bytes",
        ],
        "required_primary_seal_components": [
            "candidate_bundle_digest",
            "model_digest",
            "primary_catalog_digest",
            "state_hashes",
            "state_snapshot_digest",
            "seal_digest",
        ],
        "revealed_source_material": "judge_custody_only_until_all_primary_seals",
    }
    return _exact_byte_preimage(
        "opaque-extension-protocol-schemas", canonical_json_bytes(descriptor)
    )


def _extension_scope_spec_contract_bytes(world_slot: str) -> bytes:
    contract = _extension_axis_contract(world_slot)
    return canonical_json_bytes(
        {
            "schema_version": "ucm-extension-scope-spec-contract/1",
            "typed_spec_schema": EXTENSION_SCOPE_SPEC_SCHEMA,
            "required_fields": [
                "schema_version",
                "world_slot",
                "source_scope_digest",
                "successor_scope_id",
                "axis_patches",
                "spec_digest",
            ],
            "required_changed_axes": list(contract["required_changed_axes"]),
            "allowed_non_D_changed_axes": list(
                contract["role_specific_allowed_changed_axes"]
            ),
            "patch_value_schema": "ScopeAxisDeclarations",
            "canonical_encoding": "strict_UTF8_canonical_JSON_plus_one_LF",
            "parser": "parse_extension_scope_spec_bytes",
            "successor_deriver": "derive_successor_scope_from_spec",
            "no_op_patch": "forbidden",
        }
    )


def _extension_template(world_slot: str, role_axes: tuple[str, ...]) -> dict[str, Any]:
    declaration = EXTENSION_WORLD_REGISTRY.get(world_slot)
    world_declaration = WORLD_REGISTRY.get(world_slot)
    if declaration is None or world_declaration is None:
        raise ProtocolViolation(f"extension world registry entry missing: {world_slot}")
    axis_contract = _extension_axis_contract(world_slot)
    if role_axes != axis_contract["role_specific_allowed_changed_axes"]:
        raise ProtocolViolation(
            f"extension role-axis contract drifted for {world_slot}"
        )
    extension_declaration_bytes = canonical_json_bytes(declaration.to_wire())
    world_declaration_bytes = canonical_json_bytes(world_declaration.to_wire())
    return {
        "schema_version": EXTENSION_TEMPLATE_SCHEMA,
        "world_slot": world_slot,
        "registry_declarations": {
            "world_registry": _exact_byte_preimage(
                f"{world_slot}-world-registry-declaration", world_declaration_bytes
            ),
            "extension_registry": _exact_byte_preimage(
                f"{world_slot}-extension-registry-declaration",
                extension_declaration_bytes,
            ),
        },
        "successor_axis_coverage": "all11",
        "successor_axis_order": list(SCOPE_AXES),
        "required_changed_axes": list(axis_contract["required_changed_axes"]),
        "extension_scope_spec_contract": _exact_byte_preimage(
            f"{world_slot}-extension-scope-spec-contract",
            _extension_scope_spec_contract_bytes(world_slot),
        ),
        "allowed_changed_axes": [*role_axes, "D"],
        "role_specific_allowed_changed_axes": list(role_axes),
        "potential_scope_axes": list(role_axes),
        "distance_derivation_contract_digest": distance_derivation_contract_digest(),
        "distance_axis_rule": "derive_and_verify_D_exactly_from_base_D_actual_non_D_diff_and_bound_metric_equivalence_semantics",
        "actual_expanded_scope": "excluded",
        "actual_axis_diff": "excluded",
    }


def _extension_set_wire(
    gaps: tuple[ProtocolGap, ...],
    successor_blockers: tuple[SuccessorRuntimeBlocker, ...],
) -> dict[str, Any]:
    _validate_executable_control_plane()
    _validate_live_extension_protocol_constants()
    if tuple(EXTENSION_WORLD_REGISTRY) != ("W16", "W17"):
        raise ProtocolViolation("extension world registry drifted from W16/W17")
    protocol = {
        "opaque_protocol_schemas": _extension_protocol_schema_preimage(),
        "source_closure": _source_closure(_EXTENSION_SOURCE_PATHS),
        "distance_derivation_contract": _exact_byte_preimage(
            "extension-distance-derivation-contract",
            distance_derivation_contract_bytes(),
        ),
        "chronology": [
            "authorize_base_S_and_template",
            "register_extension_template",
            "create_opaque_commitment_under_judge_custody",
            "materialize_primary_state_space_S",
            "seal_candidate_bundle",
            "seal_model_artifact",
            "seal_every_primary_state_instance",
            "seal_primary_result_root_before_extension_reveal",
            "reveal_only_after_candidate_model_and_state_seals",
            "derive_full_expanded_state_space_S_prime",
            "compute_exact_actual_scope_diff",
            "run_state_only_first_extension_query",
            "allow_optional_measured_migration_only_after_scope_insufficient",
            "emit_extension_only_score_without_rewriting_primary_scores",
        ],
        "reveal_gate": {
            "transition_seal_schema": EXTENSION_TRANSITION_SEAL_SCHEMA,
            "scope_reveal_schema": EXTENSION_SCOPE_REVEAL_SCHEMA,
            "candidate_bundle_seal_required": True,
            "model_artifact_seal_required": True,
            "all_primary_state_seals_required": True,
            "primary_result_root_seal_required": True,
            "primary_result_root_reveal_binding_required": True,
            "typed_verifier": "SuccessorReceipt.__post_init__",
            "reveal_before_all_seals": "forbidden",
        },
        "full_transition_derivation": {
            "formal_axis_order": list(SCOPE_AXES),
            "non_distance_axis_algorithm": [
                "validate_reveal_opens_the_registered_opaque_commitment",
                "parse_exact_typed_ExtensionScopeSpec_and_validate_required_and_allowed_axes",
                "validate_spec_source_scope_digest_against_exact_base_S",
                "apply_only_the_exact_typed_axis_patches_from_the_revealed_spec",
                "for_each_non_distance_axis_use_patch_value_if_present_else_the_exact_S_value",
                "reject_noop_patches_and_require_the_patch_axis_set_to_equal_the_exact_non_D_diff",
            ],
            "distance_axis_algorithm": [
                "parse_exact_code_owned_metric_registry_bytes",
                "derive_D_with_derive_successor_distance_axis_from_base_D_actual_non_D_diff_metric_registry_and_equivalence_source_closure",
                "verify_D_with_verify_successor_distance_axis_by_exact_canonical_bytes",
                "include_D_in_actual_diff_if_and_only_if_its_canonical_bytes_differ_from_S",
            ],
            "unlisted_axis_patch": "forbidden",
            "actual_patch": "excluded",
            "actual_expanded_state_space": "excluded",
        },
        "isolation": {
            "S_is_immutable_after_primary_seal": True,
            "S_prime_is_a_distinct_append_only_scope": True,
            "writeback_into_S": "forbidden",
            "writeback_into_primary_scores": "forbidden",
            "extension_scores": "separate_secondary_outputs",
            "extension_result_namespace": "separate_extension_only_namespace",
            "mixed_scope_aggregation": "forbidden",
            "source_target_scope_join": "fail_closed_exact_identity_join",
            "first_extension_query": "sealed_state_plus_typed_extension_query_only",
            "silent_history_replay": "forbidden",
        },
        "external_successor_artifacts": {
            "actual_scope_diff": {
                "schema_version": ACTUAL_SCOPE_DIFF_SCHEMA,
                "storage": "external_not_embedded_in_template",
                "parser": "parse_actual_scope_diff_bytes",
                "verifier": "ActualScopeDiff.__post_init__+verify_successor_distance_axis",
                "extension_scope_spec_schema": EXTENSION_SCOPE_SPEC_SCHEMA,
                "extension_scope_spec_parser": "parse_extension_scope_spec_bytes",
                "successor_deriver": "derive_successor_scope_from_spec",
                "successor_scope_manifest_schema": SCOPE_MANIFEST_SCHEMA,
                "successor_axis_order": list(SCOPE_AXES),
                "required_verifications": [
                    "parse_full_base_and_successor_eleven_axis_scope_manifests",
                    "base_scope_exact_bytes_unchanged",
                    "changed_axes_equal_exact_canonical_axis_byte_diff",
                    "required_changed_axes_are_present",
                    "actual_changed_axes_subset_of_template_allowed_changed_axes",
                    "revealed_typed_extension_spec_exactly_derives_all_non_D_changes",
                    "successor_D_exactly_replays_the_bound_distance_derivation_contract",
                ],
            },
            "successor_receipt": {
                "schema_version": SUCCESSOR_RECEIPT_SCHEMA,
                "storage": "external_not_embedded_in_template",
                "parser": "parse_successor_receipt_bytes",
                "verifier": "SuccessorReceipt.__post_init__",
                "transition_seal_schema": EXTENSION_TRANSITION_SEAL_SCHEMA,
                "scope_reveal_schema": EXTENSION_SCOPE_REVEAL_SCHEMA,
                "scope_request_schema": EXTENSION_SCOPE_REQUEST_SCHEMA,
                "scope_transcript_schema": EXTENSION_SCOPE_TRANSCRIPT_SCHEMA,
                "first_query_envelope_schema": EXTENSION_FIRST_QUERY_SCHEMA,
                "first_result_envelope_schema": EXTENSION_FIRST_RESULT_SCHEMA,
                "required_verifications": [
                    "base_scope_exact_bytes_unchanged",
                    "primary_result_root_is_exactly_equal_before_seal_reveal_and_after_extension",
                    "seal_reveal_diff_request_transcript_source_and_target_scope_identity_join_fail_closed",
                    "state_only_first_request_primary_state_hash_is_a_member_of_the_sealed_primary_state_set",
                    "typed_first_query_and_result_exact_preimages_join_request_and_transcript",
                    "revealed_extension_spec_bytes_equal_the_actual_diff_spec_bytes",
                    "state_only_first_query_precedes_optional_migration",
                    "optional_migration_requires_scope_insufficient",
                    "extension_outputs_use_a_separate_extension_only_namespace",
                    "mixed_scope_aggregation_forbidden",
                    "extension_score_is_separate_from_primary_score",
                ],
                "primary_aggregate_eligible": False,
                "runtime_binding_status": "successor_runtime_not_integrated",
                "successor_runtime_eligible": False,
            },
        },
        "templates": [
            _extension_template("W16", ("O", "Q", "Pi", "Gamma", "Y", "U", "R")),
            _extension_template("W17", ("A", "Pi", "U", "R")),
        ],
    }
    return {
        "schema_version": EXTENSION_TEMPLATE_SET_SCHEMA,
        "artifact_type": "UCM_EXTENSION_TEMPLATE_SET",
        "benchmark_status": "PRE-FREEZE",
        "authority_claim": "scope_independent_extension_templates_only",
        "scope_binding_status": "not_bound",
        "freeze_authority_status": "not_claimed",
        "protocol": protocol,
        "gap_count": len(gaps),
        "gaps": [gap.to_wire() for gap in gaps],
        "successor_blocker_count": len(successor_blockers),
        "successor_blockers": [blocker.to_wire() for blocker in successor_blockers],
    }


def _parse_gap_rows(value: object, label: str) -> tuple[ProtocolGap, ...]:
    if type(value) is not list:
        raise ProtocolViolation(f"{label} gaps must be an exact list")
    return tuple(ProtocolGap.from_wire(row) for row in value)


def _parse_post_scope_requirements(
    value: object,
) -> tuple[PostScopeRequirement, ...]:
    if type(value) is not list:
        raise ProtocolViolation("post_scope_requirements must be an exact list")
    return tuple(PostScopeRequirement.from_wire(row) for row in value)


def _parse_successor_blockers(value: object) -> tuple[SuccessorRuntimeBlocker, ...]:
    if type(value) is not list:
        raise ProtocolViolation("successor_blockers must be an exact list")
    return tuple(SuccessorRuntimeBlocker.from_wire(row) for row in value)


def _validate_preimages_in_split_wire(wire: dict[str, Any]) -> None:
    schemas = wire["protocol"]["family_and_generator_intent_schemas"]
    for name in (
        "family_definition_intent",
        "generator_intent",
        "family_unit_intent",
        "intent_and_split_policy",
    ):
        _decode_exact_byte_preimage(schemas[name], f"split {name}")
    _decode_exact_byte_preimage(
        wire["protocol"]["deterministic_derivation"]["algorithm_source"],
        "split algorithm source",
    )
    commitment = wire["protocol"]["commitment_protocol"]
    _decode_exact_byte_preimage(
        commitment["commit_reveal_protocol"], "split commit/reveal protocol"
    )
    _decode_exact_byte_preimage(
        commitment["per_panel_seed_kdf"], "split per-panel seed KDF"
    )
    seed = wire["protocol"]["zipped_seed_semantics"]
    _decode_exact_byte_preimage(seed["seed_protocol_preimage"], "seed protocol")
    _decode_exact_byte_preimage(
        seed["zipped_pairing_context_preimage"], "zipped pairing context"
    )
    _validate_source_closure(
        wire["protocol"]["deterministic_derivation"]["source_closure"],
        "split derivation",
    )


def _validate_preimages_in_extension_wire(wire: dict[str, Any]) -> None:
    protocol = wire["protocol"]
    _decode_exact_byte_preimage(
        protocol["opaque_protocol_schemas"], "opaque extension schemas"
    )
    _validate_source_closure(protocol["source_closure"], "extension template")
    for template in protocol["templates"]:
        declarations = template["registry_declarations"]
        _decode_exact_byte_preimage(
            declarations["world_registry"], "world registry declaration"
        )
        _decode_exact_byte_preimage(
            declarations["extension_registry"], "extension registry declaration"
        )
        spec_contract = _decode_exact_byte_preimage(
            template["extension_scope_spec_contract"],
            "extension scope spec contract",
        )
        if spec_contract != _extension_scope_spec_contract_bytes(
            template["world_slot"]
        ):
            raise ProtocolViolation("extension scope spec contract preimage drifted")
    distance_contract = _decode_exact_byte_preimage(
        protocol["distance_derivation_contract"],
        "distance derivation contract",
    )
    if distance_contract != distance_derivation_contract_bytes():
        raise ProtocolViolation("distance derivation contract preimage drifted")
    contract_wire = _decode_canonical_object(
        distance_contract, "distance derivation contract"
    )
    runtime_binding_bytes = _decode_exact_byte_preimage(
        contract_wire["metric_runtime_bindings"],
        "distance metric runtime bindings",
    )
    runtime_binding = parse_metric_runtime_bindings_bytes(
        runtime_binding_bytes,
        benchmark_v1_metric_target_registry().canonical_bytes,
    )
    _validate_source_closure(
        contract_wire["equivalence_source_closure"],
        "distance equivalence",
    )
    outer_members = {
        item["relative_path"]: item
        for item in contract_wire["equivalence_source_closure"]["members"]
    }
    inner_rows = runtime_binding.to_wire()["source_closure"]
    if type(inner_rows) is not list or not inner_rows:
        raise ProtocolViolation("metric runtime source closure is missing")
    seen_inner_paths: set[str] = set()
    for row in inner_rows:
        if type(row) is not dict or set(row) != {
            "path",
            "byte_count",
            "artifact_digest",
        }:
            raise ProtocolViolation("metric runtime source closure row is invalid")
        path = row["path"]
        outer = outer_members.get(path)
        if (
            type(path) is not str
            or path in seen_inner_paths
            or outer is None
            or outer["byte_count"] != row["byte_count"]
            or outer["digest"] != row["artifact_digest"]
        ):
            raise ProtocolViolation(
                "metric runtime source closure does not exact-join raw replay bytes"
            )
        seen_inner_paths.add(path)


@dataclass(frozen=True, slots=True)
class SplitDerivationProtocol:
    gaps: tuple[ProtocolGap, ...] = _SPLIT_GAPS
    post_scope_requirements: tuple[PostScopeRequirement, ...] = (
        _SPLIT_POST_SCOPE_REQUIREMENTS
    )

    _EXPECTED_GAPS: ClassVar[tuple[ProtocolGap, ...]] = _SPLIT_GAPS
    _EXPECTED_POST_SCOPE_REQUIREMENTS: ClassVar[tuple[PostScopeRequirement, ...]] = (
        _SPLIT_POST_SCOPE_REQUIREMENTS
    )

    def __post_init__(self) -> None:
        if (
            self.gaps != self._EXPECTED_GAPS
            or self.post_scope_requirements != self._EXPECTED_POST_SCOPE_REQUIREMENTS
        ):
            raise ProtocolViolation("split derivation gaps are not code-owned")

    @property
    def gap_count(self) -> int:
        return len(self.gaps)

    @property
    def post_scope_requirement_count(self) -> int:
        return len(self.post_scope_requirements)

    def to_wire(self) -> dict[str, Any]:
        _validate_executable_control_plane()
        cached = _FINAL_ARTIFACT_CACHE.split_bytes
        if type(cached) is bytes:
            _validate_live_source_inventory(_SPLIT_SOURCE_PATHS)
            return copy.deepcopy(
                _decode_canonical_object(cached, "cached split derivation protocol")
            )
        return copy.deepcopy(
            _split_protocol_wire(self.gaps, self.post_scope_requirements)
        )

    @property
    def canonical_bytes(self) -> bytes:
        _validate_executable_control_plane()
        cached = _FINAL_ARTIFACT_CACHE.split_bytes
        if type(cached) is bytes:
            _validate_live_source_inventory(_SPLIT_SOURCE_PATHS)
            return cached
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return domain_digest(SPLIT_DERIVATION_DOMAIN, (self.canonical_bytes,))

    @classmethod
    def from_wire(cls, value: object) -> "SplitDerivationProtocol":
        wire = _exact_object(value, _SPLIT_TOP_LEVEL_KEYS, "split derivation protocol")
        gaps = _parse_gap_rows(wire["gaps"], "split derivation")
        requirements = _parse_post_scope_requirements(wire["post_scope_requirements"])
        result = cls(gaps, requirements)
        if type(wire["gap_count"]) is not int or wire["gap_count"] != len(gaps):
            raise ProtocolViolation("split derivation gap_count mismatch")
        if type(wire["post_scope_requirement_count"]) is not int or wire[
            "post_scope_requirement_count"
        ] != len(requirements):
            raise ProtocolViolation("split post-scope requirement_count mismatch")
        _validate_preimages_in_split_wire(wire)
        if canonical_json_bytes(wire) != result.canonical_bytes:
            raise ProtocolViolation("split derivation differs from code-owned protocol")
        return result


@dataclass(frozen=True, slots=True)
class ExtensionTemplateSet:
    gaps: tuple[ProtocolGap, ...] = _EXTENSION_GAPS
    successor_blockers: tuple[SuccessorRuntimeBlocker, ...] = (
        _EXTENSION_SUCCESSOR_BLOCKERS
    )

    _EXPECTED_GAPS: ClassVar[tuple[ProtocolGap, ...]] = _EXTENSION_GAPS
    _EXPECTED_SUCCESSOR_BLOCKERS: ClassVar[tuple[SuccessorRuntimeBlocker, ...]] = (
        _EXTENSION_SUCCESSOR_BLOCKERS
    )

    def __post_init__(self) -> None:
        if (
            self.gaps != self._EXPECTED_GAPS
            or self.successor_blockers != self._EXPECTED_SUCCESSOR_BLOCKERS
        ):
            raise ProtocolViolation("extension template gaps are not code-owned")

    @property
    def gap_count(self) -> int:
        return len(self.gaps)

    @property
    def successor_blocker_count(self) -> int:
        return len(self.successor_blockers)

    def to_wire(self) -> dict[str, Any]:
        _validate_executable_control_plane()
        cached = _FINAL_ARTIFACT_CACHE.extension_bytes
        if type(cached) is bytes:
            _validate_live_source_inventory(_EXTENSION_SOURCE_PATHS)
            return copy.deepcopy(
                _decode_canonical_object(cached, "cached extension template set")
            )
        return copy.deepcopy(_extension_set_wire(self.gaps, self.successor_blockers))

    @property
    def canonical_bytes(self) -> bytes:
        _validate_executable_control_plane()
        cached = _FINAL_ARTIFACT_CACHE.extension_bytes
        if type(cached) is bytes:
            _validate_live_source_inventory(_EXTENSION_SOURCE_PATHS)
            return cached
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return domain_digest(EXTENSION_TEMPLATE_SET_DOMAIN, (self.canonical_bytes,))

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionTemplateSet":
        wire = _exact_object(value, _EXTENSION_TOP_LEVEL_KEYS, "extension template set")
        gaps = _parse_gap_rows(wire["gaps"], "extension template set")
        blockers = _parse_successor_blockers(wire["successor_blockers"])
        result = cls(gaps, blockers)
        if type(wire["gap_count"]) is not int or wire["gap_count"] != len(gaps):
            raise ProtocolViolation("extension template gap_count mismatch")
        if type(wire["successor_blocker_count"]) is not int or wire[
            "successor_blocker_count"
        ] != len(blockers):
            raise ProtocolViolation("extension successor_blocker_count mismatch")
        _validate_preimages_in_extension_wire(wire)
        if canonical_json_bytes(wire) != result.canonical_bytes:
            raise ProtocolViolation(
                "extension template set differs from code-owned protocol"
            )
        return result


def build_split_derivation_protocol() -> SplitDerivationProtocol:
    _validate_executable_control_plane()
    return SplitDerivationProtocol()


def parse_split_derivation_protocol_bytes(payload: bytes) -> SplitDerivationProtocol:
    _validate_executable_control_plane()
    return SplitDerivationProtocol.from_wire(
        _decode_canonical_object(payload, "split derivation protocol")
    )


def split_derivation_artifact_digest_from_bytes(payload: bytes) -> str:
    parsed = parse_split_derivation_protocol_bytes(payload)
    return digest_bytes(parsed.canonical_bytes)


def split_derivation_semantic_digest_from_bytes(payload: bytes) -> str:
    parsed = parse_split_derivation_protocol_bytes(payload)
    return domain_digest(SPLIT_DERIVATION_DOMAIN, (parsed.canonical_bytes,))


def build_extension_template_set() -> ExtensionTemplateSet:
    _validate_executable_control_plane()
    return ExtensionTemplateSet()


def parse_extension_template_set_bytes(payload: bytes) -> ExtensionTemplateSet:
    _validate_executable_control_plane()
    return ExtensionTemplateSet.from_wire(
        _decode_canonical_object(payload, "extension template set")
    )


def extension_template_set_artifact_digest_from_bytes(payload: bytes) -> str:
    parsed = parse_extension_template_set_bytes(payload)
    return digest_bytes(parsed.canonical_bytes)


def extension_template_set_semantic_digest_from_bytes(payload: bytes) -> str:
    parsed = parse_extension_template_set_bytes(payload)
    return domain_digest(EXTENSION_TEMPLATE_SET_DOMAIN, (parsed.canonical_bytes,))


def _panel_seed_control_wire_from_namespace(namespace: object) -> dict[str, Any]:
    def attr(name: str) -> Any:
        if type(namespace) is dict:
            return namespace[name]
        return getattr(namespace, name)

    panel_keys = attr("EXPECTED_PANEL_TASK_KEYS")
    authority_split = attr("AuthoritySplit")
    context_type = attr("SplitSeedCommitmentContext")
    return {
        "panel_task_keys": [
            [world, panel, task.value] for world, panel, task in panel_keys
        ],
        "panel_count": attr("PANEL_COUNT"),
        "task_count": attr("TASK_COUNT"),
        "partitions_per_authority": attr("PARTITIONS_PER_AUTHORITY"),
        "zipped_slots_per_partition": attr("ZIPPED_SHARD_SLOTS_PER_PARTITION"),
        "authority_splits": [item.value for item in authority_split],
        "schemas": {
            "family_definition": attr("FAMILY_DEFINITION_PROTOCOL"),
            "generator_intent": attr("GENERATOR_INTENT_PROTOCOL"),
            "intent_policy": attr("INTENT_POLICY_PROTOCOL"),
            "split_policy": attr("SPLIT_POLICY_PROTOCOL"),
            "split_seed_context": attr("SPLIT_SEED_CONTEXT_PROTOCOL"),
        },
        "zipped_pairing_context": attr(
            "CODE_OWNED_ZIPPED_SEED_PAIRING_CONTEXT"
        ).to_wire(),
        "commitment_scheme_default": context_type.__dataclass_fields__[
            "commitment_scheme"
        ].default,
        "commitment_stage_default": context_type.__dataclass_fields__[
            "commitment_stage"
        ].default,
    }


def _seed_control_wire_from_namespace(namespace: object) -> dict[str, Any]:
    def attr(name: str) -> Any:
        if type(namespace) is dict:
            return namespace[name]
        return getattr(namespace, name)

    manifest = attr("SEED_PROTOCOL_MANIFEST_BYTES")
    return {
        "seed_protocol_manifest": _exact_byte_preimage(
            "seed-protocol-control-plane", manifest
        ),
        "seed_protocol_digest": attr("SEED_PROTOCOL_DIGEST"),
        "zipped_replicate_ids": [list(item) for item in attr("ZIPPED_REPLICATE_IDS")],
    }


def _registry_control_wire(
    world_registry: object, extension_registry: object
) -> dict[str, Any]:
    return {
        "world_registry_keys": list(world_registry),
        "extension_registry_keys": list(extension_registry),
        "W16_world": world_registry["W16"].to_wire(),
        "W17_world": world_registry["W17"].to_wire(),
        "W16_extension": extension_registry["W16"].to_wire(),
        "W17_extension": extension_registry["W17"].to_wire(),
    }


def _function_runtime_surface(value: object) -> tuple[object, ...]:
    """Capture identity plus mutable executable slots of one Python function."""

    if not inspect.isfunction(value):
        raise ProtocolViolation("runtime surface member is not a Python function")
    return (
        value,
        value.__code__,
        None if value.__defaults__ is None else tuple(value.__defaults__),
        (
            None
            if value.__kwdefaults__ is None
            else tuple(sorted(value.__kwdefaults__.items()))
        ),
        tuple(sorted(value.__annotations__.items())),
        (
            None
            if value.__closure__ is None
            else tuple(cell.cell_contents for cell in value.__closure__)
        ),
    )


def _class_runtime_surface(value: object) -> tuple[tuple[object, ...], ...]:
    """Capture executable descriptors that can alter a typed DTO at runtime."""

    if not inspect.isclass(value):
        raise ProtocolViolation("runtime surface member is not a Python class")
    rows: list[tuple[object, ...]] = []
    for name, member in sorted(vars(value).items()):
        if inspect.isfunction(member):
            rows.append((name, "function", *_function_runtime_surface(member)))
        elif type(member) is classmethod:
            rows.append(
                (
                    name,
                    "classmethod",
                    member,
                    *_function_runtime_surface(member.__func__),
                )
            )
        elif type(member) is staticmethod:
            rows.append(
                (
                    name,
                    "staticmethod",
                    member,
                    *_function_runtime_surface(member.__func__),
                )
            )
        elif type(member) is property:
            accessors = tuple(
                None if item is None else _function_runtime_surface(item)
                for item in (member.fget, member.fset, member.fdel)
            )
            rows.append((name, "property", member, accessors))
    return tuple(rows)


def _namespace_runtime_surface(
    namespace: dict[str, Any], module_name: str
) -> tuple[tuple[object, ...], ...]:
    """Capture all module-owned functions/classes used by a dependency."""

    rows: list[tuple[object, ...]] = []
    for name, value in sorted(namespace.items()):
        # This function's own binding is not available while its default
        # local-module snapshot is being evaluated.
        if name == "_validate_executable_control_plane" or (
            module_name == __name__ and name in _FINAL_WRAPPED_ENTRYPOINT_NAMES
        ):
            continue
        if inspect.isfunction(value) and value.__module__ == module_name:
            rows.append((name, "function", *_function_runtime_surface(value)))
        elif inspect.isclass(value) and value.__module__ == module_name:
            rows.append((name, "class", value, _class_runtime_surface(value)))
    return tuple(rows)


def _validate_namespace_runtime_surface(
    namespace: dict[str, Any],
    module_name: str,
    expected: tuple[tuple[object, ...], ...],
) -> None:
    current = _namespace_runtime_surface(namespace, module_name)
    if len(current) != len(expected):
        raise ProtocolViolation(f"runtime dependency surface drifted: {module_name}")
    for current_row, expected_row in zip(current, expected, strict=True):
        if len(current_row) != len(expected_row):
            raise ProtocolViolation(
                f"runtime dependency surface drifted: {module_name}"
            )
        for current_item, expected_item in zip(current_row, expected_row, strict=True):
            if current_item is expected_item:
                continue
            if (
                type(current_item) in {str, type(None)}
                and current_item == expected_item
            ):
                continue
            if type(current_item) is tuple and current_item == expected_item:
                continue
            raise ProtocolViolation(
                f"runtime dependency surface drifted: {module_name}"
            )


def _data_control_wire(value: object) -> Any:
    """Make a detached JSON-like snapshot of deterministic control data."""

    if value is None or type(value) in {bool, int, float, str}:
        return value
    if type(value) is bytes:
        return {"kind": "bytes", "hex": value.hex()}
    if isinstance(value, Enum):
        return {
            "kind": "enum",
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _data_control_wire(value.value),
        }
    if isinstance(value, re.Pattern):
        return {
            "kind": "regex",
            "pattern": value.pattern,
            "flags": value.flags,
        }
    if type(value) is Path:
        return {"kind": "path", "value": str(value)}
    if type(value) in {tuple, list}:
        return {
            "kind": "tuple" if type(value) is tuple else "list",
            "items": [_data_control_wire(item) for item in value],
        }
    if type(value) in {frozenset, set}:
        items = [_data_control_wire(item) for item in value]
        items.sort(key=canonical_json_bytes)
        return {
            "kind": "frozenset" if type(value) is frozenset else "set",
            "items": items,
        }
    if type(value) in {dict, MappingProxyType}:
        items = [
            {
                "key": _data_control_wire(key),
                "value": _data_control_wire(item),
            }
            for key, item in value.items()
        ]
        items.sort(key=canonical_json_bytes)
        return {
            "kind": "mappingproxy" if type(value) is MappingProxyType else "dict",
            "items": items,
        }
    to_wire = getattr(value, "to_wire", None)
    if callable(to_wire):
        wire = to_wire()
        validate_json_like(wire, path="dependency data control")
        return {
            "kind": "typed_wire",
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "wire": copy.deepcopy(wire),
        }
    raise ProtocolViolation(
        "dependency data control contains an unsupported exact type: "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _module_data_control_bytes(module: object, names: tuple[str, ...]) -> bytes:
    if type(names) is not tuple or names != tuple(sorted(set(names))):
        raise ProtocolViolation("dependency data control names are not canonical")
    rows = []
    for name in names:
        if not hasattr(module, name):
            raise ProtocolViolation(f"dependency data control is missing {name}")
        rows.append({"name": name, "value": _data_control_wire(getattr(module, name))})
    return canonical_json_bytes(rows)


_CODE_OWNED_DEPENDENCY_RUNTIME_SURFACES = (
    (
        _canonical_module,
        _namespace_runtime_surface(vars(_canonical_module), _canonical_module.__name__),
    ),
    (
        _extensions_module,
        _namespace_runtime_surface(
            vars(_extensions_module), _extensions_module.__name__
        ),
    ),
    (
        _metric_configuration_module,
        _namespace_runtime_surface(
            vars(_metric_configuration_module),
            _metric_configuration_module.__name__,
        ),
    ),
    (
        _metric_runtime_bindings_module,
        _namespace_runtime_surface(
            vars(_metric_runtime_bindings_module),
            _metric_runtime_bindings_module.__name__,
        ),
    ),
    (
        _panel_split_authority_module,
        _namespace_runtime_surface(
            vars(_panel_split_authority_module),
            _panel_split_authority_module.__name__,
        ),
    ),
    (
        _scope_manifest_module,
        _namespace_runtime_surface(
            vars(_scope_manifest_module), _scope_manifest_module.__name__
        ),
    ),
    (
        _seed_protocol_module,
        _namespace_runtime_surface(
            vars(_seed_protocol_module), _seed_protocol_module.__name__
        ),
    ),
    (
        _world_registry_module,
        _namespace_runtime_surface(
            vars(_world_registry_module), _world_registry_module.__name__
        ),
    ),
)

_PANEL_DATA_CONTROL_NAMES = tuple(
    sorted(
        (
            "ASSIGNMENT_AUTHORITY_COUNT",
            "CODE_OWNED_ZIPPED_SEED_PAIRING_CONTEXT",
            "EXPECTED_PANEL_TASK_KEYS",
            "FAMILY_ASSIGNMENT_PROTOCOL",
            "FAMILY_DEFINITION_PROTOCOL",
            "FAMILY_INTENT_PROTOCOL",
            "GENERATOR_INTENT_PROTOCOL",
            "GLOBAL_ASSIGNMENT_SET_PROTOCOL",
            "GLOBAL_PARTITION_SET_PROTOCOL",
            "INCOMPLETE_CODE",
            "INTENT_POLICY_PROTOCOL",
            "PANEL_COUNT",
            "PARTITIONS_PER_AUTHORITY",
            "PARTITION_AUTHORITY_COUNT",
            "PARTITION_PROTOCOL",
            "SEED_PROTOCOL_DIGEST",
            "SEED_PROTOCOL_MANIFEST_BYTES",
            "SPLIT_POLICY_PROTOCOL",
            "SPLIT_SEED_CONTEXT_PROTOCOL",
            "STRATA_PREIMAGE_SET_PROTOCOL",
            "TASK_COUNT",
            "ZIPPED_PANEL_CONTEXT_PROTOCOL",
            "ZIPPED_REPLICATE_IDS",
            "ZIPPED_SHARD_SLOTS_PER_PARTITION",
            "_ASSIGNMENT_DOMAIN",
            "_ASSIGNMENT_SET_DOMAIN",
            "_DIGEST_RE",
            "_FAMILY_INTENT_DOMAIN",
            "_IDENTITY_DOMAIN",
            "_IDENTITY_RE",
            "_LEGACY_STRATA_BLOCKERS",
            "_PARTITION_DOMAIN",
            "_PARTITION_SET_DOMAIN",
            "_PHYSICAL_ASSIGNMENT_DOMAIN",
            "_SEMANTIC_PANEL_SPLIT_SLOT_DOMAIN",
            "_SHARD_DOMAIN",
            "_STATUS_WIRE",
            "_STRATA_PREIMAGE_SET_DOMAIN",
            "_STRATA_ROOT_FIELDS",
            "_STRATA_ROOT_IDS",
            "_STRATA_ROOT_KEYS",
            "_UNIT_INTENT_DOMAIN",
            "_ZIPPED_PANEL_CONTEXT_DOMAIN",
        )
    )
)
_METRIC_CONFIGURATION_DATA_CONTROL_NAMES = tuple(
    sorted(
        (
            "METRIC_TARGET_AUTHORITY_CLAIM",
            "METRIC_TARGET_BENCHMARK_ID",
            "METRIC_TARGET_BENCHMARK_STATUS",
            "METRIC_TARGET_DOMAIN",
            "METRIC_TARGET_FREEZE_AUTHORITY",
            "METRIC_TARGET_REVISION",
            "METRIC_TARGET_RUNTIME_BINDING",
            "METRIC_TARGET_SCHEMA",
            "METRIC_TARGET_SEMANTIC_READY",
            "OUTPUT_REQUIRED_DIMENSIONS",
            "_BLOCKERS",
            "_CONDITIONAL_HARD_GATE_OUTPUTS",
            "_GLOBAL_TARGET_GAPS",
            "_MEASUREMENT_TRUTH",
            "_TOP_LEVEL_KEYS",
        )
    )
)
_METRIC_RUNTIME_DATA_CONTROL_NAMES = tuple(
    sorted(
        (
            "AGGREGATE_SCORE",
            "ARTIFACT_DOMAIN",
            "AUTHORITY_CLAIM",
            "BENCHMARK_ID",
            "BENCHMARK_STATUS",
            "BINDING_SET_DOMAIN",
            "EVALUATOR_BINDING",
            "FREEZE_AUTHORITY",
            "SCHEMA_VERSION",
            "SOURCE_CLOSURE_DOMAIN",
            "TARGET_OBJECT_DOMAIN",
            "_ALWAYS_REMAINING_BLOCKERS",
            "_IMPORTED_CONTROL_PLANE_ATTESTATION_BYTES",
            "_IMPORTED_CONTROL_PLANE_ATTESTATION_DIGEST",
            "_IMPORTED_SOURCE_DIGESTS",
            "_REMAINING_GLOBAL_GAPS",
            "_SOURCE_PATHS",
            "_TOP_LEVEL_KEYS",
        )
    )
)
_SCOPE_DATA_CONTROL_NAMES = tuple(
    sorted(
        (
            "SCOPE_AXES",
            "SCOPE_DOMAIN",
            "SCOPE_MANIFEST_SCHEMA",
            "_AXIS_KEYS",
            "_DECLARATION_KEYS",
            "_TOP_LEVEL_KEYS",
        )
    )
)
_EXTENSIONS_DATA_CONTROL_NAMES = tuple(
    sorted(
        (
            "COMMIT_PROTOCOL",
            "FIRST_QUERY_PROTOCOL",
            "MIGRATION_PROTOCOL",
            "PRIMARY_SEAL_PROTOCOL",
            "REVEAL_PROTOCOL",
            "_COMMIT_DOMAIN",
            "_STREAM_DOMAIN",
            "_TAG_DOMAIN",
            "_TREE_DOMAIN",
        )
    )
)
_SEED_DATA_CONTROL_NAMES = tuple(
    sorted(
        (
            "COMMITMENT_CONTEXT_PROTOCOL",
            "EVALUATION_REPLICATE_IDS",
            "FROZEN_BENCHMARK_REVISION",
            "OFFICIAL_COMMITMENT_HASH_DOMAIN",
            "OFFICIAL_SEED_DOMAINS",
            "SEED_PROTOCOL_DIGEST",
            "SEED_PROTOCOL_MANIFEST_BYTES",
            "SEED_PROTOCOL_VERSION",
            "TRAIN5_PRECOMMIT_ARTIFACT_TYPE",
            "TRAIN5_PRECOMMIT_PROTOCOL",
            "TRAIN5_PRECOMMIT_STAGE",
            "TRAINING_REPLICATE_IDS",
            "ZIPPED_PAIRING_PROTOCOL",
            "ZIPPED_REPLICATE_IDS",
            "_DIGEST_RE",
            "_EVALUATION_PANEL_DOMAIN",
            "_EVALUATION_PANEL_DOMAINS",
            "_EVALUATION_TUPLE_DOMAIN",
            "_IDENTITY_RE",
            "_PAIRING_AUTHORITY_DOMAIN",
            "_SEED_PROTOCOL_MANIFEST_WIRE",
            "_TRAINING_PANEL_DOMAIN",
            "_TRAINING_PANEL_DOMAINS",
            "_TRAINING_TUPLE_DOMAIN",
            "_UTC_TIMESTAMP_RE",
        )
    )
)
_WORLD_REGISTRY_DATA_CONTROL_NAMES = tuple(
    sorted(
        (
            "DEFAULT_SPLIT_SIZES",
            "EXTENSION_WORLD_REGISTRY",
            "PRIVILEGED_FIELD_NAMES",
            "WORLD_REGISTRY",
            "_DECLARATIONS",
        )
    )
)
_CODE_OWNED_DEPENDENCY_DATA_CONTROLS = tuple(
    (
        module,
        names,
        _module_data_control_bytes(module, names),
    )
    for module, names in (
        (_extensions_module, _EXTENSIONS_DATA_CONTROL_NAMES),
        (_metric_configuration_module, _METRIC_CONFIGURATION_DATA_CONTROL_NAMES),
        (_metric_runtime_bindings_module, _METRIC_RUNTIME_DATA_CONTROL_NAMES),
        (_panel_split_authority_module, _PANEL_DATA_CONTROL_NAMES),
        (_scope_manifest_module, _SCOPE_DATA_CONTROL_NAMES),
        (_seed_protocol_module, _SEED_DATA_CONTROL_NAMES),
        (_world_registry_module, _WORLD_REGISTRY_DATA_CONTROL_NAMES),
    )
)


def _validate_executable_control_plane(
    expected_callables: tuple[tuple[str, object], ...] = (
        ("canonical_json_bytes", canonical_json_bytes),
        ("digest_bytes", digest_bytes),
        ("domain_digest", domain_digest),
        ("benchmark_v1_metric_target_registry", benchmark_v1_metric_target_registry),
        ("parse_metric_target_registry_bytes", parse_metric_target_registry_bytes),
        ("benchmark_v1_metric_runtime_bindings", benchmark_v1_metric_runtime_bindings),
        ("parse_metric_runtime_bindings_bytes", parse_metric_runtime_bindings_bytes),
        ("parse_scope_manifest_bytes", parse_scope_manifest_bytes),
        ("ScopeManifest", ScopeManifest),
        ("ScopeAxisDeclarations", ScopeAxisDeclarations),
        ("ScopeDeclaration", ScopeDeclaration),
        ("AuthoritySplit", AuthoritySplit),
        ("FamilyDefinitionIntent", FamilyDefinitionIntent),
        ("GeneratorIntent", GeneratorIntent),
        ("PanelPhysicalIdentity", PanelPhysicalIdentity),
        ("SplitPolicyContext", SplitPolicyContext),
        ("SplitSeedCommitmentContext", SplitSeedCommitmentContext),
        ("SplitNeutralFamilyUnitIntent", SplitNeutralFamilyUnitIntent),
        ("SplitDerivationUnit", SplitDerivationUnit),
        ("SplitAssignmentDerivation", SplitAssignmentDerivation),
        ("_length_frame", _length_frame),
        ("_hkdf_sha256_extract_expand", _hkdf_sha256_extract_expand),
        ("_group_priority", _group_priority),
        ("compute_split_seed_commitment", compute_split_seed_commitment),
        ("derive_panel_split_seed", derive_panel_split_seed),
        ("derive_panel_family_assignments", derive_panel_family_assignments),
        ("verify_panel_family_assignments", verify_panel_family_assignments),
        ("_split_algorithm_semantics", _split_algorithm_semantics),
        ("derive_successor_distance_axis", derive_successor_distance_axis),
        ("verify_successor_distance_axis", verify_successor_distance_axis),
        ("derive_successor_scope_from_spec", derive_successor_scope_from_spec),
        ("parse_extension_scope_spec_bytes", parse_extension_scope_spec_bytes),
        ("_source_closure", _source_closure),
        (
            "_panel_seed_control_wire_from_namespace",
            _panel_seed_control_wire_from_namespace,
        ),
        ("_seed_control_wire_from_namespace", _seed_control_wire_from_namespace),
        ("_registry_control_wire", _registry_control_wire),
        ("_function_runtime_surface", _function_runtime_surface),
        ("_class_runtime_surface", _class_runtime_surface),
        ("_namespace_runtime_surface", _namespace_runtime_surface),
        ("_validate_namespace_runtime_surface", _validate_namespace_runtime_surface),
        ("_data_control_wire", _data_control_wire),
        ("_module_data_control_bytes", _module_data_control_bytes),
    ),
    expected_kat_seed: bytes = _SPLIT_KNOWN_SEED,
    expected_kat_nonce: bytes = _SPLIT_KNOWN_NONCE,
    expected_kat_answer_bytes: bytes = canonical_json_bytes(
        _SPLIT_KNOWN_ANSWER_EXPECTED
    ),
    expected_panel_control_bytes: bytes = canonical_json_bytes(
        _panel_seed_control_wire_from_namespace(globals())
    ),
    expected_seed_control_bytes: bytes = canonical_json_bytes(
        _seed_control_wire_from_namespace(globals())
    ),
    expected_registry_control_bytes: bytes = canonical_json_bytes(
        _registry_control_wire(WORLD_REGISTRY, EXTENSION_WORLD_REGISTRY)
    ),
    expected_gap_and_followup_control_bytes: bytes = canonical_json_bytes(
        {
            "split_gaps": [item.to_wire() for item in _SPLIT_GAPS],
            "split_post_scope_requirements": [
                item.to_wire() for item in _SPLIT_POST_SCOPE_REQUIREMENTS
            ],
            "extension_gaps": [item.to_wire() for item in _EXTENSION_GAPS],
            "extension_successor_blockers": [
                item.to_wire() for item in _EXTENSION_SUCCESSOR_BLOCKERS
            ],
        }
    ),
    expected_dependency_runtime_surfaces: tuple[
        tuple[object, tuple[tuple[object, ...], ...]], ...
    ] = _CODE_OWNED_DEPENDENCY_RUNTIME_SURFACES,
    expected_dependency_data_controls: tuple[
        tuple[object, tuple[str, ...], bytes], ...
    ] = _CODE_OWNED_DEPENDENCY_DATA_CONTROLS,
    expected_final_artifact_cache: _FinalArtifactCache = _FINAL_ARTIFACT_CACHE,
    expected_local_runtime_surface: tuple[tuple[object, ...], ...] = (
        _namespace_runtime_surface(globals(), __name__)
    ),
) -> None:
    _validate_protocol_control_plane()
    if _FINAL_ARTIFACT_CACHE is not expected_final_artifact_cache:
        raise ProtocolViolation("final artifact cache identity drifted")
    expected_final_artifact_cache.validate_live_globals(globals())
    for name, expected in expected_callables:
        live = globals().get(name)
        if (
            live is not expected
            and getattr(live, "__ucm_sealed_original__", None) is not expected
        ):
            raise ProtocolViolation(f"executable control plane drifted: {name}")
    _validate_namespace_runtime_surface(
        globals(), __name__, expected_local_runtime_surface
    )
    for module, expected_surface in expected_dependency_runtime_surfaces:
        _validate_namespace_runtime_surface(
            vars(module), module.__name__, expected_surface
        )
    for module, names, expected_bytes in expected_dependency_data_controls:
        if _module_data_control_bytes(module, names) != expected_bytes:
            raise ProtocolViolation(
                f"runtime dependency data drifted: {module.__name__}"
            )
    if (
        _canonical_module.canonical_json_bytes is not canonical_json_bytes
        or _canonical_module.digest_bytes is not digest_bytes
        or _canonical_module.domain_digest is not domain_digest
        or _metric_configuration_module.benchmark_v1_metric_target_registry
        is not benchmark_v1_metric_target_registry
        or _metric_configuration_module.parse_metric_target_registry_bytes
        is not parse_metric_target_registry_bytes
        or _metric_configuration_module.METRIC_TARGET_DOMAIN != METRIC_TARGET_DOMAIN
        or _metric_runtime_bindings_module.benchmark_v1_metric_runtime_bindings
        is not benchmark_v1_metric_runtime_bindings
        or _metric_runtime_bindings_module.parse_metric_runtime_bindings_bytes
        is not parse_metric_runtime_bindings_bytes
        or _metric_runtime_bindings_module.ARTIFACT_DOMAIN
        != METRIC_RUNTIME_ARTIFACT_DOMAIN
        or _scope_manifest_module.parse_scope_manifest_bytes
        is not parse_scope_manifest_bytes
        or _scope_manifest_module.ScopeManifest is not ScopeManifest
        or _scope_manifest_module.ScopeAxisDeclarations is not ScopeAxisDeclarations
        or _scope_manifest_module.ScopeDeclaration is not ScopeDeclaration
        or _scope_manifest_module.SCOPE_DOMAIN != SCOPE_DOMAIN
        or _scope_manifest_module.SCOPE_AXES != SCOPE_AXES
        or _scope_manifest_module.SCOPE_MANIFEST_SCHEMA != SCOPE_MANIFEST_SCHEMA
    ):
        raise ProtocolViolation("live runtime dependency identity drifted")
    if (
        _SPLIT_KNOWN_SEED != expected_kat_seed
        or _SPLIT_KNOWN_NONCE != expected_kat_nonce
        or canonical_json_bytes(_SPLIT_KNOWN_ANSWER_EXPECTED)
        != expected_kat_answer_bytes
    ):
        raise ProtocolViolation("split known-answer control plane drifted")
    gap_and_followup_control_bytes = canonical_json_bytes(
        {
            "split_gaps": [item.to_wire() for item in _SPLIT_GAPS],
            "split_post_scope_requirements": [
                item.to_wire() for item in _SPLIT_POST_SCOPE_REQUIREMENTS
            ],
            "extension_gaps": [item.to_wire() for item in _EXTENSION_GAPS],
            "extension_successor_blockers": [
                item.to_wire() for item in _EXTENSION_SUCCESSOR_BLOCKERS
            ],
        }
    )
    if (
        gap_and_followup_control_bytes != expected_gap_and_followup_control_bytes
        or SplitDerivationProtocol._EXPECTED_GAPS != _SPLIT_GAPS
        or SplitDerivationProtocol._EXPECTED_POST_SCOPE_REQUIREMENTS
        != _SPLIT_POST_SCOPE_REQUIREMENTS
        or ExtensionTemplateSet._EXPECTED_GAPS != _EXTENSION_GAPS
        or ExtensionTemplateSet._EXPECTED_SUCCESSOR_BLOCKERS
        != _EXTENSION_SUCCESSOR_BLOCKERS
    ):
        raise ProtocolViolation("gap/followup control plane drifted")
    if (
        canonical_json_bytes(_panel_seed_control_wire_from_namespace(globals()))
        != expected_panel_control_bytes
        or canonical_json_bytes(
            _panel_seed_control_wire_from_namespace(_panel_split_authority_module)
        )
        != expected_panel_control_bytes
    ):
        raise ProtocolViolation("panel split inventory control plane drifted")
    if (
        canonical_json_bytes(_seed_control_wire_from_namespace(globals()))
        != expected_seed_control_bytes
        or canonical_json_bytes(
            _seed_control_wire_from_namespace(_seed_protocol_module)
        )
        != expected_seed_control_bytes
    ):
        raise ProtocolViolation("seed protocol control plane drifted")
    if (
        canonical_json_bytes(
            _registry_control_wire(WORLD_REGISTRY, EXTENSION_WORLD_REGISTRY)
        )
        != expected_registry_control_bytes
        or canonical_json_bytes(
            _registry_control_wire(
                _world_registry_module.WORLD_REGISTRY,
                _world_registry_module.EXTENSION_WORLD_REGISTRY,
            )
        )
        != expected_registry_control_bytes
    ):
        raise ProtocolViolation("world/extension registry control plane drifted")
    _validate_live_extension_protocol_constants()


SPLIT_DERIVATION_PROTOCOL_BYTES = build_split_derivation_protocol().canonical_bytes
SPLIT_DERIVATION_ARTIFACT_DIGEST = digest_bytes(SPLIT_DERIVATION_PROTOCOL_BYTES)
SPLIT_DERIVATION_SEMANTIC_DIGEST = domain_digest(
    SPLIT_DERIVATION_DOMAIN, (SPLIT_DERIVATION_PROTOCOL_BYTES,)
)
EXTENSION_TEMPLATE_SET_BYTES = build_extension_template_set().canonical_bytes
EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST = digest_bytes(EXTENSION_TEMPLATE_SET_BYTES)
EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST = domain_digest(
    EXTENSION_TEMPLATE_SET_DOMAIN, (EXTENSION_TEMPLATE_SET_BYTES,)
)
_FINAL_ARTIFACT_CACHE.seal(
    SPLIT_DERIVATION_PROTOCOL_BYTES,
    SPLIT_DERIVATION_ARTIFACT_DIGEST,
    SPLIT_DERIVATION_SEMANTIC_DIGEST,
    EXTENSION_TEMPLATE_SET_BYTES,
    EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST,
    EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST,
)


def _install_final_executable_validator(
    base_validator: Any,
    expected_split_bytes: bytes,
    expected_split_artifact_digest: str,
    expected_split_semantic_digest: str,
    expected_extension_bytes: bytes,
    expected_extension_artifact_digest: str,
    expected_extension_semantic_digest: str,
) -> Any:
    """Close the bootstrap window with immutable closure-captured artifacts."""

    def final_validator() -> None:
        base_validator()
        cache = _FINAL_ARTIFACT_CACHE
        if (
            globals().get("_validate_executable_control_plane") is not final_validator
            or cache.sealed is not True
            or cache._split_bytes is not expected_split_bytes
            or cache._split_artifact_digest != expected_split_artifact_digest
            or cache._split_semantic_digest != expected_split_semantic_digest
            or cache._extension_bytes is not expected_extension_bytes
            or cache._extension_artifact_digest != expected_extension_artifact_digest
            or cache._extension_semantic_digest != expected_extension_semantic_digest
            or globals().get("SPLIT_DERIVATION_PROTOCOL_BYTES")
            is not expected_split_bytes
            or globals().get("SPLIT_DERIVATION_ARTIFACT_DIGEST")
            != expected_split_artifact_digest
            or globals().get("SPLIT_DERIVATION_SEMANTIC_DIGEST")
            != expected_split_semantic_digest
            or globals().get("EXTENSION_TEMPLATE_SET_BYTES")
            is not expected_extension_bytes
            or globals().get("EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST")
            != expected_extension_artifact_digest
            or globals().get("EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST")
            != expected_extension_semantic_digest
        ):
            raise ProtocolViolation(
                "final artifact immutable closure control plane drifted"
            )

    return final_validator


_validate_executable_control_plane = _install_final_executable_validator(
    _validate_executable_control_plane,
    SPLIT_DERIVATION_PROTOCOL_BYTES,
    SPLIT_DERIVATION_ARTIFACT_DIGEST,
    SPLIT_DERIVATION_SEMANTIC_DIGEST,
    EXTENSION_TEMPLATE_SET_BYTES,
    EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST,
    EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST,
)
del _install_final_executable_validator


def _install_sealed_entrypoint(function: Any, validator: Any) -> Any:
    def sealed_entrypoint(*args: Any, **kwargs: Any) -> Any:
        validator()
        return function(*args, **kwargs)

    sealed_entrypoint.__name__ = function.__name__
    sealed_entrypoint.__qualname__ = function.__qualname__
    sealed_entrypoint.__module__ = function.__module__
    sealed_entrypoint.__doc__ = function.__doc__
    sealed_entrypoint.__annotations__ = dict(function.__annotations__)
    sealed_entrypoint.__ucm_sealed_original__ = function
    return sealed_entrypoint


for _entrypoint_name in _FINAL_WRAPPED_ENTRYPOINT_NAMES:
    _entrypoint = globals().get(_entrypoint_name)
    if not inspect.isfunction(_entrypoint):
        raise ProtocolViolation(
            f"final wrapped entrypoint is missing: {_entrypoint_name}"
        )
    globals()[_entrypoint_name] = _install_sealed_entrypoint(
        _entrypoint, _validate_executable_control_plane
    )
del _entrypoint_name, _entrypoint, _install_sealed_entrypoint


__all__ = [
    "ACTUAL_SCOPE_DIFF_SCHEMA",
    "ActualScopeDiff",
    "DISTANCE_DERIVATION_SCHEMA",
    "EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST",
    "EXTENSION_TEMPLATE_SET_BYTES",
    "EXTENSION_TEMPLATE_SET_DOMAIN",
    "EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST",
    "EXTENSION_SCOPE_REQUEST_SCHEMA",
    "EXTENSION_SCOPE_REVEAL_SCHEMA",
    "EXTENSION_SCOPE_SPEC_SCHEMA",
    "EXTENSION_SCOPE_TRANSCRIPT_SCHEMA",
    "EXTENSION_TRANSITION_SEAL_SCHEMA",
    "EXTENSION_FIRST_QUERY_SCHEMA",
    "EXTENSION_FIRST_RESULT_SCHEMA",
    "ExtensionAxisPatch",
    "ExtensionFirstQueryEnvelope",
    "ExtensionFirstResultEnvelope",
    "ExtensionScopeRequest",
    "ExtensionScopeReveal",
    "ExtensionScopeSpec",
    "ExtensionScopeTranscript",
    "ExtensionTemplateSet",
    "ExtensionTransitionSeal",
    "POST_SCOPE_REQUIREMENT_SCHEMA",
    "PostScopeRequirement",
    "ProtocolGap",
    "SPLIT_DERIVATION_ARTIFACT_DIGEST",
    "SPLIT_DERIVATION_DOMAIN",
    "SPLIT_DERIVATION_PROTOCOL_BYTES",
    "SPLIT_DERIVATION_SEMANTIC_DIGEST",
    "SPLIT_SEED_COMMITMENT_DOMAIN",
    "SUCCESSOR_BLOCKER_SCHEMA",
    "SUCCESSOR_RECEIPT_SCHEMA",
    "SplitAssignmentDerivation",
    "SplitDerivationProtocol",
    "SplitDerivationUnit",
    "SplitUnitAssignment",
    "SuccessorReceipt",
    "SuccessorRuntimeBlocker",
    "build_actual_scope_diff",
    "build_extension_template_set",
    "build_split_derivation_protocol",
    "compute_extension_scope_commitment",
    "compute_split_seed_commitment",
    "derive_panel_family_assignments",
    "derive_panel_split_seed",
    "derive_successor_distance_axis",
    "derive_successor_scope_from_spec",
    "distance_derivation_contract_bytes",
    "distance_derivation_contract_digest",
    "extension_template_set_artifact_digest_from_bytes",
    "extension_template_set_semantic_digest_from_bytes",
    "parse_actual_scope_diff_bytes",
    "parse_extension_first_query_bytes",
    "parse_extension_first_result_bytes",
    "parse_extension_scope_spec_bytes",
    "parse_extension_template_set_bytes",
    "parse_split_derivation_protocol_bytes",
    "parse_successor_receipt_bytes",
    "split_derivation_known_answer",
    "split_derivation_artifact_digest_from_bytes",
    "split_derivation_semantic_digest_from_bytes",
    "verify_panel_family_assignments",
    "verify_successor_distance_axis",
]
