from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.f18_compliance_audit import (
    run_audit,
    verify_f18_compliance_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "research/unified_map/CANDIDATE_SEAL.json"


@pytest.fixture(scope="module")
def live_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return run_audit(
        seal_path=SEAL,
        output_root=tmp_path_factory.mktemp("f18-compliance"),
        training_records=10,
    )


def test_live_f18_hard_compliance_closes_all_runtime_checks(live_bundle: Path) -> None:
    report = verify_f18_compliance_bundle(live_bundle, repo_root=ROOT)
    assert report["execution"]["actually_instantiated_and_fit"] is True
    assert report["execution"]["family_code"] == "F18"
    assert report["summary"]["all_passed"] is True
    assert report["summary"]["raw_history_head_access_count"] == 0
    assert report["summary"]["raw_history_update_access_count"] == 0
    assert report["summary"]["retained_patient_object_count"] == 0
    assert report["summary"]["payload_forbidden_key_count"] == 0
    assert report["summary"]["retained_raw_identifier_count"] == 0

    closure = [json.loads(line) for line in (live_bundle / "state-closure.jsonl").read_bytes().splitlines()]
    checks = {row["check"]: row for row in closure}
    assert checks["live_raw_visible_history_guard"]["evidence"]["positive_control_triggered"] is True
    assert checks["live_raw_visible_history_guard"]["evidence"]["head_phase_accesses"] == []
    assert checks["live_raw_visible_history_guard"]["evidence"]["update_phase_accesses"] == []
    assert checks["visible_delta_only_update_and_old_state_immutability"]["evidence"]["delta_event_count"] > 0
    assert checks["cold_rehydrate_fresh_fit_equivalence"]["passed"] is True
    assert checks["second_patient_state_isolation"]["passed"] is True
    assert checks["second_patient_state_isolation"]["evidence"]["access_trace_operations"] == [
        "diagnose_before_A_update",
        "diagnose_after_A_update",
    ]


def test_compliance_bundle_is_canonical_and_tamper_evident(
    live_bundle: Path, tmp_path: Path
) -> None:
    report = json.loads((live_bundle / "compliance.json").read_bytes())
    manifest = json.loads((live_bundle / "manifest.json").read_bytes())
    assert (live_bundle / "compliance.json").read_bytes() == canonical_json_bytes(report)
    assert (live_bundle / "manifest.json").read_bytes() == canonical_json_bytes(manifest)

    copied = tmp_path / live_bundle.name
    shutil.copytree(live_bundle, copied)
    (copied / "access-trace.jsonl").write_bytes(
        (copied / "access-trace.jsonl").read_bytes() + b"\n"
    )
    with pytest.raises(ProtocolViolation, match="binding mismatch|canonical JSONL"):
        verify_f18_compliance_bundle(copied, repo_root=ROOT)
