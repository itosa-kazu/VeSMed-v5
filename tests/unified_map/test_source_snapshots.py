from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from prototype.unified_map.source_snapshots import (
    SourceSnapshotError,
    resolve_source_snapshot,
    verify_source_snapshots,
)


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_ROOT = ROOT / "results/unified_map/source_snapshots"


def test_archive_closes_run_and_failed_source_bindings_through_exp038() -> None:
    report = verify_source_snapshots(ROOT, through_experiment=38)

    assert report == {
        "binding_count": 88,
        "failed_attempt_count": 1,
        "index": str((SNAPSHOT_ROOT / "index.json").resolve()),
        "object_count": 16,
        "protocol": "ucm-source-snapshot-index/1",
        "run_count": 37,
        "status": "verified",
        "through_experiment": 38,
    }

    index = json.loads((SNAPSHOT_ROOT / "index.json").read_bytes())
    historical = {
        entry["sha256"]: entry["byte_length"] for entry in index["objects"]
    }
    assert historical[
        "sha256:7ab73c7361e7e75b2ea3d5c8c0f7032d94360cc7cfb1a66dcfac9374a3e71917"
    ] == 42_608
    assert historical[
        "sha256:3a1688e9b0091d238bcab55ddca8b8d504c4827623f8d3aee592ad31bdbdb3c0"
    ] == 42_957
    assert historical[
        "sha256:a9efb4754b3ed65b902e21bcdd2872531a9470784ebfa96adbcc7688b99d5141"
    ] == 43_327
    assert historical[
        "sha256:e1695706ad3950e25be2b6ef8a26e4c80b862ec651aa00be58c19de127877bcb"
    ] == 62_092

    source = resolve_source_snapshot(
        ROOT,
        "sha256:e1695706ad3950e25be2b6ef8a26e4c80b862ec651aa00be58c19de127877bcb",
        "prototype/unified_map/candidate_families.py",
    )
    assert len(source.read_bytes()) == 62_092


def test_archive_detects_a_changed_historical_byte(tmp_path: Path) -> None:
    copied = tmp_path / "source_snapshots"
    shutil.copytree(SNAPSHOT_ROOT, copied)
    index = json.loads((copied / "index.json").read_bytes())
    entry = next(
        item
        for item in index["objects"]
        if item["sha256"]
        == "sha256:7ab73c7361e7e75b2ea3d5c8c0f7032d94360cc7cfb1a66dcfac9374a3e71917"
    )
    source = copied / Path(entry["object_path"])
    original = source.read_bytes()
    source.write_bytes(b"X" + original[1:])
    assert hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(
        original
    ).digest()

    with pytest.raises(SourceSnapshotError, match="snapshot digest mismatch"):
        verify_source_snapshots(
            ROOT,
            index_path=copied / "index.json",
            through_experiment=36,
        )
