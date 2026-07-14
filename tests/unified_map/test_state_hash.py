from __future__ import annotations

import struct

import pytest

from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.state import (
    StateClass,
    StatePayload,
    compute_state_hash,
    seal_state,
)


CANDIDATE = "sha256:" + "1" * 64
MODEL = "sha256:" + "2" * 64
SCOPE = "sha256:" + "3" * 64
CATALOG = "sha256:" + "4" * 64
DELTA = "sha256:" + "5" * 64


def payload(value: float = 1.0) -> StatePayload:
    return StatePayload.from_json(
        {"belief_mean": [value], "belief_var": [0.25]},
        schema_version="test/1",
        state_class=StateClass.COMPRESSED_SHARED,
    )


def kwargs() -> dict[str, object]:
    return {
        "candidate_bundle_digest": CANDIDATE,
        "model_digest": MODEL,
        "scope_digest": SCOPE,
        "catalog_digest": CATALOG,
        "as_of_available_at": 7,
    }


def test_state_hash_is_reproducible_and_harness_owned() -> None:
    expected = compute_state_hash(payload(), **kwargs())
    first = seal_state(
        payload(), operation="initialize", state_instance_id="instance-a", **kwargs()
    )
    second = seal_state(
        payload(), operation="replay", state_instance_id="instance-b", **kwargs()
    )
    assert first.record.state_hash == second.record.state_hash == expected
    assert first.record.state_instance_id != second.record.state_instance_id
    assert first.record.state_id == second.record.state_id


def test_parent_operation_and_delta_are_lineage_not_content_identity() -> None:
    base = seal_state(
        payload(), operation="initialize", state_instance_id="base", **kwargs()
    )
    replay = seal_state(
        payload(),
        operation="update",
        parent_state_hash=base.record.state_hash,
        delta_digest=DELTA,
        state_instance_id="updated",
        **kwargs(),
    )
    assert replay.record.state_hash == base.record.state_hash
    assert replay.record.parent_state_hash == base.record.state_hash


@pytest.mark.parametrize(
    "change",
    [
        {"payload": payload(2.0)},
        {"candidate_bundle_digest": "sha256:" + "5" * 64},
        {"model_digest": "sha256:" + "6" * 64},
        {"scope_digest": "sha256:" + "7" * 64},
        {"catalog_digest": "sha256:" + "8" * 64},
        {"as_of_available_at": 8},
    ],
)
def test_state_hash_changes_with_state_scope_or_model(change: dict) -> None:
    base_payload = payload()
    base_kwargs = kwargs()
    expected = compute_state_hash(base_payload, **base_kwargs)
    changed_payload = change.pop("payload", base_payload)
    base_kwargs.update(change)
    assert compute_state_hash(changed_payload, **base_kwargs) != expected


def test_state_payload_rejects_executable_or_unregistered_codec() -> None:
    with pytest.raises(ProtocolViolation, match="not inert"):
        StatePayload(
            payload=b"\x80\x04pickle",
            codec="python-pickle",
            schema_version="1",
            state_class=StateClass.COMPRESSED_SHARED,
        )


def test_state_payload_validates_advertised_inert_codec() -> None:
    with pytest.raises(ProtocolViolation, match="not canonical"):
        StatePayload(
            payload=b'{"z":1, "a":2}',
            codec="canonical-json-v1",
            schema_version="1",
            state_class=StateClass.COMPRESSED_SHARED,
        )
    with pytest.raises(ProtocolViolation, match="multiple of 8"):
        StatePayload(
            payload=b"not-f64",
            codec="raw-f64le-v1",
            schema_version="1",
            state_class=StateClass.COMPRESSED_SHARED,
        )
    valid = StatePayload(
        payload=struct.pack("<2d", 1.0, -2.0),
        codec="raw-f64le-v1",
        schema_version="1",
        state_class=StateClass.COMPRESSED_SHARED,
    )
    assert len(valid.payload) == 16
