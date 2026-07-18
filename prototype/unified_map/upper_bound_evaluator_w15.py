"""Patient-bound PRE-FREEZE upper-bound evaluator for W15.

W15 deliberately contains two causal panels with different estimands.  W15A
has a public randomized anchor and the privileged probe receives the exact
patient severity and confounder.  W15B is an observational equivalence class:
two private SCMs have byte-identical public evidence and opposite structural
effects, so the only candidate-visible causal answer is an identified set and
abstention.

This module keeps both panels under the benchmark slot ``W15`` and carries an
explicit ``panel`` field on every cell.  In particular, it never promotes the
legacy implementation name ``W15B`` to a second benchmark world.  Like the
other upper-bound evaluator, every result is privileged, ``upper_bound_only``,
PRE-FREEZE, and worth zero ledger credit.
"""

from __future__ import annotations

from copy import deepcopy
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
from .schema import ActionPlan, DiagnosisQuery, PlanKind, RolloutQuery
from .true_state_probe_w15 import (
    W15SharedCausalProbe,
    _identified_response_delta,
    _policy,
    run_w15_causal_slice,
)
from .upper_bound_evaluator import (
    PROTOCOL,
    STATUS_CHAIN,
    _attach_bundle_root,
    _cell_root,
    _degraded_diagnosis,
    _degraded_regret,
    _degraded_trajectory,
    _diagnosis_probabilities,
    _diagnostic_metric_wire,
    _head_wire,
    _oracle_comparison,
    _oracle_wire,
    _point_rollout,
    _regret_metric_wire,
    _state_binding,
    _trajectory_metric_wire,
    compute_upper_bound_bundle_root,
)
from .worlds.base import CounterfactualOracle, WorldSplit
from .worlds.w15 import World15A, World15B
from .world_registry import WORLD_REGISTRY


DEFAULT_W15_ARTIFACT = Path(
    "results/unified_map/pre_freeze/20260717-w15-causal-separation-probe/"
    "vertical-slice.json"
)

_PANEL_IDS = {
    "W15A": "W15A-randomized-identifiable",
    "W15B": "W15B-observational-nonidentified",
}

_EXPECTED_TOP_LEVEL_KEYS = {
    "protocol",
    "bundle_kind",
    "world_slot",
    "status_chain",
    "scope_statement",
    "panel_contract",
    "source_anchor",
    "manifest",
    "manifest_digest",
    "fixture",
    "states",
    "cells",
    "cell_set_root",
    "verification_summary",
    "bundle_root",
}


def _planned_ids(policy: ActionPlan, horizon: int) -> tuple[tuple[str, ...], ...]:
    """Expand the two W15 policy forms without reusing the world solver."""

    if type(policy) is not ActionPlan or type(horizon) is not int or horizon <= 0:
        raise ProtocolViolation("W15 structural replay requires a valid policy")
    rows: list[list[str]] = [[] for _ in range(horizon)]
    if policy.kind is PlanKind.NO_NEW_ACTION:
        return tuple(() for _ in range(horizon))
    if policy.kind is not PlanKind.ACTION_SEQUENCE:
        raise ProtocolViolation("W15 structural replay supports finite explicit plans")
    for action in policy.actions:
        if action.offset >= horizon:
            raise ProtocolViolation("W15 structural replay action is outside horizon")
        rows[action.offset].append(action.action_id)
    return tuple(tuple(sorted(row)) for row in rows)


def _w15a_structural_replay_reference(
    *, severity: float, confounder: int, policy: ActionPlan, horizon: int
) -> CounterfactualOracle:
    """Inline patient-state recurrence used as a non-certified replay witness.

    This is intentionally not called a source-independent oracle.  Full
    source-separation certification belongs to the frozen oracle harness.  The
    replay is nevertheless useful here because it binds every reported mean,
    variance, and expected utility to the exact patient state rather than to
    the different public-posterior estimand of ``World15A.counterfactual``.
    """

    if type(severity) not in {int, float} or not math.isfinite(float(severity)):
        raise ProtocolViolation("W15A reference severity must be finite")
    if type(confounder) is not int or confounder not in {0, 1}:
        raise ProtocolViolation("W15A reference confounder must be zero or one")
    initial_severity = float(severity)
    current = initial_severity
    variance = 0.0
    utility = 0.0
    observation_steps: list[dict[str, Any]] = []
    latent_steps: list[dict[str, Any]] = []
    for offset, ids in enumerate(_planned_ids(policy, horizon)):
        treated = "A1" in ids
        checked = "Q1" in ids
        current = max(
            0.0,
            0.92 * current + 0.20 * confounder - 0.35 * float(treated),
        )
        variance = 0.92**2 * variance + 0.04**2
        utility -= 0.97**offset * (
            current * current + variance + 0.05 * float(treated) + 0.06 * float(checked)
        )
        observation_steps.append(
            {
                "offset": offset + 1,
                "obs_0_mean": current,
                "obs_0_variance": variance + 0.05**2,
            }
        )
        latent_steps.append(
            {
                "offset": offset + 1,
                "severity_mean": current,
                "severity_variance": variance,
            }
        )
    p_c0 = float(initial_severity < 0.80)
    return CounterfactualOracle(
        policy=policy,
        horizon=horizon,
        observation_distribution={
            "family": "identified-dynamic-scm",
            "steps": observation_steps,
        },
        latent_distribution={
            "family": "severity-confounder-state",
            "steps": latent_steps,
            "diagnostic_posterior": {"C0": p_c0, "C1": 1.0 - p_c0},
        },
        outcome_distribution={
            "identification_status": "identified-by-randomized-anchor",
            "utility_family": "discounted-severity",
            "expected_utility": float(utility),
        },
        expected_utility=float(utility),
        numerical_diagnostics={
            "method": "upper-bound-inline-patient-state-recurrence",
            "absolute_error_bound": 0.0,
            "source_independence_certified": False,
        },
    )


def _w15a_mean_trajectory(oracle: dict[str, Any]) -> list[list[float]]:
    distribution = oracle.get("observation_distribution")
    if (
        type(distribution) is not dict
        or distribution.get("family") != "identified-dynamic-scm"
    ):
        raise ProtocolViolation("W15A oracle is not the identified dynamic SCM")
    steps = distribution.get("steps")
    if type(steps) is not list or not steps:
        raise ProtocolViolation("W15A oracle has no trajectory steps")
    result: list[list[float]] = []
    for expected_offset, step in enumerate(steps, start=1):
        if (
            type(step) is not dict
            or set(step) != {"offset", "obs_0_mean", "obs_0_variance"}
            or step["offset"] != expected_offset
        ):
            raise ProtocolViolation("W15A oracle trajectory is malformed")
        mean = step["obs_0_mean"]
        variance = step["obs_0_variance"]
        if (
            type(mean) not in {int, float}
            or type(variance) not in {int, float}
            or not math.isfinite(float(mean))
            or not math.isfinite(float(variance))
            or float(variance) < 0.0
        ):
            raise ProtocolViolation("W15A oracle trajectory is non-finite")
        result.append([float(mean)])
    return result


def _w15b_structural_replay_contract(policy: ActionPlan) -> dict[str, Any]:
    """Enumerate the public two-SCM table without calling the W15B solver."""

    treated = "A1" in _planned_ids(policy, 1)[0]
    # Row order is fixed as (Mplus,u0), (Mplus,u1), (Mminus,u0),
    # (Mminus,u1).  These are the two observationally equivalent SCMs, not
    # the realized private member of either twin.
    do_zero = [0.0, 0.0, 0.0, 2.0]
    do_one = [1.0, 1.0, -1.0, 1.0]
    structural_effect_rows = [
        treated_value - untreated_value
        for treated_value, untreated_value in zip(do_one, do_zero, strict=True)
    ]
    observation_support = do_one if treated else do_zero
    policy_utility_support = [
        value - 0.05 * float(treated) for value in observation_support
    ]
    return {
        "row_order": ["Mplus.u0", "Mplus.u1", "Mminus.u0", "Mminus.u1"],
        "observation_support": observation_support,
        "observation_probabilities": [0.25, 0.25, 0.25, 0.25],
        "observation_mean": math.fsum(observation_support) / 4.0,
        "policy_utility_support": policy_utility_support,
        "structural_effect_rows": structural_effect_rows,
        "ate_identified_set": sorted(set(structural_effect_rows)),
        "recommendation": "abstain",
        "reference_independence_certified": False,
    }


def _w15b_support_contract(
    head: dict[str, Any],
    oracle: dict[str, Any],
    reference_utility: float,
    structural_replay: dict[str, Any],
) -> dict[str, Any]:
    """Extract the full public equivalence-class answer without pointifying it."""

    result = head["execution"]["response"]["result"]
    metadata = result.get("metadata")
    if (
        type(metadata) is not dict
        or metadata.get("panel") != "W15B"
        or metadata.get("identification_status") != "unsupported-point-effect"
        or metadata.get("private_scm_used") is not False
    ):
        raise ProtocolViolation("W15B candidate metadata violates nonidentification")
    predictions = result.get("observable_predictions")
    if type(predictions) is not dict or set(predictions) != {"obs_1"}:
        raise ProtocolViolation("W15B candidate observable set mismatch")
    prediction = predictions["obs_1"]
    if type(prediction) is not dict or set(prediction) != {
        "family",
        "support",
        "probabilities",
        "mean",
    }:
        raise ProtocolViolation("W15B candidate distribution is not closed")
    if prediction["family"] != "public-equivalence-mixture":
        raise ProtocolViolation("W15B candidate pointified its observation")
    utility = result.get("utility_prediction")
    if type(utility) is not dict or set(utility) != {
        "family",
        "support",
        "ate_identified_set",
        "recommendation",
    }:
        raise ProtocolViolation("W15B candidate utility answer is not a closed set")
    if (
        utility["family"] != "identified_set"
        or utility["ate_identified_set"] != [-1.0, 1.0]
        or utility["recommendation"] != "abstain"
    ):
        raise ProtocolViolation("W15B candidate invented a point causal answer")

    observation = oracle.get("observation_distribution")
    outcome = oracle.get("outcome_distribution")
    if (
        type(observation) is not dict
        or observation.get("family") != "two-scm-public-evidence-mixture"
        or type(outcome) is not dict
        or outcome.get("identification_status") != "unsupported-point-effect"
        or outcome.get("ate_identified_set") != [-1.0, 1.0]
        or outcome.get("recommendation") != "abstain"
        or outcome.get("candidate_collision_attributable") is not False
    ):
        raise ProtocolViolation("W15B public oracle was rewritten as identified")
    candidate_support = prediction["support"]
    candidate_probabilities = prediction["probabilities"]
    candidate_mean = prediction["mean"]
    candidate_utility_support = utility["support"]
    expected_replay_keys = {
        "row_order",
        "observation_support",
        "observation_probabilities",
        "observation_mean",
        "policy_utility_support",
        "structural_effect_rows",
        "ate_identified_set",
        "recommendation",
        "reference_independence_certified",
    }
    if (
        type(structural_replay) is not dict
        or set(structural_replay) != expected_replay_keys
    ):
        raise ProtocolViolation("W15B structural replay contract is not closed")
    if (
        candidate_support != structural_replay["observation_support"]
        or candidate_probabilities != structural_replay["observation_probabilities"]
        or candidate_mean != structural_replay["observation_mean"]
        or candidate_utility_support != structural_replay["policy_utility_support"]
        or utility["ate_identified_set"] != structural_replay["ate_identified_set"]
        or utility["recommendation"] != structural_replay["recommendation"]
        or observation.get("obs_1_support") != structural_replay["observation_support"]
        or observation.get("obs_1_probabilities")
        != structural_replay["observation_probabilities"]
        or observation.get("obs_1_mean") != structural_replay["observation_mean"]
        or outcome.get("policy_utility_support")
        != structural_replay["policy_utility_support"]
        or outcome.get("ate_identified_set") != structural_replay["ate_identified_set"]
        or outcome.get("recommendation") != structural_replay["recommendation"]
    ):
        raise ProtocolViolation(
            "W15B candidate/oracle does not preserve the independent four-row table"
        )
    if type(reference_utility) not in {int, float} or not math.isfinite(
        float(reference_utility)
    ):
        raise ProtocolViolation("W15B scalar reference is not finite")
    support_mean = math.fsum(float(item) for item in candidate_utility_support) / len(
        candidate_utility_support
    )
    if not math.isclose(
        support_mean, float(reference_utility), rel_tol=0.0, abs_tol=1e-12
    ):
        raise ProtocolViolation("W15B support mean disagrees with scalar reference")
    return {
        "observation_support": list(candidate_support),
        "observation_probabilities": list(candidate_probabilities),
        "observation_mean": float(candidate_mean),
        "policy_utility_support": list(candidate_utility_support),
        "ate_identified_set": [-1.0, 1.0],
        "recommendation": "abstain",
        "reference_expected_utility": float(reference_utility),
        "support_mean_matches_scalar_reference": True,
        "structural_replay": deepcopy(structural_replay),
        "point_effect_scored": False,
        "realized_private_scm_scored": False,
    }


def _read_and_replay_source(source_path: Path) -> tuple[bytes, dict[str, Any], bytes]:
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(
            f"W15 source artifact is unavailable: {source_path}"
        ) from exc
    try:
        source_wire = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("W15 source artifact is not JSON") from exc
    if canonical_json_bytes(source_wire) != source_bytes:
        raise ProtocolViolation("W15 source artifact is not canonical JSON")
    replay_bytes = canonical_json_bytes(run_w15_causal_slice())
    if replay_bytes != source_bytes:
        raise ProtocolViolation("W15 committed vertical slice does not byte-replay")
    return source_bytes, source_wire, replay_bytes


def _collect_w15_upper_bound_sanity(
    source_path: Path, *, artifact_label: str | None = None
) -> dict[str, Any]:
    source_bytes, source_wire, replay_bytes = _read_and_replay_source(source_path)
    registry_panel_ids = tuple(panel.panel_id for panel in WORLD_REGISTRY["W15"].panels)
    if registry_panel_ids != tuple(_PANEL_IDS.values()):
        raise ProtocolViolation("W15 evaluator panel ids diverge from the registry")
    identifiable = World15A()
    nonidentified = World15B()
    probe = W15SharedCausalProbe(identifiable, nonidentified)
    diagnosis_query = DiagnosisQuery(("C0", "C1"))
    manifest_digest = probe.manifest.digest

    state_a = probe.initialize_identified_true_state(severity=0.90, confounder=0)
    diagnosis_a = probe.diagnose(state_a, diagnosis_query, query_seed=1)
    policy_aliases_a = ("no_new_action", "do_A1")
    policies_a = (
        _policy(identifiable, 4, None),
        _policy(identifiable, 4, "A1"),
    )
    candidate_heads_a: dict[str, dict[str, Any]] = {}
    judge_oracles_a: dict[str, dict[str, Any]] = {}
    replay_references_a: dict[str, dict[str, Any]] = {}
    oracle_comparisons_a: dict[str, dict[str, Any]] = {}
    trajectory_checks_a: dict[str, dict[str, Any]] = {}
    trajectory_metrics_a: dict[str, dict[str, Any]] = {}
    predicted_utilities_a: list[float] = []
    judge_utilities_a: list[float] = []
    reference_utilities_a: list[float] = []
    for alias, policy in zip(policy_aliases_a, policies_a, strict=True):
        query = RolloutQuery(
            4,
            policy,
            ("obs_0",),
            digest_json(["W15A", "severity-utility", 4]),
        )
        head = _head_wire(probe.rollout(state_a, query, query_seed=2), query)
        judge = _oracle_wire(
            identifiable.judge_true_state_counterfactual(
                {"severity": 0.90}, {"confounder": 0}, policy, 4
            )
        )
        reference = oracle_output_wire(
            _w15a_structural_replay_reference(
                severity=0.90,
                confounder=0,
                policy=policy,
                horizon=4,
            ),
            include_numerical_diagnostics=False,
        )
        comparison = _oracle_comparison(judge, reference)
        predicted, predicted_utility = _point_rollout(head, ("obs_0",))
        judge_mean = _w15a_mean_trajectory(judge)
        reference_mean = _w15a_mean_trajectory(reference)
        candidate_heads_a[alias] = head
        judge_oracles_a[alias] = judge
        replay_references_a[alias] = reference
        oracle_comparisons_a[alias] = comparison
        trajectory_checks_a[alias] = {
            "candidate_mean": predicted,
            "judge_mean": judge_mean,
            "structural_replay_mean": reference_mean,
            "candidate_equals_judge_mean": predicted == judge_mean,
            "judge_equals_structural_replay": judge_mean == reference_mean,
        }
        trajectory_metrics_a[alias] = _trajectory_metric_wire(predicted, judge_mean)
        predicted_utilities_a.append(predicted_utility)
        judge_utilities_a.append(float(judge["expected_utility"]))
        reference_utilities_a.append(float(reference["expected_utility"]))

    randomized_episodes = tuple(
        identifiable.generate_episode(WorldSplit.TRAIN, 1881, index)
        for index in range(400)
    )
    randomized_effect = identifiable.estimate_randomized_anchor_effect(
        randomized_episodes
    )
    no_action_first = trajectory_checks_a["no_new_action"]["candidate_mean"][0][0]
    do_a1_first = trajectory_checks_a["do_A1"]["candidate_mean"][0][0]
    judge_no_action_first = trajectory_checks_a["no_new_action"]["judge_mean"][0][0]
    judge_do_a1_first = trajectory_checks_a["do_A1"]["judge_mean"][0][0]
    reference_no_action_first = trajectory_checks_a["no_new_action"][
        "structural_replay_mean"
    ][0][0]
    reference_do_a1_first = trajectory_checks_a["do_A1"]["structural_replay_mean"][0][0]

    delta, next_severity = _identified_response_delta()
    structural_next_severity = max(0.0, 0.92 * 0.90 - 0.35)
    expected_delta_wire = {
        "protocol": "ucm-visible-delta/1",
        "advance_to": 1,
        "events": [
            {
                "kind": "observation_available",
                "occurred_at": 1,
                "collected_at": 1,
                "available_at": 1,
                "event_uid": "w15a-factual-severity",
                "payload": {
                    "channel_id": "obs_0",
                    "value": structural_next_severity,
                },
            },
            {
                "kind": "performed_treatment",
                "occurred_at": 1,
                "collected_at": None,
                "available_at": 1,
                "event_uid": "w15a-factual-a1",
                "payload": {"action_id": "A1", "parameters": {}},
            },
        ],
    }
    if (
        next_severity != structural_next_severity
        or delta.to_wire() != expected_delta_wire
        or reference_do_a1_first != structural_next_severity
        or do_a1_first != structural_next_severity
        or judge_do_a1_first != structural_next_severity
    ):
        raise ProtocolViolation(
            "W15A update does not bind the visible A1 response to the patient recurrence"
        )
    updated_a = probe.update_identified_private(
        state_a,
        delta,
        hidden_state_at_cut={"severity": next_severity},
        invariant_parameters={"confounder": 0},
        inference_seed=3,
    )
    updated_diagnosis = probe.diagnose(updated_a, diagnosis_query, query_seed=4)
    updated_query = RolloutQuery(
        4,
        policies_a[0],
        ("obs_0",),
        digest_json(["W15A", "severity-utility", 4]),
    )
    updated_head = _head_wire(
        probe.rollout(updated_a, updated_query, query_seed=5), updated_query
    )
    updated_judge = _oracle_wire(
        identifiable.judge_true_state_counterfactual(
            {"severity": next_severity}, {"confounder": 0}, policies_a[0], 4
        )
    )
    updated_reference = oracle_output_wire(
        _w15a_structural_replay_reference(
            severity=next_severity,
            confounder=0,
            policy=policies_a[0],
            horizon=4,
        ),
        include_numerical_diagnostics=False,
    )
    updated_predicted, updated_utility = _point_rollout(updated_head, ("obs_0",))
    updated_truth = _w15a_mean_trajectory(updated_judge)

    twin_plus, twin_minus = nonidentified.nonidentified_twin_fixture(
        seed=757, confounder=0
    )
    state_b_plus = probe.initialize_nonidentified_private(twin_plus)
    state_b_minus = probe.initialize_nonidentified_private(twin_minus)
    diagnosis_b = probe.diagnose(state_b_plus, diagnosis_query, query_seed=6)
    diagnosis_b_head = _head_wire(diagnosis_b, diagnosis_query)
    diagnosis_b_result = diagnosis_b_head["execution"]["response"]["result"]
    diagnosis_b_metadata = diagnosis_b_result.get("metadata")
    if (
        diagnosis_b_result.get("probabilities") != {"C0": 0.5, "C1": 0.5}
        or type(diagnosis_b_metadata) is not dict
        or diagnosis_b_metadata.get("panel") != "W15B"
        or diagnosis_b_metadata.get("identification_status")
        != "unsupported-point-effect"
        or "private_scm" in diagnosis_b_metadata
        or "private_scm_used" in diagnosis_b_metadata
    ):
        raise ProtocolViolation("W15B diagnosis pointifies or exposes private identity")
    plus_effect = nonidentified.judge_structural_effect(twin_plus)
    minus_effect = nonidentified.judge_structural_effect(twin_minus)
    if (
        twin_plus.public_history.to_wire() != twin_minus.public_history.to_wire()
        or twin_plus.public_history.digest != twin_minus.public_history.digest
        or state_b_plus.record.state_hash != state_b_minus.record.state_hash
        or _state_binding(state_b_plus) != _state_binding(state_b_minus)
        or plus_effect != 1.0
        or minus_effect != -1.0
    ):
        raise ProtocolViolation("W15B twin quotient is not exact")
    policy_aliases_b = ("no_new_action", "do_A1")
    policies_b = (
        _policy(nonidentified, 1, None),
        _policy(nonidentified, 1, "A1"),
    )
    candidate_heads_b: dict[str, dict[str, Any]] = {}
    public_oracles_b: dict[str, dict[str, Any]] = {}
    scalar_references_b: dict[str, float] = {}
    support_contracts_b: dict[str, dict[str, Any]] = {}
    for alias, policy in zip(policy_aliases_b, policies_b, strict=True):
        query = RolloutQuery(
            1,
            policy,
            ("obs_1",),
            digest_json(["W15B", "identified-set", 1]),
        )
        head = _head_wire(probe.rollout(state_b_plus, query, query_seed=7), query)
        public_oracle = _oracle_wire(
            nonidentified.identified_set_counterfactual(policy, 1)
        )
        scalar_reference = nonidentified.reference_counterfactual(twin_plus, policy, 1)
        structural_replay = _w15b_structural_replay_contract(policy)
        candidate_heads_b[alias] = head
        public_oracles_b[alias] = public_oracle
        scalar_references_b[alias] = scalar_reference
        support_contracts_b[alias] = _w15b_support_contract(
            head, public_oracle, scalar_reference, structural_replay
        )

    initial_probabilities = _diagnosis_probabilities(
        _head_wire(diagnosis_a, diagnosis_query), ("C0", "C1")
    )
    updated_probabilities = _diagnosis_probabilities(
        _head_wire(updated_diagnosis, diagnosis_query), ("C0", "C1")
    )
    initial_target = [0.0, 1.0]
    updated_target = [1.0, 0.0]
    initial_diagnosis_metric = _diagnostic_metric_wire(
        initial_probabilities, initial_target
    )
    initial_diagnosis_degraded = _degraded_diagnosis(
        initial_probabilities, initial_target
    )
    updated_diagnosis_metric = _diagnostic_metric_wire(
        updated_probabilities, updated_target
    )
    updated_diagnosis_degraded = _degraded_diagnosis(
        updated_probabilities, updated_target
    )
    intervention_metric = _regret_metric_wire(predicted_utilities_a, judge_utilities_a)
    intervention_degraded = _degraded_regret(judge_utilities_a)
    updated_oracle_comparison = _oracle_comparison(updated_judge, updated_reference)
    updated_trajectory_metric = _trajectory_metric_wire(
        updated_predicted, updated_truth
    )
    updated_trajectory_degraded = _degraded_trajectory(updated_predicted, updated_truth)

    # A live replay that turns red is not a valid sanity bundle.  These gates
    # are intentionally evaluated before the report is labelled VALID so a
    # common-mode runtime drift cannot merely serialize ``passed: false`` and
    # retain the success status.
    if (
        initial_probabilities != initial_target
        or updated_probabilities != updated_target
        or initial_diagnosis_metric["accuracy"] != 1.0
        or initial_diagnosis_metric["log_loss"] != 0.0
        or initial_diagnosis_metric["multiclass_brier"] != 0.0
        or updated_diagnosis_metric["accuracy"] != 1.0
        or updated_diagnosis_metric["log_loss"] != 0.0
        or updated_diagnosis_metric["multiclass_brier"] != 0.0
        or initial_diagnosis_degraded["log_loss"]
        <= initial_diagnosis_metric["log_loss"]
        or updated_diagnosis_degraded["log_loss"]
        <= updated_diagnosis_metric["log_loss"]
    ):
        raise ProtocolViolation("W15A diagnosis sanity direction failed")
    for alias in policy_aliases_a:
        comparison = oracle_comparisons_a[alias]
        trajectory = trajectory_checks_a[alias]
        metric = trajectory_metrics_a[alias]
        if (
            comparison["passed"] is not True
            or comparison["numeric_mismatch_count"] != 0
            or comparison["structural_mismatch_count"] != 0
            or comparison["max_absolute_error"] != 0.0
            or comparison["max_relative_error"] != 0.0
            or judge_oracles_a[alias] != replay_references_a[alias]
            or trajectory["candidate_equals_judge_mean"] is not True
            or trajectory["judge_equals_structural_replay"] is not True
            or trajectory["candidate_mean"] != trajectory["judge_mean"]
            or trajectory["judge_mean"] != trajectory["structural_replay_mean"]
            or metric["normalized_rmse"] != 0.0
            or metric["normalized_mae"] != 0.0
        ):
            raise ProtocolViolation(
                f"W15A {alias} patient-bound trajectory/reference sanity failed"
            )
    do_effect_values = (
        do_a1_first - no_action_first,
        judge_do_a1_first - judge_no_action_first,
        reference_do_a1_first - reference_no_action_first,
        -0.35,
    )
    if (
        any(value != -0.35 for value in do_effect_values)
        or predicted_utilities_a != judge_utilities_a
        or judge_utilities_a != reference_utilities_a
        or randomized_effect >= -0.15
        or intervention_metric["worst_regret"] != 0.0
        or intervention_degraded["worst_regret"] <= 0.0
        or intervention_degraded["catastrophic_count"] <= 0
    ):
        raise ProtocolViolation("W15A intervention sanity direction failed")
    if (
        updated_oracle_comparison["passed"] is not True
        or updated_oracle_comparison["numeric_mismatch_count"] != 0
        or updated_oracle_comparison["structural_mismatch_count"] != 0
        or updated_oracle_comparison["max_absolute_error"] != 0.0
        or updated_oracle_comparison["max_relative_error"] != 0.0
        or updated_judge != updated_reference
        or updated_predicted != updated_truth
        or updated_truth != _w15a_mean_trajectory(updated_reference)
        or updated_utility != float(updated_judge["expected_utility"])
        or updated_utility != float(updated_reference["expected_utility"])
        or updated_trajectory_metric["normalized_rmse"] != 0.0
        or updated_trajectory_metric["normalized_mae"] != 0.0
        or updated_trajectory_degraded["normalized_rmse"] <= 0.0
    ):
        raise ProtocolViolation("W15A updated-cut sanity direction failed")
    cells = [
        {
            "cell_id": "W15.W15A.initial.diagnosis",
            "world_slot": "W15",
            "panel": "W15A",
            "panel_id": _PANEL_IDS["W15A"],
            "cut_alias": "initial",
            "task": "diagnosis",
            "state_hash": state_a.record.state_hash,
            "candidate_head": _head_wire(diagnosis_a, diagnosis_query),
            "oracle_target": {
                "label_order": ["C0", "C1"],
                "probabilities": initial_target,
            },
            "metric": initial_diagnosis_metric,
            "degraded_control_metric": initial_diagnosis_degraded,
        },
        {
            "cell_id": "W15.W15A.initial.intervention",
            "world_slot": "W15",
            "panel": "W15A",
            "panel_id": _PANEL_IDS["W15A"],
            "cut_alias": "initial",
            "task": "patient_bound_do_mean_utility",
            "state_hash": state_a.record.state_hash,
            "estimand": "do-effect-given-exact-severity-and-confounder",
            "policy_aliases": list(policy_aliases_a),
            "candidate_heads": candidate_heads_a,
            "judge_oracles": judge_oracles_a,
            "structural_replay_references": replay_references_a,
            "reference_independence_certified": False,
            "oracle_comparisons": oracle_comparisons_a,
            "trajectory_checks": trajectory_checks_a,
            "trajectory_metrics": trajectory_metrics_a,
            "predicted_utilities": predicted_utilities_a,
            "judge_expected_utilities": judge_utilities_a,
            "structural_replay_expected_utilities": reference_utilities_a,
            "do_effect": {
                "candidate_first_step": do_a1_first - no_action_first,
                "judge_first_step": judge_do_a1_first - judge_no_action_first,
                "structural_replay_first_step": (
                    reference_do_a1_first - reference_no_action_first
                ),
                "identified_effect": -0.35,
            },
            "public_randomized_anchor": {
                "split": WorldSplit.TRAIN.value,
                "generator_seed": 1881,
                "episode_count": 400,
                "effect_estimate": randomized_effect,
                "beneficial_sign_observed": randomized_effect < -0.15,
            },
            "metric": intervention_metric,
            "degraded_control_metric": intervention_degraded,
        },
        {
            "cell_id": "W15.W15A.update",
            "world_slot": "W15",
            "panel": "W15A",
            "panel_id": _PANEL_IDS["W15A"],
            "cut_alias": "initial-to-updated",
            "task": "recursive_update",
            "prior_state_hash": state_a.record.state_hash,
            "state_hash": updated_a.record.state_hash,
            "parent_state_hash": updated_a.record.parent_state_hash,
            "delta": delta.to_wire(),
            "delta_digest": digest_json(delta.to_wire()),
            "expected_next_severity": next_severity,
            "structural_replay_next_severity": structural_next_severity,
            "delta_observation_matches_structural_replay": True,
            "update_semantics": (
                "privileged-judge-state-replacement-after-visible-delta"
            ),
        },
        {
            "cell_id": "W15.W15A.updated.diagnosis",
            "world_slot": "W15",
            "panel": "W15A",
            "panel_id": _PANEL_IDS["W15A"],
            "cut_alias": "updated",
            "task": "diagnosis",
            "state_hash": updated_a.record.state_hash,
            "candidate_head": _head_wire(updated_diagnosis, diagnosis_query),
            "oracle_target": {
                "label_order": ["C0", "C1"],
                "probabilities": updated_target,
            },
            "metric": updated_diagnosis_metric,
            "degraded_control_metric": updated_diagnosis_degraded,
        },
        {
            "cell_id": "W15.W15A.updated.natural_forecast",
            "world_slot": "W15",
            "panel": "W15A",
            "panel_id": _PANEL_IDS["W15A"],
            "cut_alias": "updated",
            "task": "patient_bound_natural_forecast_mean",
            "state_hash": updated_a.record.state_hash,
            "candidate_head": updated_head,
            "judge_oracle": updated_judge,
            "structural_replay_reference": updated_reference,
            "reference_independence_certified": False,
            "oracle_comparison": updated_oracle_comparison,
            "trajectory_check": {
                "candidate_mean": updated_predicted,
                "judge_mean": updated_truth,
                "structural_replay_mean": _w15a_mean_trajectory(updated_reference),
            },
            "metric": updated_trajectory_metric,
            "degraded_control_metric": updated_trajectory_degraded,
            "predicted_expected_utility": updated_utility,
            "judge_expected_utility": float(updated_judge["expected_utility"]),
            "structural_replay_expected_utility": float(
                updated_reference["expected_utility"]
            ),
        },
        {
            "cell_id": "W15.W15B.public_twin",
            "world_slot": "W15",
            "panel": "W15B",
            "panel_id": _PANEL_IDS["W15B"],
            "cut_alias": "pre-action-public-equivalence",
            "task": "nonidentified_twin_quotient",
            "state_hash": state_b_plus.record.state_hash,
            "plus_state_hash": state_b_plus.record.state_hash,
            "minus_state_hash": state_b_minus.record.state_hash,
            "public_history": twin_plus.public_history.to_wire(),
            "plus_public_history_digest": twin_plus.public_history.digest,
            "minus_public_history_digest": twin_minus.public_history.digest,
            "private_structural_effect_witness": {
                "plus": plus_effect,
                "minus": minus_effect,
            },
            "private_identity_in_candidate_state": False,
        },
        {
            "cell_id": "W15.W15B.identified_set",
            "world_slot": "W15",
            "panel": "W15B",
            "panel_id": _PANEL_IDS["W15B"],
            "cut_alias": "pre-action-public-equivalence",
            "task": "nonidentified_set_and_abstention",
            "state_hash": state_b_plus.record.state_hash,
            "estimand": "public-equivalence-class-ate-identified-set",
            "diagnosis_head": diagnosis_b_head,
            "diagnosis_contract": {
                "probabilities": {"C0": 0.5, "C1": 0.5},
                "identification_status": "unsupported-point-effect",
                "private_scm_used": False,
                "private_scm_identity_exposed": False,
                "point_diagnosis_claimed": False,
            },
            "diagnosis_metric": None,
            "diagnosis_metric_reason": "soft-public-posterior-not-an-integer-label",
            "policy_aliases": list(policy_aliases_b),
            "candidate_heads": candidate_heads_b,
            "public_set_oracles": public_oracles_b,
            "scalar_reference_expected_utilities": scalar_references_b,
            "support_contracts": support_contracts_b,
            "treatment_regret_metric": None,
            "treatment_regret_metric_reason": (
                "nonidentified-set-cannot-be-point-argmax-scored"
            ),
        },
    ]

    body = {
        "protocol": PROTOCOL,
        "bundle_kind": "phase2_privileged_probe_evaluator",
        "world_slot": "W15",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": {
            "w15a_mean_trajectory_only": True,
            "w15a_expected_utility_only": True,
            "w15b_exact_support_contract_only": True,
            "proper_distribution_score_claimed": False,
            "proper_set_metric_claimed": False,
            "candidate_performance_claimed": False,
            "formal_b01_claimed": False,
            "source_distinct_reference_oracle_claimed": False,
            "observational_association_used_as_do_effect": False,
            "evidence_assimilation_claimed": False,
        },
        "panel_contract": {
            "outer_world_slot": "W15",
            "panel_alias_to_panel_id": deepcopy(_PANEL_IDS),
            "panel_identities": list(_PANEL_IDS.values()),
            "panel_identity_is_world_slot": False,
            "w15a_estimand": ("patient-bound-do-given-exact-severity-and-confounder"),
            "w15b_estimand": "public-equivalence-class-identified-set",
            "w15b_point_effect_claimed": False,
        },
        "source_anchor": {
            "artifact_relpath": (
                artifact_label if artifact_label is not None else source_path.as_posix()
            ),
            "artifact_digest": digest_bytes(source_bytes),
            "artifact_bytes": len(source_bytes),
            "artifact_protocol": source_wire["protocol"],
            "replay_digest": digest_bytes(replay_bytes),
            "byte_identical_replay": True,
        },
        "manifest": probe.manifest.to_wire(),
        "manifest_digest": manifest_digest,
        "fixture": {
            "identified": {
                "panel": "W15A",
                "panel_id": _PANEL_IDS["W15A"],
                "severity": 0.90,
                "confounder": 0,
                "horizon": 4,
                "randomized_anchor_seed": 1881,
                "randomized_anchor_episode_count": 400,
            },
            "nonidentified": {
                "panel": "W15B",
                "panel_id": _PANEL_IDS["W15B"],
                "split": WorldSplit.SEALED_TEST.value,
                "twin_seed": 757,
                "confounder_fixture": 0,
                "horizon": 1,
                "public_history_digest": twin_plus.public_history.digest,
            },
        },
        "states": {
            "W15A_initial": _state_binding(state_a),
            "W15A_updated": _state_binding(updated_a),
            "W15B_plus": _state_binding(state_b_plus),
            "W15B_minus": _state_binding(state_b_minus),
        },
        "cells": cells,
        "cell_set_root": _cell_root(cells),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_SANITY_BUNDLE",
            "cell_count": len(cells),
            "panel_count": 2,
            "state_binding_count": 4,
            "source_distinct_oracle_cells": 0,
            "ledger_credit": 0,
            "formalization_blockers": [
                "not-a-frozen-expected-cell-corpus",
                "privileged-upper-bound-only",
                "patient-bound-structural-replay-not-source-certified",
                "W15A-mean-and-expected-utility-projections-only",
                "W15B-nonidentified-set-requires-set-aware-formal-metric",
            ],
        },
    }
    return _attach_bundle_root(body)


def run_w15_upper_bound_sanity(
    *, source_artifact: Path | str = DEFAULT_W15_ARTIFACT
) -> dict[str, Any]:
    """Live-replay W15 and return its zero-credit patient-bound sanity bundle."""

    result = _collect_w15_upper_bound_sanity(Path(source_artifact))
    verify_w15_upper_bound_sanity(result, source_artifact=source_artifact)
    return result


def verify_w15_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    """Recompute the complete fixed W15 bundle from live runtime bytes.

    W15 is a fixed PRE-FREEZE probe rather than a parameterized candidate
    corpus.  Exact live reconstruction is consequently both simpler and
    stricter than trusting nested booleans: any changed state preimage, query,
    head, oracle, support set, update edge, or scope claim changes the bundle.
    """

    if type(replay_runtime) is not bool:
        raise ProtocolViolation("replay_runtime must be boolean")
    if type(value) is not dict or set(value) != _EXPECTED_TOP_LEVEL_KEYS:
        raise ProtocolViolation("W15 upper-bound report must be a closed object")
    report = value
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "phase2_privileged_probe_evaluator"
        or report["world_slot"] != "W15"
        or report["status_chain"] != STATUS_CHAIN
    ):
        raise ProtocolViolation("W15 upper-bound status or identity was rewritten")
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("W15 upper-bound bundle root mismatch")
    source = report["source_anchor"]
    if type(source) is not dict or set(source) != {
        "artifact_relpath",
        "artifact_digest",
        "artifact_bytes",
        "artifact_protocol",
        "replay_digest",
        "byte_identical_replay",
    }:
        raise ProtocolViolation("W15 source anchor must be closed")
    artifact_label = source["artifact_relpath"]
    if type(artifact_label) is not str or not artifact_label:
        raise ProtocolViolation("W15 source artifact path is invalid")
    bound_path = (
        Path(source_artifact) if source_artifact is not None else Path(artifact_label)
    )
    # Live reconstruction is mandatory for this privileged sanity adapter.
    # ``replay_runtime`` remains in the API for parity with the common
    # verifier; setting it only makes the caller's intent explicit.
    expected = _collect_w15_upper_bound_sanity(
        bound_path, artifact_label=artifact_label
    )
    if digest_json(report) != digest_json(expected):
        raise ProtocolViolation(
            "W15 upper-bound report does not match live patient-bound replay"
        )


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run or verify the PRE-FREEZE W15 upper-bound sanity bundle."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_W15_ARTIFACT)
    parser.add_argument("--replay-runtime", action="store_true")
    args = parser.parse_args()
    if args.verify is not None:
        try:
            raw = args.verify.read_bytes()
            report = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cannot read W15 report {args.verify}: {exc}") from exc
        if canonical_json_bytes(report) != raw:
            raise SystemExit(f"W15 report is not canonical JSON: {args.verify}")
        verify_w15_upper_bound_sanity(
            report,
            source_artifact=args.source_artifact,
            replay_runtime=args.replay_runtime,
        )
        return 0
    report = run_w15_upper_bound_sanity(source_artifact=args.source_artifact)
    assert args.output is not None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(report))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "DEFAULT_W15_ARTIFACT",
    "run_w15_upper_bound_sanity",
    "verify_w15_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
