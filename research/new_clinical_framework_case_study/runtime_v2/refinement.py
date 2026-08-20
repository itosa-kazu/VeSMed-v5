"""Executable behavioral-collision detection and local stratum refinement.

The unit of repair is deliberately local: a collision never adds a global
diagnostic bonus or changes an unrelated process.  If no registered public
check separates compatible worlds, the only valid result is typed
``UNIDENTIFIABLE`` and the model is left untouched.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .engine import RuntimeV2
from .architecture_wire import model_time_from_as_of
from .migration import migrate_v2_state
from .schema import (
    PublicEvent,
    SharedPatientState,
    digest,
    validate_migration_spec,
    validate_model_spec,
)


OLD_SCOPE_NON_REGRESSION_TOLERANCE = 1e-12


def _old_scope_projection(value: Any, *, affected_process_id: str) -> Any:
    """Remove only metadata that an explicit local refinement versions.

    The new local-stratum posterior and the observation-catalog digest are the
    declared scope change.  Diagnosis, natural forecast, unaffected action
    rollouts, and restricted planning outputs remain part of the frozen old
    scope and are compared below.
    """

    if isinstance(value, Mapping):
        projected: dict[str, Any] = {}
        for key, child in value.items():
            if key == "consumed_state_hash":
                continue
            if key == "local_stratum_posteriors" and isinstance(child, Mapping):
                # Only the stratum being split is outside the frozen old
                # query.  Unrelated stratum posteriors are mandatory
                # non-regression evidence and must not be hidden globally.
                projected[key] = {
                    str(process_id): _old_scope_projection(
                        posterior, affected_process_id=affected_process_id
                    )
                    for process_id, posterior in child.items()
                    if str(process_id) != affected_process_id
                }
                continue
            if key == "action_stratum_modifier_trace" and isinstance(child, list):
                projected[key] = [
                    {
                        str(trace_key): _old_scope_projection(
                            trace_value, affected_process_id=affected_process_id
                        )
                        for trace_key, trace_value in row.items()
                        if not (
                            str(row.get("process_id")) == affected_process_id
                            and trace_key == "stratum_components"
                        )
                    }
                    for row in child
                ]
                continue
            if key == "scope" and isinstance(child, Mapping):
                projected[key] = {
                    str(scope_key): _old_scope_projection(
                        scope_value, affected_process_id=affected_process_id
                    )
                    for scope_key, scope_value in child.items()
                    if scope_key not in {
                        "observation_catalog_digest",
                        "action_catalog_digest",
                        "policy_catalog_digest",
                        "utility_digest",
                    }
                }
            elif key == "causal_nonidentifiability":
                # This aggregate is intentionally changed when A is extended;
                # old action-specific claims remain compared in their own
                # query results.
                continue
            else:
                projected[str(key)] = _old_scope_projection(
                    child, affected_process_id=affected_process_id
                )
        return projected
    if isinstance(value, list):
        return [
            _old_scope_projection(child, affected_process_id=affected_process_id)
            for child in value
        ]
    return copy.deepcopy(value)


def _within_tolerance(left: Any, right: Any, *, tolerance: float) -> bool:
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return abs(float(left) - float(right)) <= tolerance
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _within_tolerance(left[key], right[key], tolerance=tolerance)
            for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _within_tolerance(a, b, tolerance=tolerance)
            for a, b in zip(left, right)
        )
    return left == right


def _old_scope_query_corpus(
    runtime: RuntimeV2,
    state: SharedPatientState,
    *,
    affected_action_id: str,
    affected_process_id: str,
) -> dict[str, Any]:
    """Run every old-scope head not intentionally changed by the split."""

    noop = {"policy_id": "NO_NEW_ACTION", "start_actions": []}
    unaffected_policies = [noop]
    corpus: dict[str, Any] = {
        "diagnose": _old_scope_projection(
            runtime.diagnose(state), affected_process_id=affected_process_id
        ),
        "forecast_no_new_action": _old_scope_projection(
            runtime.forecast(state, horizon=2),
            affected_process_id=affected_process_id,
        ),
    }
    for action_id in sorted(runtime.actions):
        if action_id == affected_action_id:
            continue
        policy = {
            "policy_id": f"START_UNAFFECTED:{action_id}",
            "start_actions": [{"action_id": action_id, "dose": 1.0}],
        }
        unaffected_policies.append(policy)
        corpus[f"rollout_unaffected:{action_id}"] = _old_scope_projection(
            runtime.rollout(state, policy, horizon=2),
            affected_process_id=affected_process_id,
        )
    corpus["plan_unaffected_policies"] = _old_scope_projection(
        runtime.plan(state, unaffected_policies, horizon=2),
        affected_process_id=affected_process_id,
    )
    return corpus


@dataclass(frozen=True)
class RefinementExecution:
    runtime: RuntimeV2
    migrated_state: SharedPatientState
    refined_state: SharedPatientState
    report: dict[str, Any]


def evaluate_behavioral_collision(
    worlds: Iterable[Mapping[str, Any]],
    *,
    old_action_ids: Iterable[str],
    new_action_id: str,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Find frozen-state worlds with incompatible optimal safe actions.

    A dangerous collision is not synonymous with an opposite-signed treatment
    response.  Under the frozen definition it requires (1) old-scope response
    equivalence, (2) a difference in optimal safe value greater than epsilon,
    and (3) disjoint optimal-safe action sets.  The input accepts compact
    numeric ``action_outcomes`` as utilities and also explicit utility/safety
    and optimal-action witnesses.
    """

    def utility(world: Mapping[str, Any], action_id: str) -> float | None:
        if action_id in world.get("action_utilities", {}):
            return float(world["action_utilities"][action_id])
        raw = world.get("action_outcomes", {}).get(action_id)
        if isinstance(raw, Mapping):
            for key in ("utility", "value", "outcome"):
                if key in raw:
                    return float(raw[key])
            return None
        return None if raw is None else float(raw)

    def safe(world: Mapping[str, Any], action_id: str) -> bool:
        if action_id in world.get("action_safety", {}):
            return bool(world["action_safety"][action_id])
        if "safe_action_ids" in world:
            return action_id in {str(value) for value in world["safe_action_ids"]}
        raw = world.get("action_outcomes", {}).get(action_id)
        if isinstance(raw, Mapping) and "safe" in raw:
            return bool(raw["safe"])
        return True

    def optimal_safe(
        world: Mapping[str, Any], action_ids: list[str]
    ) -> tuple[set[str], float] | None:
        explicit = world.get("optimal_safe_action_ids")
        values = {
            action_id: utility(world, action_id)
            for action_id in action_ids
            if safe(world, action_id)
        }
        values = {key: value for key, value in values.items() if value is not None}
        if explicit is not None:
            actions = {str(value) for value in explicit}.intersection(values)
            if not actions:
                return None
            declared_value = world.get("optimal_safe_value")
            best = (
                float(declared_value)
                if declared_value is not None
                else max(float(values[action_id]) for action_id in actions)
            )
            return actions, best
        if not values:
            return None
        best = max(float(value) for value in values.values())
        actions = {
            action_id
            for action_id, value in values.items()
            if abs(float(value) - best) <= tolerance
        }
        return actions, best

    rows = [copy.deepcopy(dict(row)) for row in worlds]
    old_ids = sorted(set(str(value) for value in old_action_ids))
    witnesses: list[dict[str, Any]] = []
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            if digest(left.get("old_state")) != digest(right.get("old_state")):
                continue
            if any(
                utility(left, action_id) is None
                or utility(right, action_id) is None
                or safe(left, action_id) != safe(right, action_id)
                or abs(float(utility(left, action_id)) - float(utility(right, action_id))) > tolerance
                for action_id in old_ids
            ):
                continue
            left_response = utility(left, new_action_id)
            right_response = utility(right, new_action_id)
            if left_response is None or right_response is None:
                continue
            action_ids = [*old_ids, str(new_action_id)]
            left_optimal = optimal_safe(left, action_ids)
            right_optimal = optimal_safe(right, action_ids)
            if left_optimal is None or right_optimal is None:
                continue
            left_actions, left_value = left_optimal
            right_actions, right_value = right_optimal
            if abs(left_value - right_value) <= tolerance:
                continue
            if left_actions.intersection(right_actions):
                continue
            left_old = optimal_safe(left, old_ids)
            right_old = optimal_safe(right, old_ids)
            if left_old is None or right_old is None:
                continue
            left_advantage = (
                float(left_response) - left_old[1]
                if safe(left, new_action_id)
                else -max(1.0, abs(float(left_response) - left_old[1]))
            )
            right_advantage = (
                float(right_response) - right_old[1]
                if safe(right, new_action_id)
                else -max(1.0, abs(float(right_response) - right_old[1]))
            )
            witnesses.append(
                {
                    "world_ids": sorted([str(left["world_id"]), str(right["world_id"])]),
                    "old_state_digest": digest(left.get("old_state")),
                    "old_action_outcomes": {
                        action_id: [
                            float(utility(left, action_id)),
                            float(utility(right, action_id)),
                        ]
                        for action_id in old_ids
                    },
                    "new_action_id": str(new_action_id),
                    "new_action_outcomes": [left_response, right_response],
                    "new_action_outcome_by_world": {
                        str(left["world_id"]): float(left_response),
                        str(right["world_id"]): float(right_response),
                    },
                    "new_action_advantage_by_world": {
                        str(left["world_id"]): left_advantage,
                        str(right["world_id"]): right_advantage,
                    },
                    "optimal_safe_action_ids_by_world": {
                        str(left["world_id"]): sorted(left_actions),
                        str(right["world_id"]): sorted(right_actions),
                    },
                    "optimal_safe_value_by_world": {
                        str(left["world_id"]): left_value,
                        str(right["world_id"]): right_value,
                    },
                    "optimal_safe_value_difference": abs(left_value - right_value),
                    "response_relation": (
                        "OPPOSITE_SIGN"
                        if float(left_response) * float(right_response) < 0.0
                        else "SAME_SIGN"
                    ),
                    "collision_basis": "INCOMPATIBLE_OPTIMAL_SAFE_ACTIONS",
                }
            )
    return {
        "status": "COLLISION_WITNESS" if witnesses else "NO_COLLISION",
        "old_action_ids": old_ids,
        "new_action_id": str(new_action_id),
        "tolerance": float(tolerance),
        "witnesses": witnesses,
        "world_digest": digest(rows),
    }


def _refined_spec(
    source_model_spec: Mapping[str, Any],
    collision: Mapping[str, Any],
    refinement: Mapping[str, Any],
) -> dict[str, Any]:
    spec = validate_model_spec(source_model_spec)
    spec["model_id"] = str(refinement.get("target_model_id") or f"{spec['model_id']}:refined")
    process_id = str(refinement["process_id"])
    process = next((row for row in spec["processes"] if row["process_id"] == process_id), None)
    if process is None:
        raise ValueError(f"refinement references unknown process: {process_id}")
    child_strata = copy.deepcopy(list(refinement.get("child_strata", [])))
    if len(child_strata) < 2:
        raise ValueError("local refinement requires at least two child strata")
    witness_worlds = {
        world_id
        for witness in collision.get("witnesses", [])
        for world_id in witness["world_ids"]
    }
    covered = {
        str(world_id)
        for stratum in child_strata
        for world_id in stratum.get("compatible_world_ids", [])
    }
    if witness_worlds and not witness_worlds.issubset(covered):
        raise ValueError("child strata do not cover collision witness worlds")
    new_action_id = str(collision.get("new_action_id") or "")
    if not new_action_id:
        raise ValueError("collision witness must name the scope-extending action")
    action_ids = {row["action_id"] for row in spec["actions"]}
    new_action_spec = refinement.get("new_action_spec")
    if new_action_id not in action_ids:
        if not isinstance(new_action_spec, Mapping):
            raise ValueError(
                "scope-extending collision requires an explicit new_action_spec"
            )
        action_row = copy.deepcopy(dict(new_action_spec))
        if str(action_row.get("action_id") or "") != new_action_id:
            raise ValueError("new_action_spec.action_id must match collision new_action_id")
        spec["actions"].append(action_row)
        action_ids.add(new_action_id)
    elif new_action_spec is not None:
        if str(new_action_spec.get("action_id") or "") != new_action_id:
            raise ValueError("new_action_spec conflicts with already registered collision action")
        declared = next(row for row in spec["actions"] if row["action_id"] == new_action_id)
        if digest(declared) != digest(dict(new_action_spec)):
            raise ValueError("new_action_spec attempts to redefine an existing action")
    response_by_world: dict[str, float] = {}
    for witness in collision.get("witnesses", []):
        response_by_world.update(
            {
                str(world_id): float(outcome)
                for world_id, outcome in (
                    witness.get("new_action_advantage_by_world")
                    or witness.get("new_action_outcome_by_world", {})
                ).items()
            }
        )
    existing_strata = copy.deepcopy(
        process.get("strata")
        or [{"stratum_id": f"stratum:{process_id}", "prior": 1.0}]
    )
    parent_stratum_id = refinement.get("parent_stratum_id")
    if parent_stratum_id is None:
        if len(existing_strata) != 1:
            raise ValueError(
                "refining an already stratified process requires parent_stratum_id"
            )
        parent_stratum_id = existing_strata[0]["stratum_id"]
    parent = next(
        (row for row in existing_strata if row["stratum_id"] == parent_stratum_id),
        None,
    )
    if parent is None:
        raise ValueError(f"unknown parent stratum: {parent_stratum_id}")
    conditional_prior_total = sum(float(row["prior"]) for row in child_strata)
    if abs(conditional_prior_total - 1.0) > 1e-12:
        raise ValueError("child stratum conditional priors must sum to one")
    process["strata"] = [
        row for row in existing_strata if row["stratum_id"] != parent_stratum_id
    ]
    child_behavior_values: dict[str, float] = {}
    for row in child_strata:
        modifiers = copy.deepcopy(row.get("action_effect_modifiers", {}))
        if not modifiers:
            values = [
                response_by_world[world_id]
                for world_id in row.get("compatible_world_ids", [])
                if world_id in response_by_world
            ]
            if values:
                mean_response = sum(values) / len(values)
                modifiers[new_action_id] = 1.0 if mean_response > 0.0 else -1.0 if mean_response < 0.0 else 0.0
                child_behavior_values[str(row["stratum_id"])] = mean_response
        if str(row["stratum_id"]) not in child_behavior_values:
            child_behavior_values[str(row["stratum_id"])] = float(
                modifiers.get(new_action_id, 1.0)
            )
        process["strata"].append(
            {
                "stratum_id": str(row["stratum_id"]),
                "prior": float(parent["prior"]) * float(row["prior"]),
                "action_effect_modifiers": {
                    str(action_id): float(value)
                    for action_id, value in sorted(modifiers.items())
                },
            }
        )
    topology = spec.setdefault("topology", {})
    inherited_edges: list[dict[str, Any]] = []
    for edge in topology.get("stratum_edges", []):
        source_sid = edge["source_stratum_id"]
        target_sid = edge["target_stratum_id"]
        if parent_stratum_id not in {source_sid, target_sid}:
            inherited_edges.append(copy.deepcopy(edge))
            continue
        for child in child_strata:
            replacement = copy.deepcopy(edge)
            if source_sid == parent_stratum_id:
                replacement["source_stratum_id"] = str(child["stratum_id"])
            if target_sid == parent_stratum_id:
                replacement["target_stratum_id"] = str(child["stratum_id"])
            inherited_edges.append(replacement)
    behavior_edges: list[dict[str, Any]] = []
    child_ids = sorted(child_behavior_values)
    for index, source_sid in enumerate(child_ids):
        for target_sid in child_ids[index + 1 :]:
            raw_distance = abs(
                child_behavior_values[source_sid]
                - child_behavior_values[target_sid]
            )
            if raw_distance <= float(collision.get("tolerance", 1e-9)):
                continue
            # Response utilities are not in process-topology distance units.
            # Map their positive separation to the declared normalized
            # behavioral metric while preserving order and non-zero identity.
            distance = raw_distance / (1.0 + raw_distance)
            behavior_edges.append(
                {
                    "source_stratum_id": source_sid,
                    "target_stratum_id": target_sid,
                    "distance": float(distance),
                    "directed": False,
                }
            )
    if not behavior_edges:
        raise ValueError(
            "refinement child strata do not create a positive behavioral geometry distance"
        )
    topology["stratum_edges"] = [*inherited_edges, *behavior_edges]
    observation = copy.deepcopy(dict(refinement["separating_observation"]))
    likelihoods = {
        str(row["stratum_id"]): copy.deepcopy(row["likelihood"])
        for row in child_strata
    }
    neutral = copy.deepcopy(observation["neutral_process_likelihood"])
    likelihoods.update(
        {
            str(row["stratum_id"]): copy.deepcopy(neutral)
            for row in process["strata"]
            if row["stratum_id"] not in likelihoods
        }
    )
    spec["observations"].append(
        {
            "concept_id": str(observation["concept_id"]),
            "factor_id": str(observation["factor_id"]),
            "reliability": float(observation.get("reliability", 1.0)),
            "emissions": [
                {
                    "process_id": process_id,
                    "active_likelihood": neutral,
                    "inactive_likelihood": copy.deepcopy(neutral),
                    "stratum_likelihoods": likelihoods,
                }
            ],
        }
    )
    spec["refinement_registry"] = [
        *copy.deepcopy(spec.get("refinement_registry", [])),
        {
            "collision_digest": digest(collision),
            "parent_process_id": process_id,
            "parent_stratum_id": str(parent_stratum_id),
            "child_stratum_ids": sorted(likelihoods),
            "separating_concept_id": observation["concept_id"],
        },
    ]
    return validate_model_spec(spec)


def execute_local_refinement(
    source_state: SharedPatientState,
    source_model_spec: Mapping[str, Any],
    collision: Mapping[str, Any],
    refinement: Mapping[str, Any],
    *,
    separating_event: PublicEvent | Mapping[str, Any] | None,
    migration_id: str,
) -> RefinementExecution | dict[str, Any]:
    """Split one local stratum only when an available public check separates it."""

    if collision.get("status") != "COLLISION_WITNESS":
        return {
            "status": "NO_REFINEMENT_REQUIRED",
            "reason": "No behavioral collision witness was supplied.",
            "model_changed": False,
        }
    if separating_event is None:
        return {
            "status": "UNIDENTIFIABLE",
            "reason": "Compatible collision worlds require incompatible optimal safe actions and no separating public information is available.",
            "compatible_world_ids": sorted(
                {
                    world_id
                    for witness in collision["witnesses"]
                    for world_id in witness["world_ids"]
                }
            ),
            "identified_set": {"lower": None, "upper": None, "unit": "action_response"},
            "model_changed": False,
        }
    event = separating_event if isinstance(separating_event, PublicEvent) else PublicEvent.from_dict(separating_event)
    observation = refinement["separating_observation"]
    if event.payload.get("event_type") != "ObservationAvailable" or event.payload.get("concept_id") != observation["concept_id"]:
        raise ValueError("separating event does not match registered refinement observation")

    source_runtime = RuntimeV2(source_model_spec)
    target_spec = _refined_spec(source_model_spec, collision, refinement)
    target_runtime = RuntimeV2(target_spec)
    coordinate_maps = {
        pid: {
            row["coordinate_id"]: row["coordinate_id"]
            for row in source_runtime.processes[pid]["coordinates"]
        }
        for pid in source_runtime.process_ids
    }
    mode_maps = {
        pid: {row["mode_id"]: row["mode_id"] for row in source_runtime.processes[pid]["modes"]}
        for pid in source_runtime.process_ids
    }
    affected_process_id = str(refinement["process_id"])
    source_strata = {
        pid: (
            source_runtime.processes[pid].get("strata")
            or [{"stratum_id": f"stratum:{pid}", "prior": 1.0}]
        )
        for pid in source_runtime.process_ids
    }
    parent_stratum_id = refinement.get("parent_stratum_id")
    if parent_stratum_id is None:
        if len(source_strata[affected_process_id]) != 1:
            raise ValueError(
                "refining an already stratified process requires parent_stratum_id"
            )
        parent_stratum_id = source_strata[affected_process_id][0]["stratum_id"]
    stratum_maps: dict[str, dict[str, Any]] = {
        pid: {row["stratum_id"]: row["stratum_id"] for row in rows}
        for pid, rows in source_strata.items()
    }
    stratum_maps[affected_process_id][str(parent_stratum_id)] = {
        str(row["stratum_id"]): float(row["prior"])
        for row in refinement["child_strata"]
    }
    migration = {
        "migration_id": str(migration_id),
        "from_model_digest": source_runtime.model_digest,
        "to_model_digest": target_runtime.model_digest,
        "process_map": {pid: pid for pid in source_runtime.process_ids},
        "coordinate_maps": coordinate_maps,
        "mode_maps": mode_maps,
        "stratum_maps": stratum_maps,
        "action_map": {action_id: action_id for action_id in source_runtime.actions},
        "refinement_lineage": {
            "kind": "behavioral_collision_local_stratum_split",
            "collision_digest": digest(collision),
            "parent_process_id": refinement["process_id"],
            "parent_stratum_id": str(parent_stratum_id),
            "child_stratum_ids": sorted(row["stratum_id"] for row in refinement["child_strata"]),
            "separating_event_id": event.event_id,
        },
    }
    migration = validate_migration_spec(migration)
    affected_action_id = str(collision.get("new_action_id") or "")
    before = source_runtime.diagnose(source_state)
    old_scope_before = _old_scope_query_corpus(
        source_runtime,
        source_state,
        affected_action_id=affected_action_id,
        affected_process_id=affected_process_id,
    )
    migrated = migrate_v2_state(source_state, source_runtime.spec, target_runtime, migration)
    after_migration = target_runtime.diagnose(migrated)
    if any(
        abs(
            float(before["process_activation_marginals"][pid])
            - float(after_migration["process_activation_marginals"][pid])
        ) > 1e-12
        for pid in source_runtime.process_ids
    ):
        raise AssertionError("local refinement violated old-scope process posterior non-regression")
    old_scope_after = _old_scope_query_corpus(
        target_runtime,
        migrated,
        affected_action_id=affected_action_id,
        affected_process_id=affected_process_id,
    )
    if set(old_scope_before) != set(old_scope_after):
        raise AssertionError("local refinement changed the old-scope query corpus")
    old_scope_comparisons = {
        query_id: {
            "within_tolerance": _within_tolerance(
                old_scope_before[query_id],
                old_scope_after[query_id],
                tolerance=OLD_SCOPE_NON_REGRESSION_TOLERANCE,
            ),
            "before_sha256": digest(old_scope_before[query_id]),
            "after_sha256": digest(old_scope_after[query_id]),
        }
        for query_id in old_scope_before
    }
    if not all(
        row["within_tolerance"] for row in old_scope_comparisons.values()
    ):
        raise AssertionError("local refinement violated complete old-scope query non-regression")
    refined = target_runtime.update(migrated, [event], advance_to=max(
        model_time_from_as_of(migrated.payload["as_of"]),
        float(event.payload["available_at"]),
    ))
    report = {
        "status": "REFINED",
        "collision_digest": digest(collision),
        "source_model_digest": source_runtime.model_digest,
        "target_model_digest": target_runtime.model_digest,
        "migration_id": migration_id,
        "migration_contract": {
            "schema_validated": True,
            "migration_spec_digest": digest(migration),
            "migration_spec": copy.deepcopy(migration),
        },
        "affected_process_id": refinement["process_id"],
        "action_scope_extension": {
            "action_id": affected_action_id,
            "was_previously_registered": affected_action_id in source_runtime.actions,
            "is_registered_after_refinement": affected_action_id in target_runtime.actions,
            "source_action_catalog_digest": digest(source_runtime.spec["actions"]),
            "target_action_catalog_digest": digest(target_runtime.spec["actions"]),
        },
        "affected_stratum_ids": sorted(row["stratum_id"] for row in refinement["child_strata"]),
        "unrelated_processes_unchanged": {
            pid: abs(
                float(before["process_activation_marginals"][pid])
                - float(after_migration["process_activation_marginals"][pid])
            ) <= 1e-12
            for pid in source_runtime.process_ids
            if pid != refinement["process_id"]
        },
        "old_scope_process_posterior_non_regression": True,
        "old_scope_query_non_regression": {
            "status": "PASS",
            "absolute_tolerance": OLD_SCOPE_NON_REGRESSION_TOLERANCE,
            "relative_tolerance": 0.0,
            "declared_scope_change_exclusions": [
                "consumed_state_hash",
                "local_stratum_posteriors",
                "identifiability.scope.observation_catalog_digest",
            ],
            "affected_action_id_excluded": affected_action_id,
            "query_manifest": old_scope_comparisons,
        },
        "separating_event_id": event.event_id,
    }
    return RefinementExecution(target_runtime, migrated, refined, report)


__all__ = ["RefinementExecution", "evaluate_behavioral_collision", "execute_local_refinement"]
