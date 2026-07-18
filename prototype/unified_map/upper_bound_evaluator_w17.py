"""Replay-bound PRE-FREEZE upper-bound adapter for W17.

The primary S0 behavioural quotient legitimately merges two histories whose
public context marker is irrelevant to every S0 action.  After the A2 operator
is revealed, those histories have opposite treatment response and the old
state is insufficient.  This adapter live-replays that counterexample and an
explicit judge-side refinement.  It does not recertify seal-before-reveal
chronology, and never promotes the revealed pack digest or the runner's ad-hoc
extension hash to formal eleven-axis UCM scope authority.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
    validate_json_like,
)
from .oracle_certification import (
    NumericTolerance,
    compare_canonical_outputs,
    oracle_output_wire,
)
from .state import StateClass
from .upper_bound_evaluator import (
    STATUS_CHAIN,
    _attach_bundle_root,
    _cell_root,
    _closed,
    _digest,
    _state_binding,
    _verify_state_binding,
    compute_upper_bound_bundle_root,
)
from .upper_bound_evaluator_w16 import (
    _FORMALIZATION_BLOCKERS as _COMMON_FORMALIZATION_BLOCKERS,
    _REPOSITORY_ROOT,
    _W16_LOADED_SOURCE_DIGESTS,
    _capture_loaded_source_digests,
    _extension_source,
    _local_scopes,
    _manifest,
    _parse_extension_source,
    _scope_boundary,
    _scope_statement,
    _seal,
    _source_anchor,
    _source_closure,
    _verify_source_anchor,
    _verify_source_closure,
)
from .worlds.base import WorldSplit
from .worlds.w17 import W17World, make_w17_extension_custody


PROTOCOL = "ucm-pre-freeze-upper-bound-extension-w17/1"
DEFAULT_W17_ARTIFACT = Path("prototype/unified_map/worlds/w17.py")
_CANONICAL_SOURCE = _REPOSITORY_ROOT / DEFAULT_W17_ARTIFACT
_W17_SOURCE_CLOSURE = (
    "prototype/unified_map/upper_bound_evaluator_w17.py",
    "prototype/unified_map/upper_bound_evaluator_w16.py",
    "prototype/unified_map/upper_bound_evaluator.py",
    "prototype/unified_map/worlds/w17.py",
    "prototype/unified_map/extensions.py",
    "prototype/unified_map/candidate_protocol.py",
    "prototype/unified_map/canonical.py",
    "prototype/unified_map/state.py",
    "prototype/unified_map/schema.py",
    "prototype/unified_map/oracle_certification.py",
    "prototype/unified_map/worlds/base.py",
    "prototype/unified_map/worlds/w01.py",
    "prototype/unified_map/worlds/randomness.py",
)
_ORACLE_TOLERANCE = NumericTolerance(absolute=1e-12, relative=1e-12)

_FORMALIZATION_BLOCKERS = [
    *_COMMON_FORMALIZATION_BLOCKERS[:-1],
    "single-pair-live-extension-treatment-counterexample",
]


def _expected_w17_pack(world: W17World) -> dict[str, Any]:
    catalog = world.extension_catalog
    return {
        "protocol": "ucm-world-extension-pack/1",
        "catalog": catalog.to_wire(),
        "catalog_digest": catalog.digest,
        "operator": {
            "action_id": "A2",
            "effect_C0": -0.55,
            "effect_C1": 0.55,
            "cost": 0.08,
        },
        "randomized_validation_arm": {
            "actions": ["NoNewAction", "A2"],
            "probabilities": [0.5, 0.5],
        },
        "frozen_corpus": {"episodes": 512, "old_state_pairs": 256},
        "plaintext_guard": "TREATMENT-EXTENSION-POST-SEAL-ONLY",
    }


def _oracle_wire(value: Any) -> dict[str, Any]:
    return oracle_output_wire(value, include_numerical_diagnostics=False)


def _oracle_pair(world: W17World, episode: Any, policy: Any) -> dict[str, Any]:
    production = _oracle_wire(world.counterfactual(episode, policy, 4, oracle_seed=1))
    reference = _oracle_wire(
        world.reference_counterfactual(episode, policy, 4, oracle_seed=2**64 - 1)
    )
    comparison = compare_canonical_outputs(
        production, reference, _ORACLE_TOLERANCE
    ).to_wire()
    if comparison["passed"] is not True:
        raise ProtocolViolation(
            "W17 production/reference extension behaviour disagrees"
        )
    return {"production": production, "reference": reference, "comparison": comparison}


def _expected_first_mean(oracle: dict[str, Any]) -> float:
    components = oracle["production"]["observation_distribution"]["components"]
    if type(components) is not list or len(components) != 2:
        raise ProtocolViolation("W17 oracle is not the two-class mixture")
    return sum(
        float(row["weight"]) * float(row["steps"][0]["mean"]) for row in components
    )


def _a2_policy(world: W17World) -> Any:
    for policy in world.extension_policy_set(4):
        if any(action.action_id == "A2" for action in policy.actions):
            return policy
    raise ProtocolViolation("W17 extension policy set has no A2 policy")


def _collect_w17_runtime(
    world: W17World, *, pair_seed: int, source_closure_root: str
) -> dict[str, Any]:
    pack_digest = digest_json(_expected_w17_pack(world))
    primary_scope, extension_scope = _local_scopes(
        world_slot="W17",
        primary_catalog_digest=world.catalog.digest,
        extension_catalog_digest=world.extension_catalog.digest,
        pack_digest=pack_digest,
    )
    left, right = world.extension_split_pair(seed=pair_seed)
    left_posterior = world.public_history_posterior(left)
    right_posterior = world.public_history_posterior(right)
    if (
        left_posterior[:2] != right_posterior[:2]
        or left_posterior[2] == right_posterior[2]
    ):
        raise ProtocolViolation(
            "W17 pair does not isolate the primary-irrelevant marker"
        )
    primary_representation = {
        "protocol": "ucm-upper-bound-primary-linear-state/1",
        "semantic_stage": "S0",
        "x_mean": float(left_posterior[0]),
        "x_variance": float(left_posterior[1]),
    }
    primary_state = _seal(
        primary_representation,
        schema_version="ucm-w17-primary-upper-bound-state/1",
        state_class=StateClass.COMPRESSED_SHARED,
        scope_digest=primary_scope,
        catalog_digest=world.catalog.digest,
        model_digest=source_closure_root,
        as_of=left.public_history.as_of_available_at,
        operation="initialize",
    )
    if (
        left.public_history.catalog_digest != world.catalog.digest
        or right.public_history.catalog_digest != world.catalog.digest
        or primary_state.record.catalog_digest != world.catalog.digest
    ):
        raise ProtocolViolation("W17 S0 history/state catalog binding crossed scope")
    if any(
        marker in primary_state.candidate_input.payload.payload
        for marker in (b"A2", b"effect_C0", b"effect_C1", b"class_posterior")
    ):
        raise ProtocolViolation("W17 primary state leaks revealed treatment vocabulary")
    primary_policy_rows = []
    for index, policy in enumerate(world.policy_set(4)):
        left_production = _oracle_wire(
            world.counterfactual(left, policy, 4, oracle_seed=3)
        )
        right_production = _oracle_wire(
            world.counterfactual(right, policy, 4, oracle_seed=5)
        )
        left_reference = _oracle_wire(
            world.reference_counterfactual(left, policy, 4, oracle_seed=7)
        )
        right_reference = _oracle_wire(
            world.reference_counterfactual(right, policy, 4, oracle_seed=11)
        )
        if left_production != right_production:
            raise ProtocolViolation(
                "W17 primary policy unexpectedly uses extension marker"
            )
        comparison_left = compare_canonical_outputs(
            left_production, left_reference, _ORACLE_TOLERANCE
        ).to_wire()
        comparison_right = compare_canonical_outputs(
            right_production, right_reference, _ORACLE_TOLERANCE
        ).to_wire()
        if (
            comparison_left["passed"] is not True
            or comparison_right["passed"] is not True
        ):
            raise ProtocolViolation(
                "W17 primary production/reference behaviour disagrees"
            )
        primary_policy_rows.append(
            {
                "policy_index": index,
                "policy": policy.to_wire(),
                "shared_production_oracle": left_production,
                "left_reference_comparison": comparison_left,
                "right_reference_comparison": comparison_right,
            }
        )

    extension_episodes = (
        world.as_extension_episode(left),
        world.as_extension_episode(right),
    )
    no_action = world.extension_policy_set(4)[0]
    a2 = _a2_policy(world)
    states: dict[str, Any] = {"primary_shared": _state_binding(primary_state)}
    cells: list[dict[str, Any]] = [
        {
            "cell_id": "W17.primary.same_state",
            "world_slot": "W17",
            "cut_alias": "primary-s0-semantics",
            "task": "extension_primary_behavioural_equivalence",
            "state_hash": primary_state.record.state_hash,
            "left_public_history_digest": left.public_history.digest,
            "right_public_history_digest": right.public_history.digest,
            "public_histories_differ": left.public_history.to_wire()
            != right.public_history.to_wire(),
            "primary_marker_omitted_from_state": True,
            "primary_policy_behaviour": primary_policy_rows,
            "same_primary_state": True,
        }
    ]
    effect_directions: list[str] = []
    a2_preferences: list[bool] = []
    refined_hashes: list[str] = []
    for side, episode in zip(("marker_1", "marker_0"), extension_episodes, strict=True):
        posterior = world.public_history_posterior(episode)
        reference = world.reference_public_history_posterior(episode)
        if max(abs(a - b) for a, b in zip(posterior, reference, strict=True)) > 1e-12:
            raise ProtocolViolation(
                "W17 refined production/reference posterior mismatch"
            )
        representation = {
            "protocol": "ucm-w17-revealed-treatment-state/1",
            "semantic_stage": "S1",
            "x_mean": float(posterior[0]),
            "x_variance": float(posterior[1]),
            "class_posterior": {
                "C0": float(1.0 - posterior[2]),
                "C1": float(posterior[2]),
            },
        }
        refined = _seal(
            representation,
            schema_version="ucm-w17-revealed-treatment-state/1",
            state_class=StateClass.DYNAMIC_SHARED,
            scope_digest=extension_scope,
            catalog_digest=world.extension_catalog.digest,
            model_digest=source_closure_root,
            as_of=episode.public_history.as_of_available_at,
            operation="replay",
            parent_state_hash=primary_state.record.state_hash,
            delta_digest=episode.public_history.digest,
        )
        no_action_oracle = _oracle_pair(world, episode, no_action)
        a2_oracle = _oracle_pair(world, episode, a2)
        no_action_mean = _expected_first_mean(no_action_oracle)
        a2_mean = _expected_first_mean(a2_oracle)
        effect = a2_mean - no_action_mean
        direction = "down" if effect < 0.0 else "up"
        preferred = float(a2_oracle["production"]["expected_utility"]) > float(
            no_action_oracle["production"]["expected_utility"]
        )
        states[f"refined_{side}"] = _state_binding(refined)
        refined_hashes.append(refined.record.state_hash)
        effect_directions.append(direction)
        a2_preferences.append(preferred)
        cells.append(
            {
                "cell_id": f"W17.refinement.{side}",
                "world_slot": "W17",
                "cut_alias": f"revealed-{side.replace('_', '-')}",
                "task": "extension_treatment_split_after_explicit_replay",
                "state_hash": refined.record.state_hash,
                "parent_state_hash": primary_state.record.state_hash,
                "history_digest": episode.public_history.digest,
                "candidate_first_query_executed": False,
                "required_honest_state_only_status": "scope_insufficient",
                "explicit_history_replay_required": True,
                "refinement_role": "judge-upper-bound-replay-not-candidate-transcript",
                "class_posterior": representation["class_posterior"],
                "no_new_action": no_action_oracle,
                "a2": a2_oracle,
                "a2_first_mean_delta": effect,
                "a2_effect_direction": direction,
                "a2_preferred_on_panel": preferred,
            }
        )
    if effect_directions != ["down", "up"] or a2_preferences != [True, False]:
        raise ProtocolViolation(
            "W17 revealed A2 did not produce the required opposite split"
        )
    if len(set(refined_hashes)) != 2:
        raise ProtocolViolation("W17 explicit refinements did not split the old state")
    return {
        "fixture": {
            "split": WorldSplit.SEALED_TEST.value,
            "pair_seed": pair_seed,
            "left_primary_history_digest": left.public_history.digest,
            "right_primary_history_digest": right.public_history.digest,
        },
        "scope_boundary": _scope_boundary(
            world_slot="W17",
            primary_scope=primary_scope,
            extension_scope=extension_scope,
            pack_digest=pack_digest,
        ),
        "states": states,
        "cells": cells,
        "verification_facts": {
            "same_primary_state": True,
            "revealed_treatment_tokens_absent_from_primary_payload": True,
            "old_state_insufficient_under_revealed_A2": True,
            "candidate_first_query_claimed": False,
            "explicit_replay_refinement_parent_preserved": True,
            "refined_state_count": 2,
            "opposite_A2_effect_directions": effect_directions,
            "opposite_A2_panel_preferences": a2_preferences,
            "live_production_reference_replay": True,
            "post_seal_reveal_chronology_claimed": False,
        },
    }


def run_w17_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W17_ARTIFACT,
    pair_seed: int = 1701,
) -> dict[str, Any]:
    """Collect one authenticated, live-replayed W17 treatment-extension probe."""

    custody = make_w17_extension_custody()
    extension_source, reveal = _extension_source(custody)
    primary = W17World(extension_commitment=reveal.commitment)
    world = primary.activate_extension(reveal)
    if reveal.pack != _expected_w17_pack(world):
        raise ProtocolViolation("fresh W17 custody did not reveal canonical pack")
    source_closure = _source_closure(
        _W17_SOURCE_CLOSURE,
        loaded_source_digests=_W17_LOADED_SOURCE_DIGESTS,
    )
    runtime = _collect_w17_runtime(
        world,
        pair_seed=pair_seed,
        source_closure_root=source_closure["closure_root"],
    )
    manifest = _manifest("W17")
    body = {
        "protocol": PROTOCOL,
        "bundle_kind": "pre_freeze_privileged_extension_behaviour_probe",
        "world_slot": "W17",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": _scope_statement("W17"),
        "scope_boundary": runtime["scope_boundary"],
        "source_anchor": _source_anchor(source_artifact, _CANONICAL_SOURCE),
        "source_closure": source_closure,
        "extension_source": extension_source,
        "manifest": manifest,
        "manifest_digest": digest_json(manifest),
        "fixture": runtime["fixture"],
        "states": runtime["states"],
        "cells": runtime["cells"],
        "cell_set_root": _cell_root(runtime["cells"]),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_W17_EXTENSION_BEHAVIOUR_PROBE",
            "cell_count": len(runtime["cells"]),
            "state_binding_count": len(runtime["states"]),
            **runtime["verification_facts"],
            "formal_scope_authority": False,
            "ucm_eligible": False,
            "ledger_credit": 0,
            "formalization_blockers": list(_FORMALIZATION_BLOCKERS),
        },
    }
    report = _attach_bundle_root(body)
    verify_w17_upper_bound_sanity(report, source_artifact=source_artifact)
    return report


def verify_w17_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = True,
) -> None:
    """Verify W17 exact source/reveal and rerun both S0 and S1 behaviours."""

    del replay_runtime
    report = _closed(
        value,
        {
            "protocol",
            "bundle_kind",
            "world_slot",
            "status_chain",
            "scope_statement",
            "scope_boundary",
            "source_anchor",
            "source_closure",
            "extension_source",
            "manifest",
            "manifest_digest",
            "fixture",
            "states",
            "cells",
            "cell_set_root",
            "verification_summary",
            "bundle_root",
        },
        "W17 upper-bound extension report",
    )
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "pre_freeze_privileged_extension_behaviour_probe"
        or report["world_slot"] != "W17"
        or report["status_chain"] != STATUS_CHAIN
        or report["scope_statement"] != _scope_statement("W17")
    ):
        raise ProtocolViolation("W17 PRE-FREEZE identity or eligibility mismatch")
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("W17 bundle root mismatch")
    expected_source = (
        source_artifact if source_artifact is not None else DEFAULT_W17_ARTIFACT
    )
    _verify_source_anchor(
        report["source_anchor"],
        source_artifact=expected_source,
        canonical_source=_CANONICAL_SOURCE,
    )
    _verify_source_closure(
        report["source_closure"],
        relative_paths=_W17_SOURCE_CLOSURE,
        loaded_source_digests=_W17_LOADED_SOURCE_DIGESTS,
    )
    reveal, world = _parse_extension_source(
        report["extension_source"],
        world_slot="W17",
        expected_pack=_expected_w17_pack,
        world_factory=W17World,
        custody_factory=make_w17_extension_custody,
    )
    manifest = _manifest("W17")
    if report["manifest"] != manifest or report["manifest_digest"] != digest_json(
        manifest
    ):
        raise ProtocolViolation("W17 adapter manifest mismatch")
    fixture = _closed(
        report["fixture"],
        {
            "split",
            "pair_seed",
            "left_primary_history_digest",
            "right_primary_history_digest",
        },
        "W17 fixture",
    )
    if (
        fixture["split"] != WorldSplit.SEALED_TEST.value
        or type(fixture["pair_seed"]) is not int
        or fixture["pair_seed"] < 0
    ):
        raise ProtocolViolation("W17 fixture identity mismatch")
    _digest(fixture["left_primary_history_digest"], "W17 left history digest")
    _digest(fixture["right_primary_history_digest"], "W17 right history digest")
    expected = _collect_w17_runtime(
        world,
        pair_seed=fixture["pair_seed"],
        source_closure_root=report["source_closure"]["closure_root"],
    )
    if fixture != expected["fixture"]:
        raise ProtocolViolation("W17 fixture differs from live replay")
    if report["scope_boundary"] != expected["scope_boundary"]:
        raise ProtocolViolation("W17 primary/revealed scope boundary mismatch")
    if (
        report["scope_boundary"]["revealed_extension"]["revealed_pack_digest"]
        != reveal.pack_digest
    ):
        raise ProtocolViolation(
            "W17 revealed pack digest is not bound to scope boundary"
        )
    if type(report["states"]) is not dict or report["states"] != expected["states"]:
        raise ProtocolViolation("W17 state bindings differ from live reconstruction")
    for alias, state in report["states"].items():
        _verify_state_binding(state, f"W17 state {alias}")
        if state["record"]["model_digest"] != report["source_closure"]["closure_root"]:
            raise ProtocolViolation(
                "W17 state model digest is not source-closure-bound"
            )
    if report["cells"] != expected["cells"]:
        raise ProtocolViolation("W17 cells differ from live extension behaviour")
    if report["cell_set_root"] != _cell_root(report["cells"]):
        raise ProtocolViolation("W17 cell-set root mismatch")
    expected_summary = {
        "status": "VALID_PRE_FREEZE_W17_EXTENSION_BEHAVIOUR_PROBE",
        "cell_count": len(expected["cells"]),
        "state_binding_count": len(expected["states"]),
        **expected["verification_facts"],
        "formal_scope_authority": False,
        "ucm_eligible": False,
        "ledger_credit": 0,
        "formalization_blockers": _FORMALIZATION_BLOCKERS,
    }
    if report["verification_summary"] != expected_summary:
        raise ProtocolViolation("W17 verification summary was overstated")


def _load_canonical_report(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read canonical report {path}") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise SystemExit(f"{path} is not canonical JSON")
    return value


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run or verify the W17 PRE-FREEZE extension probe"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify-bundle", type=Path)
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_W17_ARTIFACT)
    parser.add_argument("--pair-seed", type=int, default=1701)
    args = parser.parse_args()
    if args.output is not None:
        report = run_w17_upper_bound_sanity(
            source_artifact=args.source_artifact,
            pair_seed=args.pair_seed,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.output.open("xb") as stream:
                stream.write(canonical_json_bytes(report))
        except FileExistsError as exc:
            raise SystemExit(f"refusing to overwrite {args.output}") from exc
        except OSError as exc:
            raise SystemExit(f"cannot write {args.output}") from exc
        return 0
    verify_w17_upper_bound_sanity(
        _load_canonical_report(args.verify_bundle),
        source_artifact=args.source_artifact,
    )
    return 0


_W17_BOTTOM_SOURCE_DIGESTS = _capture_loaded_source_digests(_W17_SOURCE_CLOSURE)
_W17_LOADED_SOURCE_DIGESTS = {
    relative: _W16_LOADED_SOURCE_DIGESTS.get(
        relative, _W17_BOTTOM_SOURCE_DIGESTS[relative]
    )
    for relative in _W17_SOURCE_CLOSURE
}


__all__ = [
    "DEFAULT_W17_ARTIFACT",
    "run_w17_upper_bound_sanity",
    "verify_w17_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
