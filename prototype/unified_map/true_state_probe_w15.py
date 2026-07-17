"""W15 identifiable-versus-nonidentified causal vertical slice."""

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
from .worlds.base import PrivateEpisode, WorldSplit
from .worlds.w15 import World15A, World15B


_STATE_PROTOCOL = "ucm-phase2-causal-state-w15/1"
_STATE_SCHEMA = "ucm-phase2-causal-state-w15-state/1"


@dataclass(frozen=True, slots=True)
class W15CausalProbeManifest:
    probe_id: str = "phase2-causal-upper-bound-w15"
    baseline_id: str = "B01"
    world_slot: str = "W15"
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
            "panel_semantics": {
                "W15A": "judge-known state with identified randomized effect",
                "W15B": "public equivalence class; private SCM excluded",
            },
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


class W15SharedCausalProbe:
    """One state contract that refuses to turn association into intervention."""

    def __init__(
        self,
        identifiable: World15A | None = None,
        nonidentified: World15B | None = None,
    ) -> None:
        self.identifiable = identifiable or World15A()
        self.nonidentified = nonidentified or World15B()
        self.manifest = W15CausalProbeManifest()
        self._candidate_bundle_digest = self.manifest.digest
        self._model_digest = digest_json(
            {
                "protocol": "ucm-causal-model-binding/1",
                "world_slot": "W15",
                "identified_entrypoint": (
                    "World15A.judge_true_state_counterfactual"
                ),
                "nonidentified_entrypoint": (
                    "World15B.identified_set_counterfactual"
                ),
                "private_scm_policy": "excluded-from-W15B-state-and-scoring",
            }
        )
        self._scope_digest = digest_json(
            {
                "protocol": "ucm-true-state-scope/1",
                "world_slot": "W15",
                "catalogs": {
                    "W15A": self.identifiable.catalog.digest,
                    "W15B": self.nonidentified.catalog.digest,
                },
            }
        )

    @staticmethod
    def _identified_representation(
        *, severity: float, confounder: int, as_of_available_at: int
    ) -> dict[str, Any]:
        if type(severity) not in {int, float} or not math.isfinite(float(severity)):
            raise ProtocolViolation("W15A upper-bound severity must be finite")
        if type(confounder) is not int or confounder not in {0, 1}:
            raise ProtocolViolation("W15A upper-bound confounder must be zero or one")
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W15A upper-bound cut must be an integer")
        return {
            "protocol": _STATE_PROTOCOL,
            "panel": "W15A",
            "as_of_available_at": as_of_available_at,
            "severity": float(severity),
            "confounder": confounder,
            "identification_status": "identified-by-randomized-anchor",
            "treatment_effect": -0.35,
        }

    @staticmethod
    def _nonidentified_representation(*, as_of_available_at: int) -> dict[str, Any]:
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W15B upper-bound cut must be an integer")
        return {
            "protocol": _STATE_PROTOCOL,
            "panel": "W15B",
            "as_of_available_at": as_of_available_at,
            "diagnostic_posterior": {"C0": 0.5, "C1": 0.5},
            "causal_model_posterior": {"Mplus": 0.5, "Mminus": 0.5},
            "identification_status": "unsupported-point-effect",
            "ate_identified_set": [-1.0, 1.0],
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
            raise ProtocolViolation("W15 query requires SealedState")
        payload = state.candidate_input.payload
        if (
            payload.codec != "canonical-json-v1"
            or payload.schema_version != _STATE_SCHEMA
            or payload.state_class is not StateClass.DYNAMIC_SHARED
        ):
            raise ProtocolViolation("W15 causal payload identity mismatch")
        try:
            value = json.loads(payload.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("W15 causal payload is invalid") from exc
        if type(value) is not dict:
            raise ProtocolViolation("W15 causal payload must be an object")
        panel = value.get("panel")
        if panel == "W15A":
            expected = {
                "protocol",
                "panel",
                "as_of_available_at",
                "severity",
                "confounder",
                "identification_status",
                "treatment_effect",
            }
            if set(value) != expected:
                raise ProtocolViolation("W15A causal payload is not closed")
            normalized = cls._identified_representation(
                severity=value["severity"],
                confounder=value["confounder"],
                as_of_available_at=value["as_of_available_at"],
            )
        elif panel == "W15B":
            expected = {
                "protocol",
                "panel",
                "as_of_available_at",
                "diagnostic_posterior",
                "causal_model_posterior",
                "identification_status",
                "ate_identified_set",
            }
            if set(value) != expected:
                raise ProtocolViolation("W15B causal payload is not closed")
            normalized = cls._nonidentified_representation(
                as_of_available_at=value["as_of_available_at"]
            )
        else:
            raise ProtocolViolation("W15 causal panel is unknown")
        if value != normalized:
            raise ProtocolViolation("W15 causal payload contains noncanonical claims")
        return normalized

    def _catalog_digest(self, panel: str) -> str:
        if panel == "W15A":
            return self.identifiable.catalog.digest
        if panel == "W15B":
            return self.nonidentified.catalog.digest
        raise ProtocolViolation("unknown W15 panel")

    def _verify(self, state: SealedState) -> dict[str, Any]:
        value = self._decode(state)
        record = state.record
        if (
            record.candidate_bundle_digest != self._candidate_bundle_digest
            or record.model_digest != self._model_digest
            or record.scope_digest != self._scope_digest
            or record.catalog_digest != self._catalog_digest(value["panel"])
            or record.as_of_available_at != value["as_of_available_at"]
        ):
            raise ProtocolViolation("W15 causal seal binding mismatch")
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
            catalog_digest=self._catalog_digest(value["panel"]),
            as_of_available_at=value["as_of_available_at"],
            operation=operation,
            parent_state_hash=parent_state_hash,
            delta_digest=delta_digest,
        )

    def initialize_identified_true_state(
        self,
        *,
        severity: float,
        confounder: int,
        as_of_available_at: int = 0,
    ) -> SealedState:
        return self._seal(
            self._identified_representation(
                severity=severity,
                confounder=confounder,
                as_of_available_at=as_of_available_at,
            ),
            operation="initialize",
        )

    def initialize_nonidentified_private(self, episode: PrivateEpisode) -> SealedState:
        if type(episode) is not PrivateEpisode:
            raise ProtocolViolation("W15B initializer requires PrivateEpisode")
        if episode.environment_key != self.nonidentified.environment_key:
            raise ProtocolViolation("W15B episode belongs to another panel")
        if set(episode.hidden_state_at_cut) != {"latent_confounder"} or set(
            episode.invariant_parameters
        ) != {"private_scm"}:
            raise ProtocolViolation("W15B episode lacks the private red-team fields")
        if episode.oracle_anchor.get("point_effect_scoring") is not False:
            raise ProtocolViolation("W15B episode lacks nonidentification authority")
        return self._seal(
            self._nonidentified_representation(
                as_of_available_at=episode.public_history.as_of_available_at
            ),
            operation="initialize",
        )

    def update_identified_private(
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
        if prior["panel"] != "W15A":
            raise ProtocolViolation("only W15A has a dynamic update in this slice")
        if type(delta) is not VisibleDelta or delta.advance_to <= prior["as_of_available_at"]:
            raise ProtocolViolation("W15A update must advance the availability cut")
        if not any(
            event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_0"
            and event.available_at == delta.advance_to
            for event in delta.events
        ):
            raise ProtocolViolation("W15A update requires a newly available outcome")
        if set(hidden_state_at_cut) != {"severity"} or set(
            invariant_parameters
        ) != {"confounder"}:
            raise ProtocolViolation("W15A update lacks complete next judge state")
        if invariant_parameters["confounder"] != prior["confounder"]:
            raise ProtocolViolation("W15A invariant confounder changed")
        value = self._identified_representation(
            severity=hidden_state_at_cut["severity"],
            confounder=invariant_parameters["confounder"],
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
        catalog = (
            self.identifiable.catalog if value["panel"] == "W15A" else self.nonidentified.catalog
        )
        if query.label_catalog != catalog.diagnostic_labels:
            raise ProtocolViolation("W15 diagnosis label catalog mismatch")
        if value["panel"] == "W15A":
            low = float(value["severity"] < 0.80)
            probabilities = {"C0": low, "C1": 1.0 - low}
        else:
            probabilities = dict(value["diagnostic_posterior"])
        response = DiagnoseResponse(
            DiagnosisResult(
                ResultStatus.OK,
                probabilities,
                {
                    "baseline_id": "B01",
                    "privileged": True,
                    "eligibility": "upper_bound_only",
                    "panel": value["panel"],
                    "identification_status": value["identification_status"],
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
        if value["panel"] == "W15A":
            if query.requested_observables != ("obs_0",):
                raise ProtocolViolation("W15A probe rollout supports obs_0")
            oracle = self.identifiable.judge_true_state_counterfactual(
                {"severity": value["severity"]},
                {"confounder": value["confounder"]},
                query.plan,
                query.horizon,
            )
            steps = oracle.observation_distribution["steps"]
            observable_predictions = {
                "obs_0": {
                    "family": "point_mass",
                    "horizon": query.horizon,
                    "values": [float(step["obs_0_mean"]) for step in steps],
                }
            }
            utility_prediction = {
                "family": "point_mass",
                "value": float(oracle.expected_utility),
            }
        else:
            if query.requested_observables != ("obs_1",):
                raise ProtocolViolation("W15B probe rollout supports obs_1")
            oracle = self.nonidentified.identified_set_counterfactual(
                query.plan, query.horizon
            )
            observation = oracle.observation_distribution
            outcome = oracle.outcome_distribution
            observable_predictions = {
                "obs_1": {
                    "family": "public-equivalence-mixture",
                    "support": list(observation["obs_1_support"]),
                    "probabilities": list(observation["obs_1_probabilities"]),
                    "mean": float(observation["obs_1_mean"]),
                }
            }
            utility_prediction = {
                "family": "identified_set",
                "support": list(outcome["policy_utility_support"]),
                "ate_identified_set": list(outcome["ate_identified_set"]),
                "recommendation": "abstain",
            }
        response = RolloutResponse(
            RolloutResult(
                ResultStatus.OK,
                observable_predictions=observable_predictions,
                utility_prediction=utility_prediction,
                metadata={
                    "baseline_id": "B01",
                    "privileged": True,
                    "eligibility": "upper_bound_only",
                    "panel": value["panel"],
                    "identification_status": value["identification_status"],
                    "private_scm_used": False,
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


def _policy(world: World15A | World15B, horizon: int, action: str | None) -> ActionPlan:
    policies = world.policy_set(horizon)
    if action is None:
        return next(policy for policy in policies if policy.kind is PlanKind.NO_NEW_ACTION)
    return next(
        policy
        for policy in policies
        if len(policy.actions) == 1 and policy.actions[0].action_id == action
    )


def _identified_response_delta() -> tuple[VisibleDelta, float]:
    next_severity = World15A._step(0.90, 0, True)
    events = (
        CandidateVisibleEvent(
            kind=EventKind.PERFORMED_TREATMENT,
            occurred_at=1,
            available_at=1,
            event_uid="w15a-factual-a1",
            payload={"action_id": "A1", "parameters": {}},
            collected_at=None,
        ),
        CandidateVisibleEvent(
            kind=EventKind.OBSERVATION_AVAILABLE,
            occurred_at=1,
            available_at=1,
            event_uid="w15a-factual-severity",
            payload={"channel_id": "obs_0", "value": next_severity},
            collected_at=1,
        ),
    )
    return VisibleDelta(1, tuple(sorted(events, key=event_sort_key))), next_severity


def run_w15_causal_slice() -> dict[str, Any]:
    identifiable = World15A()
    nonidentified = World15B()
    probe = W15SharedCausalProbe(identifiable, nonidentified)
    diagnosis_query = DiagnosisQuery(("C0", "C1"))

    state_a = probe.initialize_identified_true_state(severity=0.90, confounder=0)
    diagnosis_a = probe.diagnose(state_a, diagnosis_query, query_seed=1)
    policies_a = (_policy(identifiable, 4, None), _policy(identifiable, 4, "A1"))
    names_a = ("no_new_action", "do_A1")
    rollouts_a: dict[str, Any] = {}
    consumed_a = {diagnosis_a.consumed_state_hash}
    executions_a: list[TrueStateHeadExecution] = []
    for name, policy in zip(names_a, policies_a, strict=True):
        execution = probe.rollout(
            state_a,
            RolloutQuery(
                4,
                policy,
                ("obs_0",),
                digest_json(["W15A", "severity-utility", 4]),
            ),
            query_seed=2,
        )
        consumed_a.add(execution.consumed_state_hash)
        executions_a.append(execution)
        rollouts_a[name] = execution.to_wire()
    first_no_action = executions_a[0].response.result.observable_predictions[
        "obs_0"
    ]["values"][0]
    first_do_a1 = executions_a[1].response.result.observable_predictions["obs_0"][
        "values"
    ][0]
    randomized_episodes = tuple(
        identifiable.generate_episode(WorldSplit.TRAIN, 1881, index)
        for index in range(400)
    )
    randomized_effect = identifiable.estimate_randomized_anchor_effect(
        randomized_episodes
    )

    delta, next_severity = _identified_response_delta()
    updated_a = probe.update_identified_private(
        state_a,
        delta,
        hidden_state_at_cut={"severity": next_severity},
        invariant_parameters={"confounder": 0},
        inference_seed=3,
    )
    updated_diagnosis_a = probe.diagnose(
        updated_a, diagnosis_query, query_seed=4
    )
    updated_rollout_a = probe.rollout(
        updated_a,
        RolloutQuery(
            4,
            policies_a[0],
            ("obs_0",),
            digest_json(["W15A", "severity-utility", 4]),
        ),
        query_seed=5,
    )

    twin_plus, twin_minus = nonidentified.nonidentified_twin_fixture(
        seed=757, confounder=0
    )
    state_b_plus = probe.initialize_nonidentified_private(twin_plus)
    state_b_minus = probe.initialize_nonidentified_private(twin_minus)
    diagnosis_b = probe.diagnose(state_b_plus, diagnosis_query, query_seed=6)
    policies_b = (_policy(nonidentified, 1, None), _policy(nonidentified, 1, "A1"))
    names_b = ("no_new_action", "do_A1")
    rollouts_b: dict[str, Any] = {}
    consumed_b = {diagnosis_b.consumed_state_hash}
    for name, policy in zip(names_b, policies_b, strict=True):
        execution = probe.rollout(
            state_b_plus,
            RolloutQuery(
                1,
                policy,
                ("obs_1",),
                digest_json(["W15B", "identified-set", 1]),
            ),
            query_seed=7,
        )
        consumed_b.add(execution.consumed_state_hash)
        rollouts_b[name] = execution.to_wire()

    return {
        "protocol": "ucm-phase2-w15-causal-separation-slice/1",
        "benchmark_status": "PRE-FREEZE",
        "experiment_status": "NOT_COUNT_ELIGIBLE",
        "manifest": probe.manifest.to_wire(),
        "identified_panel": {
            "initial_state_hash": state_a.record.state_hash,
            "diagnosis": diagnosis_a.to_wire(),
            "rollouts": rollouts_a,
            "first_step_do_effect": first_do_a1 - first_no_action,
            "public_randomized_anchor_effect_estimate": randomized_effect,
            "update": {
                "delta_digest": digest_json(delta.to_wire()),
                "new_state_hash": updated_a.record.state_hash,
                "parent_state_hash": updated_a.record.parent_state_hash,
                "diagnosis": updated_diagnosis_a.to_wire(),
                "no_new_action_rollout": updated_rollout_a.to_wire(),
            },
        },
        "nonidentified_panel": {
            "plus_private_effect": nonidentified.judge_structural_effect(twin_plus),
            "minus_private_effect": nonidentified.judge_structural_effect(twin_minus),
            "plus_state_hash": state_b_plus.record.state_hash,
            "minus_state_hash": state_b_minus.record.state_hash,
            "diagnosis": diagnosis_b.to_wire(),
            "rollouts": rollouts_b,
        },
        "assertions": {
            "identified_heads_consumed_one_hash": consumed_a
            == {state_a.record.state_hash},
            "identified_do_effect_has_beneficial_sign": math.isclose(
                first_do_a1 - first_no_action,
                -0.35,
                rel_tol=0.0,
                abs_tol=1e-12,
            ),
            "public_randomized_anchor_has_beneficial_sign": randomized_effect
            < -0.15,
            "identified_update_parent_link_closed": updated_a.record.parent_state_hash
            == state_a.record.state_hash,
            "identified_updated_heads_consumed_new_hash": {
                updated_diagnosis_a.consumed_state_hash,
                updated_rollout_a.consumed_state_hash,
            }
            == {updated_a.record.state_hash},
            "nonidentified_private_twins_share_state": state_b_plus.record.state_hash
            == state_b_minus.record.state_hash,
            "nonidentified_private_effects_are_opposite": (
                nonidentified.judge_structural_effect(twin_plus) == 1.0
                and nonidentified.judge_structural_effect(twin_minus) == -1.0
            ),
            "nonidentified_heads_consumed_one_hash": consumed_b
            == {state_b_plus.record.state_hash},
            "nonidentified_rollouts_abstain_with_full_effect_set": all(
                row["response"]["result"]["utility_prediction"][
                    "ate_identified_set"
                ]
                == [-1.0, 1.0]
                and row["response"]["result"]["utility_prediction"][
                    "recommendation"
                ]
                == "abstain"
                for row in rollouts_b.values()
            ),
        },
    }


def _main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Run the PRE-FREEZE W15 causal-separation slice."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = run_w15_causal_slice()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(artifact))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "W15CausalProbeManifest",
    "W15SharedCausalProbe",
    "run_w15_causal_slice",
]


if __name__ == "__main__":
    raise SystemExit(_main())
