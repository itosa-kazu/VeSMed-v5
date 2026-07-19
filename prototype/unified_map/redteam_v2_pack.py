"""Source-distinct post-seal red-team pack and commit/reveal custody.

This module intentionally knows nothing about the frozen W01--W20 simulators.
It defines a separate small stochastic process from first principles and emits
only public catalog/history wires plus judge-private analytic expectations.
Candidate construction lives in :mod:`redteam_v2_adapter`; keeping it out of
this file makes the pack generator's source independence mechanically auditable.

The production protocol is two phase:

1. ``prepare_custody`` writes a hiding commitment in the repository and writes
   the reveal *outside* the repository.  The commitment binds the exact pack,
   generator source, candidate source bindings, thresholds, and pre-pack git
   anchor without exposing any episode.
2. After the commitment itself has been durably committed, an orchestrator may
   call ``open_custody`` and run both pre-bound implementations once.  The
   reveal is copied into the result bundle only after raw outputs are sealed.

Tests use an explicit dummy secret.  No function in this module invents a
production secret or silently writes a reveal next to its commitment.
"""

from __future__ import annotations

import hashlib
import inspect
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes, digest_json
from .schema import EventKind, PlanKind


PACK_PROTOCOL = "ucm-source-distinct-redteam-pack/2"
COMMITMENT_PROTOCOL = "ucm-source-distinct-redteam-commitment/2"
REVEAL_PROTOCOL = "ucm-source-distinct-redteam-reveal/2"
REQUIRED_ATTACK_CLASSES = (
    "new_check",
    "new_treatment_opposite_response",
    "new_nonlinear_combination",
    "new_task_conditional_expected_future_utility",
    "ood",
    "dangerous_collision",
    "history_deletion_trio",
    "same_state_time_scales",
    "action_semantics",
    "query_update_rehydrate_compliance",
)
HORIZONS = (1, 24, 168)
LABELS = ("regulated", "inflamed", "depleted", "unknown")
SIGNATURE_DIMENSION = 32


def _source_bytes() -> bytes:
    return Path(inspect.getsourcefile(build_secret_pack) or __file__).read_bytes()


def source_digest() -> str:
    return digest_bytes(_source_bytes())


def _sha_stream(secret: bytes, *parts: object) -> bytes:
    preimage = b"UCM_REDTEAM_V2_SOURCE_DISTINCT\0" + secret
    for part in parts:
        preimage += b"\0" + str(part).encode("utf-8")
    return hashlib.sha256(preimage).digest()


def _u01(secret: bytes, *parts: object) -> float:
    raw = _sha_stream(secret, *parts)
    return (int.from_bytes(raw[:8], "big") + 0.5) / 2**64


def _signed(secret: bytes, *parts: object) -> float:
    return 2.0 * _u01(secret, *parts) - 1.0


def _normal(secret: bytes, *parts: object) -> float:
    u1 = max(1e-15, _u01(secret, *parts, "u1"))
    u2 = _u01(secret, *parts, "u2")
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _softmax(values: Iterable[float]) -> list[float]:
    rows = list(values)
    peak = max(rows)
    weights = [math.exp(value - peak) for value in rows]
    total = math.fsum(weights)
    return [value / total for value in weights]


def _catalog_wire(*, include_extension: bool) -> dict[str, Any]:
    base_observations = (
        ("rt_pulse", "continuous", "normalized", [-4.0, 4.0]),
        ("rt_inflammation", "continuous", "normalized", [-4.0, 4.0]),
        ("rt_reserve", "continuous", "normalized", [-4.0, 4.0]),
        ("rt_assay_artifact", "continuous", "normalized", [-8.0, 8.0]),
    )
    extension_observations = (
        ("rt_response", "continuous", "normalized", [-4.0, 4.0]),
        ("rt_new_check_signal", "continuous", "normalized", [-4.0, 4.0]),
    )
    base_actions = (
        ("rt_observation_shift", 0.01),
        ("rt_latent_repair", 0.04),
    )
    extension_actions = (
        ("rt_biphasic", 0.02),
        ("rt_order_new_check", 0.01),
    )
    observations = (*base_observations, *extension_observations) if include_extension else base_observations
    actions = (*base_actions, *extension_actions) if include_extension else base_actions
    return {
        "protocol": "ucm-public-catalog/1",
        "observations": [
            {
                "channel_id": channel,
                "value_type": value_type,
                "unit": unit,
                "valid_range": valid_range,
            }
            for channel, value_type, unit, valid_range in observations
        ],
        "actions": [
            {"action_id": action, "parameter_schema": {}, "cost": cost}
            for action, cost in actions
        ],
        "checks": ([
            {
                "check_id": "rt_new_check",
                "result_channels": ["rt_new_check_signal"],
                "delay_support": [1, 2],
                "cost": 0.01,
            }
        ] if include_extension else []),
        "diagnostic_labels": list(LABELS),
        "horizons": list(HORIZONS),
        "time_unit": "hour",
    }


def _plan_wires() -> list[dict[str, Any]]:
    return [
        {"plan_id": "natural", "kind": PlanKind.NO_NEW_ACTION.value, "actions": [], "policy_digest": None},
        {
            "plan_id": "biphasic",
            "kind": PlanKind.ACTION_SEQUENCE.value,
            "actions": [{"offset": 0, "action_id": "rt_biphasic", "parameters": {}}],
            "policy_digest": None,
        },
        {
            "plan_id": "observation_shift",
            "kind": PlanKind.ACTION_SEQUENCE.value,
            "actions": [{"offset": 0, "action_id": "rt_observation_shift", "parameters": {}}],
            "policy_digest": None,
        },
        {
            "plan_id": "latent_repair",
            "kind": PlanKind.ACTION_SEQUENCE.value,
            "actions": [{"offset": 0, "action_id": "rt_latent_repair", "parameters": {}}],
            "policy_digest": None,
        },
        {
            "plan_id": "new_check",
            "kind": PlanKind.ACTION_SEQUENCE.value,
            "actions": [{"offset": 0, "action_id": "rt_order_new_check", "parameters": {}}],
            "policy_digest": None,
        },
    ]


def _event(
    *,
    uid: str,
    kind: EventKind,
    time: int,
    payload: dict[str, Any],
    occurred_at: int | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind.value,
        "occurred_at": time if occurred_at is None else occurred_at,
        "collected_at": time if kind is EventKind.OBSERVATION_AVAILABLE else None,
        "available_at": time,
        "event_uid": uid,
        "payload": payload,
    }


def _history_wire(events: list[dict[str, Any]], catalog_digest: str, as_of: int = 0) -> dict[str, Any]:
    ordered = sorted(
        events,
        key=lambda row: (row["available_at"], row["occurred_at"], row["kind"], row["event_uid"]),
    )
    return {
        "protocol": "ucm-visible-history/1",
        "as_of_available_at": as_of,
        "catalog_digest": catalog_digest,
        "events": ordered,
    }


def _latent(secret: bytes, split: str, index: int, *, forced: str | None = None) -> dict[str, Any]:
    a = _signed(secret, split, index, "a")
    b = _signed(secret, split, index, "b")
    subtype = 1 if _u01(secret, split, index, "subtype") >= 0.5 else -1
    # Pre-register one genuinely held-out nonlinear quadrant while retaining
    # both marginal signs in training.  No ordinary training row occupies the
    # joint lower-left square used by ``novel_quadrant``.
    if split == "train" and a < -0.55 and b < -0.55:
        b = abs(b)
    if forced == "novel_quadrant":
        a = -0.55 - 0.4 * _u01(secret, split, index, "qa")
        b = -0.55 - 0.4 * _u01(secret, split, index, "qb")
    elif forced == "ood":
        a = 2.4 + 0.8 * _u01(secret, split, index, "oa")
        b = -2.4 - 0.8 * _u01(secret, split, index, "ob")
    return {
        "a": float(a),
        "b": float(b),
        "subtype": subtype,
        "interaction": float(a * b),
        "reserve": float(0.45 - 0.32 * a + 0.18 * b),
    }


def _observations(secret: bytes, split: str, index: int, latent: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step, time in enumerate((-72, -48, -24, 0)):
        drift = step / 3.0
        values = {
            "rt_pulse": 0.72 * latent["a"] + 0.18 * drift + 0.04 * _normal(secret, split, index, step, "p"),
            "rt_inflammation": 0.66 * latent["b"] + 0.42 * latent["interaction"] * drift + 0.04 * _normal(secret, split, index, step, "i"),
            "rt_reserve": latent["reserve"] - 0.12 * drift + 0.03 * _normal(secret, split, index, step, "r"),
        }
        # Deliberately reverse the middle-channel order in half of episodes.
        channels = list(values)
        if latent["subtype"] < 0 and step in {1, 2}:
            channels.reverse()
        for offset, channel in enumerate(channels):
            rows.append(
                _event(
                    uid=f"rt-{split}-{index:05d}-{step}-{offset}-{channel}",
                    kind=EventKind.OBSERVATION_AVAILABLE,
                    time=time,
                    payload={"channel_id": channel, "value": float(values[channel])},
                )
            )
    rows.append(
        _event(
            uid=f"rt-{split}-{index:05d}-context",
            kind=EventKind.CONTEXT_AVAILABLE,
            time=-6,
            payload={"context_type": "administrative_color", "value": "blue" if index % 2 else "green"},
        )
    )
    return rows


def _diagnostic_target(latent: dict[str, Any], *, ood: bool) -> dict[str, float]:
    if ood:
        return {label: float(label == "unknown") for label in LABELS}
    logits = (
        -abs(latent["a"]) - 0.2 * abs(latent["b"]),
        1.4 * latent["b"] + 0.7 * latent["interaction"],
        -1.1 * latent["reserve"] - 0.5 * latent["a"],
        -4.0,
    )
    values = _softmax(logits)
    return {label: float(values[position]) for position, label in enumerate(LABELS)}


def _conditional_expected_utility(latent: dict[str, Any]) -> float:
    """Analytic expectation; it contains no realized future-noise draw."""

    return float(
        0.7
        - 0.22 * latent["a"] ** 2
        - 0.20 * latent["b"] ** 2
        + 0.24 * latent["reserve"]
        - 0.28 * max(0.0, latent["interaction"] - 0.15) ** 2
    )


def _visible_conditional_expected_future_utility(history: dict[str, Any]) -> float:
    """A noise-integrated auxiliary future statistic identifiable from H.

    Define a future utility ``Y = g(H) + epsilon`` where the future innovation
    has conditional mean zero.  This function returns exactly ``E[Y | H]``.
    It is deliberately nonlinear and uses the allowed full visible sequence;
    no single realized epsilon is generated or scored.
    """

    series: dict[str, list[float]] = {
        "rt_pulse": [],
        "rt_inflammation": [],
        "rt_reserve": [],
    }
    order_code = 0.0
    observation_position = 0
    for event in history["events"]:
        if event["kind"] != EventKind.OBSERVATION_AVAILABLE.value:
            continue
        observation_position += 1
        channel = event["payload"].get("channel_id")
        value = event["payload"].get("value")
        if channel in series and type(value) in {int, float}:
            series[channel].append(float(value))
            order_code += observation_position * (1.0 if channel == "rt_inflammation" else -0.25)
    missing_count = sum(not values for values in series.values())
    if missing_count:
        # The registered auxiliary process defines missing-channel expectation
        # as zero imputation, not an inferred latent oracle.
        for values in series.values():
            if not values:
                values.append(0.0)
    pulse = series["rt_pulse"][-1]
    inflammation = series["rt_inflammation"][-1]
    reserve = series["rt_reserve"][-1]
    inflammation_mean = math.fsum(series["rt_inflammation"]) / len(series["rt_inflammation"])
    return float(
        0.52
        + 0.22 * reserve
        - 0.21 * pulse**2
        - 0.32 * inflammation**2
        + 0.37 * pulse * inflammation_mean
        + 0.025 * math.tanh(order_code / 40.0)
        - 0.12 * missing_count
    )


def _oracle_row(latent: dict[str, Any], plan_id: str, horizon: int) -> dict[str, Any]:
    scale = math.log1p(horizon) / math.log1p(max(HORIZONS))
    base = _conditional_expected_utility(latent)
    latent_delta = 0.0
    channel_delta = 0.0
    if plan_id == "biphasic":
        latent_delta = (0.34 if latent["subtype"] > 0 else -0.42) * scale
    elif plan_id == "latent_repair":
        latent_delta = (0.28 + 0.12 * max(0.0, latent["b"])) * scale
    elif plan_id == "observation_shift":
        channel_delta = 0.75 * scale
    elif plan_id == "new_check":
        channel_delta = 0.12 * scale
    slow_harm = -0.18 * max(0.0, latent["interaction"]) * scale**2
    utility = base + latent_delta + slow_harm
    signature = [0.0] * SIGNATURE_DIMENSION
    signature[0] = float(latent["a"] * (1.0 - 0.18 * scale) - 0.3 * latent_delta)
    signature[1] = float(latent["b"] * (1.0 + 0.12 * scale) - 0.4 * latent_delta)
    signature[2] = float(latent["reserve"] + 0.45 * latent_delta - 0.08 * scale)
    signature[3] = float(channel_delta)
    signature[4] = float(latent["interaction"] * (1.0 + scale**2))
    signature[5] = float(utility)
    signature[6] = float(0.5 * latent_delta if horizon >= 24 else -0.1 * latent_delta)
    signature[7] = float(max(0.0, -utility + 0.25) ** 2)
    return {
        "plan_id": plan_id,
        "horizon": horizon,
        "signature": signature,
        "expected_utility": float(utility),
        "conditional_expectation": True,
    }


def _episode(
    secret: bytes,
    split: str,
    index: int,
    catalog_digest: str,
    *,
    forced: str | None = None,
) -> dict[str, Any]:
    latent = _latent(secret, split, index, forced=forced)
    ood = forced == "ood"
    history = _history_wire(_observations(secret, split, index, latent), catalog_digest)
    return {
        "instance_id": f"RT2-{split}-{index:05d}",
        "tier": forced or "ordinary",
        "public_history": history,
        "judge_private": {
            "latent": latent,
            "diagnostic_target": _diagnostic_target(latent, ood=ood),
            "conditional_expected_future_utility": _visible_conditional_expected_future_utility(history),
            "new_check_result": float(0.86 * latent["subtype"] + 0.12 * latent["a"]),
            "oracle_rows": [
                _oracle_row(latent, plan["plan_id"], horizon)
                for horizon in HORIZONS
                for plan in _plan_wires()
            ],
        },
    }


def _history_digest(history: dict[str, Any]) -> str:
    return digest_json(history)


def _replace_history(episode: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    value = {
        "instance_id": episode["instance_id"],
        "tier": episode["tier"],
        "public_history": _history_wire(
            events,
            episode["public_history"]["catalog_digest"],
            episode["public_history"]["as_of_available_at"],
        ),
        "judge_private": episode["judge_private"],
    }
    return value


def _history_deletion_pairs(base: dict[str, Any]) -> list[dict[str, Any]]:
    events = base["public_history"]["events"]
    irrelevant = [row for row in events if row["kind"] != EventKind.CONTEXT_AVAILABLE.value]
    relevant_candidates = [
        row
        for row in events
        if row["kind"] == EventKind.OBSERVATION_AVAILABLE.value
        and row["payload"].get("channel_id") == "rt_inflammation"
    ]
    relevant_uids = {row["event_uid"] for row in relevant_candidates}
    relevant = [row for row in events if row["event_uid"] not in relevant_uids]
    # A truly redundant duplicate is injected and then deleted.  The episode
    # oracle is identical by construction, while the visible byte sequence is not.
    redundant_event = dict(
        next(row for row in events if row["kind"] == EventKind.CONTEXT_AVAILABLE.value)
    )
    redundant_event["event_uid"] = redundant_event["event_uid"] + "-redundant-copy"
    redundant_added = _replace_history(base, [*events, redundant_event])
    irrelevant_episode = _replace_history(base, irrelevant)
    relevant_episode = _replace_history(base, relevant)
    base_target = _visible_conditional_expected_future_utility(base["public_history"])
    irrelevant_target = _visible_conditional_expected_future_utility(irrelevant_episode["public_history"])
    relevant_target = _visible_conditional_expected_future_utility(relevant_episode["public_history"])
    redundant_target = _visible_conditional_expected_future_utility(redundant_added["public_history"])
    return [
        {
            "pair_id": base["instance_id"] + "-delete-irrelevant",
            "control": "oracle_irrelevant",
            "left": base,
            "right": irrelevant_episode,
            "expected_state_relation": "equivalent",
            "oracle_relation": "equivalent",
            "oracle_distance": abs(base_target - irrelevant_target),
            "oracle_values": [base_target, irrelevant_target],
        },
        {
            "pair_id": base["instance_id"] + "-delete-relevant",
            "control": "latent_relevant",
            "left": base,
            "right": relevant_episode,
            "expected_state_relation": "distinguishable",
            "oracle_relation": "posterior_information_removed",
            "oracle_distance": abs(base_target - relevant_target),
            "oracle_values": [base_target, relevant_target],
        },
        {
            "pair_id": base["instance_id"] + "-delete-redundant",
            "control": "oracle_equivalent_redundant",
            "left": redundant_added,
            "right": base,
            "expected_state_relation": "equivalent",
            "oracle_relation": "equivalent",
            "oracle_distance": abs(redundant_target - base_target),
            "oracle_values": [redundant_target, base_target],
        },
    ]


def _collision_pairs(test_episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Match on coarse endpoint summaries while selecting opposite treatment
    # response signs.  Exact histories and analytic futures remain source-distinct.
    positives = [row for row in test_episodes if row["judge_private"]["latent"]["subtype"] > 0 and row["tier"] == "ordinary"]
    negatives = [row for row in test_episodes if row["judge_private"]["latent"]["subtype"] < 0 and row["tier"] == "ordinary"]
    for index, left in enumerate(positives[:4]):
        if not negatives:
            break
        right = min(
            negatives,
            key=lambda row: abs(row["judge_private"]["latent"]["a"] - left["judge_private"]["latent"]["a"])
            + abs(row["judge_private"]["latent"]["b"] - left["judge_private"]["latent"]["b"]),
        )
        rows.append(
            {
                "pair_id": f"RT2-collision-{index:02d}",
                "control": "opposite_response_matched_coarse_history",
                "left_instance_id": left["instance_id"],
                "right_instance_id": right["instance_id"],
                "oracle_relation": "distinguishable",
                "oracle_margin": abs(
                    next(item for item in left["judge_private"]["oracle_rows"] if item["plan_id"] == "biphasic" and item["horizon"] == 168)["expected_utility"]
                    - next(item for item in right["judge_private"]["oracle_rows"] if item["plan_id"] == "biphasic" and item["horizon"] == 168)["expected_utility"]
                ),
            }
        )
    return rows


def build_secret_pack(
    secret: bytes,
    *,
    training_count: int = 48,
    ordinary_test_count: int = 20,
) -> dict[str, Any]:
    """Materialize one deterministic source-distinct pack from an explicit secret.

    Calling this function is pack materialization.  Production callers must do
    so only inside ``prepare_custody`` after both implementations are frozen.
    """

    if type(secret) is not bytes or len(secret) < 16:
        raise ProtocolViolation("red-team secret must be at least 128 bits")
    if training_count < 24 or ordinary_test_count < 12:
        raise ProtocolViolation("red-team pack is too small for its registered probes")
    catalog = _catalog_wire(include_extension=False)
    extension_catalog = _catalog_wire(include_extension=True)
    catalog_digest = digest_json(catalog)
    extension_catalog_digest = digest_json(extension_catalog)
    training = [_episode(secret, "train", index, catalog_digest) for index in range(training_count)]
    ordinary = [_episode(secret, "test", index, catalog_digest) for index in range(ordinary_test_count)]
    novel = [
        _episode(secret, "test-nonlinear", index, catalog_digest, forced="novel_quadrant")
        for index in range(8)
    ]
    ood = [_episode(secret, "test-ood", index, catalog_digest, forced="ood") for index in range(8)]
    tests = [*ordinary, *novel, *ood]
    deletion = _history_deletion_pairs(ordinary[0])
    if deletion[0]["oracle_distance"] > 1e-12 or deletion[2]["oracle_distance"] > 1e-12:
        raise ProtocolViolation("history-deletion equivalence controls are not oracle-equivalent")
    if deletion[1]["oracle_distance"] < 0.05:
        raise ProtocolViolation("history-deletion relevant control is not oracle-distinguishable")
    time_anchor = ordinary[1]
    return {
        "protocol": PACK_PROTOCOL,
        "generator_source_digest": source_digest(),
        "source_distinct_declaration": {
            "does_not_import_frozen_worlds": True,
            "does_not_use_frozen_fixtures": True,
            "does_not_use_frozen_oracles": True,
            "semantic_origin": "independent analytic latent process in redteam_v2_pack.py",
        },
        "attack_classes": list(REQUIRED_ATTACK_CLASSES),
        "catalog": catalog,
        "catalog_digest": catalog_digest,
        "extension_catalog": extension_catalog,
        "extension_catalog_digest": extension_catalog_digest,
        "extension_contract": {
            "primary_catalog_digest": catalog_digest,
            "extension_catalog_digest": extension_catalog_digest,
            "new_check_id": "rt_new_check",
            "new_check_channel": "rt_new_check_signal",
            "new_treatment_id": "rt_biphasic",
            "operator_absent_from_primary_training_scope": True,
            "old_state_local_use_is_scope_insufficient": True,
            "admissible_migration": "fit extension scope and replay visible history",
        },
        "plans": _plan_wires(),
        "horizons": list(HORIZONS),
        "training_episodes": training,
        "test_episodes": tests,
        "paired_controls": {
            "collision": _collision_pairs(tests),
            "history_deletion": deletion,
            "time_scales": {
                "instance_id": time_anchor["instance_id"],
                "history_digest": _history_digest(time_anchor["public_history"]),
                "horizons": list(HORIZONS),
                "same_world_same_episode_same_state_required": True,
            },
            "action_semantics": {
                "instance_id": ordinary[2]["instance_id"],
                "channel_only_plan": "observation_shift",
                "latent_only_plan": "latent_repair",
                "reference_plan": "natural",
                "opposite_response_plan": "biphasic",
            },
            "new_check": {
                "informative_instance_id": ordinary[3]["instance_id"],
                "null_instance_id": ordinary[4]["instance_id"],
                "locality_instance_id": ordinary[5]["instance_id"],
            },
        },
        "new_task_contract": {
            "target": "conditional_expected_future_utility",
            "realized_future_noise_used": False,
            "views": ["state_only", "same_capacity_full_visible_history", "true_state_upper_bound"],
            "capacities": [8, 32, 128],
            "probe": "ridge_with_fixed_hash_projection",
            "split": "train_to_secret_test",
        },
        "thresholds": {
            "state_equivalence_l2": 1e-9,
            "oracle_distinguishable_l2": 0.05,
            "catastrophic_utility_margin": 0.25,
            "ood_unknown_decision_boundary": 0.5,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_bytes())
    if type(value) is not dict:
        raise ProtocolViolation(f"{path} must contain a JSON object")
    return value


def _write_canonical(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def prepare_custody(
    *,
    secret: bytes,
    repository_root: Path,
    commitment_path: Path,
    external_reveal_path: Path,
    pre_pack_git_commit: str,
    candidate_source_bindings: dict[str, str],
    created_at: str | None = None,
    training_count: int = 48,
    ordinary_test_count: int = 20,
) -> dict[str, Any]:
    """Write public commitment and hidden reveal to provably separate trees."""

    root = repository_root.resolve()
    commitment_path = commitment_path.resolve()
    external_reveal_path = external_reveal_path.resolve()
    try:
        external_reveal_path.relative_to(root)
    except ValueError:
        pass
    else:
        raise ProtocolViolation("secret reveal must be stored outside repository root")
    try:
        commitment_path.relative_to(root)
    except ValueError as exc:
        raise ProtocolViolation("commitment must be stored inside repository root") from exc
    if not pre_pack_git_commit or len(pre_pack_git_commit) < 7:
        raise ProtocolViolation("pre-pack git commit is required")
    if set(candidate_source_bindings) != {"sealed_f18", "independent_f18"}:
        raise ProtocolViolation("both candidate source bindings must be frozen pre-pack")
    if any(not value.startswith("sha256:") or len(value) != 71 for value in candidate_source_bindings.values()):
        raise ProtocolViolation("candidate source bindings must be SHA-256 digests")
    pack = build_secret_pack(
        secret,
        training_count=training_count,
        ordinary_test_count=ordinary_test_count,
    )
    reveal = {
        "protocol": REVEAL_PROTOCOL,
        "secret_hex": secret.hex(),
        "pack": pack,
        "pack_digest": digest_json(pack),
    }
    reveal_digest = digest_json(reveal)
    commitment = {
        "protocol": COMMITMENT_PROTOCOL,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "pre_pack_git_commit": pre_pack_git_commit,
        "candidate_source_bindings": dict(sorted(candidate_source_bindings.items())),
        "generator_source_digest": source_digest(),
        "reveal_digest": reveal_digest,
        "pack_digest": reveal["pack_digest"],
        "attack_classes": list(REQUIRED_ATTACK_CLASSES),
        "thresholds_digest": digest_json(pack["thresholds"]),
        "new_task_contract_digest": digest_json(pack["new_task_contract"]),
        "custody": {
            "reveal_outside_repository": True,
            "commitment_must_be_durably_committed_before_open": True,
            "one_shot_all_prebound_implementations_before_publish": True,
        },
    }
    _write_canonical(external_reveal_path, reveal)
    _write_canonical(commitment_path, commitment)
    return commitment


def verify_reveal(commitment: dict[str, Any], reveal: dict[str, Any]) -> dict[str, Any]:
    if commitment.get("protocol") != COMMITMENT_PROTOCOL:
        raise ProtocolViolation("red-team commitment protocol mismatch")
    if reveal.get("protocol") != REVEAL_PROTOCOL:
        raise ProtocolViolation("red-team reveal protocol mismatch")
    if digest_json(reveal) != commitment.get("reveal_digest"):
        raise ProtocolViolation("red-team reveal does not match hiding commitment")
    pack = reveal.get("pack")
    if type(pack) is not dict or digest_json(pack) != commitment.get("pack_digest"):
        raise ProtocolViolation("red-team pack digest mismatch")
    if pack.get("generator_source_digest") != commitment.get("generator_source_digest"):
        raise ProtocolViolation("red-team generator source binding mismatch")
    if tuple(pack.get("attack_classes", ())) != REQUIRED_ATTACK_CLASSES:
        raise ProtocolViolation("red-team attack-class registry mismatch")
    if digest_json(pack.get("thresholds")) != commitment.get("thresholds_digest"):
        raise ProtocolViolation("red-team thresholds changed after commitment")
    if digest_json(pack.get("new_task_contract")) != commitment.get("new_task_contract_digest"):
        raise ProtocolViolation("red-team new-task contract changed after commitment")
    return pack


def open_custody(commitment_path: Path, external_reveal_path: Path) -> dict[str, Any]:
    return verify_reveal(_read_json(commitment_path), _read_json(external_reveal_path))


__all__ = [
    "COMMITMENT_PROTOCOL",
    "PACK_PROTOCOL",
    "REQUIRED_ATTACK_CLASSES",
    "REVEAL_PROTOCOL",
    "build_secret_pack",
    "open_custody",
    "prepare_custody",
    "source_digest",
    "verify_reveal",
]
