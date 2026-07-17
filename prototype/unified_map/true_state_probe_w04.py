"""W04 opposite-treatment-response true-state collision slice."""

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
    CandidateVisibleEvent,
    DiagnosisQuery,
    EventKind,
    RolloutQuery,
    VisibleDelta,
    event_sort_key,
)
from .state import SealedState, StateClass, StatePayload, seal_state
from .true_state_probe import TrueStateHeadExecution
from .worlds.base import PrivateEpisode
from .worlds.w04 import W04World


_STATE_PROTOCOL = "ucm-phase2-true-state-w04/1"
_STATE_SCHEMA = "ucm-phase2-true-state-w04-state/1"


@dataclass(frozen=True, slots=True)
class W04TrueStateProbeManifest:
    probe_id: str = "phase2-true-state-upper-bound-w04"
    baseline_id: str = "B01"
    world_slot: str = "W04"
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


class W04TrueStateUpperBoundProbe:
    """Parent-only W04 map that retains the treatment-response modifier."""

    def __init__(self, world: W04World | None = None) -> None:
        self.world = world or W04World()
        self.manifest = W04TrueStateProbeManifest()
        self._candidate_bundle_digest = self.manifest.digest
        self._model_digest = digest_json(
            {
                "protocol": "ucm-true-state-model-binding/1",
                "world_slot": "W04",
                "transition": "opposite-response-linear-gaussian",
                "entrypoint": "W04World.judge_true_state_counterfactual",
            }
        )
        self._scope_digest = digest_json(
            {
                "protocol": "ucm-true-state-scope/1",
                "world_slot": "W04",
                "catalog_digest": self.world.catalog.digest,
            }
        )

    @staticmethod
    def _representation(
        *, class_index: int, x: float, as_of_available_at: int
    ) -> dict[str, Any]:
        if type(class_index) is not int or class_index not in {0, 1}:
            raise ProtocolViolation("W04 upper-bound class_index must be zero or one")
        if type(x) not in {int, float} or not math.isfinite(float(x)):
            raise ProtocolViolation("W04 upper-bound x must be finite")
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W04 upper-bound as_of must be an integer")
        return {
            "protocol": _STATE_PROTOCOL,
            "world_slot": "W04",
            "as_of_available_at": as_of_available_at,
            "class_index": class_index,
            "x": float(x),
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
            raise ProtocolViolation("W04 upper-bound query requires SealedState")
        payload = state.candidate_input.payload
        if (
            payload.codec != "canonical-json-v1"
            or payload.schema_version != _STATE_SCHEMA
            or payload.state_class is not StateClass.DYNAMIC_SHARED
        ):
            raise ProtocolViolation("W04 upper-bound payload identity mismatch")
        try:
            value = json.loads(payload.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("W04 upper-bound payload is invalid") from exc
        if type(value) is not dict or set(value) != {
            "protocol",
            "world_slot",
            "as_of_available_at",
            "class_index",
            "x",
        }:
            raise ProtocolViolation("W04 upper-bound payload is not closed")
        if value["protocol"] != _STATE_PROTOCOL or value["world_slot"] != "W04":
            raise ProtocolViolation("W04 upper-bound state protocol mismatch")
        return W04TrueStateUpperBoundProbe._representation(
            class_index=value["class_index"],
            x=value["x"],
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
            raise ProtocolViolation("W04 upper-bound seal binding mismatch")
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
        self, *, class_index: int, x: float, as_of_available_at: int = 0
    ) -> SealedState:
        return self._seal(
            self._representation(
                class_index=class_index,
                x=x,
                as_of_available_at=as_of_available_at,
            ),
            operation="initialize",
        )

    def initialize_private(self, episode: PrivateEpisode) -> SealedState:
        if type(episode) is not PrivateEpisode:
            raise ProtocolViolation("W04 upper-bound initializer requires PrivateEpisode")
        if episode.environment_key != self.world.environment_key:
            raise ProtocolViolation("W04 upper-bound episode belongs to another world")
        if set(episode.hidden_state_at_cut) != {"x"} or set(
            episode.invariant_parameters
        ) != {"class_index"}:
            raise ProtocolViolation("W04 episode lacks complete judge truth")
        return self.initialize_true_state(
            class_index=episode.invariant_parameters["class_index"],
            x=episode.hidden_state_at_cut["x"],
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
            raise ProtocolViolation("W04 upper-bound update must advance with a delta")
        if not any(
            event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.available_at == delta.advance_to
            for event in delta.events
        ):
            raise ProtocolViolation("W04 upper-bound update requires a visible response")
        if set(hidden_state_at_cut) != {"x"} or set(invariant_parameters) != {
            "class_index"
        }:
            raise ProtocolViolation("W04 upper-bound update lacks next judge truth")
        if invariant_parameters["class_index"] != prior["class_index"]:
            raise ProtocolViolation("W04 invariant response class changed")
        value = self._representation(
            class_index=invariant_parameters["class_index"],
            x=hidden_state_at_cut["x"],
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
            raise ProtocolViolation("W04 diagnosis label catalog mismatch")
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
        if (
            query.horizon not in self.world.catalog.horizons
            or query.requested_observables != ("obs_0",)
        ):
            raise ProtocolViolation("W04 probe rollout supports the latent obs_0 path")
        oracle = self.world.judge_true_state_counterfactual(
            {"x": value["x"]},
            {"class_index": value["class_index"]},
            query.plan,
            query.horizon,
        )
        steps = oracle.observation_distribution["steps"]
        response = RolloutResponse(
            RolloutResult(
                ResultStatus.OK,
                observable_predictions={
                    "obs_0": {
                        "family": "point_mass",
                        "horizon": query.horizon,
                        "values": [float(step["mean"]) for step in steps],
                    }
                },
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


def _response_delta(*, class_index: int, prior_x: float) -> tuple[VisibleDelta, float]:
    response_sign = 1.0 if class_index == 0 else -1.0
    next_x = 0.92 * prior_x + 0.15 - 0.45 * response_sign
    events = (
        CandidateVisibleEvent(
            kind=EventKind.PERFORMED_TREATMENT,
            occurred_at=1,
            available_at=1,
            event_uid=f"w04-response-action-{class_index}",
            payload={"action_id": "A1", "parameters": {}},
            collected_at=None,
        ),
        CandidateVisibleEvent(
            kind=EventKind.OBSERVATION_AVAILABLE,
            occurred_at=1,
            available_at=1,
            event_uid=f"w04-response-observation-{class_index}",
            payload={"channel_id": "obs_0", "value": next_x},
            collected_at=1,
        ),
    )
    return VisibleDelta(1, tuple(sorted(events, key=event_sort_key))), next_x


def run_w04_collision_slice(*, x: float = 0.4) -> dict[str, Any]:
    world = W04World()
    probe = W04TrueStateUpperBoundProbe(world)
    utility_digest = digest_json(
        ["W04", world.catalog.digest, 4, "discounted-quadratic-cost"]
    )
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    policies = world.policy_set(4)[:3]
    aliases = ("no_new_action", "single_A1", "single_A2")
    patients: dict[str, Any] = {}
    no_action_paths: list[list[float]] = []
    best_actions: list[str] = []

    for class_index in (0, 1):
        state = probe.initialize_true_state(class_index=class_index, x=x)
        diagnosis = probe.diagnose(state, diagnosis_query, query_seed=1)
        rollouts: dict[str, Any] = {}
        utilities: list[float] = []
        consumed = {diagnosis.consumed_state_hash}
        for alias, policy in zip(aliases, policies, strict=True):
            execution = probe.rollout(
                state,
                RolloutQuery(4, policy, ("obs_0",), utility_digest),
                query_seed=2,
            )
            consumed.add(execution.consumed_state_hash)
            rollouts[alias] = execution.to_wire()
            utilities.append(execution.response.result.utility_prediction["value"])
        no_action_paths.append(
            rollouts["no_new_action"]["response"]["result"]
            ["observable_predictions"]["obs_0"]["values"]
        )
        best_actions.append(aliases[max(range(3), key=utilities.__getitem__)])

        delta, next_x = _response_delta(class_index=class_index, prior_x=x)
        updated = probe.update_private(
            state,
            delta,
            hidden_state_at_cut={"x": next_x},
            invariant_parameters={"class_index": class_index},
            inference_seed=3,
        )
        updated_rollout = probe.rollout(
            updated,
            RolloutQuery(4, policies[0], ("obs_0",), utility_digest),
            query_seed=4,
        )
        patients[f"C{class_index}"] = {
            "initial_state_id": state.record.state_id,
            "initial_state_hash": state.record.state_hash,
            "diagnosis": diagnosis.to_wire(),
            "rollouts": rollouts,
            "best_action": best_actions[-1],
            "update": {
                "delta_digest": digest_json(delta.to_wire()),
                "new_state_id": updated.record.state_id,
                "new_state_hash": updated.record.state_hash,
                "parent_state_hash": updated.record.parent_state_hash,
                "updated_no_action_rollout": updated_rollout.to_wire(),
            },
            "all_initial_heads_consumed_one_hash": consumed
            == {state.record.state_hash},
        }

    return {
        "protocol": "ucm-phase2-w04-dangerous-collision-slice/1",
        "benchmark_status": "PRE-FREEZE",
        "experiment_status": "NOT_COUNT_ELIGIBLE",
        "manifest": probe.manifest.to_wire(),
        "shared_observed_scalar": float(x),
        "patients": patients,
        "assertions": {
            "same_natural_course": no_action_paths[0] == no_action_paths[1],
            "opposite_optimal_treatments": best_actions
            == ["single_A1", "single_A2"],
            "modifier_prevents_state_collision": patients["C0"]["initial_state_hash"]
            != patients["C1"]["initial_state_hash"],
            "all_heads_share_patient_state": all(
                patient["all_initial_heads_consumed_one_hash"]
                for patient in patients.values()
            ),
            "updates_close_parent_links": all(
                patient["update"]["parent_state_hash"]
                == patient["initial_state_hash"]
                for patient in patients.values()
            ),
        },
    }


def _main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Run the PRE-FREEZE W04 dangerous-collision slice."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--x", type=float, default=0.4)
    args = parser.parse_args()
    artifact = run_w04_collision_slice(x=args.x)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(artifact))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "W04TrueStateProbeManifest",
    "W04TrueStateUpperBoundProbe",
    "run_w04_collision_slice",
]


if __name__ == "__main__":
    raise SystemExit(_main())
