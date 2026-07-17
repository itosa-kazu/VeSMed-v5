"""W19 rare-contraindication public-belief vertical slice."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any

from .canonical import ProtocolViolation, canonical_json_bytes, digest_json
from .candidate_protocol import (
    DiagnoseResponse,
    DiagnosisResult,
    Operation,
    ResultStatus,
    RolloutResponse,
    RolloutResult,
)
from .schema import (
    ActionPlan,
    CandidateVisibleEvent,
    DiagnosisQuery,
    EventKind,
    PlanKind,
    RolloutQuery,
    VisibleDelta,
    event_sort_key,
)
from .state import SealedState, StateClass, StatePayload, seal_state
from .true_state_probe import TrueStateHeadExecution
from .worlds.base import PrivateEpisode
from .worlds.w19 import W19World, _truncated_uniform_gaussian_moments


_STATE_PROTOCOL = "ucm-phase2-public-tail-state-w19/1"
_STATE_SCHEMA = "ucm-phase2-public-tail-state-w19-state/1"


@dataclass(frozen=True, slots=True)
class W19TailProbeManifest:
    probe_id: str = "phase2-public-tail-upper-bound-w19"
    baseline_id: str = "B01"
    world_slot: str = "W19"
    privileged: bool = True
    eligibility: str = "upper_bound_only"
    freeze_grade: bool = False

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-true-state-probe-manifest/1",
            "probe_id": self.probe_id,
            "baseline_id": self.baseline_id,
            "world_slot": self.world_slot,
            "privileged": self.privileged,
            "eligibility": self.eligibility,
            "freeze_grade": self.freeze_grade,
            "state_schema": _STATE_SCHEMA,
            "state_evidence": "public-sufficient-statistics-only",
            "private_tail_policy": "excluded",
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


class W19PublicTailProbe:
    """Shared public belief that retains rare catastrophic tail mass."""

    def __init__(self, world: W19World | None = None) -> None:
        self.world = world or W19World()
        self.manifest = W19TailProbeManifest()
        self._candidate_bundle_digest = self.manifest.digest
        self._model_digest = digest_json(
            {
                "protocol": "ucm-public-tail-model-binding/1",
                "world_slot": "W19",
                "posterior": "truncated-normal-plus-marker-bayes",
                "rollout": "W19World.public_belief_counterfactual",
                "private_tail_policy": "excluded",
            }
        )
        self._scope_digest = digest_json(
            {
                "protocol": "ucm-true-state-scope/1",
                "world_slot": "W19",
                "catalog_digest": self.world.catalog.digest,
            }
        )

    def _representation(
        self,
        *,
        x_observation_count: int,
        x_observation_mean: float,
        marker: int | None,
        as_of_available_at: int,
    ) -> dict[str, Any]:
        if type(x_observation_count) is not int or x_observation_count <= 0:
            raise ProtocolViolation("W19 state requires a positive x count")
        if (
            type(x_observation_mean) not in {int, float}
            or not math.isfinite(float(x_observation_mean))
        ):
            raise ProtocolViolation("W19 state x mean must be finite")
        if marker not in {None, 0, 1}:
            raise ProtocolViolation("W19 marker must be null, zero or one")
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W19 public cut must be an integer")
        x_mean, x_variance, evidence = _truncated_uniform_gaussian_moments(
            (float(x_observation_mean),) * x_observation_count
        )
        p_tail = self.world._marker_posterior(marker)
        return {
            "protocol": _STATE_PROTOCOL,
            "world_slot": "W19",
            "as_of_available_at": as_of_available_at,
            "x_observation_count": x_observation_count,
            "x_observation_mean": float(x_observation_mean),
            "latest_marker": marker,
            "public_belief": {
                "C0": 1.0 - p_tail,
                "C1": p_tail,
                "x_mean": x_mean,
                "x_variance": x_variance,
                "x_evidence": evidence,
            },
        }

    @staticmethod
    def _payload(value: dict[str, Any]) -> StatePayload:
        return StatePayload.from_json(
            value,
            schema_version=_STATE_SCHEMA,
            state_class=StateClass.DYNAMIC_SHARED,
        )

    def _decode(self, state: SealedState) -> dict[str, Any]:
        if type(state) is not SealedState:
            raise ProtocolViolation("W19 query requires SealedState")
        payload = state.candidate_input.payload
        if (
            payload.codec != "canonical-json-v1"
            or payload.schema_version != _STATE_SCHEMA
            or payload.state_class is not StateClass.DYNAMIC_SHARED
        ):
            raise ProtocolViolation("W19 tail payload identity mismatch")
        try:
            value = json.loads(payload.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("W19 tail payload is invalid") from exc
        expected = {
            "protocol",
            "world_slot",
            "as_of_available_at",
            "x_observation_count",
            "x_observation_mean",
            "latest_marker",
            "public_belief",
        }
        if type(value) is not dict or set(value) != expected:
            raise ProtocolViolation("W19 tail payload is not closed")
        if value.get("protocol") != _STATE_PROTOCOL or value.get("world_slot") != "W19":
            raise ProtocolViolation("W19 tail state protocol mismatch")
        normalized = self._representation(
            x_observation_count=value["x_observation_count"],
            x_observation_mean=value["x_observation_mean"],
            marker=value["latest_marker"],
            as_of_available_at=value["as_of_available_at"],
        )
        if value != normalized:
            raise ProtocolViolation("W19 tail state contains noncanonical claims")
        return normalized

    def _verify(self, state: SealedState) -> dict[str, Any]:
        value = self._decode(state)
        record = state.record
        if (
            record.candidate_bundle_digest != self._candidate_bundle_digest
            or record.model_digest != self._model_digest
            or record.scope_digest != self._scope_digest
            or record.catalog_digest != self.world.catalog.digest
            or record.as_of_available_at != value["as_of_available_at"]
        ):
            raise ProtocolViolation("W19 tail seal binding mismatch")
        return value

    def _seal(
        self,
        value: dict[str, Any],
        *,
        operation: str,
        parent_state_hash: str | None = None,
        delta_digest: str | None = None,
    ) -> SealedState:
        return seal_state(
            self._payload(value),
            candidate_bundle_digest=self._candidate_bundle_digest,
            model_digest=self._model_digest,
            scope_digest=self._scope_digest,
            catalog_digest=self.world.catalog.digest,
            as_of_available_at=value["as_of_available_at"],
            operation=operation,
            parent_state_hash=parent_state_hash,
            delta_digest=delta_digest,
        )

    @staticmethod
    def _public_statistics(episode: PrivateEpisode) -> tuple[int, float, int | None]:
        observations: list[float] = []
        marker: int | None = None
        for event in episode.public_history.events:
            if event.kind is not EventKind.OBSERVATION_AVAILABLE:
                continue
            channel = event.payload.get("channel_id")
            if channel == "obs_0":
                observations.append(float(event.payload["value"]))
            elif channel == "obs_1":
                marker = int(event.payload["value"])
        if not observations:
            raise ProtocolViolation("W19 initialization requires obs_0")
        return len(observations), math.fsum(observations) / len(observations), marker

    def initialize_public_episode(self, episode: PrivateEpisode) -> SealedState:
        if type(episode) is not PrivateEpisode:
            raise ProtocolViolation("W19 initializer requires PrivateEpisode")
        if episode.environment_key != self.world.environment_key:
            raise ProtocolViolation("W19 episode belongs to another world")
        count, mean, marker = self._public_statistics(episode)
        return self._seal(
            self._representation(
                x_observation_count=count,
                x_observation_mean=mean,
                marker=marker,
                as_of_available_at=episode.public_history.as_of_available_at,
            ),
            operation="initialize",
        )

    def update_public(
        self,
        state: SealedState,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> SealedState:
        del inference_seed
        prior = self._verify(state)
        if type(delta) is not VisibleDelta or delta.advance_to <= prior["as_of_available_at"]:
            raise ProtocolViolation("W19 update must advance the availability cut")
        new_x: list[float] = []
        marker = prior["latest_marker"]
        for event in delta.events:
            if event.kind is not EventKind.OBSERVATION_AVAILABLE:
                continue
            channel = event.payload.get("channel_id")
            if channel == "obs_0":
                new_x.append(float(event.payload["value"]))
            elif channel == "obs_1":
                marker = int(event.payload["value"])
        if not new_x and marker == prior["latest_marker"]:
            raise ProtocolViolation("W19 update contains no new belief evidence")
        previous_count = int(prior["x_observation_count"])
        count = previous_count + len(new_x)
        mean = (
            previous_count * float(prior["x_observation_mean"])
            + math.fsum(new_x)
        ) / count
        value = self._representation(
            x_observation_count=count,
            x_observation_mean=mean,
            marker=marker,
            as_of_available_at=delta.advance_to,
        )
        return self._seal(
            value,
            operation="update",
            parent_state_hash=state.record.state_hash,
            delta_digest=digest_json(delta.to_wire()),
        )

    def diagnose(
        self, state: SealedState, query: DiagnosisQuery, *, query_seed: int
    ) -> TrueStateHeadExecution:
        del query_seed
        value = self._verify(state)
        if query.label_catalog != self.world.catalog.diagnostic_labels:
            raise ProtocolViolation("W19 diagnosis label catalog mismatch")
        belief = value["public_belief"]
        response = DiagnoseResponse(
            DiagnosisResult(
                ResultStatus.OK,
                {"C0": float(belief["C0"]), "C1": float(belief["C1"])},
                {
                    "baseline_id": "B01",
                    "eligibility": "upper_bound_only",
                    "public_evidence_only": True,
                    "tail_probability": float(belief["C1"]),
                },
            )
        )
        return TrueStateHeadExecution(
            Operation.DIAGNOSE,
            state.record.state_hash,
            digest_json(query.to_wire()),
            response,
            self.manifest.digest,
        )

    def rollout(
        self, state: SealedState, query: RolloutQuery, *, query_seed: int
    ) -> TrueStateHeadExecution:
        del query_seed
        value = self._verify(state)
        if query.requested_observables != ("obs_0",):
            raise ProtocolViolation("W19 rollout supports obs_0")
        oracle = self.world.public_belief_counterfactual(
            dict(value["public_belief"]), query.plan, query.horizon
        )
        components = oracle.observation_distribution["components"]
        outcome = oracle.outcome_distribution
        hard_gate = bool(outcome["catastrophic_hard_gate_exposed"])
        response = RolloutResponse(
            RolloutResult(
                ResultStatus.OK,
                observable_predictions={
                    "obs_0": {
                        "family": "two-component-linear-gaussian",
                        "components": [
                            {
                                "class": component["class"],
                                "weight": float(component["weight"]),
                                "means": [
                                    float(step["mean"])
                                    for step in component["steps"]
                                ],
                                "variances": [
                                    float(step["variance"])
                                    for step in component["steps"]
                                ],
                            }
                            for component in components
                        ],
                    }
                },
                utility_prediction={
                    "family": "tail-aware",
                    "expected": float(outcome["expected_utility"]),
                    "worst_component": float(outcome["worst_component_utility"]),
                    "lower_tail_cvar_95": float(outcome["lower_tail_cvar_95"]),
                    "tail_only_regret": float(outcome["tail_only_regret"]),
                    "catastrophic_action_probability": float(
                        outcome["catastrophic_action_probability"]
                    ),
                    "recommendation": "contraindicated" if hard_gate else "eligible",
                },
                metadata={
                    "baseline_id": "B01",
                    "eligibility": "upper_bound_only",
                    "public_evidence_only": True,
                    "tail_probability": float(value["public_belief"]["C1"]),
                    "catastrophic_hard_gate_exposed": hard_gate,
                },
            )
        )
        return TrueStateHeadExecution(
            Operation.ROLLOUT,
            state.record.state_hash,
            digest_json(query.to_wire()),
            response,
            self.manifest.digest,
        )


def _policy(world: W19World, action: str | None) -> ActionPlan:
    if action is None:
        return next(
            policy
            for policy in world.policy_set(4)
            if policy.kind is PlanKind.NO_NEW_ACTION
        )
    return next(
        policy
        for policy in world.policy_set(4)
        if len(policy.actions) == 1 and policy.actions[0].action_id == action
    )


def _marker_response_delta() -> VisibleDelta:
    events = (
        CandidateVisibleEvent(
            kind=EventKind.PERFORMED_TREATMENT,
            occurred_at=1,
            available_at=1,
            event_uid="w19-safe-a2",
            payload={"action_id": "A2", "parameters": {}},
            collected_at=None,
        ),
        CandidateVisibleEvent(
            kind=EventKind.OBSERVATION_AVAILABLE,
            occurred_at=1,
            available_at=1,
            event_uid="w19-response-x",
            payload={"channel_id": "obs_0", "value": 0.62},
            collected_at=1,
        ),
        CandidateVisibleEvent(
            kind=EventKind.OBSERVATION_AVAILABLE,
            occurred_at=0,
            available_at=1,
            event_uid="w19-marker-positive",
            payload={"channel_id": "obs_1", "value": 1},
            collected_at=0,
        ),
    )
    return VisibleDelta(1, tuple(sorted(events, key=event_sort_key)))


def run_w19_tail_slice() -> dict[str, Any]:
    world = W19World()
    probe = W19PublicTailProbe(world)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    policies = (
        _policy(world, None),
        _policy(world, "A1"),
        _policy(world, "A2"),
    )
    aliases = ("no_new_action", "do_A1", "do_A2")
    utility_digest = digest_json(["W19", "tail-aware-utility", 4])

    common_alias, tail_alias = world.unidentified_tail_alias_pair(seed=1903)
    common_state = probe.initialize_public_episode(common_alias)
    tail_state = probe.initialize_public_episode(tail_alias)
    initial_diagnosis = probe.diagnose(common_state, diagnosis_query, query_seed=1)
    initial_rollouts: dict[str, Any] = {}
    initial_consumed = {initial_diagnosis.consumed_state_hash}
    for alias, policy in zip(aliases, policies, strict=True):
        execution = probe.rollout(
            common_state,
            RolloutQuery(4, policy, ("obs_0",), utility_digest),
            query_seed=2,
        )
        initial_consumed.add(execution.consumed_state_hash)
        initial_rollouts[alias] = execution.to_wire()

    delta = _marker_response_delta()
    updated = probe.update_public(common_state, delta, inference_seed=3)
    updated_diagnosis = probe.diagnose(updated, diagnosis_query, query_seed=4)
    updated_rollouts: dict[str, Any] = {}
    updated_consumed = {updated_diagnosis.consumed_state_hash}
    for alias, policy in zip(aliases, policies, strict=True):
        execution = probe.rollout(
            updated,
            RolloutQuery(4, policy, ("obs_0",), utility_digest),
            query_seed=5,
        )
        updated_consumed.add(execution.consumed_state_hash)
        updated_rollouts[alias] = execution.to_wire()

    initial_tail_probability = initial_diagnosis.response.result.probabilities["C1"]
    updated_tail_probability = updated_diagnosis.response.result.probabilities["C1"]
    a1_utility = updated_rollouts["do_A1"]["response"]["result"][
        "utility_prediction"
    ]
    a2_utility = updated_rollouts["do_A2"]["response"]["result"][
        "utility_prediction"
    ]
    return {
        "protocol": "ucm-phase2-w19-rare-contraindication-slice/1",
        "benchmark_status": "PRE-FREEZE",
        "experiment_status": "NOT_COUNT_ELIGIBLE",
        "manifest": probe.manifest.to_wire(),
        "unidentified_alias": {
            "common_state_hash": common_state.record.state_hash,
            "tail_state_hash": tail_state.record.state_hash,
            "initial_tail_probability": initial_tail_probability,
            "diagnosis": initial_diagnosis.to_wire(),
            "rollouts": initial_rollouts,
        },
        "marker_response_update": {
            "delta_digest": digest_json(delta.to_wire()),
            "new_state_hash": updated.record.state_hash,
            "parent_state_hash": updated.record.parent_state_hash,
            "updated_tail_probability": updated_tail_probability,
            "diagnosis": updated_diagnosis.to_wire(),
            "rollouts": updated_rollouts,
        },
        "assertions": {
            "unidentified_private_aliases_share_state": common_state.record.state_hash
            == tail_state.record.state_hash,
            "initial_tail_probability_matches_prevalence": math.isclose(
                initial_tail_probability,
                1.0 / 64.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            ),
            "initial_heads_consumed_one_hash": initial_consumed
            == {common_state.record.state_hash},
            "marker_response_update_parent_link_closed": updated.record.parent_state_hash
            == common_state.record.state_hash,
            "positive_marker_raises_tail_probability": updated_tail_probability
            > 0.40,
            "updated_heads_consumed_new_hash": updated_consumed
            == {updated.record.state_hash},
            "a1_exposes_catastrophic_hard_gate": (
                a1_utility["recommendation"] == "contraindicated"
                and a1_utility["tail_only_regret"] > 10.0
                and a1_utility["catastrophic_action_probability"] > 0.40
            ),
            "a2_avoids_catastrophic_hard_gate": (
                a2_utility["recommendation"] == "eligible"
                and a2_utility["catastrophic_action_probability"] == 0.0
            ),
        },
    }


def _main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Run the PRE-FREEZE W19 rare-contraindication slice."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = run_w19_tail_slice()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(artifact))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "W19PublicTailProbe",
    "W19TailProbeManifest",
    "run_w19_tail_slice",
]


if __name__ == "__main__":
    raise SystemExit(_main())
