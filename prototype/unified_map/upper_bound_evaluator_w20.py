"""Patient-bound PRE-FREEZE upper-bound evaluator for W20 feedback memory.

The estimand is deliberately narrow: a sealed, rounded public posterior over
``x`` plus public exposure memory is used for diagnosis and for policy-indexed
marginal observation moments / expected utility.  The bundle does not claim a
joint temporal law, calibration, a minimal quotient, candidate performance, or
freeze authority.  Raw history and evidence-count provenance remain auditable,
but are excluded from behavioral state identity: an extra nonpredictive Q1 at
the same cut now aliases to the same state when every frozen horizon-4 policy
has identical semantics.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .oracle_certification import oracle_output_wire
from .metrics import PairProbe, classify_pair, treatment_regret
from .schema import (
    DiagnosisQuery,
    EventKind,
    RolloutQuery,
    event_sort_key,
)
from .state import SealedState, StateClass, StatePayload
from .true_state_probe_w20 import (
    W20PublicFeedbackProbe,
    _a1_response_delta,
    _policy,
    run_w20_feedback_slice,
)
from .upper_bound_evaluator import (
    STATUS_CHAIN,
    _cell_root,
    _head_wire,
    _state_binding,
    compute_upper_bound_bundle_root,
)
from .worlds.w01 import _check_event, _observation_event
from .worlds.w20 import W20World, _rounded


PROTOCOL = "ucm-pre-freeze-upper-bound-sanity/1"
DEFAULT_W20_ARTIFACT = Path(
    "results/unified_map/pre_freeze/20260717-w20-feedback-memory-probe/vertical-slice.json"
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_ALIASES = ("no_new_action", "do_A1", "do_A2")
_BEHAVIOR_STATE_PROTOCOL = "ucm-phase2-feedback-behavior-state-w20/1"
_BEHAVIOR_STATE_SCHEMA = "ucm-phase2-feedback-behavior-state-w20-state/1"
_FORMAL_BLOCKERS = [
    "not-a-frozen-expected-cell-corpus",
    "patient-bound-rounded-state-projection-only",
    "marginal-moments-no-joint-temporal-law",
    "combined-action-response-update-not-action-only",
    "minimal-behavioral-quotient-not-proved",
    "source-distinct-sealed-state-reference-not-collected",
    "runtime-document-oracle-method-drift",
    "privileged-upper-bound-only",
]

_PAIR_THRESHOLDS = {
    "candidate_same_epsilon": 0.008,
    "candidate_split_delta": 0.38,
    "oracle_distinguishable_delta": 0.38,
    "oracle_equivalent_epsilon": 0.008,
    "catastrophic_margin": 0.80,
}


@dataclass(frozen=True, slots=True)
class _W20BehavioralProbeManifest:
    """Evaluator-local manifest for the repaired behavioral state identity."""

    probe_id: str = "phase2-public-feedback-behavior-upper-bound-w20"
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
            "state_schema": _BEHAVIOR_STATE_SCHEMA,
            "state_evidence": "public-bayesian-behavioral-sufficient-statistics",
            "state_channels": ["posterior_x", "exposure_memory_r"],
            "audit_provenance_outside_state_identity": [
                "public_history_digest",
                "raw_evidence_count",
            ],
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


class _W20BehavioralFeedbackProbe(W20PublicFeedbackProbe):
    """W20 probe whose hash contains only behavior-bearing state fields.

    ``W20World.public_belief_counterfactual`` retains a legacy positive
    ``evidence_count`` argument but does not consume it after validation.  The
    inherited heads therefore receive the fixed validation sentinel ``1``
    from :meth:`_decode`; the raw count is reconstructed independently into
    report provenance and never enters the sealed payload or state hash.
    """

    def __init__(self, world: W20World | None = None) -> None:
        super().__init__(world)
        self.manifest = _W20BehavioralProbeManifest()
        self._candidate_bundle_digest = self.manifest.digest
        self._model_digest = digest_json(
            {
                "protocol": "ucm-public-feedback-behavior-model-binding/1",
                "world_slot": "W20",
                "filter": "covariance-form-incremental",
                "rollout": "W20World.public_belief_counterfactual",
                "behavior_state_closure": [
                    "as_of_available_at",
                    "posterior_mean",
                    "posterior_variance",
                    "exposure_memory",
                ],
                "excluded_audit_provenance": [
                    "public_history_digest",
                    "raw_evidence_count",
                ],
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
            raise ProtocolViolation("W20 audit evidence count must be positive")
        if type(as_of_available_at) is not int:
            raise ProtocolViolation("W20 public cut must be an integer")
        return {
            "protocol": _BEHAVIOR_STATE_PROTOCOL,
            "world_slot": "W20",
            "as_of_available_at": as_of_available_at,
            "posterior_mean": _rounded(mean),
            "posterior_variance": _rounded(variance),
            "exposure_memory": _rounded(exposure),
        }

    @staticmethod
    def _payload(value: dict[str, Any]) -> StatePayload:
        return StatePayload.from_json(
            value,
            schema_version=_BEHAVIOR_STATE_SCHEMA,
            state_class=StateClass.DYNAMIC_SHARED,
        )

    @classmethod
    def _decode(cls, state: SealedState) -> dict[str, Any]:
        if type(state) is not SealedState:
            raise ProtocolViolation("W20 query requires SealedState")
        payload = state.candidate_input.payload
        if (
            payload.codec != "canonical-json-v1"
            or payload.schema_version != _BEHAVIOR_STATE_SCHEMA
            or payload.state_class is not StateClass.DYNAMIC_SHARED
        ):
            raise ProtocolViolation("W20 behavior payload identity mismatch")
        try:
            value = json.loads(payload.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("W20 behavior payload is invalid") from exc
        expected = {
            "protocol",
            "world_slot",
            "as_of_available_at",
            "posterior_mean",
            "posterior_variance",
            "exposure_memory",
        }
        if type(value) is not dict or set(value) != expected:
            raise ProtocolViolation("W20 behavior payload is not closed")
        normalized = cls._representation(
            mean=value["posterior_mean"],
            variance=value["posterior_variance"],
            exposure=value["exposure_memory"],
            evidence_count=1,
            as_of_available_at=value["as_of_available_at"],
        )
        if value != normalized:
            raise ProtocolViolation("W20 behavior state contains noncanonical claims")
        # Compatibility sentinel for the world's legacy validation-only
        # argument.  It is not serialized, sealed, hashed, or reported as
        # patient state.
        return {**normalized, "evidence_count": 1}


def _oracle_wire(value: Any) -> dict[str, Any]:
    return oracle_output_wire(value, include_numerical_diagnostics=False)


def _read_canonical(path: Path, label: str) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(f"{label} is unavailable: {path}") from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} is not JSON") from exc
    if canonical_json_bytes(decoded) != raw:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    return raw


def _representation(state: Any) -> dict[str, Any]:
    binding = _state_binding(state)
    value = binding["payload"]["representation"]
    expected = {
        "protocol",
        "world_slot",
        "as_of_available_at",
        "posterior_mean",
        "posterior_variance",
        "exposure_memory",
    }
    if type(value) is not dict or set(value) != expected:
        raise ProtocolViolation("W20 state representation is not closed")
    return value


def _rollout_projection(oracle: dict[str, Any]) -> dict[str, Any]:
    components = oracle["observation_distribution"]["components"]
    return {
        "family": "public-posterior-branch-mixture",
        "components": [
            {
                "branch_action": component["branch_action"],
                "weight": component["weight"],
                "means": [step["mean"] for step in component["steps"]],
                "variances": [
                    step["observation_variance"] for step in component["steps"]
                ],
            }
            for component in components
        ],
    }


def _policy_panel(
    world: W20World,
    probe: W20PublicFeedbackProbe,
    state: Any,
    *,
    query_seed: int,
) -> dict[str, Any]:
    representation = _representation(state)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    diagnosis = probe.diagnose(state, diagnosis_query, query_seed=query_seed)
    expected_probabilities = {
        "C0": float(representation["exposure_memory"] < 0.75),
        "C1": float(representation["exposure_memory"] >= 0.75),
    }
    diagnosis_wire = _head_wire(diagnosis, diagnosis_query)
    if (
        diagnosis_wire["execution"]["response"]["result"]["probabilities"]
        != expected_probabilities
    ):
        raise ProtocolViolation("W20 diagnosis does not follow sealed exposure memory")

    policies = (
        _policy(world, None),
        _policy(world, "A1"),
        _policy(world, "A2"),
    )
    utility_digest = digest_json(["W20", "posterior-quadratic", 4])
    heads: dict[str, Any] = {}
    oracles: dict[str, Any] = {}
    projections: dict[str, Any] = {}
    utilities: dict[str, float] = {}
    first_marginal_means: dict[str, float] = {}
    consumed = {diagnosis.consumed_state_hash}
    for offset, (alias, policy) in enumerate(
        zip(_ALIASES, policies, strict=True), start=1
    ):
        query = RolloutQuery(4, policy, ("obs_0",), utility_digest)
        execution = probe.rollout(
            state,
            query,
            query_seed=query_seed + offset,
        )
        head = _head_wire(execution, query)
        oracle = _oracle_wire(
            world.public_belief_counterfactual(
                representation["posterior_mean"],
                representation["posterior_variance"],
                representation["exposure_memory"],
                1,
                policy,
                4,
            )
        )
        predicted = head["execution"]["response"]["result"]
        projection = _rollout_projection(oracle)
        utility = float(oracle["expected_utility"])
        if predicted["observable_predictions"]["obs_0"] != projection or predicted[
            "utility_prediction"
        ] != {
            "family": "posterior-expected-quadratic-cost",
            "value": utility,
        }:
            raise ProtocolViolation(
                f"W20 {alias} head is not the sealed-state oracle projection"
            )
        consumed.add(execution.consumed_state_hash)
        heads[alias] = head
        oracles[alias] = oracle
        projections[alias] = {
            "marginal_moments_exact": True,
            "max_marginal_moment_error": 0.0,
            "expected_utility_exact": True,
            "joint_temporal_law_scored": False,
        }
        utilities[alias] = utility
        first_marginal_means[alias] = sum(
            component["weight"] * component["means"][0]
            for component in projection["components"]
        )
    if consumed != {state.record.state_hash}:
        raise ProtocolViolation("W20 task heads did not consume one shared state")
    best = max(_ALIASES, key=lambda alias: utilities[alias])
    regret_value = treatment_regret(
        [[utilities[alias] for alias in _ALIASES]],
        [[utilities[alias] for alias in _ALIASES]],
        catastrophic_margin=_PAIR_THRESHOLDS["catastrophic_margin"],
    )
    regret = asdict(regret_value)
    regret["chosen_actions"] = list(regret_value.chosen_actions)
    regret["catastrophic_margin"] = _PAIR_THRESHOLDS["catastrophic_margin"]
    if regret["worst_regret"] != 0.0:
        raise ProtocolViolation("W20 exact policy panel has nonzero treatment regret")
    return {
        "state_hash": state.record.state_hash,
        "diagnosis_head": diagnosis_wire,
        "candidate_heads": heads,
        "sealed_state_oracles": oracles,
        "projection_checks": projections,
        "utilities": utilities,
        "first_marginal_means": first_marginal_means,
        "treatment_regret_metric": regret,
        "panel_expected_utility_argmax": best,
        "all_heads_consumed_one_state": True,
        "source_distinct_reference_oracle_claimed": False,
    }


def _history_evidence_provenance(
    world: W20World,
    episode: Any,
) -> dict[str, Any]:
    """Bind raw public history/evidence without making it state identity."""

    _mean, _variance, _exposure, raw_evidence_count = world._production_posterior(
        episode
    )
    evidence_events = [
        event
        for event in episode.public_history.events
        if (
            event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") in {"obs_0", "obs_1"}
        )
        or (
            event.kind is EventKind.PERFORMED_TREATMENT
            and event.payload.get("action_id") in {"A1", "A2"}
        )
    ]
    evidence_wires = [event.to_wire() for event in evidence_events]
    if len(evidence_events) != raw_evidence_count:
        raise ProtocolViolation("W20 evidence provenance count does not close")
    return {
        "protocol": "ucm-w20-history-evidence-provenance/1",
        "public_history_digest": episode.public_history.digest,
        "as_of_available_at": episode.public_history.as_of_available_at,
        "public_event_count": len(episode.public_history.events),
        "raw_evidence_count": raw_evidence_count,
        "evidence_event_uids": [event.event_uid for event in evidence_events],
        "evidence_events_digest": digest_json(evidence_wires),
        "raw_history_in_state_identity": False,
        "raw_evidence_count_in_state_identity": False,
        "behavior_state_identity_fields": [
            "as_of_available_at",
            "posterior_mean",
            "posterior_variance",
            "exposure_memory",
        ],
    }


def _q1_augmented_episode(episode: Any) -> Any:
    """Append behavior-inert, already-available Q1 evidence at the same cut."""

    seed = 2020
    slot = 919
    q1_triplet = (
        _check_event(seed, "Q1", -1, performed=False, slot=slot),
        _check_event(seed, "Q1", -1, performed=True, slot=slot),
        _observation_event(
            seed,
            "obs_1",
            0.25,
            collected_at=-1,
            available_at=0,
            slot=slot,
        ),
    )
    history = replace(
        episode.public_history,
        events=tuple(
            sorted(
                (*episode.public_history.events, *q1_triplet),
                key=event_sort_key,
            )
        ),
    )
    return replace(episode, public_history=history)


def _behavior_alias_cell(
    world: W20World,
    left_episode: Any,
    left_state: Any,
    right_episode: Any,
    right_state: Any,
) -> dict[str, Any]:
    left = _representation(left_state)
    right = _representation(right_state)
    left_provenance = _history_evidence_provenance(world, left_episode)
    right_provenance = _history_evidence_provenance(world, right_episode)
    left_uids = {event.event_uid for event in left_episode.public_history.events}
    added_events = [
        event
        for event in right_episode.public_history.events
        if event.event_uid not in left_uids
    ]
    if (
        len(added_events) != 3
        or [event.kind for event in added_events]
        != [
            EventKind.TEST_ORDERED,
            EventKind.TEST_PERFORMED,
            EventKind.OBSERVATION_AVAILABLE,
        ]
        or added_events[0].payload != {"check_id": "Q1"}
        or added_events[1].payload != {"check_id": "Q1"}
        or added_events[2].payload.get("channel_id") != "obs_1"
        or added_events[2].collected_at != -1
        or added_events[2].available_at != 0
    ):
        raise ProtocolViolation(
            "W20 behavior-alias Q1 evidence lacks a legal event triplet"
        )
    if (
        left["posterior_mean"] != right["posterior_mean"]
        or left["posterior_variance"] != right["posterior_variance"]
        or left["exposure_memory"] != right["exposure_memory"]
        or right_provenance["raw_evidence_count"]
        != left_provenance["raw_evidence_count"] + 1
        or left_provenance["public_history_digest"]
        == right_provenance["public_history_digest"]
        or left_state.record.state_hash != right_state.record.state_hash
    ):
        raise ProtocolViolation("W20 nonpredictive evidence behavior alias failed")
    policy_rows: list[dict[str, Any]] = []
    left_utilities: list[float] = []
    right_utilities: list[float] = []
    all_equal = True
    all_match_state_sentinel = True
    for index, policy in enumerate(world.policy_set(4)):
        left_oracle = _oracle_wire(
            world.public_belief_counterfactual(
                left["posterior_mean"],
                left["posterior_variance"],
                left["exposure_memory"],
                left_provenance["raw_evidence_count"],
                policy,
                4,
            )
        )
        right_oracle = _oracle_wire(
            world.public_belief_counterfactual(
                right["posterior_mean"],
                right["posterior_variance"],
                right["exposure_memory"],
                right_provenance["raw_evidence_count"],
                policy,
                4,
            )
        )
        state_sentinel_oracle = _oracle_wire(
            world.public_belief_counterfactual(
                left["posterior_mean"],
                left["posterior_variance"],
                left["exposure_memory"],
                1,
                policy,
                4,
            )
        )
        equal = left_oracle == right_oracle
        sentinel_equal = (
            left_oracle == state_sentinel_oracle
            and right_oracle == state_sentinel_oracle
        )
        all_equal = all_equal and equal
        all_match_state_sentinel = all_match_state_sentinel and sentinel_equal
        left_utilities.append(float(left_oracle["expected_utility"]))
        right_utilities.append(float(right_oracle["expected_utility"]))
        policy_rows.append(
            {
                "policy_index": index,
                "policy": policy.to_wire(),
                "policy_digest": digest_json(policy.to_wire()),
                "left_semantic_digest": digest_json(left_oracle),
                "right_semantic_digest": digest_json(right_oracle),
                "state_sentinel_semantic_digest": digest_json(state_sentinel_oracle),
                "semantic_equal": equal,
                "raw_count_semantics_equal_state_sentinel": sentinel_equal,
            }
        )
    if not all_equal or not all_match_state_sentinel or len(policy_rows) != 9:
        raise ProtocolViolation("W20 Q1 alias is behaviorally meaningful")
    classification = classify_pair(
        PairProbe(
            pair_id="W20-evidence-count-behavior-alias",
            state_hash_a=left_state.record.state_hash,
            state_hash_b=right_state.record.state_hash,
            candidate_signature_a=(
                float(left["posterior_mean"]),
                float(left["posterior_variance"]),
                float(left["exposure_memory"]),
            ),
            candidate_signature_b=(
                float(right["posterior_mean"]),
                float(right["posterior_variance"]),
                float(right["exposure_memory"]),
            ),
            oracle_signature_a=tuple(left_utilities),
            oracle_signature_b=tuple(right_utilities),
            oracle_action_values_a=tuple(left_utilities),
            oracle_action_values_b=tuple(right_utilities),
            information_relation="distinguishable_from_public_history",
            intervention_identifiable=True,
        ),
        **_PAIR_THRESHOLDS,
    )
    classification_wire = asdict(classification)
    if (
        classification.false_split is not False
        or classification.dangerous_collision is not False
        or classification.candidate_distance != 0.0
        or classification.oracle_distance != 0.0
    ):
        raise ProtocolViolation("W20 behavior-alias collector classification failed")
    return {
        "cell_id": "W20.evidence_count.behavior_alias",
        "world_slot": "W20",
        "cut_alias": "initial-plus-nonpredictive-q1",
        "task": "behavioral_quotient_alias_regression",
        "left_public_history_digest": left_episode.public_history.digest,
        "right_public_history_digest": right_episode.public_history.digest,
        "added_q1_event_triplet": [event.to_wire() for event in added_events],
        "left_state_hash": left_state.record.state_hash,
        "right_state_hash": right_state.record.state_hash,
        "posterior_and_exposure_equal": True,
        "raw_evidence_counts": [
            left_provenance["raw_evidence_count"],
            right_provenance["raw_evidence_count"],
        ],
        "raw_history_digests_different": True,
        "raw_evidence_counts_different": True,
        "state_hashes_equal": True,
        "state_identity_fields": [
            "as_of_available_at",
            "posterior_mean",
            "posterior_variance",
            "exposure_memory",
        ],
        "state_identity_excludes": [
            "public_history_digest",
            "raw_evidence_count",
        ],
        "full_h4_policy_count": len(policy_rows),
        "full_h4_policy_semantics_equal": all_equal,
        "legacy_count_argument_semantically_inert": all_match_state_sentinel,
        "policy_semantic_witnesses": policy_rows,
        "pair_thresholds": dict(_PAIR_THRESHOLDS),
        "pair_classification": classification_wire,
        "known_false_split_repaired": True,
        "false_split_detected": False,
        "minimal_quotient_claimed": False,
        "formal_blocker": "minimal-behavioral-quotient-not-proved",
    }


def _collect_w20_upper_bound_sanity(source_artifact: Path) -> dict[str, Any]:
    source_path = source_artifact
    if not source_path.is_absolute():
        source_path = _REPOSITORY_ROOT / source_path
    try:
        source_label = source_path.resolve().relative_to(_REPOSITORY_ROOT).as_posix()
    except ValueError:
        source_label = source_path.resolve().as_posix()
    source_raw = _read_canonical(source_path, "W20 source artifact")
    source_wire = json.loads(source_raw.decode("utf-8"))
    replay_raw = canonical_json_bytes(run_w20_feedback_slice())
    if replay_raw != source_raw:
        raise ProtocolViolation("W20 committed vertical slice does not byte-replay")

    world = W20World()
    probe = _W20BehavioralFeedbackProbe(world)
    low_episode, high_episode = world.exposure_collision_pair(seed=2001)
    low_state = probe.initialize_public_episode(low_episode)
    high_state = probe.initialize_public_episode(high_episode)
    low_panel = _policy_panel(world, probe, low_state, query_seed=101)
    high_panel = _policy_panel(world, probe, high_state, query_seed=201)
    low_representation = _representation(low_state)
    high_representation = _representation(high_state)
    physiology_signature_low = [
        low_representation["posterior_mean"],
        low_representation["posterior_variance"],
    ]
    physiology_signature_high = [
        high_representation["posterior_mean"],
        high_representation["posterior_variance"],
    ]
    if physiology_signature_low != physiology_signature_high:
        raise ProtocolViolation("W20 exposure collision lacks one physiology posterior")
    low_best = low_panel["panel_expected_utility_argmax"]
    high_best = high_panel["panel_expected_utility_argmax"]
    if low_best == high_best:
        raise ProtocolViolation(
            "W20 exposure collision does not change the best action"
        )
    cross_regrets = {
        "low_using_high_choice": low_panel["utilities"][low_best]
        - low_panel["utilities"][high_best],
        "high_using_low_choice": high_panel["utilities"][high_best]
        - high_panel["utilities"][low_best],
    }
    if min(cross_regrets.values()) <= 0.0 or max(cross_regrets.values()) <= 0.8:
        raise ProtocolViolation(
            "W20 physiology-only collision is not decision material"
        )

    degraded_hash = digest_json(
        {
            "protocol": "ucm-w20-physiology-only-compression/1",
            "signature": physiology_signature_low,
        }
    )
    low_utilities = tuple(low_panel["utilities"][alias] for alias in _ALIASES)
    high_utilities = tuple(high_panel["utilities"][alias] for alias in _ALIASES)
    physiology_classification = classify_pair(
        PairProbe(
            pair_id="W20-physiology-only-compression-collision",
            state_hash_a=degraded_hash,
            state_hash_b=degraded_hash,
            candidate_signature_a=tuple(physiology_signature_low),
            candidate_signature_b=tuple(physiology_signature_high),
            oracle_signature_a=low_utilities,
            oracle_signature_b=high_utilities,
            oracle_action_values_a=low_utilities,
            oracle_action_values_b=high_utilities,
            information_relation="distinguishable_from_public_history",
            intervention_identifiable=True,
        ),
        **_PAIR_THRESHOLDS,
    )
    physiology_classification_wire = asdict(physiology_classification)
    if (
        physiology_classification.dangerous_collision is not True
        or physiology_classification.attributable_collision is not True
        or physiology_classification.cross_applied_regret != max(cross_regrets.values())
    ):
        raise ProtocolViolation("W20 physiology compression classification failed")

    delta = _a1_response_delta()
    updated_state = probe.update_public(low_state, delta, inference_seed=3)
    updated_panel = _policy_panel(world, probe, updated_state, query_seed=301)
    updated_representation = _representation(updated_state)
    response_reversal = {
        "before_a1_first_mean": low_panel["first_marginal_means"]["do_A1"],
        "before_no_action_first_mean": low_panel["first_marginal_means"][
            "no_new_action"
        ],
        "after_a1_first_mean": updated_panel["first_marginal_means"]["do_A1"],
        "after_no_action_first_mean": updated_panel["first_marginal_means"][
            "no_new_action"
        ],
    }
    response_reversal["direction_reversed"] = bool(
        response_reversal["before_a1_first_mean"]
        < response_reversal["before_no_action_first_mean"]
        and response_reversal["after_a1_first_mean"]
        > response_reversal["after_no_action_first_mean"]
    )
    batch_history = replace(
        low_episode.public_history,
        events=tuple(
            sorted(
                (*low_episode.public_history.events, *delta.events),
                key=event_sort_key,
            )
        ),
        as_of_available_at=delta.advance_to,
    )
    batch_episode = replace(low_episode, public_history=batch_history)
    production_batch = world._production_posterior(batch_episode)
    reference_batch = world._reference_posterior(batch_episode)
    updated_provenance = _history_evidence_provenance(world, batch_episode)
    batch_replay = {
        "production_full_history": [
            round(production_batch[0], 12),
            round(production_batch[1], 12),
            round(production_batch[2], 12),
            production_batch[3],
        ],
        "reference_full_history": [
            round(reference_batch[0], 12),
            round(reference_batch[1], 12),
            round(reference_batch[2], 12),
            reference_batch[3],
        ],
        "sealed_rounded_update": [
            updated_representation["posterior_mean"],
            updated_representation["posterior_variance"],
            updated_representation["exposure_memory"],
        ],
        "raw_evidence_count_audit_provenance": updated_provenance["raw_evidence_count"],
    }
    batch_replay["production_reference_exact_at_wire_precision"] = (
        batch_replay["production_full_history"]
        == batch_replay["reference_full_history"]
    )
    batch_replay["sealed_quantization_max_abs_error"] = max(
        abs(
            float(batch_replay["sealed_rounded_update"][index])
            - float(production_batch[index])
        )
        for index in range(3)
    )
    batch_replay["sealed_quantization_error_bound"] = 2e-12
    if (
        updated_state.record.parent_state_hash != low_state.record.state_hash
        or updated_state.record.delta_digest != digest_json(delta.to_wire())
        or updated_representation["as_of_available_at"] != 1
        or updated_representation["exposure_memory"] != 1.0
        or updated_panel["panel_expected_utility_argmax"]
        == low_panel["panel_expected_utility_argmax"]
        or response_reversal["direction_reversed"] is not True
        or batch_replay["production_reference_exact_at_wire_precision"] is not True
        or batch_replay["sealed_quantization_max_abs_error"] > 2e-12
        or batch_replay["sealed_rounded_update"][2]
        != batch_replay["production_full_history"][2]
        or batch_replay["raw_evidence_count_audit_provenance"]
        != batch_replay["production_full_history"][3]
    ):
        raise ProtocolViolation("W20 combined response update did not close")

    q1_episode = _q1_augmented_episode(low_episode)
    q1_state = probe.initialize_public_episode(q1_episode)
    behavior_alias = _behavior_alias_cell(
        world,
        low_episode,
        low_state,
        q1_episode,
        q1_state,
    )
    cells = [
        {
            "cell_id": "W20.low.initial.shared_state",
            "world_slot": "W20",
            "cut_alias": "low-exposure-initial",
            "task": "diagnosis_and_policy_marginal_moments",
            **low_panel,
        },
        {
            "cell_id": "W20.high.initial.shared_state",
            "world_slot": "W20",
            "cut_alias": "high-exposure-initial",
            "task": "diagnosis_and_policy_marginal_moments",
            **high_panel,
        },
        {
            "cell_id": "W20.physiology_only.compression_collision",
            "world_slot": "W20",
            "cut_alias": "paired-initial",
            "task": "physiology_only_compression_collision",
            "physiology_signature_fields": [
                "posterior_mean",
                "posterior_variance",
            ],
            "low_signature": physiology_signature_low,
            "high_signature": physiology_signature_high,
            "signatures_collide": True,
            "low_full_state_hash": low_state.record.state_hash,
            "high_full_state_hash": high_state.record.state_hash,
            "full_states_distinct": True,
            "low_expected_utility_argmax": low_best,
            "high_expected_utility_argmax": high_best,
            "optimal_actions_differ": True,
            "cross_applied_regrets": cross_regrets,
            "max_cross_applied_regret": max(cross_regrets.values()),
            "degraded_state_hash": degraded_hash,
            "pair_thresholds": dict(_PAIR_THRESHOLDS),
            "pair_classification": physiology_classification_wire,
            "exposure_functional_required": True,
            "specific_field_encoding_required": False,
        },
        {
            "cell_id": "W20.combined_action_response.update",
            "world_slot": "W20",
            "cut_alias": "low-after-A1-and-Q0-response",
            "task": "combined_action_and_response_batch_update",
            "prior_state_hash": low_state.record.state_hash,
            "parent_state_hash": updated_state.record.parent_state_hash,
            "state_hash": updated_state.record.state_hash,
            "delta": delta.to_wire(),
            "delta_digest": digest_json(delta.to_wire()),
            "new_representation": updated_representation,
            "response_reversal": response_reversal,
            "full_history_batch_replay": batch_replay,
            "action_only_update_claimed": False,
            "combined_batch_update_closed": True,
        },
        {
            "cell_id": "W20.updated.shared_state",
            "world_slot": "W20",
            "cut_alias": "updated",
            "task": "updated_diagnosis_and_policy_marginal_moments",
            **updated_panel,
        },
        behavior_alias,
    ]
    history_evidence_provenance = {
        "low_initial": _history_evidence_provenance(world, low_episode),
        "high_initial": _history_evidence_provenance(world, high_episode),
        "low_updated": updated_provenance,
        "low_plus_nonpredictive_q1": _history_evidence_provenance(world, q1_episode),
    }
    report = {
        "protocol": PROTOCOL,
        "bundle_kind": "phase2_privileged_probe_evaluator",
        "world_slot": "W20",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": {
            "sealed_rounded_state_estimand": True,
            "policy_conditioned_marginal_moments_only": True,
            "expected_utility_only": True,
            "joint_temporal_law_claimed": False,
            "proper_distribution_calibration_claimed": False,
            "source_distinct_reference_oracle_claimed": False,
            "action_only_update_claimed": False,
            "minimal_behavioral_quotient_claimed": False,
            "known_evidence_count_false_split_open": False,
            "candidate_performance_claimed": False,
            "formal_b01_claimed": False,
        },
        "source_anchor": {
            "artifact_relpath": source_label,
            "artifact_digest": digest_bytes(source_raw),
            "artifact_bytes": len(source_raw),
            "artifact_protocol": source_wire["protocol"],
            "replay_digest": digest_bytes(replay_raw),
            "byte_identical_replay": True,
        },
        "manifest": probe.manifest.to_wire(),
        "manifest_digest": probe.manifest.digest,
        "fixture": {
            "collision_seed": 2001,
            "horizon": 4,
            "policy_panel_aliases": list(_ALIASES),
            "full_h4_policy_count_for_behavior_alias": 9,
        },
        "states": {
            "low_initial": _state_binding(low_state),
            "high_initial": _state_binding(high_state),
            "low_updated": _state_binding(updated_state),
            "low_plus_nonpredictive_q1": _state_binding(q1_state),
        },
        "history_evidence_provenance": history_evidence_provenance,
        "cells": cells,
        "cell_set_root": _cell_root(cells),
        "collector_metrics": {
            "pair_thresholds": dict(_PAIR_THRESHOLDS),
            "physiology_only_compression": physiology_classification_wire,
            "evidence_count_behavior_alias": behavior_alias["pair_classification"],
            "policy_panel_treatment_regret": {
                "low_initial": low_panel["treatment_regret_metric"],
                "high_initial": high_panel["treatment_regret_metric"],
                "low_updated": updated_panel["treatment_regret_metric"],
            },
            "response_reversal": response_reversal,
        },
        "runtime_semantics": {
            "production_oracle": "covariance-form-filter-plus-branch-enumeration",
            "reference_oracle": "information-form-filter-plus-independent-enumeration",
            "legacy_document_sobol_r_grid_description_matches_runtime": False,
            "sealed_state_rounding_digits": 12,
            "source_distinct_sealed_state_reference_collected": False,
        },
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_SANITY_BUNDLE_WITH_BEHAVIOR_ALIAS_REPAIR",
            "cell_count": len(cells),
            "state_binding_count": 4,
            "policy_marginal_panels": 3,
            "source_distinct_oracle_cells": 0,
            "physiology_only_collision_detected": True,
            "known_evidence_count_false_split_repaired": True,
            "nonpredictive_false_split_detected": False,
            "full_h4_policy_behavior_alias_witness_count": 9,
            "minimal_quotient_claimed": False,
            "ledger_credit": 0,
            "formalization_blockers": list(_FORMAL_BLOCKERS),
        },
    }
    report["bundle_root"] = compute_upper_bound_bundle_root(report)
    validate_json_like(report)
    return report


def run_w20_upper_bound_sanity(
    *, source_artifact: Path | str = DEFAULT_W20_ARTIFACT
) -> dict[str, Any]:
    report = _collect_w20_upper_bound_sanity(Path(source_artifact))
    verify_w20_upper_bound_sanity(
        report,
        source_artifact=source_artifact,
        replay_runtime=True,
    )
    return report


def verify_w20_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    del replay_runtime
    if type(value) is not dict:
        raise ProtocolViolation("W20 upper-bound report must be an object")
    report = value
    if report.get("bundle_root") != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("W20 upper-bound bundle root mismatch")
    bound = (
        Path(source_artifact) if source_artifact is not None else DEFAULT_W20_ARTIFACT
    )
    expected = _collect_w20_upper_bound_sanity(bound)
    if report != expected or canonical_json_bytes(report) != canonical_json_bytes(
        expected
    ):
        raise ProtocolViolation(
            "W20 report differs from exact live runtime reconstruction"
        )


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run or verify the PRE-FREEZE W20 upper-bound sanity bundle."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_W20_ARTIFACT)
    parser.add_argument("--replay-runtime", action="store_true")
    args = parser.parse_args()
    if args.verify is not None:
        raw = _read_canonical(args.verify, "W20 evaluator artifact")
        report = json.loads(raw.decode("utf-8"))
        verify_w20_upper_bound_sanity(
            report,
            source_artifact=args.source_artifact,
            replay_runtime=args.replay_runtime,
        )
        return 0
    assert args.output is not None
    report = run_w20_upper_bound_sanity(source_artifact=args.source_artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(report))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "DEFAULT_W20_ARTIFACT",
    "run_w20_upper_bound_sanity",
    "verify_w20_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
