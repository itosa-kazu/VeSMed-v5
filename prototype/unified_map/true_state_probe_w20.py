"""W20 feedback-memory public-belief vertical slice."""

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
from .worlds.w20 import W20World, _rounded


_STATE_PROTOCOL = "ucm-phase2-feedback-state-w20/1"
_STATE_SCHEMA = "ucm-phase2-feedback-state-w20-state/1"
_DOSE = {"A1": 1.0, "A2": 0.5}


@dataclass(frozen=True, slots=True)
class W20FeedbackProbeManifest:
    probe_id: str = "phase2-public-feedback-upper-bound-w20"
    baseline_id: str = "B01"
    world_slot: str = "W20"
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
            "state_evidence": "public-bayesian-sufficient-statistics",
            "state_channels": ["posterior_x", "exposure_memory_r"],
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


class W20PublicFeedbackProbe:
    """Shared ``P(x|H) x delta_r`` state with incremental response updates."""

    def __init__(self, world: W20World | None = None) -> None:
        self.world = world or W20World()
        self.manifest = W20FeedbackProbeManifest()
        self._candidate_bundle_digest = self.manifest.digest
        self._model_digest = digest_json(
            {
                "protocol": "ucm-public-feedback-model-binding/1",
                "world_slot": "W20",
                "filter": "covariance-form-incremental",
                "rollout": "W20World.public_belief_counterfactual",
                "closure": ["posterior_mean", "posterior_variance", "r"],
            }
        )
        self._scope_digest = digest_json(
            {
                "protocol": "ucm-true-state-scope/1",
                "world_slot": "W20",
                "catalog_digest": self.world.catalog.digest,
            }
        )

    @staticmethod
    def _representation(
        *,
        mean: float,
        variance: float,
        exposure: float,
        evidence_count: int,
        as_of_available_at: int,
    ) -> dict[str, Any]:
        if any(
            type(value) not in {int, float} or not math.isfinite(float(value))
            for value in (mean, variance, exposure)
        ):
            raise ProtocolViolation("W20 public belief must be finite")
        if variance < 0.0 or exposure < 0.0:
            raise ProtocolViolation("W20 variance/exposure cannot be negative")
        if type(evidence_count) is not int or evidence_count <= 0:
            raise ProtocolViolation("W20 evidence count must be positive")
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W20 public cut must be an integer")
        return {
            "protocol": _STATE_PROTOCOL,
            "world_slot": "W20",
            "as_of_available_at": as_of_available_at,
            "posterior_mean": _rounded(mean),
            "posterior_variance": _rounded(variance),
            "exposure_memory": _rounded(exposure),
            "evidence_count": evidence_count,
        }

    @staticmethod
    def _payload(value: dict[str, Any]) -> StatePayload:
        return StatePayload.from_json(
            value,
            schema_version=_STATE_SCHEMA,
            state_class=StateClass.DYNAMIC_SHARED,
        )

    @classmethod
    def _decode(cls, state: SealedState) -> dict[str, Any]:
        if type(state) is not SealedState:
            raise ProtocolViolation("W20 query requires SealedState")
        payload = state.candidate_input.payload
        if (
            payload.codec != "canonical-json-v1"
            or payload.schema_version != _STATE_SCHEMA
            or payload.state_class is not StateClass.DYNAMIC_SHARED
        ):
            raise ProtocolViolation("W20 feedback payload identity mismatch")
        try:
            value = json.loads(payload.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("W20 feedback payload is invalid") from exc
        expected = {
            "protocol",
            "world_slot",
            "as_of_available_at",
            "posterior_mean",
            "posterior_variance",
            "exposure_memory",
            "evidence_count",
        }
        if type(value) is not dict or set(value) != expected:
            raise ProtocolViolation("W20 feedback payload is not closed")
        if value.get("protocol") != _STATE_PROTOCOL or value.get("world_slot") != "W20":
            raise ProtocolViolation("W20 feedback state protocol mismatch")
        normalized = cls._representation(
            mean=value["posterior_mean"],
            variance=value["posterior_variance"],
            exposure=value["exposure_memory"],
            evidence_count=value["evidence_count"],
            as_of_available_at=value["as_of_available_at"],
        )
        if value != normalized:
            raise ProtocolViolation("W20 feedback state contains noncanonical claims")
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
            raise ProtocolViolation("W20 feedback seal binding mismatch")
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

    def initialize_public_episode(self, episode: PrivateEpisode) -> SealedState:
        if type(episode) is not PrivateEpisode:
            raise ProtocolViolation("W20 initializer requires PrivateEpisode")
        if episode.environment_key != self.world.environment_key:
            raise ProtocolViolation("W20 episode belongs to another world")
        mean, variance, exposure, evidence_count = self.world._production_posterior(
            episode
        )
        return self._seal(
            self._representation(
                mean=mean,
                variance=variance,
                exposure=exposure,
                evidence_count=evidence_count,
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
        if type(delta) is not VisibleDelta or delta.advance_to != prior["as_of_available_at"] + 1:
            raise ProtocolViolation("W20 update must advance exactly one time step")
        actions = [
            str(event.payload.get("action_id"))
            for event in delta.events
            if event.kind is EventKind.PERFORMED_TREATMENT
            and event.payload.get("action_id") in _DOSE
        ]
        if len(actions) > 1:
            raise ProtocolViolation("W20 update contains multiple performed actions")
        dose = _DOSE.get(actions[0], 0.0) if actions else 0.0
        observations = [
            float(event.payload["value"])
            for event in delta.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_0"
            and event.available_at == delta.advance_to
        ]
        if len(observations) != 1:
            raise ProtocolViolation("W20 update requires one newly available Q0")
        mean = float(prior["posterior_mean"])
        variance = float(prior["posterior_variance"])
        exposure = float(prior["exposure_memory"])
        predicted_mean, next_exposure = self.world.transition(
            mean, exposure, dose
        )
        predicted_variance = 0.90**2 * variance + 0.04**2
        innovation_variance = predicted_variance + 0.05**2
        gain = predicted_variance / innovation_variance
        posterior_mean = predicted_mean + gain * (
            observations[0] - predicted_mean
        )
        posterior_variance = (1.0 - gain) * predicted_variance
        value = self._representation(
            mean=posterior_mean,
            variance=posterior_variance,
            exposure=next_exposure,
            evidence_count=int(prior["evidence_count"]) + 1 + len(actions),
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
            raise ProtocolViolation("W20 diagnosis label catalog mismatch")
        high = float(value["exposure_memory"] >= 0.75)
        response = DiagnoseResponse(
            DiagnosisResult(
                ResultStatus.OK,
                {"C0": 1.0 - high, "C1": high},
                {
                    "baseline_id": "B01",
                    "eligibility": "upper_bound_only",
                    "public_evidence_only": True,
                    "response_regime": "reversed" if high else "ordinary",
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
            raise ProtocolViolation("W20 rollout supports obs_0")
        oracle = self.world.public_belief_counterfactual(
            float(value["posterior_mean"]),
            float(value["posterior_variance"]),
            float(value["exposure_memory"]),
            int(value["evidence_count"]),
            query.plan,
            query.horizon,
        )
        components = oracle.observation_distribution["components"]
        response = RolloutResponse(
            RolloutResult(
                ResultStatus.OK,
                observable_predictions={
                    "obs_0": {
                        "family": "public-posterior-branch-mixture",
                        "components": [
                            {
                                "branch_action": component["branch_action"],
                                "weight": float(component["weight"]),
                                "means": [
                                    float(step["mean"])
                                    for step in component["steps"]
                                ],
                                "variances": [
                                    float(step["observation_variance"])
                                    for step in component["steps"]
                                ],
                            }
                            for component in components
                        ],
                    }
                },
                utility_prediction={
                    "family": "posterior-expected-quadratic-cost",
                    "value": float(oracle.expected_utility),
                },
                metadata={
                    "baseline_id": "B01",
                    "eligibility": "upper_bound_only",
                    "public_evidence_only": True,
                    "response_regime": (
                        "reversed"
                        if value["exposure_memory"] >= 0.75
                        else "ordinary"
                    ),
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


def _policy(world: W20World, action: str | None) -> ActionPlan:
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


def _a1_response_delta() -> VisibleDelta:
    events = (
        CandidateVisibleEvent(
            kind=EventKind.PERFORMED_TREATMENT,
            occurred_at=0,
            available_at=1,
            event_uid="w20-factual-a1",
            payload={"action_id": "A1", "parameters": {}},
            collected_at=None,
        ),
        CandidateVisibleEvent(
            kind=EventKind.OBSERVATION_AVAILABLE,
            occurred_at=1,
            available_at=1,
            event_uid="w20-factual-response",
            payload={"channel_id": "obs_0", "value": 0.34},
            collected_at=1,
        ),
    )
    return VisibleDelta(1, tuple(sorted(events, key=event_sort_key)))


def _first_mean(execution: TrueStateHeadExecution) -> float:
    components = execution.response.result.observable_predictions["obs_0"][
        "components"
    ]
    return math.fsum(
        float(component["weight"]) * float(component["means"][0])
        for component in components
    )


def run_w20_feedback_slice() -> dict[str, Any]:
    world = W20World()
    probe = W20PublicFeedbackProbe(world)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    policies = (
        _policy(world, None),
        _policy(world, "A1"),
        _policy(world, "A2"),
    )
    aliases = ("no_new_action", "do_A1", "do_A2")
    utility_digest = digest_json(["W20", "posterior-quadratic", 4])

    low_episode, high_episode = world.exposure_collision_pair(seed=2001)
    low_state = probe.initialize_public_episode(low_episode)
    high_state = probe.initialize_public_episode(high_episode)
    patients: dict[str, Any] = {}
    executions_by_regime: dict[str, dict[str, TrueStateHeadExecution]] = {}
    for regime, state in (("low_exposure", low_state), ("high_exposure", high_state)):
        diagnosis = probe.diagnose(state, diagnosis_query, query_seed=1)
        consumed = {diagnosis.consumed_state_hash}
        executions: dict[str, TrueStateHeadExecution] = {}
        rollouts: dict[str, Any] = {}
        for alias, policy in zip(aliases, policies, strict=True):
            execution = probe.rollout(
                state,
                RolloutQuery(4, policy, ("obs_0",), utility_digest),
                query_seed=2,
            )
            consumed.add(execution.consumed_state_hash)
            executions[alias] = execution
            rollouts[alias] = execution.to_wire()
        patients[regime] = {
            "state_hash": state.record.state_hash,
            "diagnosis": diagnosis.to_wire(),
            "rollouts": rollouts,
            "all_heads_consumed_one_hash": consumed == {state.record.state_hash},
        }
        executions_by_regime[regime] = executions

    false_left, false_right = world.sufficient_statistic_false_split_pair(seed=2003)
    false_left_state = probe.initialize_public_episode(false_left)
    false_right_state = probe.initialize_public_episode(false_right)

    delta = _a1_response_delta()
    updated = probe.update_public(low_state, delta, inference_seed=3)
    updated_diagnosis = probe.diagnose(updated, diagnosis_query, query_seed=4)
    updated_no_action = probe.rollout(
        updated,
        RolloutQuery(4, policies[0], ("obs_0",), utility_digest),
        query_seed=5,
    )
    updated_a1 = probe.rollout(
        updated,
        RolloutQuery(4, policies[1], ("obs_0",), utility_digest),
        query_seed=6,
    )

    low = executions_by_regime["low_exposure"]
    high = executions_by_regime["high_exposure"]
    return {
        "protocol": "ucm-phase2-w20-feedback-memory-slice/1",
        "benchmark_status": "PRE-FREEZE",
        "experiment_status": "NOT_COUNT_ELIGIBLE",
        "manifest": probe.manifest.to_wire(),
        "exposure_collision": {
            "low": patients["low_exposure"],
            "high": patients["high_exposure"],
            "low_a1_first_mean": _first_mean(low["do_A1"]),
            "high_a1_first_mean": _first_mean(high["do_A1"]),
            "low_no_action_first_mean": _first_mean(low["no_new_action"]),
            "high_no_action_first_mean": _first_mean(high["no_new_action"]),
        },
        "sufficient_false_split": {
            "left_state_hash": false_left_state.record.state_hash,
            "right_state_hash": false_right_state.record.state_hash,
        },
        "response_update": {
            "delta_digest": digest_json(delta.to_wire()),
            "new_state_hash": updated.record.state_hash,
            "parent_state_hash": updated.record.parent_state_hash,
            "diagnosis": updated_diagnosis.to_wire(),
            "no_new_action_rollout": updated_no_action.to_wire(),
            "a1_rollout": updated_a1.to_wire(),
        },
        "assertions": {
            "exposure_memory_prevents_dangerous_collision": low_state.record.state_hash
            != high_state.record.state_hash,
            "same_x_but_opposite_a1_response": (
                _first_mean(low["do_A1"])
                < _first_mean(low["no_new_action"])
                and _first_mean(high["do_A1"])
                > _first_mean(high["no_new_action"])
            ),
            "all_initial_heads_share_patient_state": all(
                patient["all_heads_consumed_one_hash"]
                for patient in patients.values()
            ),
            "sufficient_histories_are_quotiented": false_left_state.record.state_hash
            == false_right_state.record.state_hash,
            "response_update_parent_link_closed": updated.record.parent_state_hash
            == low_state.record.state_hash,
            "response_update_changed_state": updated.record.state_hash
            != low_state.record.state_hash,
            "updated_heads_consumed_new_hash": {
                updated_diagnosis.consumed_state_hash,
                updated_no_action.consumed_state_hash,
                updated_a1.consumed_state_hash,
            }
            == {updated.record.state_hash},
            "updated_memory_reverses_next_a1_response": _first_mean(updated_a1)
            > _first_mean(updated_no_action),
        },
    }


def _main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Run the PRE-FREEZE W20 feedback-memory slice."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = run_w20_feedback_slice()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(artifact))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "W20FeedbackProbeManifest",
    "W20PublicFeedbackProbe",
    "run_w20_feedback_slice",
]


if __name__ == "__main__":
    raise SystemExit(_main())
