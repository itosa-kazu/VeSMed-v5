from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from prototype.unified_map.benchmark_v1_authority import load_seed_authority
from prototype.unified_map.benchmark_v1_freeze import (
    SEED_REVEAL_SCHEMA,
    SEED_SECRET_SCHEMA,
    build_freeze_manifest,
    build_seed_reveal,
    new_seed_secret,
)
from prototype.unified_map.benchmark_v1_runner import verify_run_bundle
from prototype.unified_map.candidate_seal import verify_candidate_seal
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "research/unified_map/BENCHMARK_V1_FREEZE.json"
REVEAL = ROOT / "research/unified_map/BENCHMARK_V1_SEED_REVEAL.json"
SEAL = ROOT / "research/unified_map/CANDIDATE_SEAL.json"

SCREENING_RUNS_012_032 = tuple(
    path
    for path in sorted((ROOT / "results/unified_map/runs").iterdir())
    if path.is_dir()
    and any(f"-EXP-{index:03d}-" in path.name for index in range(12, 33))
)


def _write(path: Path, value: dict) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _change_digest(value: str) -> str:
    final = "0" if value[-1] != "0" else "1"
    return value[:-1] + final


def test_seed_authority_accepts_private_secret_and_public_reveal(tmp_path: Path) -> None:
    secret = new_seed_secret()
    freeze = build_freeze_manifest(secret)
    reveal = build_seed_reveal(secret, freeze)
    freeze_path = tmp_path / "freeze.json"
    secret_path = tmp_path / "secret.json"
    reveal_path = tmp_path / "reveal.json"
    _write(freeze_path, freeze)
    _write(secret_path, secret)
    _write(reveal_path, reveal)

    private_freeze, private_execution, private_provenance = load_seed_authority(
        freeze_path, secret_path
    )
    public_freeze, public_execution, public_provenance = load_seed_authority(
        freeze_path, reveal_path
    )

    assert private_freeze == public_freeze == freeze
    assert private_execution == public_execution == secret
    assert private_provenance == {
        "authority_kind": "private_seed_secret",
        "authority_schema_version": SEED_SECRET_SCHEMA,
        "seed_preimages_published": False,
    }
    assert public_provenance == {
        "authority_kind": "public_seed_reveal",
        "authority_schema_version": SEED_REVEAL_SCHEMA,
        "seed_preimages_published": True,
    }


def test_seed_authority_rejects_nonopening_or_relabelled_reveal(tmp_path: Path) -> None:
    secret = new_seed_secret()
    freeze = build_freeze_manifest(secret)
    reveal = build_seed_reveal(secret, freeze)
    freeze_path = tmp_path / "freeze.json"
    authority_path = tmp_path / "authority.json"
    _write(freeze_path, freeze)

    changed_seed = copy.deepcopy(reveal)
    changed_seed["replicates"][0]["sealed_test_root_seed"] ^= 1
    _write(authority_path, changed_seed)
    with pytest.raises(ProtocolViolation, match="does not open"):
        load_seed_authority(freeze_path, authority_path)

    relabelled = copy.deepcopy(reveal)
    relabelled["schema_version"] = SEED_SECRET_SCHEMA
    _write(authority_path, relabelled)
    with pytest.raises(ProtocolViolation, match="missing or extra fields"):
        load_seed_authority(freeze_path, authority_path)


def test_published_seed_reveal_opens_the_live_freeze() -> None:
    freeze, execution, provenance = load_seed_authority(FREEZE, REVEAL)
    assert freeze["freeze_root"] == json.loads(SEAL.read_text())["freeze_root"]
    assert [row["replicate_id"] for row in execution["replicates"]] == [
        "R01",
        "R02",
        "R03",
        "R04",
        "R05",
    ]
    assert provenance["seed_preimages_published"] is True


def test_candidate_seal_rebuilds_live_and_derived_authorities() -> None:
    seal = verify_candidate_seal(SEAL, repo_root=ROOT)
    assert seal["candidate_source_binding"]["source_digest"] == digest_json(
        seal["candidate_source_binding"]["files"]
    )
    assert seal["complete_run"]["replicate_ids"] == [
        "R01",
        "R02",
        "R03",
        "R04",
        "R05",
    ]


@pytest.mark.parametrize(
    "mutation",
    (
        "source_aggregate",
        "freeze_root",
        "cross_seed",
        "hard_failure",
        "replicate_id",
        "eligibility",
    ),
)
def test_candidate_seal_rejects_single_field_relabelling(
    tmp_path: Path, mutation: str
) -> None:
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    if mutation == "source_aggregate":
        binding = seal["candidate_source_binding"]
        binding["source_digest"] = _change_digest(binding["source_digest"])
    elif mutation == "freeze_root":
        seal["freeze_root"] = _change_digest(seal["freeze_root"])
    elif mutation == "cross_seed":
        metric = seal["complete_run"]["cross_seed_summary"]["diagnosis_top1_accuracy"]
        metric["seed_count"] = 4
    elif mutation == "hard_failure":
        seal["complete_run"]["hard_failures"]["unsafe_forced_known_ood"] = 4
    elif mutation == "replicate_id":
        seal["complete_run"]["replicate_ids"][4] = "R04"
    else:
        seal["selection_disposition"]["ucm_eligible"] = True
    path = tmp_path / "seal.json"
    _write(path, seal)
    with pytest.raises(ProtocolViolation):
        verify_candidate_seal(path, repo_root=ROOT)


def test_exp012_through_exp032_bundles_and_source_aggregates_reverify() -> None:
    assert len(SCREENING_RUNS_012_032) == 21
    for expected_index, directory in enumerate(SCREENING_RUNS_012_032, start=12):
        summary = verify_run_bundle(directory)
        assert summary["config"]["experiment_id"] == f"EXP-{expected_index:03d}"
        binding = summary["source_binding"]
        assert binding["source_digest"] == digest_json(binding["files"])
        assert len({row["relative_path"] for row in binding["files"]}) == len(
            binding["files"]
        )
        for row in binding["files"]:
            assert set(row) == {"relative_path", "byte_length", "sha256"}
            assert type(row["relative_path"]) is str and row["relative_path"]
            assert type(row["byte_length"]) is int and row["byte_length"] >= 0
            assert type(row["sha256"]) is str and len(row["sha256"]) == 71


def test_all_published_reports_bind_the_exact_candidate_seal_digest() -> None:
    expected = digest_bytes(SEAL.read_bytes())
    reports: list[Path] = []
    for root_name, filename in (
        ("redteam", "redteam.json"),
        ("reproduction", "reproduction.json"),
        ("demo", "demo.json"),
    ):
        reports.extend((ROOT / "results/unified_map" / root_name).glob(f"*/{filename}"))
    bound = 0
    for path in reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        if "candidate_seal_digest" in report:
            bound += 1
            assert report["candidate_seal_digest"] == expected, path
    assert bound >= 3


def test_legacy_singular_source_manifest_field_is_not_skipped() -> None:
    """The first red-team schema used ``source``, not ``sources``."""

    checked = 0
    for manifest_path in (
        ROOT / "results/unified_map/redteam"
    ).glob("*/manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if "source" not in manifest:
            continue
        checked += 1
        row = manifest["source"]
        assert set(row) == {"relative_path", "byte_length", "sha256"}
        raw = (ROOT / row["relative_path"]).read_bytes()
        assert len(raw) == row["byte_length"]
        assert digest_bytes(raw) == row["sha256"]
    assert checked >= 1
