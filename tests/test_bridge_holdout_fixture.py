"""Integrity and replay checks for the post-seal bridge holdout corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from tests.bridge_holdout.audit_corpus_executability import audit


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "bridge_holdout" / "hidden_corpus.json"
MANIFEST = ROOT / "results" / "bridge-holdout" / "fixture-manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_fixture_manifest_sidecars_and_source_seals() -> None:
    corpus = _load(FIXTURE)
    manifest = _load(MANIFEST)

    for metadata in manifest["artifacts"].values():
        path = ROOT / metadata["path"]
        assert path.stat().st_size == metadata["bytes"]
        assert _sha256(path) == metadata["sha256"]

    for path in (
        FIXTURE,
        MANIFEST,
        ROOT / "results" / "bridge-holdout" / "reveal-seed.json",
    ):
        sidecar = path.with_suffix(path.suffix + ".sha256")
        assert sidecar.read_text(encoding="ascii").split()[0] == _sha256(path)

    source_paths = {
        "implementation_a": ROOT / "prototype" / "bridge_holdout" / "impl_a.py",
        "implementation_b": ROOT / "prototype" / "bridge_holdout" / "impl_b.py",
        "panel_a": ROOT / "prototype" / "bridge_holdout" / "panel_a.py",
        "panel_b": ROOT / "prototype" / "bridge_holdout" / "panel_b.py",
    }
    seals = corpus["implementation_seals"]
    for name, path in source_paths.items():
        assert _sha256(path) == seals[name]
    assert _sha256(ROOT / "results" / "bridge-holdout" / "freeze-manifest.json") == seals[
        "freeze_manifest"
    ]


def test_fixture_shape_and_corrected_cross_kernel_metadata() -> None:
    corpus = _load(FIXTURE)
    assert corpus["protocol_version"] == "bridge-holdout/1.0-preregistered"
    assert [case["case_id"] for case in corpus["cases"]] == [
        f"H{index:02d}" for index in range(1, 42)
    ]

    base = corpus["base"]
    roles = {root["concept"]: root["semantic_role"] for root in base["roots"]}
    assert roles[base["scm"]["treatment_concept"]] == "performed_intervention"
    assert roles[base["scm"]["outcome_concept"]] == "observed_outcome"

    versions = base["cut"]["version_vector"]["model_by_kernel"]
    assert versions == {
        "finite_dbn": base["dbn"]["model_version"],
        "finite_scm": base["scm"]["model_version"],
    }


def test_generator_exact_byte_replay(tmp_path: Path) -> None:
    corpus = _load(FIXTURE)
    generation = corpus["generation"]
    seals = corpus["implementation_seals"]
    output = tmp_path / FIXTURE.name

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tests" / "bridge_holdout" / "generate_hidden_corpus.py"),
            "--seed-hex",
            generation["seed_hex"],
            "--output",
            str(output),
            "--seal-a",
            seals["implementation_a"],
            "--seal-b",
            seals["implementation_b"],
            "--seal-panel-a",
            seals["panel_a"],
            "--seal-panel-b",
            seals["panel_b"],
            "--freeze-manifest-sha256",
            seals["freeze_manifest"],
            "--git-commit",
            seals["git_commit"],
            "--reveal-time",
            generation["generated_at"],
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert output.read_bytes() == FIXTURE.read_bytes()
    assert output.with_suffix(output.suffix + ".sha256").read_bytes() == FIXTURE.with_suffix(
        FIXTURE.suffix + ".sha256"
    ).read_bytes()
    assert output.with_name("COVERAGE.md").read_bytes() == FIXTURE.with_name("COVERAGE.md").read_bytes()


def test_corpus_executability_gaps_are_explicit() -> None:
    result = audit(_load(FIXTURE))
    assert result["concrete_base_cases"] == ["H01", "H02", "H08", "H16"]
    assert result["dangling_queries"] == {
        "H09": ["smooth_t1"],
        "H20": ["condition_t0", "do_t1"],
        "H21": ["aap_do_t0_given_factual_t1_y1"],
    }
    assert len(result["descriptor_only_cases"]) == 35
