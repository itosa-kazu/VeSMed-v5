"""Exact PRE-FREEZE public-oracle upper-bound adapter for W03.

The four adapters W03/W05/W06/W07 share the implementation in this module.
They are intentionally *not* true-state readers.  Their candidate state is the
exact candidate-visible ``PublicHistory`` and their head is the world's public
history oracle.  Collection also replaces every judge-private episode field
and requires the head bytes to remain identical.  This makes use of the world
law an explicit upper bound without smuggling realised class, latent state,
future, propensity, or split-private fields into the candidate state.

These bundles are evidence machinery only: PRE-FREEZE, upper-bound-only,
``ucm_eligible=false``, zero ledger credit, and no freeze authority.  W03 and
W05 expose full reference agreement.  W06 and W07 expose expected-utility
reference agreement only.  Source/runtime separation certification is not
embedded, so all four retain an explicit blocker and make no source-distinct
claim.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import inspect
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Callable

import numpy as np

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .schema import DiagnosisQuery, PlanKind, RolloutQuery
from .state import StateClass, StatePayload, compute_state_hash
from .upper_bound_evaluator import (
    PROTOCOL,
    STATE_BINDING_PROTOCOL,
    STATUS_CHAIN,
    _attach_bundle_root,
    _cell_root,
    _closed,
    _digest,
    _finite,
    _oracle_comparison,
    _oracle_wire,
    _verify_state_binding,
    compute_upper_bound_bundle_root,
)
from .worlds.base import CounterfactualOracle, MicroWorld, PrivateEpisode, WorldSplit
from .worlds.w03 import W03World


DEFAULT_W03_SOURCE = Path("prototype/unified_map/worlds/w03.py")
# Kept for the same adapter-facing API used by the existing suite.
DEFAULT_W03_ARTIFACT = DEFAULT_W03_SOURCE
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SHARED_EVALUATOR_SOURCE = Path("prototype/unified_map/upper_bound_evaluator_w03.py")
_QUANTIZATION_SCALE = 1e-12
_LOADED_EVALUATOR_SOURCE_DIGESTS: dict[str, str] = {}


def _register_loaded_evaluator_source(relpath: Path, module_file: str) -> None:
    """Record exact evaluator/helper bytes while its module is importing.

    World modules are compiled from anchored bytes separately.  Imported
    evaluator wrappers and helpers register here during module execution.
    Collection and verification later require the live repository bytes to
    equal this process-local digest, closing post-import source drift instead
    of binding new bytes to stale code objects.
    """

    if not isinstance(relpath, Path) or relpath.is_absolute() or ".." in relpath.parts:
        raise ProtocolViolation("loaded evaluator source must be repo-relative")
    normalized = relpath.as_posix()
    if not normalized.startswith("prototype/unified_map/") or not normalized.endswith(
        ".py"
    ):
        raise ProtocolViolation("loaded evaluator source is outside its package")
    expected_path = (_REPOSITORY_ROOT / relpath).resolve()
    actual_path = Path(module_file).resolve()
    if actual_path != expected_path:
        raise ProtocolViolation("loaded evaluator module path does not match its role")
    try:
        digest = digest_bytes(actual_path.read_bytes())
    except OSError as exc:
        raise ProtocolViolation(
            f"loaded evaluator source is unavailable: {normalized}"
        ) from exc
    existing = _LOADED_EVALUATOR_SOURCE_DIGESTS.get(normalized)
    if existing is not None and existing != digest:
        raise ProtocolViolation(
            "loaded evaluator source changed after its first process attestation"
        )
    _LOADED_EVALUATOR_SOURCE_DIGESTS[normalized] = digest


@dataclass(frozen=True, slots=True)
class _PublicOracleAdapterConfig:
    world_slot: str
    world_factory: Callable[[], MicroWorld]
    committed_source: Path
    generator_seed: int
    episode_index: int
    oracle_seed: int
    reference_tolerance: float
    source_class_name: str | None = None
    adapter_source: Path | None = None
    additional_evaluator_sources: tuple[Path, ...] = ()


_W03_CONFIG = _PublicOracleAdapterConfig(
    world_slot="W03",
    world_factory=W03World,
    committed_source=DEFAULT_W03_SOURCE,
    generator_seed=92003,
    episode_index=13,
    oracle_seed=3003,
    reference_tolerance=1e-12,
    source_class_name="W03World",
    adapter_source=_SHARED_EVALUATOR_SOURCE,
)


def _source_bytes(supplied: Path | str, *, committed: Path, world_slot: str) -> bytes:
    committed_path = _REPOSITORY_ROOT / committed
    supplied_path = Path(supplied)
    if not supplied_path.is_absolute():
        supplied_path = _REPOSITORY_ROOT / supplied_path
    try:
        committed_raw = committed_path.read_bytes()
        supplied_raw = supplied_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(f"{world_slot} world source is unavailable") from exc
    if supplied_raw != committed_raw:
        raise ProtocolViolation(
            f"{world_slot} supplied world source is not byte-identical to the "
            "repository-owned canonical source"
        )
    if not committed_raw or b"class " not in committed_raw:
        raise ProtocolViolation(f"{world_slot} canonical world source is malformed")
    return committed_raw


def _evaluator_source_closure(
    config: _PublicOracleAdapterConfig,
) -> dict[str, Any]:
    """Bind wrapper, shared evaluator, world, and declared helper bytes."""

    if not isinstance(config.committed_source, Path) or (
        config.adapter_source is not None
        and not isinstance(config.adapter_source, Path)
    ):
        raise ProtocolViolation("configured evaluator sources must be Paths")
    paths_by_role: dict[Path, set[str]] = {
        config.committed_source: {"world_source"},
        _SHARED_EVALUATOR_SOURCE: {"shared_evaluator"},
    }
    adapter_source = config.adapter_source or _SHARED_EVALUATOR_SOURCE
    paths_by_role.setdefault(adapter_source, set()).add("adapter_entrypoint")
    if type(config.additional_evaluator_sources) is not tuple:
        raise ProtocolViolation("additional evaluator sources must be a tuple")
    for path in config.additional_evaluator_sources:
        if not isinstance(path, Path):
            raise ProtocolViolation("additional evaluator source must be a Path")
        paths_by_role.setdefault(path, set()).add("additional_dependency")

    files: list[dict[str, Any]] = []
    ordered_paths = sorted(
        paths_by_role, key=lambda item: item.as_posix().encode("utf-8")
    )
    for relpath in ordered_paths:
        if relpath.is_absolute() or ".." in relpath.parts:
            raise ProtocolViolation("evaluator source dependency must be repo-relative")
        normalized = relpath.as_posix()
        if not normalized.startswith(
            "prototype/unified_map/"
        ) or not normalized.endswith(".py"):
            raise ProtocolViolation(
                "evaluator source dependency is outside its isolated package"
            )
        try:
            raw = (_REPOSITORY_ROOT / relpath).read_bytes()
        except OSError as exc:
            raise ProtocolViolation(
                f"evaluator source dependency is unavailable: {normalized}"
            ) from exc
        if not raw:
            raise ProtocolViolation("evaluator source dependency is empty")
        live_digest = digest_bytes(raw)
        roles = paths_by_role[relpath]
        if roles == {"world_source"}:
            runtime_attestation = {
                "mode": "exact-world-source-byte-compile",
                "attested_digest": live_digest,
            }
        else:
            loaded_digest = _LOADED_EVALUATOR_SOURCE_DIGESTS.get(normalized)
            if loaded_digest is None:
                raise ProtocolViolation(
                    f"evaluator source lacks import-time attestation: {normalized}"
                )
            if loaded_digest != live_digest:
                raise ProtocolViolation(
                    f"loaded evaluator source differs from live bytes: {normalized}"
                )
            runtime_attestation = {
                "mode": "import-time-source-digest-match",
                "attested_digest": loaded_digest,
            }
        files.append(
            {
                "relpath": normalized,
                "roles": sorted(roles),
                "digest": live_digest,
                "bytes": len(raw),
                "runtime_attestation": runtime_attestation,
            }
        )
    preimage = {
        "protocol": "ucm-upper-bound-evaluator-source-closure/1",
        "files": files,
    }
    return {**preimage, "closure_root": digest_json(preimage)}


def _manifest(config: _PublicOracleAdapterConfig, world: MicroWorld) -> dict[str, Any]:
    return {
        "protocol": "ucm-public-oracle-upper-bound-manifest/1",
        "baseline_id": "B01-PUBLIC-ORACLE-UPPER-BOUND",
        "world_slot": config.world_slot,
        "catalog_digest": world.catalog.digest,
        "privileged_world_law": True,
        "candidate_input": "candidate-visible-public-history-only",
        "eligibility": "upper_bound_only",
        "ucm_eligible": False,
        "freeze_grade": False,
    }


def _scope_statement(reference_kind: str) -> dict[str, Any]:
    return {
        "public_history_state_only": True,
        "private_swap_invariance_required": True,
        "public_posterior_primary_claimed": True,
        "realized_true_class_score_claimed": False,
        "mean_and_expected_utility_projection_only": True,
        "proper_distribution_score_claimed": False,
        "candidate_performance_claimed": False,
        "formal_b01_claimed": False,
        "recursive_update_claimed": False,
        "full_reference_agreement_observed": reference_kind == "full_oracle",
        "source_distinct_full_reference_claimed": False,
        "source_distinct_utility_reference_claimed": False,
    }


def _quantized(values: list[float]) -> dict[str, Any]:
    clean = [_finite(value, "quantized projection value") for value in values]
    return {
        "protocol": "ucm-upper-bound-quantized-projection/1",
        "scale": _QUANTIZATION_SCALE,
        "raw_values": clean,
        "raw_digest": digest_json(clean),
        "integer_values": [int(round(value / _QUANTIZATION_SCALE)) for value in clean],
    }


def _posterior(oracle: dict[str, Any], labels: tuple[str, ...]) -> list[float]:
    candidates: list[object] = []
    latent = oracle.get("latent_distribution")
    outcome = oracle.get("outcome_distribution")
    if type(latent) is dict:
        candidates.append(latent.get("diagnostic_posterior"))
    if type(outcome) is dict:
        candidates.append(outcome.get("diagnostic_posterior"))
    posterior = next((item for item in candidates if type(item) is dict), None)
    if type(posterior) is not dict or set(posterior) != set(labels):
        raise ProtocolViolation("public oracle lacks a closed diagnostic posterior")
    values = [_finite(posterior[label], f"posterior {label}") for label in labels]
    if any(value < 0.0 or value > 1.0 for value in values) or not np.isclose(
        sum(values), 1.0, atol=1e-12, rtol=0.0
    ):
        raise ProtocolViolation("public diagnostic posterior is not normalized")
    return values


def _private_swap(episode: PrivateEpisode) -> PrivateEpisode:
    labels = tuple(episode.diagnostic_target)
    flipped = {
        label: float(episode.diagnostic_target[labels[-index - 1]])
        for index, label in enumerate(labels)
    }
    alternate_split = (
        WorldSplit.SEALED_TEST
        if episode.split is not WorldSplit.SEALED_TEST
        else WorldSplit.TRAIN
    )
    return replace(
        episode,
        case_key=episode.case_key + "-private-swap",
        environment_key="private-swap-must-be-ignored",
        split=alternate_split,
        generator_seed=episode.generator_seed + 999_983,
        hidden_state_at_cut={"private_swap_sentinel": 91.0},
        invariant_parameters={"private_swap_sentinel": -73.0},
        diagnostic_target=flipped,
        factual_future=[{"private_swap_sentinel": -123.0}],
        action_propensities=[{"private_swap_sentinel": 0.999}],
        factual_utility=episode.factual_utility - 10_000.0,
        oracle_anchor={"private_swap_sentinel": "changed"},
    )


def _exact_source_world_factory(
    config: _PublicOracleAdapterConfig, source_raw: bytes
) -> Callable[[], MicroWorld]:
    """Compile the exact anchored world bytes instead of trusting a stale import.

    A normal module import can keep an old code object after the file changes.
    The evaluator instead compiles the already-hashed bytes into an isolated
    package module.  Transitive imported dependencies remain an explicit
    formalization blocker; this function closes the world-module byte/runtime
    edge itself.
    """

    module_name = (
        "prototype.unified_map.worlds._ucm_upper_bound_live_"
        + config.world_slot.lower()
    )
    module = ModuleType(module_name)
    module.__file__ = str((_REPOSITORY_ROOT / config.committed_source).resolve())
    module.__package__ = "prototype.unified_map.worlds"
    module.__builtins__ = __builtins__
    sys.modules[module_name] = module
    try:
        code = compile(source_raw, module.__file__, "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ProtocolViolation(
            f"{config.world_slot} exact anchored world source cannot execute"
        ) from exc
    class_name = config.source_class_name or config.world_factory.__name__
    if type(class_name) is not str or not class_name:
        raise ProtocolViolation("exact source class name must be non-empty")
    factory = getattr(module, class_name, None)
    if not isinstance(factory, type) or not issubclass(factory, MicroWorld):
        raise ProtocolViolation(
            f"{config.world_slot} exact source lacks the configured world class"
        )
    return factory


def _state_binding(
    *,
    config: _PublicOracleAdapterConfig,
    world: MicroWorld,
    episode: PrivateEpisode,
    source_digest: str,
    manifest_digest: str,
    scope_digest: str,
) -> dict[str, Any]:
    representation = {
        "protocol": "ucm-public-oracle-upper-bound-state/1",
        "world_slot": config.world_slot,
        "as_of_available_at": episode.public_history.as_of_available_at,
        "public_history": episode.public_history.to_wire(),
    }
    payload = StatePayload.from_json(
        representation,
        schema_version="ucm-public-oracle-upper-bound-state/1",
        state_class=StateClass.DYNAMIC_SHARED,
    )
    state_hash = compute_state_hash(
        payload,
        candidate_bundle_digest=manifest_digest,
        model_digest=source_digest,
        scope_digest=scope_digest,
        catalog_digest=world.catalog.digest,
        as_of_available_at=episode.public_history.as_of_available_at,
    )
    return {
        "protocol": STATE_BINDING_PROTOCOL,
        "payload": {
            "codec": payload.codec,
            "schema_version": payload.schema_version,
            "state_class": payload.state_class.value,
            "representation": representation,
        },
        "record": {
            "state_id": "ucm-state:" + state_hash[7:23],
            "state_hash": state_hash,
            "parent_state_hash": None,
            "operation": "initialize",
            "delta_digest": None,
            "candidate_bundle_digest": manifest_digest,
            "model_digest": source_digest,
            "scope_digest": scope_digest,
            "catalog_digest": world.catalog.digest,
            "as_of_available_at": episode.public_history.as_of_available_at,
            "payload_size_bytes": len(payload.payload),
        },
    }


def _reference_wire(
    production: dict[str, Any],
    reference: CounterfactualOracle | float,
    *,
    tolerance: float,
) -> tuple[str, dict[str, Any]]:
    if isinstance(reference, CounterfactualOracle):
        reference_oracle = _oracle_wire(reference)
        comparison = _oracle_comparison(production, reference_oracle)
        if comparison["passed"] is not True:
            raise ProtocolViolation("source-distinct full reference oracle disagrees")
        return "full_oracle", {
            "kind": "full_oracle",
            "source_distinct": False,
            "source_separation_certified": False,
            "reference_oracle": reference_oracle,
            "comparison": comparison,
        }
    reference_utility = _finite(reference, "source-distinct reference utility")
    production_utility = _finite(
        production["expected_utility"], "production expected utility"
    )
    absolute_error = abs(production_utility - reference_utility)
    if absolute_error > tolerance:
        raise ProtocolViolation("source-distinct expected-utility reference disagrees")
    return "expected_utility_only", {
        "kind": "expected_utility_only",
        "source_distinct": False,
        "source_separation_certified": False,
        "production_expected_utility": production_utility,
        "reference_expected_utility": reference_utility,
        "absolute_error": absolute_error,
        "absolute_tolerance": tolerance,
        "passed": True,
    }


def _call_reference(
    world: MicroWorld,
    episode: PrivateEpisode,
    policy: Any,
    *,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle | float:
    """Call legacy/current reference APIs without swallowing body errors."""

    method = world.reference_counterfactual
    if "oracle_seed" in inspect.signature(method).parameters:
        return method(episode, policy, horizon, oracle_seed=oracle_seed)
    return method(episode, policy, horizon)


def _head(
    *,
    operation: str,
    state_hash: str,
    manifest_digest: str,
    query: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "protocol": "ucm-public-oracle-upper-bound-head/1",
        "operation": operation,
        "consumed_state_hash": state_hash,
        "manifest_digest": manifest_digest,
        "query": query,
        "query_digest": digest_json(query),
        "result": result,
    }


def _collect_public_oracle_upper_bound(
    config: _PublicOracleAdapterConfig,
    *,
    source_artifact: Path | str,
    generator_seed: int,
    episode_index: int,
    oracle_seed: int,
) -> dict[str, Any]:
    source_raw = _source_bytes(
        source_artifact,
        committed=config.committed_source,
        world_slot=config.world_slot,
    )
    source_digest = digest_bytes(source_raw)
    evaluator_source_closure = _evaluator_source_closure(config)
    exact_factory = _exact_source_world_factory(config, source_raw)
    world = exact_factory()
    swapped_world = exact_factory()
    episode = world.generate_episode(WorldSplit.TRAIN, generator_seed, episode_index)
    swapped = _private_swap(episode)
    if episode.public_history.to_wire() != swapped.public_history.to_wire():
        raise ProtocolViolation("private swap changed candidate-visible public history")
    if episode.diagnostic_target == swapped.diagnostic_target:
        raise ProtocolViolation(
            "private swap did not change the realized diagnosis target"
        )

    policies = world.policy_set(4)
    if not policies or policies[0].kind is not PlanKind.NO_NEW_ACTION:
        raise ProtocolViolation(f"{config.world_slot} lacks a leading no-action policy")
    aliases = tuple(f"policy_{index:02d}" for index in range(len(policies)))
    requested = tuple(item.channel_id for item in world.catalog.observations)
    utility_digest = digest_json(
        {
            "protocol": "ucm-public-oracle-upper-bound-utility/1",
            "world_slot": config.world_slot,
            "catalog_digest": world.catalog.digest,
            "horizon": 4,
        }
    )

    production_by_alias: dict[str, dict[str, Any]] = {}
    reference_by_alias: dict[str, dict[str, Any]] = {}
    query_by_alias: dict[str, dict[str, Any]] = {}
    swapped_roots: dict[str, str] = {}
    reference_kind: str | None = None
    for alias, policy in zip(aliases, policies, strict=True):
        query = RolloutQuery(4, policy, requested, utility_digest).to_wire()
        production = _oracle_wire(world.counterfactual(episode, policy, 4, oracle_seed))
        swapped_production = _oracle_wire(
            swapped_world.counterfactual(swapped, policy, 4, oracle_seed)
        )
        if digest_json(production) != digest_json(swapped_production):
            raise ProtocolViolation(
                f"{config.world_slot} public oracle consumed judge-private episode fields"
            )
        kind, reference = _reference_wire(
            production,
            _call_reference(
                world,
                episode,
                policy,
                horizon=4,
                oracle_seed=oracle_seed,
            ),
            tolerance=config.reference_tolerance,
        )
        if reference_kind is None:
            reference_kind = kind
        elif kind != reference_kind:
            raise ProtocolViolation("reference capability changes across policies")
        query_by_alias[alias] = query
        production_by_alias[alias] = production
        reference_by_alias[alias] = reference
        swapped_roots[alias] = digest_json(swapped_production)
    if reference_kind is None:
        raise ProtocolViolation("public-oracle adapter collected no policies")

    manifest = _manifest(config, world)
    manifest_digest = digest_json(manifest)
    scope = _scope_statement(reference_kind)
    scope_digest = digest_json(
        {
            "protocol": "ucm-local-upper-bound-scope/1",
            "world_slot": config.world_slot,
            "scope_statement": scope,
        }
    )
    state = _state_binding(
        config=config,
        world=world,
        episode=episode,
        source_digest=evaluator_source_closure["closure_root"],
        manifest_digest=manifest_digest,
        scope_digest=scope_digest,
    )
    state_hash = state["record"]["state_hash"]

    no_action = production_by_alias[aliases[0]]
    labels = world.catalog.diagnostic_labels
    posterior_values = _posterior(no_action, labels)
    diagnosis_query = DiagnosisQuery(labels).to_wire()
    diagnosis_projection = _quantized(posterior_values)
    diagnosis_head = _head(
        operation="diagnose",
        state_hash=state_hash,
        manifest_digest=manifest_digest,
        query=diagnosis_query,
        result={
            "label_order": list(labels),
            "public_posterior": {
                label: posterior_values[index] for index, label in enumerate(labels)
            },
            "quantized_projection": diagnosis_projection,
        },
    )

    rollout_heads: dict[str, dict[str, Any]] = {}
    utility_values: list[float] = []
    for alias in aliases:
        production = production_by_alias[alias]
        utility = _finite(production["expected_utility"], "production utility")
        utility_values.append(utility)
        rollout_heads[alias] = _head(
            operation="rollout",
            state_hash=state_hash,
            manifest_digest=manifest_digest,
            query=query_by_alias[alias],
            result={
                "semantic_oracle": production,
                "semantic_oracle_digest": digest_json(production),
                "expected_utility": utility,
            },
        )

    best_utility = max(utility_values)
    best_aliases = [
        alias
        for alias, utility in zip(aliases, utility_values, strict=True)
        if utility == best_utility
    ]
    cells = [
        {
            "cell_id": f"{config.world_slot}.initial.public_diagnosis",
            "world_slot": config.world_slot,
            "cut_alias": "initial",
            "task": "public_posterior_diagnosis",
            "state_hash": state_hash,
            "candidate_head": diagnosis_head,
            "oracle_target": {
                "role": "public_posterior_not_realized_true_class",
                "label_order": list(labels),
                "quantized_projection": diagnosis_projection,
            },
            "metric": {"max_absolute_error": 0.0, "l1_error": 0.0},
        },
        {
            "cell_id": f"{config.world_slot}.initial.natural_forecast",
            "world_slot": config.world_slot,
            "cut_alias": "initial",
            "task": "natural_forecast_public_oracle",
            "state_hash": state_hash,
            "candidate_head": rollout_heads[aliases[0]],
            "production_oracle": no_action,
            "reference_evidence": reference_by_alias[aliases[0]],
            "metric": {
                "semantic_output_digest_match": True,
                "expected_utility_absolute_error": 0.0,
            },
        },
        {
            "cell_id": f"{config.world_slot}.initial.intervention",
            "world_slot": config.world_slot,
            "cut_alias": "initial",
            "task": "intervention_public_oracle",
            "state_hash": state_hash,
            "policy_aliases": list(aliases),
            "candidate_heads": rollout_heads,
            "production_oracles": production_by_alias,
            "reference_evidence": reference_by_alias,
            "utility_projection": _quantized(utility_values),
            "metric": {
                "worst_regret": 0.0,
                "best_policy_aliases": best_aliases,
            },
        },
    ]
    formalization_blockers = [
        "not-a-frozen-expected-cell-corpus",
        "public-world-law-upper-bound-only",
        "mean-and-expected-utility-projections-only",
        "recursive-update-adapter-not-yet-available",
        "source-separation-certification-not-embedded",
        "transitive-runtime-dependency-closure-not-bound",
    ]
    if reference_kind != "full_oracle":
        formalization_blockers.append("reference-output-is-utility-only")
    body = {
        "protocol": PROTOCOL,
        "bundle_kind": "phase2_public_oracle_upper_bound_evaluator",
        "world_slot": config.world_slot,
        "ucm_eligible": False,
        "status_chain": deepcopy(STATUS_CHAIN),
        "freeze_authority": {
            "claimed": False,
            "authorized_frozen": False,
            "issuer": None,
        },
        "scope_statement": scope,
        "scope_digest": scope_digest,
        "source_anchor": {
            "artifact_relpath": config.committed_source.as_posix(),
            "artifact_digest": source_digest,
            "artifact_bytes": len(source_raw),
            "artifact_protocol": "ucm-world-python-source/1",
            "replay_digest": source_digest,
            "byte_identical_replay": True,
        },
        "evaluator_source_closure": evaluator_source_closure,
        "manifest": manifest,
        "manifest_digest": manifest_digest,
        "fixture": {
            "split": WorldSplit.TRAIN.value,
            "generator_seed": generator_seed,
            "episode_index": episode_index,
            "oracle_seed": oracle_seed,
            "public_history_digest": episode.public_history.digest,
        },
        "states": {"initial": state},
        "candidate_visibility_proof": {
            "protocol": "ucm-private-swap-invariance/1",
            "candidate_public_history_digest": episode.public_history.digest,
            "private_inputs_distinct": True,
            "realized_target_changed": True,
            "independent_world_instances": world is not swapped_world,
            "policy_output_roots": {
                alias: digest_json(production_by_alias[alias]) for alias in aliases
            },
            "private_swap_output_roots": swapped_roots,
            "all_policy_outputs_byte_identical": True,
        },
        "cells": cells,
        "cell_set_root": _cell_root(cells),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_PUBLIC_ORACLE_UPPER_BOUND",
            "cell_count": len(cells),
            "state_binding_count": 1,
            "policy_count": len(aliases),
            "reference_kind": reference_kind,
            "private_swap_policy_count": len(aliases),
            "ledger_credit": 0,
            "formalization_blockers": formalization_blockers,
        },
    }
    return _attach_bundle_root(body)


def _verify_quantized(value: object, label: str) -> None:
    row = _closed(
        value,
        {"protocol", "scale", "raw_values", "raw_digest", "integer_values"},
        label,
    )
    if row["protocol"] != "ucm-upper-bound-quantized-projection/1":
        raise ProtocolViolation(f"{label} protocol mismatch")
    if row["scale"] != _QUANTIZATION_SCALE:
        raise ProtocolViolation(f"{label} scale mismatch")
    raw = row["raw_values"]
    integers = row["integer_values"]
    if type(raw) is not list or type(integers) is not list or len(raw) != len(integers):
        raise ProtocolViolation(f"{label} vector shape mismatch")
    clean = [_finite(item, f"{label} raw value") for item in raw]
    if digest_json(clean) != row["raw_digest"]:
        raise ProtocolViolation(f"{label} raw digest mismatch")
    expected = [int(round(item / _QUANTIZATION_SCALE)) for item in clean]
    if integers != expected or any(type(item) is not int for item in integers):
        raise ProtocolViolation(f"{label} integer projection mismatch")


def _verify_head_binding(
    value: object,
    *,
    operation: str,
    state_hash: str,
    manifest_digest: str,
    label: str,
) -> dict[str, Any]:
    head = _closed(
        value,
        {
            "protocol",
            "operation",
            "consumed_state_hash",
            "manifest_digest",
            "query",
            "query_digest",
            "result",
        },
        label,
    )
    if (
        head["protocol"] != "ucm-public-oracle-upper-bound-head/1"
        or head["operation"] != operation
        or head["consumed_state_hash"] != state_hash
        or head["manifest_digest"] != manifest_digest
        or type(head["query"]) is not dict
        or digest_json(head["query"]) != head["query_digest"]
        or type(head["result"]) is not dict
    ):
        raise ProtocolViolation(f"{label} is not bound to the shared state/query")
    return head


def _verify_public_oracle_upper_bound(
    value: object,
    config: _PublicOracleAdapterConfig,
    *,
    source_artifact: Path | str | None,
    replay_runtime: bool,
) -> None:
    del replay_runtime  # Verification is always live; retained for suite API parity.
    keys = {
        "protocol",
        "bundle_kind",
        "world_slot",
        "ucm_eligible",
        "status_chain",
        "freeze_authority",
        "scope_statement",
        "scope_digest",
        "source_anchor",
        "evaluator_source_closure",
        "manifest",
        "manifest_digest",
        "fixture",
        "states",
        "candidate_visibility_proof",
        "cells",
        "cell_set_root",
        "verification_summary",
        "bundle_root",
    }
    report = _closed(value, keys, f"{config.world_slot} upper-bound report")
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "phase2_public_oracle_upper_bound_evaluator"
        or report["world_slot"] != config.world_slot
        or report["ucm_eligible"] is not False
        or report["status_chain"] != STATUS_CHAIN
    ):
        raise ProtocolViolation(f"{config.world_slot} identity or status was rewritten")
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation(f"{config.world_slot} bundle root mismatch")
    freeze = _closed(
        report["freeze_authority"],
        {"claimed", "authorized_frozen", "issuer"},
        "freeze authority",
    )
    if freeze != {"claimed": False, "authorized_frozen": False, "issuer": None}:
        raise ProtocolViolation("upper-bound report falsely claims freeze authority")
    manifest = report["manifest"]
    if digest_json(manifest) != report["manifest_digest"]:
        raise ProtocolViolation("public-oracle manifest digest mismatch")
    if (
        type(manifest) is not dict
        or manifest.get("world_slot") != config.world_slot
        or manifest.get("ucm_eligible") is not False
        or manifest.get("freeze_grade") is not False
        or manifest.get("eligibility") != "upper_bound_only"
    ):
        raise ProtocolViolation("public-oracle manifest eligibility mismatch")
    scope = report["scope_statement"]
    reference_kind = report["verification_summary"].get("reference_kind")
    if scope != _scope_statement(reference_kind):
        raise ProtocolViolation("public-oracle scope statement mismatch")
    if report["scope_digest"] != digest_json(
        {
            "protocol": "ucm-local-upper-bound-scope/1",
            "world_slot": config.world_slot,
            "scope_statement": scope,
        }
    ):
        raise ProtocolViolation("local upper-bound scope digest mismatch")

    source = _closed(
        report["source_anchor"],
        {
            "artifact_relpath",
            "artifact_digest",
            "artifact_bytes",
            "artifact_protocol",
            "replay_digest",
            "byte_identical_replay",
        },
        "source anchor",
    )
    if source["artifact_relpath"] != config.committed_source.as_posix():
        raise ProtocolViolation(
            "source anchor does not name the canonical world module"
        )
    _digest(source["artifact_digest"], "source artifact digest")
    bound_source = source_artifact or config.committed_source
    committed_raw = _source_bytes(
        bound_source,
        committed=config.committed_source,
        world_slot=config.world_slot,
    )
    if (
        source["artifact_digest"] != digest_bytes(committed_raw)
        or source["replay_digest"] != source["artifact_digest"]
        or source["artifact_bytes"] != len(committed_raw)
        or source["artifact_protocol"] != "ucm-world-python-source/1"
        or source["byte_identical_replay"] is not True
    ):
        raise ProtocolViolation("source anchor bytes or role mismatch")
    live_source_closure = _evaluator_source_closure(config)
    if report["evaluator_source_closure"] != live_source_closure:
        raise ProtocolViolation("evaluator source dependency closure mismatch")

    states = _closed(report["states"], {"initial"}, "states")
    state = _verify_state_binding(states["initial"], "initial public-oracle state")
    if state["record"]["model_digest"] != live_source_closure["closure_root"]:
        raise ProtocolViolation("shared state is not bound to evaluator source closure")
    representation = state["payload"]["representation"]
    if (
        type(representation) is not dict
        or set(representation)
        != {"protocol", "world_slot", "as_of_available_at", "public_history"}
        or representation["protocol"] != "ucm-public-oracle-upper-bound-state/1"
        or representation["world_slot"] != config.world_slot
        or representation["as_of_available_at"] != state["record"]["as_of_available_at"]
    ):
        raise ProtocolViolation(
            "candidate state is not the closed public-history state"
        )
    state_bytes = canonical_json_bytes(representation)
    for forbidden in (
        b"hidden_state_at_cut",
        b"invariant_parameters",
        b"diagnostic_target",
        b"factual_future",
        b"action_propensities",
        b"factual_utility",
        b"oracle_anchor",
    ):
        if forbidden in state_bytes:
            raise ProtocolViolation(
                "candidate state contains judge-private episode data"
            )

    cells = report["cells"]
    if (
        type(cells) is not list
        or len(cells) != 3
        or _cell_root(cells) != report["cell_set_root"]
    ):
        raise ProtocolViolation("public-oracle cell set is malformed")
    expected_ids = {
        f"{config.world_slot}.initial.public_diagnosis",
        f"{config.world_slot}.initial.natural_forecast",
        f"{config.world_slot}.initial.intervention",
    }
    if {cell.get("cell_id") for cell in cells if type(cell) is dict} != expected_ids:
        raise ProtocolViolation("public-oracle cell coverage mismatch")
    state_hash = state["record"]["state_hash"]
    for cell in cells:
        if (
            cell.get("world_slot") != config.world_slot
            or cell.get("state_hash") != state_hash
        ):
            raise ProtocolViolation("cell does not consume the shared state")
    by_id = {cell["cell_id"]: cell for cell in cells}
    diagnosis = by_id[f"{config.world_slot}.initial.public_diagnosis"]
    diagnosis_head = _verify_head_binding(
        diagnosis["candidate_head"],
        operation="diagnose",
        state_hash=state_hash,
        manifest_digest=report["manifest_digest"],
        label="diagnosis head",
    )
    _verify_quantized(
        diagnosis_head["result"]["quantized_projection"],
        "candidate diagnosis projection",
    )
    _verify_quantized(
        diagnosis["oracle_target"]["quantized_projection"],
        "oracle diagnosis projection",
    )
    if diagnosis_head["result"]["quantized_projection"] != diagnosis["oracle_target"][
        "quantized_projection"
    ] or diagnosis.get("metric") != {"max_absolute_error": 0.0, "l1_error": 0.0}:
        raise ProtocolViolation("diagnosis projection is not its public oracle target")
    intervention = by_id[f"{config.world_slot}.initial.intervention"]
    _verify_quantized(intervention["utility_projection"], "utility projection")
    if intervention["metric"].get("worst_regret") != 0.0:
        raise ProtocolViolation("public-oracle upper bound reports non-zero regret")
    aliases = intervention.get("policy_aliases")
    candidate_heads = intervention.get("candidate_heads")
    production_oracles = intervention.get("production_oracles")
    references = intervention.get("reference_evidence")
    if (
        type(aliases) is not list
        or not aliases
        or len(aliases) != len(set(aliases))
        or type(candidate_heads) is not dict
        or type(production_oracles) is not dict
        or type(references) is not dict
        or set(candidate_heads) != set(aliases)
        or set(production_oracles) != set(aliases)
        or set(references) != set(aliases)
    ):
        raise ProtocolViolation("intervention policy/head/reference coverage mismatch")
    for alias in aliases:
        rollout_head = _verify_head_binding(
            candidate_heads[alias],
            operation="rollout",
            state_hash=state_hash,
            manifest_digest=report["manifest_digest"],
            label=f"intervention head {alias}",
        )
        semantic_oracle = rollout_head["result"].get("semantic_oracle")
        if (
            type(semantic_oracle) is not dict
            or semantic_oracle != production_oracles[alias]
            or rollout_head["result"].get("semantic_oracle_digest")
            != digest_json(semantic_oracle)
            or rollout_head["result"].get("expected_utility")
            != semantic_oracle.get("expected_utility")
        ):
            raise ProtocolViolation("rollout head is not the exact production oracle")
    natural = by_id[f"{config.world_slot}.initial.natural_forecast"]
    natural_head = _verify_head_binding(
        natural["candidate_head"],
        operation="rollout",
        state_hash=state_hash,
        manifest_digest=report["manifest_digest"],
        label="natural forecast head",
    )
    if (
        natural_head != candidate_heads[aliases[0]]
        or natural.get("production_oracle") != production_oracles[aliases[0]]
        or natural.get("reference_evidence") != references[aliases[0]]
    ):
        raise ProtocolViolation("natural forecast is not the leading no-action policy")
    visibility = report["candidate_visibility_proof"]
    if (
        type(visibility) is not dict
        or visibility.get("protocol") != "ucm-private-swap-invariance/1"
        or visibility.get("private_inputs_distinct") is not True
        or visibility.get("realized_target_changed") is not True
        or visibility.get("independent_world_instances") is not True
        or visibility.get("all_policy_outputs_byte_identical") is not True
        or visibility.get("policy_output_roots")
        != visibility.get("private_swap_output_roots")
    ):
        raise ProtocolViolation("candidate visibility private-swap proof failed")

    fixture = _closed(
        report["fixture"],
        {
            "split",
            "generator_seed",
            "episode_index",
            "oracle_seed",
            "public_history_digest",
        },
        "fixture",
    )
    if (
        fixture["split"] != WorldSplit.TRAIN.value
        or type(fixture["generator_seed"]) is not int
        or type(fixture["episode_index"]) is not int
        or type(fixture["oracle_seed"]) is not int
    ):
        raise ProtocolViolation("fixture identity is invalid")
    _digest(fixture["public_history_digest"], "fixture public history digest")

    expected = _collect_public_oracle_upper_bound(
        config,
        source_artifact=config.committed_source,
        generator_seed=fixture["generator_seed"],
        episode_index=fixture["episode_index"],
        oracle_seed=fixture["oracle_seed"],
    )
    if canonical_json_bytes(report) != canonical_json_bytes(expected):
        raise ProtocolViolation(
            f"{config.world_slot} report is not the exact live reconstruction"
        )


def run_w03_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W03_SOURCE,
    generator_seed: int = _W03_CONFIG.generator_seed,
    episode_index: int = _W03_CONFIG.episode_index,
    oracle_seed: int = _W03_CONFIG.oracle_seed,
) -> dict[str, Any]:
    result = _collect_public_oracle_upper_bound(
        _W03_CONFIG,
        source_artifact=source_artifact,
        generator_seed=generator_seed,
        episode_index=episode_index,
        oracle_seed=oracle_seed,
    )
    verify_w03_upper_bound_sanity(
        result, source_artifact=source_artifact, replay_runtime=True
    )
    return result


def verify_w03_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    _verify_public_oracle_upper_bound(
        value,
        _W03_CONFIG,
        source_artifact=source_artifact,
        replay_runtime=replay_runtime,
    )


def w03_upper_bound_artifact_bytes(**kwargs: Any) -> bytes:
    """Return deterministic canonical bytes without writing a results artifact."""

    return canonical_json_bytes(run_w03_upper_bound_sanity(**kwargs))


__all__ = [
    "DEFAULT_W03_ARTIFACT",
    "DEFAULT_W03_SOURCE",
    "run_w03_upper_bound_sanity",
    "verify_w03_upper_bound_sanity",
    "w03_upper_bound_artifact_bytes",
]


_register_loaded_evaluator_source(_SHARED_EVALUATOR_SOURCE, __file__)
