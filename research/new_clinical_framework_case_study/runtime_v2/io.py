"""Stable JSON interchange helpers for holdout harnesses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import PublicEvent, SharedPatientState, canonical_json_bytes


def load_events_json(path: str | Path) -> list[PublicEvent]:
    value: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("events")
    if not isinstance(value, list):
        raise ValueError("event JSON must be a list or an object with an events list")
    return [PublicEvent.from_dict(row) for row in value]


def save_state_json(state: SharedPatientState, path: str | Path) -> None:
    Path(path).write_bytes(canonical_json_bytes(state.to_dict()) + b"\n")


def load_state_json(path: str | Path) -> SharedPatientState:
    return SharedPatientState.from_bytes(Path(path).read_bytes())


__all__ = ["load_events_json", "load_state_json", "save_state_json"]
