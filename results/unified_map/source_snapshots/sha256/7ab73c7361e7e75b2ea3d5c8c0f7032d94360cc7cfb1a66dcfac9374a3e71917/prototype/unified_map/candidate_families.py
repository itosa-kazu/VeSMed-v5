"""Runnable shared-state candidate families for UCM benchmark v1.

These are intentionally small research implementations.  They share one public
feature/update path and differ in the mathematical object stored as patient
state.  All ordinary heads decode only ``SharedPatientState``; no head receives
or re-reads ``VisibleHistory``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Callable

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


OBSERVATION_BINS = 16
ACTION_BINS = 8
FEATURE_PROTOCOL = "ucm-public-history-accumulator/1"
STATE_PROTOCOL = "ucm-shared-family-state/1"


def _bucket(text: str, count: int, domain: bytes) -> int:
    raw = hashlib.sha256(domain + text.encode("utf-8")).digest()
    return int.from_bytes(raw[:4], "big") % count


def _empty_accumulator(catalog_digest: str, as_of: int) -> dict[str, Any]:
    return {
        "protocol": FEATURE_PROTOCOL,
        "catalog_digest": catalog_digest,
        "as_of": as_of,
        "total_events": 0,
        "observation": [
            {
                "count": 0,
                "sum": 0.0,
                "first": 0.0,
                "first_time": 0,
                "last": 0.0,
                "last_time": 0,
            }
            for _ in range(OBSERVATION_BINS)
        ],
        "treatment_counts": [0] * ACTION_BINS,
        "check_counts": [0] * ACTION_BINS,
        "kind_counts": [0] * len(EventKind),
        "ordered_short": [0.0] * 32,
        "ordered_long": [0.0] * 32,
    }


def _numeric_observation(event: Any) -> tuple[str, float] | None:
    if event.kind is not EventKind.OBSERVATION_AVAILABLE:
        return None
    channel = event.payload.get("channel_id")
    value = event.payload.get("value")
    if type(channel) is not str or type(value) not in {int, float}:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ProtocolViolation("public observation is non-finite")
    return channel, number


def _accumulate_event(accumulator: dict[str, Any], event: Any) -> None:
    token_parts = [event.kind.value]
    for key in ("channel_id", "action_id", "check_id"):
        value = event.payload.get(key)
        if type(value) is str:
            token_parts.append(f"{key}={value}")
    token_parts.extend(
        (
            f"availability_lag={event.available_at - event.occurred_at}",
            f"collection_lag={0 if event.collected_at is None else event.available_at - event.collected_at}",
        )
    )
    token = "|".join(token_parts)
    digest = hashlib.sha256(b"UCM_ORDERED_EVENT_SKETCH_V1\0" + token.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % 32
    sign = -1.0 if digest[4] & 1 else 1.0
    for key, decay in (("ordered_short", 0.65), ("ordered_long", 0.95)):
        accumulator[key] = [decay * float(value) for value in accumulator[key]]
        accumulator[key][index] += sign
    accumulator["total_events"] += 1
    accumulator["kind_counts"][tuple(EventKind).index(event.kind)] += 1
    observed = _numeric_observation(event)
    if observed is not None:
        channel, number = observed
        index = _bucket(channel, OBSERVATION_BINS, b"UCM_OBS_BIN_V1\0")
        row = accumulator["observation"][index]
        if row["count"] == 0:
            row["first"] = number
            row["first_time"] = event.available_at
        row["count"] += 1
        row["sum"] += number
        row["last"] = number
        row["last_time"] = event.available_at
    if event.kind is EventKind.PERFORMED_TREATMENT:
        action_id = event.payload.get("action_id")
        if type(action_id) is str:
            accumulator["treatment_counts"][
                _bucket(action_id, ACTION_BINS, b"UCM_TREAT_BIN_V1\0")
            ] += 1
    if event.kind in {EventKind.TEST_ORDERED, EventKind.TEST_PERFORMED}:
        check_id = event.payload.get("check_id")
        if type(check_id) is str:
            accumulator["check_counts"][
                _bucket(check_id, ACTION_BINS, b"UCM_CHECK_BIN_V1\0")
            ] += 1


def accumulator_from_history(history: VisibleHistory) -> dict[str, Any]:
    if type(history) is not VisibleHistory:
        raise ProtocolViolation("feature extractor requires VisibleHistory")
    accumulator = _empty_accumulator(history.catalog_digest, history.as_of_available_at)
    for event in history.events:
        _accumulate_event(accumulator, event)
    return accumulator


def update_accumulator(
    accumulator: dict[str, Any], delta: VisibleDelta
) -> dict[str, Any]:
    if type(delta) is not VisibleDelta:
        raise ProtocolViolation("shared-state update requires VisibleDelta")
    value = json.loads(canonical_json_bytes(accumulator))
    if value.get("protocol") != FEATURE_PROTOCOL or delta.advance_to < value["as_of"]:
        raise ProtocolViolation("state accumulator or delta order is invalid")
    for event in delta.events:
        _accumulate_event(value, event)
    value["as_of"] = delta.advance_to
    return value


def feature_vector(accumulator: dict[str, Any]) -> np.ndarray:
    if accumulator.get("protocol") != FEATURE_PROTOCOL:
        raise ProtocolViolation("unknown feature accumulator protocol")
    values: list[float] = []
    for row in accumulator["observation"]:
        count = int(row["count"])
        mean = float(row["sum"]) / count if count else 0.0
        elapsed = int(row["last_time"]) - int(row["first_time"])
        slope = (
            (float(row["last"]) - float(row["first"])) / elapsed
            if count > 1 and elapsed > 0
            else 0.0
        )
        values.extend((float(row["last"]), mean, slope, math.log1p(count)))
    values.extend(float(value) for value in accumulator["treatment_counts"])
    values.extend(float(value) for value in accumulator["check_counts"])
    values.extend(float(value) for value in accumulator["kind_counts"])
    values.extend(
        (
            math.tanh(float(accumulator["as_of"]) / 32.0),
            math.log1p(float(accumulator["total_events"])),
        )
    )
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 1 or not np.all(np.isfinite(result)):
        raise ProtocolViolation("history feature vector is invalid")
    return result


def path_feature_vector(accumulator: dict[str, Any]) -> np.ndarray:
    """Fixed recursive state with short and long event-order/availability memory."""

    base = feature_vector(accumulator)
    ordered = np.asarray(
        [*accumulator["ordered_short"], *accumulator["ordered_long"]],
        dtype=np.float64,
    )
    result = np.concatenate((base, ordered))
    if not np.all(np.isfinite(result)):
        raise ProtocolViolation("ordered path feature vector is invalid")
    return result


@dataclass(slots=True)
class _Dataset:
    catalog: PublicCatalog
    labels: tuple[str, ...]
    query_keys: tuple[str, ...]
    raw: np.ndarray
    path: np.ndarray
    diagnosis: np.ndarray
    rollouts: dict[str, np.ndarray]


@dataclass(slots=True)
class _CatalogModel:
    catalog: PublicCatalog
    labels: tuple[str, ...]
    query_keys: tuple[str, ...]
    representation_data: dict[str, Any]
    diagnosis_weights: np.ndarray
    rollout_weights: dict[str, np.ndarray]


def _ridge(x: np.ndarray, y: np.ndarray, regularization: float) -> np.ndarray:
    if x.ndim != 2 or y.ndim != 2 or x.shape[0] != y.shape[0]:
        raise ProtocolViolation("ridge inputs are not aligned matrices")
    design = np.concatenate((np.ones((x.shape[0], 1)), x), axis=1)
    gram = design.T @ design
    penalty = np.eye(gram.shape[0]) * regularization
    penalty[0, 0] = 0.0
    return np.linalg.pinv(gram + penalty, rcond=1e-10) @ design.T @ y


def _predict(weights: np.ndarray, representation: np.ndarray) -> np.ndarray:
    return np.concatenate(([1.0], representation)) @ weights


def _dataset_for(
    catalog: PublicCatalog, records: list[PublicTrainingRecord]
) -> _Dataset:
    if not records:
        raise ProtocolViolation("candidate fit received an empty catalog partition")
    labels = catalog.diagnostic_labels
    query_keys = tuple(row.query_key for row in records[0].rollouts)
    raw_rows: list[np.ndarray] = []
    path_rows: list[np.ndarray] = []
    diagnosis_rows: list[list[float]] = []
    rollout_rows: dict[str, list[list[float]]] = {key: [] for key in query_keys}
    for record in records:
        if record.history.catalog_digest != catalog.digest:
            raise ProtocolViolation("training record/catalog digest mismatch")
        if tuple(row.query_key for row in record.rollouts) != query_keys:
            raise ProtocolViolation("training query set drifted within one catalog")
        accumulator = accumulator_from_history(record.history)
        raw_rows.append(feature_vector(accumulator))
        path_rows.append(path_feature_vector(accumulator))
        diagnosis_rows.append([float(record.diagnostic_target[label]) for label in labels])
        for target in record.rollouts:
            rollout_rows[target.query_key].append(
                [*target.signature, float(target.expected_utility)]
            )
    return _Dataset(
        catalog,
        labels,
        query_keys,
        np.vstack(raw_rows),
        np.vstack(path_rows),
        np.asarray(diagnosis_rows, dtype=np.float64),
        {key: np.asarray(value, dtype=np.float64) for key, value in rollout_rows.items()},
    )


def _catalog_partitions(
    catalogs: tuple[PublicCatalog, ...], records: tuple[PublicTrainingRecord, ...]
) -> tuple[_Dataset, ...]:
    unique: dict[str, PublicCatalog] = {}
    for catalog in catalogs:
        if type(catalog) is not PublicCatalog:
            raise ProtocolViolation("candidate catalogs must be PublicCatalog values")
        if catalog.digest in unique and unique[catalog.digest].to_wire() != catalog.to_wire():
            raise ProtocolViolation("catalog digest collision")
        unique[catalog.digest] = catalog
    grouped: dict[str, list[PublicTrainingRecord]] = {key: [] for key in unique}
    for record in records:
        if record.history.catalog_digest not in grouped:
            raise ProtocolViolation("training record references an unknown catalog")
        grouped[record.history.catalog_digest].append(record)
    return tuple(_dataset_for(unique[key], grouped[key]) for key in sorted(unique))


class LinearSharedCandidate:
    """Base for a single patient representation with stateless linear heads."""

    family_id = "abstract-linear-shared"
    candidate_id = "abstract-linear-shared-v1"

    def __init__(self, *, regularization: float = 1e-3, **_: Any) -> None:
        self.regularization = float(regularization)
        self._models: dict[str, _CatalogModel] = {}
        self._model_seed = 0

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        del model_seed
        data: dict[str, Any] = {}
        return data, np.vstack([self._transform(row, data) for row in dataset.raw])

    def _transform(
        self, raw: np.ndarray, representation_data: dict[str, Any]
    ) -> np.ndarray:
        return raw.copy()

    def fit(
        self,
        catalogs: tuple[PublicCatalog, ...],
        records: tuple[PublicTrainingRecord, ...],
        *,
        model_seed: int,
    ) -> None:
        if type(model_seed) is not int:
            raise ProtocolViolation("model_seed must be an exact integer")
        self._model_seed = model_seed
        models: dict[str, _CatalogModel] = {}
        for dataset in _catalog_partitions(catalogs, records):
            representation_data, z = self._fit_representation(dataset, model_seed)
            if z.ndim != 2 or z.shape[0] != dataset.raw.shape[0]:
                raise ProtocolViolation("candidate representation fit returned wrong shape")
            models[dataset.catalog.digest] = _CatalogModel(
                dataset.catalog,
                dataset.labels,
                dataset.query_keys,
                representation_data,
                _ridge(z, dataset.diagnosis, self.regularization),
                {
                    key: _ridge(z, dataset.rollouts[key], self.regularization)
                    for key in dataset.query_keys
                },
            )
        self._models = models

    def _model(self, catalog_digest: str) -> _CatalogModel:
        model = self._models.get(catalog_digest)
        if model is None:
            raise ProtocolViolation("candidate was not fitted for this public catalog")
        return model

    def _representation_for_accumulator(
        self, accumulator: dict[str, Any], model: _CatalogModel
    ) -> np.ndarray:
        raw = feature_vector(accumulator)
        representation = self._transform(raw, model.representation_data)
        if representation.ndim != 1 or not np.all(np.isfinite(representation)):
            raise ProtocolViolation("candidate state representation is invalid")
        return representation

    def _state(
        self,
        accumulator: dict[str, Any],
        model: _CatalogModel,
        *,
        extra: dict[str, Any] | None = None,
        compactness_class: str = "candidate_shared_state",
    ) -> SharedPatientState:
        representation = self._representation_for_accumulator(accumulator, model)
        wire = {
            "protocol": STATE_PROTOCOL,
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "catalog_digest": model.catalog.digest,
            "accumulator": accumulator,
            "representation": representation.tolist(),
            "extra": extra or {},
        }
        return SharedPatientState(
            f"{self.candidate_id}/state-v1",
            canonical_json_bytes(wire),
            tuple(float(value) for value in representation),
            compactness_class,
        )

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> SharedPatientState:
        del inference_seed
        model = self._model(history.catalog_digest)
        return self._state(accumulator_from_history(history), model)

    def _decoded(self, state: SharedPatientState) -> tuple[dict[str, Any], _CatalogModel, np.ndarray]:
        if type(state) is not SharedPatientState:
            raise ProtocolViolation("head requires SharedPatientState")
        try:
            wire = json.loads(state.payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProtocolViolation("candidate state payload cannot be decoded") from exc
        if (
            wire.get("protocol") != STATE_PROTOCOL
            or wire.get("candidate_id") != self.candidate_id
            or wire.get("family_id") != self.family_id
        ):
            raise ProtocolViolation("candidate state identity mismatch")
        model = self._model(wire["catalog_digest"])
        representation = np.asarray(wire["representation"], dtype=np.float64)
        if tuple(representation.tolist()) != state.distance_vector:
            raise ProtocolViolation("state payload/distance vector mismatch")
        return wire, model, representation

    def update(
        self,
        state: SharedPatientState,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> SharedPatientState:
        del inference_seed
        wire, model, _ = self._decoded(state)
        accumulator = update_accumulator(wire["accumulator"], delta)
        return self._state(accumulator, model)

    def diagnose(
        self,
        state: SharedPatientState,
        label_catalog: tuple[str, ...],
        *,
        query_seed: int,
    ) -> DiagnosisPrediction:
        del query_seed
        _, model, representation = self._decoded(state)
        if label_catalog != model.labels:
            raise ProtocolViolation("diagnosis query labels drifted")
        raw = _predict(model.diagnosis_weights, representation)
        clipped = np.maximum(raw, 1e-9)
        clipped /= clipped.sum()
        return DiagnosisPrediction(
            {label: float(clipped[index]) for index, label in enumerate(model.labels)}
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
        _, model, representation = self._decoded(state)
        key = policy_key(policy, horizon)
        weights = model.rollout_weights.get(key)
        if weights is None:
            return RolloutPrediction((0.0,) * 32, 0.0, abstained=True)
        raw = _predict(weights, representation)
        return RolloutPrediction(
            tuple(float(value) for value in raw[:-1]),
            float(raw[-1]),
            abstained=False,
        )

    def model_summary(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "regularization": self.regularization,
            "model_seed": self._model_seed,
            "catalog_count": len(self._models),
            "parameter_count": sum(
                model.diagnosis_weights.size
                + sum(weights.size for weights in model.rollout_weights.values())
                for model in self._models.values()
            ),
        }


class MechanismVectorCandidate(LinearSharedCandidate):
    family_id = "F01-mechanism-vector"
    candidate_id = "F01-mechanism-vector-v1"


class BeliefStateCandidate(LinearSharedCandidate):
    family_id = "F02-belief-state"
    candidate_id = "F02-gaussian-belief-v1"

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        del model_seed
        class_index = np.argmax(dataset.diagnosis, axis=1)
        means = []
        variances = []
        priors = []
        for index in range(len(dataset.labels)):
            rows = dataset.raw[class_index == index]
            if len(rows) == 0:
                rows = dataset.raw
            means.append(rows.mean(axis=0))
            variances.append(rows.var(axis=0) + 0.05)
            priors.append(max(1, len(rows)))
        priors_array = np.asarray(priors, dtype=np.float64)
        priors_array /= priors_array.sum()
        data = {
            "means": np.vstack(means).tolist(),
            "variances": np.vstack(variances).tolist(),
            "priors": priors_array.tolist(),
        }
        return data, np.vstack([self._transform(row, data) for row in dataset.raw])

    def _transform(
        self, raw: np.ndarray, representation_data: dict[str, Any]
    ) -> np.ndarray:
        means = np.asarray(representation_data["means"], dtype=np.float64)
        variances = np.asarray(representation_data["variances"], dtype=np.float64)
        priors = np.asarray(representation_data["priors"], dtype=np.float64)
        logits = np.log(np.maximum(priors, 1e-12)) - 0.5 * np.sum(
            np.log(variances) + (raw[None, :] - means) ** 2 / variances,
            axis=1,
        )
        logits -= logits.max()
        posterior = np.exp(logits)
        posterior /= posterior.sum()
        return posterior


class PredictiveStateCandidate(LinearSharedCandidate):
    family_id = "F03-controlled-psr"
    candidate_id = "F03-linear-predictive-state-v1"

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        del model_seed
        target = np.concatenate(
            (
                dataset.diagnosis,
                *(dataset.rollouts[key] for key in dataset.query_keys),
            ),
            axis=1,
        )
        encoder = _ridge(dataset.raw, target, self.regularization)
        design = np.concatenate((np.ones((len(dataset.raw), 1)), dataset.raw), axis=1)
        z_full = design @ encoder
        # A fixed low-rank predictive state is the leading SVD coordinate system.
        rank = min(24, z_full.shape[0], z_full.shape[1])
        center = z_full.mean(axis=0)
        _, _, right = np.linalg.svd(z_full - center, full_matrices=False)
        basis = right[:rank].T
        z = (z_full - center) @ basis
        return {
            "encoder": encoder.tolist(),
            "center": center.tolist(),
            "basis": basis.tolist(),
        }, z

    def _transform(
        self, raw: np.ndarray, representation_data: dict[str, Any]
    ) -> np.ndarray:
        encoder = np.asarray(representation_data["encoder"], dtype=np.float64)
        center = np.asarray(representation_data["center"], dtype=np.float64)
        basis = np.asarray(representation_data["basis"], dtype=np.float64)
        predicted_tests = np.concatenate(([1.0], raw)) @ encoder
        return (predicted_tests - center) @ basis


def _kmeans(values: np.ndarray, clusters: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    clusters = min(clusters, len(values))
    chosen = rng.choice(len(values), size=clusters, replace=False)
    centroids = values[chosen].copy()
    assignment = np.zeros(len(values), dtype=np.int64)
    for _ in range(30):
        distances = ((values[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        next_assignment = np.argmin(distances, axis=1)
        if np.array_equal(next_assignment, assignment):
            break
        assignment = next_assignment
        for index in range(clusters):
            rows = values[assignment == index]
            if len(rows):
                centroids[index] = rows.mean(axis=0)
    return centroids, assignment


class CausalStateCandidate(LinearSharedCandidate):
    family_id = "F04-causal-state"
    candidate_id = "F04-behavioral-quotient-v1"

    def __init__(self, *, clusters: int = 8, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.clusters = int(clusters)

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        behavior = np.concatenate(
            (dataset.diagnosis, *(dataset.rollouts[key] for key in dataset.query_keys)),
            axis=1,
        )
        _, assignment = _kmeans(behavior, self.clusters, model_seed)
        feature_centroids = np.vstack(
            [dataset.raw[assignment == index].mean(axis=0) for index in sorted(set(assignment))]
        )
        scale = np.std(dataset.raw, axis=0) + 0.1
        data = {"feature_centroids": feature_centroids.tolist(), "scale": scale.tolist()}
        return data, np.vstack([self._transform(row, data) for row in dataset.raw])

    def _transform(
        self, raw: np.ndarray, representation_data: dict[str, Any]
    ) -> np.ndarray:
        centroids = np.asarray(representation_data["feature_centroids"], dtype=np.float64)
        scale = np.asarray(representation_data["scale"], dtype=np.float64)
        distances = np.sum(((centroids - raw[None, :]) / scale) ** 2, axis=1)
        logits = -0.5 * distances
        logits -= logits.max()
        posterior = np.exp(logits)
        posterior /= posterior.sum()
        return posterior


class DynamicSCMCandidate(LinearSharedCandidate):
    family_id = "F05-dynamic-scm"
    candidate_id = "F05-structural-interaction-state-v1"

    def _transform(
        self, raw: np.ndarray, representation_data: dict[str, Any]
    ) -> np.ndarray:
        del representation_data
        observations = raw[: 4 * OBSERVATION_BINS].reshape(OBSERVATION_BINS, 4)
        last = observations[:, 0]
        mean = observations[:, 1]
        slope = observations[:, 2]
        exposure = raw[4 * OBSERVATION_BINS : 4 * OBSERVATION_BINS + ACTION_BINS]
        interactions = last[:ACTION_BINS] * (1.0 + exposure)
        return np.concatenate((last, mean, slope, exposure, interactions))


class KoopmanCandidate(LinearSharedCandidate):
    family_id = "F06-koopman"
    candidate_id = "F06-polynomial-observable-operator-v1"

    def _transform(
        self, raw: np.ndarray, representation_data: dict[str, Any]
    ) -> np.ndarray:
        del representation_data
        base = raw[:32]
        return np.concatenate((base, base**2, base[:-1] * base[1:]))


class NeuralWorldCandidate(LinearSharedCandidate):
    family_id = "F07-neural-world-model"
    candidate_id = "F07-single-neural-latent-v1"

    def __init__(self, *, hidden_dim: int = 32, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.hidden_dim = int(hidden_dim)

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        rng = np.random.default_rng(model_seed ^ int(dataset.catalog.digest[7:15], 16))
        scale = np.std(dataset.raw, axis=0) + 0.1
        weights = rng.normal(0.0, 1.0 / math.sqrt(dataset.raw.shape[1]), (dataset.raw.shape[1], self.hidden_dim))
        bias = rng.normal(0.0, 0.2, self.hidden_dim)
        data = {"scale": scale.tolist(), "weights": weights.tolist(), "bias": bias.tolist()}
        return data, np.vstack([self._transform(row, data) for row in dataset.raw])

    def _transform(
        self, raw: np.ndarray, representation_data: dict[str, Any]
    ) -> np.ndarray:
        scale = np.asarray(representation_data["scale"], dtype=np.float64)
        weights = np.asarray(representation_data["weights"], dtype=np.float64)
        bias = np.asarray(representation_data["bias"], dtype=np.float64)
        return np.tanh((raw / scale) @ weights + bias)


class MechanismGraphCandidate(LinearSharedCandidate):
    family_id = "F08-mechanism-graph"
    candidate_id = "F08-message-passing-mechanism-graph-v1"

    def _transform(
        self, raw: np.ndarray, representation_data: dict[str, Any]
    ) -> np.ndarray:
        del representation_data
        nodes = raw[: 4 * OBSERVATION_BINS].reshape(OBSERVATION_BINS, 4)
        left = np.roll(nodes, 1, axis=0)
        right = np.roll(nodes, -1, axis=0)
        first = np.tanh(nodes + 0.25 * (left + right))
        second = np.tanh(first + 0.25 * (np.roll(first, 1, axis=0) + np.roll(first, -1, axis=0)))
        treatments = raw[4 * OBSERVATION_BINS : 4 * OBSERVATION_BINS + ACTION_BINS]
        return np.concatenate((second.ravel(), treatments))


class RecursivePathCandidate(LinearSharedCandidate):
    """Two-timescale recursive event-order and availability state."""

    family_id = "F09-recursive-path-state"
    candidate_id = "F09-two-timescale-path-state-v1"

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        del model_seed
        return {}, dataset.path.copy()

    def _representation_for_accumulator(
        self, accumulator: dict[str, Any], model: _CatalogModel
    ) -> np.ndarray:
        del model
        return path_feature_vector(accumulator)


def _support_data(dataset: _Dataset) -> dict[str, Any]:
    scale = np.std(dataset.path, axis=0) + 0.1
    normalized = dataset.path / scale
    if len(normalized) > 1:
        pair = np.sqrt(
            np.sum((normalized[:, None, :] - normalized[None, :, :]) ** 2, axis=2)
        )
        pair += np.eye(len(pair)) * 1e12
        nearest = np.min(pair, axis=1)
        reference = float(np.quantile(nearest, 0.90))
    else:
        reference = 1.0
    return {
        "exemplars": dataset.path.tolist(),
        "diagnosis_targets": dataset.diagnosis.tolist(),
        "scale": scale.tolist(),
        "reference_distance": max(reference, 1e-6),
        "label_count": len(dataset.labels),
    }


def _support_transform(path: np.ndarray, data: dict[str, Any]) -> np.ndarray:
    exemplars = np.asarray(data["exemplars"], dtype=np.float64)
    targets = np.asarray(data["diagnosis_targets"], dtype=np.float64)
    scale = np.asarray(data["scale"], dtype=np.float64)
    distances = np.sqrt(np.sum(((exemplars - path[None, :]) / scale) ** 2, axis=1))
    reference = float(data["reference_distance"])
    weights = np.exp(-0.5 * (distances / reference) ** 2)
    if float(weights.sum()) <= 1e-15:
        posterior = targets.mean(axis=0)
    else:
        posterior = weights @ targets / weights.sum()
    minimum = float(distances.min())
    novelty = 1.0 - math.exp(-max(0.0, minimum - reference) / reference)
    return np.concatenate((posterior, [minimum / reference, novelty]))


class SupportAwareBeliefCandidate(LinearSharedCandidate):
    """Nonparametric support/posterior belief stored inside the shared state."""

    family_id = "F10-support-aware-belief"
    candidate_id = "F10-nonparametric-support-belief-v1"

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        del model_seed
        data = _support_data(dataset)
        return data, np.vstack([_support_transform(row, data) for row in dataset.path])

    def _representation_for_accumulator(
        self, accumulator: dict[str, Any], model: _CatalogModel
    ) -> np.ndarray:
        return _support_transform(path_feature_vector(accumulator), model.representation_data)

    def diagnose(
        self,
        state: SharedPatientState,
        label_catalog: tuple[str, ...],
        *,
        query_seed: int,
    ) -> DiagnosisPrediction:
        del query_seed
        _, model, representation = self._decoded(state)
        if label_catalog != model.labels:
            raise ProtocolViolation("diagnosis query labels drifted")
        probabilities = np.maximum(representation[: len(model.labels)], 1e-12)
        if "unknown" in model.labels:
            unknown = model.labels.index("unknown")
            probabilities[unknown] = max(probabilities[unknown], representation[-1])
        probabilities /= probabilities.sum()
        return DiagnosisPrediction(
            {label: float(probabilities[index]) for index, label in enumerate(model.labels)}
        )


class PathCausalStateCandidate(CausalStateCandidate):
    """Behavioral quotient learned from an order-aware recursive public state."""

    family_id = "F11-path-causal-state"
    candidate_id = "F11-order-aware-behavioral-quotient-v1"

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        behavior = np.concatenate(
            (dataset.diagnosis, *(dataset.rollouts[key] for key in dataset.query_keys)),
            axis=1,
        )
        _, assignment = _kmeans(behavior, self.clusters, model_seed)
        feature_centroids = np.vstack(
            [dataset.path[assignment == index].mean(axis=0) for index in sorted(set(assignment))]
        )
        scale = np.std(dataset.path, axis=0) + 0.1
        data = {"feature_centroids": feature_centroids.tolist(), "scale": scale.tolist()}
        return data, np.vstack([self._transform(row, data) for row in dataset.path])

    def _representation_for_accumulator(
        self, accumulator: dict[str, Any], model: _CatalogModel
    ) -> np.ndarray:
        return self._transform(path_feature_vector(accumulator), model.representation_data)


class PathSupportCausalCandidate(PathCausalStateCandidate):
    """Order-aware behavioral clusters plus in-state epistemic support belief."""

    family_id = "F12-path-support-causal"
    candidate_id = "F12-path-support-behavioral-state-v1"

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        behavior = np.concatenate(
            (dataset.diagnosis, *(dataset.rollouts[key] for key in dataset.query_keys)),
            axis=1,
        )
        _, assignment = _kmeans(behavior, self.clusters, model_seed)
        feature_centroids = np.vstack(
            [dataset.path[assignment == index].mean(axis=0) for index in sorted(set(assignment))]
        )
        cluster_scale = np.std(dataset.path, axis=0) + 0.1
        support = _support_data(dataset)
        data = {
            "feature_centroids": feature_centroids.tolist(),
            "scale": cluster_scale.tolist(),
            "support": support,
            "cluster_count": len(feature_centroids),
        }
        z = np.vstack([self._combined(row, data) for row in dataset.path])
        return data, z

    @staticmethod
    def _combined(path: np.ndarray, data: dict[str, Any]) -> np.ndarray:
        centroids = np.asarray(data["feature_centroids"], dtype=np.float64)
        scale = np.asarray(data["scale"], dtype=np.float64)
        distances = np.sum(((centroids - path[None, :]) / scale) ** 2, axis=1)
        logits = -0.5 * distances
        logits -= logits.max()
        clusters = np.exp(logits)
        clusters /= clusters.sum()
        return np.concatenate((clusters, _support_transform(path, data["support"])))

    def _representation_for_accumulator(
        self, accumulator: dict[str, Any], model: _CatalogModel
    ) -> np.ndarray:
        return self._combined(path_feature_vector(accumulator), model.representation_data)

    def diagnose(
        self,
        state: SharedPatientState,
        label_catalog: tuple[str, ...],
        *,
        query_seed: int,
    ) -> DiagnosisPrediction:
        del query_seed
        _, model, representation = self._decoded(state)
        if label_catalog != model.labels:
            raise ProtocolViolation("diagnosis query labels drifted")
        offset = int(model.representation_data["cluster_count"])
        probabilities = np.maximum(
            representation[offset : offset + len(model.labels)], 1e-12
        )
        if "unknown" in model.labels:
            unknown = model.labels.index("unknown")
            probabilities[unknown] = max(probabilities[unknown], representation[-1])
        probabilities /= probabilities.sum()
        return DiagnosisPrediction(
            {label: float(probabilities[index]) for index, label in enumerate(model.labels)}
        )


class FullHistoryBaseline(MechanismVectorCandidate):
    family_id = "B02-full-history"
    candidate_id = "B02-full-visible-history-v1"

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> SharedPatientState:
        del inference_seed
        model = self._model(history.catalog_digest)
        accumulator = accumulator_from_history(history)
        event_sketch = np.zeros(32, dtype=np.float64)
        for event in history.events:
            raw = canonical_json_bytes(event.to_wire())
            digest = hashlib.sha256(b"UCM_FULL_HISTORY_SKETCH_V1\0" + raw).digest()
            event_sketch[int.from_bytes(digest[:2], "big") % len(event_sketch)] += 1.0
        representation = self._representation_for_accumulator(accumulator, model)
        extra = {"visible_history": history.to_wire()}
        state = self._state(
            accumulator,
            model,
            extra=extra,
            compactness_class="full_visible_history_baseline",
        )
        # Count the exact history payload in state size and expose history-sensitive distance.
        wire = json.loads(state.payload)
        return SharedPatientState(
            state.schema_version,
            canonical_json_bytes(wire),
            tuple(np.concatenate((representation, event_sketch)).tolist()),
            "full_visible_history_baseline",
        )

    def _decoded(self, state: SharedPatientState) -> tuple[dict[str, Any], _CatalogModel, np.ndarray]:
        # Heads use the stored representation, not the retained history baseline field.
        if type(state) is not SharedPatientState:
            raise ProtocolViolation("head requires SharedPatientState")
        wire = json.loads(state.payload)
        model = self._model(wire["catalog_digest"])
        representation = np.asarray(wire["representation"], dtype=np.float64)
        if tuple(representation.tolist()) != state.distance_vector[: len(representation)]:
            raise ProtocolViolation("full-history state representation mismatch")
        return wire, model, representation

    def update(
        self,
        state: SharedPatientState,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> SharedPatientState:
        del inference_seed
        wire, model, _ = self._decoded(state)
        if not delta.events and delta.advance_to == wire["accumulator"]["as_of"]:
            return state
        accumulator = update_accumulator(wire["accumulator"], delta)
        # The baseline intentionally retains the complete visible sequence.  A
        # later non-empty delta is appended without giving heads a history input.
        history_wire = json.loads(canonical_json_bytes(wire["extra"]["visible_history"]))
        history_wire["as_of_available_at"] = delta.advance_to
        history_wire["events"].extend(event.to_wire() for event in delta.events)
        representation = self._representation_for_accumulator(accumulator, model)
        event_sketch = np.zeros(32, dtype=np.float64)
        for event_wire in history_wire["events"]:
            raw = canonical_json_bytes(event_wire)
            digest = hashlib.sha256(b"UCM_FULL_HISTORY_SKETCH_V1\0" + raw).digest()
            event_sketch[int.from_bytes(digest[:2], "big") % len(event_sketch)] += 1.0
        payload = {
            "protocol": STATE_PROTOCOL,
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "catalog_digest": model.catalog.digest,
            "accumulator": accumulator,
            "representation": representation.tolist(),
            "extra": {"visible_history": history_wire},
        }
        return SharedPatientState(
            f"{self.candidate_id}/state-v1",
            canonical_json_bytes(payload),
            tuple(np.concatenate((representation, event_sketch)).tolist()),
            "full_visible_history_baseline",
        )


class K0OnlyBaseline(LinearSharedCandidate):
    family_id = "B04-k0-only"
    candidate_id = "B04-k0-control-plane-only-v1"

    def _fit_representation(
        self, dataset: _Dataset, model_seed: int
    ) -> tuple[dict[str, Any], np.ndarray]:
        del model_seed
        # Only custody/timing metadata, deliberately no patient physiology.
        z = dataset.raw[:, -2:]
        return {}, z

    def _transform(
        self, raw: np.ndarray, representation_data: dict[str, Any]
    ) -> np.ndarray:
        del representation_data
        return raw[-2:]

    def _state(
        self,
        accumulator: dict[str, Any],
        model: _CatalogModel,
        *,
        extra: dict[str, Any] | None = None,
        compactness_class: str = "k0_only_baseline",
    ) -> SharedPatientState:
        return super()._state(
            accumulator,
            model,
            extra=extra,
            compactness_class="k0_only_baseline",
        )


class SeparateTaskBaseline(LinearSharedCandidate):
    """Deliberate non-UCM baseline with three separately fitted patient latents."""

    family_id = "B03-separate-task"
    candidate_id = "B03-separate-task-latents-v1"

    def _state(
        self,
        accumulator: dict[str, Any],
        model: _CatalogModel,
        *,
        extra: dict[str, Any] | None = None,
        compactness_class: str = "separate_task_baseline",
    ) -> SharedPatientState:
        raw = feature_vector(accumulator)
        diagnosis_state = raw[:40]
        natural_state = raw[16:64]
        intervention_state = np.concatenate((raw[:32], raw[64:80]))
        # For score comparability the trained readout still uses the full state,
        # but the payload truthfully exposes the three patient-specific paths.
        representation = self._representation_for_accumulator(accumulator, model)
        wire = {
            "protocol": STATE_PROTOCOL,
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "catalog_digest": model.catalog.digest,
            "accumulator": accumulator,
            "representation": representation.tolist(),
            "task_states": {
                "diagnosis": diagnosis_state.tolist(),
                "natural": natural_state.tolist(),
                "intervention": intervention_state.tolist(),
            },
            "extra": extra or {},
        }
        return SharedPatientState(
            f"{self.candidate_id}/state-v1",
            canonical_json_bytes(wire),
            tuple(np.concatenate((diagnosis_state, natural_state, intervention_state)).tolist()),
            "separate_task_baseline",
        )

    def _decoded(self, state: SharedPatientState) -> tuple[dict[str, Any], _CatalogModel, np.ndarray]:
        wire = json.loads(state.payload)
        if wire.get("candidate_id") != self.candidate_id:
            raise ProtocolViolation("separate-task state identity mismatch")
        model = self._model(wire["catalog_digest"])
        return wire, model, np.asarray(wire["representation"], dtype=np.float64)


CANDIDATE_FACTORIES: dict[str, Callable[..., LinearSharedCandidate]] = {
    "F01": MechanismVectorCandidate,
    "F02": BeliefStateCandidate,
    "F03": PredictiveStateCandidate,
    "F04": CausalStateCandidate,
    "F05": DynamicSCMCandidate,
    "F06": KoopmanCandidate,
    "F07": NeuralWorldCandidate,
    "F08": MechanismGraphCandidate,
    "F09": RecursivePathCandidate,
    "F10": SupportAwareBeliefCandidate,
    "F11": PathCausalStateCandidate,
    "F12": PathSupportCausalCandidate,
    "B02": FullHistoryBaseline,
    "B03": SeparateTaskBaseline,
    "B04": K0OnlyBaseline,
}


def make_candidate(family_code: str, **parameters: Any) -> LinearSharedCandidate:
    factory = CANDIDATE_FACTORIES.get(family_code)
    if factory is None:
        raise ProtocolViolation(f"unknown candidate family {family_code!r}")
    return factory(**parameters)


__all__ = [
    "BeliefStateCandidate",
    "CANDIDATE_FACTORIES",
    "CausalStateCandidate",
    "DynamicSCMCandidate",
    "FullHistoryBaseline",
    "K0OnlyBaseline",
    "KoopmanCandidate",
    "MechanismGraphCandidate",
    "MechanismVectorCandidate",
    "NeuralWorldCandidate",
    "PathCausalStateCandidate",
    "PathSupportCausalCandidate",
    "PredictiveStateCandidate",
    "RecursivePathCandidate",
    "SeparateTaskBaseline",
    "SupportAwareBeliefCandidate",
    "accumulator_from_history",
    "feature_vector",
    "make_candidate",
    "path_feature_vector",
    "update_accumulator",
]
