from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.postseal_candidate_set import (
    build_candidate_set_seal,
    verify_candidate_set_seal_bytes,
)


ROOT = Path(__file__).resolve().parents[2]


def test_build_and_verify_candidate_set_against_committed_blob() -> None:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    seal = build_candidate_set_seal(
        source_commit=commit,
        source_paths=["prototype/unified_map/candidate_families.py"],
        subjects=[{"family_code": "F18", "role": "ucm_redteam_subject"}],
        repo_root=ROOT,
    )
    assert verify_candidate_set_seal_bytes(canonical_json_bytes(seal), repo_root=ROOT) == seal


def test_candidate_set_rejects_noncanonical_or_uncommitted_source() -> None:
    with pytest.raises(ProtocolViolation):
        verify_candidate_set_seal_bytes(b"{}\n\n", repo_root=ROOT)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    with pytest.raises(ProtocolViolation, match="unavailable"):
        build_candidate_set_seal(
            source_commit=commit,
            source_paths=["prototype/unified_map/not-present.py"],
            subjects=[],
            repo_root=ROOT,
        )
