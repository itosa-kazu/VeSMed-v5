"""F22: action-conditioned switching-particle shared patient belief.

This module is deliberately separate from the sealed candidate-family source.
It implements a different research object: a posterior over discrete latent
trajectory prototypes.  Public visible prefixes identify the prototypes and
their action-conditioned switching operators; public trainer targets attach
diagnosis and counterfactual outcome statistics to the same prototypes.

Patient state is recursive and compact.  It contains one prototype posterior,
epistemic uncertainty, and a fixed-size sufficient-statistic accumulator.  It
never retains the visible event sequence, task-specific child states, simulator
state, future observations, case/test identifiers, or patient caches.
"""

from __future__ import annotations

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
from .candidate_families import (
    accumulator_from_history,
    path_feature_vector,
    update_accumulator,
)
from .canonical import ProtocolViolation, canonical_json_bytes
from .schema import ActionPlan, EventKind, PlanKind, VisibleDelta, VisibleHistory
from .worlds.base import PublicCatalog


STATE_PROTOCOL = "ucm-f22-switching-particle-state/1"
MODEL_PROTOCOL = "ucm-f22-switching-particle-model/1"
NATURAL_OPERATOR = "natural"


def _softmax(logits: np.ndarray) -> np.ndarray:
    if logits.ndim != 1 or not np.all(np.isfinite(logits)):
        raise ProtocolViolation("F22 posterior logits must be a finite vector")
    shifted = logits - float(np.max(logits))
    values = np.exp(np.clip(shifted, -700.0, 0.0))
    total = float(values.sum())
    if total <= 0.0 or not math.isfinite(total):
        return np.full(len(values), 1.0 / len(values), dtype=np.float64)
    return values / total


def _normalize(values: np.ndarray) -> np.ndarray:
    result = np.maximum(np.asarray(values, dtype=np.float64), 1e-15)
    total = float(result.sum())
    if result.ndim != 1 or total <= 0.0 or not math.isfinite(total):
        raise ProtocolViolation("F22 probability vector is invalid")
    return result / total


def _entropy(probabilities: np.ndarray) -> float:
    if len(probabilities) <= 1:
        return 0.0
    return float(
        -np.sum(probabilities * np.log(np.maximum(probabilities, 1e-15)))
        / math.log(len(probabilities))
    )


def _kmeans_plus_plus(
    values: np.ndarray, clusters: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Small deterministic k-means++ used only to learn trajectory prototypes."""

    if values.ndim != 2 or not len(values) or not np.all(np.isfinite(values)):
        raise ProtocolViolation("F22 prototype training matrix is invalid")
    count = min(max(1, int(clusters)), len(values))
    rng = np.random.default_rng(seed)
    chosen = [int(rng.integers(0, len(values)))]
    while len(chosen) < count:
        distance = np.min(
            np.sum((values[:, None, :] - values[np.asarray(chosen)][None, :, :]) ** 2, axis=2),
            axis=1,
        )
        distance[np.asarray(chosen)] = 0.0
        total = float(distance.sum())
        if total <= 1e-15:
            remaining = [index for index in range(len(values)) if index not in chosen]
            chosen.append(remaining[0])
        else:
            chosen.append(int(rng.choice(len(values), p=distance / total)))
    centers = values[np.asarray(chosen)].copy()
    assignment = np.full(len(values), -1, dtype=np.int64)
    for _ in range(50):
        distances = np.sum((values[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        next_assignment = np.argmin(distances, axis=1)
        if np.array_equal(next_assignment, assignment):
            break
        assignment = next_assignment
        for index in range(count):
            rows = values[assignment == index]
            if len(rows):
                centers[index] = rows.mean(axis=0)
    return centers, assignment


def _action_operator_key(action_id: str) -> str:
    if type(action_id) is not str or not action_id:
        raise ProtocolViolation("F22 action operator requires an action id")
    return f"action:{action_id}"


def _check_operator_key(check_id: str) -> str:
    if type(check_id) is not str or not check_id:
        raise ProtocolViolation("F22 check operator requires a check id")
    return f"check:{check_id}"


def _event_operator_key(event: Any) -> str:
    if event.kind is EventKind.PERFORMED_TREATMENT:
        action_id = event.payload.get("action_id")
        if type(action_id) is str and action_id:
            return _action_operator_key(action_id)
    if event.kind in {EventKind.TEST_ORDERED, EventKind.TEST_PERFORMED}:
        check_id = event.payload.get("check_id")
        if type(check_id) is str and check_id:
            return _check_operator_key(check_id)
    return NATURAL_OPERATOR


def _catalog_operator_key(identifier: str, catalog: PublicCatalog) -> str | None:
    """Resolve a generic public policy control without world/id special cases."""

    if identifier in {row.action_id for row in catalog.actions}:
        return _action_operator_key(identifier)
    if identifier in {row.check_id for row in catalog.checks}:
        return _check_operator_key(identifier)
    return None


def _row_stochastic(counts: np.ndarray, *, identity_prior: float = 0.5) -> np.ndarray:
    if counts.ndim != 2 or counts.shape[0] != counts.shape[1]:
        raise ProtocolViolation("F22 switching counts must be square")
    smoothed = np.asarray(counts, dtype=np.float64) + 0.05
    smoothed += np.eye(len(smoothed), dtype=np.float64) * identity_prior
    return smoothed / smoothed.sum(axis=1, keepdims=True)


@dataclass(slots=True)
class _SwitchingModel:
    catalog: PublicCatalog
    labels: tuple[str, ...]
    query_keys: tuple[str, ...]
    center: np.ndarray
    scale: np.ndarray
    prototypes: np.ndarray
    emission_variance: np.ndarray
    prior: np.ndarray
    transitions: dict[str, np.ndarray]
    operator_evidence_counts: dict[str, int]
    diagnosis_statistics: np.ndarray
    outcome_statistics: dict[str, np.ndarray]
    outcome_global: dict[str, np.ndarray]
    natural_query_keys: dict[int, str]
    support_reference: float
    training_count: int


class SwitchingParticleBeliefCandidate:
    """One recursively filtered posterior over action-switching prototypes."""

    family_id = "F22-switching-particle-belief"
    candidate_id = "F22-action-conditioned-trajectory-particle-state-v2"

    def __init__(
        self,
        *,
        prototypes: int = 10,
        emission_temperature: float = 1.0,
        target_shrinkage: float = 1.0,
        **_: Any,
    ) -> None:
        if type(prototypes) is not int or prototypes <= 1:
            raise ProtocolViolation("F22 prototypes must be an integer greater than one")
        if emission_temperature <= 0.0 or target_shrinkage <= 0.0:
            raise ProtocolViolation("F22 smoothing parameters must be positive")
        self.prototype_count = prototypes
        self.emission_temperature = float(emission_temperature)
        self.target_shrinkage = float(target_shrinkage)
        self._models: dict[str, _SwitchingModel] = {}
        self._model_seed = 0

    @staticmethod
    def _validate_catalogs(
        catalogs: tuple[PublicCatalog, ...], records: tuple[PublicTrainingRecord, ...]
    ) -> dict[str, tuple[PublicCatalog, list[PublicTrainingRecord]]]:
        grouped: dict[str, tuple[PublicCatalog, list[PublicTrainingRecord]]] = {}
        for catalog in catalogs:
            if type(catalog) is not PublicCatalog:
                raise ProtocolViolation("F22 fit requires PublicCatalog values")
            if catalog.digest in grouped:
                if grouped[catalog.digest][0].to_wire() != catalog.to_wire():
                    raise ProtocolViolation("F22 observed a catalog digest collision")
            else:
                grouped[catalog.digest] = (catalog, [])
        for record in records:
            if type(record) is not PublicTrainingRecord:
                raise ProtocolViolation("F22 fit requires PublicTrainingRecord values")
            partition = grouped.get(record.history.catalog_digest)
            if partition is None:
                raise ProtocolViolation("F22 record references an unknown catalog")
            partition[1].append(record)
        if any(not partition[1] for partition in grouped.values()):
            raise ProtocolViolation("F22 cannot fit an empty catalog partition")
        return grouped

    def fit(
        self,
        catalogs: tuple[PublicCatalog, ...],
        records: tuple[PublicTrainingRecord, ...],
        *,
        model_seed: int,
    ) -> None:
        if type(model_seed) is not int:
            raise ProtocolViolation("F22 model_seed must be an exact integer")
        models: dict[str, _SwitchingModel] = {}
        for catalog_digest, (catalog, partition) in self._validate_catalogs(
            catalogs, records
        ).items():
            models[catalog_digest] = self._fit_catalog(catalog, partition, model_seed)
        self._models = models
        self._model_seed = model_seed

    def _fit_catalog(
        self,
        catalog: PublicCatalog,
        records: list[PublicTrainingRecord],
        model_seed: int,
    ) -> _SwitchingModel:
        query_keys = tuple(row.query_key for row in records[0].rollouts)
        if not query_keys:
            raise ProtocolViolation("F22 requires public rollout targets")
        paths: list[np.ndarray] = []
        for record in records:
            if tuple(row.query_key for row in record.rollouts) != query_keys:
                raise ProtocolViolation("F22 query set drifted within a catalog")
            paths.append(path_feature_vector(accumulator_from_history(record.history)))
        matrix = np.vstack(paths)
        center = np.median(matrix, axis=0)
        scale = np.std(matrix, axis=0) + 0.1
        standardized = (matrix - center) / scale
        prototypes, assignment = _kmeans_plus_plus(
            standardized,
            self.prototype_count,
            model_seed ^ int(catalog.digest[7:15], 16),
        )
        count = len(prototypes)

        emission_variance = np.empty_like(prototypes)
        global_variance = np.var(standardized, axis=0) + 0.2
        for index in range(count):
            rows = standardized[assignment == index]
            local = np.var(rows, axis=0) if len(rows) > 1 else global_variance
            emission_variance[index] = np.maximum(local, 0.2)

        cluster_counts = np.bincount(assignment, minlength=count).astype(np.float64)
        prior = _normalize(cluster_counts + 0.5)
        diagnosis_global = np.mean(
            np.asarray(
                [
                    [float(record.diagnostic_target[label]) for label in catalog.diagnostic_labels]
                    for record in records
                ],
                dtype=np.float64,
            ),
            axis=0,
        )
        diagnosis_statistics = np.zeros((count, len(catalog.diagnostic_labels)))
        for index in range(count):
            rows = [
                [float(record.diagnostic_target[label]) for label in catalog.diagnostic_labels]
                for row_index, record in enumerate(records)
                if assignment[row_index] == index
            ]
            total = np.sum(rows, axis=0) if rows else np.zeros_like(diagnosis_global)
            diagnosis_statistics[index] = _normalize(
                total + self.target_shrinkage * diagnosis_global
            )

        outcome_statistics: dict[str, np.ndarray] = {}
        outcome_global: dict[str, np.ndarray] = {}
        natural_query_keys: dict[int, str] = {}
        for target_index, key in enumerate(query_keys):
            target_template = records[0].rollouts[target_index]
            if target_template.policy.kind is PlanKind.NO_NEW_ACTION:
                natural_query_keys[target_template.horizon] = key
            elif (
                target_template.policy.kind is PlanKind.CONTINUE_CURRENT
                and target_template.horizon not in natural_query_keys
            ):
                natural_query_keys[target_template.horizon] = key
            targets = np.asarray(
                [
                    [
                        *record.rollouts[target_index].signature,
                        float(record.rollouts[target_index].expected_utility),
                    ]
                    for record in records
                ],
                dtype=np.float64,
            )
            global_mean = targets.mean(axis=0)
            outcome_global[key] = global_mean
            values = np.empty((count, targets.shape[1]), dtype=np.float64)
            for index in range(count):
                rows = targets[assignment == index]
                values[index] = (
                    rows.sum(axis=0) + self.target_shrinkage * global_mean
                ) / (len(rows) + self.target_shrinkage)
            outcome_statistics[key] = values

        operator_names = {NATURAL_OPERATOR}
        operator_names.update(_action_operator_key(action.action_id) for action in catalog.actions)
        operator_names.update(_check_operator_key(check.check_id) for check in catalog.checks)
        transition_counts = {
            name: np.zeros((count, count), dtype=np.float64) for name in operator_names
        }
        for record in records:
            accumulator = accumulator_from_history(
                VisibleHistory((), 0, catalog.digest)
            )
            previous = self._nearest_prototype(
                path_feature_vector(accumulator), center, scale, prototypes
            )
            for event in record.history.events:
                delta = VisibleDelta(max(accumulator["as_of"], event.available_at), (event,))
                accumulator = update_accumulator(accumulator, delta)
                current = self._nearest_prototype(
                    path_feature_vector(accumulator), center, scale, prototypes
                )
                operator_key = _event_operator_key(event)
                if operator_key not in transition_counts:
                    raise ProtocolViolation(
                        "F22 visible event references a control absent from its catalog"
                    )
                transition_counts[operator_key][previous, current] += 1.0
                previous = current
        operator_evidence_counts = {
            name: int(counts.sum()) for name, counts in transition_counts.items()
        }
        natural_transition = _row_stochastic(transition_counts[NATURAL_OPERATOR])
        transitions: dict[str, np.ndarray] = {NATURAL_OPERATOR: natural_transition}
        for name, counts in transition_counts.items():
            if name == NATURAL_OPERATOR:
                continue
            if operator_evidence_counts[name] == 0:
                # This is an epistemic prior, not a learned treatment/check effect.
                # Keeping equal identity/natural mass makes the legal query total
                # while the rollout head separately abstains and returns its
                # natural-policy prediction rather than inventing an effect.
                transitions[name] = 0.5 * np.eye(count, dtype=np.float64) + 0.5 * natural_transition
            else:
                transitions[name] = _row_stochastic(counts)

        endpoint_distance = np.sqrt(
            np.min(
                np.mean(
                    ((standardized[:, None, :] - prototypes[None, :, :]) ** 2)
                    / emission_variance[None, :, :],
                    axis=2,
                ),
                axis=1,
            )
        )
        support_reference = max(float(np.quantile(endpoint_distance, 0.9)), 1e-6)
        return _SwitchingModel(
            catalog=catalog,
            labels=catalog.diagnostic_labels,
            query_keys=query_keys,
            center=center,
            scale=scale,
            prototypes=prototypes,
            emission_variance=emission_variance,
            prior=prior,
            transitions=transitions,
            operator_evidence_counts=operator_evidence_counts,
            diagnosis_statistics=diagnosis_statistics,
            outcome_statistics=outcome_statistics,
            outcome_global=outcome_global,
            natural_query_keys=natural_query_keys,
            support_reference=support_reference,
            training_count=len(records),
        )

    @staticmethod
    def _nearest_prototype(
        path: np.ndarray,
        center: np.ndarray,
        scale: np.ndarray,
        prototypes: np.ndarray,
    ) -> int:
        standardized = (path - center) / scale
        distance = np.mean((prototypes - standardized[None, :]) ** 2, axis=1)
        return int(np.argmin(distance))

    def _model(self, catalog_digest: str) -> _SwitchingModel:
        model = self._models.get(catalog_digest)
        if model is None:
            raise ProtocolViolation("F22 was not fitted for this public catalog")
        return model

    def _emission(
        self, accumulator: dict[str, Any], model: _SwitchingModel
    ) -> tuple[np.ndarray, float]:
        path = path_feature_vector(accumulator)
        standardized = (path - model.center) / model.scale
        distance = np.mean(
            ((standardized[None, :] - model.prototypes) ** 2)
            / model.emission_variance,
            axis=1,
        )
        likelihood = np.exp(
            np.clip(-0.5 * distance / self.emission_temperature, -700.0, 0.0)
        )
        novelty = math.sqrt(max(0.0, float(np.min(distance)))) / model.support_reference
        return np.maximum(likelihood, 1e-15), novelty

    def _distance_vector(
        self,
        posterior: np.ndarray,
        novelty: float,
        accumulator: dict[str, Any],
    ) -> tuple[float, ...]:
        lag_statistics = (
            _entropy(posterior),
            math.tanh(novelty / 4.0),
            math.tanh(float(accumulator["as_of"]) / 32.0),
            math.tanh(math.log1p(float(accumulator["total_events"])) / 4.0),
        )
        return tuple(float(value) for value in posterior) + lag_statistics

    def _state(
        self,
        accumulator: dict[str, Any],
        model: _SwitchingModel,
        posterior: np.ndarray,
        novelty: float,
    ) -> SharedPatientState:
        posterior = _normalize(posterior)
        payload = {
            "protocol": STATE_PROTOCOL,
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "catalog_digest": model.catalog.digest,
            "posterior": posterior.tolist(),
            "posterior_entropy": _entropy(posterior),
            "novelty_ratio": float(novelty),
            "accumulator": accumulator,
        }
        return SharedPatientState(
            f"{self.candidate_id}/state-v1",
            canonical_json_bytes(payload),
            self._distance_vector(posterior, novelty, accumulator),
            "candidate_shared_state",
        )

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> SharedPatientState:
        if type(history) is not VisibleHistory or type(inference_seed) is not int:
            raise ProtocolViolation("F22 initialize requires public history and exact seed")
        model = self._model(history.catalog_digest)
        accumulator = accumulator_from_history(history)
        emission, novelty = self._emission(accumulator, model)
        posterior = _normalize(model.prior * emission)
        return self._state(accumulator, model, posterior, novelty)

    def _decoded(
        self, state: SharedPatientState
    ) -> tuple[dict[str, Any], _SwitchingModel, np.ndarray, float]:
        if type(state) is not SharedPatientState:
            raise ProtocolViolation("F22 head requires SharedPatientState")
        try:
            wire = json.loads(state.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("F22 state cannot be decoded") from exc
        if (
            wire.get("protocol") != STATE_PROTOCOL
            or wire.get("candidate_id") != self.candidate_id
            or wire.get("family_id") != self.family_id
        ):
            raise ProtocolViolation("F22 state identity mismatch")
        model = self._model(wire.get("catalog_digest"))
        posterior = np.asarray(wire.get("posterior"), dtype=np.float64)
        if (
            posterior.ndim != 1
            or len(posterior) != len(model.prototypes)
            or not np.all(np.isfinite(posterior))
            or np.any(posterior < 0.0)
            or not math.isclose(float(posterior.sum()), 1.0, abs_tol=1e-12)
        ):
            raise ProtocolViolation("F22 posterior dimension drifted")
        novelty = float(wire.get("novelty_ratio"))
        if not math.isfinite(novelty) or novelty < 0.0:
            raise ProtocolViolation("F22 novelty ratio is invalid")
        expected = self._distance_vector(posterior, novelty, wire.get("accumulator"))
        if expected != state.distance_vector:
            raise ProtocolViolation("F22 state payload/distance vector mismatch")
        return wire, model, posterior, novelty

    def update(
        self,
        state: SharedPatientState,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> SharedPatientState:
        if type(delta) is not VisibleDelta or type(inference_seed) is not int:
            raise ProtocolViolation("F22 update requires public delta and exact seed")
        wire, model, posterior, _ = self._decoded(state)
        accumulator = wire["accumulator"]
        if not delta.events and delta.advance_to == accumulator["as_of"]:
            return state
        if delta.advance_to < accumulator["as_of"]:
            raise ProtocolViolation("F22 delta moved patient time backwards")
        predicted = posterior.copy()
        for event in delta.events:
            predicted = predicted @ model.transitions[_event_operator_key(event)]
        if not delta.events:
            predicted = predicted @ model.transitions[NATURAL_OPERATOR]
        next_accumulator = update_accumulator(accumulator, delta)
        emission, novelty = self._emission(next_accumulator, model)
        filtered = _normalize(predicted * emission)
        return self._state(next_accumulator, model, filtered, novelty)

    def diagnose(
        self,
        state: SharedPatientState,
        label_catalog: tuple[str, ...],
        *,
        query_seed: int,
    ) -> DiagnosisPrediction:
        if type(query_seed) is not int:
            raise ProtocolViolation("F22 query_seed must be an exact integer")
        _, model, posterior, novelty = self._decoded(state)
        if label_catalog != model.labels:
            raise ProtocolViolation("F22 diagnosis labels drifted")
        probabilities = _normalize(posterior @ model.diagnosis_statistics)
        if "unknown" in model.labels:
            unknown_index = model.labels.index("unknown")
            known_mask = np.arange(len(model.labels)) != unknown_index
            support_ood = 1.0 - math.exp(-max(0.0, novelty - 1.0))
            ambiguity_ood = 0.5 * _entropy(posterior)
            unknown = max(
                float(probabilities[unknown_index]), support_ood, ambiguity_ood
            )
            known = probabilities[known_mask]
            probabilities[:] = 0.0
            probabilities[unknown_index] = min(1.0, unknown)
            if float(known.sum()) > 0.0:
                probabilities[known_mask] = (
                    known / known.sum() * (1.0 - probabilities[unknown_index])
                )
        return DiagnosisPrediction(
            {label: float(probabilities[index]) for index, label in enumerate(model.labels)}
        )

    @staticmethod
    def _natural_power(model: _SwitchingModel, steps: int) -> np.ndarray:
        return np.linalg.matrix_power(model.transitions[NATURAL_OPERATOR], max(0, steps))

    def _counterfactual_posterior(
        self,
        posterior: np.ndarray,
        policy: ActionPlan,
        horizon: int,
        model: _SwitchingModel,
    ) -> tuple[np.ndarray, bool]:
        """Return switched belief and whether any operator has zero evidence."""

        if policy.kind is PlanKind.ACTION_SEQUENCE:
            current_offset = 0
            result = posterior.copy()
            used_epistemic_fallback = False
            for action in policy.actions:
                gap = max(0, min(8, action.offset - current_offset))
                result = result @ self._natural_power(model, gap)
                operator_key = _catalog_operator_key(action.action_id, model.catalog)
                if operator_key is None:
                    raise ProtocolViolation(
                        "F22 policy references a control absent from its public catalog"
                    )
                result = result @ model.transitions[operator_key]
                used_epistemic_fallback = (
                    used_epistemic_fallback
                    or model.operator_evidence_counts[operator_key] == 0
                )
                current_offset = action.offset
            result = result @ self._natural_power(
                model, max(0, min(8, horizon - current_offset))
            )
            return _normalize(result), used_epistemic_fallback
        # no-new-action, continue-current, and stop-controllable are all explicit
        # public policy operators with no new treatment insertion.
        return (
            _normalize(
                posterior @ self._natural_power(model, max(1, min(8, horizon)))
            ),
            False,
        )

    def rollout(
        self,
        state: SharedPatientState,
        policy: ActionPlan,
        horizon: int,
        *,
        query_seed: int,
    ) -> RolloutPrediction:
        if type(policy) is not ActionPlan or type(horizon) is not int or horizon <= 0:
            raise ProtocolViolation("F22 rollout requires a typed public query")
        if type(query_seed) is not int:
            raise ProtocolViolation("F22 query_seed must be an exact integer")
        _, model, posterior, novelty = self._decoded(state)
        if policy.kind is PlanKind.ACTION_SEQUENCE and any(
            _catalog_operator_key(action.action_id, model.catalog) is None
            for action in policy.actions
        ):
            raise ProtocolViolation(
                "F22 policy references a control absent from its public catalog"
            )
        key = policy_key(policy, horizon)
        statistics = model.outcome_statistics.get(key)
        if statistics is None:
            return RolloutPrediction((0.0,) * 32, 0.0, abstained=True)
        counterfactual, used_epistemic_fallback = self._counterfactual_posterior(
            posterior, policy, horizon, model
        )
        prediction_key = key
        if used_epistemic_fallback:
            # A zero-evidence operator is explicitly not a learned effect.  Use
            # the corresponding natural-policy head and declare abstention.
            prediction_key = model.natural_query_keys.get(horizon, key)
            statistics = model.outcome_statistics[prediction_key]
            counterfactual = _normalize(
                posterior @ self._natural_power(model, max(1, min(8, horizon)))
            )
        local = counterfactual @ statistics
        ood_weight = 1.0 - math.exp(-max(0.0, novelty - 1.0))
        prediction = (
            (1.0 - ood_weight) * local
            + ood_weight * model.outcome_global[prediction_key]
        )
        return RolloutPrediction(
            tuple(float(value) for value in prediction[:-1]),
            float(prediction[-1]),
            abstained=bool(used_epistemic_fallback or ood_weight > 0.995),
        )

    def model_artifact(self) -> bytes:
        """Serialize only catalog-level public training products, never patient state."""

        models: dict[str, Any] = {}
        for digest, model in sorted(self._models.items()):
            models[digest] = {
                "labels": list(model.labels),
                "query_keys": list(model.query_keys),
                "center": model.center.tolist(),
                "scale": model.scale.tolist(),
                "prototypes": model.prototypes.tolist(),
                "emission_variance": model.emission_variance.tolist(),
                "prior": model.prior.tolist(),
                "transitions": {
                    key: value.tolist() for key, value in sorted(model.transitions.items())
                },
                "operator_evidence_counts": dict(
                    sorted(model.operator_evidence_counts.items())
                ),
                "diagnosis_statistics": model.diagnosis_statistics.tolist(),
                "outcome_statistics": {
                    key: value.tolist()
                    for key, value in sorted(model.outcome_statistics.items())
                },
                "outcome_global": {
                    key: value.tolist() for key, value in sorted(model.outcome_global.items())
                },
                "natural_query_keys": {
                    str(key): value for key, value in sorted(model.natural_query_keys.items())
                },
                "support_reference": model.support_reference,
                "training_count": model.training_count,
            }
        return canonical_json_bytes(
            {
                "protocol": MODEL_PROTOCOL,
                "candidate_id": self.candidate_id,
                "parameters": {
                    "prototype_count": self.prototype_count,
                    "emission_temperature": self.emission_temperature,
                    "target_shrinkage": self.target_shrinkage,
                    "model_seed": self._model_seed,
                },
                "models": models,
            }
        )

    def load_model_artifact(
        self, catalogs: tuple[PublicCatalog, ...], artifact: bytes
    ) -> None:
        """Cold-load a model so persisted states need no process-local patient cache."""

        if type(artifact) is not bytes:
            raise ProtocolViolation("F22 model artifact must be exact bytes")
        try:
            wire = json.loads(artifact)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("F22 model artifact cannot be decoded") from exc
        if canonical_json_bytes(wire) != artifact or wire.get("protocol") != MODEL_PROTOCOL:
            raise ProtocolViolation("F22 model artifact is not canonical or has wrong protocol")
        if wire.get("candidate_id") != self.candidate_id:
            raise ProtocolViolation("F22 model artifact identity mismatch")
        public = {catalog.digest: catalog for catalog in catalogs}
        models: dict[str, _SwitchingModel] = {}
        for digest, row in wire["models"].items():
            catalog = public.get(digest)
            if catalog is None or tuple(row["labels"]) != catalog.diagnostic_labels:
                raise ProtocolViolation("F22 model artifact/catalog mismatch")
            models[digest] = _SwitchingModel(
                catalog=catalog,
                labels=tuple(row["labels"]),
                query_keys=tuple(row["query_keys"]),
                center=np.asarray(row["center"], dtype=np.float64),
                scale=np.asarray(row["scale"], dtype=np.float64),
                prototypes=np.asarray(row["prototypes"], dtype=np.float64),
                emission_variance=np.asarray(row["emission_variance"], dtype=np.float64),
                prior=np.asarray(row["prior"], dtype=np.float64),
                transitions={
                    key: np.asarray(value, dtype=np.float64)
                    for key, value in row["transitions"].items()
                },
                operator_evidence_counts={
                    key: int(value)
                    for key, value in row["operator_evidence_counts"].items()
                },
                diagnosis_statistics=np.asarray(
                    row["diagnosis_statistics"], dtype=np.float64
                ),
                outcome_statistics={
                    key: np.asarray(value, dtype=np.float64)
                    for key, value in row["outcome_statistics"].items()
                },
                outcome_global={
                    key: np.asarray(value, dtype=np.float64)
                    for key, value in row["outcome_global"].items()
                },
                natural_query_keys={
                    int(key): value for key, value in row["natural_query_keys"].items()
                },
                support_reference=float(row["support_reference"]),
                training_count=int(row["training_count"]),
            )
        parameters = wire["parameters"]
        self.prototype_count = int(parameters["prototype_count"])
        self.emission_temperature = float(parameters["emission_temperature"])
        self.target_shrinkage = float(parameters["target_shrinkage"])
        self._model_seed = int(parameters["model_seed"])
        self._models = models

    def model_summary(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "architecture": "action_conditioned_switching_particle_filter",
            "model_seed": self._model_seed,
            "catalog_count": len(self._models),
            "prototype_count_by_catalog": {
                digest: len(model.prototypes) for digest, model in sorted(self._models.items())
            },
            "transition_operator_count": sum(
                len(model.transitions) for model in self._models.values()
            ),
            "zero_evidence_operator_count": sum(
                sum(
                    count == 0
                    for key, count in model.operator_evidence_counts.items()
                    if key != NATURAL_OPERATOR
                )
                for model in self._models.values()
            ),
            "training_count": sum(model.training_count for model in self._models.values()),
            "parameter_count": sum(
                model.prototypes.size
                + model.emission_variance.size
                + model.diagnosis_statistics.size
                + sum(value.size for value in model.transitions.values())
                + sum(value.size for value in model.outcome_statistics.values())
                for model in self._models.values()
            ),
        }


F22_FACTORIES: dict[str, Callable[..., SwitchingParticleBeliefCandidate]] = {
    "F22": SwitchingParticleBeliefCandidate,
}


def make_f22_candidate(
    family_code: str = "F22", **parameters: Any
) -> SwitchingParticleBeliefCandidate:
    factory = F22_FACTORIES.get(family_code)
    if factory is None:
        raise ProtocolViolation(f"unknown F22 candidate family {family_code!r}")
    return factory(**parameters)


__all__ = [
    "F22_FACTORIES",
    "SwitchingParticleBeliefCandidate",
    "make_f22_candidate",
]
