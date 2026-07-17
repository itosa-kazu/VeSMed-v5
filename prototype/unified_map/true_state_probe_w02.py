"""W02 partially observed true-state upper-bound vertical slice."""

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
from .worlds.base import PrivateEpisode, WorldSplit
from .worlds.w02 import W02World


_STATE_PROTOCOL = "ucm-phase2-true-state-w02/1"
_STATE_SCHEMA = "ucm-phase2-true-state-w02-state/1"


@dataclass(frozen=True, slots=True)
class W02TrueStateProbeManifest:
    probe_id: str = "phase2-true-state-upper-bound-w02"
    baseline_id: str = "B01"
    world_slot: str = "W02"
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


class W02TrueStateUpperBoundProbe:
    """Parent-only W02 state whose heads cannot reread public history."""

    def __init__(self, world: W02World | None = None) -> None:
        self.world = world or W02World()
        self.manifest = W02TrueStateProbeManifest()
        self._candidate_bundle_digest = self.manifest.digest
        self._model_digest = digest_json(
            {
                "protocol": "ucm-true-state-model-binding/1",
                "world_slot": "W02",
                "transition": "class-linear-gaussian",
                "entrypoint": "W02World.judge_true_state_counterfactual",
            }
        )
        self._scope_digest = digest_json(
            {
                "protocol": "ucm-true-state-scope/1",
                "world_slot": "W02",
                "catalog_digest": self.world.catalog.digest,
            }
        )

    @staticmethod
    def _representation(
        *, class_index: int, x: list[float], as_of_available_at: int
    ) -> dict[str, Any]:
        if type(class_index) is not int or class_index not in {0, 1}:
            raise ProtocolViolation("W02 upper-bound class_index must be zero or one")
        if (
            type(x) is not list
            or len(x) != 2
            or any(type(value) not in {int, float} for value in x)
            or any(not math.isfinite(float(value)) for value in x)
        ):
            raise ProtocolViolation("W02 upper-bound x must be two finite numbers")
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W02 upper-bound as_of must be an integer")
        return {
            "protocol": _STATE_PROTOCOL,
            "world_slot": "W02",
            "as_of_available_at": as_of_available_at,
            "class_index": class_index,
            "x": [float(value) for value in x],
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
            raise ProtocolViolation("W02 upper-bound query requires SealedState")
        payload = state.candidate_input.payload
        if (
            payload.codec != "canonical-json-v1"
            or payload.schema_version != _STATE_SCHEMA
            or payload.state_class is not StateClass.DYNAMIC_SHARED
        ):
            raise ProtocolViolation("W02 upper-bound payload identity mismatch")
        try:
            value = json.loads(payload.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("W02 upper-bound payload is invalid") from exc
        if type(value) is not dict or set(value) != {
            "protocol",
            "world_slot",
            "as_of_available_at",
            "class_index",
            "x",
        }:
            raise ProtocolViolation("W02 upper-bound payload is not closed")
        if value["protocol"] != _STATE_PROTOCOL or value["world_slot"] != "W02":
            raise ProtocolViolation("W02 upper-bound state protocol mismatch")
        return W02TrueStateUpperBoundProbe._representation(
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
            raise ProtocolViolation("W02 upper-bound seal binding mismatch")
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

    def initialize_private(self, episode: PrivateEpisode) -> SealedState:
        if type(episode) is not PrivateEpisode:
            raise ProtocolViolation("W02 upper-bound initializer requires PrivateEpisode")
        if episode.environment_key != self.world.environment_key:
            raise ProtocolViolation("W02 upper-bound episode belongs to another world")
        if set(episode.hidden_state_at_cut) != {"x"} or set(
            episode.invariant_parameters
        ) != {"class_index"}:
            raise ProtocolViolation("W02 episode lacks complete judge truth")
        return self._seal(
            self._representation(
                class_index=episode.invariant_parameters["class_index"],
                x=episode.hidden_state_at_cut["x"],
                as_of_available_at=episode.public_history.as_of_available_at,
            ),
            operation="initialize",
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
        """Advance a partially observed map using parent-only next truth."""

        del inference_seed
        prior = self._verify(state)
        if type(delta) is not VisibleDelta:
            raise ProtocolViolation("W02 upper-bound update requires VisibleDelta")
        if delta.advance_to <= prior["as_of_available_at"]:
            raise ProtocolViolation("W02 upper-bound update must advance the cut")
        if not any(
            event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.available_at == delta.advance_to
            for event in delta.events
        ):
            raise ProtocolViolation("W02 upper-bound update requires a visible response")
        if set(hidden_state_at_cut) != {"x"} or set(invariant_parameters) != {
            "class_index"
        }:
            raise ProtocolViolation("W02 upper-bound update lacks next judge truth")
        class_index = invariant_parameters["class_index"]
        if class_index != prior["class_index"]:
            raise ProtocolViolation("W02 invariant class changed during update")
        value = self._representation(
            class_index=class_index,
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
            raise ProtocolViolation("W02 diagnosis label catalog mismatch")
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
        allowed = {item.channel_id for item in self.world.catalog.observations}
        if (
            query.horizon not in self.world.catalog.horizons
            or not query.requested_observables
            or not set(query.requested_observables) <= allowed
        ):
            raise ProtocolViolation("W02 rollout query is outside the public catalog")
        oracle = self.world.judge_true_state_counterfactual(
            {"x": value["x"]},
            {"class_index": value["class_index"]},
            query.plan,
            query.horizon,
        )
        steps = oracle.observation_distribution["latent_moment_projection"]
        predictions: dict[str, Any] = {}
        for observable in query.requested_observables:
            if observable == "obs_0":
                values = [float(sum(step["mean"])) for step in steps]
            elif observable == "obs_1":
                values = [float(step["mean"][0]) for step in steps]
            else:
                values = [float(step["mean"][1]) for step in steps]
            predictions[observable] = {
                "family": "point_mass",
                "horizon": query.horizon,
                "values": values,
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


def _factual_delta(episode: PrivateEpisode) -> VisibleDelta:
    if not episode.factual_future:
        raise ProtocolViolation("W02 demo episode has no factual future")
    row = episode.factual_future[0]
    observation = row["available_observation"]
    events: list[CandidateVisibleEvent] = []
    action_id = row["performed_action"]
    if action_id != "NoNewAction":
        events.append(
            CandidateVisibleEvent(
                kind=EventKind.PERFORMED_TREATMENT,
                occurred_at=1,
                available_at=1,
                event_uid="probe-" + digest_json(
                    ["w02-action", episode.case_key, action_id]
                )[7:31],
                payload={"action_id": action_id, "parameters": {}},
                collected_at=None,
            )
        )
    events.append(
        CandidateVisibleEvent(
            kind=EventKind.OBSERVATION_AVAILABLE,
            occurred_at=1,
            available_at=1,
            event_uid="probe-" + digest_json(
                ["w02-observation", episode.case_key, observation["channel_id"]]
            )[7:31],
            payload=observation,
            collected_at=1,
        )
    )
    return VisibleDelta(1, tuple(sorted(events, key=event_sort_key)))


def run_w02_vertical_slice(
    *, generator_seed: int = 92024, episode_index: int = 36
) -> dict[str, Any]:
    world = W02World()
    probe = W02TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(WorldSplit.TRAIN, generator_seed, episode_index)
    initial = probe.initialize_private(episode)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    diagnosis = probe.diagnose(initial, diagnosis_query, query_seed=1)
    utility_digest = digest_json(
        {
            "protocol": "ucm-w02-upper-bound-utility/1",
            "catalog_digest": world.catalog.digest,
            "horizon": 4,
            "utility": "discounted-quadratic-cost",
        }
    )
    rollouts: dict[str, Any] = {}
    consumed = {diagnosis.consumed_state_hash}
    for alias, policy in zip(
        ("no_new_action", "single_A1", "single_A2"),
        world.policy_set(4)[:3],
        strict=True,
    ):
        execution = probe.rollout(
            initial,
            RolloutQuery(
                4,
                policy,
                ("obs_0", "obs_1", "obs_2"),
                utility_digest,
            ),
            query_seed=2,
        )
        consumed.add(execution.consumed_state_hash)
        rollouts[alias] = execution.to_wire()

    public_oracle = world.counterfactual(episode, world.policy_set(4)[0], 4, 2)
    public_posterior = public_oracle.latent_distribution["diagnostic_posterior"]
    true_probabilities = diagnosis.response.result.probabilities
    delta = _factual_delta(episode)
    next_row = episode.factual_future[0]
    updated = probe.update_private(
        initial,
        delta,
        hidden_state_at_cut={"x": next_row["latent_outcome"]},
        invariant_parameters=episode.invariant_parameters,
        inference_seed=3,
    )
    updated_diagnosis = probe.diagnose(updated, diagnosis_query, query_seed=4)
    updated_rollout = probe.rollout(
        updated,
        RolloutQuery(
            4,
            world.policy_set(4)[0],
            ("obs_0", "obs_1", "obs_2"),
            utility_digest,
        ),
        query_seed=5,
    )
    return {
        "protocol": "ucm-phase2-true-state-vertical-slice/1",
        "benchmark_status": "PRE-FREEZE",
        "experiment_status": "NOT_COUNT_ELIGIBLE",
        "manifest": probe.manifest.to_wire(),
        "train_fixture": {
            "generator_seed": generator_seed,
            "episode_index": episode_index,
            "public_history_digest": episode.public_history.digest,
        },
        "public_belief_diagnosis": public_posterior,
        "true_state_diagnosis": true_probabilities,
        "initial_state": {
            "state_id": initial.record.state_id,
            "state_hash": initial.record.state_hash,
            "as_of_available_at": initial.record.as_of_available_at,
            "payload_size_bytes": initial.record.payload_size_bytes,
        },
        "diagnosis": diagnosis.to_wire(),
        "rollouts": rollouts,
        "update": {
            "delta_digest": digest_json(delta.to_wire()),
            "prior_state_hash": initial.record.state_hash,
            "new_state_id": updated.record.state_id,
            "new_state_hash": updated.record.state_hash,
            "parent_state_hash": updated.record.parent_state_hash,
            "as_of_available_at": updated.record.as_of_available_at,
        },
        "updated_diagnosis": updated_diagnosis.to_wire(),
        "updated_no_action_rollout": updated_rollout.to_wire(),
        "assertions": {
            "public_belief_is_non_degenerate": all(
                0.0 < float(value) < 1.0 for value in public_posterior.values()
            ),
            "true_state_diagnosis_is_one_hot": sorted(true_probabilities.values())
            == [0.0, 1.0],
            "initial_heads_consumed_one_hash": consumed
            == {initial.record.state_hash},
            "update_changed_hash": updated.record.state_hash
            != initial.record.state_hash,
            "update_parent_link_closed": updated.record.parent_state_hash
            == initial.record.state_hash,
            "updated_heads_consumed_new_hash": {
                updated_diagnosis.consumed_state_hash,
                updated_rollout.consumed_state_hash,
            }
            == {updated.record.state_hash},
        },
    }


def _main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Run the PRE-FREEZE W02 true-state upper-bound vertical slice."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generator-seed", type=int, default=92024)
    parser.add_argument("--episode-index", type=int, default=36)
    args = parser.parse_args()
    artifact = run_w02_vertical_slice(
        generator_seed=args.generator_seed,
        episode_index=args.episode_index,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(artifact))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "W02TrueStateProbeManifest",
    "W02TrueStateUpperBoundProbe",
    "run_w02_vertical_slice",
]


if __name__ == "__main__":
    raise SystemExit(_main())
