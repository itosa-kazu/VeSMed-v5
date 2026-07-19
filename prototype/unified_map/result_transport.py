"""Deterministic gzip transport for append-only UCM raw JSONL evidence."""

from __future__ import annotations

import argparse
import gzip
import io
import json
from pathlib import Path
from typing import Any

from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes


def _decode_manifest(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("run manifest is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation("run manifest is not canonical JSON")
    return value


def deterministic_gzip(payload: bytes, *, compresslevel: int = 9) -> bytes:
    """Return gzip bytes with no filename and a zero timestamp."""

    target = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=target, compresslevel=compresslevel, mtime=0
    ) as handle:
        handle.write(payload)
    return target.getvalue()


def compress_run_raw(run_path: Path, *, replace_sidecars: bool = False) -> list[Path]:
    """Create deterministic sidecars for manifest-bound ``*.jsonl`` members."""

    run_path = run_path.resolve(strict=True)
    manifest = _decode_manifest(run_path / "manifest.json")
    written: list[Path] = []
    for row in manifest.get("files", []):
        name = row.get("name")
        if type(name) is not str or not name.endswith(".jsonl"):
            continue
        source = run_path / name
        if not source.is_file():
            raise ProtocolViolation(f"expanded raw member is missing: {name}")
        payload = source.read_bytes()
        if len(payload) != row.get("byte_length") or digest_bytes(payload) != row.get(
            "sha256"
        ):
            raise ProtocolViolation(f"expanded raw member drifted: {name}")
        sidecar = source.with_name(source.name + ".gz")
        compressed = deterministic_gzip(payload)
        if sidecar.exists() and not replace_sidecars:
            if sidecar.read_bytes() != compressed:
                raise ProtocolViolation(f"existing gzip sidecar drifted: {sidecar.name}")
        else:
            mode = "wb" if replace_sidecars else "xb"
            with sidecar.open(mode) as handle:
                handle.write(compressed)
        if gzip.decompress(sidecar.read_bytes()) != payload:
            raise ProtocolViolation(f"gzip sidecar failed round trip: {sidecar.name}")
        written.append(sidecar)
    if not written:
        raise ProtocolViolation("run manifest has no raw JSONL members")
    return written


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_path", type=Path)
    parser.add_argument("--replace-sidecars", action="store_true")
    args = parser.parse_args()
    rows = compress_run_raw(args.run_path, replace_sidecars=args.replace_sidecars)
    print(json.dumps({"status": "verified", "sidecars": [str(p) for p in rows]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

