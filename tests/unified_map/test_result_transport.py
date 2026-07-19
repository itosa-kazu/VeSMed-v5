from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes, digest_bytes
from prototype.unified_map.result_transport import compress_run_raw, deterministic_gzip


def test_deterministic_gzip_has_stable_header_and_round_trip() -> None:
    payload = b'{"row":1}\n'
    first = deterministic_gzip(payload)
    second = deterministic_gzip(payload)
    assert first == second
    assert first[4:8] == b"\0\0\0\0"
    assert gzip.decompress(first) == payload


def test_compress_run_raw_binds_uncompressed_manifest(tmp_path: Path) -> None:
    raw = b'{"row":1}\n{"row":2}\n'
    (tmp_path / "raw-episodes.jsonl").write_bytes(raw)
    manifest = {
        "protocol": "fixture",
        "files": [
            {
                "name": "raw-episodes.jsonl",
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        ],
    }
    (tmp_path / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    sidecars = compress_run_raw(tmp_path)
    assert sidecars == [tmp_path / "raw-episodes.jsonl.gz"]
    assert gzip.decompress(sidecars[0].read_bytes()) == raw
    assert compress_run_raw(tmp_path) == sidecars


def test_compress_run_raw_rejects_manifest_drift(tmp_path: Path) -> None:
    raw = b'{"row":1}\n'
    (tmp_path / "raw-episodes.jsonl").write_bytes(raw + b"x")
    manifest = {
        "files": [
            {
                "name": "raw-episodes.jsonl",
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        ]
    }
    (tmp_path / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(ProtocolViolation, match="drifted"):
        compress_run_raw(tmp_path)
