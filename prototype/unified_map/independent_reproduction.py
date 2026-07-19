"""Full frozen-v1 reproduction of sealed F18 through an independent implementation.

The reproduction harness uses the public seed reveal, verifies that it opens the
frozen commitments, and evaluates the sealed implementation beside
``IndependentStructuralEnsemble`` on every W01--W20 panel and R01--R05
replicate.  Candidate code receives public training records, public histories,
shared states and public query descriptions only.  Simulator-private state is
kept on the judge side and is never passed to either candidate.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterable

import numpy as np

from .benchmark_v1_contract import (
    DiagnosisPrediction,
    RolloutPrediction,
    SharedPatientState,
)
from .benchmark_v1_freeze import (
    FREEZE_FILENAME,
    MODEL_SEEDS,
    REPLICATE_IDS,
    SPLIT_EPISODES_PER_PANEL,
    verify_freeze_manifest_bytes,
    verify_seed_reveal,
)
from .benchmark_v1_runner import _training_records as _judge_training_records
from .candidate_families import make_candidate
from .candidate_seal import verify_candidate_seal
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from .independent_f18 import IndependentStructuralEnsemble
from .schema import VisibleDelta, VisibleHistory
from .world_registry import EXTENSION_WORLD_REGISTRY, WORLD_REGISTRY
from .worlds.base import MicroWorld, PrivateEpisode, WorldSplit


REPRODUCTION_PROTOCOL = "ucm-independent-f18-full-reproduction/2"
MANIFEST_PROTOCOL = "ucm-independent-f18-reproduction-manifest/2"
EPISODE_RAW_PROTOCOL = "ucm-independent-f18-episode-raw/2"
PAIR_RAW_PROTOCOL = "ucm-independent-f18-pair-raw/2"
SEED_DERIVATION_DOMAIN = b"UCM_EXECUTABLE_BENCHMARK_V1_SEED_DERIVATION\0"
PAIR_LIMIT_PER_DECLARATION = 2
SOURCE_PATHS = (
    "prototype/unified_map/independent_f18.py",
    "prototype/unified_map/independent_reproduction.py",
    "prototype/unified_map/candidate_families.py",
    "prototype/unified_map/benchmark_v1_runner.py",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_commit(root: Path) -> str:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProtocolViolation("source Git commit is unavailable") from exc
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ProtocolViolation("source Git commit is malformed")
    return value


def _decode_canonical(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} is unavailable or invalid") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    return value


def _derived_seed(root_seed: int, *parts: str | int) -> int:
    payload = canonical_json_bytes([root_seed, *parts])
    return int.from_bytes(
        hashlib.sha256(SEED_DERIVATION_DOMAIN + payload).digest()[:8], "big"
    ) & ((1 << 63) - 1)


def _panels() -> list[tuple[str, Any, MicroWorld]]:
    return [
        (slot, panel, panel.instantiate())
        for slot in WORLD_REGISTRY
        for panel in WORLD_REGISTRY[slot].panels
    ]


def _flatten_probe_result(
    result: object, mapping: bool
) -> list[tuple[PrivateEpisode, ...]]:
    if mapping:
        if type(result) is not dict:
            raise ProtocolViolation("mapping probe did not return a dict")
        rows: list[tuple[PrivateEpisode, ...]] = []
        for key in sorted(result):
            value = result[key]
            if (
                type(value) is not tuple
                or not value
                or any(type(item) is not PrivateEpisode for item in value)
            ):
                raise ProtocolViolation("mapping probe contains invalid episodes")
            rows.append(value)
        return rows
    if type(result) is PrivateEpisode:
        return [(result,)]
    if (
        type(result) is tuple
        and result
        and all(type(item) is PrivateEpisode for item in result)
    ):
        return [result]
    raise ProtocolViolation("probe result is invalid")


def _split_history(history: VisibleHistory) -> tuple[VisibleHistory, VisibleDelta]:
    """Return a strict public prefix and a non-empty public suffix delta."""

    if not history.events:
        raise ProtocolViolation("reproduction episode has no event for non-empty update")
    split = len(history.events) // 2
    if split == len(history.events):
        split -= 1
    prefix_events = history.events[:split]
    prefix_as_of = (
        max(event.available_at for event in prefix_events) if prefix_events else 0
    )
    prefix = VisibleHistory(prefix_events, prefix_as_of, history.catalog_digest)
    delta = VisibleDelta(history.as_of_available_at, history.events[split:])
    if not delta.events:
        raise ProtocolViolation("reproduction non-empty update unexpectedly became empty")
    return prefix, delta


def _max_abs(left: Iterable[float], right: Iterable[float]) -> float:
    a = np.asarray(tuple(left), dtype=np.float64)
    b = np.asarray(tuple(right), dtype=np.float64)
    if a.shape != b.shape:
        raise ProtocolViolation("compared vectors have different shapes")
    return float(np.max(np.abs(a - b))) if a.size else 0.0


def _prediction_wire(prediction: RolloutPrediction) -> dict[str, Any]:
    return {
        "signature": list(prediction.signature),
        "expected_utility": prediction.expected_utility,
        "abstained": prediction.abstained,
    }


def _state_wire(state: SharedPatientState) -> dict[str, Any]:
    return {
        "state_hash": state.state_hash,
        "schema_version": state.schema_version,
        "payload_sha256": digest_bytes(state.payload),
        "payload_bytes": len(state.payload),
        "distance_vector": list(state.distance_vector),
    }


def _new_differences() -> dict[str, float]:
    return {
        "prefix_state_vector_max_abs": 0.0,
        "full_state_vector_max_abs": 0.0,
        "updated_state_vector_max_abs": 0.0,
        "diagnosis_probability_max_abs": 0.0,
        "updated_diagnosis_probability_max_abs": 0.0,
        "reference_diagnosis_update_replay_max_abs": 0.0,
        "independent_diagnosis_update_replay_max_abs": 0.0,
        "rollout_signature_max_abs": 0.0,
        "rollout_utility_max_abs": 0.0,
        "updated_rollout_signature_max_abs": 0.0,
        "updated_rollout_utility_max_abs": 0.0,
        "reference_rollout_update_replay_signature_max_abs": 0.0,
        "reference_rollout_update_replay_utility_max_abs": 0.0,
        "independent_rollout_update_replay_signature_max_abs": 0.0,
        "independent_rollout_update_replay_utility_max_abs": 0.0,
        "pair_distance_max_abs": 0.0,
    }


def _merge_max(target: dict[str, float], source: dict[str, float]) -> None:
    for key, value in source.items():
        target[key] = max(target[key], value)


def _evaluate_episode(
    *,
    reference: Any,
    independent: IndependentStructuralEnsemble,
    slot: str,
    panel: Any,
    world: MicroWorld,
    episode: PrivateEpisode,
    replicate_id: str,
    episode_index: int,
    oracle_root: int,
) -> tuple[dict[str, Any], dict[str, float], dict[str, int], int]:
    candidates = (reference, independent)
    history = episode.public_history
    prefix, nonempty_delta = _split_history(history)
    initialize_seed = _derived_seed(oracle_root, "initialize", episode_index)
    update_seed = _derived_seed(oracle_root, "update", episode_index)
    diagnosis_seed = _derived_seed(oracle_root, "diagnosis", episode_index)

    full_states = tuple(
        candidate.initialize(history, inference_seed=initialize_seed)
        for candidate in candidates
    )
    prefix_states = tuple(
        candidate.initialize(prefix, inference_seed=initialize_seed)
        for candidate in candidates
    )
    empty_states = tuple(
        candidate.update(
            state,
            VisibleDelta(history.as_of_available_at, ()),
            inference_seed=update_seed,
        )
        for candidate, state in zip(candidates, full_states, strict=True)
    )
    updated_states = tuple(
        candidate.update(
            state,
            nonempty_delta,
            inference_seed=update_seed,
        )
        for candidate, state in zip(candidates, prefix_states, strict=True)
    )

    differences = _new_differences()
    differences["prefix_state_vector_max_abs"] = _max_abs(
        prefix_states[0].distance_vector, prefix_states[1].distance_vector
    )
    differences["full_state_vector_max_abs"] = _max_abs(
        full_states[0].distance_vector, full_states[1].distance_vector
    )
    differences["updated_state_vector_max_abs"] = _max_abs(
        updated_states[0].distance_vector, updated_states[1].distance_vector
    )
    failures = {
        "empty_update_identity": sum(
            int(before.state_hash != after.state_hash)
            for before, after in zip(full_states, empty_states, strict=True)
        ),
        "nonempty_update_replay": sum(
            int(full.state_hash != updated.state_hash)
            for full, updated in zip(full_states, updated_states, strict=True)
        ),
        "abstention_mismatch": 0,
        "nonempty_head_replay": 0,
    }

    diagnoses = tuple(
        candidate.diagnose(
            state, world.catalog.diagnostic_labels, query_seed=diagnosis_seed
        )
        for candidate, state in zip(candidates, full_states, strict=True)
    )
    updated_diagnoses = tuple(
        candidate.diagnose(
            state, world.catalog.diagnostic_labels, query_seed=diagnosis_seed
        )
        for candidate, state in zip(candidates, updated_states, strict=True)
    )
    if any(type(value) is not DiagnosisPrediction for value in (*diagnoses, *updated_diagnoses)):
        raise ProtocolViolation("reproduction diagnosis head returned wrong type")
    for value in (*diagnoses, *updated_diagnoses):
        value.validate_for(world.catalog)
    differences["diagnosis_probability_max_abs"] = max(
        abs(diagnoses[0].probabilities[label] - diagnoses[1].probabilities[label])
        for label in world.catalog.diagnostic_labels
    )
    differences["updated_diagnosis_probability_max_abs"] = max(
        abs(
            updated_diagnoses[0].probabilities[label]
            - updated_diagnoses[1].probabilities[label]
        )
        for label in world.catalog.diagnostic_labels
    )
    differences["reference_diagnosis_update_replay_max_abs"] = max(
        abs(
            diagnoses[0].probabilities[label]
            - updated_diagnoses[0].probabilities[label]
        )
        for label in world.catalog.diagnostic_labels
    )
    differences["independent_diagnosis_update_replay_max_abs"] = max(
        abs(
            diagnoses[1].probabilities[label]
            - updated_diagnoses[1].probabilities[label]
        )
        for label in world.catalog.diagnostic_labels
    )
    failures["nonempty_head_replay"] += sum(
        int(before.probabilities != after.probabilities)
        for before, after in zip(diagnoses, updated_diagnoses, strict=True)
    )
    rollout_rows: list[dict[str, Any]] = []
    rollout_query_count = 0
    for horizon in world.catalog.horizons:
        policies = world.policy_set(horizon)
        for policy_index, policy in enumerate(policies):
            query_seed = _derived_seed(
                oracle_root, "rollout", episode_index, horizon, policy_index
            )
            predictions = tuple(
                candidate.rollout(state, policy, horizon, query_seed=query_seed)
                for candidate, state in zip(candidates, full_states, strict=True)
            )
            updated_predictions = tuple(
                candidate.rollout(state, policy, horizon, query_seed=query_seed)
                for candidate, state in zip(candidates, updated_states, strict=True)
            )
            if any(
                type(value) is not RolloutPrediction
                for value in (*predictions, *updated_predictions)
            ):
                raise ProtocolViolation("reproduction rollout head returned wrong type")
            differences["rollout_signature_max_abs"] = max(
                differences["rollout_signature_max_abs"],
                _max_abs(predictions[0].signature, predictions[1].signature),
            )
            differences["rollout_utility_max_abs"] = max(
                differences["rollout_utility_max_abs"],
                abs(predictions[0].expected_utility - predictions[1].expected_utility),
            )
            differences["updated_rollout_signature_max_abs"] = max(
                differences["updated_rollout_signature_max_abs"],
                _max_abs(
                    updated_predictions[0].signature,
                    updated_predictions[1].signature,
                ),
            )
            differences["updated_rollout_utility_max_abs"] = max(
                differences["updated_rollout_utility_max_abs"],
                abs(
                    updated_predictions[0].expected_utility
                    - updated_predictions[1].expected_utility
                ),
            )
            for implementation_index, name in enumerate(
                ("reference", "independent")
            ):
                differences[
                    f"{name}_rollout_update_replay_signature_max_abs"
                ] = max(
                    differences[
                        f"{name}_rollout_update_replay_signature_max_abs"
                    ],
                    _max_abs(
                        predictions[implementation_index].signature,
                        updated_predictions[implementation_index].signature,
                    ),
                )
                differences[
                    f"{name}_rollout_update_replay_utility_max_abs"
                ] = max(
                    differences[
                        f"{name}_rollout_update_replay_utility_max_abs"
                    ],
                    abs(
                        predictions[implementation_index].expected_utility
                        - updated_predictions[implementation_index].expected_utility
                    ),
                )
                failures["nonempty_head_replay"] += int(
                    predictions[implementation_index]
                    != updated_predictions[implementation_index]
                )
            failures["abstention_mismatch"] += int(
                predictions[0].abstained != predictions[1].abstained
            )
            failures["abstention_mismatch"] += int(
                updated_predictions[0].abstained != updated_predictions[1].abstained
            )
            rollout_rows.append(
                {
                    "horizon": horizon,
                    "policy_index": policy_index,
                    "policy": policy.to_wire(),
                    "query_seed": query_seed,
                    "reference": _prediction_wire(predictions[0]),
                    "independent": _prediction_wire(predictions[1]),
                    "reference_after_nonempty_update": _prediction_wire(
                        updated_predictions[0]
                    ),
                    "independent_after_nonempty_update": _prediction_wire(
                        updated_predictions[1]
                    ),
                }
            )
            rollout_query_count += 1

    raw = {
        "protocol": EPISODE_RAW_PROTOCOL,
        "replicate_id": replicate_id,
        "world_slot": slot,
        "panel_id": panel.panel_id,
        "episode_index": episode_index,
        "public_history_digest": history.digest,
        "public_event_count": len(history.events),
        "prefix_history_digest": prefix.digest,
        "prefix_event_count": len(prefix.events),
        "nonempty_delta_digest": digest_json(nonempty_delta.to_wire()),
        "nonempty_delta_event_count": len(nonempty_delta.events),
        "states": {
            "prefix_reference": _state_wire(prefix_states[0]),
            "prefix_independent": _state_wire(prefix_states[1]),
            "full_reference": _state_wire(full_states[0]),
            "full_independent": _state_wire(full_states[1]),
            "empty_updated_reference": _state_wire(empty_states[0]),
            "empty_updated_independent": _state_wire(empty_states[1]),
            "nonempty_updated_reference": _state_wire(updated_states[0]),
            "nonempty_updated_independent": _state_wire(updated_states[1]),
        },
        "diagnosis": {
            "reference": diagnoses[0].probabilities,
            "independent": diagnoses[1].probabilities,
            "reference_after_nonempty_update": updated_diagnoses[0].probabilities,
            "independent_after_nonempty_update": updated_diagnoses[1].probabilities,
        },
        "rollouts": rollout_rows,
        "differences": differences,
        "failures": failures,
    }
    return raw, differences, failures, rollout_query_count


def _evaluate_pairs(
    *,
    reference: Any,
    independent: IndependentStructuralEnsemble,
    panels: list[tuple[str, Any, MicroWorld]],
    replicate_id: str,
    seed_root: int,
    writer: BinaryIO,
) -> tuple[int, float]:
    count = 0
    maximum = 0.0
    for slot, panel, world in panels:
        # Match the frozen benchmark runner's primary-scope pair protocol.
        # W16/W17 pair declarations belong to the separately committed S1
        # extension workflow and deliberately fail before its reveal.  Calling
        # them here would widen REPRO5 beyond the sealed F18 run rather than
        # reproduce it (benchmark_v1_runner._precompute_pair_oracles applies
        # the same exclusion).
        if slot in EXTENSION_WORLD_REGISTRY:
            continue
        for declaration in panel.probes:
            for probe_index in range(
                min(PAIR_LIMIT_PER_DECLARATION, declaration.indexed_count)
            ):
                seed = _derived_seed(
                    seed_root,
                    slot,
                    panel.panel_id,
                    declaration.probe_id,
                    probe_index,
                )
                method = getattr(world, declaration.method_name)
                result = (
                    method(seed, probe_index=probe_index)
                    if declaration.indexed_count > 1
                    else method(seed)
                )
                for group_index, episodes in enumerate(
                    _flatten_probe_result(result, declaration.mapping_result)
                ):
                    if len(episodes) < 2:
                        continue
                    left, right = episodes[:2]
                    distances: list[float] = []
                    state_hashes: dict[str, list[str]] = {}
                    for name, candidate in (
                        ("reference", reference),
                        ("independent", independent),
                    ):
                        states = tuple(
                            candidate.initialize(
                                episode.public_history,
                                inference_seed=seed + side + 1,
                            )
                            for side, episode in enumerate((left, right))
                        )
                        distances.append(
                            float(
                                np.linalg.norm(
                                    np.asarray(states[0].distance_vector)
                                    - np.asarray(states[1].distance_vector)
                                )
                            )
                        )
                        state_hashes[name] = [state.state_hash for state in states]
                    difference = abs(distances[0] - distances[1])
                    maximum = max(maximum, difference)
                    writer.write(
                        canonical_json_bytes(
                            {
                                "protocol": PAIR_RAW_PROTOCOL,
                                "replicate_id": replicate_id,
                                "world_slot": slot,
                                "panel_id": panel.panel_id,
                                "probe_id": declaration.probe_id,
                                "probe_index": probe_index,
                                "group_index": group_index,
                                "seed": seed,
                                "left_history_digest": left.public_history.digest,
                                "right_history_digest": right.public_history.digest,
                                "reference_distance": distances[0],
                                "independent_distance": distances[1],
                                "distance_absolute_difference": difference,
                                "state_hashes": state_hashes,
                            }
                        )
                    )
                    count += 1
    return count, maximum


def _write_deterministic_gzip(source: Path, target: Path) -> None:
    with source.open("rb") as reader, target.open("wb") as raw_target:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw_target, compresslevel=9, mtime=0
        ) as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)


def _source_binding(root: Path) -> list[dict[str, Any]]:
    rows = []
    for relative in SOURCE_PATHS:
        raw = (root / relative).read_bytes()
        rows.append(
            {
                "relative_path": relative,
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        )
    return rows


def reproduce(
    *,
    seal_path: Path,
    freeze_path: Path,
    reveal_path: Path,
    output_root: Path,
) -> Path:
    root = _repo_root()
    freeze = verify_freeze_manifest_bytes(freeze_path.read_bytes())
    reveal = _decode_canonical(reveal_path, "benchmark seed reveal")
    verify_seed_reveal(reveal, freeze)
    seal = verify_candidate_seal(seal_path, repo_root=root)
    source_commit = _source_commit(root)
    if seal["freeze_root"] != freeze["freeze_root"]:
        raise ProtocolViolation("candidate seal and benchmark reveal bind different freezes")

    panels = _panels()
    if len(panels) != freeze["panel_count"] or len(panels) != 21:
        raise ProtocolViolation("reproduction did not resolve all 21 frozen panels")
    reveal_rows = {row["replicate_id"]: row for row in reveal["replicates"]}
    if tuple(reveal_rows) != REPLICATE_IDS:
        raise ProtocolViolation("seed reveal replicate order drifted")

    run_id = (
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"I18-full-repro-{uuid.uuid4().hex[:10]}"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / run_id
    temporary = output_root / f".{run_id}.tmp"
    if output.exists() or temporary.exists():
        raise ProtocolViolation("reproduction run id collision")
    temporary.mkdir(parents=True)
    episode_path = temporary / "raw-episodes.jsonl"
    pair_path = temporary / "raw-pairs.jsonl"
    started = time.perf_counter()

    global_differences = _new_differences()
    global_failures = {
        "empty_update_identity": 0,
        "nonempty_update_replay": 0,
        "abstention_mismatch": 0,
        "nonempty_head_replay": 0,
    }
    replicate_summaries: list[dict[str, Any]] = []
    episode_count = 0
    rollout_query_count = 0
    pair_count = 0
    try:
        with episode_path.open("wb") as episode_writer, pair_path.open("wb") as pair_writer:
            for replicate_index, replicate_id in enumerate(REPLICATE_IDS):
                seed_row = reveal_rows[replicate_id]
                # These frozen judge helpers parallelize oracle materialization.  They
                # return only public training records to fit; sealed private state and
                # counterfactuals remain in this harness and never enter a candidate.
                catalogs, training = _judge_training_records(
                    panels, seed_row, SPLIT_EPISODES_PER_PANEL["train"]
                )
                reference = make_candidate("F18")
                independent = IndependentStructuralEnsemble()
                model_seed = MODEL_SEEDS[replicate_index]
                fit_started = time.perf_counter()
                reference.fit(catalogs, training, model_seed=model_seed)
                independent.fit(catalogs, training, model_seed=model_seed)
                fit_seconds = time.perf_counter() - fit_started
                replicate_differences = _new_differences()
                replicate_failures = {key: 0 for key in global_failures}
                replicate_episode_count = 0
                replicate_query_count = 0

                for slot, panel, world in panels:
                    population_seed = _derived_seed(
                        seed_row["sealed_test_root_seed"],
                        slot,
                        panel.panel_id,
                        "population",
                    )
                    panel_oracle_root = _derived_seed(
                        seed_row["sealed_test_root_seed"],
                        slot,
                        panel.panel_id,
                        "oracle",
                    )
                    for episode_index in range(
                        SPLIT_EPISODES_PER_PANEL["sealed_test"]
                    ):
                        episode = world.generate_episode(
                            WorldSplit.SEALED_TEST, population_seed, episode_index
                        )
                        episode_oracle_root = _derived_seed(
                            panel_oracle_root, episode_index
                        )
                        raw, differences, failures, query_count = _evaluate_episode(
                            reference=reference,
                            independent=independent,
                            slot=slot,
                            panel=panel,
                            world=world,
                            episode=episode,
                            replicate_id=replicate_id,
                            episode_index=episode_index,
                            oracle_root=episode_oracle_root,
                        )
                        episode_writer.write(canonical_json_bytes(raw))
                        _merge_max(replicate_differences, differences)
                        for key, value in failures.items():
                            replicate_failures[key] += value
                        replicate_episode_count += 1
                        replicate_query_count += query_count

                replicate_pair_count, pair_difference = _evaluate_pairs(
                    reference=reference,
                    independent=independent,
                    panels=panels,
                    replicate_id=replicate_id,
                    seed_root=seed_row["sealed_test_root_seed"],
                    writer=pair_writer,
                )
                replicate_differences["pair_distance_max_abs"] = pair_difference
                _merge_max(global_differences, replicate_differences)
                for key, value in replicate_failures.items():
                    global_failures[key] += value
                episode_count += replicate_episode_count
                rollout_query_count += replicate_query_count
                pair_count += replicate_pair_count
                replicate_summaries.append(
                    {
                        "replicate_id": replicate_id,
                        "model_seed": model_seed,
                        "seed_commitment": next(
                            row["commitment"]
                            for row in freeze["seed_commitments"]
                            if row["replicate_id"] == replicate_id
                        ),
                        "training_record_count": len(training),
                        "episode_count": replicate_episode_count,
                        "rollout_query_count": replicate_query_count,
                        "pair_count": replicate_pair_count,
                        "fit_seconds": fit_seconds,
                        "differences": replicate_differences,
                        "failures": replicate_failures,
                    }
                )

        expected_episode_count = (
            len(panels)
            * len(REPLICATE_IDS)
            * SPLIT_EPISODES_PER_PANEL["sealed_test"]
        )
        if episode_count != expected_episode_count:
            raise ProtocolViolation("full reproduction episode cardinality mismatch")
        exact = not any(global_differences.values()) and not any(
            global_failures.values()
        )
        report = {
            "protocol": REPRODUCTION_PROTOCOL,
            "run_id": run_id,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "freeze_root": freeze["freeze_root"],
            "source_commit": source_commit,
            "freeze_manifest_digest": digest_bytes(freeze_path.read_bytes()),
            "seed_reveal_digest": digest_bytes(reveal_path.read_bytes()),
            "seed_commitments_verified": True,
            "candidate_seal_digest": digest_bytes(seal_path.read_bytes()),
            "sealed_candidate_source_digest": seal["candidate_source_binding"][
                "source_digest"
            ],
            "implementation_independence": {
                "independent_module": "prototype/unified_map/independent_f18.py",
                "imports_candidate_families": False,
                "separate_public_history_fold": True,
                "separate_state_wire": True,
                "separate_fit_and_head_code": True,
            },
            "scope": {
                "world_slots": list(WORLD_REGISTRY),
                "world_count": len(WORLD_REGISTRY),
                "panel_count": len(panels),
                "replicate_ids": list(REPLICATE_IDS),
                "train_episodes_per_panel_per_replicate": SPLIT_EPISODES_PER_PANEL[
                    "train"
                ],
                "sealed_test_episodes_per_panel_per_replicate": SPLIT_EPISODES_PER_PANEL[
                    "sealed_test"
                ],
                "pair_probe_limit_per_declaration": PAIR_LIMIT_PER_DECLARATION,
                "pair_probe_world_slots": [
                    slot for slot in WORLD_REGISTRY if slot not in EXTENSION_WORLD_REGISTRY
                ],
                "pair_probe_excluded_extension_world_slots": list(
                    EXTENSION_WORLD_REGISTRY
                ),
                "pair_probe_scope_rule": (
                    "match benchmark_v1_runner primary-scope pair materialization; "
                    "W16/W17 S1 pairs require separate extension reveal"
                ),
            },
            "episode_count": episode_count,
            "rollout_query_count": rollout_query_count,
            "pair_count": pair_count,
            "updates_tested_per_episode": ["empty_identity", "nonempty_suffix_replay"],
            "differences": global_differences,
            "failures": global_failures,
            "exact_core_reproduction": exact,
            "replicates": replicate_summaries,
            "claim_boundary": {
                "complete_frozen_panel_replicate_query_scope": True,
                "oracle_metric_recomputation": False,
                "synthetic_only": True,
                "clinical_validity_claimed": False,
                "does_not_repair_sealed_ood_failure": True,
                "equivalence_to_sealed_f18_only": True,
            },
            "wall_seconds": time.perf_counter() - started,
        }
        summary_path = temporary / "reproduction.json"
        summary_path.write_bytes(canonical_json_bytes(report))
        episode_gzip = temporary / "raw-episodes.jsonl.gz"
        pair_gzip = temporary / "raw-pairs.jsonl.gz"
        _write_deterministic_gzip(episode_path, episode_gzip)
        _write_deterministic_gzip(pair_path, pair_gzip)

        files = []
        for path in (
            summary_path,
            episode_path,
            episode_gzip,
            pair_path,
            pair_gzip,
        ):
            raw = path.read_bytes()
            files.append(
                {
                    "name": path.name,
                    "byte_length": len(raw),
                    "sha256": digest_bytes(raw),
                }
            )
        manifest = {
            "protocol": MANIFEST_PROTOCOL,
            "run_id": run_id,
            "freeze_root": freeze["freeze_root"],
            "source_commit": source_commit,
            "files": files,
            "sources": _source_binding(root),
            "authorities": [
                {
                    "relative_path": str(path.resolve().relative_to(root)).replace(
                        "\\", "/"
                    ),
                    "byte_length": path.stat().st_size,
                    "sha256": digest_bytes(path.read_bytes()),
                }
                for path in (freeze_path, reveal_path, seal_path)
            ],
        }
        manifest["bundle_root"] = digest_json(manifest)
        (temporary / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        os.replace(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    verify_reproduction_bundle(output)
    return output


def _canonical_jsonl_count(raw: bytes, label: str, protocol: str) -> int:
    if not raw:
        raise ProtocolViolation(f"{label} is empty")
    count = 0
    for line in raw.splitlines(keepends=True):
        try:
            value = json.loads(line.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation(f"{label} contains invalid JSON") from exc
        if (
            type(value) is not dict
            or value.get("protocol") != protocol
            or canonical_json_bytes(value) != line
        ):
            raise ProtocolViolation(f"{label} contains a non-canonical row")
        count += 1
    return count


def verify_reproduction_bundle(
    path: Path, *, require_live_sources: bool = True
) -> dict[str, Any]:
    """Fail closed on canonical JSON, hashes, deterministic gzip and row counts."""

    root = _repo_root()
    manifest = _decode_canonical(path / "manifest.json", "reproduction manifest")
    if manifest.get("protocol") != MANIFEST_PROTOCOL:
        raise ProtocolViolation("reproduction manifest protocol mismatch")
    expected_root = digest_json(
        {key: value for key, value in manifest.items() if key != "bundle_root"}
    )
    if manifest.get("bundle_root") != expected_root:
        raise ProtocolViolation("reproduction bundle root mismatch")
    rows = manifest.get("files")
    if type(rows) is not list or not rows:
        raise ProtocolViolation("reproduction manifest has no files")
    by_name = {row.get("name"): row for row in rows if type(row) is dict}
    if len(by_name) != len(rows):
        raise ProtocolViolation("reproduction manifest file rows are malformed")
    for row in rows:
        if set(row) != {"name", "byte_length", "sha256"}:
            raise ProtocolViolation("reproduction manifest file row shape mismatch")
        member = path / row["name"]
        if member.is_file():
            raw = member.read_bytes()
        elif row["name"].endswith(".jsonl"):
            gzip_member = path / f"{row['name']}.gz"
            if not gzip_member.is_file():
                raise ProtocolViolation("reproduction raw member and gzip fallback missing")
            raw = gzip.decompress(gzip_member.read_bytes())
        else:
            raise ProtocolViolation("reproduction manifest member missing")
        if len(raw) != row["byte_length"] or digest_bytes(raw) != row["sha256"]:
            raise ProtocolViolation("reproduction manifest member digest mismatch")

    for raw_name in ("raw-episodes.jsonl", "raw-pairs.jsonl"):
        gzip_name = f"{raw_name}.gz"
        raw_member = path / raw_name
        gzip_member = path / gzip_name
        compressed = gzip_member.read_bytes()
        decompressed = gzip.decompress(compressed)
        if raw_member.is_file() and raw_member.read_bytes() != decompressed:
            raise ProtocolViolation("reproduction raw/gzip content mismatch")
        temporary = path / f".{gzip_name}.verify.tmp"
        try:
            temporary.write_bytes(decompressed)
            deterministic = path / f".{gzip_name}.deterministic.tmp"
            _write_deterministic_gzip(temporary, deterministic)
            if deterministic.read_bytes() != compressed:
                raise ProtocolViolation("reproduction gzip is not deterministic")
        finally:
            temporary.unlink(missing_ok=True)
            (path / f".{gzip_name}.deterministic.tmp").unlink(missing_ok=True)

    summary = _decode_canonical(path / "reproduction.json", "reproduction summary")
    if (
        summary.get("protocol") != REPRODUCTION_PROTOCOL
        or summary.get("run_id") != manifest.get("run_id")
        or summary.get("freeze_root") != manifest.get("freeze_root")
        or summary.get("source_commit") != manifest.get("source_commit")
    ):
        raise ProtocolViolation("reproduction summary binding mismatch")
    source_commit = summary.get("source_commit")
    if (
        type(source_commit) is not str
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise ProtocolViolation("reproduction source commit is malformed")
    episode_raw = gzip.decompress((path / "raw-episodes.jsonl.gz").read_bytes())
    pair_raw = gzip.decompress((path / "raw-pairs.jsonl.gz").read_bytes())
    if _canonical_jsonl_count(
        episode_raw, "episode raw", EPISODE_RAW_PROTOCOL
    ) != summary.get("episode_count"):
        raise ProtocolViolation("reproduction episode row count mismatch")
    if _canonical_jsonl_count(pair_raw, "pair raw", PAIR_RAW_PROTOCOL) != summary.get(
        "pair_count"
    ):
        raise ProtocolViolation("reproduction pair row count mismatch")
    pair_scope = summary.get("scope", {})
    expected_pair_slots = [
        slot for slot in WORLD_REGISTRY if slot not in EXTENSION_WORLD_REGISTRY
    ]
    if (
        pair_scope.get("pair_probe_world_slots") != expected_pair_slots
        or pair_scope.get("pair_probe_excluded_extension_world_slots")
        != list(EXTENSION_WORLD_REGISTRY)
    ):
        raise ProtocolViolation("reproduction pair scope mismatch")
    for line in pair_raw.splitlines():
        row = json.loads(line)
        if row.get("world_slot") in EXTENSION_WORLD_REGISTRY:
            raise ProtocolViolation("extension-world S1 pair leaked into primary REPRO5")

    if require_live_sources:
        for section in ("sources", "authorities"):
            values = manifest.get(section)
            if type(values) is not list or not values:
                raise ProtocolViolation(f"reproduction {section} binding is empty")
            for row in values:
                if set(row) != {"relative_path", "byte_length", "sha256"}:
                    raise ProtocolViolation(f"reproduction {section} row shape mismatch")
                member = root / row["relative_path"]
                raw = member.read_bytes()
                if (
                    len(raw) != row["byte_length"]
                    or digest_bytes(raw) != row["sha256"]
                ):
                    raise ProtocolViolation(f"reproduction {section} source drifted")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full independent F18 reproduction")
    parser.add_argument(
        "--seal", type=Path, default=Path("research/unified_map/CANDIDATE_SEAL.json")
    )
    parser.add_argument(
        "--freeze", type=Path, default=Path(FREEZE_FILENAME)
    )
    parser.add_argument(
        "--reveal",
        type=Path,
        default=Path("research/unified_map/BENCHMARK_V1_SEED_REVEAL.json"),
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("results/unified_map/reproduction")
    )
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify is not None:
        summary = verify_reproduction_bundle(args.verify)
        print(
            json.dumps(
                {
                    "run_id": summary["run_id"],
                    "exact_core_reproduction": summary["exact_core_reproduction"],
                },
                sort_keys=True,
            )
        )
        return 0
    print(
        reproduce(
            seal_path=args.seal,
            freeze_path=args.freeze,
            reveal_path=args.reveal,
            output_root=args.output_root,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["reproduce", "verify_reproduction_bundle"]
