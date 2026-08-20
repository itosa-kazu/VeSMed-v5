"""Normalize the two independently extracted real-case ledgers.

The adapters consume *ordinal information cuts*.  They deliberately do not
invent floating-point hospital dates for facts whose papers only establish a
partial order.  The output is the small ``PublicEvent`` wire schema accepted by
``framework.py`` while retaining the complete source row under ``provenance``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class NormalizedCase:
    case_id: str
    source: dict[str, Any]
    cut_ids: tuple[str, ...]
    events: tuple[dict[str, Any], ...]

    def events_at(self, cut_id: str) -> list[dict[str, Any]]:
        cut_index = self.cut_ids.index(cut_id)
        return [copy.deepcopy(row) for row in self.events if row["available_cut"] <= cut_index]

    def delta(self, previous_cut_id: str, next_cut_id: str) -> list[dict[str, Any]]:
        low = self.cut_ids.index(previous_cut_id)
        high = self.cut_ids.index(next_cut_id)
        if high <= low:
            raise ValueError("next cut must follow previous cut")
        return [copy.deepcopy(row) for row in self.events if low < row["available_cut"] <= high]


def _base_event(
    *,
    event_id: str,
    event_type: str,
    available_cut: int,
    concept_id: str | None,
    value: Any,
    unit: str | None,
    source_row: Mapping[str, Any],
    rankable: bool,
    status: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "event_id": event_id,
        "event_type": event_type,
        "available_at": available_cut,
        "available_cut": available_cut,
        "concept_id": concept_id,
        "value": value,
        "unit": unit,
        "rankable": bool(rankable),
        "measurement_context": {},
        "provenance": {
            "source_event_id": source_row.get("event_id"),
            "source_row": copy.deepcopy(dict(source_row)),
        },
    }
    if status is not None:
        row["status"] = status
    return row


def _load_hav(raw: Mapping[str, Any]) -> NormalizedCase:
    cuts = tuple(row["cut_id"] for row in raw["phase_cuts"])
    cut_index = {cut_id: index for index, cut_id in enumerate(cuts)}
    events: list[dict[str, Any]] = []
    for source in raw["events"]:
        availability = source.get("availability", {})
        first_cut = availability.get("first_available_cut_id")
        if first_cut is None and availability.get("excluded_from_realtime_replay") is True:
            continue
        if first_cut not in cut_index:
            raise ValueError(f"HAV event {source['event_id']} has invalid first cut {first_cut!r}")
        at = cut_index[first_cut]
        event_class = source.get("event_class")
        for index, observation in enumerate(source.get("observations", [])):
            events.append(
                _base_event(
                    event_id=f"{source['event_id']}#obs{index}",
                    event_type="ObservationAvailable",
                    available_cut=at,
                    concept_id=observation.get("axis_id"),
                    value=observation.get("value"),
                    unit=observation.get("unit"),
                    source_row=source,
                    rankable=True,
                )
            )
        if event_class == "action":
            action = source.get("action", {})
            status = str(action.get("status", "performed")).lower()
            planned = status in {"planned", "considered", "contraindicated", "deferred"}
            event_type = "PlannedTreatment" if planned else "PerformedTreatment"
            action_id = (
                action.get("action_id")
                or action.get("action_type")
                or action.get("treatment_id")
                or source["event_id"]
            )
            events.append(
                _base_event(
                    event_id=source["event_id"],
                    event_type=event_type,
                    available_cut=at,
                    concept_id=str(action_id),
                    value=copy.deepcopy(action),
                    unit=None,
                    source_row=source,
                    rankable=False,
                    status="planned" if planned else "performed",
                )
            )
        elif event_class in {"context", "background", "mode", "outcome"}:
            events.append(
                _base_event(
                    event_id=source["event_id"],
                    event_type="ContextUpdate",
                    available_cut=at,
                    concept_id=event_class,
                    value=copy.deepcopy(source.get(event_class, source.get("value"))),
                    unit=None,
                    source_row=source,
                    rankable=False,
                )
            )
    return NormalizedCase(
        case_id=str(raw["case_id"]),
        source=copy.deepcopy(dict(raw["source"])),
        cut_ids=cuts,
        events=tuple(events),
    )


_TMA_CUTS = (
    "C0_ED_PRESENTATION_PRE_TREATMENT",
    "C1_AFTER_INITIAL_TREATMENT_AND_DAY1_DRAW",
    "C2_AFTER_DAY3_BIOPSY_BEFORE_RESULT",
    "C3_DAY4_POST_BIOPSY_COMPLICATION",
    "C4_AFTER_REVISED_WORKUP_COMPLETE",
    "C5_DISCHARGE_AFTER_15_DAY_HOSPITALIZATION",
)


def _tma_available_cut(source: Mapping[str, Any]) -> int:
    event_id = str(source["event_id"])
    event_type = source.get("event_type")
    available = source.get("available_at", {})
    kind = available.get("kind")
    if event_type in {"future_plan", "outcome"} or event_id == "O041":
        return 5
    if event_id in {"A012", "A013", "A014", "A015"}:
        # The paper only places these after diagnostic redirection and before
        # discharge.  Keeping them out of C4 is the conservative no-leak cut.
        return 5
    if event_id in {"O025", "R001"} or event_id.startswith("O02") or event_id.startswith("O03"):
        return 4
    if kind == "exact_hospital_day":
        day = int(available["hospital_day"])
        if day == 0:
            # C0 is explicitly pre-treatment.
            return 1 if event_type == "action" else 0
        if day <= 1:
            return 1
        if day <= 3:
            return 2
        if day <= 4:
            return 3
        if day <= 14:
            return 4
        return 5
    earliest = int(available.get("earliest_hospital_day", available.get("hospital_day", 99)))
    if earliest <= 1:
        return 1
    if earliest <= 3:
        return 2
    if earliest <= 4:
        return 3
    return 4


def _tma_wire_type(source: Mapping[str, Any]) -> tuple[str, str | None]:
    kind = source.get("event_type")
    concept = str(source.get("concept_id", ""))
    if kind == "observation":
        return "ObservationAvailable", None
    if kind == "background":
        return "ContextUpdate", None
    if kind == "future_plan":
        return "PlannedTreatment", "planned"
    if kind == "action":
        if concept.endswith("_order") or concept.endswith("_sample_collection"):
            return "TestPerformed", "performed"
        return "PerformedTreatment", "performed"
    if kind == "report_conclusion":
        return "ObservationAvailable", None
    return "ContextUpdate", None


def _load_tma(raw: Mapping[str, Any]) -> NormalizedCase:
    extracted_cuts = tuple(row["cut_id"] for row in raw["information_cuts"])
    if extracted_cuts != _TMA_CUTS:
        raise ValueError("TMA cut manifest changed; adapter must be re-audited")
    events: list[dict[str, Any]] = []
    for source in raw["event_stream"]:
        wire_type, status = _tma_wire_type(source)
        events.append(
            _base_event(
                event_id=str(source["event_id"]),
                event_type=wire_type,
                available_cut=_tma_available_cut(source),
                concept_id=source.get("concept_id"),
                value=copy.deepcopy(source.get("value")),
                unit=source.get("unit"),
                source_row=source,
                rankable=bool(source.get("rankable_observation", False)),
                status=status,
            )
        )
    return NormalizedCase(
        case_id=str(raw["case_id"]),
        source=copy.deepcopy(dict(raw["source"])),
        cut_ids=extracted_cuts,
        events=tuple(events),
    )


def load_case(path: str | Path) -> NormalizedCase:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if "events" in raw and "phase_cuts" in raw:
        return _load_hav(raw)
    if "event_stream" in raw and "information_cuts" in raw:
        return _load_tma(raw)
    raise ValueError(f"unsupported case ledger schema in {path}")


def validate_monotone_case(case: NormalizedCase) -> None:
    seen_ids: set[str] = set()
    previous: set[str] = set()
    for cut in case.cut_ids:
        current = {row["event_id"] for row in case.events_at(cut)}
        if not previous.issubset(current):
            raise AssertionError(f"events disappeared at cut {cut}")
        previous = current
    for row in case.events:
        event_id = row["event_id"]
        if event_id in seen_ids:
            raise AssertionError(f"duplicate normalized event id {event_id}")
        seen_ids.add(event_id)
        if not (0 <= row["available_cut"] < len(case.cut_ids)):
            raise AssertionError(f"invalid cut index for {event_id}")


def public_events(case: NormalizedCase, cut_id: str) -> Iterable[dict[str, Any]]:
    """Yield a deep copy to prevent engine mutation from altering the ledger."""

    yield from case.events_at(cut_id)
