"""Replay-bound PRE-FREEZE upper-bound adapter for W16.

W16 is a two-stage scope-extension world.  The benchmark contract requires a
primary S0 state to be sealed before Q2 is revealed.  This adapter proves only
the narrower behaviour semantics: a genuine S0 state plus a revealed Q2 delta
locally refines into two posterior states.  Seal-before-reveal chronology is
tested elsewhere and is explicitly not claimed here.  The adapter does not
treat the revealed-pack digest (or the legacy
``ucm-extension-scope/1`` hash used by the extension runner) as authority for
the formal eleven-axis UCM scope S'.

The report is privileged, ``upper_bound_only``, PRE-FREEZE, UCM-ineligible and
worth zero ledger credit.  Its verifier binds the exact repository source
bytes, opens a fresh opaque commitment to check the deterministic reported
pack, reconstructs every state-hash preimage, and reruns the live W16
production/reference behaviour.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Callable

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .extensions import (
    COMMIT_PROTOCOL,
    REVEAL_PROTOCOL,
    OpaqueExtensionCustody,
    RevealedExtensionPack,
    _open_custody,
)
from .oracle_certification import (
    NumericTolerance,
    compare_canonical_outputs,
    oracle_output_wire,
)
from .schema import VisibleHistory, event_sort_key
from .state import StateClass, StatePayload, seal_state
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
from .worlds.base import WorldSplit
from .worlds.w16 import W16World, make_w16_extension_custody


PROTOCOL = "ucm-pre-freeze-upper-bound-extension-w16/1"
DEFAULT_W16_ARTIFACT = Path("prototype/unified_map/worlds/w16.py")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL_SOURCE = _REPOSITORY_ROOT / DEFAULT_W16_ARTIFACT
_W16_SOURCE_CLOSURE = (
    "prototype/unified_map/upper_bound_evaluator_w16.py",
    "prototype/unified_map/upper_bound_evaluator.py",
    "prototype/unified_map/worlds/w16.py",
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
_FORMAL_SCOPE_AXES = ("P", "O", "A", "Q", "Pi", "Tau", "Gamma", "Y", "U", "D", "R")
_S_PRIME_BLOCKER = "formal-11-axis-S-prime-scope-manifest-not-materialized"
_SOURCE_PROTOCOL = "ucm-runtime-python-source-exact-bytes/1"
_EXTENSION_SOURCE_PROTOCOL = "ucm-upper-bound-extension-reveal-source/1"
_SCOPE_BOUNDARY_PROTOCOL = "ucm-upper-bound-extension-scope-boundary/1"
_SOURCE_CLOSURE_PROTOCOL = "ucm-upper-bound-live-source-closure/1"
_ORACLE_TOLERANCE = NumericTolerance(absolute=1e-12, relative=1e-12)

_CANDIDATE_DIGEST = digest_json(
    {
        "protocol": "ucm-upper-bound-extension-adapter-identity/1",
        "identity": "privileged-behaviour-probe-not-candidate",
    }
)
_FORMALIZATION_BLOCKERS = [
    "not-a-frozen-expected-cell-corpus",
    "privileged-upper-bound-only",
    _S_PRIME_BLOCKER,
    "revealed-pack-digest-is-not-formal-scope-authority",
    "post-seal-reveal-chronology-not-recertified-by-this-behaviour-adapter",
    "source-runtime-attestation-requires-fresh-process-import",
    "single-pair-live-extension-behaviour-probe",
]


def _manifest(world_slot: str) -> dict[str, Any]:
    return {
        "protocol": "ucm-upper-bound-extension-adapter-manifest/1",
        "world_slot": world_slot,
        "baseline_id": "B01",
        "privileged": True,
        "eligibility": "upper_bound_only",
        "freeze_grade": False,
        "formal_scope_authority": False,
        "ucm_eligible": False,
        "ledger_credit": 0,
    }


def _source_path(value: Path | str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _REPOSITORY_ROOT / path


def _source_anchor(
    source_artifact: Path | str, canonical_source: Path
) -> dict[str, Any]:
    requested = _source_path(source_artifact)
    try:
        canonical = canonical_source.read_bytes()
        supplied = requested.read_bytes()
    except OSError as exc:
        raise ProtocolViolation("extension evaluator source is unavailable") from exc
    if supplied != canonical:
        raise ProtocolViolation(
            "extension evaluator source is not byte-identical to canonical runtime source"
        )
    return {
        "artifact_relpath": Path(source_artifact).as_posix(),
        "artifact_digest": digest_bytes(supplied),
        "artifact_bytes": len(supplied),
        "artifact_protocol": _SOURCE_PROTOCOL,
        "replay_digest": digest_bytes(canonical),
        "byte_identical_replay": True,
    }


def _verify_source_anchor(
    value: object,
    *,
    source_artifact: Path | str,
    canonical_source: Path,
) -> None:
    row = _closed(
        value,
        {
            "artifact_relpath",
            "artifact_digest",
            "artifact_bytes",
            "artifact_protocol",
            "replay_digest",
            "byte_identical_replay",
        },
        "extension source anchor",
    )
    expected = _source_anchor(source_artifact, canonical_source)
    if row != expected:
        raise ProtocolViolation(
            "extension report is not bound to exact canonical source bytes"
        )


def _capture_loaded_source_digests(
    relative_paths: tuple[str, ...],
) -> dict[str, str]:
    captured: dict[str, str] = {}
    for relative in relative_paths:
        try:
            captured[relative] = digest_bytes(
                (_REPOSITORY_ROOT / relative).read_bytes()
            )
        except OSError as exc:
            raise ProtocolViolation(
                f"cannot attest loaded extension source: {relative}"
            ) from exc
    return captured


def _source_closure(
    relative_paths: tuple[str, ...],
    *,
    loaded_source_digests: dict[str, str],
) -> dict[str, Any]:
    if not relative_paths or len(relative_paths) != len(set(relative_paths)):
        raise ProtocolViolation("extension source closure paths must be unique")
    if set(loaded_source_digests) != set(relative_paths):
        raise ProtocolViolation("loaded source attestation coverage mismatch")
    members = []
    for relative in relative_paths:
        path = _REPOSITORY_ROOT / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ProtocolViolation(
                f"extension source-closure member is unavailable: {relative}"
            ) from exc
        live_digest = digest_bytes(raw)
        loaded_digest = loaded_source_digests[relative]
        if live_digest != loaded_digest:
            raise ProtocolViolation(
                f"extension source changed after import: {relative}"
            )
        members.append(
            {
                "relpath": relative,
                "byte_count": len(raw),
                "digest": live_digest,
                "loaded_source_digest": loaded_digest,
                "live_matches_loaded_source": True,
            }
        )
    root = digest_json({"protocol": _SOURCE_CLOSURE_PROTOCOL, "members": members})
    return {
        "protocol": _SOURCE_CLOSURE_PROTOCOL,
        "members": members,
        "closure_root": root,
        "exact_live_bytes": True,
        "import_time_attestation_fail_closed": True,
        "runtime_attestation_scope": "fresh-process-import-plus-post-registration-drift",
        "arbitrary_preloaded_module_staleness_closed": False,
    }


def _verify_source_closure(
    value: object,
    *,
    relative_paths: tuple[str, ...],
    loaded_source_digests: dict[str, str],
) -> None:
    row = _closed(
        value,
        {
            "protocol",
            "members",
            "closure_root",
            "exact_live_bytes",
            "import_time_attestation_fail_closed",
            "runtime_attestation_scope",
            "arbitrary_preloaded_module_staleness_closed",
        },
        "extension source closure",
    )
    expected = _source_closure(
        relative_paths, loaded_source_digests=loaded_source_digests
    )
    if row != expected:
        raise ProtocolViolation(
            "extension source closure differs from exact live dependency bytes"
        )


def _extension_source(
    custody: OpaqueExtensionCustody,
) -> tuple[dict[str, Any], RevealedExtensionPack]:
    reveal = _open_custody(custody)
    return (
        {
            "protocol": _EXTENSION_SOURCE_PROTOCOL,
            "world_slot": reveal.world_id,
            "commitment_protocol": COMMIT_PROTOCOL,
            "reveal_protocol": REVEAL_PROTOCOL,
            "revealed_pack": reveal.pack,
            "revealed_pack_digest": reveal.pack_digest,
            "revealed_pack_bytes_hex": reveal.pack_bytes.hex(),
            "exact_canonical_pack_bytes": True,
            "fresh_opaque_commitment_opened_live": True,
            "randomized_commitment_material_persisted": False,
            "post_seal_reveal_chronology_claimed": False,
            "formal_scope_authority": False,
        },
        reveal,
    )


def _parse_extension_source(
    value: object,
    *,
    world_slot: str,
    expected_pack: Callable[[Any], dict[str, Any]],
    world_factory: Callable[..., Any],
    custody_factory: Callable[[], OpaqueExtensionCustody],
) -> tuple[RevealedExtensionPack, Any]:
    row = _closed(
        value,
        {
            "protocol",
            "world_slot",
            "commitment_protocol",
            "reveal_protocol",
            "revealed_pack",
            "revealed_pack_digest",
            "revealed_pack_bytes_hex",
            "exact_canonical_pack_bytes",
            "fresh_opaque_commitment_opened_live",
            "randomized_commitment_material_persisted",
            "post_seal_reveal_chronology_claimed",
            "formal_scope_authority",
        },
        f"{world_slot} extension source",
    )
    if (
        row["protocol"] != _EXTENSION_SOURCE_PROTOCOL
        or row["world_slot"] != world_slot
        or row["commitment_protocol"] != COMMIT_PROTOCOL
        or row["reveal_protocol"] != REVEAL_PROTOCOL
        or row["exact_canonical_pack_bytes"] is not True
        or row["fresh_opaque_commitment_opened_live"] is not True
        or row["randomized_commitment_material_persisted"] is not False
        or row["post_seal_reveal_chronology_claimed"] is not False
        or row["formal_scope_authority"] is not False
    ):
        raise ProtocolViolation(
            f"{world_slot} extension source authority was overstated"
        )
    try:
        pack_bytes = bytes.fromhex(row["revealed_pack_bytes_hex"])
    except (TypeError, ValueError) as exc:
        raise ProtocolViolation(
            f"{world_slot} revealed pack bytes must be hexadecimal"
        ) from exc
    if (
        row["revealed_pack_bytes_hex"] != pack_bytes.hex()
        or type(row["revealed_pack"]) is not dict
        or canonical_json_bytes(row["revealed_pack"]) != pack_bytes
        or digest_bytes(pack_bytes) != row["revealed_pack_digest"]
    ):
        raise ProtocolViolation(f"{world_slot} revealed pack byte binding mismatch")
    opened = _open_custody(custody_factory())
    if opened.pack != row["revealed_pack"] or opened.pack_bytes != pack_bytes:
        raise ProtocolViolation(
            f"{world_slot} fresh opaque commitment does not open to reported pack"
        )
    primary = world_factory(extension_commitment=opened.commitment)
    world = primary.activate_extension(opened)
    if opened.pack != expected_pack(world):
        raise ProtocolViolation(
            f"{world_slot} revealed pack differs from canonical live contract"
        )
    return opened, world


def _local_scopes(
    *,
    world_slot: str,
    primary_catalog_digest: str,
    extension_catalog_digest: str,
    pack_digest: str,
) -> tuple[str, str]:
    primary = digest_json(
        {
            "protocol": "ucm-upper-bound-primary-state-scope-input/1",
            "world_slot": world_slot,
            "semantic_stage": "S0",
            "catalog_digest": primary_catalog_digest,
        }
    )
    extension = digest_json(
        {
            "protocol": "ucm-upper-bound-revealed-state-scope-input/1",
            "world_slot": world_slot,
            "semantic_stage": "S1",
            "probe_local_primary_scope_digest": primary,
            "revealed_pack_digest": pack_digest,
            "catalog_digest": extension_catalog_digest,
        }
    )
    return primary, extension


def _scope_boundary(
    *,
    world_slot: str,
    primary_scope: str,
    extension_scope: str,
    pack_digest: str,
) -> dict[str, Any]:
    return {
        "protocol": _SCOPE_BOUNDARY_PROTOCOL,
        "world_slot": world_slot,
        "formal_scope_axis_names": list(_FORMAL_SCOPE_AXES),
        "primary": {
            "semantic_scope": "S0",
            "probe_local_state_hash_scope_digest": primary_scope,
            "formal_scope_authority": False,
        },
        "revealed_extension": {
            "semantic_scope": "S-prime",
            "revealed_pack_digest": pack_digest,
            "probe_local_state_hash_scope_digest": extension_scope,
            "formal_scope_manifest_materialized": False,
            "formal_scope_authority": False,
        },
        "legacy_ad_hoc_extension_scope_digest_accepted_as_formal": False,
        "ucm_eligible": False,
        "blockers": [
            _S_PRIME_BLOCKER,
            "revealed-pack-digest-is-not-formal-scope-authority",
        ],
    }


def _scope_statement(world_slot: str) -> dict[str, Any]:
    return {
        "benchmark_status": "PRE-FREEZE",
        "world_slot": world_slot,
        "primary_and_revealed_extension_scopes_distinct": True,
        "post_seal_reveal_chronology_claimed": False,
        "formal_scope_authority": False,
        "formal_S_prime_materialized": False,
        "privileged": True,
        "upper_bound_only": True,
        "ucm_eligible": False,
        "candidate_performance_claimed": False,
        "benchmark_freeze_evidence": False,
        "ledger_credit": 0,
    }


def _expected_w16_pack(world: W16World) -> dict[str, Any]:
    catalog = world.extension_catalog
    return {
        "protocol": "ucm-world-extension-pack/1",
        "catalog": catalog.to_wire(),
        "catalog_digest": catalog.digest,
        "operator": {
            "check_id": "Q2",
            "result_channel": "obs_2",
            "p_result_1_given_C0": 0.05,
            "p_result_1_given_C1": 0.95,
            "delay_ticks": 1,
            "cost": 0.08,
        },
        "frozen_corpus": {"episodes": 512, "branch_pairs": 256},
        "plaintext_guard": "CHECK-EXTENSION-POST-SEAL-ONLY",
    }


def _episode_after_delta(episode: Any, delta: Any, catalog_digest: str) -> Any:
    history = VisibleHistory(
        events=tuple(
            sorted(
                (*episode.public_history.events, *delta.events),
                key=event_sort_key,
            )
        ),
        as_of_available_at=delta.advance_to,
        catalog_digest=catalog_digest,
    )
    return replace(episode, public_history=history)


def _oracle_wire(value: Any) -> dict[str, Any]:
    return oracle_output_wire(value, include_numerical_diagnostics=False)


def _oracle_pair(world: W16World, episode: Any, policy: Any) -> dict[str, Any]:
    production = _oracle_wire(world.counterfactual(episode, policy, 4, oracle_seed=1))
    reference = _oracle_wire(
        world.reference_counterfactual(episode, policy, 4, oracle_seed=2**64 - 1)
    )
    comparison = compare_canonical_outputs(
        production, reference, _ORACLE_TOLERANCE
    ).to_wire()
    if comparison["passed"] is not True:
        raise ProtocolViolation(
            "W16 production/reference extension behaviour disagrees"
        )
    return {"production": production, "reference": reference, "comparison": comparison}


def _seal(
    representation: dict[str, Any],
    *,
    schema_version: str,
    state_class: StateClass,
    scope_digest: str,
    catalog_digest: str,
    model_digest: str,
    as_of: int,
    operation: str,
    parent_state_hash: str | None = None,
    delta_digest: str | None = None,
) -> Any:
    payload = StatePayload.from_json(
        representation,
        schema_version=schema_version,
        state_class=state_class,
    )
    return seal_state(
        payload,
        candidate_bundle_digest=_CANDIDATE_DIGEST,
        model_digest=model_digest,
        scope_digest=scope_digest,
        catalog_digest=catalog_digest,
        as_of_available_at=as_of,
        operation=operation,
        parent_state_hash=parent_state_hash,
        delta_digest=delta_digest,
        state_instance_id="upper-bound-extension-state",
    )


def _w16_refine_from_primary_state(
    primary_representation: dict[str, Any],
    delta: Any,
    revealed_pack: dict[str, Any],
) -> dict[str, Any]:
    """Apply Q2 using only the sealed S0 representation and new delta."""

    primary = _closed(
        primary_representation,
        {"protocol", "semantic_stage", "x_mean", "x_variance"},
        "W16 sealed primary representation",
    )
    if (
        primary["protocol"] != "ucm-upper-bound-primary-linear-state/1"
        or primary["semantic_stage"] != "S0"
    ):
        raise ProtocolViolation("W16 local refinement did not receive an S0 state")
    operator = _closed(
        revealed_pack.get("operator"),
        {
            "check_id",
            "result_channel",
            "p_result_1_given_C0",
            "p_result_1_given_C1",
            "delay_ticks",
            "cost",
        },
        "W16 revealed Q2 operator",
    )
    if operator["check_id"] != "Q2" or operator["result_channel"] != "obs_2":
        raise ProtocolViolation("W16 revealed check identity mismatch")
    result_rows = [
        event
        for event in delta.events
        if event.payload.get("channel_id") == operator["result_channel"]
    ]
    ordered_rows = [
        event
        for event in delta.events
        if event.payload.get("check_id") == operator["check_id"]
    ]
    if len(result_rows) != 1 or len(ordered_rows) != 1:
        raise ProtocolViolation(
            "W16 local refinement requires one Q2 order/result delta"
        )
    result = result_rows[0].payload.get("value")
    if result not in {0, 1}:
        raise ProtocolViolation("W16 local refinement Q2 result must be binary")
    result = int(result)
    likelihood_c0 = (
        operator["p_result_1_given_C0"]
        if result == 1
        else 1.0 - operator["p_result_1_given_C0"]
    )
    likelihood_c1 = (
        operator["p_result_1_given_C1"]
        if result == 1
        else 1.0 - operator["p_result_1_given_C1"]
    )
    posterior_c1 = round(likelihood_c1 / (likelihood_c0 + likelihood_c1), 15)
    return {
        "protocol": "ucm-w16-revealed-check-state/1",
        "semantic_stage": "S1",
        "x_mean": float(primary["x_mean"]),
        "x_variance": float(primary["x_variance"]),
        "class_posterior": {
            "C0": float(1.0 - posterior_c1),
            "C1": float(posterior_c1),
        },
        "revealed_check_result": result,
    }


def _collect_w16_runtime(
    world: W16World, *, pair_seed: int, source_closure_root: str
) -> dict[str, Any]:
    pack_digest = digest_json(_expected_w16_pack(world))
    primary_scope, extension_scope = _local_scopes(
        world_slot="W16",
        primary_catalog_digest=world.catalog.digest,
        extension_catalog_digest=world.extension_catalog.digest,
        pack_digest=pack_digest,
    )
    left_alias = world.generate_episode(WorldSplit.SEALED_TEST, pair_seed, 0)
    right_alias = replace(
        left_alias,
        case_key=digest_json(
            {"pair": "w16-s0-private-alias", "seed": pair_seed, "side": 1}
        ),
        invariant_parameters={"stage": "S0", "class_index": 1},
    )
    if left_alias.public_history.to_wire() != right_alias.public_history.to_wire():
        raise ProtocolViolation(
            "W16 pre-result private aliases do not share public bytes"
        )
    primary_posterior = world.public_history_posterior(left_alias)
    primary_reference = world.reference_public_history_posterior(left_alias)
    if (
        max(
            abs(a - b)
            for a, b in zip(primary_posterior, primary_reference, strict=True)
        )
        > 1e-12
    ):
        raise ProtocolViolation("W16 primary production/reference posterior mismatch")
    primary_representation = {
        "protocol": "ucm-upper-bound-primary-linear-state/1",
        "semantic_stage": "S0",
        "x_mean": float(primary_posterior[0]),
        "x_variance": float(primary_posterior[1]),
    }
    primary_state = _seal(
        primary_representation,
        schema_version="ucm-w16-primary-upper-bound-state/1",
        state_class=StateClass.COMPRESSED_SHARED,
        scope_digest=primary_scope,
        catalog_digest=world.catalog.digest,
        model_digest=source_closure_root,
        as_of=left_alias.public_history.as_of_available_at,
        operation="initialize",
    )
    if (
        left_alias.public_history.catalog_digest != world.catalog.digest
        or primary_state.record.catalog_digest
        != left_alias.public_history.catalog_digest
    ):
        raise ProtocolViolation("W16 S0 history/state catalog binding crossed scope")
    if any(
        marker in primary_state.candidate_input.payload.payload
        for marker in (b"Q2", b"obs_2", b"C0", b"C1")
    ):
        raise ProtocolViolation("W16 primary state leaks revealed check vocabulary")
    primary_policy_rows = []
    for index, policy in enumerate(world.policy_set(4)):
        left = _oracle_wire(world.counterfactual(left_alias, policy, 4, oracle_seed=11))
        right = _oracle_wire(
            world.counterfactual(right_alias, policy, 4, oracle_seed=13)
        )
        if left != right:
            raise ProtocolViolation(
                "W16 S0 private aliases are not behaviourally equivalent"
            )
        if left["outcome_distribution"].get("scope") != "S0":
            raise ProtocolViolation("W16 primary oracle is not in S0 scope")
        primary_policy_rows.append(
            {"policy_index": index, "policy": policy.to_wire(), "shared_oracle": left}
        )

    adaptive_q2_policy = world.extension_policy_set(4)[-1]
    extension_prefix = replace(
        left_alias,
        public_history=VisibleHistory(
            events=left_alias.public_history.events,
            as_of_available_at=left_alias.public_history.as_of_available_at,
            catalog_digest=world.extension_catalog.digest,
        ),
        invariant_parameters={"stage": "S1", "class_index": 0},
    )
    states: dict[str, Any] = {"primary_shared": _state_binding(primary_state)}
    cells: list[dict[str, Any]] = [
        {
            "cell_id": "W16.primary.same_state",
            "world_slot": "W16",
            "cut_alias": "primary-s0-semantics",
            "task": "extension_primary_state_equivalence",
            "state_hash": primary_state.record.state_hash,
            "left_public_history_digest": left_alias.public_history.digest,
            "right_public_history_digest": right_alias.public_history.digest,
            "public_histories_byte_identical": True,
            "private_classes_differ": left_alias.invariant_parameters
            != right_alias.invariant_parameters,
            "primary_policy_behaviour": primary_policy_rows,
            "same_primary_state": True,
        }
    ]
    posterior_values: list[float] = []
    refined_hashes: list[str] = []
    for result in (0, 1):
        delta = world.extension_delta(
            result,
            seed=pair_seed,
            episode_index=0,
            ordered_at=-1,
            available_at=0,
        )
        episode = _episode_after_delta(
            extension_prefix, delta, world.extension_catalog.digest
        )
        posterior = world.public_history_posterior(episode)
        reference = world.reference_public_history_posterior(episode)
        if max(abs(a - b) for a, b in zip(posterior, reference, strict=True)) > 1e-12:
            raise ProtocolViolation(
                "W16 refined production/reference posterior mismatch"
            )
        refined_representation = _w16_refine_from_primary_state(
            deepcopy(primary_representation), delta, _expected_w16_pack(world)
        )
        expected_from_full_replay = {
            "x_mean": float(posterior[0]),
            "x_variance": float(posterior[1]),
            "class_posterior": {
                "C0": float(1.0 - posterior[2]),
                "C1": float(posterior[2]),
            },
        }
        if {
            key: refined_representation[key] for key in expected_from_full_replay
        } != expected_from_full_replay:
            raise ProtocolViolation(
                "W16 state-plus-delta refinement disagrees with full replay reference"
            )
        delta_wire = delta.to_wire()
        refined = _seal(
            refined_representation,
            schema_version="ucm-w16-revealed-check-state/1",
            state_class=StateClass.DYNAMIC_SHARED,
            scope_digest=extension_scope,
            catalog_digest=world.extension_catalog.digest,
            model_digest=source_closure_root,
            as_of=delta.advance_to,
            operation="update",
            parent_state_hash=primary_state.record.state_hash,
            delta_digest=digest_json(delta_wire),
        )
        oracle = _oracle_pair(world, episode, adaptive_q2_policy)
        state_alias = f"refined_q2_result_{result}"
        states[state_alias] = _state_binding(refined)
        posterior_values.append(float(refined_representation["class_posterior"]["C1"]))
        refined_hashes.append(refined.record.state_hash)
        cells.append(
            {
                "cell_id": f"W16.refinement.q2_result_{result}",
                "world_slot": "W16",
                "cut_alias": f"revealed-q2-result-{result}",
                "task": "extension_check_local_refinement",
                "state_hash": refined.record.state_hash,
                "parent_state_hash": primary_state.record.state_hash,
                "delta": delta_wire,
                "delta_digest": digest_json(delta_wire),
                "class_posterior": refined_representation["class_posterior"],
                "policy": adaptive_q2_policy.to_wire(),
                "live_behaviour": oracle,
                "history_replay_used_for_state_update": False,
                "full_history_replay_used_as_reference_only": True,
                "local_update_matches_full_replay_reference": True,
            }
        )
    if posterior_values != [0.05, 0.95] or len(set(refined_hashes)) != 2:
        raise ProtocolViolation("W16 revealed Q2 result did not split the sealed state")
    return {
        "fixture": {
            "split": WorldSplit.SEALED_TEST.value,
            "pair_seed": pair_seed,
            "primary_public_history_digest": left_alias.public_history.digest,
        },
        "scope_boundary": _scope_boundary(
            world_slot="W16",
            primary_scope=primary_scope,
            extension_scope=extension_scope,
            pack_digest=pack_digest,
        ),
        "states": states,
        "cells": cells,
        "verification_facts": {
            "same_primary_state": True,
            "revealed_check_tokens_absent_from_primary_payload": True,
            "local_refinement_parent_preserved": True,
            "refined_state_count": 2,
            "q2_result_posteriors": posterior_values,
            "live_production_reference_replay": True,
            "post_seal_reveal_chronology_claimed": False,
        },
    }


def run_w16_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W16_ARTIFACT,
    pair_seed: int = 1601,
) -> dict[str, Any]:
    """Collect one cryptographically revealed, live-replayed W16 behaviour probe."""

    custody = make_w16_extension_custody()
    extension_source, reveal = _extension_source(custody)
    primary = W16World(extension_commitment=reveal.commitment)
    world = primary.activate_extension(reveal)
    if reveal.pack != _expected_w16_pack(world):
        raise ProtocolViolation("fresh W16 custody did not reveal canonical pack")
    source_closure = _source_closure(
        _W16_SOURCE_CLOSURE,
        loaded_source_digests=_W16_LOADED_SOURCE_DIGESTS,
    )
    runtime = _collect_w16_runtime(
        world,
        pair_seed=pair_seed,
        source_closure_root=source_closure["closure_root"],
    )
    manifest = _manifest("W16")
    body = {
        "protocol": PROTOCOL,
        "bundle_kind": "pre_freeze_privileged_extension_behaviour_probe",
        "world_slot": "W16",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": _scope_statement("W16"),
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
            "status": "VALID_PRE_FREEZE_W16_EXTENSION_BEHAVIOUR_PROBE",
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
    verify_w16_upper_bound_sanity(report, source_artifact=source_artifact)
    return report


def verify_w16_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = True,
) -> None:
    """Verify exact W16 source, reveal, scope boundary, states and behaviour."""

    del replay_runtime  # Live reconstruction is mandatory, never optional.
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
        "W16 upper-bound extension report",
    )
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "pre_freeze_privileged_extension_behaviour_probe"
        or report["world_slot"] != "W16"
        or report["status_chain"] != STATUS_CHAIN
        or report["scope_statement"] != _scope_statement("W16")
    ):
        raise ProtocolViolation("W16 PRE-FREEZE identity or eligibility mismatch")
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("W16 bundle root mismatch")
    expected_source = (
        source_artifact if source_artifact is not None else DEFAULT_W16_ARTIFACT
    )
    _verify_source_anchor(
        report["source_anchor"],
        source_artifact=expected_source,
        canonical_source=_CANONICAL_SOURCE,
    )
    _verify_source_closure(
        report["source_closure"],
        relative_paths=_W16_SOURCE_CLOSURE,
        loaded_source_digests=_W16_LOADED_SOURCE_DIGESTS,
    )
    reveal, world = _parse_extension_source(
        report["extension_source"],
        world_slot="W16",
        expected_pack=_expected_w16_pack,
        world_factory=W16World,
        custody_factory=make_w16_extension_custody,
    )
    manifest = _manifest("W16")
    if report["manifest"] != manifest or report["manifest_digest"] != digest_json(
        manifest
    ):
        raise ProtocolViolation("W16 adapter manifest mismatch")
    fixture = _closed(
        report["fixture"],
        {"split", "pair_seed", "primary_public_history_digest"},
        "W16 fixture",
    )
    if (
        fixture["split"] != WorldSplit.SEALED_TEST.value
        or type(fixture["pair_seed"]) is not int
        or fixture["pair_seed"] < 0
    ):
        raise ProtocolViolation("W16 fixture identity mismatch")
    _digest(fixture["primary_public_history_digest"], "W16 history digest")
    expected = _collect_w16_runtime(
        world,
        pair_seed=fixture["pair_seed"],
        source_closure_root=report["source_closure"]["closure_root"],
    )
    if fixture != expected["fixture"]:
        raise ProtocolViolation("W16 fixture differs from live replay")
    if report["scope_boundary"] != expected["scope_boundary"]:
        raise ProtocolViolation("W16 primary/revealed scope boundary mismatch")
    if (
        report["scope_boundary"]["revealed_extension"]["revealed_pack_digest"]
        != reveal.pack_digest
    ):
        raise ProtocolViolation(
            "W16 revealed pack digest is not bound to scope boundary"
        )
    if type(report["states"]) is not dict or report["states"] != expected["states"]:
        raise ProtocolViolation("W16 state bindings differ from live reconstruction")
    for alias, state in report["states"].items():
        _verify_state_binding(state, f"W16 state {alias}")
        if state["record"]["model_digest"] != report["source_closure"]["closure_root"]:
            raise ProtocolViolation(
                "W16 state model digest is not source-closure-bound"
            )
    if report["cells"] != expected["cells"]:
        raise ProtocolViolation("W16 cells differ from live extension behaviour")
    if report["cell_set_root"] != _cell_root(report["cells"]):
        raise ProtocolViolation("W16 cell-set root mismatch")
    summary = report["verification_summary"]
    expected_summary = {
        "status": "VALID_PRE_FREEZE_W16_EXTENSION_BEHAVIOUR_PROBE",
        "cell_count": len(expected["cells"]),
        "state_binding_count": len(expected["states"]),
        **expected["verification_facts"],
        "formal_scope_authority": False,
        "ucm_eligible": False,
        "ledger_credit": 0,
        "formalization_blockers": _FORMALIZATION_BLOCKERS,
    }
    if summary != expected_summary:
        raise ProtocolViolation("W16 verification summary was overstated")


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
        description="Run or verify the W16 PRE-FREEZE extension probe"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify-bundle", type=Path)
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_W16_ARTIFACT)
    parser.add_argument("--pair-seed", type=int, default=1601)
    args = parser.parse_args()
    if args.output is not None:
        report = run_w16_upper_bound_sanity(
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
    verify_w16_upper_bound_sanity(
        _load_canonical_report(args.verify_bundle),
        source_artifact=args.source_artifact,
    )
    return 0


_W16_LOADED_SOURCE_DIGESTS = _capture_loaded_source_digests(_W16_SOURCE_CLOSURE)


__all__ = [
    "DEFAULT_W16_ARTIFACT",
    "run_w16_upper_bound_sanity",
    "verify_w16_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
