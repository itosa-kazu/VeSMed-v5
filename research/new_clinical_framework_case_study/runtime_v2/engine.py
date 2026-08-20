"""Executable finite Runtime v2 kernel.

This module is intentionally dependency-free and numerically conservative.  It
implements structural contracts; its parameters are not clinically calibrated.
"""

from __future__ import annotations

import copy
import heapq
import itertools
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .schema import (
    RUNTIME_VERSION,
    PublicEvent,
    SharedPatientState,
    digest,
    validate_architecture_state_payload,
    validate_model_spec,
    validate_state_payload,
)
from .architecture_wire import (
    architecture_state_to_internal,
    internal_to_architecture_state,
    model_time_from_as_of,
    validate_runtime_state_semantics,
)
from .ledger import attach_event_ledger_proof, ledger_entries_digest


_EPS = 1e-12


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _normalize(weights: Mapping[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in weights.values())
    if total <= 0.0:
        raise ValueError("cannot normalize zero probability mass")
    return {str(k): max(0.0, float(v)) / total for k, v in sorted(weights.items())}


def _logsumexp(values: Sequence[float]) -> float:
    if not values:
        return -math.inf
    maximum = max(values)
    if not math.isfinite(maximum):
        return maximum
    return maximum + math.log(sum(math.exp(value - maximum) for value in values))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "positive", "present", "yes", "1"}:
        return True
    if text in {"false", "negative", "absent", "no", "0"}:
        return False
    raise ValueError(f"cannot interpret {value!r} as boolean")


def log_likelihood(distribution: Mapping[str, Any], value: Any) -> float:
    """Return a typed finite log likelihood."""

    family = distribution["family"]
    if family == "bernoulli":
        p_true = float(distribution["p_true"])
        probability = p_true if _as_bool(value) else 1.0 - p_true
        return math.log(max(_EPS, probability))
    if family == "categorical":
        probabilities = distribution["probabilities"]
        floor = float(distribution.get("floor", 1e-6))
        return math.log(max(floor, float(probabilities.get(str(value), floor))))
    if family == "gaussian":
        number = float(value)
        mean = float(distribution["mean"])
        sd = float(distribution["sd"])
        z = (number - mean) / sd
        return -0.5 * math.log(2.0 * math.pi * sd * sd) - 0.5 * z * z
    raise ValueError(f"unsupported likelihood family: {family}")


class RuntimeV2:
    """Exact small-scope factorial inference and controlled rollout engine."""

    def __init__(
        self,
        model_spec: Mapping[str, Any],
        *,
        topology_enabled: bool = True,
        mode_guards_enabled: bool = True,
    ) -> None:
        self.topology_enabled = bool(topology_enabled)
        self.mode_guards_enabled = bool(mode_guards_enabled)
        self.spec = validate_model_spec(model_spec)
        # Execution switches are part of the model/runtime preimage.  Two
        # runtimes that would answer the same canonical state differently must
        # never share a model_digest or accept each other's state.
        self.spec["runtime_options"] = {
            "topology_enabled": self.topology_enabled,
            "mode_guards_enabled": self.mode_guards_enabled,
        }
        declared_horizon = float(self.spec["scope"]["horizon"]["value"])
        if not math.isfinite(declared_horizon) or not declared_horizon.is_integer():
            raise ValueError(
                "scope.horizon must be a finite whole number of discrete model steps"
            )
        self.model_digest = digest(self.spec)
        self.processes = {row["process_id"]: row for row in self.spec["processes"]}
        self.process_ids = tuple(sorted(self.processes))
        self.observations = {row["concept_id"]: row for row in self.spec["observations"]}
        self.common_cause_factors = {
            row["factor_id"]: row for row in self.spec.get("common_cause_factors", [])
        }
        self.common_cause_by_concept = {
            concept_id: row
            for row in self.common_cause_factors.values()
            for concept_id in row["member_concept_ids"]
        }
        self.actions = {row["action_id"]: row for row in self.spec["actions"]}
        self._distances = self._all_pairs_distances()
        self._stratum_owners = {
            stratum["stratum_id"]: pid
            for pid, process in self.processes.items()
            for stratum in (
                process.get("strata")
                or [{"stratum_id": f"stratum:{pid}"}]
            )
        }
        self._stratum_distances = self._all_pairs_stratum_distances()
        # The validated construction preimage is immutable by contract.  Keep
        # private seals and verify them at every public boundary rather than
        # allowing an exposed dict/list to be mutated underneath an already
        # issued model digest.
        self._sealed_model_digest = self.model_digest
        self._sealed_registry_digest = self._runtime_registry_digest()

    @classmethod
    def from_json(
        cls,
        path: str | Path,
        *,
        topology_enabled: bool = True,
        mode_guards_enabled: bool = True,
    ) -> "RuntimeV2":
        """Load and validate a model JSON file."""

        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("model JSON must contain an object")
        return cls(
            value,
            topology_enabled=topology_enabled,
            mode_guards_enabled=mode_guards_enabled,
        )

    def _all_pairs_distances(self) -> dict[tuple[str, str], float]:
        graph: dict[str, dict[str, float]] = {pid: {} for pid in self.process_ids}
        for edge in self.spec["topology"]["edges"]:
            source, target = edge["source"], edge["target"]
            distance = float(edge["distance"])
            graph[source][target] = min(distance, graph[source].get(target, math.inf))
            if not edge.get("directed", False):
                graph[target][source] = min(distance, graph[target].get(source, math.inf))
        result: dict[tuple[str, str], float] = {}
        for source in self.process_ids:
            best = {source: 0.0}
            queue = [(0.0, source)]
            while queue:
                current, node = heapq.heappop(queue)
                if current != best[node]:
                    continue
                for neighbor, edge_distance in graph[node].items():
                    candidate = current + edge_distance
                    if candidate < best.get(neighbor, math.inf):
                        best[neighbor] = candidate
                        heapq.heappush(queue, (candidate, neighbor))
            for target, distance in best.items():
                result[(source, target)] = distance
        return result

    def _all_pairs_stratum_distances(self) -> dict[tuple[str, str], float]:
        """Shortest-path geometry over local behavioral strata.

        Process topology supplies cross-process bridges.  Refinement-specific
        ``stratum_edges`` supplies the previously missing within-process
        geometry, so opposite-response child strata are not collapsed to
        distance zero merely because they share a parent process.
        """

        graph: dict[str, dict[str, float]] = {
            sid: {} for sid in self._stratum_owners
        }

        def connect(source: str, target: str, distance: float, directed: bool) -> None:
            graph[source][target] = min(distance, graph[source].get(target, math.inf))
            if not directed:
                graph[target][source] = min(distance, graph[target].get(source, math.inf))

        strata_by_process = {
            pid: sorted(
                sid for sid, owner in self._stratum_owners.items() if owner == pid
            )
            for pid in self.process_ids
        }
        for edge in self.spec["topology"]["edges"]:
            for source_sid in strata_by_process[edge["source"]]:
                for target_sid in strata_by_process[edge["target"]]:
                    connect(
                        source_sid,
                        target_sid,
                        float(edge["distance"]),
                        bool(edge.get("directed", False)),
                    )
        for edge in self.spec["topology"].get("stratum_edges", []):
            connect(
                edge["source_stratum_id"],
                edge["target_stratum_id"],
                float(edge["distance"]),
                bool(edge.get("directed", False)),
            )

        result: dict[tuple[str, str], float] = {}
        for source in sorted(graph):
            best = {source: 0.0}
            queue = [(0.0, source)]
            while queue:
                current, node = heapq.heappop(queue)
                if current != best[node]:
                    continue
                for neighbor, edge_distance in graph[node].items():
                    candidate = current + edge_distance
                    if candidate < best.get(neighbor, math.inf):
                        best[neighbor] = candidate
                        heapq.heappush(queue, (candidate, neighbor))
            for target, distance in best.items():
                result[(source, target)] = distance
        return result

    def _runtime_registry_digest(self) -> str:
        return digest(
            {
                "process_ids": list(self.process_ids),
                "processes": self.processes,
                "observations": self.observations,
                "common_cause_factors": self.common_cause_factors,
                "common_cause_by_concept": self.common_cause_by_concept,
                "actions": self.actions,
                "distances": [
                    {"source": source, "target": target, "distance": distance}
                    for (source, target), distance in sorted(self._distances.items())
                ],
                "stratum_distances": [
                    {"source": source, "target": target, "distance": distance}
                    for (source, target), distance in sorted(
                        self._stratum_distances.items()
                    )
                ],
                "topology_enabled": self.topology_enabled,
                "mode_guards_enabled": self.mode_guards_enabled,
            }
        )

    def _assert_runtime_spec_integrity(self) -> None:
        if self.model_digest != self._sealed_model_digest or digest(self.spec) != self._sealed_model_digest:
            raise ValueError("runtime model spec mutated after construction")
        if self._runtime_registry_digest() != self._sealed_registry_digest:
            raise ValueError("runtime registries mutated after construction")

    def _validate_horizon(self, horizon: int | float) -> tuple[int | None, float, bool]:
        if isinstance(horizon, bool):
            raise ValueError("horizon must be a positive finite number")
        try:
            value = float(horizon)
        except (TypeError, ValueError) as exc:
            raise ValueError("horizon must be a positive finite number") from exc
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("horizon must be a positive finite number")
        declared = float(self.spec["scope"]["horizon"]["value"])
        if value > declared + _EPS:
            return None, value, True
        if not value.is_integer():
            raise ValueError(
                "horizon must be a whole number of discrete model steps; "
                "fractional integration is not declared"
            )
        return int(value), value, False

    def _out_of_scope_identifiability(
        self,
        state: SharedPatientState,
        requested_horizon: float,
    ) -> dict[str, Any]:
        declared = float(self.spec["scope"]["horizon"]["value"])
        unit = str(self.spec["scope"]["horizon"]["unit"])
        return {
            "status": "OUT_OF_SCOPE",
            "assumption_ids": sorted(
                set(self.spec["posterior_factorization"]["assumption_ids"])
            ),
            "compatible_world_ids": [],
            "reasons": [
                f"requested horizon {requested_horizon} {unit} exceeds frozen scope horizon "
                f"{declared} {unit}"
            ],
            "scope": copy.deepcopy(state.payload["scope"]),
            "uncertainty": copy.deepcopy(state.payload["epistemic_residual"]),
        }

    def _out_of_scope_rollout(
        self,
        state: SharedPatientState,
        policy: Mapping[str, Any] | str,
        requested_horizon: float,
    ) -> dict[str, Any]:
        policy_id = policy if isinstance(policy, str) else str(
            policy.get("policy_id", "UNNAMED_POLICY")
        )
        identifiability = self._out_of_scope_identifiability(state, requested_horizon)
        return {
            "consumed_state_hash": state.state_hash,
            "policy_id": policy_id,
            "status": "OUT_OF_SCOPE",
            "execution_status": "NOT_EXECUTED_OUT_OF_SCOPE",
            "requested_horizon": {
                "value": requested_horizon,
                "unit": str(self.spec["scope"]["horizon"]["unit"]),
            },
            "identifiability": identifiability,
            "posterior_factorization": copy.deepcopy(
                self.spec["posterior_factorization"]
            ),
            "factorization_limitation": (
                "Requested query is outside the frozen horizon; within-scope local state "
                "would additionally use the declared conditional-active mean-field "
                "factorization."
            ),
        }

    def branch_distance(self, process_a: str, process_b: str) -> float:
        self._assert_runtime_spec_integrity()
        if process_a not in self.processes or process_b not in self.processes:
            raise KeyError("unknown process id")
        return self._branch_distance_unchecked(process_a, process_b)

    def _branch_distance_unchecked(self, process_a: str, process_b: str) -> float:
        """Read the construction-sealed process-distance cache.

        This is an internal hot-path primitive.  Callers must already have
        crossed a public runtime boundary that invokes
        ``_assert_runtime_spec_integrity``.  The public ``branch_distance``
        method deliberately retains the integrity assertion and identifier
        checks for standalone callers.
        """

        return self._distances.get((process_a, process_b), math.inf)

    def stratum_distance(self, stratum_a: str, stratum_b: str) -> float:
        """Return the model-bound behavioral distance between local strata."""

        self._assert_runtime_spec_integrity()
        if stratum_a not in self._stratum_owners or stratum_b not in self._stratum_owners:
            raise KeyError("unknown stratum id")
        return self._stratum_distance_unchecked(stratum_a, stratum_b)

    def _stratum_distance_unchecked(self, stratum_a: str, stratum_b: str) -> float:
        """Read the construction-sealed stratum-distance cache internally.

        The cache is part of ``_sealed_registry_digest``.  Re-hashing the
        entire model for every pair in a geometry closure does not add an
        integrity guarantee after the enclosing public boundary has already
        verified that seal; it only turns an O(S^2) lookup into repeated
        whole-model serialization.
        """

        return self._stratum_distances.get((stratum_a, stratum_b), math.inf)

    def _stratum_action_modifier(
        self, process_id: str, stratum_id: str, action_id: str
    ) -> tuple[float, str | None, float | None]:
        """Resolve an action modifier using declared stratum geometry.

        Explicit local modifiers are authoritative.  If a stratum lacks one,
        the nearest geometrically connected stratum with a declared modifier
        supplies an attenuated planning analogue.  With no such witness the
        neutral multiplier remains 1.0.
        """

        rows = {
            row["stratum_id"]: row
            for row in (
                self.processes[process_id].get("strata")
                or [{"stratum_id": f"stratum:{process_id}", "action_effect_modifiers": {}}]
            )
        }
        local = rows[stratum_id].get("action_effect_modifiers", {})
        if action_id in local:
            return float(local[action_id]), stratum_id, 0.0
        candidates = []
        for candidate_id, candidate in rows.items():
            modifiers = candidate.get("action_effect_modifiers", {})
            if action_id not in modifiers:
                continue
            distance = self._stratum_distance_unchecked(stratum_id, candidate_id)
            if math.isfinite(distance):
                candidates.append((distance, candidate_id, float(modifiers[action_id])))
        if not candidates:
            return 1.0, None, None
        distance, witness_id, witness_modifier = min(candidates)
        scale = max(_EPS, float(self.spec["topology"]["distance_scale"]))
        attenuated = 1.0 + (witness_modifier - 1.0) * math.exp(-distance / scale)
        return attenuated, witness_id, distance

    def _enumerate_prior(self) -> list[dict[str, Any]]:
        unknown_prior = float(self.spec["epistemic"]["unknown_prior"])
        if not 0.0 < unknown_prior < 1.0:
            raise ValueError("unknown_prior must be in (0,1)")
        log_rows: list[tuple[list[str], bool, float]] = []
        for bits in itertools.product((False, True), repeat=len(self.process_ids)):
            active = [pid for pid, enabled in zip(self.process_ids, bits) if enabled]
            for unknown in (False, True):
                logp = math.log(unknown_prior if unknown else 1.0 - unknown_prior)
                for pid, enabled in zip(self.process_ids, bits):
                    prior = float(self.processes[pid]["activation_prior"])
                    logp += math.log(prior if enabled else 1.0 - prior)
                active_set = set(active)
                for interaction in self.spec["coactivation_interactions"]:
                    if {interaction["process_a"], interaction["process_b"]}.issubset(active_set):
                        logp += float(interaction.get("log_potential_when_coactive", 0.0))
                log_rows.append((active, unknown, logp))
        normalizer = _logsumexp([row[2] for row in log_rows])
        return [
            {
                "configuration_id": self._configuration_id(active, unknown),
                "active_processes": active,
                "unknown_active": unknown,
                "probability": math.exp(logp - normalizer),
            }
            for active, unknown, logp in log_rows
        ]

    @staticmethod
    def _configuration_id(active: Sequence[str], unknown: bool) -> str:
        return f"known={','.join(sorted(active)) or '-'}|unknown={int(bool(unknown))}"

    def _empty_payload(self, cut: float) -> dict[str, Any]:
        per_process: dict[str, Any] = {}
        for pid in self.process_ids:
            process = self.processes[pid]
            mode_prior = _normalize(
                {row["mode_id"]: float(row.get("prior", 0.0)) for row in process["modes"]}
            )
            coordinates = {
                row["coordinate_id"]: {
                    "mean": float(row["prior_mean"]),
                    "uncertainty": float(row.get("prior_uncertainty", 1.0)),
                }
                for row in process["coordinates"]
            }
            stratum_rows = process.get("strata") or [
                {"stratum_id": f"stratum:{pid}", "prior": 1.0}
            ]
            per_process[pid] = {
                "coordinates": coordinates,
                "mode_posterior": mode_prior,
                "stratum_posterior": _normalize(
                    {row["stratum_id"]: float(row.get("prior", 0.0)) for row in stratum_rows}
                ),
            }
        payload = {
            "internal_schema_version": "new-clinical-runtime.internal.v2.1",
            "runtime_version": RUNTIME_VERSION,
            "model_id": self.spec["model_id"],
            "model_digest": self.model_digest,
            "state_time": float(min(0.0, cut)),
            "joint_hypotheses": self._enumerate_prior(),
            "process_activation_marginals": {},
            "per_process": per_process,
            "action_instances": {},
            "planned_action_records": [],
            # Canonical source-result identities are distinct from transport
            # event ids.  Keep the semantic fingerprint so an equivalent
            # re-rendering of an action/order is exact-once just like an
            # observation.  The wire materializes the source ids on the
            # affected action instance; the private map preserves the stronger
            # warm-process collision check.
            "action_source_ledger": {},
            "action_source_identity_complete": True,
            "history_summary": {},
            "event_ledger": {},
            "event_ledger_digest": digest([]),
            "evidence_ledger": {},
            "evidence_trace": [],
            "epistemic": {
                "mapped_observation_count": 0,
                "unmapped_observation_count": 0,
                "deduplicated_evidence_count": 0,
                "measurement_count": 0,
                "measurement_reliability_sum": 0.0,
                "misfit_sum": 0.0,
                "mapping_residual": 0.5,
                "model_misfit_residual": 0.0,
                "unknown_process_probability": float(self.spec["epistemic"]["unknown_prior"]),
            },
            "lineage": {
                "parent_state_hash": None,
                "consumed_event_ids": [],
                "skipped_duplicate_event_ids": [],
                "migration_history": [],
            },
            "warnings": [],
            "architecture_factor_messages": [],
            "architecture_unexplained_observations": [],
            "missing_distinguishing_information": [],
            "mode_transitions": [],
            "action_response_windows": [],
        }
        self._derive_marginals(payload)
        self._derive_epistemic(payload)
        return payload

    def initialize(
        self,
        events: Iterable[PublicEvent | Mapping[str, Any]],
        *,
        cut: int | float,
    ) -> SharedPatientState:
        self._assert_runtime_spec_integrity()
        if isinstance(cut, bool):
            raise ValueError("cut must be a finite number")
        cut_value = float(cut)
        if not math.isfinite(cut_value):
            raise ValueError("cut must be a finite number")
        rows = self._coerce_events(events)
        available = [row for row in rows if float(row.payload["available_at"]) <= cut_value]
        payload = self._empty_payload(cut_value)
        payload = self._consume(payload, available, advance_to=cut_value, parent_hash=None)
        validate_state_payload(payload, self.spec)
        return internal_to_architecture_state(self, payload)

    def update(
        self,
        state: SharedPatientState,
        events: Iterable[PublicEvent | Mapping[str, Any]],
        *,
        advance_to: int | float,
        event_ledger_proof: Mapping[str, Any] | None = None,
    ) -> SharedPatientState:
        if event_ledger_proof is not None:
            state = attach_event_ledger_proof(state, event_ledger_proof)
        self._assert_state(state)
        if isinstance(advance_to, bool):
            raise ValueError("advance_to must be a finite number")
        target = float(advance_to)
        if not math.isfinite(target):
            raise ValueError("advance_to must be a finite number")
        current = model_time_from_as_of(state.payload["as_of"])
        if target < current:
            raise ValueError("state time cannot move backwards")
        rows = self._coerce_events(events)
        available = [row for row in rows if float(row.payload["available_at"]) <= target]
        # No public event and no clock movement means no transition at all.
        # This also lets a cold caller submit only still-unavailable future
        # events without requiring a ledger proof or changing canonical bytes.
        if target == current and not available:
            return state
        if (
            state._internal_payload is None
            and state.payload["event_lineage"]["processed_event_ids"]
            and state._event_ledger_proof is None
        ):
            raise ValueError(
                "cold state transition requires a content-addressed event ledger proof"
            )
        internal = architecture_state_to_internal(self, state)
        # Exact replay at the same cut is a true idempotent no-op: preserve the
        # authoritative canonical bytes, including lineage and state hash.
        if target == float(internal["state_time"]) and available:
            all_exact_duplicates = True
            for event in available:
                if event.event_id not in internal["event_ledger"]:
                    if self._is_equivalent_source_duplicate(internal, event):
                        continue
                    all_exact_duplicates = False
                    break
                known = internal["event_ledger"][event.event_id]
                if known is None:
                    raise ValueError(
                        "cold duplicate validation requires a content-addressed event ledger proof"
                    )
                if known != event.event_digest:
                    raise ValueError(f"event_id collision with changed bytes: {event.event_id}")
            if all_exact_duplicates:
                return state
        payload = self._consume(internal, available, advance_to=target, parent_hash=state.state_hash)
        validate_state_payload(payload, self.spec)
        return internal_to_architecture_state(self, payload)

    @staticmethod
    def _coerce_events(values: Iterable[PublicEvent | Mapping[str, Any]]) -> list[PublicEvent]:
        rows = [row if isinstance(row, PublicEvent) else PublicEvent.from_dict(row) for row in values]
        # Availability remains the outer causal boundary: an event cannot be
        # consumed before it is public.  Inside one availability cut, however,
        # lifecycle events must follow their occurred-time partial order, not
        # arbitrary transport ids.  The type rank breaks exact-time ties in a
        # medically/legal lifecycle order while the event id is only the final
        # deterministic tiebreaker.
        lifecycle_rank = {
            "PlannedAction": 0,
            "PlannedTreatment": 0,
            "ActionStarted": 1,
            "ActionContinued": 2,
            "ActionDoseChanged": 3,
            "ActionHeld": 4,
            "ActionStopped": 5,
            "ActionCompleted": 6,
            "ObservationAvailable": 7,
            "RecordOnly": 8,
        }
        return sorted(
            rows,
            key=lambda row: (
                float(row.payload["available_at"]),
                float(row.payload["occurred_time"]["lower"]),
                float(row.payload["occurred_time"]["upper"]),
                lifecycle_rank.get(str(row.payload["event_type"]), 99),
                row.event_id,
            ),
        )

    def _assert_state(self, state: SharedPatientState) -> None:
        self._assert_runtime_spec_integrity()
        validate_architecture_state_payload(state.payload)
        if state.payload.get("model_lineage", {}).get("model_digest") != self.model_digest:
            raise ValueError("state belongs to another model digest; explicit migration required")
        validate_runtime_state_semantics(self, state)

    def _common_cause_batch_groups(
        self,
        payload: Mapping[str, Any],
        events: Sequence[PublicEvent],
    ) -> tuple[dict[str, tuple[Mapping[str, Any], list[PublicEvent], str]], dict[str, str]]:
        """Preflight complete, atomic common-cause factors in one update batch.

        Cross-state/asynchronous member accumulation is intentionally not
        implemented: without a canonical pending-factor wire it would make a
        warm process and cold reconstruction disagree.  Any incomplete new
        group therefore fails closed before patient state is mutated.
        """

        grouped: dict[tuple[str, str], list[PublicEvent]] = {}
        for event in events:
            row = event.payload
            if row.get("event_type") != "ObservationAvailable":
                continue
            factor = self.common_cause_by_concept.get(str(row.get("concept_id") or ""))
            if factor is None:
                continue
            if event.event_id in payload.get("event_ledger", {}):
                known_digest = payload["event_ledger"][event.event_id]
                if known_digest is not None and known_digest != event.event_digest:
                    raise ValueError(f"event_id collision with changed bytes: {event.event_id}")
                continue
            if self._is_equivalent_source_duplicate(payload, event):
                continue
            source_id = str(row["provenance"]["source_result_id"])
            if factor["binding_mode"] == "SAME_SOURCE_RESULT":
                instance_id = source_id
            else:
                instance_id = str(
                    row.get("provenance", {}).get("common_cause_instance_id") or ""
                )
                if not instance_id:
                    raise ValueError(
                        f"{factor['factor_id']}: SHARED_LATENT_INSTANCE member requires "
                        "provenance.common_cause_instance_id"
                    )
            grouped.setdefault((str(factor["factor_id"]), instance_id), []).append(event)

        leaders: dict[str, tuple[Mapping[str, Any], list[PublicEvent], str]] = {}
        member_to_leader: dict[str, str] = {}
        for (factor_id, instance_id), members in sorted(grouped.items()):
            factor = self.common_cause_factors[factor_id]
            expected = set(factor["member_concept_ids"])
            actual = [str(event.payload["concept_id"]) for event in members]
            if len(actual) != len(set(actual)):
                raise ValueError(f"{factor_id}: duplicate member in common-cause batch")
            if set(actual) != expected:
                missing = sorted(expected.difference(actual))
                extra = sorted(set(actual).difference(expected))
                raise ValueError(
                    f"{factor_id}: incomplete common-cause batch; "
                    f"missing={missing}, extra={extra}"
                )
            temporal_signatures = {
                digest(
                    {
                        "sample_time": event.payload.get("sample_time"),
                        "result_at": event.payload.get("result_at"),
                        "recorded_at": event.payload.get("recorded_at"),
                        "available_at": event.payload.get("available_at"),
                    }
                )
                for event in members
            }
            if len(temporal_signatures) != 1:
                raise ValueError(
                    f"{factor_id}: common-cause members require identical temporal semantics"
                )
            sources = {
                str(event.payload["provenance"]["source_result_id"])
                for event in members
            }
            if factor["binding_mode"] == "SAME_SOURCE_RESULT" and len(sources) != 1:
                raise ValueError(
                    f"{factor_id}: SAME_SOURCE_RESULT members require one source_result_id"
                )
            if factor["binding_mode"] == "SHARED_LATENT_INSTANCE" and len(sources) < 2:
                raise ValueError(
                    f"{factor_id}: SHARED_LATENT_INSTANCE must bind distinct source results"
                )
            ordered = sorted(members, key=lambda event: str(event.payload["concept_id"]))
            # `events` has already been canonicalized by _coerce_events;
            # preserve its first member as the atomic consumption point while
            # canonicalizing member values independently by concept id.
            leader = members[0].event_id
            leaders[leader] = (factor, ordered, instance_id)
            for event in ordered:
                member_to_leader[event.event_id] = leader
        return leaders, member_to_leader

    def _consume(
        self,
        payload: dict[str, Any],
        events: Sequence[PublicEvent],
        *,
        advance_to: float,
        parent_hash: str | None,
    ) -> dict[str, Any]:
        consumed: list[str] = []
        skipped: list[str] = []
        common_groups, common_members = self._common_cause_batch_groups(payload, events)
        consumed_common_members: set[str] = set()
        for event in events:
            if event.event_id in consumed_common_members:
                continue
            if event.event_id in payload["event_ledger"]:
                existing = payload["event_ledger"][event.event_id]
                if existing is None:
                    raise ValueError(
                        "cold duplicate validation requires a content-addressed event ledger proof"
                    )
                if existing != event.event_digest:
                    raise ValueError(f"event_id collision with changed bytes: {event.event_id}")
                skipped.append(event.event_id)
                continue
            if self._is_equivalent_source_duplicate(payload, event):
                # Equivalent renderings of an already-consumed public source
                # are transport duplicates, not new patient-state events.
                # They therefore do not perturb the canonical ledger/bytes.
                continue
            if float(event.payload["available_at"]) < float(payload["state_time"]) - _EPS:
                # The recursive state has already been propagated past the
                # event's information time.  Absorbing it at `state_time`
                # produces a different patient trajectory from replaying the
                # same event before propagation (initialize-at-cut), even when
                # both public calls claim the same final cut.  Until an exact
                # replay/smoothing kernel exists, fail closed instead of
                # silently changing the event's temporal semantics.
                raise ValueError(
                    "stale recursive event requires complete replay or smoothing; "
                    "available_at precedes current state_time"
                )
            if (
                event.payload["event_type"]
                in {
                    "ActionStarted",
                    "ActionContinued",
                    "ActionDoseChanged",
                    "ActionHeld",
                    "ActionStopped",
                    "ActionCompleted",
                }
                and float(event.payload["occurred_time"]["upper"])
                < float(event.payload["available_at"]) - _EPS
            ):
                # A delayed administration record changes the factual path
                # before its information cut.  Backfilling only cumulative
                # dose would leave coordinates, modes, and process activation
                # on the untreated path.  Until the runtime has a complete
                # event replay/smoothing kernel, reject that false precision.
                raise ValueError(
                    "retrospective action lifecycle event requires complete replay or smoothing; "
                    "occurred_time precedes available_at"
                )
            common_leader = common_members.get(event.event_id)
            if common_leader is not None:
                if common_leader != event.event_id:
                    # Canonical sorting always places the declared leader first;
                    # reaching another member would imply an internal ordering
                    # defect rather than a partially consumable factor.
                    raise ValueError("common-cause batch leader ordering is inconsistent")
                factor, member_events, instance_id = common_groups[common_leader]
                event_time = max(
                    float(payload["state_time"]),
                    float(event.payload["available_at"]),
                )
                self._advance_patient_state(payload, event_time)
                for member_event in member_events:
                    payload["event_ledger"][member_event.event_id] = member_event.event_digest
                    consumed.append(member_event.event_id)
                    consumed_common_members.add(member_event.event_id)
                self._consume_common_cause_group(
                    payload,
                    factor,
                    member_events,
                    instance_id=instance_id,
                )
                continue
            event_time = max(float(payload["state_time"]), float(event.payload["available_at"]))
            self._advance_patient_state(payload, event_time)
            payload["event_ledger"][event.event_id] = event.event_digest
            consumed.append(event.event_id)
            kind = event.payload["event_type"]
            if kind == "ObservationAvailable":
                self._consume_observation(payload, event)
            elif kind in {
                "ActionStarted", "ActionContinued", "ActionDoseChanged", "ActionHeld",
                "ActionStopped", "ActionCompleted",
            }:
                self._consume_action(payload, event)
            elif kind in {"PlannedAction", "PlannedTreatment"}:
                action_id = str(event.payload.get("action_id") or "")
                if action_id not in self.actions:
                    raise ValueError(f"unregistered planned action: {action_id}")
                source_id = str(event.payload["provenance"]["source_result_id"])
                semantic_fingerprint = self._action_source_fingerprint(event)
                payload["planned_action_records"].append(
                    {
                        "event_id": event.event_id,
                        "source_result_id": source_id,
                        "source_fingerprint": semantic_fingerprint,
                        "action_id": action_id,
                        "exposure_id": event.payload.get("exposure_id"),
                        "available_at": event.payload["available_at"],
                        "event_cursor": len(payload["event_ledger"]),
                    }
                )
                payload["action_source_ledger"][source_id] = {
                    "fingerprint": semantic_fingerprint,
                    "event_type": kind,
                    "action_id": action_id,
                    "exposure_id": event.payload.get("exposure_id"),
                }
            else:
                source_id, _, semantic_fingerprint = self._register_observation_source_member(
                    payload, event
                )
                inference_fingerprint = self._observation_inference_fingerprint(event)
                payload["evidence_trace"].append(
                    {
                        "event_id": event.event_id,
                        "event_digest": event.event_digest,
                        "semantic_fingerprint": semantic_fingerprint,
                        "inference_fingerprint": inference_fingerprint,
                        # RecordOnly has occurrence rather than laboratory
                        # sample/result times.  Preserve that distinction while
                        # still carrying a complete temporal provenance tuple.
                        "sample_time": copy.deepcopy(event.payload["occurred_time"]),
                        "result_at": event.payload["recorded_at"],
                        "recorded_at": event.payload["recorded_at"],
                        "available_at": event.payload["available_at"],
                        "provenance_digest": digest(event.payload.get("provenance", {})),
                        "concept_id": str(event.payload.get("concept_id") or kind),
                        "factor_id": f"DISPOSITION:{event.event_id}",
                        "source_result_id": source_id,
                        "status": "RECORD_ONLY_EVENT",
                        "disposition_reason": f"record_only_event_type:{kind}",
                        "reliability": 0.0,
                    }
                )
                payload["warnings"].append(f"record_only_event_type:{kind}")
        self._advance_patient_state(payload, advance_to)
        payload["lineage"] = {
            "parent_state_hash": parent_hash,
            "consumed_event_ids": sorted(consumed),
            "skipped_duplicate_event_ids": sorted(skipped),
            "migration_history": copy.deepcopy(payload.get("lineage", {}).get("migration_history", [])),
        }
        payload["warnings"] = sorted(set(payload["warnings"]))
        if consumed:
            payload["event_ledger_digest"] = ledger_entries_digest(payload["event_ledger"])
        self._derive_marginals(payload)
        self._derive_epistemic(payload)
        return payload

    def _is_equivalent_source_duplicate(
        self,
        payload: Mapping[str, Any],
        event: PublicEvent,
    ) -> bool:
        row = event.payload
        kind = str(row.get("event_type") or "")
        source_id = str(row.get("provenance", {}).get("source_result_id") or event.event_id)
        if kind in {
            "PlannedAction", "PlannedTreatment", "ActionStarted", "ActionContinued",
            "ActionDoseChanged", "ActionHeld", "ActionStopped", "ActionCompleted",
        }:
            existing = payload.get("action_source_ledger", {}).get(source_id)
            if existing is None:
                if (
                    not payload.get("action_source_identity_complete", False)
                    and source_id != event.event_id
                ):
                    raise ValueError(
                        "action source_result_id is not bound by the frozen canonical wire; "
                        "new transport rendering fails closed"
                    )
                return False
            fingerprint = self._action_source_fingerprint(event)
            known = existing.get("fingerprint") if isinstance(existing, Mapping) else None
            if known is None:
                raise ValueError(
                    f"content-addressed action source proof required: {source_id}"
                )
            if known != fingerprint:
                raise ValueError(f"action/source collision with changed semantics: {source_id}")
            return True
        if kind not in {"ObservationAvailable", "RecordOnly"}:
            return False
        concept_id = str(row.get("concept_id") or kind)
        evidence_key = f"source:{source_id}"
        if evidence_key in payload.get("evidence_ledger", {}):
            existing = payload["evidence_ledger"][evidence_key]
            fingerprint = self._observation_source_fingerprint(event)
            inference_fingerprint = self._observation_inference_fingerprint(event)
            if isinstance(existing, Mapping) and isinstance(existing.get("members"), Mapping):
                known = existing["members"].get(concept_id)
                if known is None:
                    if any(
                        isinstance(member, Mapping)
                        and member.get("inference_fingerprint") == inference_fingerprint
                        for member in existing["members"].values()
                    ):
                        return True
                    return False
                known_fingerprint = (
                    known.get("fingerprint") if isinstance(known, Mapping) else known
                )
                if known_fingerprint != fingerprint:
                    raise ValueError(
                        f"factor/source member collision with changed evidence: "
                        f"{evidence_key}:{concept_id}"
                    )
                return True
            # Compatibility with an earlier one-member ledger representation.
            if isinstance(existing, Mapping) and existing.get("concept_id") == concept_id:
                if existing.get("fingerprint") not in {None, fingerprint}:
                    raise ValueError(
                        f"factor/source collision with changed evidence: {evidence_key}"
                    )
                return True
        return False

    @staticmethod
    def _observation_source_fingerprint(event: PublicEvent) -> str:
        """Digest every semantic observation field except its transport event id.

        A second rendering is exact-once only when *all* fields that can alter
        inference agree: value/unit, temporal coordinates, reliability,
        measurement conditions, rankability and full provenance included.
        """

        row = copy.deepcopy(event.payload)
        row.pop("event_id", None)
        return digest(row)

    def _observation_inference_fingerprint(self, event: PublicEvent) -> str:
        """Common-parent member identity excluding names/rendering aliases."""

        row = event.payload
        observation = self.observations.get(str(row.get("concept_id") or ""))
        if observation is None:
            return self._observation_source_fingerprint(event)
        observation_semantics = {
            key: copy.deepcopy(value)
            for key, value in observation.items()
            if key not in {"concept_id", "factor_id"}
        }
        return digest(
            {
                "observation_semantics": observation_semantics,
                "value": copy.deepcopy(row.get("value")),
                "unit": row.get("unit"),
                "reliability": row.get("reliability", 1.0),
                "measurement_condition": copy.deepcopy(row.get("measurement_condition")),
                "rankable": row.get("rankable", True),
                "sample_time": copy.deepcopy(row.get("sample_time")),
                "occurred_time": copy.deepcopy(row.get("occurred_time")),
                "result_at": row.get("result_at"),
                "recorded_at": row.get("recorded_at"),
                "available_at": row.get("available_at"),
            }
        )

    def _register_observation_source_member(
        self,
        payload: dict[str, Any],
        event: PublicEvent,
    ) -> tuple[str, str, str]:
        row = event.payload
        concept_id = str(row.get("concept_id") or row.get("event_type") or "record-only")
        source_id = str(row.get("provenance", {}).get("source_result_id") or event.event_id)
        evidence_key = f"source:{source_id}"
        fingerprint = self._observation_source_fingerprint(event)
        inference_fingerprint = self._observation_inference_fingerprint(event)
        existing = payload["evidence_ledger"].get(evidence_key)
        if isinstance(existing, Mapping) and isinstance(existing.get("members"), Mapping):
            members = dict(existing["members"])
        elif isinstance(existing, Mapping) and existing.get("concept_id"):
            members = {
                str(existing["concept_id"]): {
                    "fingerprint": existing.get("fingerprint"),
                    "event_id": existing.get("event_id"),
                }
            }
        elif existing is None:
            members = {}
        else:
            members = {}
        known = members.get(concept_id)
        if known is not None:
            known_fingerprint = known.get("fingerprint") if isinstance(known, Mapping) else known
            if known_fingerprint != fingerprint:
                raise ValueError(
                    f"factor/source member collision with changed evidence: "
                    f"{evidence_key}:{concept_id}"
                )
            raise ValueError(
                "internal duplicate observation member reached consumption instead of exact-once filter"
            )
        members[concept_id] = {
            "fingerprint": fingerprint,
            "inference_fingerprint": inference_fingerprint,
            "event_id": event.event_id,
            "event_digest": event.event_digest,
        }
        payload["evidence_ledger"][evidence_key] = {"members": members}
        return source_id, evidence_key, fingerprint

    @staticmethod
    def _is_time_local_observation(observation: Mapping[str, Any]) -> bool:
        return any(
            emission.get("coordinate_update")
            or emission.get("mode_likelihoods")
            or emission.get("stratum_likelihoods")
            for emission in observation.get("emissions", [])
        )

    def _measurement_reliability(
        self,
        payload: Mapping[str, Any],
        row: Mapping[str, Any],
        observation: Mapping[str, Any],
    ) -> tuple[float, float, float]:
        declared = float(row.get("reliability", 1.0)) * float(
            observation.get("reliability", 1.0)
        )
        condition = row.get("measurement_condition") or {}
        masking = float(condition.get("support_masking", 0.0))
        for exposure_id in condition.get("active_support_exposure_ids", []):
            instance = payload.get("action_instances", {}).get(str(exposure_id))
            if not isinstance(instance, Mapping):
                raise ValueError(
                    f"unknown active support exposure in measurement_condition: {exposure_id}"
                )
            action_id = str(instance.get("action_id") or "")
            action = self.actions.get(action_id)
            if action is None:
                raise ValueError(
                    f"unregistered active support exposure in measurement_condition: {exposure_id}"
                )
            # Masking belongs to the specifically named exposure, not to every
            # concurrent instance of the same action.  Otherwise one patient's
            # second support exposure could silently alter the measurement
            # condition attributed to the first one.
            status = str(instance.get("status") or "")
            dose = float(instance.get("current_dose", 0.0))
            if status in {"held", "stopped", "completed"}:
                washout_steps = float(action.get("washout_steps", 0.0))
                remaining = float(instance.get("washout_remaining", 0.0))
                dose *= (
                    _clamp(remaining / washout_steps, 0.0, 1.0)
                    if washout_steps > 0.0
                    else 0.0
                )
            elif status != "active":
                dose = 0.0
            masking = max(
                masking,
                _clamp(dose / max(_EPS, float(action["dose_reference"])), 0.0, 1.0),
            )
        effective = _clamp(declared * (1.0 - masking), 0.0, 1.0)
        return effective, declared, masking

    @staticmethod
    def _add_unexplained_observation(
        payload: dict[str, Any],
        *,
        result_id: str,
        reason: str,
        surprisal: float | None,
        candidate_process_ids: Sequence[str],
    ) -> None:
        existing = next(
            (
                item
                for item in payload["architecture_unexplained_observations"]
                if item.get("result_id") == result_id and item.get("reason") == reason
            ),
            None,
        )
        if existing is not None:
            existing["candidate_process_ids"] = sorted(
                set(existing.get("candidate_process_ids", [])) | set(candidate_process_ids)
            )
            if surprisal is not None:
                prior = existing.get("surprisal")
                existing["surprisal"] = max(float(prior or 0.0), float(surprisal))
            return
        payload["architecture_unexplained_observations"].append(
            {
                "result_id": result_id,
                "reason": reason,
                "surprisal": surprisal,
                "candidate_process_ids": sorted(set(candidate_process_ids)),
            }
        )

    def _consume_withheld_observation(
        self,
        payload: dict[str, Any],
        event: PublicEvent,
        *,
        source_id: str,
        semantic_fingerprint: str,
        disposition: str,
        candidate_process_ids: Sequence[str],
    ) -> None:
        row = event.payload
        payload["epistemic"]["measurement_count"] += 1
        # Withheld evidence is known to exist but supplies zero usable
        # measurement information to the declared inference state.
        payload["epistemic"]["measurement_reliability_sum"] += 0.0
        self._add_unexplained_observation(
            payload,
            result_id=source_id,
            reason="unknown_measurement_condition",
            surprisal=None,
            candidate_process_ids=candidate_process_ids or self.process_ids,
        )
        payload["evidence_trace"].append(
            {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "semantic_fingerprint": semantic_fingerprint,
                "inference_fingerprint": self._observation_inference_fingerprint(event),
                "sample_time": copy.deepcopy(row.get("sample_time")),
                "result_at": row.get("result_at"),
                "recorded_at": row.get("recorded_at"),
                "available_at": row.get("available_at"),
                "provenance_digest": digest(row.get("provenance", {})),
                "concept_id": str(row.get("concept_id") or "record-only-observation"),
                "factor_id": f"DISPOSITION:{event.event_id}",
                "source_result_id": source_id,
                "status": "RECORD_ONLY_NONRANKABLE",
                "disposition_reason": disposition,
                "canonical_unexplained_reason": "unknown_measurement_condition",
                "reliability": 0.0,
            }
        )

    @staticmethod
    def _action_source_fingerprint(event: PublicEvent) -> str:
        """Digest action semantics while ignoring transport-rendering fields."""

        row = event.payload
        return digest(
            {
                "event_type": row.get("event_type"),
                "action_id": row.get("action_id"),
                "exposure_id": row.get("exposure_id"),
                "occurred_time": row.get("occurred_time"),
                "dose": row.get("dose"),
                "dose_unit": row.get("dose_unit"),
                "route": row.get("route"),
            }
        )

    def _consume_common_cause_group(
        self,
        payload: dict[str, Any],
        factor: Mapping[str, Any],
        events: Sequence[PublicEvent],
        *,
        instance_id: str,
    ) -> None:
        """Assimilate several observation events as one declared latent factor."""

        member_rows: list[dict[str, Any]] = []
        for event in events:
            row = event.payload
            concept_id = str(row["concept_id"])
            observation = self.observations[concept_id]
            if row.get("rankable", True) is False:
                raise ValueError(
                    f"{factor['factor_id']}: non-rankable common-cause member cannot be "
                    "partially assimilated"
                )
            if self._is_time_local_observation(observation) and float(
                row["sample_time"]["upper"]
            ) < float(payload["state_time"]) - _EPS:
                raise ValueError(
                    f"{factor['factor_id']}: asynchronous common-cause smoothing is NOT_SUPPORTED"
                )
            source_id, _, semantic_fingerprint = self._register_observation_source_member(
                payload, event
            )
            inference_fingerprint = self._observation_inference_fingerprint(event)
            effective, declared, masking = self._measurement_reliability(
                payload, row, observation
            )
            member_rows.append(
                {
                    "event": event,
                    "row": row,
                    "observation": observation,
                    "source_result_id": source_id,
                    "semantic_fingerprint": semantic_fingerprint,
                    "inference_fingerprint": inference_fingerprint,
                    "effective_reliability": effective,
                    "declared_reliability": declared,
                    "support_masking": masking,
                }
            )

        group_reliability = min(
            float(member["effective_reliability"]) for member in member_rows
        )
        value_object = {
            str(member["row"]["concept_id"]): copy.deepcopy(member["row"]["value"])
            for member in sorted(member_rows, key=lambda value: value["row"]["concept_id"])
        }
        value_key = json.dumps(
            value_object,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        joint_log_likelihoods = {
            str(active_set): group_reliability * log_likelihood(distribution, value_key)
            for active_set, distribution in factor["joint_value_likelihoods"].items()
        }
        target_process_ids = sorted(
            {
                str(emission["process_id"])
                for member in member_rows
                for emission in member["observation"]["emissions"]
            }
        )
        unknown_llr = 0.0
        if factor.get("unknown_likelihood") is not None:
            unknown_llr = group_reliability * (
                log_likelihood(factor["unknown_likelihood"], value_key)
                - log_likelihood(factor["reference_likelihood"], value_key)
            )

        # One upstream factor is one mapped evidence update, while measurement
        # quality still accounts for every contributing raw member.
        payload["epistemic"]["mapped_observation_count"] += 1
        payload["epistemic"]["measurement_count"] += len(member_rows)
        payload["epistemic"]["measurement_reliability_sum"] += sum(
            float(member["effective_reliability"]) for member in member_rows
        )

        emission_trace: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        for member in member_rows:
            event = member["event"]
            row = member["row"]
            observation = member["observation"]
            reliability = float(member["effective_reliability"])
            bindings.append(
                {
                    "event_id": event.event_id,
                    "event_digest": event.event_digest,
                    "source_result_id": str(member["source_result_id"]),
                    "concept_id": str(row["concept_id"]),
                    "fingerprint": str(member["semantic_fingerprint"]),
                    "inference_fingerprint": str(member["inference_fingerprint"]),
                    "reliability": reliability,
                    "common_cause_instance_id": str(instance_id),
                }
            )
            for emission in observation["emissions"]:
                pid = str(emission["process_id"])
                active_logp = reliability * log_likelihood(
                    emission["active_likelihood"], row["value"]
                )
                inactive_logp = reliability * log_likelihood(
                    emission["inactive_likelihood"], row["value"]
                )
                emission_trace.append(
                    {
                        "process_id": pid,
                        "member_concept_id": str(row["concept_id"]),
                        "active_log_likelihood": active_logp,
                        "inactive_log_likelihood": inactive_logp,
                        "signed_llr": active_logp - inactive_logp,
                        "direction": "LOCAL_ONLY_COMMON_CAUSE_MEMBER",
                    }
                )
                coordinate_update = emission.get("coordinate_update")
                before_coordinate = None
                if coordinate_update:
                    before_coordinate = float(
                        payload["per_process"][pid]["coordinates"][
                            coordinate_update["coordinate_id"]
                        ]["mean"]
                    )
                self._update_coordinate(
                    payload,
                    pid,
                    coordinate_update,
                    row["value"],
                    reliability=reliability,
                )
                if coordinate_update and before_coordinate is not None:
                    after_coordinate = float(
                        payload["per_process"][pid]["coordinates"][
                            coordinate_update["coordinate_id"]
                        ]["mean"]
                    )
                    self._record_action_response(
                        payload,
                        event,
                        pid,
                        coordinate_update["coordinate_id"],
                        before_coordinate,
                        after_coordinate,
                    )
                before_modes = payload["per_process"][pid]["mode_posterior"]
                before_mode = max(before_modes, key=before_modes.get)
                self._update_local_mode(
                    payload,
                    pid,
                    emission.get("mode_likelihoods", {}),
                    row["value"],
                    reliability=reliability,
                )
                self._update_local_stratum(
                    payload,
                    pid,
                    emission.get("stratum_likelihoods", {}),
                    row["value"],
                    reliability=reliability,
                )
                guarded_modes, guard_trace = self._apply_mode_guards(
                    pid,
                    payload["per_process"][pid]["coordinates"],
                    payload["per_process"][pid]["mode_posterior"],
                )
                payload["per_process"][pid]["mode_posterior"] = guarded_modes
                after_modes = payload["per_process"][pid]["mode_posterior"]
                after_mode = max(after_modes, key=after_modes.get)
                if before_mode != after_mode:
                    cursor = len(payload["event_ledger"])
                    payload["mode_transitions"].append(
                        {
                            "stratum_id": max(
                                sorted(payload["per_process"][pid]["stratum_posterior"]),
                                key=lambda key: payload["per_process"][pid][
                                    "stratum_posterior"
                                ][key],
                            ),
                            "from_mode_id": before_mode,
                            "to_mode_id": after_mode,
                            "event_cursor": cursor,
                            "probability": float(after_modes[after_mode]),
                            "guard_ids": [f"common_cause:{factor['factor_id']}"]
                            + [trace["guard_id"] for trace in guard_trace],
                        }
                    )
                    payload["per_process"][pid]["last_transition_cursor"] = cursor
            self._update_history(
                payload,
                str(row["concept_id"]),
                row["value"],
                row["available_at"],
                event.event_id,
                row.get("unit"),
            )

        self._update_joint_common_factor(
            payload,
            target_process_ids,
            joint_log_likelihoods,
            unknown_llr,
        )
        best_known = max(joint_log_likelihoods.values())
        surprise = max(0.0, -min(0.0, best_known))
        payload["epistemic"]["misfit_sum"] += 1.0 - math.exp(-surprise)
        if surprise >= float(
            self.spec["epistemic"]["known_factor_misfit_surprisal_threshold"]
        ):
            self._add_unexplained_observation(
                payload,
                result_id=str(instance_id),
                reason="model_misfit",
                surprisal=surprise,
                candidate_process_ids=target_process_ids,
            )

        leader = member_rows[0]
        leader_row = leader["row"]
        payload["evidence_trace"].append(
            {
                "event_id": leader["event"].event_id,
                "event_digest": leader["event"].event_digest,
                "semantic_fingerprint": leader["semantic_fingerprint"],
                "inference_fingerprint": leader["inference_fingerprint"],
                "sample_time": copy.deepcopy(leader_row.get("sample_time")),
                "result_at": leader_row.get("result_at"),
                "recorded_at": leader_row.get("recorded_at"),
                "available_at": leader_row.get("available_at"),
                "provenance_digest": digest(leader_row.get("provenance", {})),
                "concept_id": str(leader_row["concept_id"]),
                "factor_id": str(factor["factor_id"]),
                "source_result_id": str(leader["source_result_id"]),
                "source_result_ids": sorted(
                    {str(binding["source_result_id"]) for binding in bindings}
                ),
                "status": "CONSUMED_COMMON_CAUSE",
                "common_cause_instance_id": str(instance_id),
                "common_cause_bindings": sorted(
                    bindings,
                    key=lambda binding: (
                        binding["concept_id"], binding["source_result_id"], binding["event_id"]
                    ),
                ),
                "emissions": emission_trace,
                "joint_log_likelihoods": joint_log_likelihoods,
                "topology_contributions": [],
                "unknown_llr": unknown_llr,
                "reliability": group_reliability,
                "declared_reliability": min(
                    float(member["declared_reliability"]) for member in member_rows
                ),
                "support_masking": max(
                    float(member["support_masking"]) for member in member_rows
                ),
                "conflicting_measurements": [],
            }
        )

    def _consume_observation(self, payload: dict[str, Any], event: PublicEvent) -> None:
        row = event.payload
        source_id, evidence_key, semantic_fingerprint = self._register_observation_source_member(
            payload, event
        )
        inference_fingerprint = self._observation_inference_fingerprint(event)
        concept_id = str(row["concept_id"])
        observation = self.observations.get(concept_id)
        if row.get("rankable", True) is False:
            candidates = (
                [str(emission["process_id"]) for emission in observation["emissions"]]
                if observation is not None
                else list(self.process_ids)
            )
            self._consume_withheld_observation(
                payload,
                event,
                source_id=source_id,
                semantic_fingerprint=semantic_fingerprint,
                disposition=str(
                    row.get("mapper_disposition_reason") or "UNKNOWN_CONDITION"
                ),
                candidate_process_ids=candidates,
            )
            return
        if observation is None:
            payload["epistemic"]["unmapped_observation_count"] += 1
            payload["epistemic"]["measurement_count"] += 1
            payload["epistemic"]["measurement_reliability_sum"] += float(
                row.get("reliability", 1.0)
            )
            unknown_llr = float(self.spec["epistemic"]["unmapped_event_log_bayes_factor"])
            self._update_joint(payload, {}, unknown_llr)
            payload["evidence_trace"].append(
                {
                    "event_id": event.event_id,
                    "event_digest": event.event_digest,
                    "semantic_fingerprint": semantic_fingerprint,
                    "inference_fingerprint": inference_fingerprint,
                    "sample_time": copy.deepcopy(row.get("sample_time")),
                    "result_at": row.get("result_at"),
                    "recorded_at": row.get("recorded_at"),
                    "available_at": row.get("available_at"),
                    "provenance_digest": digest(row.get("provenance", {})),
                    "concept_id": concept_id,
                    "status": "UNMAPPED",
                    "unknown_llr": unknown_llr,
                    "source_result_id": source_id,
                    "reliability": float(row.get("reliability", 1.0)),
                }
            )
            return

        factor_id = str(observation["factor_id"])
        if self._is_time_local_observation(observation) and float(
            row["sample_time"]["upper"]
        ) < float(payload["state_time"]) - _EPS:
            self._consume_withheld_observation(
                payload,
                event,
                source_id=source_id,
                semantic_fingerprint=semantic_fingerprint,
                disposition="TEMPORAL_OOD_NO_SMOOTHING",
                candidate_process_ids=[
                    str(emission["process_id"]) for emission in observation["emissions"]
                ],
            )
            return

        effective_reliability, declared_reliability, support_masking = (
            self._measurement_reliability(payload, row, observation)
        )
        payload["epistemic"]["mapped_observation_count"] += 1
        payload["epistemic"]["measurement_count"] += 1
        payload["epistemic"]["measurement_reliability_sum"] += effective_reliability

        direct: dict[str, float] = {}
        emission_trace: list[dict[str, Any]] = []
        best_known_log_likelihood = -math.inf
        joint_log_likelihoods: dict[str, float] = {}
        if observation.get("joint_likelihoods") is not None:
            joint_log_likelihoods = {
                str(active_set): effective_reliability
                * log_likelihood(distribution, row["value"])
                for active_set, distribution in observation["joint_likelihoods"].items()
            }
            best_known_log_likelihood = max(joint_log_likelihoods.values())
        for emission in observation["emissions"]:
            pid = emission["process_id"]
            active_logp = effective_reliability * log_likelihood(
                emission["active_likelihood"], row["value"]
            )
            inactive_logp = effective_reliability * log_likelihood(
                emission["inactive_likelihood"], row["value"]
            )
            llr = active_logp - inactive_logp
            if not joint_log_likelihoods:
                direct[pid] = direct.get(pid, 0.0) + llr
                best_known_log_likelihood = max(
                    best_known_log_likelihood, active_logp, inactive_logp
                )
            emission_trace.append(
                {
                    "process_id": pid,
                    "active_log_likelihood": active_logp,
                    "inactive_log_likelihood": inactive_logp,
                    "signed_llr": llr,
                    "direction": "SUPPORTS" if llr > 1e-12 else "REFUTES" if llr < -1e-12 else "NEUTRAL",
                }
            )
            coordinate_update = emission.get("coordinate_update")
            before_coordinate = None
            if coordinate_update:
                before_coordinate = float(
                    payload["per_process"][pid]["coordinates"][
                        coordinate_update["coordinate_id"]
                    ]["mean"]
                )
            self._update_coordinate(
                payload,
                pid,
                coordinate_update,
                row["value"],
                reliability=effective_reliability,
            )
            if coordinate_update and before_coordinate is not None:
                after_coordinate = float(
                    payload["per_process"][pid]["coordinates"][
                        coordinate_update["coordinate_id"]
                    ]["mean"]
                )
                self._record_action_response(
                    payload,
                    event,
                    pid,
                    coordinate_update["coordinate_id"],
                    before_coordinate,
                    after_coordinate,
                )
            before_modes = payload["per_process"][pid]["mode_posterior"]
            before_mode = max(before_modes, key=before_modes.get)
            self._update_local_mode(
                payload,
                pid,
                emission.get("mode_likelihoods", {}),
                row["value"],
                reliability=effective_reliability,
            )
            self._update_local_stratum(
                payload,
                pid,
                emission.get("stratum_likelihoods", {}),
                row["value"],
                reliability=effective_reliability,
            )
            guarded_modes, guard_trace = self._apply_mode_guards(
                pid,
                payload["per_process"][pid]["coordinates"],
                payload["per_process"][pid]["mode_posterior"],
            )
            payload["per_process"][pid]["mode_posterior"] = guarded_modes
            after_modes = payload["per_process"][pid]["mode_posterior"]
            after_mode = max(after_modes, key=after_modes.get)
            if before_mode != after_mode:
                cursor = len(payload["event_ledger"])
                payload["mode_transitions"].append(
                    {
                        "stratum_id": max(
                            sorted(payload["per_process"][pid]["stratum_posterior"]),
                            key=lambda key: payload["per_process"][pid]["stratum_posterior"][key],
                        ),
                        "from_mode_id": before_mode,
                        "to_mode_id": after_mode,
                        "event_cursor": cursor,
                        "probability": float(after_modes[after_mode]),
                        "guard_ids": [f"emission:{factor_id}"]
                        + [trace["guard_id"] for trace in guard_trace],
                    }
                )
                payload["per_process"][pid]["last_transition_cursor"] = cursor

        conflicts: list[dict[str, Any]] = []
        prior_messages = copy.deepcopy(payload.get("architecture_factor_messages", []))
        # Also include earlier events from the current update batch; those have
        # not yet been materialized into architecture_factor_messages.
        for trace in payload.get("evidence_trace", []):
            if trace.get("status") != "CONSUMED":
                continue
            likelihoods: dict[str, float] = {}
            for prior_emission in trace.get("emissions", []):
                prior_pid = str(prior_emission["process_id"])
                likelihoods[f"process:{prior_pid}:active"] = float(
                    prior_emission["active_log_likelihood"]
                )
                likelihoods[f"process:{prior_pid}:inactive"] = float(
                    prior_emission["inactive_log_likelihood"]
                )
            prior_messages.append(
                {
                    "factor_id": trace.get("factor_id"),
                    "source_result_ids": [trace.get("source_result_id")],
                    "log_likelihood_by_hypothesis": likelihoods,
                }
            )
        for prior_message in prior_messages:
            if prior_message.get("factor_id") != factor_id:
                continue
            likelihoods = prior_message.get("log_likelihood_by_hypothesis", {})
            for pid, current_llr in direct.items():
                prior_active = likelihoods.get(f"process:{pid}:active")
                prior_inactive = likelihoods.get(f"process:{pid}:inactive")
                if prior_active is None or prior_inactive is None:
                    continue
                prior_llr = float(prior_active) - float(prior_inactive)
                if prior_llr * float(current_llr) >= -1e-12:
                    continue
                strength = min(abs(prior_llr), abs(float(current_llr)))
                conflicts.append(
                    {
                        "process_id": pid,
                        "prior_source_result_ids": list(prior_message["source_result_ids"]),
                        "current_source_result_id": source_id,
                        "opposed_signed_llrs": [prior_llr, float(current_llr)],
                        "strength": strength,
                    }
                )
        if conflicts:
            conflict_surprisal = max(row["strength"] for row in conflicts)
            payload["epistemic"]["misfit_sum"] += 1.0 - math.exp(-conflict_surprisal)
            if not any(
                row.get("result_id") == source_id
                and row.get("reason") == "conflicting_measurements"
                for row in payload["architecture_unexplained_observations"]
            ):
                payload["architecture_unexplained_observations"].append(
                    {
                        "result_id": source_id,
                        "reason": "conflicting_measurements",
                        "surprisal": conflict_surprisal,
                        "candidate_process_ids": sorted({row["process_id"] for row in conflicts}),
                    }
                )

        combined = dict(direct)
        topology_trace: list[dict[str, Any]] = []
        topology = self.spec["topology"]
        coupling = float(topology["inference_coupling"]) if self.topology_enabled else 0.0
        scale = max(_EPS, float(topology["distance_scale"]))
        if coupling:
            for source, source_llr in sorted(direct.items()):
                for target in self.process_ids:
                    if target == source:
                        continue
                    distance = self.branch_distance(source, target)
                    if not math.isfinite(distance):
                        continue
                    weight = coupling * math.exp(-distance / scale)
                    contribution = source_llr * weight
                    combined[target] = combined.get(target, 0.0) + contribution
                    topology_trace.append(
                        {
                            "source_process_id": source,
                            "target_process_id": target,
                            "distance": distance,
                            "weight": weight,
                            "signed_llr": contribution,
                        }
                    )

        unknown_llr = 0.0
        if observation.get("unknown_likelihood") is not None:
            unknown_logp = effective_reliability * log_likelihood(
                observation["unknown_likelihood"], row["value"]
            )
            reference_logp = effective_reliability * log_likelihood(
                observation["reference_likelihood"], row["value"]
            )
            unknown_llr = unknown_logp - reference_logp
        if joint_log_likelihoods:
            self._update_joint_common_factor(
                payload,
                [str(emission["process_id"]) for emission in observation["emissions"]],
                joint_log_likelihoods,
                unknown_llr,
            )
        else:
            self._update_joint(payload, combined, unknown_llr)

        surprise = max(0.0, -min(0.0, best_known_log_likelihood))
        payload["epistemic"]["misfit_sum"] += 1.0 - math.exp(-surprise)
        if surprise >= float(
            self.spec["epistemic"]["known_factor_misfit_surprisal_threshold"]
        ):
            self._add_unexplained_observation(
                payload,
                result_id=source_id,
                reason="model_misfit",
                surprisal=surprise,
                candidate_process_ids=[
                    str(emission["process_id"]) for emission in observation["emissions"]
                ],
            )
        self._update_history(
            payload,
            concept_id,
            row["value"],
            row["available_at"],
            event.event_id,
            row.get("unit"),
        )
        payload["evidence_trace"].append(
            {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "semantic_fingerprint": semantic_fingerprint,
                "inference_fingerprint": inference_fingerprint,
                "sample_time": copy.deepcopy(row.get("sample_time")),
                "result_at": row.get("result_at"),
                "recorded_at": row.get("recorded_at"),
                "available_at": row.get("available_at"),
                "provenance_digest": digest(row.get("provenance", {})),
                "concept_id": concept_id,
                "factor_id": factor_id,
                "source_result_id": source_id,
                "status": "CONSUMED",
                "emissions": emission_trace,
                "joint_log_likelihoods": joint_log_likelihoods,
                "topology_contributions": topology_trace,
                "unknown_llr": unknown_llr,
                "reliability": effective_reliability,
                "declared_reliability": declared_reliability,
                "support_masking": support_masking,
                "conflicting_measurements": conflicts,
            }
        )

    def _update_joint(
        self,
        payload: dict[str, Any],
        process_llrs: Mapping[str, float],
        unknown_llr: float,
    ) -> None:
        log_weights: list[float] = []
        for hypothesis in payload["joint_hypotheses"]:
            probability = max(_EPS, float(hypothesis["probability"]))
            value = math.log(probability)
            active = set(hypothesis["active_processes"])
            value += sum(float(llr) for pid, llr in process_llrs.items() if pid in active)
            if hypothesis["unknown_active"]:
                value += float(unknown_llr)
            log_weights.append(value)
        normalizer = _logsumexp(log_weights)
        for hypothesis, log_weight in zip(payload["joint_hypotheses"], log_weights):
            hypothesis["probability"] = math.exp(log_weight - normalizer)
        self._derive_marginals(payload)

    def _update_joint_common_factor(
        self,
        payload: dict[str, Any],
        process_ids: Sequence[str],
        joint_log_likelihoods: Mapping[str, float],
        unknown_llr: float,
    ) -> None:
        target_ids = set(process_ids)
        log_weights: list[float] = []
        for hypothesis in payload["joint_hypotheses"]:
            probability = max(_EPS, float(hypothesis["probability"]))
            local_active = sorted(set(hypothesis["active_processes"]).intersection(target_ids))
            active_key = ",".join(local_active) or "-"
            if active_key not in joint_log_likelihoods:
                raise ValueError(
                    f"joint common-cause factor omits active set: {active_key}"
                )
            value = math.log(probability) + float(joint_log_likelihoods[active_key])
            if hypothesis["unknown_active"]:
                value += float(unknown_llr)
            log_weights.append(value)
        normalizer = _logsumexp(log_weights)
        for hypothesis, log_weight in zip(payload["joint_hypotheses"], log_weights):
            hypothesis["probability"] = math.exp(log_weight - normalizer)
        self._derive_marginals(payload)

    def _derive_marginals(self, payload: dict[str, Any]) -> None:
        marginals = {pid: 0.0 for pid in self.process_ids}
        unknown = 0.0
        for hypothesis in payload["joint_hypotheses"]:
            probability = float(hypothesis["probability"])
            for pid in hypothesis["active_processes"]:
                marginals[pid] += probability
            if hypothesis["unknown_active"]:
                unknown += probability
        payload["process_activation_marginals"] = marginals
        payload.setdefault("epistemic", {})["unknown_process_probability"] = unknown

    def _derive_epistemic(self, payload: dict[str, Any]) -> None:
        epistemic = payload["epistemic"]
        mapped = int(epistemic["mapped_observation_count"])
        unmapped = int(epistemic["unmapped_observation_count"])
        alpha, beta = map(float, self.spec["epistemic"]["mapping_beta_prior"])
        epistemic["mapping_residual"] = (unmapped + alpha) / (mapped + unmapped + alpha + beta)
        epistemic["model_misfit_residual"] = float(epistemic["misfit_sum"]) / max(1, mapped)

    def _update_history(
        self,
        payload: dict[str, Any],
        concept_id: str,
        value: Any,
        at: Any,
        event_id: str,
        unit: Any,
    ) -> None:
        old = payload["history_summary"].get(concept_id)
        trend: float | None = None
        old_latest = old.get("latest") if old is not None else None
        old_is_numeric = (
            not isinstance(old_latest, bool)
            and isinstance(old_latest, (int, float))
            and math.isfinite(float(old_latest))
        )
        value_is_numeric = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
        )
        # Python's bool is a subclass of int, but a repeated present/absent
        # finding is not a quantitative trajectory.  Treating True/False as
        # 1/0 created a trend that the frozen numeric-only trajectory wire
        # could not encode, so a valid warm state failed on cold query.
        if old is not None and old_is_numeric and value_is_numeric:
            trend = float(value) - float(old["latest"])
        payload["history_summary"][concept_id] = {
            "latest": copy.deepcopy(value),
            "previous": copy.deepcopy(old.get("latest")) if old else None,
            "trend": trend,
            "count": int(old.get("count", 0)) + 1 if old else 1,
            "latest_available_at": at,
            "source_event_ids": sorted(set((old.get("source_event_ids", []) if old else []) + [event_id])),
            "unit": unit,
        }

    def _update_coordinate(
        self,
        payload: dict[str, Any],
        process_id: str,
        update: Mapping[str, Any] | None,
        value: Any,
        *,
        reliability: float = 1.0,
    ) -> None:
        if not update:
            return
        coordinate_id = update["coordinate_id"]
        mapping = update.get("mapping", {"type": "identity"})
        mapping_type = mapping.get("type", "identity")
        coord_spec = next(
            row for row in self.processes[process_id]["coordinates"] if row["coordinate_id"] == coordinate_id
        )
        low, high = map(float, coord_spec["bounds"])
        if mapping_type == "identity":
            measured = float(value)
        elif mapping_type == "linear":
            in_low, in_high = map(float, mapping["input_range"])
            out_low, out_high = map(float, mapping.get("output_range", [low, high]))
            fraction = (float(value) - in_low) / max(_EPS, in_high - in_low)
            measured = out_low + fraction * (out_high - out_low)
        elif mapping_type == "binary_to_bounds":
            measured = high if _as_bool(value) else low
        else:
            raise ValueError(f"unsupported coordinate mapping type: {mapping_type}")
        measured = _clamp(measured, low, high)
        gain = _clamp(float(update.get("gain", 0.5)) * float(reliability), 0.0, 1.0)
        estimate = payload["per_process"][process_id]["coordinates"][coordinate_id]
        estimate["mean"] = _clamp((1.0 - gain) * float(estimate["mean"]) + gain * measured, low, high)
        estimate["uncertainty"] = max(0.0, float(estimate["uncertainty"]) * math.sqrt(1.0 - gain))

    def _update_local_mode(
        self,
        payload: dict[str, Any],
        process_id: str,
        likelihoods: Mapping[str, Mapping[str, Any]],
        value: Any,
        *,
        reliability: float = 1.0,
    ) -> None:
        if not likelihoods:
            return
        old = payload["per_process"][process_id]["mode_posterior"]
        log_weights = {
            mode_id: math.log(max(_EPS, float(probability)))
            + float(reliability) * log_likelihood(likelihoods[mode_id], value)
            for mode_id, probability in old.items()
            if mode_id in likelihoods
        }
        missing = set(old).difference(log_weights)
        if missing:
            raise ValueError(f"mode likelihood update omitted modes: {sorted(missing)}")
        normalizer = _logsumexp(list(log_weights.values()))
        payload["per_process"][process_id]["mode_posterior"] = {
            mode_id: math.exp(value - normalizer) for mode_id, value in sorted(log_weights.items())
        }

    def _update_local_stratum(
        self,
        payload: dict[str, Any],
        process_id: str,
        likelihoods: Mapping[str, Mapping[str, Any]],
        value: Any,
        *,
        reliability: float = 1.0,
    ) -> None:
        if not likelihoods:
            return
        old = payload["per_process"][process_id]["stratum_posterior"]
        if set(likelihoods) != set(old):
            raise ValueError("stratum likelihood update must cover the local refined partition")
        log_weights = {
            stratum_id: math.log(max(_EPS, float(probability)))
            + float(reliability) * log_likelihood(likelihoods[stratum_id], value)
            for stratum_id, probability in old.items()
        }
        normalizer = _logsumexp(list(log_weights.values()))
        payload["per_process"][process_id]["stratum_posterior"] = {
            stratum_id: math.exp(weight - normalizer)
            for stratum_id, weight in sorted(log_weights.items())
        }

    def _record_action_response(
        self,
        payload: dict[str, Any],
        event: PublicEvent,
        process_id: str,
        coordinate_id: str,
        before: float,
        after: float,
    ) -> None:
        delta = after - before
        direction = "increase" if delta > 1e-12 else "decrease" if delta < -1e-12 else "stable"
        event_cursor = len(payload["event_ledger"])
        baseline_hash = (
            payload.get("lineage", {}).get("parent_state_hash")
            or digest(
                {
                    "kind": "within-update-response-baseline",
                    "model_digest": self.model_digest,
                    "event_cursor": max(0, event_cursor - 1),
                }
            )
        )
        for exposure_id, instance in sorted(payload["action_instances"].items()):
            action = self.actions.get(instance["action_id"])
            if action is None or not any(
                effect["process_id"] == process_id
                and effect["coordinate_id"] == coordinate_id
                for effect in action.get("effects", [])
            ):
                continue
            if instance["status"] in {"completed"}:
                continue
            if instance["status"] == "stopped" and float(instance.get("washout_remaining", 0.0)) <= 0.0:
                continue
            # A transport sort is not a causal partial order.  Only create an
            # action-response window when the action is definitely established
            # before the observation's earliest possible occurrence.  An
            # overlapping start interval and result interval remains typed
            # ambiguity rather than fabricated response attribution.
            definitely_active_by = instance.get("definitely_active_by")
            observation_lower = float(event.payload["occurred_time"]["lower"])
            if definitely_active_by is None or float(definitely_active_by) >= observation_lower:
                information_id = f"temporal-order:{exposure_id}:{event.event_id}"
                if not any(
                    item.get("information_id") == information_id
                    for item in payload["missing_distinguishing_information"]
                ):
                    payload["missing_distinguishing_information"].append(
                        {
                            "information_id": information_id,
                            "target_query_id": f"action-response:{exposure_id}",
                            "expected_discrimination": 1.0,
                            "availability": "unknown",
                            "risk_class": "passive",
                        }
                    )
                continue
            window_id = f"response:{exposure_id}:{event.event_id}:{coordinate_id}"
            window = {
                "window_id": window_id,
                "action_instance_ids": [exposure_id],
                "start_cursor": int(instance.get("started_cursor") or 0),
                "end_cursor": event_cursor,
                "baseline_state_hash": baseline_hash,
                "result_event_ids": [event.event_id],
            }
            if not any(row["window_id"] == window_id for row in payload["action_response_windows"]):
                payload["action_response_windows"].append(window)
            summary = {
                "target_id": f"{process_id}.{coordinate_id}",
                "window_id": window_id,
                "direction": direction,
                "magnitude": {
                    "family": "point",
                    "mean": delta,
                    "sd": 0.0,
                    "quantiles": {"0.05": delta, "0.5": delta, "0.95": delta},
                    "particle_digest": None,
                },
                "attribution_status": "descriptive_only",
                "source_event_ids": [event.event_id],
            }
            instance.setdefault("response_summaries", []).append(summary)

    def _apply_mode_guards(
        self,
        process_id: str,
        coordinates: Mapping[str, Mapping[str, float]],
        modes: Mapping[str, float],
        *,
        step_width: float = 1.0,
        activity_weight: float = 1.0,
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        result = {str(key): float(value) for key, value in modes.items()}
        trace: list[dict[str, Any]] = []
        if not self.mode_guards_enabled:
            return result, trace
        for guard in self.processes[process_id].get("mode_guards", []):
            value = float(coordinates[guard["coordinate_id"]]["mean"])
            source = guard["source_mode_id"]
            target = guard["target_mode_id"]
            probability = float(guard["transition_probability"])
            effective_probability = (
                1.0 - (1.0 - probability) ** float(step_width)
                if probability < 1.0
                else 1.0
            )
            effective_probability *= _clamp(float(activity_weight), 0.0, 1.0)
            if guard["direction"] == "above":
                entering = value >= float(guard["enter_threshold"])
                exiting = value <= float(guard["exit_threshold"])
            else:
                entering = value <= float(guard["enter_threshold"])
                exiting = value >= float(guard["exit_threshold"])
            if entering:
                moved = result.get(source, 0.0) * effective_probability
                result[source] = result.get(source, 0.0) - moved
                result[target] = result.get(target, 0.0) + moved
                direction = f"{source}->{target}"
            elif exiting:
                moved = result.get(target, 0.0) * effective_probability
                result[target] = result.get(target, 0.0) - moved
                result[source] = result.get(source, 0.0) + moved
                direction = f"{target}->{source}"
            else:
                moved = 0.0
                direction = "HYSTERESIS_HOLD"
            trace.append(
                {
                    "guard_id": guard["guard_id"],
                    "coordinate_id": guard["coordinate_id"],
                    "coordinate_value": value,
                    "transition": direction,
                    "probability_mass_moved": moved,
                    "step_width": float(step_width),
                }
            )
        return _normalize(result), trace

    def _advance_patient_state(self, payload: dict[str, Any], target_time: float) -> None:
        """Advance factual state through the same dynamics used by forecast.

        Clock movement is not a bookkeeping-only operation.  Between public
        event cuts, coordinates, local modes, couplings, existing exposures,
        washout, and cumulative exposure all evolve.  We deliberately reuse
        ``rollout`` as the single dynamics kernel, then materialize its final
        state back into the canonical internal payload.  Longer factual jumps
        are chunked at the declared forecasting horizon rather than bypassing
        the frozen scope.
        """

        current = float(payload["state_time"])
        target = float(target_time)
        if target < current:
            return
        max_horizon = float(self.spec["scope"]["horizon"]["value"])
        while target - current > _EPS:
            duration = min(target - current, max_horizon)
            # A preceding event in the same availability cut may have changed
            # the joint posterior or residuals.  Materialize their canonical
            # derived views before passing the transient state through the
            # public, semantics-checked rollout kernel.
            self._derive_marginals(payload)
            self._derive_epistemic(payload)
            snapshot = copy.deepcopy(payload)
            # During a multi-event consume, the canonical ledger digest is
            # finalized at the end of the cut.  A transient dynamics snapshot
            # nevertheless needs a proof coherent with entries consumed so
            # far.
            snapshot["event_ledger_digest"] = ledger_entries_digest(
                snapshot["event_ledger"]
            )
            transient = internal_to_architecture_state(self, snapshot)
            forecast = self.rollout(
                transient,
                {"policy_id": "NO_NEW_ACTION", "start_actions": []},
                horizon=duration,
                _allow_fractional_horizon=True,
            )
            for process_id in self.process_ids:
                prior_modes = payload["per_process"][process_id]["mode_posterior"]
                next_modes = forecast["final_mode_posteriors"][process_id]
                from_mode = max(prior_modes, key=prior_modes.get)
                to_mode = max(next_modes, key=next_modes.get)
                if from_mode != to_mode:
                    event_cursor = len(payload["event_ledger"])
                    stratum_posterior = payload["per_process"][process_id].get(
                        "stratum_posterior", {f"stratum:{process_id}": 1.0}
                    )
                    stratum_id = max(
                        stratum_posterior, key=stratum_posterior.get
                    )
                    guard_ids = sorted(
                        {
                            str(row["guard_id"])
                            for row in forecast.get("mode_guard_trace", [])
                            if row.get("process_id") == process_id
                            and float(row.get("probability_mass_moved", 0.0)) > 0.0
                        }
                    )
                    transition = {
                        "stratum_id": stratum_id,
                        "from_mode_id": from_mode,
                        "to_mode_id": to_mode,
                        "event_cursor": event_cursor,
                        "probability": float(next_modes[to_mode]),
                        "guard_ids": guard_ids,
                    }
                    # Several fractional clock chunks at the same event cursor
                    # are one factual interval in the frozen wire.  Compress
                    # them to the net transition rather than creating an
                    # ambiguous duplicate (stratum, cursor) slot.
                    existing = next(
                        (
                            row
                            for row in payload["mode_transitions"]
                            if row["stratum_id"] == stratum_id
                            and int(row["event_cursor"]) == event_cursor
                        ),
                        None,
                    )
                    if existing is None:
                        payload["mode_transitions"].append(transition)
                        payload["per_process"][process_id][
                            "last_transition_cursor"
                        ] = event_cursor
                    elif existing["from_mode_id"] == to_mode:
                        payload["mode_transitions"].remove(existing)
                        prior_cursors = [
                            int(row["event_cursor"])
                            for row in payload["mode_transitions"]
                            if row["stratum_id"] == stratum_id
                        ]
                        payload["per_process"][process_id][
                            "last_transition_cursor"
                        ] = max(prior_cursors) if prior_cursors else None
                    else:
                        existing["to_mode_id"] = to_mode
                        existing["probability"] = float(next_modes[to_mode])
                        existing["guard_ids"] = sorted(
                            set(existing.get("guard_ids", [])).union(guard_ids)
                        )
                        payload["per_process"][process_id][
                            "last_transition_cursor"
                        ] = event_cursor
                payload["per_process"][process_id]["coordinates"] = copy.deepcopy(
                    forecast["final_coordinates"][process_id]
                )
                payload["per_process"][process_id]["mode_posterior"] = copy.deepcopy(
                    forecast["final_mode_posteriors"][process_id]
                )
            payload["joint_hypotheses"] = copy.deepcopy(
                forecast["final_joint_hypotheses"]
            )
            self._derive_marginals(payload)
            next_time = current + duration
            self._advance_actions(payload, next_time)
            current = next_time

    def _advance_actions(self, payload: dict[str, Any], target_time: float) -> None:
        current = float(payload["state_time"])
        if target_time < current:
            return
        elapsed = target_time - current
        for instance in payload["action_instances"].values():
            if instance["status"] == "active":
                instance["cumulative_exposure"] += float(instance["current_dose"]) * elapsed
            elif instance["status"] in {"held", "stopped", "completed"}:
                instance["washout_remaining"] = max(
                    0.0, float(instance["washout_remaining"]) - elapsed
                )
            instance["last_accounted_at"] = target_time
        payload["state_time"] = target_time

    def _consume_action(self, payload: dict[str, Any], event: PublicEvent) -> None:
        row = event.payload
        action_id = str(row["action_id"])
        exposure_id = str(row["exposure_id"])
        if action_id not in self.actions:
            # A performed action changes the factual state.  Silently dropping
            # an unmodelled administration would erase causal history while
            # retaining a misleading event-ledger entry, so the public update
            # must fail closed until a typed OOD action representation exists.
            raise ValueError(f"unregistered performed action: {action_id}")
        action = self.actions[action_id]
        instances = payload["action_instances"]
        kind = row["event_type"]
        dose = float(row.get("dose", action["dose_reference"]))
        event_cursor = len(payload["event_ledger"])
        declared_unit = str(action.get("dose_unit") or "normalized")
        dose_unit = str(row.get("dose_unit") or declared_unit)
        if not math.isfinite(dose) or dose < 0.0:
            raise ValueError("action dose must be finite and non-negative")
        if dose_unit != declared_unit:
            raise ValueError(
                f"action dose unit mismatch for {action_id}: {dose_unit} != {declared_unit}"
            )
        occurred_at = float(row["occurred_time"]["upper"])
        state_time = float(payload["state_time"])
        retrospective_elapsed = max(0.0, state_time - occurred_at)
        source_id = str(row["provenance"]["source_result_id"])
        source_fingerprint = self._action_source_fingerprint(event)
        instance = instances.get(exposure_id)
        if kind == "ActionStarted":
            if instance is not None:
                # Exposure identity is course identity.  Re-use after stop or
                # completion would overwrite cumulative dose and lineage.
                raise ValueError(f"exposure_id already exists: {exposure_id}")

            matching_plan = None
            plans = payload.get("planned_action_records", [])
            exact_plan_index = next(
                (
                    index
                    for index, plan in enumerate(plans)
                    if str(plan.get("action_id") or "") == action_id
                    and plan.get("exposure_id") is not None
                    and str(plan.get("exposure_id")) == exposure_id
                ),
                None,
            )
            fallback_plan_index = next(
                (
                    index
                    for index, plan in enumerate(plans)
                    if str(plan.get("action_id") or "") == action_id
                    and plan.get("exposure_id") is None
                ),
                None,
            )
            plan_index = exact_plan_index if exact_plan_index is not None else fallback_plan_index
            if plan_index is not None:
                matching_plan = payload["planned_action_records"].pop(plan_index)
            source_result_ids = []
            lifecycle_event_ids = []
            planned_cursor = None
            if matching_plan is not None:
                planned_cursor = matching_plan.get("event_cursor")
                source_result_ids.append(str(matching_plan["source_result_id"]))
                lifecycle_event_ids.append(str(matching_plan["event_id"]))
            source_result_ids.append(source_id)
            lifecycle_event_ids.append(event.event_id)
            instances[exposure_id] = {
                "action_id": action_id,
                "status": "active",
                "planned_cursor": planned_cursor,
                "started_at": occurred_at,
                "definitely_active_by": float(row["occurred_time"]["upper"]),
                "started_cursor": event_cursor,
                "last_accounted_at": state_time,
                "last_lifecycle_occurred_at": occurred_at,
                "current_dose": dose,
                "dose_unit": dose_unit,
                # Availability governs knowledge, but cumulative exposure is a
                # property of what actually happened.  Backfill from the
                # conservative occurred-time upper bound to the current cut.
                "cumulative_exposure": dose * retrospective_elapsed,
                "stopped_at": None,
                "held_cursor": None,
                "stopped_cursor": None,
                "completed_cursor": None,
                "washout_remaining": 0.0,
                "lifecycle_event_ids": lifecycle_event_ids,
                "source_result_ids": source_result_ids,
                "dose_history": [
                    {
                        "event_cursor": event_cursor,
                        "operation": "start",
                        "value": dose,
                        "unit": dose_unit,
                        "route": row.get("route"),
                    }
                ],
                "response_summaries": [],
            }
            payload.setdefault("action_source_ledger", {})[source_id] = {
                "fingerprint": source_fingerprint,
                "event_type": kind,
                "action_id": action_id,
                "exposure_id": exposure_id,
            }
            return
        if instance is None or instance["action_id"] != action_id:
            raise ValueError(f"action lifecycle event lacks matching start: {exposure_id}")
        if row.get("dose_unit") is None:
            dose_unit = str(instance.get("dose_unit") or declared_unit)
        if dose_unit != str(instance.get("dose_unit") or declared_unit):
            raise ValueError(
                f"action dose unit changed within exposure {exposure_id}: "
                f"{dose_unit} != {instance.get('dose_unit') or declared_unit}"
            )
        prior_lifecycle_time = float(instance.get("last_lifecycle_occurred_at", instance["started_at"]))
        if occurred_at < prior_lifecycle_time:
            raise ValueError(
                f"action lifecycle occurrence regressed for {exposure_id}: "
                f"{occurred_at} < {prior_lifecycle_time}"
            )
        if kind == "ActionContinued":
            if instance["status"] not in {"active", "held"}:
                raise ValueError(f"cannot continue stopped/completed exposure: {exposure_id}")
            prior_status = instance["status"]
            old_dose = float(instance["current_dose"])
            instance["status"] = "active"
            instance["washout_remaining"] = 0.0
            if "dose" in row:
                instance["current_dose"] = dose
            # _advance_actions accounted the pre-event state through the
            # availability cut.  Correct the delayed interval to the factual
            # post-event administration.
            if prior_status == "held":
                instance["cumulative_exposure"] += float(instance["current_dose"]) * retrospective_elapsed
            else:
                instance["cumulative_exposure"] += (
                    float(instance["current_dose"]) - old_dose
                ) * retrospective_elapsed
            operation = "continue"
        elif kind == "ActionDoseChanged":
            if instance["status"] != "active":
                raise ValueError(f"cannot change stopped exposure: {exposure_id}")
            old_dose = float(instance["current_dose"])
            operation = "increase" if dose > old_dose else "decrease"
            instance["current_dose"] = dose
            instance["cumulative_exposure"] += (dose - old_dose) * retrospective_elapsed
        elif kind in {"ActionHeld", "ActionStopped"}:
            prior_status = instance["status"]
            if kind == "ActionHeld" and prior_status != "active":
                raise ValueError(f"exposure is not active: {exposure_id}")
            if kind == "ActionStopped" and prior_status not in {"active", "held"}:
                raise ValueError(f"exposure cannot be stopped from {prior_status}: {exposure_id}")
            instance["status"] = "held" if kind == "ActionHeld" else "stopped"
            instance["stopped_at"] = float(payload["state_time"])
            if kind == "ActionHeld":
                instance["held_cursor"] = event_cursor
            else:
                instance["stopped_cursor"] = event_cursor
            # A fresh hold/stop from active administration starts washout.
            # Converting an already-held exposure into a terminal stop must
            # not resurrect residual effect that has already decayed.
            if prior_status == "active":
                instance["washout_remaining"] = float(action.get("washout_steps", 0.0))
                instance["cumulative_exposure"] -= (
                    float(instance["current_dose"]) * retrospective_elapsed
                )
                instance["washout_remaining"] = max(
                    0.0,
                    float(instance["washout_remaining"]) - retrospective_elapsed,
                )
            operation = "hold" if kind == "ActionHeld" else "stop"
        elif kind == "ActionCompleted":
            if instance["status"] not in {"active", "held"}:
                raise ValueError(f"exposure cannot be completed from {instance['status']}: {exposure_id}")
            prior_status = instance["status"]
            instance["status"] = "completed"
            instance["stopped_at"] = float(payload["state_time"])
            instance["completed_cursor"] = event_cursor
            # Completion terminates the active administration, not the
            # declared residual effect.  The frozen architecture explicitly
            # requires both stopped and completed actions to traverse their
            # residual/washout phase.  Keep the terminal lifecycle identity
            # ("completed") while the orthogonal washout field decays.
            if prior_status == "active":
                instance["washout_remaining"] = float(action.get("washout_steps", 0.0))
                instance["cumulative_exposure"] -= (
                    float(instance["current_dose"]) * retrospective_elapsed
                )
                instance["washout_remaining"] = max(
                    0.0,
                    float(instance["washout_remaining"]) - retrospective_elapsed,
                )
            # The frozen dosePoint enum has no `complete`; termination is a
            # dose-history stop while completed_cursor/status retain the
            # semantically distinct completion lifecycle.
            operation = "stop"
        instance.setdefault("dose_history", []).append(
            {
                "event_cursor": event_cursor,
                "operation": operation,
                "value": None if operation in {"hold", "stop"} else float(instance["current_dose"]),
                "unit": str(instance.get("dose_unit") or dose_unit),
                "route": row.get("route"),
            }
        )
        instance["lifecycle_event_ids"].append(event.event_id)
        instance.setdefault("source_result_ids", []).append(source_id)
        instance["last_lifecycle_occurred_at"] = occurred_at
        payload.setdefault("action_source_ledger", {})[source_id] = {
            "fingerprint": source_fingerprint,
            "event_type": kind,
            "action_id": action_id,
            "exposure_id": exposure_id,
        }

    def diagnose(self, state: SharedPatientState) -> dict[str, Any]:
        self._assert_state(state)
        wire = state.to_dict()
        # Reconstruct the authoritative cold-state cache once.  Calling the
        # same deterministic decoder once per process is byte-equivalent but
        # quadratic in the size of a factorial wire (the generic 13-process
        # fixture is several MiB).
        internal = architecture_state_to_internal(self, state)
        top_joint = sorted(
            wire["active_process_posterior"]["joint_hypotheses"],
            key=lambda row: (-row["probability"], row["hypothesis_id"]),
        )[:10]
        marginals = {
            row["process_id"]: row["p_active"]
            for row in wire["active_process_posterior"]["process_marginals"]
            if row["process_id"] in self.processes
        }
        return {
            "consumed_state_hash": state.state_hash,
            "process_activation_marginals": dict(
                sorted(marginals.items(), key=lambda row: (-row[1], row[0]))
            ),
            "top_joint_hypotheses": top_joint,
            "per_process_modes": {
                row["process_id"]: {
                    mode["mode_id"]: mode["probability"] for mode in row["mode_posterior"]
                }
                for row in wire["local_states"]
            },
            "local_stratum_posteriors": {
                pid: copy.deepcopy(
                    internal["per_process"][pid]["stratum_posterior"]
                )
                for pid in self.process_ids
            },
            "epistemic": copy.deepcopy(wire["epistemic_residual"]),
            "abstention_status": wire["epistemic_residual"]["abstention_status"],
            "identifiability": next(
                row for row in wire["identifiability_claims"]
                if row["query_id"] == "diagnose.active_process_posterior"
            ),
            "inference_kind": (
                "exact_factorial_activation_plus_"
                "conditional_active_mean_field_local_state"
            ),
            "posterior_factorization": copy.deepcopy(
                self.spec["posterior_factorization"]
            ),
            "factorization_limitation": (
                "Activation configurations are propagated jointly, but each process-local "
                "coordinate/mode posterior is represented only as q(x,m|process active). "
                "Activation-local and cross-process local-state correlations excluded by the "
                "declared assumptions are OUT_OF_SCOPE."
            ),
        }

    def _effective_action_doses(
        self, payload: Mapping[str, Any], policy: Mapping[str, Any] | str
    ) -> tuple[
        dict[str, list[dict[str, float | str]]],
        float,
        str,
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        instances = copy.deepcopy(payload["action_instances"])
        lifecycle_trace: list[dict[str, Any]] = []

        allowed_string_policies = {"NO_NEW_ACTION", "CONTINUE_CURRENT"}
        allowed_policy_keys = {
            "policy_id",
            "start_actions",
            "continue_actions",
            "dose_changes",
            "hold_actions",
            "stop_actions",
            "complete_actions",
        }
        operation_keys = allowed_policy_keys.difference({"policy_id"})
        if isinstance(policy, str):
            if policy not in allowed_string_policies:
                raise ValueError(f"unsupported string policy: {policy}")
            policy_id = policy
            policy_row: Mapping[str, Any] = {}
        elif isinstance(policy, Mapping):
            policy_row = policy
            policy_id = str(policy.get("policy_id") or "")
            if not policy_id:
                raise ValueError("policy_id must be a non-empty string")
            unknown_keys = set(policy).difference(allowed_policy_keys)
            if unknown_keys:
                raise ValueError(f"policy contains unknown keys: {sorted(unknown_keys)}")
        else:
            raise ValueError("policy must be a mapping or a supported string policy")

        for key in operation_keys:
            value = policy_row.get(key, [])
            if not isinstance(value, list):
                raise ValueError(f"policy {key} must be a list")
            if any(not isinstance(item, Mapping) for item in value):
                raise ValueError(f"policy {key} entries must be mappings")
        allowed_item_keys = {
            "start_actions": {"action_id", "exposure_id", "dose", "dose_unit"},
            "continue_actions": {"action_id", "exposure_id", "dose", "dose_unit"},
            "dose_changes": {"action_id", "exposure_id", "dose", "dose_unit"},
            "hold_actions": {"action_id", "exposure_id"},
            "stop_actions": {"action_id", "exposure_id"},
            "complete_actions": {"action_id", "exposure_id"},
        }
        for key, allowed in allowed_item_keys.items():
            for item in policy_row.get(key, []):
                unknown = set(item).difference(allowed)
                if unknown:
                    raise ValueError(
                        f"policy {key} entry contains unknown keys: {sorted(unknown)}"
                    )

        def _dose(value: Any, *, context: str) -> float:
            try:
                parsed = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{context} dose must be numeric") from exc
            if not math.isfinite(parsed) or parsed < 0.0:
                raise ValueError(f"{context} dose must be finite and non-negative")
            return parsed

        touched_exposures: dict[str, str] = {}

        def _instance(item: Mapping[str, Any], operation: str) -> dict[str, Any]:
            exposure_id = str(item.get("exposure_id") or "")
            if not exposure_id:
                raise ValueError(f"policy {operation} requires exposure_id")
            if exposure_id not in instances:
                raise ValueError(f"policy {operation} references unknown exposure: {exposure_id}")
            prior_operation = touched_exposures.get(exposure_id)
            if prior_operation is not None:
                raise ValueError(
                    f"policy has conflicting operations for {exposure_id}: "
                    f"{prior_operation}, {operation}"
                )
            touched_exposures[exposure_id] = operation
            row = instances[exposure_id]
            supplied_action = item.get("action_id")
            if supplied_action is not None and supplied_action != row["action_id"]:
                raise ValueError(f"policy {operation} action/exposure mismatch: {exposure_id}")
            supplied_unit = item.get("dose_unit")
            expected_unit = str(row.get("dose_unit") or self.actions[row["action_id"]].get("dose_unit") or "normalized")
            if supplied_unit is not None and str(supplied_unit) != expected_unit:
                raise ValueError(
                    f"policy {operation} dose unit mismatch for {exposure_id}: "
                    f"{supplied_unit} != {expected_unit}"
                )
            return row

        for item in policy_row.get("continue_actions", []):
            row = _instance(item, "continue")
            if row["status"] not in {"active", "held"}:
                raise ValueError("policy can continue only an active or held exposure")
            row["status"] = "active"
            row["washout_remaining"] = 0.0
            if "dose" in item:
                row["current_dose"] = _dose(item["dose"], context="continue")
            lifecycle_trace.append({"operation": "continue", "exposure_id": item["exposure_id"], "action_id": row["action_id"]})
        for item in policy_row.get("dose_changes", []):
            row = _instance(item, "dose_change")
            if row["status"] != "active":
                raise ValueError("policy can change dose only for an active exposure")
            if "dose" not in item:
                raise ValueError("policy dose_change requires dose")
            row["current_dose"] = _dose(item["dose"], context="dose_change")
            lifecycle_trace.append({"operation": "dose_change", "exposure_id": item["exposure_id"], "action_id": row["action_id"], "dose": row["current_dose"]})
        for item in policy_row.get("hold_actions", []):
            row = _instance(item, "hold")
            if row["status"] != "active":
                raise ValueError("policy can hold only an active exposure")
            row["status"] = "held"
            row["washout_remaining"] = float(self.actions[row["action_id"]].get("washout_steps", 0.0))
            lifecycle_trace.append({"operation": "hold", "exposure_id": item["exposure_id"], "action_id": row["action_id"]})
        for item in policy_row.get("stop_actions", []):
            row = _instance(item, "stop")
            if row["status"] not in {"active", "held"}:
                raise ValueError("policy can stop only an active or held exposure")
            prior_status = row["status"]
            row["status"] = "stopped"
            if prior_status == "active":
                row["washout_remaining"] = float(self.actions[row["action_id"]].get("washout_steps", 0.0))
            lifecycle_trace.append({"operation": "stop", "exposure_id": item["exposure_id"], "action_id": row["action_id"]})
        for item in policy_row.get("complete_actions", []):
            row = _instance(item, "complete")
            if row["status"] not in {"active", "held"}:
                raise ValueError("policy can complete only an active or held exposure")
            prior_status = row["status"]
            row["status"] = "completed"
            if prior_status == "active":
                row["washout_remaining"] = float(
                    self.actions[row["action_id"]].get("washout_steps", 0.0)
                )
            lifecycle_trace.append(
                {
                    "operation": "complete",
                    "exposure_id": item["exposure_id"],
                    "action_id": row["action_id"],
                }
            )

        starts = list(policy_row.get("start_actions", []))
        cost = 0.0
        for start_index, start in enumerate(starts):
            action_id = str(start.get("action_id") or "")
            if action_id not in self.actions:
                raise ValueError(f"policy references unregistered action: {action_id}")
            action = self.actions[action_id]
            declared_unit = str(action.get("dose_unit") or "normalized")
            supplied_unit = str(start.get("dose_unit") or declared_unit)
            if supplied_unit != declared_unit:
                raise ValueError(
                    f"policy start dose unit mismatch for {action_id}: "
                    f"{supplied_unit} != {declared_unit}"
                )
            dose = _dose(
                start.get("dose", action["dose_reference"]),
                context=f"start {action_id}",
            )
            exposure_id = str(
                start.get("exposure_id")
                or f"policy:{policy_id}:{start_index}:{action_id}"
            )
            if exposure_id in instances:
                raise ValueError(f"policy start reuses exposure_id: {exposure_id}")
            if exposure_id in touched_exposures:
                raise ValueError(f"policy repeats exposure_id: {exposure_id}")
            touched_exposures[exposure_id] = "start"
            instances[exposure_id] = {
                "action_id": action_id,
                "status": "active",
                "current_dose": dose,
                "dose_unit": supplied_unit,
                "washout_remaining": 0.0,
            }
            lifecycle_trace.append(
                {
                    "operation": "start",
                    "exposure_id": exposure_id,
                    "action_id": action_id,
                    "dose": dose,
                    "dose_unit": supplied_unit,
                }
            )
            cost += float(action.get("action_cost", 0.0)) * (
                dose / float(action["dose_reference"])
            )

        exposures: dict[str, list[dict[str, float | str]]] = {}
        for instance in instances.values():
            action_id = instance["action_id"]
            action = self.actions.get(action_id)
            if action is None:
                continue
            if instance["status"] == "active":
                exposures.setdefault(action_id, []).append(
                    {"kind": "active", "dose": float(instance["current_dose"]), "washout_remaining": 0.0}
                )
            elif instance["status"] in {"held", "stopped", "completed"}:
                washout = float(action.get("washout_steps", 0.0))
                exposures.setdefault(action_id, []).append(
                    {
                        "kind": "washout",
                        "dose": float(instance["current_dose"]),
                        "washout_remaining": float(instance["washout_remaining"]),
                        "washout_steps": washout,
                    }
                )
        return exposures, cost, policy_id, lifecycle_trace, instances

    def _objective(self, coordinates: Mapping[str, Any], marginals: Mapping[str, float]) -> float:
        total = 0.0
        for pid, process in self.processes.items():
            activation = float(marginals[pid])
            for coord in process["coordinates"]:
                weight = float(coord.get("objective_weight", 0.0))
                if not weight:
                    continue
                low, high = map(float, coord["bounds"])
                value = float(coordinates[pid][coord["coordinate_id"]]["mean"])
                normalized = (value - low) / (high - low)
                total += activation * weight * normalized
        return total

    def _step_action_doses(
        self,
        exposures: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        elapsed_before_step: float,
    ) -> dict[str, float]:
        doses: dict[str, float] = {}
        for action_id, components in exposures.items():
            dose = 0.0
            for component in components:
                if component["kind"] == "washout":
                    washout_steps = float(component.get("washout_steps", 0.0))
                    remaining = max(
                        0.0,
                        float(component["washout_remaining"]) - elapsed_before_step,
                    )
                    fraction = remaining / washout_steps if washout_steps > 0.0 else 0.0
                else:
                    fraction = 1.0
                dose += float(component["dose"]) * fraction
            doses[str(action_id)] = dose
        return doses

    def _activation_dynamics_enabled(self) -> bool:
        """Whether the declared model can move factorial activation mass in time.

        The canonical wire stores the *current* joint belief, not a complete
        executable history.  The architecture validator may replay a static
        prior-plus-factor posterior only when this predicate is false.  Keep
        the predicate deliberately structural: even a currently zero dose or
        a currently inactive coupling remains a declared time-transition
        mechanism and therefore makes static replay unsound.
        """

        for process in self.processes.values():
            transition = process.get("activation_transition", {})
            if float(transition.get("enter_hazard_per_step", 0.0)) > 0.0:
                return True
            if float(transition.get("withdraw_hazard_per_step", 0.0)) > 0.0:
                return True
        if self.spec.get("process_activation_couplings"):
            return True
        return any(
            action.get("activation_effects")
            for action in self.actions.values()
        )

    def _local_activation_weight(self, process_id: str, marginal: float) -> float:
        """Gate an active-conditional local state only at numerically zero mass.

        Under ``conditional_active_mean_field_over_process_local_state`` the
        stored coordinate/mode posterior is ``q(x,m | process active)``.  Own
        drift and own action effects therefore act at full local scale whenever
        the conditioning event has representable mass.  Multiplying them by
        ``P(active)`` here would make the objective multiply activation twice.

        The local row is only a prior placeholder when active mass is at or
        below the declared factorization tolerance; it must not evolve there.
        Static legacy processes have no active/dormant transition semantics and
        retain their direct local-state behavior.
        """

        transition = self.processes[process_id].get("activation_transition", {})
        dynamic = any(
            float(transition.get(key, 0.0)) > 0.0
            for key in ("enter_hazard_per_step", "withdraw_hazard_per_step")
        )
        if not dynamic:
            return 1.0
        epsilon = max(
            _EPS,
            float(
                self.spec.get("posterior_factorization", {})
                .get("error_tolerance", {})
                .get("epsilon", self.spec["scope"]["tolerance"])
            ),
        )
        return 0.0 if float(marginal) <= epsilon else 1.0

    def _conditional_coactivation_weight(
        self,
        joint_hypotheses: Sequence[Mapping[str, Any]],
        source_process_id: str,
        target_process_id: str,
        *,
        target_marginal: float | None = None,
    ) -> float:
        """Return ``P(source active | target active)`` from the exact joint.

        Cross-process dynamics update a target-local conditional state.  The
        relevant exposure is therefore conditional coactivation, not the
        product of two marginal probabilities.  This preserves perfect
        coactivation and mutual exclusion represented by the factorial joint.
        """

        if source_process_id == target_process_id:
            return self._local_activation_weight(
                target_process_id,
                1.0 if target_marginal is None else float(target_marginal),
            )
        p_target = (
            float(target_marginal)
            if target_marginal is not None
            else math.fsum(
                float(row["probability"])
                for row in joint_hypotheses
                if target_process_id in row["active_processes"]
            )
        )
        epsilon = max(
            _EPS,
            float(
                self.spec.get("posterior_factorization", {})
                .get("error_tolerance", {})
                .get("epsilon", self.spec["scope"]["tolerance"])
            ),
        )
        if p_target <= epsilon:
            return 0.0
        p_joint = math.fsum(
            float(row["probability"])
            for row in joint_hypotheses
            if source_process_id in row["active_processes"]
            and target_process_id in row["active_processes"]
        )
        return _clamp(p_joint / p_target, 0.0, 1.0)

    def _advance_process_activation(
        self,
        joint_hypotheses: Sequence[Mapping[str, Any]],
        *,
        action_doses: Mapping[str, float],
        coordinates: Mapping[str, Mapping[str, Mapping[str, float]]],
        modes: Mapping[str, Mapping[str, float]],
        step_width: float,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Propagate the exact factorial mass table one declared time slice.

        Enter/withdraw parameters are continuous-time non-negative hazards;
        couplings and actions apply signed log-hazard shifts.  Every rate in a
        sub-step is evaluated from the same source configuration, then all
        single-bit probability fluxes are applied synchronously.  Adaptive
        Euler sub-steps keep outgoing mass non-negative.  This is invariant to
        process registry/ID ordering and costs O(K * N * 2^N), unlike the old
        simultaneous-target enumerator (O(4^N)).

        ``K`` is bounded fail-closed below.  Marginals are never evolved
        independently; the complete dependent joint is propagated.
        """

        accumulated: dict[tuple[tuple[str, ...], bool], float] = {
            (
                tuple(sorted(str(pid) for pid in row["active_processes"])),
                bool(row["unknown_active"]),
            ): float(row["probability"])
            for row in joint_hypotheses
        }
        before = {
            pid: sum(
                float(row["probability"])
                for row in joint_hypotheses
                if pid in row["active_processes"]
            )
            for pid in self.process_ids
        }
        activation_couplings = self.spec.get("process_activation_couplings", [])
        entered_flux = {pid: 0.0 for pid in self.process_ids}
        withdrawn_flux = {pid: 0.0 for pid in self.process_ids}

        def transition_rate(
            process_id: str,
            active_set: set[str],
        ) -> float:
                currently_active = process_id in active_set
                transition = self.processes[process_id].get("activation_transition", {})
                rate_key = (
                    "withdraw_hazard_per_step" if currently_active else "enter_hazard_per_step"
                )
                base_rate = float(transition.get(rate_key, 0.0))
                log_shift_terms: list[float] = []
                mode_shift_key = (
                    "withdraw_log_hazard_shift_by_mode"
                    if currently_active
                    else "enter_log_hazard_shift_by_mode"
                )
                log_shift_terms.append(sum(
                    float(modes[process_id].get(mode_id, 0.0)) * float(shift)
                    for mode_id, shift in transition.get(mode_shift_key, {}).items()
                ))
                coordinate_shift_key = (
                    "withdraw_log_hazard_shift_by_coordinate"
                    if currently_active
                    else "enter_log_hazard_shift_by_coordinate"
                )
                coordinate_specs = {
                    row["coordinate_id"]: row
                    for row in self.processes[process_id]["coordinates"]
                }
                for coordinate_id, shift in transition.get(
                    coordinate_shift_key, {}
                ).items():
                    low, high = map(float, coordinate_specs[coordinate_id]["bounds"])
                    mean = float(coordinates[process_id][coordinate_id]["mean"])
                    normalized = (mean - low) / (high - low)
                    log_shift_terms.append(normalized * float(shift))
                for coupling in sorted(
                    activation_couplings,
                    key=lambda row: str(row["coupling_id"]),
                ):
                    if coupling["target_process_id"] != process_id:
                        continue
                    if coupling["source_process_id"] not in active_set:
                        continue
                    shift_key = (
                        "withdraw_log_hazard_shift_per_step"
                        if currently_active
                        else "enter_log_hazard_shift_per_step"
                    )
                    log_shift_terms.append(float(coupling.get(shift_key, 0.0)))
                for action_id, dose in sorted(action_doses.items()):
                    if dose <= 0.0:
                        continue
                    action = self.actions[action_id]
                    dose_ratio = dose / float(action["dose_reference"])
                    for effect in action.get("activation_effects", []):
                        if effect["process_id"] != process_id:
                            continue
                        shift_key = (
                            "withdraw_log_hazard_shift_per_unit"
                            if currently_active
                            else "enter_log_hazard_shift_per_unit"
                        )
                        log_shift_terms.append(
                            float(effect.get(shift_key, 0.0)) * dose_ratio
                        )
                log_shift = math.fsum(log_shift_terms)
                # Calculate in log space.  A finite but very large declared
                # base hazard multiplied by exp(700) can overflow even though
                # both inputs passed construction validation.
                effective_rate = (
                    math.exp(
                        max(
                            -700.0,
                            min(700.0, math.log(base_rate) + log_shift),
                        )
                    )
                    if base_rate > 0.0
                    else 0.0
                )
                return effective_rate

        rate_table: dict[
            tuple[tuple[str, ...], bool], dict[str, float]
        ] = {}
        maximum_exit_rate = 0.0
        for key in sorted(accumulated):
            active_set = set(key[0])
            rates = {
                process_id: transition_rate(process_id, active_set)
                for process_id in self.process_ids
            }
            rate_table[key] = rates
            maximum_exit_rate = max(
                maximum_exit_rate,
                math.fsum(rates.values()),
            )

        # Synchronous explicit flux is non-negative when total outgoing mass
        # per sub-step is <= 0.25.  Refuse pathologically stiff declarations
        # rather than silently changing the kernel or exhausting the runtime.
        substeps = max(
            1,
            int(math.ceil(maximum_exit_rate * float(step_width) / 0.25)),
        )
        if substeps > 4096:
            raise ValueError(
                "process activation transition is too stiff for the declared runtime scope"
            )
        substep_width = float(step_width) / substeps
        for _ in range(substeps):
            contributions: dict[
                tuple[tuple[str, ...], bool], list[float]
            ] = {key: [] for key in accumulated}
            for key in sorted(accumulated):
                source_mass = float(accumulated[key])
                active_tuple, unknown_active = key
                active_set = set(active_tuple)
                rates = rate_table[key]
                outgoing_fraction = math.fsum(rates.values()) * substep_width
                if outgoing_fraction > 1.0 + 1e-12:
                    raise ValueError(
                        "process activation sub-step would create negative probability mass"
                    )
                contributions[key].append(
                    source_mass * max(0.0, 1.0 - outgoing_fraction)
                )
                for process_id in self.process_ids:
                    rate = rates[process_id]
                    if rate <= 0.0:
                        continue
                    moved_mass = source_mass * rate * substep_width
                    if process_id in active_set:
                        withdrawn_flux[process_id] += moved_mass
                    else:
                        entered_flux[process_id] += moved_mass
                    flipped_set = set(active_set)
                    if process_id in flipped_set:
                        flipped_set.remove(process_id)
                    else:
                        flipped_set.add(process_id)
                    flip_key = (tuple(sorted(flipped_set)), unknown_active)
                    contributions.setdefault(flip_key, []).append(
                        moved_mass
                    )
            accumulated = {
                key: math.fsum(sorted(values))
                for key, values in sorted(contributions.items())
            }
        total = sum(accumulated.values())
        if not math.isfinite(total) or total <= 0.0:
            raise ValueError("process activation transition lost all probability mass")
        rows = [
            {
                "configuration_id": self._configuration_id(active, unknown),
                "active_processes": list(active),
                "unknown_active": unknown,
                "probability": probability / total,
            }
            for (active, unknown), probability in sorted(accumulated.items())
        ]
        after = {
            pid: sum(
                float(row["probability"])
                for row in rows
                if pid in row["active_processes"]
            )
            for pid in self.process_ids
        }
        trace = [
            {
                "process_id": pid,
                "p_active_before": before[pid],
                "p_active_after": after[pid],
                "delta": after[pid] - before[pid],
                "entered_probability_flux": entered_flux[pid],
                "withdrawn_probability_flux": withdrawn_flux[pid],
                "step_width": step_width,
            }
            for pid in self.process_ids
            if (
                abs(after[pid] - before[pid]) > 1e-15
                or entered_flux[pid] > 1e-15
                or withdrawn_flux[pid] > 1e-15
            )
        ]
        return rows, trace

    def _apply_activation_local_semantics(
        self,
        process_id: str,
        coordinates: dict[str, dict[str, float]],
        modes: dict[str, float],
        activation_trace: Mapping[str, Any] | None,
        *,
        step_width: float,
    ) -> dict[str, Any]:
        """Propagate ``q(x,m | process active)`` through activation flux.

        The frozen wire stores one local posterior, so dynamic processes use a
        restricted conditional-active contract.  Exit is non-selective: the
        surviving active conditional is invariant under partial withdrawal.
        Entrants are always initialized from the declared prior and mixed with
        survivors by their active-mass share.  When active mass vanishes, the
        wire row becomes a prior placeholder; a later re-entry therefore also
        starts at the prior.  No unrepresented dormant memory is invented.
        """

        transition = self.processes[process_id].get("activation_transition", {})
        if not transition:
            return {
                "entry_policy": "CARRY",
                "exit_policy": "CARRY",
                "prior_blend_fraction": 0.0,
                "local_state_semantics": "static_local_state",
            }
        trace = activation_trace or {
            "p_active_before": 0.0,
            "p_active_after": 0.0,
            "entered_probability_flux": 0.0,
            "withdrawn_probability_flux": 0.0,
        }
        entry_policy = str(
            transition.get("entry_initialization", {}).get("policy", "CARRY")
        )
        exit_row = transition.get("exit_policy", {"policy": "CARRY"})
        exit_policy = str(exit_row.get("policy", "CARRY"))
        p_before = _clamp(float(trace.get("p_active_before", 0.0)), 0.0, 1.0)
        p_after = _clamp(float(trace.get("p_active_after", p_before)), 0.0, 1.0)
        entered = max(0.0, float(trace.get("entered_probability_flux", 0.0)))
        withdrawn = max(0.0, float(trace.get("withdrawn_probability_flux", 0.0)))

        process = self.processes[process_id]
        prior_coordinates = {
            row["coordinate_id"]: {
                "mean": float(row["prior_mean"]),
                "uncertainty": float(row.get("prior_uncertainty", 1.0)),
            }
            for row in process["coordinates"]
        }
        prior_modes = _normalize(
            {row["mode_id"]: float(row.get("prior", 0.0)) for row in process["modes"]}
        )

        def blend_to_prior(fraction: float) -> None:
            fraction = _clamp(float(fraction), 0.0, 1.0)
            if fraction <= 0.0:
                return
            for coordinate_id, target in prior_coordinates.items():
                current = coordinates[coordinate_id]
                current["mean"] = (
                    (1.0 - fraction) * float(current["mean"])
                    + fraction * float(target["mean"])
                )
                current["uncertainty"] = (
                    (1.0 - fraction) * float(current["uncertainty"])
                    + fraction * float(target["uncertainty"])
                )
            blended_modes = {
                mode_id: (
                    (1.0 - fraction) * float(modes.get(mode_id, 0.0))
                    + fraction * float(prior_modes.get(mode_id, 0.0))
                )
                for mode_id in prior_modes
            }
            modes.clear()
            modes.update(_normalize(blended_modes))

        dynamic = any(
            float(transition.get(key, 0.0)) > 0.0
            for key in ("enter_hazard_per_step", "withdraw_hazard_per_step")
        )
        if not dynamic:
            return {
                "entry_policy": entry_policy,
                "exit_policy": exit_policy,
                "prior_blend_fraction": 0.0,
                "local_state_semantics": "static_local_state",
            }

        # validate_model_spec enforces these exact policies for a dynamic
        # process.  Keep a runtime fail-closed guard for direct/private calls.
        if (
            entry_policy != "RESET_TO_PRIOR"
            or exit_policy != "SURVIVOR_CARRY_REENTRY_RESET"
        ):
            raise ValueError(
                f"{process_id}: dynamic activation requires RESET_TO_PRIOR entry and "
                "SURVIVOR_CARRY_REENTRY_RESET exit"
            )

        epsilon = max(
            _EPS,
            float(
                self.spec.get("posterior_factorization", {})
                .get("error_tolerance", {})
                .get("epsilon", self.spec["scope"]["tolerance"])
            ),
        )
        if p_after <= epsilon:
            blend_to_prior(1.0)
            combined_blend = 1.0
        else:
            surviving = max(0.0, p_before - withdrawn)
            active_mass = surviving + entered
            # Under non-selective transition hazards active_mass == p_after up
            # to numerical integration error.  Normalize the mixture by the
            # actual survivor+entrant decomposition rather than by a rounded
            # marginal so probability churn remains deterministic.
            fraction = (
                _clamp(entered / active_mass, 0.0, 1.0)
                if entered > 0.0 and active_mass > epsilon
                else 0.0
            )
            blend_to_prior(fraction)
            combined_blend = fraction
        return {
            "entry_policy": entry_policy,
            "exit_policy": exit_policy,
            "prior_blend_fraction": combined_blend,
            "local_state_semantics": "q(x,m|process_active)",
        }

    def _rollout_identifiability(
        self,
        state: SharedPatientState,
        policy: Mapping[str, Any] | str,
        collision_witnesses: Iterable[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        collision_rows = [copy.deepcopy(dict(row)) for row in collision_witnesses]
        claims = {row["query_id"]: row for row in state.payload["identifiability_claims"]}
        row = {} if isinstance(policy, str) else policy
        action_ids = {str(item["action_id"]) for item in row.get("start_actions", [])}
        internal = architecture_state_to_internal(self, state)
        # Natural history is conditional on factual ongoing/residual exposure.
        # A NO_NEW_ACTION policy therefore inherits the causal identification
        # status of every existing course that can still affect the trajectory;
        # it is not a treatment-free forecast merely because no new start was
        # requested.
        for exposure in internal.get("action_instances", {}).values():
            if exposure.get("status") in {"active", "held", "residual", "completed"}:
                action_ids.add(str(exposure["action_id"]))
        for key in (
            "continue_actions",
            "dose_changes",
            "hold_actions",
            "stop_actions",
            "complete_actions",
        ):
            for item in row.get(key, []):
                exposure = internal["action_instances"].get(str(item.get("exposure_id") or ""))
                if exposure is not None:
                    action_ids.add(str(exposure["action_id"]))
        selected_claims = [claims.get(f"action:{action_id}") for action_id in sorted(action_ids)]
        selected_claims = [row for row in selected_claims if row is not None]
        unresolved_collision_ids = sorted(
            {
                str(collision.get("new_action_id"))
                for collision in collision_rows
                if collision.get("status") == "COLLISION_WITNESS"
                and str(collision.get("new_action_id")) in action_ids
            }
        )
        if unresolved_collision_ids:
            selected_claims.append(
                {
                    "status": "UNIDENTIFIABLE",
                    "assumption_ids": ["behavioral-collision-unresolved"],
                    "compatible_world_ids": sorted(
                        {
                            world_id
                            for collision in collision_rows
                            if str(collision.get("new_action_id")) in unresolved_collision_ids
                            for witness in collision.get("witnesses", [])
                            for world_id in witness.get("world_ids", [])
                        }
                    ),
                    "reason": (
                        "Opposite action responses remain compatible under the current public state: "
                        + ", ".join(unresolved_collision_ids)
                    ),
                }
            )
        if not selected_claims:
            selected_claims = [claims["forecast.no_new_action"]]
        priority = {
            "IDENTIFIED_WITHIN_SCOPE": 0,
            "PARTIALLY_IDENTIFIED": 1,
            "UNIDENTIFIABLE": 2,
            "OUT_OF_SCOPE": 3,
        }
        status = max((row["status"] for row in selected_claims), key=priority.get)
        return {
            "status": status,
            "assumption_ids": sorted({item for row in selected_claims for item in row["assumption_ids"]}),
            "compatible_world_ids": sorted({item for row in selected_claims for item in row["compatible_world_ids"]}),
            "reasons": [row["reason"] for row in selected_claims],
            "identified_sets": [
                {
                    "query_id": row.get("query_id"),
                    "target_id": row.get("target_id"),
                    "status": row.get("status"),
                    "identified_set": copy.deepcopy(row.get("identified_set")),
                }
                for row in selected_claims
            ],
            "scope": copy.deepcopy(state.payload["scope"]),
            "uncertainty": copy.deepcopy(state.payload["epistemic_residual"]),
        }

    def rollout(
        self,
        state: SharedPatientState,
        policy: Mapping[str, Any] | str,
        *,
        horizon: int | float,
        collision_witnesses: Iterable[Mapping[str, Any]] = (),
        _allow_fractional_horizon: bool = False,
    ) -> dict[str, Any]:
        self._assert_state(state)
        if _allow_fractional_horizon:
            requested_horizon = float(horizon)
            if not math.isfinite(requested_horizon) or requested_horizon <= 0.0:
                raise ValueError("factual elapsed horizon must be positive and finite")
            declared = float(self.spec["scope"]["horizon"]["value"])
            if requested_horizon > declared + _EPS:
                raise ValueError("internal factual elapsed horizon exceeds frozen scope")
            full_steps = int(math.floor(requested_horizon))
            remainder = requested_horizon - full_steps
            step_widths = [1.0] * full_steps
            if remainder > _EPS:
                step_widths.append(remainder)
            steps = len(step_widths)
        else:
            steps, requested_horizon, out_of_scope = self._validate_horizon(horizon)
            if out_of_scope:
                return self._out_of_scope_rollout(state, policy, requested_horizon)
            assert steps is not None
            step_widths = [1.0] * steps
        wire = architecture_state_to_internal(self, state)
        coordinates = {
            pid: copy.deepcopy(wire["per_process"][pid]["coordinates"]) for pid in self.process_ids
        }
        initial_coordinates = copy.deepcopy(coordinates)
        modes = {
            pid: copy.deepcopy(wire["per_process"][pid]["mode_posterior"]) for pid in self.process_ids
        }
        joint_hypotheses = copy.deepcopy(wire["joint_hypotheses"])
        marginals = dict(wire["process_activation_marginals"])
        (
            exposures,
            action_cost,
            policy_id,
            lifecycle_trace,
            policy_instances,
        ) = self._effective_action_doses(wire, policy)
        trajectory: list[dict[str, Any]] = []
        topology_trace: list[dict[str, Any]] = []
        coupling_trace: list[dict[str, Any]] = []
        mode_coupling_trace: list[dict[str, Any]] = []
        mode_guard_trace: list[dict[str, Any]] = []
        action_dose_trace: list[dict[str, Any]] = []
        action_stratum_modifier_trace: list[dict[str, Any]] = []
        process_activation_trace: list[dict[str, Any]] = []
        topology = self.spec["topology"]
        planning_coupling = float(topology["planning_coupling"]) if self.topology_enabled else 0.0
        distance_scale = max(_EPS, float(topology["distance_scale"]))

        for step in range(1, steps + 1):
            step_width = step_widths[step - 1]
            elapsed_before_step = sum(step_widths[: step - 1])
            step_action_doses = self._step_action_doses(
                exposures,
                elapsed_before_step=elapsed_before_step,
            )
            activation_before = {
                pid: float(marginals[pid]) for pid in self.process_ids
            }
            joint_hypotheses, activation_rows = self._advance_process_activation(
                joint_hypotheses,
                action_doses=step_action_doses,
                coordinates=coordinates,
                modes=modes,
                step_width=step_width,
            )
            activation_by_process = {
                str(row["process_id"]): row for row in activation_rows
            }
            marginals = {
                pid: sum(
                    float(row["probability"])
                    for row in joint_hypotheses
                    if pid in row["active_processes"]
                )
                for pid in self.process_ids
            }
            marginals["NCF_UNMODELED_PROCESS"] = sum(
                float(row["probability"])
                for row in joint_hypotheses
                if row["unknown_active"]
            )
            for pid in self.process_ids:
                activation_context = activation_by_process.get(pid) or {
                    "process_id": pid,
                    "p_active_before": activation_before[pid],
                    "p_active_after": float(marginals[pid]),
                    "delta": float(marginals[pid]) - activation_before[pid],
                    "entered_probability_flux": 0.0,
                    "withdrawn_probability_flux": 0.0,
                    "step_width": step_width,
                }
                local_semantics = self._apply_activation_local_semantics(
                    pid,
                    coordinates[pid],
                    modes[pid],
                    activation_context,
                    step_width=step_width,
                )
                if pid in activation_by_process:
                    activation_by_process[pid].update(local_semantics)
            process_activation_trace.extend(
                {"step": step, **row} for row in activation_rows
            )
            deltas: dict[tuple[str, str], float] = {}
            for coupling_row in self.spec["mode_couplings"]:
                source_pid = coupling_row["source_process_id"]
                target_pid = coupling_row["target_process_id"]
                source_mode = coupling_row["source_mode_id"]
                target_mode = coupling_row["target_mode_id"]
                conditional_coactivation = self._conditional_coactivation_weight(
                    joint_hypotheses,
                    source_pid,
                    target_pid,
                    target_marginal=float(marginals[target_pid]),
                )
                log_shift = (
                    float(coupling_row["log_potential_per_step"])
                    * float(modes[source_pid][source_mode])
                    * conditional_coactivation
                    * step_width
                )
                target_weights = dict(modes[target_pid])
                target_weights[target_mode] *= math.exp(log_shift)
                modes[target_pid] = _normalize(target_weights)
                mode_coupling_trace.append(
                    {
                        "step": step,
                        "source_process_id": source_pid,
                        "source_mode_id": source_mode,
                        "target_process_id": target_pid,
                        "target_mode_id": target_mode,
                        "conditional_coactivation": conditional_coactivation,
                        "log_potential": log_shift,
                    }
                )
            for pid, process in self.processes.items():
                for mode in process["modes"]:
                    mode_mass = float(modes[pid].get(mode["mode_id"], 0.0))
                    for cid, drift in mode.get("coordinate_drift", {}).items():
                        deltas[(pid, cid)] = (
                            deltas.get((pid, cid), 0.0)
                            + mode_mass
                            * float(drift)
                            * self._local_activation_weight(
                                pid, float(marginals[pid])
                            )
                            * step_width
                        )

            for coupling_row in self.spec["process_couplings"]:
                source_pid = coupling_row["source_process_id"]
                target_pid = coupling_row["target_process_id"]
                source_cid = coupling_row["source_coordinate_id"]
                target_cid = coupling_row["target_coordinate_id"]
                source_value = float(coordinates[source_pid][source_cid]["mean"])
                conditional_coactivation = self._conditional_coactivation_weight(
                    joint_hypotheses,
                    source_pid,
                    target_pid,
                    target_marginal=float(marginals[target_pid]),
                )
                amount = (
                    float(coupling_row["strength_per_step"])
                    * source_value
                    * conditional_coactivation
                    * step_width
                )
                deltas[(target_pid, target_cid)] = deltas.get((target_pid, target_cid), 0.0) + amount
                coupling_trace.append(
                    {
                        "step": step,
                        "source_process_id": source_pid,
                        "target_process_id": target_pid,
                        "target_coordinate_id": target_cid,
                        "conditional_coactivation": conditional_coactivation,
                        "delta": amount,
                    }
                )

            for action_id, components in sorted(exposures.items()):
                action = self.actions[action_id]
                dose = step_action_doses[action_id]
                action_dose_trace.append({"step": step, "action_id": action_id, "effective_dose": dose})
                dose_ratio = dose / float(action["dose_reference"])
                for effect in action.get("effects", []):
                    source_pid = effect["process_id"]
                    source_cid = effect["coordinate_id"]
                    strata = self.processes[source_pid].get("strata") or [
                        {"stratum_id": f"stratum:{source_pid}", "action_effect_modifiers": {}}
                    ]
                    stratum_posterior = wire["per_process"][source_pid].get(
                        "stratum_posterior", {f"stratum:{source_pid}": 1.0}
                    )
                    stratum_modifier_components = []
                    modifier = 0.0
                    for row in strata:
                        stratum_id = row["stratum_id"]
                        local_modifier, witness_id, distance = self._stratum_action_modifier(
                            source_pid, stratum_id, action_id
                        )
                        posterior_weight = float(
                            stratum_posterior.get(stratum_id, 0.0)
                        )
                        modifier += posterior_weight * local_modifier
                        stratum_modifier_components.append(
                            {
                                "stratum_id": stratum_id,
                                "posterior_weight": posterior_weight,
                                "resolved_modifier": local_modifier,
                                "geometry_witness_stratum_id": witness_id,
                                "geometry_distance": distance,
                            }
                        )
                    direct_delta = (
                        float(effect["delta_per_unit_step"])
                        * dose_ratio
                        * modifier
                        * self._local_activation_weight(
                            source_pid, float(marginals[source_pid])
                        )
                        * step_width
                    )
                    action_stratum_modifier_trace.append(
                        {
                            "step": step,
                            "action_id": action_id,
                            "process_id": source_pid,
                            "coordinate_id": source_cid,
                            "posterior_weighted_modifier": modifier,
                            "stratum_components": stratum_modifier_components,
                        }
                    )
                    deltas[(source_pid, source_cid)] = deltas.get((source_pid, source_cid), 0.0) + direct_delta
                    if planning_coupling:
                        for bridge in topology.get("planning_bridges", []):
                            if (
                                bridge["source_process_id"] != source_pid
                                or bridge["source_coordinate_id"] != source_cid
                            ):
                                continue
                            target_pid = bridge["target_process_id"]
                            target_cid = bridge["target_coordinate_id"]
                            distance = self._branch_distance_unchecked(
                                source_pid, target_pid
                            )
                            if not math.isfinite(distance):
                                continue
                            weight = (
                                planning_coupling
                                * float(bridge.get("scale", 1.0))
                                * math.exp(-distance / distance_scale)
                            )
                            conditional_coactivation = self._conditional_coactivation_weight(
                                joint_hypotheses,
                                source_pid,
                                target_pid,
                                target_marginal=float(marginals[target_pid]),
                            )
                            spillover = direct_delta * weight * conditional_coactivation
                            deltas[(target_pid, target_cid)] = deltas.get((target_pid, target_cid), 0.0) + spillover
                            topology_trace.append(
                                {
                                    "step": step,
                                    "action_id": action_id,
                                    "source_process_id": source_pid,
                                    "target_process_id": target_pid,
                                    "target_coordinate_id": target_cid,
                                    "distance": distance,
                                    "weight": weight,
                                    "conditional_coactivation": conditional_coactivation,
                                    "delta": spillover,
                                }
                            )

            for (pid, cid), delta in sorted(deltas.items()):
                coord_spec = next(
                    row for row in self.processes[pid]["coordinates"] if row["coordinate_id"] == cid
                )
                low, high = map(float, coord_spec["bounds"])
                estimate = coordinates[pid][cid]
                estimate["mean"] = _clamp(float(estimate["mean"]) + delta, low, high)
            for pid in self.process_ids:
                if self._local_activation_weight(pid, float(marginals[pid])) > 0.0:
                    modes[pid], guard_rows = self._apply_mode_guards(
                        pid,
                        coordinates[pid],
                        modes[pid],
                        step_width=step_width,
                    )
                else:
                    guard_rows = []
                for guard_row in guard_rows:
                    mode_guard_trace.append({"step": step, "process_id": pid, **guard_row})
            trajectory.append(
                {
                    "step": step,
                    "step_width": step_width,
                    "expected_coordinate_burden": self._objective(coordinates, marginals),
                }
            )

        expected_burden = self._objective(coordinates, marginals)
        total_objective = expected_burden + action_cost
        identifiability = self._rollout_identifiability(
            state, policy, collision_witnesses
        )
        objective_id = str(self.spec["scope"]["outcome_ids"][0])
        decision_value_interval: dict[str, Any] | None = None
        if identifiability["status"] == "IDENTIFIED_WITHIN_SCOPE":
            decision_value_interval = {
                "lower": total_objective,
                "upper": total_objective,
                "unit": objective_id,
                "basis": "identified_point",
            }
        elif identifiability["status"] == "PARTIALLY_IDENTIFIED":
            numeric_sets = []
            invalid_set_reason: str | None = None
            for item in identifiability.get("identified_sets", []):
                bounds = item.get("identified_set")
                if not isinstance(bounds, Mapping):
                    numeric_sets = []
                    invalid_set_reason = "A partially identified claim has no numeric outcome set."
                    break
                lower, upper = bounds.get("lower"), bounds.get("upper")
                if lower is None or upper is None:
                    numeric_sets = []
                    invalid_set_reason = "A partially identified claim has an unbounded outcome set."
                    break
                lower_f, upper_f = float(lower), float(upper)
                if (
                    not math.isfinite(lower_f)
                    or not math.isfinite(upper_f)
                    or lower_f > upper_f
                ):
                    numeric_sets = []
                    invalid_set_reason = "A partially identified claim has invalid outcome bounds."
                    break
                if item.get("target_id") != objective_id or bounds.get("unit") != objective_id:
                    numeric_sets = []
                    invalid_set_reason = (
                        "A partially identified claim targets a different quantity or unit than "
                        f"the declared objective {objective_id}."
                    )
                    break
                numeric_sets.append((lower_f, upper_f))
            if numeric_sets and len(numeric_sets) != 1:
                # Marginal identified sets for several actions do not identify
                # the joint policy value.  A joint compatible-world outcome
                # model is required before such bounds can authorize a choice.
                numeric_sets = []
                invalid_set_reason = (
                    "Several marginal action outcome sets do not identify the combined policy value."
                )
            if numeric_sets:
                lower_f, upper_f = numeric_sets[0]
                lower_with_cost = lower_f + action_cost
                upper_with_cost = upper_f + action_cost
                if not (
                    lower_with_cost - _EPS
                    <= total_objective
                    <= upper_with_cost + _EPS
                ):
                    invalid_set_reason = (
                        "The declared-model policy objective lies outside the claimed complete "
                        "post-policy outcome set; effect bounds cannot be used as outcome bounds."
                    )
                else:
                    decision_value_interval = {
                        "lower": lower_with_cost,
                        "upper": upper_with_cost,
                        "unit": objective_id,
                        "basis": "externally_supplied_complete_outcome_identified_set",
                    }
            if invalid_set_reason is not None:
                identifiability["status"] = "UNIDENTIFIABLE"
                identifiability.setdefault("reasons", []).append(invalid_set_reason)
                identifiability.setdefault("assumption_ids", []).append(
                    "complete-post-policy-outcome-set-required"
                )
                identifiability["assumption_ids"] = sorted(
                    set(identifiability["assumption_ids"])
                )
        continuous_support = []
        direction_support = []
        for pid in self.process_ids:
            coordinate_specs = {
                row["coordinate_id"]: row for row in self.processes[pid]["coordinates"]
            }
            for cid, estimate in sorted(coordinates[pid].items()):
                low, high = map(float, coordinate_specs[cid]["bounds"])
                scale = max(1e-6, float(estimate["uncertainty"]) * (high - low) / 2.0)
                continuous_support.append(
                    {
                        "process_id": pid,
                        "coordinate_id": cid,
                        "family": "truncated_normal",
                        "mean": float(estimate["mean"]),
                        "scale": scale,
                        "support": {"lower": low, "upper": high},
                    }
                )
                delta = float(estimate["mean"]) - float(initial_coordinates[pid][cid]["mean"])
                leading = "increase" if delta > 1e-12 else "decrease" if delta < -1e-12 else "stable"
                probabilities = {"increase": 0.1, "decrease": 0.1, "stable": 0.1}
                probabilities[leading] = 0.8
                direction_support.append(
                    {
                        "process_id": pid,
                        "coordinate_id": cid,
                        "probabilities": probabilities,
                    }
                )
        predictive_support = {
            "schema_version": "ncf.predictive-support.v1",
            "scoring_rule_id": "truncated-normal-plus-categorical-log-score-v1",
            "continuous_coordinates": continuous_support,
            "coordinate_directions": direction_support,
            "process_activation": [
                {"process_id": pid, "p_active": float(marginals[pid])}
                for pid in self.process_ids
            ],
            "local_modes": [
                {"process_id": pid, "probabilities": copy.deepcopy(modes[pid])}
                for pid in self.process_ids
            ],
        }
        final_action_lifecycle = []
        for exposure_id, instance in sorted(policy_instances.items()):
            status = str(instance["status"])
            remaining = float(instance.get("washout_remaining", 0.0))
            if status in {"held", "stopped", "completed"}:
                remaining = max(0.0, remaining - steps)
            final_action_lifecycle.append(
                {
                    "exposure_id": exposure_id,
                    "action_id": str(instance["action_id"]),
                    "status": status,
                    "dose": float(instance.get("current_dose", 0.0)),
                    "dose_unit": str(instance.get("dose_unit") or "normalized"),
                    "washout_remaining": remaining,
                }
            )
        return {
            "consumed_state_hash": state.state_hash,
            "policy_id": policy_id,
            "status": identifiability["status"],
            "identifiability": identifiability,
            "trajectory": trajectory,
            "final_coordinates": coordinates,
            "final_mode_posteriors": modes,
            "final_joint_hypotheses": joint_hypotheses,
            "expected_coordinate_burden": expected_burden,
            "action_cost": action_cost,
            "total_objective": total_objective,
            "decision_value_interval": decision_value_interval,
            "topology_effect_trace": topology_trace,
            "process_coupling_trace": coupling_trace,
            "mode_coupling_trace": mode_coupling_trace,
            "mode_guard_trace": mode_guard_trace,
            "action_effective_dose_trace": action_dose_trace,
            "action_stratum_modifier_trace": action_stratum_modifier_trace,
            "process_activation_trace": process_activation_trace,
            "policy_lifecycle_trace": lifecycle_trace,
            "final_action_lifecycle": final_action_lifecycle,
            "predictive_support": predictive_support,
            "posterior_factorization": copy.deepcopy(
                self.spec["posterior_factorization"]
            ),
            "factorization_limitation": (
                "Forecast local states use conditional-active mean-field propagation; "
                "unsupported activation-local and cross-process local-state correlations "
                "are OUT_OF_SCOPE."
            ),
        }

    @staticmethod
    def score_predictive_support(
        forecast: Mapping[str, Any],
        realized: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Apply the frozen continuous/discrete support log score."""

        support = forecast.get("predictive_support")
        if not isinstance(support, Mapping) or support.get("schema_version") != "ncf.predictive-support.v1":
            raise ValueError("forecast lacks ncf.predictive-support.v1")
        components: list[dict[str, Any]] = []
        zero_or_undefined: list[str] = []
        missing_components: list[str] = []

        coordinates = realized.get("coordinates", {})
        for row in support["continuous_coordinates"]:
            pid, cid = row["process_id"], row["coordinate_id"]
            component_id = f"coordinate:{pid}:{cid}"
            if pid not in coordinates or cid not in coordinates[pid]:
                missing_components.append(component_id)
                continue
            value = float(coordinates[pid][cid])
            low, high = float(row["support"]["lower"]), float(row["support"]["upper"])
            if not math.isfinite(value) or value < low or value > high:
                zero_or_undefined.append(component_id)
                continue
            mean, scale = float(row["mean"]), float(row["scale"])
            z = (value - mean) / scale
            alpha = (low - mean) / (scale * math.sqrt(2.0))
            beta = (high - mean) / (scale * math.sqrt(2.0))
            normalization = max(_EPS, 0.5 * (math.erf(beta) - math.erf(alpha)))
            log_score = -0.5 * math.log(2.0 * math.pi * scale * scale) - 0.5 * z * z - math.log(normalization)
            components.append({"component_id": component_id, "log_score": log_score})

        def score_categorical(
            rows: Iterable[Mapping[str, Any]],
            observations: Mapping[str, Any],
            *,
            value_key: str,
        ) -> None:
            for row in rows:
                pid = str(row["process_id"])
                cid = str(row.get("coordinate_id") or "")
                observed = observations.get(pid)
                if cid:
                    if not isinstance(observed, Mapping):
                        missing_components.append(
                            f"{value_key}:{pid}:{cid}"
                        )
                        continue
                    observed = observed.get(cid)
                if observed is None:
                    missing_components.append(
                        f"{value_key}:{pid}" + (f":{cid}" if cid else "")
                    )
                    continue
                probabilities = row["probabilities"]
                key = str(observed)
                component_id = f"{value_key}:{pid}" + (f":{cid}" if cid else "")
                probability = float(probabilities.get(key, 0.0))
                if not math.isfinite(probability) or probability <= 0.0:
                    zero_or_undefined.append(component_id)
                else:
                    components.append({"component_id": component_id, "log_score": math.log(probability)})

        score_categorical(
            support["coordinate_directions"],
            realized.get("coordinate_directions", {}),
            value_key="direction",
        )
        score_categorical(
            support["local_modes"],
            realized.get("modes", {}),
            value_key="mode",
        )
        activation = realized.get("process_activation", {})
        for row in support["process_activation"]:
            pid = str(row["process_id"])
            if pid not in activation:
                missing_components.append(f"activation:{pid}")
                continue
            p_active = min(1.0 - _EPS, max(_EPS, float(row["p_active"])))
            probability = p_active if bool(activation[pid]) else 1.0 - p_active
            components.append(
                {"component_id": f"activation:{pid}", "log_score": math.log(probability)}
            )
        unsupported = sorted(set(zero_or_undefined) | set(missing_components))
        return {
            "scoring_rule_id": support["scoring_rule_id"],
            "component_scores": components,
            "aggregate_log_score": sum(row["log_score"] for row in components) if components else None,
            "required_component_count": (
                len(support["continuous_coordinates"])
                + len(support["coordinate_directions"])
                + len(support["local_modes"])
                + len(support["process_activation"])
            ),
            "observed_component_count": len(components) + len(set(zero_or_undefined)),
            "missing_component_ids": sorted(set(missing_components)),
            "zero_or_undefined_support_ids": unsupported,
            "status": "ZERO_OR_UNDEFINED_SUPPORT" if unsupported else "SUPPORTED",
        }

    def forecast(self, state: SharedPatientState, *, horizon: int | float) -> dict[str, Any]:
        """Natural-history forecast through the same rollout core."""

        result = self.rollout(state, {"policy_id": "NO_NEW_ACTION", "start_actions": []}, horizon=horizon)
        result["inference_kind"] = "natural_history_with_existing_exposures"
        return result

    def plan(
        self,
        state: SharedPatientState,
        policies: Iterable[Mapping[str, Any] | str],
        *,
        horizon: int | float,
        collision_witnesses: Iterable[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        self._assert_state(state)
        _, requested_horizon, out_of_scope = self._validate_horizon(horizon)
        policy_rows = list(policies)
        if out_of_scope:
            rollouts = [
                self._out_of_scope_rollout(state, policy, requested_horizon)
                for policy in policy_rows
            ]
            return {
                "consumed_state_hash": state.state_hash,
                "status": "OUT_OF_SCOPE",
                "execution_status": "NOT_EXECUTED_OUT_OF_SCOPE",
                "requested_horizon": {
                    "value": requested_horizon,
                    "unit": str(self.spec["scope"]["horizon"]["unit"]),
                },
                "selected_policy_id": None,
                "policy_rollouts": rollouts,
                "identifiability": self._out_of_scope_identifiability(
                    state, requested_horizon
                ),
                "selection_rule": "no_selection_outside_frozen_scope",
                "excluded_policy_ids": sorted(row["policy_id"] for row in rollouts),
            }
        collision_rows = [copy.deepcopy(dict(row)) for row in collision_witnesses]
        rollouts = [
            self.rollout(
                state,
                policy,
                horizon=horizon,
                collision_witnesses=collision_rows,
            )
            for policy in policy_rows
        ]
        epistemic = state.payload["epistemic_residual"]
        operative_ood = bool(epistemic.get("unexplained_observations")) or str(
            epistemic.get("abstention_status")
        ) in {"abstain_unmodeled", "abstain_unidentifiable", "out_of_scope"}
        selectable = [
            row
            for row in rollouts
            if row["status"] not in {"UNIDENTIFIABLE", "OUT_OF_SCOPE"}
            and row.get("decision_value_interval") is not None
        ]
        selected = None
        selection_rule = "typed_abstention_no_robustly_dominant_policy"
        if not operative_ood and selectable:
            # Point estimates may rank declared-model simulations, but cannot
            # authorize a partially identified action.  Select only when the
            # propagated value set robustly dominates every other eligible
            # policy.  Fully identified point ties are harmless and use the
            # stable policy id tiebreaker.
            if all(row["status"] == "IDENTIFIED_WITHIN_SCOPE" for row in selectable):
                selected = min(
                    selectable,
                    key=lambda row: (row["decision_value_interval"]["upper"], row["policy_id"]),
                )
                selection_rule = "minimize_identified_decision_value"
            elif len(selectable) == 1:
                # A singleton partially identified action does not dominate
                # anything merely because the caller omitted alternatives.
                # The conservative no-new-action policy may stand alone, but
                # an operative action needs either full identification or a
                # robust comparison against another identified value set.
                if not selectable[0].get("policy_lifecycle_trace"):
                    selected = selectable[0]
                    selection_rule = "only_conservative_policy_with_bounded_value"
            else:
                robust = [
                    candidate
                    for candidate in selectable
                    if all(
                        candidate["decision_value_interval"]["upper"]
                        < competitor["decision_value_interval"]["lower"]
                        for competitor in selectable
                        if competitor is not candidate
                    )
                ]
                if len(robust) == 1:
                    selected = robust[0]
                    selection_rule = "robust_interval_dominance"
        if operative_ood:
            selection_rule = "typed_abstention_unmodeled_public_evidence"
        return {
            "consumed_state_hash": state.state_hash,
            "selected_policy_id": selected["policy_id"] if selected else None,
            "execution_status": (
                "SELECTED" if selected
                else "ABSTAIN_UNMODELED" if operative_ood
                else "ABSTAIN_NO_ROBUST_DOMINANCE"
            ),
            "policy_rollouts": rollouts,
            "identifiability": copy.deepcopy(selected["identifiability"]) if selected else {
                "status": "UNIDENTIFIABLE",
                "assumption_ids": sorted({
                    item
                    for rollout in rollouts
                    for item in rollout["identifiability"]["assumption_ids"]
                }),
                "compatible_world_ids": sorted({
                    item
                    for rollout in rollouts
                    for item in rollout["identifiability"]["compatible_world_ids"]
                }),
                "reasons": (
                    ["All supplied policies were excluded as unidentifiable or out of scope."]
                    if rollouts else ["No policy was supplied."]
                ),
                "scope": copy.deepcopy(state.payload["scope"]),
                "uncertainty": copy.deepcopy(state.payload["epistemic_residual"]),
            },
            "selection_rule": selection_rule,
            "excluded_policy_ids": sorted(
                row["policy_id"] for row in rollouts
                if row["status"] in {"UNIDENTIFIABLE", "OUT_OF_SCOPE"}
                or row.get("decision_value_interval") is None
            ),
        }


__all__ = ["RuntimeV2", "log_likelihood"]
