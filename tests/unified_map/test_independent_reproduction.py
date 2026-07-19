from __future__ import annotations

import ast
import gzip
import io
import json
import subprocess
from pathlib import Path

import numpy as np

from prototype.unified_map.benchmark_v1_contract import build_public_training_record
from prototype.unified_map.benchmark_v1_freeze import (
    verify_freeze_manifest_bytes,
    verify_seed_reveal,
)
from prototype.unified_map.candidate_families import make_candidate
from prototype.unified_map.canonical import canonical_json_bytes, digest_bytes, digest_json
from prototype.unified_map.independent_f18 import IndependentStructuralEnsemble
from prototype.unified_map.independent_reproduction import (
    _derived_seed,
    _evaluate_pairs,
    _split_history,
    _write_deterministic_gzip,
)
from prototype.unified_map.schema import VisibleDelta
from prototype.unified_map.world_registry import WORLD_REGISTRY
from prototype.unified_map.worlds.base import WorldSplit


ROOT = Path(__file__).resolve().parents[2]


def test_public_reveal_opens_freeze_and_resolves_all_panels() -> None:
    freeze = verify_freeze_manifest_bytes(
        (ROOT / "research/unified_map/BENCHMARK_V1_FREEZE.json").read_bytes()
    )
    reveal = json.loads(
        (ROOT / "research/unified_map/BENCHMARK_V1_SEED_REVEAL.json").read_bytes()
    )
    verify_seed_reveal(reveal, freeze)
    assert sum(len(entry.panels) for entry in WORLD_REGISTRY.values()) == 21
    assert [row["replicate_id"] for row in reveal["replicates"]] == [
        "R01",
        "R02",
        "R03",
        "R04",
        "R05",
    ]


def test_independent_f18_matches_reference_after_empty_and_nonempty_update() -> None:
    panel = WORLD_REGISTRY["W01"].panels[0]
    world = panel.instantiate()
    records = tuple(
        build_public_training_record(
            world,
            world.generate_episode(WorldSplit.TRAIN, 111, index),
            oracle_seed=222 + index,
        )
        for index in range(8)
    )
    reference = make_candidate("F18")
    independent = IndependentStructuralEnsemble()
    for candidate in (reference, independent):
        candidate.fit((world.catalog,), records, model_seed=104729)

    episode = world.generate_episode(WorldSplit.SEALED_TEST, 333, 0)
    prefix, delta = _split_history(episode.public_history)
    assert delta.events
    candidates = (reference, independent)
    full = tuple(
        candidate.initialize(episode.public_history, inference_seed=7)
        for candidate in candidates
    )
    prefix_states = tuple(
        candidate.initialize(prefix, inference_seed=7) for candidate in candidates
    )
    updated = tuple(
        candidate.update(state, delta, inference_seed=8)
        for candidate, state in zip(candidates, prefix_states, strict=True)
    )
    empty = tuple(
        candidate.update(
            state,
            VisibleDelta(episode.public_history.as_of_available_at, ()),
            inference_seed=8,
        )
        for candidate, state in zip(candidates, full, strict=True)
    )
    assert all(before.state_hash == after.state_hash for before, after in zip(full, empty))
    assert all(before.state_hash == after.state_hash for before, after in zip(full, updated))
    np.testing.assert_array_equal(full[0].distance_vector, full[1].distance_vector)

    diagnoses = tuple(
        candidate.diagnose(
            state, world.catalog.diagnostic_labels, query_seed=9
        ).probabilities
        for candidate, state in zip(candidates, full, strict=True)
    )
    assert diagnoses[0] == diagnoses[1]
    for horizon in world.catalog.horizons:
        for policy in world.policy_set(horizon):
            predictions = tuple(
                candidate.rollout(state, policy, horizon, query_seed=10)
                for candidate, state in zip(candidates, full, strict=True)
            )
            assert predictions[0] == predictions[1]


def test_independent_module_has_no_candidate_family_import() -> None:
    source = ROOT / "prototype/unified_map/independent_f18.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert all("candidate_families" not in name for name in imports)


def test_reproduction_gzip_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    source.write_bytes(
        canonical_json_bytes({"protocol": "row/1", "seed": _derived_seed(7, "x")})
    )
    first = tmp_path / "first.gz"
    second = tmp_path / "second.gz"
    _write_deterministic_gzip(source, first)
    _write_deterministic_gzip(source, second)
    assert first.read_bytes() == second.read_bytes()
    assert gzip.decompress(first.read_bytes()) == source.read_bytes()


def test_primary_reproduction_does_not_open_extension_world_pairs() -> None:
    """W16/W17 pair fixtures are S1-only and must not enter primary REPRO5."""

    panels = []
    for slot in ("W16", "W17"):
        panel = WORLD_REGISTRY[slot].panels[0]
        panels.append((slot, panel, panel.instantiate()))
    writer = io.BytesIO()
    pair_count, maximum = _evaluate_pairs(
        reference=object(),
        independent=object(),
        panels=panels,
        replicate_id="R01",
        seed_root=123,
        writer=writer,
    )
    assert pair_count == 0
    assert maximum == 0.0
    assert writer.getvalue() == b""


def test_failed_full_reproduction_attempt_is_bound_without_result_credit() -> None:
    path = ROOT / "research/unified_map/REPRO5_FAILED_ATTEMPT_20260719T095421Z.json"
    raw = path.read_bytes()
    receipt = json.loads(raw)
    assert raw == canonical_json_bytes(receipt)
    preimage = {key: value for key, value in receipt.items() if key != "receipt_root"}
    assert receipt["receipt_root"] == digest_json(preimage)
    assert receipt["status"] == "FAILED_UNFINALIZED"
    assert receipt["failure"]["classification"] == "HARNESS_SCOPE_MISMATCH"
    assert receipt["claim_boundary"] == {
        "benchmark_failure": False,
        "candidate_failure": False,
        "completed_bundle": False,
        "completed_replicates": 0,
        "harness_failure": True,
        "reproduction_credit": False,
    }
    for binding in receipt["source_bindings"] + receipt["authority_bindings"]:
        blob = subprocess.check_output(
            [
                "git",
                "show",
                f"{receipt['source_commit']}:{binding['relative_path']}",
            ],
            cwd=ROOT,
        )
        assert binding == {
            "relative_path": binding["relative_path"],
            "byte_length": len(blob),
            "sha256": digest_bytes(blob),
        }
    failed_output = (
        ROOT
        / "results/unified_map/reproduction"
        / receipt["run_id"]
    )
    assert not failed_output.exists()
