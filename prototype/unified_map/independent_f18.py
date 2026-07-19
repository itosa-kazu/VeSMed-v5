"""Independent implementation of the sealed F18 structural-ensemble hypothesis.

This module intentionally does not import ``candidate_families``.  It repeats
the public-history fold, behavioral quotient, operator lift, support belief,
shared-state wire and stateless heads through a separate code path.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .benchmark_v1_contract import (
    DiagnosisPrediction,
    PublicTrainingRecord,
    RolloutPrediction,
    SharedPatientState,
    policy_key,
)
from .canonical import ProtocolViolation, canonical_json_bytes
from .schema import ActionPlan, EventKind, VisibleDelta, VisibleHistory
from .worlds.base import PublicCatalog


OBS_BINS = 16
ACTION_BINS = 8
ACCUMULATOR_PROTOCOL = "ucm-independent-public-fold/1"
STATE_PROTOCOL = "ucm-independent-f18-state/1"


def _bucket(value: str, count: int, domain: bytes) -> int:
    digest = hashlib.sha256(domain + value.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % count


def _empty(catalog_digest: str, as_of: int) -> dict[str, Any]:
    return {
        "protocol": ACCUMULATOR_PROTOCOL,
        "catalog_digest": catalog_digest,
        "as_of": as_of,
        "event_count": 0,
        "observations": [
            {"n": 0, "sum": 0.0, "first": 0.0, "last": 0.0, "t0": 0, "t1": 0}
            for _ in range(OBS_BINS)
        ],
        "treatments": [0] * ACTION_BINS,
        "checks": [0] * ACTION_BINS,
        "kinds": [0] * len(EventKind),
        "short": [0.0] * 32,
        "long": [0.0] * 32,
    }


def _fold_event(state: dict[str, Any], event: Any) -> None:
    tokens = [event.kind.value]
    for field in ("channel_id", "action_id", "check_id"):
        value = event.payload.get(field)
        if type(value) is str:
            tokens.append(f"{field}={value}")
    tokens.extend(
        (
            f"availability_lag={event.available_at - event.occurred_at}",
            f"collection_lag={0 if event.collected_at is None else event.available_at - event.collected_at}",
        )
    )
    digest = hashlib.sha256(
        b"UCM_ORDERED_EVENT_SKETCH_V1\0" + "|".join(tokens).encode("utf-8")
    ).digest()
    sketch_index = int.from_bytes(digest[:4], "big") % 32
    sign = -1.0 if digest[4] & 1 else 1.0
    for name, decay in (("short", 0.65), ("long", 0.95)):
        state[name] = [decay * float(value) for value in state[name]]
        state[name][sketch_index] += sign
    state["event_count"] += 1
    state["kinds"][tuple(EventKind).index(event.kind)] += 1
    if event.kind is EventKind.OBSERVATION_AVAILABLE:
        channel = event.payload.get("channel_id")
        value = event.payload.get("value")
        if type(channel) is str and type(value) in {int, float}:
            value = float(value)
            if not math.isfinite(value):
                raise ProtocolViolation("independent fold received non-finite observation")
            row = state["observations"][_bucket(channel, OBS_BINS, b"UCM_OBS_BIN_V1\0")]
            if row["n"] == 0:
                row["first"] = value
                row["t0"] = event.available_at
            row["n"] += 1
            row["sum"] += value
            row["last"] = value
            row["t1"] = event.available_at
    elif event.kind is EventKind.PERFORMED_TREATMENT:
        action = event.payload.get("action_id")
        if type(action) is str:
            state["treatments"][_bucket(action, ACTION_BINS, b"UCM_TREAT_BIN_V1\0")] += 1
    elif event.kind in {EventKind.TEST_ORDERED, EventKind.TEST_PERFORMED}:
        check = event.payload.get("check_id")
        if type(check) is str:
            state["checks"][_bucket(check, ACTION_BINS, b"UCM_CHECK_BIN_V1\0")] += 1


def _from_history(history: VisibleHistory) -> dict[str, Any]:
    if type(history) is not VisibleHistory:
        raise ProtocolViolation("independent encoder requires VisibleHistory")
    state = _empty(history.catalog_digest, history.as_of_available_at)
    for event in history.events:
        _fold_event(state, event)
    return state


def _update(state: dict[str, Any], delta: VisibleDelta) -> dict[str, Any]:
    value = json.loads(canonical_json_bytes(state))
    if delta.advance_to < int(value["as_of"]):
        raise ProtocolViolation("independent update moved backwards")
    for event in delta.events:
        _fold_event(value, event)
    value["as_of"] = delta.advance_to
    return value


def _path(state: dict[str, Any]) -> np.ndarray:
    values: list[float] = []
    for row in state["observations"]:
        count = int(row["n"])
        mean = float(row["sum"]) / count if count else 0.0
        elapsed = int(row["t1"]) - int(row["t0"])
        slope = (
            (float(row["last"]) - float(row["first"])) / elapsed
            if count > 1 and elapsed > 0
            else 0.0
        )
        values.extend((float(row["last"]), mean, slope, math.log1p(count)))
    values.extend(float(value) for value in state["treatments"])
    values.extend(float(value) for value in state["checks"])
    values.extend(float(value) for value in state["kinds"])
    values.extend(
        (
            math.tanh(float(state["as_of"]) / 32.0),
            math.log1p(float(state["event_count"])),
            *[float(value) for value in state["short"]],
            *[float(value) for value in state["long"]],
        )
    )
    result = np.asarray(values, dtype=np.float64)
    if result.shape != (151,) or not np.all(np.isfinite(result)):
        raise ProtocolViolation("independent path state has wrong shape")
    return result


def _ridge(x: np.ndarray, y: np.ndarray, penalty: float) -> np.ndarray:
    design = np.concatenate((np.ones((len(x), 1)), x), axis=1)
    gram = design.T @ design
    regularizer = np.eye(gram.shape[0]) * penalty
    regularizer[0, 0] = 0.0
    return np.linalg.pinv(gram + regularizer, rcond=1e-10) @ design.T @ y


def _kmeans(values: np.ndarray, count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    count = min(count, len(values))
    centroids = values[rng.choice(len(values), size=count, replace=False)].copy()
    assignment = np.zeros(len(values), dtype=np.int64)
    for _ in range(30):
        distances = np.sum(
            (values[:, None, :] - centroids[None, :, :]) ** 2, axis=2
        )
        next_assignment = np.argmin(distances, axis=1)
        if np.array_equal(next_assignment, assignment):
            break
        assignment = next_assignment
        for index in range(count):
            members = values[assignment == index]
            if len(members):
                centroids[index] = members.mean(axis=0)
    return assignment


@dataclass(slots=True)
class _Model:
    catalog: PublicCatalog
    labels: tuple[str, ...]
    query_keys: tuple[str, ...]
    data: dict[str, Any]
    diagnosis_weights: np.ndarray
    rollout_weights: dict[str, np.ndarray]


class IndependentStructuralEnsemble:
    family_id = "I18-independent-structural-ensemble"
    candidate_id = "I18-independent-causal-operator-state-v1"

    def __init__(self, *, clusters: int = 8, regularization: float = 1e-3) -> None:
        self.clusters = int(clusters)
        self.regularization = float(regularization)
        self._models: dict[str, _Model] = {}

    @staticmethod
    def _cluster(path: np.ndarray, data: dict[str, Any]) -> np.ndarray:
        centers = np.asarray(data["centers"], dtype=np.float64)
        scale = np.asarray(data["cluster_scale"], dtype=np.float64)
        logits = -0.5 * np.sum(((centers - path[None, :]) / scale) ** 2, axis=1)
        logits -= logits.max()
        posterior = np.exp(logits)
        return posterior / posterior.sum()

    @staticmethod
    def _lift(path: np.ndarray, data: dict[str, Any]) -> np.ndarray:
        indices = np.asarray(data["lift_indices"], dtype=np.int64)
        center = np.asarray(data["lift_center"], dtype=np.float64)
        scale = np.asarray(data["lift_scale"], dtype=np.float64)
        x = np.tanh((path[indices] - center) / scale)
        return np.concatenate((x, x**2, x[:-1] * x[1:]))

    @staticmethod
    def _support(path: np.ndarray, data: dict[str, Any]) -> np.ndarray:
        exemplars = np.asarray(data["exemplars"], dtype=np.float64)
        targets = np.asarray(data["diagnosis_targets"], dtype=np.float64)
        scale = np.asarray(data["support_scale"], dtype=np.float64)
        distance = np.sqrt(np.sum(((exemplars - path[None, :]) / scale) ** 2, axis=1))
        reference = float(data["support_reference"])
        weights = np.exp(-0.5 * (distance / reference) ** 2)
        posterior = targets.mean(axis=0) if weights.sum() <= 1e-15 else weights @ targets / weights.sum()
        minimum = float(distance.min())
        novelty = 1.0 - math.exp(-max(0.0, minimum - reference) / reference)
        return np.concatenate((posterior, [minimum / reference, novelty]))

    @classmethod
    def _represent(cls, path: np.ndarray, data: dict[str, Any]) -> np.ndarray:
        return np.concatenate((cls._cluster(path, data), cls._lift(path, data), cls._support(path, data)))

    def fit(
        self,
        catalogs: tuple[PublicCatalog, ...],
        records: tuple[PublicTrainingRecord, ...],
        *,
        model_seed: int,
    ) -> None:
        models: dict[str, _Model] = {}
        for catalog in catalogs:
            selected = [record for record in records if record.history.catalog_digest == catalog.digest]
            if not selected:
                raise ProtocolViolation("independent fit received an empty catalog")
            labels = catalog.diagnostic_labels
            query_keys = tuple(row.query_key for row in selected[0].rollouts)
            paths = np.vstack([_path(_from_history(record.history)) for record in selected])
            diagnosis = np.asarray(
                [[float(record.diagnostic_target[label]) for label in labels] for record in selected],
                dtype=np.float64,
            )
            rollouts = {
                key: np.asarray(
                    [
                        [
                            *next(row for row in record.rollouts if row.query_key == key).signature,
                            next(row for row in record.rollouts if row.query_key == key).expected_utility,
                        ]
                        for record in selected
                    ],
                    dtype=np.float64,
                )
                for key in query_keys
            }
            behavior = np.concatenate(
                (diagnosis, *(rollouts[key] for key in query_keys)), axis=1
            )
            assignment = _kmeans(behavior, self.clusters, model_seed)
            active = sorted(set(int(value) for value in assignment))
            centers = np.vstack(
                [paths[assignment == index].mean(axis=0) for index in active]
            )
            support_scale = np.std(paths, axis=0) + 0.1
            normalized = paths / support_scale
            if len(paths) > 1:
                pairwise = np.sqrt(
                    np.sum(
                        (normalized[:, None, :] - normalized[None, :, :]) ** 2,
                        axis=2,
                    )
                )
                pairwise += np.eye(len(paths)) * 1e12
                reference = float(np.quantile(np.min(pairwise, axis=1), 0.90))
            else:
                reference = 1.0
            variance = np.var(paths, axis=0)
            lift_indices = np.asarray(
                sorted(int(index) for index in np.argsort(variance)[-24:]),
                dtype=np.int64,
            )
            data = {
                "centers": centers.tolist(),
                "cluster_scale": (np.std(paths, axis=0) + 0.1).tolist(),
                "exemplars": paths.tolist(),
                "diagnosis_targets": diagnosis.tolist(),
                "support_scale": support_scale.tolist(),
                "support_reference": max(reference, 1e-6),
                "lift_indices": lift_indices.tolist(),
                "lift_center": np.mean(paths[:, lift_indices], axis=0).tolist(),
                "lift_scale": (np.std(paths[:, lift_indices], axis=0) + 0.1).tolist(),
                "diagnosis_offset": len(centers) + (24 + 24 + 23),
            }
            representation = np.vstack([self._represent(row, data) for row in paths])
            models[catalog.digest] = _Model(
                catalog,
                labels,
                query_keys,
                data,
                _ridge(representation, diagnosis, self.regularization),
                {
                    key: _ridge(representation, rollouts[key], self.regularization)
                    for key in query_keys
                },
            )
        self._models = models

    def _model(self, digest: str) -> _Model:
        if digest not in self._models:
            raise ProtocolViolation("independent candidate was not fitted for catalog")
        return self._models[digest]

    def _state(self, accumulator: dict[str, Any], model: _Model) -> SharedPatientState:
        representation = self._represent(_path(accumulator), model.data)
        payload = canonical_json_bytes(
            {
                "protocol": STATE_PROTOCOL,
                "catalog_digest": model.catalog.digest,
                "accumulator": accumulator,
                "representation": representation.tolist(),
            }
        )
        return SharedPatientState(
            f"{self.candidate_id}/state-v1",
            payload,
            tuple(float(value) for value in representation),
        )

    def initialize(self, history: VisibleHistory, *, inference_seed: int) -> SharedPatientState:
        del inference_seed
        return self._state(_from_history(history), self._model(history.catalog_digest))

    def _decode(self, state: SharedPatientState) -> tuple[dict[str, Any], _Model, np.ndarray]:
        wire = json.loads(state.payload)
        if wire.get("protocol") != STATE_PROTOCOL:
            raise ProtocolViolation("independent state protocol mismatch")
        model = self._model(wire["catalog_digest"])
        representation = np.asarray(wire["representation"], dtype=np.float64)
        if tuple(representation.tolist()) != state.distance_vector:
            raise ProtocolViolation("independent state wire mismatch")
        return wire, model, representation

    def update(
        self, state: SharedPatientState, delta: VisibleDelta, *, inference_seed: int
    ) -> SharedPatientState:
        del inference_seed
        wire, model, _ = self._decode(state)
        return self._state(_update(wire["accumulator"], delta), model)

    def diagnose(
        self,
        state: SharedPatientState,
        label_catalog: tuple[str, ...],
        *,
        query_seed: int,
    ) -> DiagnosisPrediction:
        del query_seed
        _, model, z = self._decode(state)
        if label_catalog != model.labels:
            raise ProtocolViolation("independent diagnosis label drift")
        offset = int(model.data["diagnosis_offset"])
        probabilities = np.maximum(z[offset : offset + len(model.labels)], 1e-12)
        if "unknown" in model.labels:
            unknown = model.labels.index("unknown")
            known = np.delete(probabilities, unknown)
            ambiguity = min(1.0, 2.0 * max(0.0, 1.0 - float(known.max())))
            p_unknown = min(1.0, max(float(probabilities[unknown]), float(z[-1]), ambiguity))
            known_total = float(known.sum())
            probabilities[:] = 0.0
            probabilities[np.arange(len(model.labels)) != unknown] = known / known_total * (1.0 - p_unknown)
            probabilities[unknown] = p_unknown
        else:
            probabilities /= probabilities.sum()
        return DiagnosisPrediction(
            {label: float(probabilities[index]) for index, label in enumerate(model.labels)}
        )

    def rollout(
        self,
        state: SharedPatientState,
        policy: ActionPlan,
        horizon: int,
        *,
        query_seed: int,
    ) -> RolloutPrediction:
        del query_seed
        _, model, z = self._decode(state)
        weights = model.rollout_weights.get(policy_key(policy, horizon))
        if weights is None:
            return RolloutPrediction((0.0,) * 32, 0.0, abstained=True)
        raw = np.concatenate(([1.0], z)) @ weights
        return RolloutPrediction(tuple(float(value) for value in raw[:-1]), float(raw[-1]))

    def model_summary(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "catalog_count": len(self._models),
            "independent_source": True,
        }


__all__ = ["IndependentStructuralEnsemble"]
