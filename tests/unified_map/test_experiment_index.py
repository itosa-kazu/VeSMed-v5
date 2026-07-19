from __future__ import annotations

import copy
from pathlib import Path

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.experiment_index import (
    INDEX_FILENAME,
    INDEX_PROTOCOL,
    verify_experiment_index,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _reseal(value: dict) -> dict:
    result = copy.deepcopy(value)
    result["index_root"] = digest_json(
        {key: item for key, item in result.items() if key != "index_root"}
    )
    return result


def _write(path: Path, value: dict) -> Path:
    path.write_bytes(canonical_json_bytes(value))
    return path


def _gap_entry(ordinal: int) -> dict:
    return {
        "count_eligible": False,
        "decision": "not_decidable_without_run",
        "digests": None,
        "evidence_gaps": ["no_authoritative_run_bundle"],
        "evidence_status": "evidence_gap",
        "experiment_id": f"EXP-{ordinal:03d}",
        "family": "UNRUN",
        "ordinal": ordinal,
        "role": "unexecuted_record",
        "run_id": None,
        "run_path": None,
        "substantive_change_class": "architecture",
    }


def _accounting(experiments: list[dict]) -> dict:
    from collections import Counter

    return {
        "count_eligible": sum(row["count_eligible"] for row in experiments),
        "count_ineligible": sum(not row["count_eligible"] for row in experiments),
        "evidence_gap_count": sum(
            row["evidence_status"] == "evidence_gap" for row in experiments
        ),
        "last_experiment_id": experiments[-1]["experiment_id"],
        "role_counts": dict(sorted(Counter(row["role"] for row in experiments).items())),
        "substantive_change_class_counts": dict(
            sorted(
                Counter(
                    row["substantive_change_class"] for row in experiments
                ).items()
            )
        ),
        "total_experiments": len(experiments),
    }


def test_canonical_index_replays_all_retained_runs_and_conservative_count() -> None:
    value = verify_experiment_index(REPO_ROOT / INDEX_FILENAME, repo_root=REPO_ROOT)
    assert value["protocol"] == INDEX_PROTOCOL
    assert len(value["experiments"]) >= 36
    first_36 = value["experiments"][:36]
    assert [row["experiment_id"] for row in first_36] == [
        f"EXP-{ordinal:03d}" for ordinal in range(1, 37)
    ]
    assert sum(row["count_eligible"] for row in first_36) == 29
    assert {
        row["experiment_id"]
        for row in first_36
        if not row["count_eligible"]
    } == {
        "EXP-009",
        "EXP-010",
        "EXP-011",
        "EXP-033",
        "EXP-034",
        "EXP-035",
        "EXP-036",
    }
    assert all(row["evidence_status"] == "bound_run_bundle" for row in first_36)


def test_resealed_forged_accounting_is_rejected(tmp_path: Path) -> None:
    value = verify_experiment_index(REPO_ROOT / INDEX_FILENAME, repo_root=REPO_ROOT)
    forged = copy.deepcopy(value)
    forged["accounting"]["count_eligible"] += 1
    path = _write(tmp_path / "index.json", _reseal(forged))
    with pytest.raises(ProtocolViolation, match="accounting mismatch"):
        verify_experiment_index(path, repo_root=REPO_ROOT)


def test_resealed_run_digest_substitution_is_rejected(tmp_path: Path) -> None:
    value = verify_experiment_index(REPO_ROOT / INDEX_FILENAME, repo_root=REPO_ROOT)
    forged = copy.deepcopy(value)
    forged["experiments"][0]["digests"]["config"] = "sha256:" + "0" * 64
    path = _write(tmp_path / "index.json", _reseal(forged))
    with pytest.raises(ProtocolViolation, match="config digest mismatch"):
        verify_experiment_index(path, repo_root=REPO_ROOT)


def test_resealed_duplicate_run_path_is_rejected(tmp_path: Path) -> None:
    value = verify_experiment_index(REPO_ROOT / INDEX_FILENAME, repo_root=REPO_ROOT)
    forged = copy.deepcopy(value)
    forged["experiments"][1]["run_path"] = forged["experiments"][0]["run_path"]
    path = _write(tmp_path / "index.json", _reseal(forged))
    with pytest.raises(ProtocolViolation, match="canonical run location"):
        verify_experiment_index(path, repo_root=REPO_ROOT)


def test_explicit_evidence_gap_does_not_invent_or_count_a_run(tmp_path: Path) -> None:
    experiments = [_gap_entry(1)]
    body = {
        "accounting": _accounting(experiments),
        "experiments": experiments,
        "freeze_root": "sha256:" + "1" * 64,
        "protocol": INDEX_PROTOCOL,
    }
    path = _write(tmp_path / "gap.json", {**body, "index_root": digest_json(body)})
    value = verify_experiment_index(path, repo_root=tmp_path)
    assert value["accounting"] == {
        "count_eligible": 0,
        "count_ineligible": 1,
        "evidence_gap_count": 1,
        "last_experiment_id": "EXP-001",
        "role_counts": {"unexecuted_record": 1},
        "substantive_change_class_counts": {"architecture": 1},
        "total_experiments": 1,
    }


def test_future_experiment_ids_can_be_appended_as_explicit_gaps(tmp_path: Path) -> None:
    value = verify_experiment_index(REPO_ROOT / INDEX_FILENAME, repo_root=REPO_ROOT)
    extended = copy.deepcopy(value)
    next_ordinal = len(extended["experiments"]) + 1
    extended["experiments"].append(_gap_entry(next_ordinal))
    extended["accounting"] = _accounting(extended["experiments"])
    path = _write(tmp_path / "extended.json", _reseal(extended))
    verified = verify_experiment_index(path, repo_root=REPO_ROOT)
    assert verified["accounting"]["last_experiment_id"] == f"EXP-{next_ordinal:03d}"


def test_noncanonical_index_bytes_are_rejected(tmp_path: Path) -> None:
    value = verify_experiment_index(REPO_ROOT / INDEX_FILENAME, repo_root=REPO_ROOT)
    path = tmp_path / "pretty.json"
    import json

    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    with pytest.raises(ProtocolViolation, match="not canonical JSON"):
        verify_experiment_index(path, repo_root=REPO_ROOT)
