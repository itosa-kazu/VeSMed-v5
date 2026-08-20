"""Explicit, auditable state migration for Runtime v2."""

from __future__ import annotations

import copy
import itertools
import re
from typing import Any, Mapping

from .engine import RuntimeV2
from .architecture_wire import architecture_state_to_internal, internal_to_architecture_state
from .schema import (
    SharedPatientState,
    digest,
    validate_migration_spec,
    validate_model_spec,
    validate_state_payload,
)
from .ledger import ledger_entries_digest


def _normalize_joint(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(float(row["probability"]) for row in rows)
    if total <= 0.0:
        raise ValueError("migration produced zero joint mass")
    # Preserve already-normalized source masses exactly.  Re-dividing by a
    # harmless 0.9999999999999999 changes canonical bytes and can make an
    # identity/rename migration observably non-identity even though no
    # probability transport occurred.
    if abs(total - 1.0) > 1e-12:
        for row in rows:
            row["probability"] = float(row["probability"]) / total
    return sorted(rows, key=lambda row: row["configuration_id"])


def _independent_expansion(
    base: list[dict[str, Any]],
    new_process_priors: Mapping[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    new_ids = sorted(new_process_priors)
    for hypothesis in base:
        for bits in itertools.product((False, True), repeat=len(new_ids)):
            active = set(hypothesis["active_processes"])
            probability = float(hypothesis["probability"])
            for pid, enabled in zip(new_ids, bits):
                prior = float(new_process_priors[pid])
                probability *= prior if enabled else 1.0 - prior
                if enabled:
                    active.add(pid)
            rows.append(
                {
                    "configuration_id": RuntimeV2._configuration_id(sorted(active), hypothesis["unknown_active"]),
                    "active_processes": sorted(active),
                    "unknown_active": bool(hypothesis["unknown_active"]),
                    "probability": probability,
                }
            )
    return _normalize_joint(rows)


def _remap_factor_messages(
    messages: list[dict[str, Any]],
    process_map: Mapping[str, str],
    dropped_processes: set[str],
    factor_map: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Carry historical evidence provenance across an explicit model migration.

    Factor messages are not replayed during migration: their likelihood has
    already been incorporated into the migrated joint posterior.  They remain
    operationally important, however, because they are the public exact-once
    evidence ledger and the provenance for supporting/opposing factor ids.
    Silently clearing them therefore both loses lineage and allows the same
    source result to be counted again.

    Process identifiers in explanatory message keys are remapped.  Evidence
    about an explicitly dropped process is retained as historical unmodeled
    evidence rather than being erased.
    """

    remapped: list[dict[str, Any]] = []
    for original in messages:
        row = copy.deepcopy(original)
        factor_id = str(row.get("factor_id") or "")
        if not factor_id.startswith("DISPOSITION:"):
            target_factor_id = factor_map.get(factor_id)
            if target_factor_id is None:
                raise ValueError(
                    f"migration would orphan historical factor provenance: {factor_id}"
                )
            row["factor_id"] = target_factor_id
        variables: list[str] = []
        for variable_id in row.get("variable_ids", []):
            variable = str(variable_id)
            if variable in process_map:
                variables.append(process_map[variable])
            elif variable in dropped_processes:
                variables.append("UNMODELED_PROCESS")
            else:
                variables.append(variable)
        row["variable_ids"] = sorted(set(variables))

        likelihoods: dict[str, float] = {}
        for key, value in row.get("log_likelihood_by_hypothesis", {}).items():
            name = str(key)
            if name.startswith("process:"):
                parts = name.split(":", 2)
                if len(parts) == 3 and parts[1] in process_map:
                    name = f"process:{process_map[parts[1]]}:{parts[2]}"
                elif len(parts) == 3 and parts[1] in dropped_processes:
                    name = f"unmodeled:migrated_from:{parts[1]}:{parts[2]}"
            elif name.startswith("topology:") and "->" in name:
                edge = name.split(":", 1)[1]
                source_id, target_id = edge.split("->", 1)
                if source_id in dropped_processes or target_id in dropped_processes:
                    name = f"unmodeled:migrated_topology:{source_id}->{target_id}"
                else:
                    name = (
                        "topology:"
                        f"{process_map.get(source_id, source_id)}->"
                        f"{process_map.get(target_id, target_id)}"
                    )
            likelihoods[name] = float(value)
        row["log_likelihood_by_hypothesis"] = dict(sorted(likelihoods.items()))
        remapped.append(row)
    return remapped


def _factor_semantic_rows(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for observation in spec["observations"]:
        factor_id = str(observation["factor_id"])
        if factor_id in rows:
            raise ValueError(f"factor_id must identify one semantic factor: {factor_id}")
        semantic = copy.deepcopy(dict(observation))
        # A factor registry rename is not a semantic change.  Concept identity,
        # likelihoods, coordinate updates and reliability remain part of the
        # meaning and therefore remain in the digest.
        semantic.pop("factor_id", None)
        rows[factor_id] = semantic
    return rows


def _remap_factor_semantic(
    semantic: Mapping[str, Any], migration: Mapping[str, Any]
) -> dict[str, Any]:
    """Express source factor semantics in target registry identifiers."""

    row = copy.deepcopy(dict(semantic))
    process_map = migration.get("process_map", {})
    coordinate_maps = migration.get("coordinate_maps", {})
    mode_maps = migration.get("mode_maps", {})
    stratum_maps = migration.get("stratum_maps", {})
    for emission in row.get("emissions", []):
        source_pid = str(emission["process_id"])
        emission["process_id"] = str(process_map.get(source_pid, source_pid))
        coordinate_update = emission.get("coordinate_update")
        if isinstance(coordinate_update, Mapping):
            source_cid = coordinate_update.get("coordinate_id")
            if source_cid in coordinate_maps.get(source_pid, {}):
                coordinate_update["coordinate_id"] = coordinate_maps[source_pid][source_cid]
        if emission.get("mode_likelihoods"):
            emission["mode_likelihoods"] = {
                str(mode_maps.get(source_pid, {}).get(source_mid, source_mid)): distribution
                for source_mid, distribution in emission["mode_likelihoods"].items()
            }
        if emission.get("stratum_likelihoods"):
            remapped_likelihoods: dict[str, Any] = {}
            for source_sid, distribution in emission["stratum_likelihoods"].items():
                targets = stratum_maps.get(source_pid, {}).get(source_sid, source_sid)
                if isinstance(targets, Mapping):
                    target_ids = [sid for sid, weight in targets.items() if float(weight) > 0.0]
                else:
                    target_ids = [str(targets)]
                for target_sid in target_ids:
                    remapped_likelihoods[str(target_sid)] = copy.deepcopy(distribution)
            emission["stratum_likelihoods"] = dict(sorted(remapped_likelihoods.items()))
    return row


def _validated_factor_transport(
    migration: Mapping[str, Any],
    source_state: SharedPatientState,
    source_spec: Mapping[str, Any],
    target_runtime: RuntimeV2,
) -> bool:
    transport = migration.get("validated_posterior_transport")
    if not isinstance(transport, Mapping):
        return False
    artifact = str(transport.get("validation_artifact_digest") or "")
    return (
        transport.get("source_state_hash") == source_state.state_hash
        and transport.get("from_factor_graph_digest") == digest(source_spec["observations"])
        and transport.get("to_factor_graph_digest")
        == digest(target_runtime.spec["observations"])
        and bool(_SHA256_RE.fullmatch(artifact))
    )


def _remap_action_semantic(
    action: Mapping[str, Any],
    migration: Mapping[str, Any],
    target_action_id: str,
) -> dict[str, Any]:
    """Express an action definition in target registry identifiers.

    Action instances contain numerical lifecycle state whose meaning depends on
    the action registry (dose unit/reference, washout and effect kernel).  An
    ``action_map`` is therefore only an identifier map; it is not permission to
    reinterpret a stored dose under a different target definition.
    """

    row = copy.deepcopy(dict(action))
    row["action_id"] = str(target_action_id)
    process_map = migration.get("process_map", {})
    coordinate_maps = migration.get("coordinate_maps", {})
    for key in ("effects", "activation_effects"):
        for effect in row.get(key, []):
            source_pid = str(effect["process_id"])
            effect["process_id"] = str(process_map.get(source_pid, source_pid))
            source_cid = effect.get("coordinate_id")
            if source_cid is not None:
                effect["coordinate_id"] = str(
                    coordinate_maps.get(source_pid, {}).get(source_cid, source_cid)
                )
    return row


def _action_transport(
    source_action_id: str,
    target_action_id: str,
    source_action: Mapping[str, Any],
    target_action: Mapping[str, Any],
    migration: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the audited numerical action-state transport or fail closed.

    Runtime v2 presently implements one typed transport: a linear dose-unit
    conversion.  Everything other than the dose unit/reference must remain
    semantically identical after process/coordinate identifier remapping.
    General action or pharmacokinetic reinterpretation would require a richer
    validated state-transition transport and is deliberately not guessed.
    """

    remapped = _remap_action_semantic(source_action, migration, target_action_id)
    if digest(remapped) == digest(target_action):
        return {
            "transport_type": "identity",
            "dose_multiplier": 1.0,
            "cumulative_exposure_multiplier": 1.0,
        }

    declared = migration.get("action_transports", {}).get(source_action_id)
    if not isinstance(declared, Mapping):
        raise ValueError(
            "mapped action semantics changed; an explicit typed action transport "
            f"is required: {source_action_id}->{target_action_id}"
        )
    allowed = {
        "transport_type",
        "target_action_id",
        "source_action_digest",
        "target_action_digest",
        "source_dose_unit",
        "target_dose_unit",
        "dose_multiplier",
        "validation_artifact_digest",
    }
    if set(declared) != allowed:
        raise ValueError(
            f"action transport for {source_action_id} must contain exactly its typed bound fields"
        )
    if declared.get("transport_type") != "linear_dose_unit_conversion":
        raise ValueError(
            f"unsupported action transport type for {source_action_id}: "
            f"{declared.get('transport_type')}"
        )
    if declared.get("target_action_id") != target_action_id:
        raise ValueError(f"action transport target mismatch for {source_action_id}")
    if declared.get("source_action_digest") != digest(source_action):
        raise ValueError(f"action transport source digest mismatch for {source_action_id}")
    if declared.get("target_action_digest") != digest(target_action):
        raise ValueError(f"action transport target digest mismatch for {source_action_id}")
    if not _SHA256_RE.fullmatch(str(declared.get("validation_artifact_digest") or "")):
        raise ValueError(f"action transport validation artifact must be SHA-256 for {source_action_id}")
    source_unit = source_action.get("dose_unit")
    target_unit = target_action.get("dose_unit")
    if declared.get("source_dose_unit") != source_unit or declared.get("target_dose_unit") != target_unit:
        raise ValueError(f"action transport dose-unit binding mismatch for {source_action_id}")
    multiplier = float(declared.get("dose_multiplier"))
    if not (multiplier > 0.0):
        raise ValueError(f"action transport dose multiplier must be positive for {source_action_id}")

    converted = copy.deepcopy(remapped)
    converted["dose_unit"] = target_unit
    converted["dose_reference"] = float(converted["dose_reference"]) * multiplier
    if digest(converted) != digest(target_action):
        raise ValueError(
            "linear dose conversion cannot transport changed lifecycle/washout/effect semantics: "
            f"{source_action_id}->{target_action_id}"
        )
    return {
        "transport_type": "linear_dose_unit_conversion",
        "dose_multiplier": multiplier,
        "cumulative_exposure_multiplier": multiplier,
    }


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _stratum_allocations(
    source_spec: Mapping[str, Any],
    target_runtime: RuntimeV2,
    process_map: Mapping[str, str],
    declared_maps: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, float]]]:
    """Validate explicit one-to-one or one-to-many stratum migration maps.

    A model-id-only migration may omit ``stratum_maps`` when the source and
    target identifiers are exactly identical.  Any split/merge must be
    explicit: silently falling back to target priors would change action
    planning for an otherwise unchanged patient.
    """

    source_processes = {row["process_id"]: row for row in source_spec["processes"]}
    result: dict[str, dict[str, dict[str, float]]] = {}
    for source_pid, target_pid in sorted(process_map.items()):
        source_strata = {
            row["stratum_id"]
            for row in source_processes[source_pid].get("strata", [])
        } or {f"stratum:{source_pid}"}
        target_strata = {
            row["stratum_id"]
            for row in target_runtime.processes[target_pid].get("strata", [])
        } or {f"stratum:{target_pid}"}
        declared = declared_maps.get(source_pid)
        if declared is None:
            if source_strata != target_strata:
                raise ValueError(
                    f"stratum map is required when strata change for {source_pid}"
                )
            declared = {stratum_id: stratum_id for stratum_id in source_strata}
        if set(declared) != source_strata:
            missing = source_strata.difference(declared)
            extra = set(declared).difference(source_strata)
            raise ValueError(
                f"stratum map must account for every stratum of {source_pid}; "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        process_allocations: dict[str, dict[str, float]] = {}
        for source_sid, raw_targets in declared.items():
            if isinstance(raw_targets, str):
                allocation = {raw_targets: 1.0}
            elif isinstance(raw_targets, Mapping):
                allocation = {
                    str(target_sid): float(weight)
                    for target_sid, weight in raw_targets.items()
                }
            else:
                raise ValueError(
                    f"invalid stratum allocation for {source_pid}.{source_sid}"
                )
            if not allocation or not set(allocation).issubset(target_strata):
                raise ValueError(
                    f"stratum map for {source_pid}.{source_sid} references unknown target"
                )
            if any(weight < 0.0 for weight in allocation.values()) or abs(
                sum(allocation.values()) - 1.0
            ) > 1e-12:
                raise ValueError(
                    f"stratum allocation for {source_pid}.{source_sid} must be non-negative and sum to one"
                )
            process_allocations[str(source_sid)] = dict(sorted(allocation.items()))
        result[source_pid] = process_allocations
    return result


def _remap_mode_transitions(
    transitions: list[dict[str, Any]],
    source_spec: Mapping[str, Any],
    process_map: Mapping[str, str],
    mode_maps: Mapping[str, Any],
    stratum_allocations: Mapping[str, Mapping[str, Mapping[str, float]]],
    history_stratum_maps: Mapping[str, Any],
    factor_map: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Remap history identifiers or fail when a split is historically ambiguous."""

    owners: dict[str, str] = {}
    for process in source_spec["processes"]:
        pid = process["process_id"]
        source_strata = process.get("strata", []) or [
            {"stratum_id": f"stratum:{pid}"}
        ]
        for row in source_strata:
            sid = str(row["stratum_id"])
            if sid in owners:
                raise ValueError(
                    f"mode transition stratum ids must be globally unique: {sid}"
                )
            owners[sid] = pid

    remapped: list[dict[str, Any]] = []
    for original in transitions:
        row = copy.deepcopy(original)
        source_sid = str(row["stratum_id"])
        source_pid = owners.get(source_sid)
        if source_pid is None or source_pid not in process_map:
            raise ValueError(
                f"mode transition references dropped or unknown stratum: {source_sid}"
            )
        allocation = stratum_allocations[source_pid][source_sid]
        explicit_history_sid = history_stratum_maps.get(source_pid, {}).get(source_sid)
        if explicit_history_sid is not None:
            target_sid = str(explicit_history_sid)
            if target_sid not in allocation:
                raise ValueError(
                    f"history stratum map is inconsistent with allocation: {source_sid}->{target_sid}"
                )
        else:
            nonzero = [sid for sid, weight in allocation.items() if weight > 0.0]
            if len(nonzero) != 1:
                raise ValueError(
                    f"historical mode transition cannot be silently allocated across split strata: {source_sid}"
                )
            target_sid = nonzero[0]
        row["stratum_id"] = target_sid
        mode_map = mode_maps[source_pid]
        for key in ("from_mode_id", "to_mode_id"):
            source_mid = str(row[key])
            target_mid = mode_map.get(source_mid)
            if target_mid is None:
                raise ValueError(
                    f"mode transition references unmapped mode: {source_pid}.{source_mid}"
                )
            row[key] = str(target_mid)
        row["guard_ids"] = [
            (
                f"emission:{factor_map.get(guard_id.split(':', 1)[1], guard_id.split(':', 1)[1])}"
                if str(guard_id).startswith("emission:")
                else str(guard_id)
            )
            for guard_id in row.get("guard_ids", [])
        ]
        remapped.append(row)
    return remapped


def migrate_v2_state(
    source_state: SharedPatientState,
    source_model_spec: Mapping[str, Any] | RuntimeV2,
    target_runtime: RuntimeV2,
    migration: Mapping[str, Any],
) -> SharedPatientState:
    """Migrate across v2 model digests using explicit identifier maps."""

    if isinstance(source_model_spec, RuntimeV2):
        source_runtime = source_model_spec
        source_runtime._assert_runtime_spec_integrity()
        source_spec = copy.deepcopy(source_runtime.spec)
    else:
        source_spec = validate_model_spec(source_model_spec)
        options = source_spec.get("runtime_options", {})
        source_runtime = RuntimeV2(
            source_spec,
            topology_enabled=bool(options.get("topology_enabled", True)),
            mode_guards_enabled=bool(options.get("mode_guards_enabled", True)),
        )
    # A caller-supplied source spec is not authoritative merely because the
    # migration document repeats the digest claimed by the wire.  Validate the
    # complete source wire against the actual source runtime before reading any
    # operational state from it.
    if source_runtime.model_digest != source_state.payload["model_lineage"]["model_digest"]:
        raise ValueError("source_model_spec digest does not match source state lineage")
    source_runtime._assert_state(source_state)
    source_payload = architecture_state_to_internal(source_runtime, source_state)
    validate_state_payload(source_payload, source_spec)
    migration = validate_migration_spec(migration)
    if not migration.get("migration_id"):
        raise ValueError("migration_id is required")
    if migration.get("from_model_digest") != source_state.payload["model_lineage"]["model_digest"]:
        raise ValueError("migration from_model_digest mismatch")
    if migration.get("from_model_digest") != source_runtime.model_digest:
        raise ValueError("migration from_model_digest does not match source_model_spec")
    if migration.get("to_model_digest") != target_runtime.model_digest:
        raise ValueError("migration to_model_digest mismatch")

    source_factor_semantics = _factor_semantic_rows(source_spec)
    target_factor_semantics = _factor_semantic_rows(target_runtime.spec)
    historical_factor_ids = {
        str(message.get("factor_id") or "")
        for message in source_payload.get("architecture_factor_messages", [])
        if not str(message.get("factor_id") or "").startswith("DISPOSITION:")
    }
    declared_factor_map = {
        str(source_id): str(target_id)
        for source_id, target_id in migration.get("factor_map", {}).items()
    }
    factor_map = {
        factor_id: declared_factor_map.get(factor_id, factor_id)
        for factor_id in historical_factor_ids
    }
    semantic_changes: list[tuple[str, str]] = []
    for source_factor_id, target_factor_id in sorted(factor_map.items()):
        if source_factor_id not in source_factor_semantics:
            raise ValueError(
                f"historical factor is absent from source model registry: {source_factor_id}"
            )
        if target_factor_id not in target_factor_semantics:
            raise ValueError(
                f"factor_map references unknown target factor: {source_factor_id}->{target_factor_id}"
            )
        remapped_source_semantic = _remap_factor_semantic(
            source_factor_semantics[source_factor_id], migration
        )
        if digest(remapped_source_semantic) != digest(
            target_factor_semantics[target_factor_id]
        ):
            semantic_changes.append((source_factor_id, target_factor_id))
    if semantic_changes and not _validated_factor_transport(
        migration, source_state, source_spec, target_runtime
    ):
        raise ValueError(
            "historical factor semantics changed; raw evidence replay or an explicit "
            f"validated_posterior_transport is required: {semantic_changes}"
        )

    source_ids = {row["process_id"] for row in source_spec["processes"]}
    target_ids = set(target_runtime.process_ids)
    process_map = {str(k): str(v) for k, v in migration.get("process_map", {}).items()}
    dropped = set(migration.get("drop_processes", []))
    if set(process_map).union(dropped) != source_ids:
        missing = source_ids.difference(set(process_map), dropped)
        extra = set(process_map).union(dropped).difference(source_ids)
        raise ValueError(f"migration must account for every source process; missing={sorted(missing)}, extra={sorted(extra)}")
    if not set(process_map.values()).issubset(target_ids):
        raise ValueError("process_map references unknown target process")
    if len(set(process_map.values())) != len(process_map):
        duplicate_targets = sorted(
            target_pid
            for target_pid in set(process_map.values())
            if list(process_map.values()).count(target_pid) > 1
        )
        if not migration.get("merge_kernels"):
            raise ValueError(
                "many-to-one process migration requires an explicit typed merge kernel; "
                f"targets={duplicate_targets}"
            )
        # The finite v2 runtime has no audited joint/local/history merge kernel
        # yet.  Reject rather than accepting a document whose type name is
        # present but whose aggregation semantics cannot be executed exactly.
        raise ValueError(
            "many-to-one process merge kernels are not implemented by Runtime v2"
        )

    cut = float(source_payload["state_time"])
    target_payload = target_runtime._empty_payload(cut)
    # ``_empty_payload`` intentionally starts no later than model-time zero so
    # ordinary initialization can integrate natural dynamics up to a positive
    # first cut.  Migration is different: the posterior is already evaluated
    # at the source cut and must not be relabelled as time zero.
    target_payload["state_time"] = cut
    aggregate: dict[tuple[tuple[str, ...], bool], float] = {}
    dropped_active_mass = 0.0
    for hypothesis in source_payload["joint_hypotheses"]:
        mapped_active = {process_map[pid] for pid in hypothesis["active_processes"] if pid in process_map}
        had_dropped_active = any(pid in dropped for pid in hypothesis["active_processes"])
        unknown = bool(hypothesis["unknown_active"] or had_dropped_active)
        if had_dropped_active:
            dropped_active_mass += float(hypothesis["probability"])
        key = (tuple(sorted(mapped_active)), unknown)
        aggregate[key] = aggregate.get(key, 0.0) + float(hypothesis["probability"])
    base = [
        {
            "configuration_id": RuntimeV2._configuration_id(active, unknown),
            "active_processes": list(active),
            "unknown_active": unknown,
            "probability": probability,
        }
        for (active, unknown), probability in aggregate.items()
    ]
    new_targets = target_ids.difference(process_map.values())
    priors = {pid: float(target_runtime.processes[pid]["activation_prior"]) for pid in new_targets}
    target_payload["joint_hypotheses"] = _independent_expansion(_normalize_joint(base), priors)

    coordinate_maps = migration.get("coordinate_maps", {})
    mode_maps = migration.get("mode_maps", {})
    stratum_allocations = _stratum_allocations(
        source_spec,
        target_runtime,
        process_map,
        migration.get("stratum_maps", {}),
    )
    warnings: list[str] = []
    for source_pid, target_pid in sorted(process_map.items()):
        source_local = source_payload["per_process"][source_pid]
        target_local = target_payload["per_process"][target_pid]
        coord_map = coordinate_maps.get(source_pid, {})
        source_coordinate_ids = set(source_local["coordinates"])
        if set(coord_map) != source_coordinate_ids:
            missing = source_coordinate_ids.difference(coord_map)
            extra = set(coord_map).difference(source_coordinate_ids)
            raise ValueError(
                f"coordinate map must account for every coordinate of mapped process {source_pid}; "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        if len(set(coord_map.values())) != len(coord_map):
            raise ValueError(f"coordinate map for {source_pid} must be one-to-one")
        for source_cid, target_cid in coord_map.items():
            if source_cid not in source_local["coordinates"] or target_cid not in target_local["coordinates"]:
                raise ValueError(f"invalid coordinate mapping {source_pid}.{source_cid}->{target_pid}.{target_cid}")
            target_local["coordinates"][target_cid] = copy.deepcopy(source_local["coordinates"][source_cid])
        mode_map = mode_maps.get(source_pid, {})
        source_mode_ids = set(source_local["mode_posterior"])
        if set(mode_map) != source_mode_ids:
            missing = source_mode_ids.difference(mode_map)
            extra = set(mode_map).difference(source_mode_ids)
            raise ValueError(
                f"mode map must account for every mode of mapped process {source_pid}; "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        mapped_modes = {mid: 0.0 for mid in target_local["mode_posterior"]}
        for source_mid, probability in source_local["mode_posterior"].items():
            target_mid = mode_map.get(source_mid)
            if target_mid not in mapped_modes:
                raise ValueError(f"invalid mode mapping {source_pid}.{source_mid}->{target_pid}.{target_mid}")
            mapped_modes[target_mid] += float(probability)
        total = sum(mapped_modes.values())
        if total:
            target_local["mode_posterior"] = {
                key: (value / total if abs(total - 1.0) > 1e-12 else value)
                for key, value in sorted(mapped_modes.items())
            }
        mapped_strata = {
            row["stratum_id"]: 0.0
            for row in target_runtime.processes[target_pid].get("strata", [])
        } or {f"stratum:{target_pid}": 0.0}
        for source_sid, probability in source_local["stratum_posterior"].items():
            for target_sid, allocation in stratum_allocations[source_pid][source_sid].items():
                mapped_strata[target_sid] += float(probability) * float(allocation)
        stratum_total = sum(mapped_strata.values())
        if stratum_total <= 0.0:
            raise ValueError(f"stratum migration produced zero mass for {source_pid}")
        target_local["stratum_posterior"] = {
            key: (
                value / stratum_total
                if abs(stratum_total - 1.0) > 1e-12
                else value
            )
            for key, value in sorted(mapped_strata.items())
        }

    action_map = {str(k): str(v) for k, v in migration.get("action_map", {}).items()}
    action_transports: dict[str, dict[str, Any]] = {}
    for source_action_id, target_action_id in sorted(action_map.items()):
        if source_action_id not in source_runtime.actions:
            raise ValueError(f"action_map references unknown source action: {source_action_id}")
        if target_action_id not in target_runtime.actions:
            raise ValueError(f"action_map references unknown target action: {target_action_id}")
        action_transports[source_action_id] = _action_transport(
            source_action_id,
            target_action_id,
            source_runtime.actions[source_action_id],
            target_runtime.actions[target_action_id],
            migration,
        )
    for exposure_id, instance in source_payload.get("action_instances", {}).items():
        source_action = instance["action_id"]
        target_action = action_map.get(source_action)
        if target_action is None:
            raise ValueError(
                f"migration would drop operative action instance without an action mapping: "
                f"{exposure_id}:{source_action}"
            )
        if target_action not in target_runtime.actions:
            raise ValueError(f"action_map references unknown target action: {target_action}")
        migrated_instance = copy.deepcopy(instance)
        migrated_instance["action_id"] = target_action
        transport = action_transports[source_action]
        dose_multiplier = float(transport["dose_multiplier"])
        migrated_instance["current_dose"] = (
            float(migrated_instance.get("current_dose", 0.0)) * dose_multiplier
        )
        migrated_instance["cumulative_exposure"] = (
            float(migrated_instance.get("cumulative_exposure", 0.0))
            * float(transport["cumulative_exposure_multiplier"])
        )
        migrated_instance["dose_unit"] = target_runtime.actions[target_action].get(
            "dose_unit"
        )
        for dose_row in migrated_instance.get("dose_history", []):
            if dose_row.get("value") is not None:
                dose_row["value"] = float(dose_row["value"]) * dose_multiplier
            dose_row["unit"] = migrated_instance["dose_unit"] or "normalized"
        for summary in migrated_instance.get("response_summaries", []):
            target_id = str(summary.get("target_id") or "")
            source_pid, separator, source_cid = target_id.partition(".")
            if not separator or source_pid not in process_map:
                raise ValueError(
                    f"action response summary has unmappable target: {target_id}"
                )
            target_pid = process_map[source_pid]
            target_cid = coordinate_maps[source_pid].get(source_cid)
            if target_cid is None:
                raise ValueError(
                    f"action response summary has unmapped coordinate: {target_id}"
                )
            summary["target_id"] = f"{target_pid}.{target_cid}"
        target_payload["action_instances"][exposure_id] = migrated_instance

    for key in (
        "history_summary",
        "event_ledger",
        "evidence_trace",
        "action_response_windows",
        "architecture_unexplained_observations",
        "missing_distinguishing_information",
    ):
        target_payload[key] = copy.deepcopy(source_payload.get(key, target_payload.get(key)))
    target_payload["mode_transitions"] = _remap_mode_transitions(
        copy.deepcopy(source_payload.get("mode_transitions", [])),
        source_spec,
        process_map,
        mode_maps,
        stratum_allocations,
        migration.get("history_stratum_maps", {}),
        factor_map,
    )
    target_stratum_owner: dict[str, str] = {}
    for target_pid in target_runtime.process_ids:
        target_strata = target_runtime.processes[target_pid].get("strata", []) or [
            {"stratum_id": f"stratum:{target_pid}"}
        ]
        for stratum in target_strata:
            target_stratum_owner[str(stratum["stratum_id"])] = target_pid
        target_payload["per_process"][target_pid]["last_transition_cursor"] = None
    for transition in target_payload["mode_transitions"]:
        target_pid = target_stratum_owner[str(transition["stratum_id"])]
        cursor = int(transition["event_cursor"])
        previous = target_payload["per_process"][target_pid].get(
            "last_transition_cursor"
        )
        if previous is None or cursor > int(previous):
            target_payload["per_process"][target_pid]["last_transition_cursor"] = cursor
    target_payload["planned_action_records"] = []
    for planned in source_payload.get("planned_action_records", []):
        source_action = str(planned["action_id"])
        target_action = action_map.get(source_action)
        if target_action is None:
            raise ValueError(
                f"migration would drop planned action without an action mapping: {source_action}"
            )
        migrated_planned = copy.deepcopy(planned)
        migrated_planned["action_id"] = target_action
        target_payload["planned_action_records"].append(migrated_planned)
    target_payload["action_source_ledger"] = copy.deepcopy(
        source_payload.get("action_source_ledger", {})
    )
    for source_id, action_source in target_payload["action_source_ledger"].items():
        if not isinstance(action_source, Mapping):
            continue
        source_action = action_source.get("action_id")
        if source_action is None:
            continue
        target_action = action_map.get(str(source_action))
        if target_action is None:
            raise ValueError(
                f"migration would drop action source lineage without an action mapping: "
                f"{source_id}:{source_action}"
            )
        action_source["action_id"] = target_action
    if any(value is None for value in target_payload["event_ledger"].values()):
        raise ValueError("v2 migration of a cold state requires an event ledger proof")
    target_payload["event_ledger_digest"] = ledger_entries_digest(target_payload["event_ledger"])
    # Preserve exact-once source identity and historical factor provenance.  A
    # migrated posterior must not accept an alternate rendering of evidence
    # already incorporated before migration as a fresh independent factor.
    target_payload["architecture_factor_messages"] = _remap_factor_messages(
        copy.deepcopy(source_payload.get("architecture_factor_messages", [])),
        process_map,
        dropped,
        factor_map,
    )
    target_payload["evidence_ledger"] = {
        f"source:{source_id}": copy.deepcopy(
            source_payload.get("evidence_ledger", {}).get(f"source:{source_id}")
        )
        for message in target_payload["architecture_factor_messages"]
        if not str(message.get("factor_id", "")).startswith("DISPOSITION:")
        for source_id in message.get("source_result_ids", [])
    }
    target_payload["epistemic"] = copy.deepcopy(source_payload["epistemic"])
    if dropped_active_mass:
        warnings.append(f"dropped_active_process_mass_absorbed_by_unknown:{dropped_active_mass:.12g}")
    record = {
        "migration_id": migration["migration_id"],
        "kind": "v2_model_migration",
        "source_state_hash": source_state.state_hash,
        "from_model_digest": source_state.payload["model_lineage"]["model_digest"],
        "to_model_digest": target_runtime.model_digest,
        "migration_spec_digest": digest(migration),
        "warnings": sorted(set(warnings)),
    }
    if migration.get("validated_posterior_transport") is not None:
        record["validated_posterior_transport_digest"] = digest(
            migration["validated_posterior_transport"]
        )
    if migration.get("refinement_lineage") is not None:
        record["refinement_lineage"] = copy.deepcopy(migration["refinement_lineage"])
    target_payload["lineage"] = {
        "parent_state_hash": source_state.state_hash,
        "consumed_event_ids": [],
        "skipped_duplicate_event_ids": [],
        "migration_history": [
            *copy.deepcopy(source_payload.get("lineage", {}).get("migration_history", [])),
            record,
        ],
    }
    target_payload["warnings"] = sorted(set(target_payload.get("warnings", []) + warnings))
    target_runtime._derive_marginals(target_payload)
    target_runtime._derive_epistemic(target_payload)
    validate_state_payload(target_payload, target_runtime.spec)
    migrated_state = internal_to_architecture_state(target_runtime, target_payload)
    # Migration is a public state producer and must itself guarantee canonical
    # closure; callers should never receive a wire which only fails later when
    # diagnose/forecast first consumes it.
    target_runtime._assert_state(migrated_state)
    return migrated_state


def import_legacy_v1_state(
    legacy_payload: Mapping[str, Any],
    target_runtime: RuntimeV2,
    migration: Mapping[str, Any],
) -> SharedPatientState:
    """Import the v1 exclusive-simplex state with an explicit lossy warning."""

    legacy = copy.deepcopy(dict(legacy_payload))
    if not migration.get("migration_id"):
        raise ValueError("migration_id is required")
    branch_map = {str(k): str(v) for k, v in migration.get("process_map", {}).items()}
    source_branches = set(legacy.get("branch_posterior", {}))
    dropped = set(migration.get("drop_processes", []))
    if set(branch_map).union(dropped) != source_branches:
        missing = source_branches.difference(set(branch_map), dropped)
        raise ValueError(f"legacy migration must account for every branch: {sorted(missing)}")
    if not set(branch_map.values()).issubset(target_runtime.process_ids):
        raise ValueError("legacy process_map references unknown target")

    cut = float(legacy.get("available_cut", 0.0))
    payload = target_runtime._empty_payload(cut)
    payload["state_time"] = cut
    target_marginals = {
        pid: float(target_runtime.processes[pid]["activation_prior"]) for pid in target_runtime.process_ids
    }
    for source_pid, target_pid in branch_map.items():
        target_marginals[target_pid] = float(legacy["branch_posterior"][source_pid])
    unknown = float(legacy.get("unknown_mass", target_runtime.spec["epistemic"]["unknown_prior"]))
    dropped_mass = sum(float(legacy["branch_posterior"][pid]) for pid in dropped)
    unknown = min(1.0 - 1e-9, unknown + dropped_mass)

    rows: list[dict[str, Any]] = []
    pids = sorted(target_marginals)
    for bits in itertools.product((False, True), repeat=len(pids)):
        for unknown_active in (False, True):
            probability = unknown if unknown_active else 1.0 - unknown
            active: list[str] = []
            for pid, enabled in zip(pids, bits):
                marginal = min(1.0 - 1e-9, max(1e-9, target_marginals[pid]))
                probability *= marginal if enabled else 1.0 - marginal
                if enabled:
                    active.append(pid)
            rows.append(
                {
                    "configuration_id": RuntimeV2._configuration_id(active, unknown_active),
                    "active_processes": active,
                    "unknown_active": unknown_active,
                    "probability": probability,
                }
            )
    payload["joint_hypotheses"] = _normalize_joint(rows)

    coordinate_maps = migration.get("coordinate_maps", {})
    mode_maps = migration.get("mode_maps", {})
    warnings = ["legacy_simplex_to_factorial_independence_approximation"]
    for source_pid, target_pid in branch_map.items():
        source_local = legacy.get("per_branch", {}).get(source_pid, {})
        target_local = payload["per_process"][target_pid]
        for source_cid, target_cid in coordinate_maps.get(source_pid, {}).items():
            if source_cid in source_local.get("local_coordinates", {}) and target_cid in target_local["coordinates"]:
                target_local["coordinates"][target_cid]["mean"] = float(
                    source_local["local_coordinates"][source_cid]
                )
        mapped_modes = {mid: 0.0 for mid in target_local["mode_posterior"]}
        source_modes = source_local.get("mode_posterior", legacy.get("mode_posterior", {}))
        for source_mid, probability in source_modes.items():
            target_mid = mode_maps.get(source_pid, {}).get(source_mid)
            if target_mid in mapped_modes:
                mapped_modes[target_mid] += float(probability)
        total = sum(mapped_modes.values())
        if total:
            target_local["mode_posterior"] = {mid: value / total for mid, value in sorted(mapped_modes.items())}

    action_map = {str(k): str(v) for k, v in migration.get("action_map", {}).items()}
    for source_action, instance in legacy.get("action_exposure", {}).items():
        target_action = action_map.get(source_action)
        if target_action not in target_runtime.actions:
            warnings.append(f"dropped_legacy_action:{source_action}")
            continue
        exposure_id = f"legacy:{source_action}"
        active = bool(instance.get("active", False))
        payload["action_instances"][exposure_id] = {
            "action_id": target_action,
            "status": "active" if active else "stopped",
            "started_at": float(instance.get("last_available_at", cut)),
            "last_accounted_at": cut,
            "current_dose": float(instance.get("level", target_runtime.actions[target_action]["dose_reference"])),
            "dose_unit": None,
            "cumulative_exposure": 0.0,
            "stopped_at": None if active else cut,
            "washout_remaining": 0.0,
            "lifecycle_event_ids": [],
        }

    payload["history_summary"] = copy.deepcopy(legacy.get("history_summary", {}))
    mapped_count = int(legacy.get("recognized_observation_count", 0))
    unmapped_count = int(legacy.get("unrecognized_observation_count", 0))
    payload["epistemic"]["mapped_observation_count"] = mapped_count
    payload["epistemic"]["unmapped_observation_count"] = unmapped_count
    payload["epistemic"]["misfit_sum"] = 0.0
    # The architecture wire derives mapping coverage from factor/result
    # provenance.  Represent legacy aggregate counts explicitly; otherwise a
    # warm import looks valid but a cold query reconstructs zero measurements
    # and rejects its own epistemic residual.
    payload["architecture_factor_messages"] = []
    for index in range(mapped_count):
        event_id = f"legacy-mapped-event-{index}"
        source_id = f"legacy-mapped-result-{index}"
        concept_id = f"legacy-mapped-concept-{index}"
        event_digest = digest({"legacy_event": index})
        payload["event_ledger"][event_id] = event_digest
        payload["architecture_factor_messages"].append(
            {
                "factor_id": f"LEGACY:MAPPED:{index}",
                "factor_type": "measurement",
                "variable_ids": ["UNMODELED_PROCESS"],
                "source_result_ids": [source_id],
                "log_likelihood_by_hypothesis": {
                    f"provenance:event:{event_id}:{event_digest}": 0.0,
                    f"provenance:member:{concept_id}:{digest({'legacy_member': index})}": 0.0,
                    f"provenance:inference_member:{digest({'legacy_inference_member': index})}": 0.0,
                },
                "reliability": 1.0,
            }
        )
    payload["event_ledger_digest"] = ledger_entries_digest(payload["event_ledger"])
    payload["architecture_unexplained_observations"] = [
        {
            "result_id": f"legacy-unmapped-result-{index}",
            "reason": "unmapped",
            "surprisal": None,
            "candidate_process_ids": [],
        }
        for index in range(unmapped_count)
    ]
    payload["missing_distinguishing_information"] = [
        {
            "information_id": "legacy-migration-information-loss",
            "target_query_id": "legacy.simplex_to_factorial_state",
            "expected_discrimination": 1.0,
            "availability": "not_available",
            "risk_class": "unknown",
        }
    ]
    raw_parent_digest = legacy.get("model_digest")
    if isinstance(raw_parent_digest, str) and _SHA256_RE.fullmatch(raw_parent_digest):
        parent_model_digest = raw_parent_digest
    else:
        parent_model_digest = digest(
            {"legacy_model_identity_claim": raw_parent_digest}
        )
        warnings.append("legacy_parent_model_digest_normalized_to_sha256")
    record = {
        "migration_id": migration["migration_id"],
        "kind": "legacy_v1_simplex_import",
        "source_state_hash": digest(legacy),
        "from_model_digest": parent_model_digest,
        "to_model_digest": target_runtime.model_digest,
        "migration_spec_digest": digest(migration),
        "warnings": sorted(set(warnings)),
    }
    payload["lineage"] = {
        "parent_state_hash": digest(legacy),
        "consumed_event_ids": [],
        "skipped_duplicate_event_ids": [],
        "migration_history": [record],
    }
    payload["warnings"] = sorted(set(warnings))
    target_runtime._derive_marginals(payload)
    target_runtime._derive_epistemic(payload)
    validate_state_payload(payload, target_runtime.spec)
    migrated = internal_to_architecture_state(target_runtime, payload)
    target_runtime._assert_state(migrated)
    return migrated


__all__ = ["import_legacy_v1_state", "migrate_v2_state"]
