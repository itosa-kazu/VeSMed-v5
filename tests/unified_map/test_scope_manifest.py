from __future__ import annotations

import copy
import hashlib
import json

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    domain_digest,
)
from prototype.unified_map.scope_manifest import (
    SCOPE_AXES,
    SCOPE_DOMAIN,
    SCOPE_MANIFEST_SCHEMA,
    ScopeAxisDeclarations,
    ScopeDeclaration,
    ScopeManifest,
    parse_scope_manifest_bytes,
    scope_digest_from_bytes,
    scope_manifest_digest_from_bytes,
)


def _manifest_wire() -> dict[str, object]:
    return {
        "schema_version": SCOPE_MANIFEST_SCHEMA,
        "benchmark_id": "UCM-BENCHMARK-v1",
        "scope_id": "UCM-SCOPE-v1",
        "axes": {
            axis_id: {
                "declarations": [
                    {
                        "declaration_id": f"{axis_id}:primary",
                        "value": {
                            "axis": axis_id,
                            "ordinal": ordinal,
                            "required": True,
                        },
                    }
                ]
            }
            for ordinal, axis_id in enumerate(SCOPE_AXES)
        },
    }


def _payload() -> bytes:
    return canonical_json_bytes(_manifest_wire())


def test_exact_parser_round_trips_closed_scope_dto() -> None:
    payload = _payload()
    manifest = parse_scope_manifest_bytes(payload)

    assert isinstance(manifest, ScopeManifest)
    assert manifest.schema_version == SCOPE_MANIFEST_SCHEMA
    assert manifest.benchmark_id == "UCM-BENCHMARK-v1"
    assert manifest.scope_id == "UCM-SCOPE-v1"
    assert tuple(manifest.axes) == SCOPE_AXES
    assert all(
        isinstance(manifest.axes[axis_id], ScopeAxisDeclarations)
        and isinstance(manifest.axes[axis_id].declarations[0], ScopeDeclaration)
        for axis_id in SCOPE_AXES
    )
    assert manifest.canonical_bytes == payload
    assert manifest.manifest_digest == digest_bytes(payload)
    assert manifest.scope_digest == scope_digest_from_bytes(payload)
    assert "scope_digest" not in manifest.to_wire()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update({"extra": False}),
        lambda row: row.pop("benchmark_id"),
        lambda row: row["axes"].update({"Extra": {"declarations": []}}),
        lambda row: row["axes"].pop("R"),
        lambda row: row["axes"]["P"].update({"extra": False}),
        lambda row: row["axes"]["P"]["declarations"][0].update({"extra": False}),
        lambda row: row["axes"]["P"]["declarations"][0].pop("value"),
    ],
)
def test_closed_schema_rejects_every_extra_or_missing_field(mutation: object) -> None:
    wire = _manifest_wire()
    mutation(wire)  # type: ignore[operator]
    with pytest.raises(ProtocolViolation, match="missing/extra|exactly all 11"):
        parse_scope_manifest_bytes(canonical_json_bytes(wire))


def test_manifest_rejects_a_forged_self_scope_digest_field() -> None:
    wire = _manifest_wire()
    wire["scope_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ProtocolViolation, match="missing/extra"):
        parse_scope_manifest_bytes(canonical_json_bytes(wire))


@pytest.mark.parametrize(
    "attack",
    [
        lambda payload: json.dumps(
            json.loads(payload), ensure_ascii=False, indent=2
        ).encode("utf-8"),
        lambda payload: payload.rstrip(b"\n"),
        lambda payload: b'{"schema_version":"ucm-scope-manifest/1",' + payload[1:],
        lambda payload: payload.replace(b'"axes":', b'"axes" :', 1),
    ],
)
def test_parser_rejects_noncanonical_exact_bytes(attack: object) -> None:
    with pytest.raises(ProtocolViolation, match="canonical|duplicate"):
        parse_scope_manifest_bytes(attack(_payload()))  # type: ignore[operator]


def test_declaration_registry_is_nonempty_unique_and_utf8_sorted() -> None:
    for declarations, match in (
        ([], "non-empty"),
        (
            [
                {"declaration_id": "same", "value": 1},
                {"declaration_id": "same", "value": 2},
            ],
            "unique",
        ),
        (
            [
                {"declaration_id": "éclair", "value": 1},
                {"declaration_id": "zebra", "value": 2},
            ],
            "UTF-8",
        ),
        ([{"declaration_id": "", "value": 1}], "non-empty"),
    ):
        wire = _manifest_wire()
        wire["axes"]["P"]["declarations"] = declarations
        with pytest.raises(ProtocolViolation, match=match):
            parse_scope_manifest_bytes(canonical_json_bytes(wire))


def test_golden_manifest_and_scope_digests() -> None:
    payload = _payload()

    assert scope_manifest_digest_from_bytes(payload) == (
        "sha256:288d72d83244f02e5181ac510a567029546ee3919f9eb7ee93301663c2c08296"
    )
    assert scope_digest_from_bytes(payload) == (
        "sha256:992c2b1f9a071594a93e77847ada54c5ff535a46d790cfca6b68ee1ff378c487"
    )
    assert scope_digest_from_bytes(payload) == (
        "sha256:" + hashlib.sha256(SCOPE_DOMAIN + payload).hexdigest()
    )


def test_every_one_of_the_eleven_axes_is_bound_into_scope_digest() -> None:
    baseline = scope_digest_from_bytes(_payload())
    changed: set[str] = set()

    for axis_id in SCOPE_AXES:
        wire = copy.deepcopy(_manifest_wire())
        declaration = wire["axes"][axis_id]["declarations"][0]
        declaration["value"]["required"] = False
        changed.add(scope_digest_from_bytes(canonical_json_bytes(wire)))

    assert len(changed) == len(SCOPE_AXES)
    assert baseline not in changed


def test_scope_hash_is_not_domain_digest_length_prefix_substitute() -> None:
    payload = _payload()
    direct_concatenation = scope_digest_from_bytes(payload)

    assert domain_digest(SCOPE_DOMAIN, (payload,)) != direct_concatenation


@pytest.mark.parametrize("payload", [bytearray(b"{}\n"), "{}\n", memoryview(b"{}\n")])
def test_parser_and_digest_helpers_require_exact_bytes(payload: object) -> None:
    for function in (
        parse_scope_manifest_bytes,
        scope_manifest_digest_from_bytes,
        scope_digest_from_bytes,
    ):
        with pytest.raises(ProtocolViolation, match="exact bytes"):
            function(payload)  # type: ignore[arg-type]
