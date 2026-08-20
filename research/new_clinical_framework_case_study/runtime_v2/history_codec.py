"""Canonical numeric trajectory-summary codec for SharedPatientStateV1.

The frozen trajectoryFeature wire carries finite numbers only.  This codec
therefore preserves every numeric piece of the runtime's bounded history
summary and rejects unknown feature kinds instead of silently deleting them on
the next update.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Iterable, Mapping

from .schema import digest


_VALUE_PREFIXES = ("latest", "previous", "trend", "count", "latest_available_at")

_FEATURE_WIRE_TYPES = {
    "latest": ("latest-public-value", None),
    "previous": ("previous-public-value", None),
    "trend": ("latest-minus-previous", None),
    "count": ("all-public-values", "count"),
    "latest_available_at": ("latest-availability-time", "model_time"),
}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def encode_history_summary(
    rows: Mapping[str, Mapping[str, Any]],
    *,
    mode_transitions: Iterable[Mapping[str, Any]],
    action_response_windows: Iterable[Mapping[str, Any]],
    retained_event_ids: Iterable[str],
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for concept_id, row in sorted(rows.items()):
        source_ids = sorted({str(value) for value in row.get("source_event_ids", [])})
        unit = str(row.get("unit") or "declared_observation_unit")
        definitions = (
            ("latest", row.get("latest"), "latest-public-value", unit),
            ("previous", row.get("previous"), "previous-public-value", unit),
            ("trend", row.get("trend"), "latest-minus-previous", unit),
            ("count", row.get("count"), "all-public-values", "count"),
            (
                "latest_available_at",
                row.get("latest_available_at"),
                "latest-availability-time",
                "model_time",
            ),
        )
        for prefix, raw_value, window_id, feature_unit in definitions:
            number = _finite_number(raw_value)
            if number is None:
                continue
            features.append(
                {
                    "feature_id": f"{prefix}:{concept_id}",
                    "target_id": str(concept_id),
                    "window_id": window_id,
                    "value": number,
                    "unit": feature_unit,
                    "source_event_ids": source_ids,
                }
            )
    body = {
        "trajectory_features": features,
        "mode_transitions": copy.deepcopy(list(mode_transitions)),
        "action_response_windows": copy.deepcopy(list(action_response_windows)),
        "retained_event_ids": sorted({str(value) for value in retained_event_ids}),
    }
    return {"summary_digest": digest(body), **body}


def decode_history_features(
    features: Iterable[Mapping[str, Any]],
    *,
    default_state_time: float,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for raw in features:
        row = dict(raw)
        feature_id = str(row.get("feature_id", ""))
        if ":" not in feature_id:
            raise ValueError(f"unsupported trajectory feature id: {feature_id!r}")
        prefix, encoded_target = feature_id.split(":", 1)
        if prefix not in _VALUE_PREFIXES:
            raise ValueError(f"unsupported trajectory feature kind: {prefix!r}")
        target_id = str(row.get("target_id", ""))
        if not target_id or target_id != encoded_target:
            raise ValueError(
                f"trajectory feature target mismatch: {feature_id!r} vs {target_id!r}"
            )
        bucket = grouped.setdefault(target_id, {})
        if prefix in bucket:
            raise ValueError(f"duplicate trajectory feature: {feature_id}")
        expected_window, required_unit = _FEATURE_WIRE_TYPES[prefix]
        if row.get("window_id") != expected_window:
            raise ValueError(
                f"trajectory feature {feature_id} has invalid typed window: "
                f"{row.get('window_id')!r}"
            )
        if required_unit is not None and row.get("unit") != required_unit:
            raise ValueError(
                f"trajectory feature {feature_id} has invalid typed unit: "
                f"{row.get('unit')!r}"
            )
        bucket[prefix] = row

    result: dict[str, dict[str, Any]] = {}
    for target_id, bucket in sorted(grouped.items()):
        source_sets = {
            tuple(sorted({str(value) for value in row.get("source_event_ids", [])}))
            for row in bucket.values()
        }
        if len(source_sets) > 1:
            raise ValueError(f"trajectory feature provenance disagrees for {target_id}")
        source_ids = list(next(iter(source_sets), ()))
        if not source_ids or any(not value for value in source_ids):
            raise ValueError(
                f"trajectory feature provenance must name retained events for {target_id}"
            )
        if "count" not in bucket or "latest_available_at" not in bucket:
            raise ValueError(
                f"trajectory feature set lacks count/availability type for {target_id}"
            )
        count = float(bucket.get("count", {}).get("value", 1.0))
        if not math.isfinite(count) or count < 1.0 or not count.is_integer():
            raise ValueError(f"trajectory count must be a positive integer for {target_id}")
        if int(count) != len(source_ids):
            raise ValueError(
                f"trajectory count/provenance cardinality disagrees for {target_id}"
            )
        latest_row = bucket.get("latest")
        previous_row = bucket.get("previous")
        trend_row = bucket.get("trend")
        available_row = bucket.get("latest_available_at")
        latest = float(latest_row["value"]) if latest_row is not None else None
        previous = float(previous_row["value"]) if previous_row is not None else None
        trend = float(trend_row["value"]) if trend_row is not None else None
        if latest is None and (previous is not None or trend is not None):
            raise ValueError(f"previous/trend exists without numeric latest for {target_id}")
        if count < 2.0 and (previous is not None or trend is not None):
            raise ValueError(
                f"previous/trend exists before two retained observations for {target_id}"
            )
        if latest is not None and previous is not None and trend is not None:
            if not math.isclose(latest - previous, trend, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"trajectory trend is inconsistent for {target_id}")
        primary_units = {
            str(row["unit"])
            for key, row in bucket.items()
            if key in {"latest", "previous", "trend"}
        }
        if len(primary_units) > 1:
            raise ValueError(f"trajectory units disagree for {target_id}")
        latest_available_at = (
            float(available_row["value"])
            if available_row is not None
            else float(default_state_time)
        )
        if (
            not math.isfinite(latest_available_at)
            or latest_available_at > float(default_state_time) + 1e-12
        ):
            raise ValueError(
                f"trajectory availability exceeds the state cut for {target_id}"
            )
        result[target_id] = {
            "latest": latest,
            "previous": previous,
            "trend": trend,
            "count": int(count),
            "latest_available_at": latest_available_at,
            "source_event_ids": source_ids,
            "unit": next(iter(primary_units), "declared_observation_unit"),
        }
    return result


__all__ = ["decode_history_features", "encode_history_summary"]
