"""W18 public-evidence OOD/rejection vertical slice."""

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
from .worlds.w18 import W18World


_STATE_PROTOCOL = "ucm-phase2-public-ood-state-w18/1"
_STATE_SCHEMA = "ucm-phase2-public-ood-state-w18-state/1"


@dataclass(frozen=True, slots=True)
class W18OODProbeManifest:
    probe_id: str = "phase2-public-ood-upper-bound-w18"
    baseline_id: str = "B01"
    world_slot: str = "W18"
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
            "state_evidence": "public-observations-only",
            "private_mechanism_policy": "excluded",
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


class W18PublicOODProbe:
    """Shared public belief state with support-aware abstention."""

    def __init__(self, world: W18World | None = None) -> None:
        self.world = world or W18World()
        self.manifest = W18OODProbeManifest()
        self._candidate_bundle_digest = self.manifest.digest
        self._model_digest = digest_json(
            {
                "protocol": "ucm-public-ood-model-binding/1",
                "world_slot": "W18",
                "posterior": "analytic-bounded-support-mixture",
                "rollout": "W18World.public_state_counterfactual",
                "private_mechanism_policy": "excluded",
            }
        )
        self._scope_digest = digest_json(
            {
                "protocol": "ucm-true-state-scope/1",
                "world_slot": "W18",
                "catalog_digest": self.world.catalog.digest,
            }
        )

    def _representation(
        self, *, obs_0: float, obs_1: float, as_of_available_at: int
    ) -> dict[str, Any]:
        if any(
            type(value) not in {int, float} or not math.isfinite(float(value))
            for value in (obs_0, obs_1)
        ):
            raise ProtocolViolation("W18 public observations must be finite")
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W18 public cut must be an integer")
        posterior = self.world._mechanism_posterior_values(
            float(obs_0), float(obs_1)
        )
        support = {
            mechanism: self.world._class_likelihood(
                mechanism, float(obs_0), float(obs_1)
            )
            > 0.0
            for mechanism in ("C0", "C1")
        }
        return {
            "protocol": _STATE_PROTOCOL,
            "world_slot": "W18",
            "as_of_available_at": as_of_available_at,
            "latest_observations": {
                "obs_0": float(obs_0),
                "obs_1": float(obs_1),
            },
            "mechanism_posterior": posterior,
            "known_support": support,
            "public_ood_attribution": (
                "KNOWN_SUPPORT_PRESENT" if any(support.values()) else "OOD_ATTRIBUTABLE"
            ),
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
            raise ProtocolViolation("W18 query requires SealedState")
        payload = state.candidate_input.payload
        if (
            payload.codec != "canonical-json-v1"
            or payload.schema_version != _STATE_SCHEMA
            or payload.state_class is not StateClass.DYNAMIC_SHARED
        ):
            raise ProtocolViolation("W18 OOD payload identity mismatch")
        try:
            value = json.loads(payload.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("W18 OOD payload is invalid") from exc
        expected = {
            "protocol",
            "world_slot",
            "as_of_available_at",
            "latest_observations",
            "mechanism_posterior",
            "known_support",
            "public_ood_attribution",
        }
        if type(value) is not dict or set(value) != expected:
            raise ProtocolViolation("W18 OOD payload is not closed")
        if value.get("protocol") != _STATE_PROTOCOL or value.get("world_slot") != "W18":
            raise ProtocolViolation("W18 OOD state protocol mismatch")
        observations = value.get("latest_observations")
        if type(observations) is not dict or set(observations) != {"obs_0", "obs_1"}:
            raise ProtocolViolation("W18 OOD observations are not closed")
        normalized = self._representation(
            obs_0=observations["obs_0"],
            obs_1=observations["obs_1"],
            as_of_available_at=value["as_of_available_at"],
        )
        if value != normalized:
            raise ProtocolViolation("W18 OOD state contains noncanonical claims")
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
            raise ProtocolViolation("W18 OOD seal binding mismatch")
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
    def _latest_public_pair(episode: PrivateEpisode) -> tuple[float, float]:
        values: dict[str, float] = {}
        for event in episode.public_history.events:
            if (
                event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.payload.get("channel_id") in {"obs_0", "obs_1"}
            ):
                values[str(event.payload["channel_id"])] = float(
                    event.payload["value"]
                )
        if set(values) != {"obs_0", "obs_1"}:
            raise ProtocolViolation("W18 initialization requires both public channels")
        return values["obs_0"], values["obs_1"]

    def initialize_public_episode(self, episode: PrivateEpisode) -> SealedState:
        if type(episode) is not PrivateEpisode:
            raise ProtocolViolation("W18 initializer requires PrivateEpisode")
        if episode.environment_key != self.world.environment_key:
            raise ProtocolViolation("W18 episode belongs to another world")
        obs_0, obs_1 = self._latest_public_pair(episode)
        return self._seal(
            self._representation(
                obs_0=obs_0,
                obs_1=obs_1,
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
            raise ProtocolViolation("W18 update must advance the availability cut")
        values: dict[str, float] = {}
        for event in delta.events:
            if (
                event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.available_at == delta.advance_to
                and event.payload.get("channel_id") in {"obs_0", "obs_1"}
            ):
                values[str(event.payload["channel_id"])] = float(
                    event.payload["value"]
                )
        if set(values) != {"obs_0", "obs_1"}:
            raise ProtocolViolation("W18 update requires a complete new public pair")
        value = self._representation(
            obs_0=values["obs_0"],
            obs_1=values["obs_1"],
            as_of_available_at=delta.advance_to,
        )
        return self._seal(
            value,
            operation="update",
            parent_state_hash=state.record.state_hash,
            delta_digest=digest_json(delta.to_wire()),
        )

    @staticmethod
    def _diagnostic_posterior(value: dict[str, Any]) -> dict[str, float]:
        posterior = value["mechanism_posterior"]
        return {
            "C0": float(posterior["C0"]),
            "C1": float(posterior["C1"]),
            "unknown": float(posterior["C2"] + posterior["Cdev"]),
        }

    def diagnose(
        self, state: SealedState, query: DiagnosisQuery, *, query_seed: int
    ) -> TrueStateHeadExecution:
        del query_seed
        value = self._verify(state)
        if query.label_catalog != self.world.catalog.diagnostic_labels:
            raise ProtocolViolation("W18 diagnosis label catalog mismatch")
        abstain = value["public_ood_attribution"] == "OOD_ATTRIBUTABLE"
        response = DiagnoseResponse(
            DiagnosisResult(
                ResultStatus.OK,
                self._diagnostic_posterior(value),
                {
                    "baseline_id": "B01",
                    "eligibility": "upper_bound_only",
                    "public_evidence_only": True,
                    "public_ood_attribution": value["public_ood_attribution"],
                    "abstain": abstain,
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
        allowed = {"obs_0", "obs_1"}
        if not query.requested_observables or not set(query.requested_observables) <= allowed:
            raise ProtocolViolation("W18 rollout requested an unknown observable")
        observations = value["latest_observations"]
        oracle = self.world.public_state_counterfactual(
            observations["obs_0"],
            observations["obs_1"],
            query.plan,
            query.horizon,
        )
        components = oracle.observation_distribution["components"]
        predictions = {
            channel: {
                "family": "bounded-affine-mixture",
                "components": [
                    {
                        "label": component["public_component"],
                        "weight": float(component["weight"]),
                        "values": [
                            float(step[f"{channel}_mean"])
                            for step in component["steps"]
                        ],
                    }
                    for component in components
                ],
            }
            for channel in query.requested_observables
        }
        abstain = value["public_ood_attribution"] == "OOD_ATTRIBUTABLE"
        response = RolloutResponse(
            RolloutResult(
                ResultStatus.OK,
                observable_predictions=predictions,
                utility_prediction={
                    "family": "public-reference-mixture",
                    "value": float(oracle.expected_utility),
                    "recommendation": "abstain" if abstain else "evaluate-actions",
                },
                metadata={
                    "baseline_id": "B01",
                    "eligibility": "upper_bound_only",
                    "public_evidence_only": True,
                    "public_ood_attribution": value["public_ood_attribution"],
                    "abstain": abstain,
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


def _policy(world: W18World, action: str | None) -> ActionPlan:
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


def _attributable_delta() -> VisibleDelta:
    events = tuple(
        sorted(
            (
                CandidateVisibleEvent(
                    kind=EventKind.OBSERVATION_AVAILABLE,
                    occurred_at=1,
                    available_at=1,
                    event_uid=f"w18-attributable-{channel}",
                    payload={"channel_id": channel, "value": value},
                    collected_at=1,
                )
                for channel, value in (("obs_0", 0.8), ("obs_1", 0.0))
            ),
            key=event_sort_key,
        )
    )
    return VisibleDelta(1, events)


def run_w18_ood_slice() -> dict[str, Any]:
    world = W18World()
    probe = W18PublicOODProbe(world)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    policies = (_policy(world, None), _policy(world, "A1"))
    aliases = ("no_new_action", "do_A1")
    utility_digest = digest_json(["W18", "public-reference-utility", 4])

    unseen_alias, known_alias = world.irreducible_alias_pair(seed=1803)
    unseen_state = probe.initialize_public_episode(unseen_alias)
    known_state = probe.initialize_public_episode(known_alias)
    initial_diagnosis = probe.diagnose(unseen_state, diagnosis_query, query_seed=1)
    initial_rollouts: dict[str, Any] = {}
    initial_consumed = {initial_diagnosis.consumed_state_hash}
    for alias, policy in zip(aliases, policies, strict=True):
        execution = probe.rollout(
            unseen_state,
            RolloutQuery(4, policy, ("obs_0", "obs_1"), utility_digest),
            query_seed=2,
        )
        initial_consumed.add(execution.consumed_state_hash)
        initial_rollouts[alias] = execution.to_wire()

    delta = _attributable_delta()
    updated = probe.update_public(unseen_state, delta, inference_seed=3)
    updated_diagnosis = probe.diagnose(updated, diagnosis_query, query_seed=4)
    updated_rollouts: dict[str, Any] = {}
    updated_consumed = {updated_diagnosis.consumed_state_hash}
    for alias, policy in zip(aliases, policies, strict=True):
        execution = probe.rollout(
            updated,
            RolloutQuery(4, policy, ("obs_0", "obs_1"), utility_digest),
            query_seed=5,
        )
        updated_consumed.add(execution.consumed_state_hash)
        updated_rollouts[alias] = execution.to_wire()

    extreme = world.known_extreme_fixture(seed=1805)
    extreme_state = probe.initialize_public_episode(extreme)
    extreme_diagnosis = probe.diagnose(
        extreme_state, diagnosis_query, query_seed=6
    )
    initial_probabilities = initial_diagnosis.response.result.probabilities
    updated_probabilities = updated_diagnosis.response.result.probabilities
    extreme_probabilities = extreme_diagnosis.response.result.probabilities

    return {
        "protocol": "ucm-phase2-w18-public-ood-slice/1",
        "benchmark_status": "PRE-FREEZE",
        "experiment_status": "NOT_COUNT_ELIGIBLE",
        "manifest": probe.manifest.to_wire(),
        "irreducible_alias": {
            "unseen_private_tag": world.attribution_tag(unseen_alias),
            "known_private_tag": world.attribution_tag(known_alias),
            "unseen_state_hash": unseen_state.record.state_hash,
            "known_state_hash": known_state.record.state_hash,
            "diagnosis": initial_diagnosis.to_wire(),
            "rollouts": initial_rollouts,
        },
        "public_ood_update": {
            "delta_digest": digest_json(delta.to_wire()),
            "new_state_hash": updated.record.state_hash,
            "parent_state_hash": updated.record.parent_state_hash,
            "diagnosis": updated_diagnosis.to_wire(),
            "rollouts": updated_rollouts,
        },
        "known_extreme_control": {
            "state_hash": extreme_state.record.state_hash,
            "diagnosis": extreme_diagnosis.to_wire(),
        },
        "assertions": {
            "irreducible_private_aliases_share_state": unseen_state.record.state_hash
            == known_state.record.state_hash,
            "irreducible_private_alias_not_forced_ood": (
                initial_probabilities["unknown"] < 0.90
                and initial_diagnosis.response.result.metadata["abstain"] is False
            ),
            "initial_heads_consumed_one_hash": initial_consumed
            == {unseen_state.record.state_hash},
            "public_ood_update_changed_state": updated.record.state_hash
            != unseen_state.record.state_hash,
            "public_ood_update_parent_link_closed": updated.record.parent_state_hash
            == unseen_state.record.state_hash,
            "public_ood_update_reaches_unknown": math.isclose(
                updated_probabilities["unknown"],
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            ),
            "public_ood_heads_abstain": all(
                row["response"]["result"]["metadata"]["abstain"] is True
                and row["response"]["result"]["utility_prediction"][
                    "recommendation"
                ]
                == "abstain"
                for row in updated_rollouts.values()
            ),
            "updated_heads_consumed_new_hash": updated_consumed
            == {updated.record.state_hash},
            "known_extreme_not_rejected": (
                extreme_probabilities["C0"] == 1.0
                and extreme_diagnosis.response.result.metadata["abstain"] is False
            ),
        },
    }


def _main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Run the PRE-FREEZE W18 public-OOD slice."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = run_w18_ood_slice()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(artifact))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "W18OODProbeManifest",
    "W18PublicOODProbe",
    "run_w18_ood_slice",
]


if __name__ == "__main__":
    raise SystemExit(_main())
