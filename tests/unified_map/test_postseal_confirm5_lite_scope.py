from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.postseal_confirm5_lite_scope import (
    PROTOCOL,
    build_lite_scope,
    verify_lite_scope_bytes,
)


ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "research/unified_map/POSTSEAL_CONFIRM5_LITE_SCOPE.json"
BATCH = ROOT / (
    "results/unified_map/postseal_confirm5_lite_t4_s2_p0/"
    "20260719T090636Z-POSTSEAL-CONFIRM5-25eeeb5ec6"
)


def test_published_confirm5_lite_scope_matches_streaming_custody() -> None:
    scope = verify_lite_scope_bytes(SCOPE.read_bytes(), repo_root=ROOT)
    assert scope == build_lite_scope(batch_dir=BATCH, repo_root=ROOT)
    assert scope["protocol"] == PROTOCOL
    assert scope["scope_class"] == "supplemental_all_world_lite"
    assert scope["complete_benchmark"] is False
    assert scope["no_pair_collision_evidence"] is True
    assert scope["execution_disclosure"] == {
        "finalized_batch_count_for_pack": 1,
        "machine_reverified_from_finalized_batch": False,
        "prior_unfinalized_execution_attempt": True,
        "private_seed_material_loaded_by_prior_attempt": True,
    }
    assert scope["batch_binding"]["gzip_only_verified"] is True
    assert scope["batch_binding"]["config"]["pair_probe_limit_per_declaration"] == 0
    assert len(scope["confirm_source_binding"]["files"]) == 5
    assert scope["full_candidate_set_live_verifier"]["status"] == (
        "SUPERSEDED_ONLY_FOR_REDTEAM_EVALUATOR_SOURCES"
    )
    assert (
        scope["full_candidate_set_live_verifier"][
            "confirm_scope_requires_evaluator_supersession"
        ]
        is False
    )


def test_confirm5_lite_scope_rejects_tampered_root_and_batch_binding() -> None:
    scope = json.loads(SCOPE.read_bytes())
    scope["scope_root"] = "sha256:" + ("0" * 64)
    with pytest.raises(ProtocolViolation, match="scope root mismatch"):
        verify_lite_scope_bytes(canonical_json_bytes(scope), repo_root=ROOT)

    scope = json.loads(SCOPE.read_bytes())
    scope["batch_binding"]["config"]["test_episodes_per_panel"] = 3
    preimage = {key: item for key, item in scope.items() if key != "scope_root"}
    scope["scope_root"] = digest_json(preimage)
    with pytest.raises(ProtocolViolation, match="no longer matches live custody"):
        verify_lite_scope_bytes(canonical_json_bytes(scope), repo_root=ROOT)
