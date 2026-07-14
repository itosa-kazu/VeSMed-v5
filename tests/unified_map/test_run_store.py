from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_bytes
from prototype.unified_map.run_store import AppendOnlyRunWriter


def manifest() -> dict:
    return {
        "schema_version": "ucm-run-manifest/1",
        "run_id": "run-a",
        "benchmark_freeze_digest": "sha256:" + "0" * 64,
    }


def test_run_bundle_is_atomic_inventoried_and_non_overwriting(tmp_path: Path) -> None:
    writer = AppendOnlyRunWriter(tmp_path, "run-a", manifest())
    assert not (tmp_path / "run-a").exists()
    writer.write_json("raw/prediction.json", {"value": 1.25})
    writer.write_bytes("audit/transcript.jsonl", b'{"call":1}\n')
    target = writer.finalize()

    assert target == tmp_path / "run-a"
    assert not (tmp_path / ".run-a.lock").exists()
    inventory_bytes = (target / "INVENTORY.json").read_bytes()
    inventory = json.loads(inventory_bytes)
    assert [row["path"] for row in inventory["files"]] == [
        "RUN_MANIFEST.json",
        "audit/transcript.jsonl",
        "raw/prediction.json",
    ]
    for row in inventory["files"]:
        payload = (target / row["path"]).read_bytes()
        assert row["bytes"] == len(payload)
        assert row["sha256"] == digest_bytes(payload)
    finalized = json.loads((target / "FINALIZED.json").read_bytes())
    assert finalized["inventory_sha256"] == digest_bytes(inventory_bytes)

    with pytest.raises(FileExistsError):
        AppendOnlyRunWriter(tmp_path, "run-a", manifest())


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "a\\b",
        "",
        ".",
        "raw/data:stream",
        "NUL",
        "reports/COM1.json",
        "trailing.",
        "bad\x01name",
    ],
)
def test_bundle_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    writer = AppendOnlyRunWriter(tmp_path, "safe", manifest())
    try:
        with pytest.raises(ProtocolViolation):
            writer.write_bytes(path, b"x")
    finally:
        writer.abort()


def test_abort_removes_partial_run_and_lock(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        with AppendOnlyRunWriter(tmp_path, "failed", manifest()) as writer:
            writer.write_bytes("partial.bin", b"partial")
            raise RuntimeError("boom")
    assert not (tmp_path / "failed").exists()
    assert not (tmp_path / ".failed.lock").exists()
    assert not list(tmp_path.glob(".failed.tmp-*"))


@pytest.mark.parametrize("run_id", ["", "../x", "x/y", "x y", ".", "a" * 129])
def test_run_id_is_one_safe_component(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ProtocolViolation):
        AppendOnlyRunWriter(tmp_path, run_id, manifest())
