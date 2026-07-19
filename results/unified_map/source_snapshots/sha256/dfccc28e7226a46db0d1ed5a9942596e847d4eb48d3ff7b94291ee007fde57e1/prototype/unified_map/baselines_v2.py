"""Honest, ineligible comparison baselines for UCM benchmark v1.

``B02V2`` retains the complete visible event sequence in its patient state and
recomputes a sequence-kernel representation from those exact bytes for every
head.  It is intentionally not a compressed UCM candidate.

``B03V2`` retains three complete, independently fitted patient states and
routes diagnosis, natural-history and intervention queries to different
models.  It is intentionally a non-shared-state comparison baseline.
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
from .candidate_families import make_candidate
from .canonical import ProtocolViolation, canonical_json_bytes, validate_json_like
from .schema import ActionPlan, PlanKind, VisibleDelta, VisibleHistory
from .worlds.base import PublicCatalog


FULL_HISTORY_PROTOCOL = "ucm-b02-v2-exact-visible-history/1"
SEPARATE_TASK_PROTOCOL = "ucm-b03-v2-separate-task-state/1"
FULL_HISTORY_FEATURE_DIMENSION = 256
NATURAL_PLAN_KINDS = frozenset({PlanKind.NO_NEW_ACTION, PlanKind.CONTINUE_CURRENT})


def _ridge(x: np.ndarray, y: np.ndarray, regularization: float) -> np.ndarray:
    if x.ndim != 2 or y.ndim != 2 or x.shape[0] != y.shape[0]:
        raise ProtocolViolation("baseline ridge inputs are not aligned matrices")
    design = np.concatenate((np.ones((x.shape[0], 1)), x), axis=1)
    penalty = np.eye(design.shape[1], dtype=np.float64) * regularization
    penalty[0, 0] = 0.0
    return np.linalg.pinv(design.T @ design + penalty, rcond=1e-10) @ design.T @ y


def _predict(weights: np.ndarray, representation: np.ndarray) -> np.ndarray:
    return np.concatenate(([1.0], representation)) @ weights


def _history_sort_key(event: dict[str, Any]) -> tuple[int, int, str, str]:
    return (
        int(event["available_at"]),
        int(event["occurred_at"]),
        str(event["kind"]),
        str(event["event_uid"]),
    )


def _validate_history_wire(wire: Any) -> dict[str, Any]:
    validate_json_like(wire, path="full history baseline state")
    if type(wire) is not dict or wire.get("protocol") != "ucm-visible-history/1":
        raise ProtocolViolation("full-history state does not contain a visible history")
    if type(wire.get("as_of_available_at")) is not int:
        raise ProtocolViolation("full-history cut must be an exact integer")
    catalog_digest = wire.get("catalog_digest")
    if (
        type(catalog_digest) is not str
        or not catalog_digest.startswith("sha256:")
        or len(catalog_digest) != 71
    ):
        raise ProtocolViolation("full-history catalog digest is invalid")
    events = wire.get("events")
    if type(events) is not list:
        raise ProtocolViolation("full-history events must be an exact list")
    required = {"kind", "occurred_at", "collected_at", "available_at", "event_uid", "payload"}
    for event in events:
        if type(event) is not dict or set(event) != required:
            raise ProtocolViolation("full-history event wire shape drifted")
        if type(event["kind"]) is not str or type(event["event_uid"]) is not str:
            raise ProtocolViolation("full-history event identity is invalid")
        if type(event["occurred_at"]) is not int or type(event["available_at"]) is not int:
            raise ProtocolViolation("full-history event time is invalid")
        if event["collected_at"] is not None and type(event["collected_at"]) is not int:
            raise ProtocolViolation("full-history collection time is invalid")
        if type(event["payload"]) is not dict:
            raise ProtocolViolation("full-history event payload is invalid")
        if event["available_at"] > wire["as_of_available_at"]:
            raise ProtocolViolation("full-history state contains future-visible data")
    if events != sorted(events, key=_history_sort_key):
        raise ProtocolViolation("full-history state events are not canonically ordered")
    uids = [event["event_uid"] for event in events]
    if len(uids) != len(set(uids)):
        raise ProtocolViolation("full-history state contains duplicate event UIDs")
    return wire


def _project(vector: np.ndarray, domain: bytes, token: bytes, value: float, *, start: int, width: int) -> None:
    digest = hashlib.sha256(domain + token).digest()
    index = start + int.from_bytes(digest[:4], "big") % width
    sign = -1.0 if digest[4] & 1 else 1.0
    vector[index] += sign * float(value)


def _flatten_payload(value: Any, path: str = "payload") -> list[tuple[str, Any]]:
    if type(value) is dict:
        rows: list[tuple[str, Any]] = []
        for key in sorted(value):
            rows.extend(_flatten_payload(value[key], f"{path}.{key}"))
        return rows
    if type(value) is list:
        rows = []
        for index, item in enumerate(value):
            rows.extend(_flatten_payload(item, f"{path}[{index}]"))
        return rows
    return [(path, value)]


def exact_history_feature_vector(history_wire: dict[str, Any]) -> np.ndarray:
    """Embed every exact visible event while retaining order and numeric values.

    This is a readout feature, not the patient state: B02V2 stores the complete
    uncompressed history wire and recomputes this vector after deserialization.
    """

    wire = _validate_history_wire(history_wire)
    vector = np.zeros(FULL_HISTORY_FEATURE_DIMENSION, dtype=np.float64)
    events = wire["events"]
    as_of = wire["as_of_available_at"]
    vector[0] = math.tanh(float(as_of) / 32.0)
    vector[1] = math.log1p(len(events))
    for position, event in enumerate(events):
        order = (position + 1.0) / max(1.0, float(len(events)))
        availability = math.tanh((float(event["available_at"]) - as_of) / 32.0)
        lag = math.tanh((float(event["available_at"]) - event["occurred_at"]) / 32.0)
        collected = event["collected_at"]
        collection_lag = 0.0 if collected is None else math.tanh(
            (float(event["available_at"]) - collected) / 32.0
        )
        semantic = {
            "kind": event["kind"],
            "payload": event["payload"],
            "availability_lag": event["available_at"] - event["occurred_at"],
            "collection_lag": None if collected is None else event["available_at"] - collected,
        }
        token = canonical_json_bytes(semantic)
        for channel, value in enumerate((1.0, order, availability, lag, collection_lag)):
            _project(
                vector,
                b"UCM_B02_V2_SEMANTIC\0" + bytes([channel]),
                token,
                value,
                start=2,
                width=126,
            )
        for path, value in _flatten_payload(event["payload"]):
            path_bytes = path.encode("utf-8")
            if type(value) in {int, float} and type(value) is not bool:
                number = math.tanh(float(value) / 32.0)
                _project(vector, b"UCM_B02_V2_NUMERIC\0", path_bytes, number, start=128, width=64)
                _project(vector, b"UCM_B02_V2_NUMERIC_ORDER\0", path_bytes, number * order, start=128, width=64)
            else:
                leaf = canonical_json_bytes({"path": path, "value": value})
                _project(vector, b"UCM_B02_V2_CATEGORICAL\0", leaf, 1.0, start=128, width=64)
                _project(vector, b"UCM_B02_V2_CATEGORICAL_ORDER\0", leaf, order, start=128, width=64)
        # The exact wire (including UID and timestamps) gets a low-amplitude
        # channel.  Thus even details ignored by legacy accumulators affect the
        # readout while semantic proximity still dominates generalization.
        exact = canonical_json_bytes(event)
        _project(vector, b"UCM_B02_V2_EXACT\0", exact, 0.05, start=192, width=64)
        _project(vector, b"UCM_B02_V2_EXACT_ORDER\0", exact, 0.05 * order, start=192, width=64)
    if not np.all(np.isfinite(vector)):
        raise ProtocolViolation("full-history feature vector is non-finite")
    return vector


@dataclass(slots=True)
class _FullHistoryModel:
    catalog: PublicCatalog
    labels: tuple[str, ...]
    query_keys: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    landmarks: np.ndarray
    bandwidth: float
    diagnosis_weights: np.ndarray
    rollout_weights: dict[str, np.ndarray]


class ExactFullHistoryBaselineV2:
    """High-capacity exact-visible-history baseline; never promotion eligible."""

    family_id = "B02V2-exact-full-history"
    candidate_id = "B02V2-sequence-kernel-full-history-v1"

    def __init__(self, *, regularization: float = 1e-5, **_: Any) -> None:
        self.regularization = float(regularization)
        self._models: dict[str, _FullHistoryModel] = {}
        self._model_seed = 0

    @staticmethod
    def _kernel(raw: np.ndarray, model: _FullHistoryModel) -> np.ndarray:
        normalized = (raw - model.mean) / model.scale
        distance = np.mean((model.landmarks - normalized[None, :]) ** 2, axis=1)
        return np.exp(-distance / (2.0 * model.bandwidth**2))

    def fit(
        self,
        catalogs: tuple[PublicCatalog, ...],
        records: tuple[PublicTrainingRecord, ...],
        *,
        model_seed: int,
    ) -> None:
        if type(model_seed) is not int:
            raise ProtocolViolation("model_seed must be an exact integer")
        unique = {catalog.digest: catalog for catalog in catalogs}
        grouped: dict[str, list[PublicTrainingRecord]] = {digest: [] for digest in unique}
        for record in records:
            if record.history.catalog_digest not in grouped:
                raise ProtocolViolation("full-history training record has unknown catalog")
            grouped[record.history.catalog_digest].append(record)
        models: dict[str, _FullHistoryModel] = {}
        for digest in sorted(unique):
            rows = grouped[digest]
            if not rows:
                raise ProtocolViolation("full-history baseline received an empty partition")
            labels = unique[digest].diagnostic_labels
            query_keys = tuple(target.query_key for target in rows[0].rollouts)
            if any(tuple(target.query_key for target in row.rollouts) != query_keys for row in rows):
                raise ProtocolViolation("full-history training query set drifted")
            raw = np.vstack([exact_history_feature_vector(row.history.to_wire()) for row in rows])
            mean = raw.mean(axis=0)
            scale = raw.std(axis=0)
            scale[scale < 1e-8] = 1.0
            landmarks = (raw - mean) / scale
            pairwise = np.sqrt(np.mean((landmarks[:, None, :] - landmarks[None, :, :]) ** 2, axis=2))
            positive = pairwise[pairwise > 1e-12]
            bandwidth = float(np.median(positive)) if positive.size else 1.0
            shell = _FullHistoryModel(unique[digest], labels, query_keys, mean, scale, landmarks, bandwidth, np.empty((0, 0)), {})
            z = np.vstack([self._kernel(row, shell) for row in raw])
            diagnosis = np.asarray(
                [[float(row.diagnostic_target[label]) for label in labels] for row in rows],
                dtype=np.float64,
            )
            rollouts = {
                key: np.asarray(
                    [[*row.rollouts[index].signature, float(row.rollouts[index].expected_utility)] for row in rows],
                    dtype=np.float64,
                )
                for index, key in enumerate(query_keys)
            }
            shell.diagnosis_weights = _ridge(z, diagnosis, self.regularization)
            shell.rollout_weights = {
                key: _ridge(z, target, self.regularization) for key, target in rollouts.items()
            }
            models[digest] = shell
        self._models = models
        self._model_seed = model_seed

    def _model(self, digest: str) -> _FullHistoryModel:
        model = self._models.get(digest)
        if model is None:
            raise ProtocolViolation("full-history baseline was not fitted for this catalog")
        return model

    def _state(self, history_wire: dict[str, Any]) -> SharedPatientState:
        history_wire = _validate_history_wire(history_wire)
        model = self._model(history_wire["catalog_digest"])
        representation = self._kernel(exact_history_feature_vector(history_wire), model)
        exact_digest = hashlib.sha256(canonical_json_bytes(history_wire)).digest()
        identity = np.frombuffer(exact_digest, dtype=np.uint8).astype(np.float64) / 255.0
        payload = {
            "protocol": FULL_HISTORY_PROTOCOL,
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "catalog_digest": history_wire["catalog_digest"],
            "visible_history": history_wire,
            "storage_semantics": "exact_uncompressed_visible_history",
            "eligibility": "baseline_only_ineligible",
        }
        return SharedPatientState(
            f"{self.candidate_id}/state-v1",
            canonical_json_bytes(payload),
            tuple(np.concatenate((representation, identity)).tolist()),
            "full_visible_history_baseline",
        )

    def initialize(self, history: VisibleHistory, *, inference_seed: int) -> SharedPatientState:
        del inference_seed
        if type(history) is not VisibleHistory:
            raise ProtocolViolation("full-history initialize requires VisibleHistory")
        return self._state(history.to_wire())

    def _decoded(self, state: SharedPatientState) -> tuple[dict[str, Any], _FullHistoryModel, np.ndarray]:
        if type(state) is not SharedPatientState or state.compactness_class != "full_visible_history_baseline":
            raise ProtocolViolation("full-history head requires its baseline state")
        wire = json.loads(state.payload)
        if (
            wire.get("protocol") != FULL_HISTORY_PROTOCOL
            or wire.get("candidate_id") != self.candidate_id
            or wire.get("family_id") != self.family_id
            or wire.get("storage_semantics") != "exact_uncompressed_visible_history"
        ):
            raise ProtocolViolation("full-history state identity drifted")
        history_wire = _validate_history_wire(wire.get("visible_history"))
        if history_wire["catalog_digest"] != wire.get("catalog_digest"):
            raise ProtocolViolation("full-history state catalog identity drifted")
        model = self._model(history_wire["catalog_digest"])
        representation = self._kernel(exact_history_feature_vector(history_wire), model)
        exact_digest = hashlib.sha256(canonical_json_bytes(history_wire)).digest()
        identity = np.frombuffer(exact_digest, dtype=np.uint8).astype(np.float64) / 255.0
        expected = tuple(np.concatenate((representation, identity)).tolist())
        if expected != state.distance_vector:
            raise ProtocolViolation("full-history state/readout representation mismatch")
        return history_wire, model, representation

    def update(
        self,
        state: SharedPatientState,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> SharedPatientState:
        del inference_seed
        if type(delta) is not VisibleDelta:
            raise ProtocolViolation("full-history update requires VisibleDelta")
        history, _, _ = self._decoded(state)
        old_cut = history["as_of_available_at"]
        if delta.advance_to < old_cut:
            raise ProtocolViolation("full-history update cannot move backward")
        if not delta.events and delta.advance_to == old_cut:
            return state
        old_uids = {event["event_uid"] for event in history["events"]}
        if any(event.event_uid in old_uids for event in delta.events):
            raise ProtocolViolation("full-history update repeats an event UID")
        merged = [*history["events"], *(event.to_wire() for event in delta.events)]
        updated = {
            "protocol": "ucm-visible-history/1",
            "as_of_available_at": delta.advance_to,
            "catalog_digest": history["catalog_digest"],
            "events": sorted(merged, key=_history_sort_key),
        }
        return self._state(updated)

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
            raise ProtocolViolation("full-history diagnosis label catalog drifted")
        raw = np.maximum(_predict(model.diagnosis_weights, representation), 1e-9)
        raw /= raw.sum()
        return DiagnosisPrediction({label: float(raw[index]) for index, label in enumerate(model.labels)})

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
        weights = model.rollout_weights.get(policy_key(policy, horizon))
        if weights is None:
            return RolloutPrediction((0.0,) * 32, 0.0, abstained=True)
        raw = _predict(weights, representation)
        return RolloutPrediction(tuple(float(value) for value in raw[:-1]), float(raw[-1]))

    def model_summary(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "eligibility": "baseline_only_ineligible",
            "patient_state_semantics": "exact_uncompressed_visible_history",
            "readout": "full-history-derived sequence-kernel ridge",
            "regularization": self.regularization,
            "model_seed": self._model_seed,
            "catalog_count": len(self._models),
            "parameter_count": sum(
                model.landmarks.size
                + model.diagnosis_weights.size
                + sum(weights.size for weights in model.rollout_weights.values())
                for model in self._models.values()
            ),
        }


def _child_to_wire(state: SharedPatientState) -> dict[str, Any]:
    return {
        "schema_version": state.schema_version,
        "payload": json.loads(state.payload),
        "distance_vector": list(state.distance_vector),
        "compactness_class": state.compactness_class,
    }


def _child_from_wire(wire: Any) -> SharedPatientState:
    validate_json_like(wire, path="separate-task child state")
    if type(wire) is not dict or set(wire) != {
        "schema_version", "payload", "distance_vector", "compactness_class"
    }:
        raise ProtocolViolation("separate-task child state shape drifted")
    if type(wire["distance_vector"]) is not list:
        raise ProtocolViolation("separate-task child distance vector is invalid")
    return SharedPatientState(
        wire["schema_version"],
        canonical_json_bytes(wire["payload"]),
        tuple(wire["distance_vector"]),
        wire["compactness_class"],
    )


class SeparateTaskBaselineV2:
    """Three independent patient models; deliberately violates UCM sharing."""

    family_id = "B03V2-separate-task-models"
    candidate_id = "B03V2-three-independent-patient-states-v1"
    component_codes = {"diagnosis": "F10", "natural": "F14", "intervention": "F18"}

    def __init__(self, **parameters: Any) -> None:
        self._parameters = dict(parameters)
        self._components = {
            task: make_candidate(code, **parameters) for task, code in self.component_codes.items()
        }
        self._model_seed = 0

    def fit(
        self,
        catalogs: tuple[PublicCatalog, ...],
        records: tuple[PublicTrainingRecord, ...],
        *,
        model_seed: int,
    ) -> None:
        if type(model_seed) is not int:
            raise ProtocolViolation("model_seed must be an exact integer")
        for component in self._components.values():
            component.fit(catalogs, records, model_seed=model_seed)
        self._model_seed = model_seed

    def _state(self, task_states: dict[str, SharedPatientState]) -> SharedPatientState:
        if set(task_states) != set(self.component_codes):
            raise ProtocolViolation("separate-task baseline requires exactly three states")
        wire = {
            "protocol": SEPARATE_TASK_PROTOCOL,
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "eligibility": "baseline_only_non_ucm",
            "task_states": {task: _child_to_wire(task_states[task]) for task in sorted(task_states)},
        }
        distance = tuple(
            number
            for task in sorted(task_states)
            for number in task_states[task].distance_vector
        )
        return SharedPatientState(
            f"{self.candidate_id}/state-v1",
            canonical_json_bytes(wire),
            distance,
            "separate_task_baseline",
        )

    def initialize(self, history: VisibleHistory, *, inference_seed: int) -> SharedPatientState:
        return self._state(
            {
                task: component.initialize(history, inference_seed=inference_seed)
                for task, component in self._components.items()
            }
        )

    def _decoded(self, state: SharedPatientState) -> dict[str, SharedPatientState]:
        if type(state) is not SharedPatientState or state.compactness_class != "separate_task_baseline":
            raise ProtocolViolation("separate-task head requires its baseline state")
        wire = json.loads(state.payload)
        if (
            wire.get("protocol") != SEPARATE_TASK_PROTOCOL
            or wire.get("candidate_id") != self.candidate_id
            or wire.get("family_id") != self.family_id
            or wire.get("eligibility") != "baseline_only_non_ucm"
            or type(wire.get("task_states")) is not dict
            or set(wire["task_states"]) != set(self.component_codes)
        ):
            raise ProtocolViolation("separate-task state identity drifted")
        children = {task: _child_from_wire(value) for task, value in wire["task_states"].items()}
        expected = tuple(
            number for task in sorted(children) for number in children[task].distance_vector
        )
        if expected != state.distance_vector:
            raise ProtocolViolation("separate-task outer/child distance mismatch")
        return children

    def update(
        self,
        state: SharedPatientState,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> SharedPatientState:
        if type(delta) is not VisibleDelta:
            raise ProtocolViolation("separate-task update requires VisibleDelta")
        children = self._decoded(state)
        updated = {
            task: self._components[task].update(
                children[task], delta, inference_seed=inference_seed
            )
            for task in self.component_codes
        }
        result = self._state(updated)
        return state if result.state_hash == state.state_hash else result

    def diagnose(
        self,
        state: SharedPatientState,
        label_catalog: tuple[str, ...],
        *,
        query_seed: int,
    ) -> DiagnosisPrediction:
        children = self._decoded(state)
        return self._components["diagnosis"].diagnose(
            children["diagnosis"], label_catalog, query_seed=query_seed
        )

    def rollout(
        self,
        state: SharedPatientState,
        policy: ActionPlan,
        horizon: int,
        *,
        query_seed: int,
    ) -> RolloutPrediction:
        children = self._decoded(state)
        task = "natural" if policy.kind in NATURAL_PLAN_KINDS else "intervention"
        return self._components[task].rollout(
            children[task], policy, horizon, query_seed=query_seed
        )

    def model_summary(self) -> dict[str, Any]:
        summaries = {task: component.model_summary() for task, component in self._components.items()}
        return {
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "eligibility": "baseline_only_non_ucm",
            "patient_state_semantics": "three_independent_task_states",
            "model_seed": self._model_seed,
            "components": summaries,
            "parameter_count": sum(int(row["parameter_count"]) for row in summaries.values()),
        }


BASELINE_V2_FACTORIES: dict[str, Callable[..., Any]] = {
    "B02V2": ExactFullHistoryBaselineV2,
    "B03V2": SeparateTaskBaselineV2,
}


def make_baseline_v2(family_code: str, **parameters: Any) -> Any | None:
    factory = BASELINE_V2_FACTORIES.get(family_code)
    return None if factory is None else factory(**parameters)


__all__ = [
    "BASELINE_V2_FACTORIES",
    "ExactFullHistoryBaselineV2",
    "SeparateTaskBaselineV2",
    "exact_history_feature_vector",
    "make_baseline_v2",
]
