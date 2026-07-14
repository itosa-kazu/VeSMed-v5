"""Append-only, content-inventoried result bundles for UCM experiments."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def validate_run_id(run_id: str) -> None:
    if type(run_id) is not str or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ProtocolViolation(
            "run_id must be one safe path component of at most 128 characters"
        )
    if run_id in {".", ".."}:
        raise ProtocolViolation("run_id cannot be a dot path")


def _safe_relative(path: str) -> Path:
    if (
        type(path) is not str
        or not path
        or "\\" in path
        or path.startswith("/")
        or ":" in path
        or any(ord(character) < 32 for character in path)
    ):
        raise ProtocolViolation("bundle path must be a non-empty POSIX path")
    relative = Path(path)
    if (
        relative == Path(".")
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ProtocolViolation("bundle path must stay within the run directory")
    for part in relative.parts:
        stem = part.split(".", 1)[0].upper()
        if part.endswith((" ", ".")) or stem in WINDOWS_RESERVED_NAMES:
            raise ProtocolViolation("bundle path is unsafe on Windows")
    return relative


class AppendOnlyRunWriter:
    """Build one run in a sibling temporary directory, then publish once."""

    def __init__(self, root: Path, run_id: str, manifest: dict[str, Any]) -> None:
        validate_run_id(run_id)
        if not isinstance(root, Path):
            raise ProtocolViolation("run root must be pathlib.Path")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.target = self.root / run_id
        self.lock = self.root / f".{run_id}.lock"
        if self.target.exists():
            raise FileExistsError(f"run already exists: {self.target}")

        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.lock,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            os.write(descriptor, (run_id + "\n").encode("ascii"))
        except FileExistsError as exc:
            raise FileExistsError(f"run is already being produced: {run_id}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

        self.temporary = Path(
            tempfile.mkdtemp(prefix=f".{run_id}.tmp-", dir=self.root)
        )
        self._closed = False
        try:
            self.write_json("RUN_MANIFEST.json", manifest)
        except BaseException:
            self.abort()
            raise

    def _destination(self, relative: str) -> Path:
        if self._closed:
            raise RuntimeError("run writer is closed")
        target = self.temporary / _safe_relative(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write_bytes(self, relative: str, payload: bytes) -> None:
        if type(payload) is not bytes:
            raise ProtocolViolation("run payload must be exact bytes")
        target = self._destination(relative)
        with target.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

    def write_json(self, relative: str, value: Any) -> None:
        self.write_bytes(relative, canonical_json_bytes(value))

    def _inventory_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        files = [path for path in self.temporary.rglob("*") if path.is_file()]
        files.sort(
            key=lambda path: path.relative_to(self.temporary).as_posix().encode(
                "utf-8"
            )
        )
        for path in files:
            relative = path.relative_to(self.temporary).as_posix()
            if relative in {"INVENTORY.json", "FINALIZED.json"}:
                continue
            payload = path.read_bytes()
            rows.append(
                {
                    "path": relative,
                    "bytes": len(payload),
                    "sha256": digest_bytes(payload),
                }
            )
        return rows

    def finalize(self) -> Path:
        if self._closed:
            raise RuntimeError("run writer is closed")
        inventory = {
            "schema_version": "ucm-output-inventory/1",
            "run_id": self.run_id,
            "files": self._inventory_rows(),
        }
        inventory_bytes = canonical_json_bytes(inventory)
        self.write_bytes("INVENTORY.json", inventory_bytes)
        self.write_json(
            "FINALIZED.json",
            {
                "schema_version": "ucm-finalized-run/1",
                "run_id": self.run_id,
                "inventory_sha256": digest_bytes(inventory_bytes),
                "state": "FINALIZED",
            },
        )
        if self.target.exists():
            self.abort()
            raise FileExistsError(f"run appeared before publish: {self.target}")
        self.temporary.rename(self.target)
        self.lock.unlink(missing_ok=True)
        self._closed = True
        return self.target

    def abort(self) -> None:
        if self._closed:
            return
        shutil.rmtree(self.temporary, ignore_errors=True)
        self.lock.unlink(missing_ok=True)
        self._closed = True

    def __enter__(self) -> "AppendOnlyRunWriter":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None:
            self.abort()
        elif not self._closed:
            self.abort()
        return False
