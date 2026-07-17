"""W08 asynchronous-availability true-state vertical slice."""

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
from .worlds.w08 import World08


_STATE_PROTOCOL = "ucm-phase2-true-state-w08/1"
_STATE_SCHEMA = "ucm-phase2-true-state-w08-state/1"


@dataclass(frozen=True, slots=True)
class W08TrueStateProbeManifest:
    probe_id: str = "phase2-true-state-upper-bound-w08"
    baseline_id: str = "B01"
    world_slot: str = "W08"
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
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


class W08TrueStateUpperBoundProbe:
    """Parent-only W08 map with physiology and active-course typestate."""

    def __init__(self, world: World08 | None = None) -> None:
        self.world = world or World08()
        self.manifest = W08TrueStateProbeManifest()
        self._candidate_bundle_digest = self.manifest.digest
        self._model_digest = digest_json(
            {
                "protocol": "ucm-true-state-model-binding/1",
                "world_slot": "W08",
                "transition": "asynchronous-course-linear-gaussian",
                "entrypoint": "World08.judge_true_state_counterfactual",
                "pending_private_reports": "excluded_until_available",
            }
        )
        self._scope_digest = digest_json(
            {
                "protocol": "ucm-true-state-scope/1",
                "world_slot": "W08",
                "catalog_digest": self.world.catalog.digest,
            }
        )

    @staticmethod
    def _representation(
        *,
        class_index: int,
        x: list[float],
        exposure: int,
        remaining: int,
        as_of_available_at: int,
    ) -> dict[str, Any]:
        if type(class_index) is not int or class_index not in {0, 1}:
            raise ProtocolViolation("W08 upper-bound class_index must be zero or one")
        if (
            type(x) is not list
            or len(x) != 2
            or any(type(value) not in {int, float} for value in x)
            or any(not math.isfinite(float(value)) for value in x)
        ):
            raise ProtocolViolation("W08 upper-bound x must contain two finite numbers")
        if type(exposure) is not int or exposure not in {-1, 0, 1}:
            raise ProtocolViolation("W08 upper-bound exposure must be -1, zero or one")
        if type(remaining) is not int or remaining not in range(5):
            raise ProtocolViolation("W08 upper-bound remaining must be in [0, 4]")
        if (remaining == 0) != (exposure == 0):
            raise ProtocolViolation("W08 upper-bound course typestate is inconsistent")
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W08 upper-bound as_of must be an integer")
        return {
            "protocol": _STATE_PROTOCOL,
            "world_slot": "W08",
            "as_of_available_at": as_of_available_at,
            "class_index": class_index,
            "x": [float(value) for value in x],
            "exposure": exposure,
            "remaining": remaining,
        }

    @staticmethod
    def _payload(value: dict[str, Any]) -> StatePayload:
        return StatePayload.from_json(
            value,
            schema_version=_STATE_SCHEMA,
            state_class=StateClass.DYNAMIC_SHARED,
        )

    @staticmethod
    def _decode(state: SealedState) -> dict[str, Any]:
        if type(state) is not SealedState:
            raise ProtocolViolation("W08 upper-bound query requires SealedState")
        payload = state.candidate_input.payload
        if (
            payload.codec != "canonical-json-v1"
            or payload.schema_version != _STATE_SCHEMA
            or payload.state_class is not StateClass.DYNAMIC_SHARED
        ):
            raise ProtocolViolation("W08 upper-bound payload identity mismatch")
        try:
            value = json.loads(payload.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("W08 upper-bound payload is invalid") from exc
        if type(value) is not dict or set(value) != {
            "protocol",
            "world_slot",
            "as_of_available_at",
            "class_index",
            "x",
            "exposure",
            "remaining",
        }:
            raise ProtocolViolation("W08 upper-bound payload is not closed")
        if value["protocol"] != _STATE_PROTOCOL or value["world_slot"] != "W08":
            raise ProtocolViolation("W08 upper-bound state protocol mismatch")
        return W08TrueStateUpperBoundProbe._representation(
            class_index=value["class_index"],
            x=value["x"],
            exposure=value["exposure"],
            remaining=value["remaining"],
            as_of_available_at=value["as_of_available_at"],
        )

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
            raise ProtocolViolation("W08 upper-bound seal binding mismatch")
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

    def initialize_true_state(
        self,
        *,
        class_index: int,
        x: list[float],
        exposure: int = 0,
        remaining: int = 0,
        as_of_available_at: int = 0,
    ) -> SealedState:
        return self._seal(
            self._representation(
                class_index=class_index,
                x=x,
                exposure=exposure,
                remaining=remaining,
                as_of_available_at=as_of_available_at,
            ),
            operation="initialize",
        )

    def initialize_private(self, episode: PrivateEpisode) -> SealedState:
        if type(episode) is not PrivateEpisode:
            raise ProtocolViolation("W08 upper-bound initializer requires PrivateEpisode")
        if episode.environment_key != self.world.environment_key:
            raise ProtocolViolation("W08 upper-bound episode belongs to another world")
        if set(episode.hidden_state_at_cut) != {
            "x",
            "exposure",
            "remaining",
            "pending_results",
        } or set(episode.invariant_parameters) != {"c", "course_starts"}:
            raise ProtocolViolation("W08 episode lacks complete judge truth")
        return self.initialize_true_state(
            class_index=episode.invariant_parameters["c"],
            x=episode.hidden_state_at_cut["x"],
            exposure=episode.hidden_state_at_cut["exposure"],
            remaining=episode.hidden_state_at_cut["remaining"],
            as_of_available_at=episode.public_history.as_of_available_at,
        )

    def update_private(
        self,
        state: SealedState,
        delta: VisibleDelta,
        *,
        hidden_state_at_cut: dict[str, Any],
        invariant_parameters: dict[str, Any],
        inference_seed: int,
    ) -> SealedState:
        del inference_seed
        prior = self._verify(state)
        if type(delta) is not VisibleDelta or delta.advance_to <= prior["as_of_available_at"]:
            raise ProtocolViolation("W08 upper-bound update must advance with a delta")
        if not any(
            event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.available_at == delta.advance_to
            for event in delta.events
        ):
            raise ProtocolViolation("W08 upper-bound update requires a visible response")
        if set(hidden_state_at_cut) != {"x", "exposure", "remaining"} or set(
            invariant_parameters
        ) != {"c"}:
            raise ProtocolViolation("W08 upper-bound update lacks next judge truth")
        if invariant_parameters["c"] != prior["class_index"]:
            raise ProtocolViolation("W08 invariant class changed")
        value = self._representation(
            class_index=invariant_parameters["c"],
            x=hidden_state_at_cut["x"],
            exposure=hidden_state_at_cut["exposure"],
            remaining=hidden_state_at_cut["remaining"],
            as_of_available_at=delta.advance_to,
        )
        return self._seal(
            value,
            operation="update",
            parent_state_hash=state.record.state_hash,
            delta_digest=digest_json(delta.to_wire()),
        )

    def diagnose(
        self,
        state: SealedState,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> TrueStateHeadExecution:
        del query_seed
        value = self._verify(state)
        if query.label_catalog != self.world.catalog.diagnostic_labels:
            raise ProtocolViolation("W08 diagnosis label catalog mismatch")
        class_index = value["class_index"]
        response = DiagnoseResponse(
            DiagnosisResult(
                ResultStatus.OK,
                {
                    "C0": float(class_index == 0),
                    "C1": float(class_index == 1),
                },
                {
                    "baseline_id": "B01",
                    "privileged": True,
                    "eligibility": "upper_bound_only",
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
        self,
        state: SealedState,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> TrueStateHeadExecution:
        del query_seed
        value = self._verify(state)
        allowed = {"obs_0", "obs_1"}
        if (
            query.horizon not in self.world.catalog.horizons
            or not query.requested_observables
            or not set(query.requested_observables) <= allowed
        ):
            raise ProtocolViolation("W08 probe rollout requested an unknown observable")
        oracle = self.world.judge_true_state_counterfactual(
            {
                "x": value["x"],
                "exposure": value["exposure"],
                "remaining": value["remaining"],
            },
            {"c": value["class_index"]},
            query.plan,
            query.horizon,
        )
        predictions = {
            channel: {
                "family": "point_mass",
                "horizon": query.horizon,
                "values": [
                    float(step["mean"])
                    for step in oracle.observation_distribution[channel]
                ],
            }
            for channel in query.requested_observables
        }
        response = RolloutResponse(
            RolloutResult(
                ResultStatus.OK,
                observable_predictions=predictions,
                utility_prediction={
                    "family": "point_mass",
                    "value": float(oracle.expected_utility),
                },
                metadata={
                    "baseline_id": "B01",
                    "privileged": True,
                    "eligibility": "upper_bound_only",
                    "projection": "conditional-mean-observation",
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


def _late_response_delta() -> tuple[VisibleDelta, list[float]]:
    # From cut -1 to cut 0 the C0 state evolves naturally.  A1 starts at cut 0
    # and remains active for the transition to cut 1.
    at_zero = _c0_step([0.4, -0.2], active=0)
    next_x = _c0_step(at_zero, active=1)
    events = (
        CandidateVisibleEvent(
            kind=EventKind.PERFORMED_TREATMENT,
            occurred_at=0,
            available_at=0,
            event_uid="w08-factual-a1-at-zero",
            payload={"action_id": "A1", "course_microticks": 4},
            collected_at=None,
        ),
        CandidateVisibleEvent(
            kind=EventKind.OBSERVATION_AVAILABLE,
            occurred_at=-1,
            available_at=1,
            event_uid="w08-late-result-at-one",
            payload={"channel_id": "obs_0", "check_id": "Q0", "value": 0.55},
            collected_at=-1,
        ),
    )
    return VisibleDelta(1, tuple(sorted(events, key=event_sort_key))), next_x


def _c0_step(state: list[float], *, active: int) -> list[float]:
    """Independent closed-form C0 step used by the runnable evidence path."""

    return [
        0.98 * state[0] + 0.01 * state[1] - 0.07 * active,
        -0.005 * state[0] + 0.97 * state[1] + 0.025 * active,
    ]


def _vertical_policies(world: World08) -> tuple[ActionPlan, ActionPlan, ActionPlan]:
    policies = world.policy_set(4)
    no_action = next(policy for policy in policies if policy.kind is PlanKind.NO_NEW_ACTION)
    a1 = next(
        policy
        for policy in policies
        if len(policy.actions) == 1 and policy.actions[0].action_id == "A1"
    )
    a2 = next(
        policy
        for policy in policies
        if len(policy.actions) == 1 and policy.actions[0].action_id == "A2"
    )
    return no_action, a1, a2


def run_w08_availability_slice() -> dict[str, Any]:
    world = World08()
    probe = W08TrueStateUpperBoundProbe(world)
    utility_digest = digest_json(
        ["W08", world.catalog.digest, 4, "discounted-quadratic-cost"]
    )
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    policies = _vertical_policies(world)
    aliases = ("no_new_action", "single_A1", "single_A2")
    state = probe.initialize_true_state(
        class_index=0,
        x=[0.4, -0.2],
        exposure=0,
        remaining=0,
        as_of_available_at=-1,
    )
    diagnosis = probe.diagnose(state, diagnosis_query, query_seed=1)
    rollouts: dict[str, Any] = {}
    initial_consumed = {diagnosis.consumed_state_hash}
    for alias, policy in zip(aliases, policies, strict=True):
        execution = probe.rollout(
            state,
            RolloutQuery(4, policy, ("obs_0", "obs_1"), utility_digest),
            query_seed=2,
        )
        initial_consumed.add(execution.consumed_state_hash)
        rollouts[alias] = execution.to_wire()

    delta, next_x = _late_response_delta()
    updated = probe.update_private(
        state,
        delta,
        hidden_state_at_cut={"x": next_x, "exposure": 1, "remaining": 3},
        invariant_parameters={"c": 0},
        inference_seed=3,
    )
    updated_diagnosis = probe.diagnose(updated, diagnosis_query, query_seed=4)
    updated_rollout = probe.rollout(
        updated,
        RolloutQuery(4, policies[0], ("obs_0", "obs_1"), utility_digest),
        query_seed=5,
    )
    updated_consumed = {
        updated_diagnosis.consumed_state_hash,
        updated_rollout.consumed_state_hash,
    }

    private_left, private_right = world.probe_fixtures(806)[
        "identical_prefix_future_swap"
    ]
    private_left_state = probe.initialize_private(private_left)
    private_right_state = probe.initialize_private(private_right)
    pending_left = private_left.hidden_state_at_cut["pending_results"]
    pending_right = private_right.hidden_state_at_cut["pending_results"]
    first_updated_obs_0 = updated_rollout.response.result.observable_predictions[
        "obs_0"
    ]["values"][0]
    expected_active_course_obs_0 = _c0_step(next_x, active=1)[0]

    return {
        "protocol": "ucm-phase2-w08-asynchronous-availability-slice/1",
        "benchmark_status": "PRE-FREEZE",
        "experiment_status": "NOT_COUNT_ELIGIBLE",
        "manifest": probe.manifest.to_wire(),
        "initial_state_id": state.record.state_id,
        "initial_state_hash": state.record.state_hash,
        "diagnosis": diagnosis.to_wire(),
        "rollouts": rollouts,
        "late_update": {
            "delta": delta.to_wire(),
            "delta_digest": digest_json(delta.to_wire()),
            "new_state_id": updated.record.state_id,
            "new_state_hash": updated.record.state_hash,
            "parent_state_hash": updated.record.parent_state_hash,
            "diagnosis": updated_diagnosis.to_wire(),
            "no_new_action_rollout": updated_rollout.to_wire(),
        },
        "private_pending_swap": {
            "left_pending_digest": digest_json(pending_left),
            "right_pending_digest": digest_json(pending_right),
            "left_state_hash": private_left_state.record.state_hash,
            "right_state_hash": private_right_state.record.state_hash,
        },
        "assertions": {
            "initial_heads_consumed_one_hash": initial_consumed
            == {state.record.state_hash},
            "pending_private_result_excluded_before_availability": (
                pending_left != pending_right
                and private_left_state.record.state_hash
                == private_right_state.record.state_hash
            ),
            "late_result_preserved_collection_and_availability_times": any(
                event.collected_at == -1
                and event.available_at == 1
                and event.kind is EventKind.OBSERVATION_AVAILABLE
                for event in delta.events
            ),
            "update_changed_hash": updated.record.state_hash
            != state.record.state_hash,
            "update_parent_link_closed": updated.record.parent_state_hash
            == state.record.state_hash,
            "updated_heads_consumed_new_hash": updated_consumed
            == {updated.record.state_hash},
            "active_course_typestate_retained": math.isclose(
                first_updated_obs_0,
                expected_active_course_obs_0,
                rel_tol=0.0,
                abs_tol=1e-12,
            ),
        },
    }


def _main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Run the PRE-FREEZE W08 asynchronous-availability slice."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = run_w08_availability_slice()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(artifact))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "W08TrueStateProbeManifest",
    "W08TrueStateUpperBoundProbe",
    "run_w08_availability_slice",
]


if __name__ == "__main__":
    raise SystemExit(_main())
