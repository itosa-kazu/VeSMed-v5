"""Judge-only true-state upper-bound probe for the UCM Phase-2 harness.

This module is not a deployable candidate and does not open Phase 3.  It gives
the benchmark a concrete upper-bound sanity path using the same inert shared
state, diagnosis result, rollout result, and harness-computed state hashes that
ordinary candidates must use.  Private simulator state is consumed only by the
parent-side initializer and is explicitly marked ``upper_bound_only``.

The first vertical slice is W01, where the complete Markov state is small and
fully observed.  Later worlds can add their own judge-only state kernels
without weakening the ordinary candidate information boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any

from .canonical import ProtocolViolation, canonical_json_bytes, digest_json
from .candidate_protocol import (
    CandidateResponse,
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
from .worlds.base import PrivateEpisode, WorldSplit
from .worlds.w01 import W01World


_STATE_PROTOCOL = "ucm-phase2-true-state-w01/1"
_STATE_SCHEMA = "ucm-phase2-true-state-w01-state/1"


def _sha256(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} must be hexadecimal") from exc
    return value


@dataclass(frozen=True, slots=True)
class TrueStateProbeManifest:
    """Closed identity for a non-candidate upper-bound probe."""

    probe_id: str = "phase2-true-state-upper-bound-w01"
    baseline_id: str = "B01"
    world_slot: str = "W01"
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


@dataclass(frozen=True, slots=True)
class TrueStateHeadExecution:
    """One parent-side readout bound to the exact consumed shared state."""

    operation: Operation
    consumed_state_hash: str
    query_digest: str
    response: CandidateResponse
    manifest_digest: str

    def __post_init__(self) -> None:
        if self.operation not in {Operation.DIAGNOSE, Operation.ROLLOUT}:
            raise ProtocolViolation("upper-bound head operation must be a readout")
        _sha256(self.consumed_state_hash, "consumed_state_hash")
        _sha256(self.query_digest, "query_digest")
        _sha256(self.manifest_digest, "manifest_digest")
        if self.response.operation is not self.operation:
            raise ProtocolViolation("upper-bound response operation mismatch")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-true-state-head-execution/1",
            "operation": self.operation.value,
            "consumed_state_hash": self.consumed_state_hash,
            "query_digest": self.query_digest,
            "manifest_digest": self.manifest_digest,
            "privileged": True,
            "eligibility": "upper_bound_only",
            "response": self.response.to_wire(),
        }


class W01TrueStateUpperBoundProbe:
    """Executable W01 shared-state upper bound, excluded from candidate ranking."""

    def __init__(self, world: W01World | None = None) -> None:
        self.world = world or W01World()
        self.manifest = TrueStateProbeManifest()
        self._candidate_bundle_digest = self.manifest.digest
        self._model_digest = digest_json(
            {
                "protocol": "ucm-true-state-model-binding/1",
                "world_slot": "W01",
                "transition": "analytic-linear-gaussian",
                "entrypoint": "W01World.judge_true_state_counterfactual",
            }
        )
        self._scope_digest = digest_json(
            {
                "protocol": "ucm-true-state-scope/1",
                "world_slot": "W01",
                "catalog_digest": self.world.catalog.digest,
            }
        )

    @staticmethod
    def _state_representation(
        *, class_index: int, x: list[float], as_of_available_at: int
    ) -> dict[str, Any]:
        if type(class_index) is not int or class_index not in {0, 1}:
            raise ProtocolViolation("W01 upper-bound class_index must be zero or one")
        if (
            type(x) is not list
            or len(x) != 2
            or any(type(value) not in {int, float} for value in x)
            or any(not math.isfinite(float(value)) for value in x)
        ):
            raise ProtocolViolation("W01 upper-bound x must be two finite numbers")
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W01 upper-bound as_of must be an integer")
        return {
            "protocol": _STATE_PROTOCOL,
            "world_slot": "W01",
            "as_of_available_at": as_of_available_at,
            "class_index": class_index,
            "x": [float(value) for value in x],
        }

    @staticmethod
    def _payload(representation: dict[str, Any]) -> StatePayload:
        return StatePayload.from_json(
            representation,
            schema_version=_STATE_SCHEMA,
            state_class=StateClass.DYNAMIC_SHARED,
        )

    @staticmethod
    def _decode(state: SealedState) -> dict[str, Any]:
        if type(state) is not SealedState:
            raise ProtocolViolation("upper-bound query requires a SealedState")
        payload = state.candidate_input.payload
        if (
            payload.codec != "canonical-json-v1"
            or payload.schema_version != _STATE_SCHEMA
            or payload.state_class is not StateClass.DYNAMIC_SHARED
        ):
            raise ProtocolViolation("upper-bound state payload identity mismatch")
        try:
            value = json.loads(payload.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("upper-bound state payload is invalid") from exc
        if type(value) is not dict or set(value) != {
            "protocol",
            "world_slot",
            "as_of_available_at",
            "class_index",
            "x",
        }:
            raise ProtocolViolation("upper-bound state payload is not closed")
        if value["protocol"] != _STATE_PROTOCOL or value["world_slot"] != "W01":
            raise ProtocolViolation("upper-bound state protocol mismatch")
        return W01TrueStateUpperBoundProbe._state_representation(
            class_index=value["class_index"],
            x=value["x"],
            as_of_available_at=value["as_of_available_at"],
        )

    def _verify_seal(self, state: SealedState) -> dict[str, Any]:
        value = self._decode(state)
        record = state.record
        if (
            record.candidate_bundle_digest != self._candidate_bundle_digest
            or record.model_digest != self._model_digest
            or record.scope_digest != self._scope_digest
            or record.catalog_digest != self.world.catalog.digest
            or record.as_of_available_at != value["as_of_available_at"]
        ):
            raise ProtocolViolation("upper-bound state seal binding mismatch")
        return value

    def initialize_private(self, episode: PrivateEpisode) -> SealedState:
        """Create B01 state from judge-only truth; never callable by candidates."""

        if type(episode) is not PrivateEpisode:
            raise ProtocolViolation("upper-bound initializer requires PrivateEpisode")
        if episode.environment_key != self.world.environment_key:
            raise ProtocolViolation("upper-bound episode belongs to another world")
        if set(episode.hidden_state_at_cut) != {"x"} or set(
            episode.invariant_parameters
        ) != {"class_index"}:
            raise ProtocolViolation("upper-bound episode lacks the complete W01 state")
        representation = self._state_representation(
            class_index=episode.invariant_parameters["class_index"],
            x=episode.hidden_state_at_cut["x"],
            as_of_available_at=episode.public_history.as_of_available_at,
        )
        return seal_state(
            self._payload(representation),
            candidate_bundle_digest=self._candidate_bundle_digest,
            model_digest=self._model_digest,
            scope_digest=self._scope_digest,
            catalog_digest=self.world.catalog.digest,
            as_of_available_at=representation["as_of_available_at"],
            operation="initialize",
        )

    def update(
        self,
        state: SealedState,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> SealedState:
        """Recursively update W01 from a newly available full observation panel."""

        del inference_seed
        prior = self._verify_seal(state)
        if type(delta) is not VisibleDelta:
            raise ProtocolViolation("upper-bound update requires VisibleDelta")
        if delta.advance_to <= prior["as_of_available_at"]:
            raise ProtocolViolation("upper-bound update must advance the availability cut")

        panel: dict[str, float] = {}
        for event in delta.events:
            if (
                event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.available_at == delta.advance_to
            ):
                channel = event.payload.get("channel_id")
                value = event.payload.get("value")
                if channel in {"obs_0", "obs_1", "obs_2"}:
                    if channel in panel:
                        raise ProtocolViolation("upper-bound update repeats a panel channel")
                    if type(value) not in {int, float} or not math.isfinite(float(value)):
                        raise ProtocolViolation("upper-bound update contains a non-finite value")
                    panel[str(channel)] = float(value)
        if set(panel) != {"obs_0", "obs_1", "obs_2"}:
            raise ProtocolViolation("upper-bound update requires a complete W01 panel")
        class_index = int(panel["obs_2"])
        if panel["obs_2"] != float(class_index) or class_index != prior["class_index"]:
            raise ProtocolViolation("W01 invariant class changed during update")

        representation = self._state_representation(
            class_index=class_index,
            x=[panel["obs_0"], panel["obs_1"]],
            as_of_available_at=delta.advance_to,
        )
        return seal_state(
            self._payload(representation),
            candidate_bundle_digest=self._candidate_bundle_digest,
            model_digest=self._model_digest,
            scope_digest=self._scope_digest,
            catalog_digest=self.world.catalog.digest,
            as_of_available_at=delta.advance_to,
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
        value = self._verify_seal(state)
        if query.label_catalog != self.world.catalog.diagnostic_labels:
            raise ProtocolViolation("W01 diagnosis label catalog mismatch")
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
        value = self._verify_seal(state)
        if query.horizon not in self.world.catalog.horizons:
            raise ProtocolViolation("W01 rollout horizon is unsupported")
        allowed = {item.channel_id for item in self.world.catalog.observations}
        if not query.requested_observables or not set(query.requested_observables) <= allowed:
            raise ProtocolViolation("W01 rollout requested unknown observables")
        oracle = self.world.judge_true_state_counterfactual(
            {"x": value["x"]},
            {"class_index": value["class_index"]},
            query.plan,
            query.horizon,
        )
        steps = oracle.observation_distribution["steps"]
        predictions: dict[str, Any] = {}
        for observable in query.requested_observables:
            if observable == "obs_0":
                values = [float(step["mean"][0]) for step in steps]
            elif observable == "obs_1":
                values = [float(step["mean"][1]) for step in steps]
            else:
                values = [float(value["class_index"])] * query.horizon
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
                    "projection": "conditional_mean",
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


def _w01_factual_delta(episode: PrivateEpisode) -> VisibleDelta:
    """Project the first public TRAIN response into one recursive update."""

    if not episode.factual_future:
        raise ProtocolViolation("W01 upper-bound demo episode has no factual future")
    row = episode.factual_future[0]
    if type(row) is not dict or set(row) != {
        "offset",
        "observations",
        "performed_action",
    }:
        raise ProtocolViolation("W01 factual future row is malformed")
    observations = row["observations"]
    if type(observations) is not dict or set(observations) != {
        "obs_0",
        "obs_1",
        "obs_2",
    }:
        raise ProtocolViolation("W01 factual response panel is incomplete")

    events: list[CandidateVisibleEvent] = []
    action_id = row["performed_action"]
    if action_id != "NoNewAction":
        events.append(
            CandidateVisibleEvent(
                kind=EventKind.PERFORMED_TREATMENT,
                occurred_at=1,
                collected_at=None,
                available_at=1,
                event_uid="probe-" + digest_json(
                    {
                        "domain": "w01-upper-bound-action/1",
                        "case_key": episode.case_key,
                        "action_id": action_id,
                    }
                )[7:31],
                payload={"action_id": action_id, "parameters": {}},
            )
        )
    for slot, channel in enumerate(("obs_0", "obs_1", "obs_2")):
        events.append(
            CandidateVisibleEvent(
                kind=EventKind.OBSERVATION_AVAILABLE,
                occurred_at=1,
                collected_at=1,
                available_at=1,
                event_uid="probe-" + digest_json(
                    {
                        "domain": "w01-upper-bound-observation/1",
                        "case_key": episode.case_key,
                        "slot": slot,
                        "channel": channel,
                    }
                )[7:31],
                payload={"channel_id": channel, "value": observations[channel]},
            )
        )
    return VisibleDelta(1, tuple(sorted(events, key=event_sort_key)))


def run_w01_vertical_slice(
    *, generator_seed: int = 92011, episode_index: int = 13
) -> dict[str, Any]:
    """Run one deterministic shared-state W01 upper-bound demonstration."""

    if type(generator_seed) is not int or generator_seed < 0:
        raise ProtocolViolation("generator_seed must be a non-negative integer")
    if type(episode_index) is not int or episode_index < 0:
        raise ProtocolViolation("episode_index must be a non-negative integer")

    world = W01World()
    probe = W01TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(WorldSplit.TRAIN, generator_seed, episode_index)
    initial = probe.initialize_private(episode)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    utility_digest = digest_json(
        {
            "protocol": "ucm-w01-upper-bound-utility/1",
            "catalog_digest": world.catalog.digest,
            "horizon": 4,
            "utility": "discounted-quadratic-cost",
        }
    )
    diagnosis = probe.diagnose(initial, diagnosis_query, query_seed=1)

    rollout_records: dict[str, Any] = {}
    consumed_hashes = {diagnosis.consumed_state_hash}
    policy_aliases = ("no_new_action", "single_A1", "single_A2")
    for alias, policy in zip(policy_aliases, world.policy_set(4)[:3], strict=True):
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
        consumed_hashes.add(execution.consumed_state_hash)
        rollout_records[alias] = execution.to_wire()

    delta = _w01_factual_delta(episode)
    updated = probe.update(initial, delta, inference_seed=3)
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
        "initial_state": {
            "state_id": initial.record.state_id,
            "state_hash": initial.record.state_hash,
            "as_of_available_at": initial.record.as_of_available_at,
            "payload_size_bytes": initial.record.payload_size_bytes,
        },
        "diagnosis": diagnosis.to_wire(),
        "rollouts": rollout_records,
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
            "initial_heads_consumed_one_hash": consumed_hashes
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
        description="Run the PRE-FREEZE W01 true-state upper-bound vertical slice."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generator-seed", type=int, default=92011)
    parser.add_argument("--episode-index", type=int, default=13)
    args = parser.parse_args()
    artifact = run_w01_vertical_slice(
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
    "TrueStateHeadExecution",
    "TrueStateProbeManifest",
    "W01TrueStateUpperBoundProbe",
    "run_w01_vertical_slice",
]


if __name__ == "__main__":
    raise SystemExit(_main())
