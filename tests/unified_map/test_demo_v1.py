from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.demo_v1 import verify_demo_bundle


ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "20260719T073939Z-DEMO-956e6ca844"
DEMO = ROOT / "results/unified_map/demo" / RUN_ID


def _load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def test_current_demo_is_canonical_and_verifies_live_sources() -> None:
    report = verify_demo_bundle(DEMO, repo_root=ROOT)
    manifest = _load(DEMO / "manifest.json")

    assert (DEMO / "manifest.json").read_bytes() == canonical_json_bytes(manifest)
    assert (DEMO / "demo.json").read_bytes() == canonical_json_bytes(report)
    assert not (DEMO / "manifest.json").read_bytes().endswith(b"\n\n")
    assert not (DEMO / "demo.json").read_bytes().endswith(b"\n\n")

    bound = {
        "protocol": manifest["protocol"],
        "run_id": manifest["run_id"],
        "files": manifest["files"],
        "sources": manifest["sources"],
    }
    assert manifest["bundle_root"] == digest_json(bound)
    for field, replacement in (
        ("protocol", "changed-protocol"),
        ("run_id", "changed-run"),
        ("files", []),
        ("sources", []),
    ):
        mutated = dict(bound)
        mutated[field] = replacement
        assert digest_json(mutated) != manifest["bundle_root"]


def test_demo_fans_out_diagnosis_noop_and_three_treatments_then_updates() -> None:
    report = verify_demo_bundle(DEMO, repo_root=ROOT)
    loop = report["closed_loop"]
    expected_heads = {
        "diagnosis",
        "no_new_treatment",
        "treatment_A",
        "treatment_B",
        "treatment_C",
    }
    for phase in ("before", "after"):
        head_hashes = loop[phase]["head_input_state_hashes"]
        assert set(head_hashes) == expected_heads
        assert len(set(head_hashes.values())) == 1
        assert loop[phase]["all_heads_same_state"] is True

    delta = loop["realized_public_delta"]
    assert delta["performed_action_event_count"] == 1
    assert delta["observation_event_count"] >= 1
    assert loop["update"]["actual_candidate_update_call"] is True
    assert loop["update"]["nonempty_action_and_observation_delta"] is True
    assert loop["update"]["state_changed"] is True
    assert loop["update"]["input_state_hash"] != loop["update"]["output_state_hash"]

    insufficiency = report["ood_or_insufficient_information"]
    assert insufficiency["map_admitted_unknown"] is True
    assert insufficiency["boundary"]["sealed_full_benchmark_unsafe_forced_known_ood"] == 5
    assert insufficiency["boundary"]["example_is_not_aggregate_validation"] is True
    assert report["claim_boundary"]["clinical_validity_claimed"] is False
    assert report["claim_boundary"]["production_safety_claimed"] is False


def test_demo_verifier_rejects_noncanonical_double_lf(tmp_path: Path) -> None:
    copied = tmp_path / RUN_ID
    shutil.copytree(DEMO, copied)
    demo_path = copied / "demo.json"
    demo_path.write_bytes(demo_path.read_bytes() + b"\n")
    with pytest.raises(ProtocolViolation, match="binding mismatch|not canonical"):
        verify_demo_bundle(copied, repo_root=ROOT)
