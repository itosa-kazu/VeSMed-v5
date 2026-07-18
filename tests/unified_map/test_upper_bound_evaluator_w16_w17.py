from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from prototype.unified_map.upper_bound_evaluator import (
    _cell_root,
    compute_upper_bound_bundle_root,
)
from prototype.unified_map.upper_bound_evaluator_w16 import (
    DEFAULT_W16_ARTIFACT,
    run_w16_upper_bound_sanity,
    verify_w16_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w17 import (
    DEFAULT_W17_ARTIFACT,
    run_w17_upper_bound_sanity,
    verify_w17_upper_bound_sanity,
)
from prototype.unified_map.worlds.w16 import W16World


def _resign(report: dict, *, cells_changed: bool = False) -> dict:
    result = deepcopy(report)
    if cells_changed:
        result["cell_set_root"] = _cell_root(result["cells"])
    result["bundle_root"] = compute_upper_bound_bundle_root(result)
    return result


def test_w16_live_reveal_locally_refines_one_primary_state() -> None:
    report = run_w16_upper_bound_sanity()
    verify_w16_upper_bound_sanity(report)

    assert report["status_chain"]["benchmark_status"] == "PRE-FREEZE"
    assert report["status_chain"]["eligibility"] == "upper_bound_only"
    assert report["verification_summary"]["ledger_credit"] == 0
    assert report["verification_summary"]["ucm_eligible"] is False
    assert report["verification_summary"]["formal_scope_authority"] is False
    assert (
        "formal-11-axis-S-prime-scope-manifest-not-materialized"
        in report["verification_summary"]["formalization_blockers"]
    )

    primary = report["states"]["primary_shared"]["record"]
    assert all(
        state["record"]["model_digest"] == report["source_closure"]["closure_root"]
        for state in report["states"].values()
    )
    assert (
        report["source_closure"]["arbitrary_preloaded_module_staleness_closed"] is False
    )
    assert (
        "source-runtime-attestation-requires-fresh-process-import"
        in report["verification_summary"]["formalization_blockers"]
    )
    negative = report["states"]["refined_q2_result_0"]["record"]
    positive = report["states"]["refined_q2_result_1"]["record"]
    assert (
        negative["parent_state_hash"]
        == positive["parent_state_hash"]
        == primary["state_hash"]
    )
    assert negative["state_hash"] != positive["state_hash"]
    assert negative["operation"] == positive["operation"] == "update"
    assert report["cells"][0]["same_primary_state"] is True
    assert report["cells"][0]["public_histories_byte_identical"] is True
    assert primary["catalog_digest"] == W16World().catalog.digest
    assert all(
        row["shared_oracle"]["outcome_distribution"]["scope"] == "S0"
        for row in report["cells"][0]["primary_policy_behaviour"]
    )
    assert [cell["class_posterior"]["C1"] for cell in report["cells"][1:]] == [
        0.05,
        0.95,
    ]
    assert all(
        cell["live_behaviour"]["comparison"]["passed"] is True
        and cell["history_replay_used_for_state_update"] is False
        and cell["full_history_replay_used_as_reference_only"] is True
        and cell["local_update_matches_full_replay_reference"] is True
        for cell in report["cells"][1:]
    )
    assert (
        report["verification_summary"]["post_seal_reveal_chronology_claimed"] is False
    )


def test_w17_same_primary_behaviour_is_split_by_revealed_a2() -> None:
    report = run_w17_upper_bound_sanity()
    verify_w17_upper_bound_sanity(report)

    primary = report["states"]["primary_shared"]["record"]
    assert all(
        state["record"]["model_digest"] == report["source_closure"]["closure_root"]
        for state in report["states"].values()
    )
    marker_one = report["states"]["refined_marker_1"]["record"]
    marker_zero = report["states"]["refined_marker_0"]["record"]
    assert (
        marker_one["parent_state_hash"]
        == marker_zero["parent_state_hash"]
        == primary["state_hash"]
    )
    assert marker_one["state_hash"] != marker_zero["state_hash"]
    assert marker_one["operation"] == marker_zero["operation"] == "replay"
    assert report["cells"][0]["same_primary_state"] is True
    assert report["cells"][0]["public_histories_differ"] is True
    assert [cell["a2_effect_direction"] for cell in report["cells"][1:]] == [
        "down",
        "up",
    ]
    assert [cell["a2_preferred_on_panel"] for cell in report["cells"][1:]] == [
        True,
        False,
    ]
    assert all(
        cell["candidate_first_query_executed"] is False
        and cell["required_honest_state_only_status"] == "scope_insufficient"
        and cell["explicit_history_replay_required"] is True
        for cell in report["cells"][1:]
    )
    assert report["verification_summary"]["ucm_eligible"] is False
    assert report["verification_summary"]["formal_scope_authority"] is False
    assert (
        report["verification_summary"]["post_seal_reveal_chronology_claimed"] is False
    )


@pytest.mark.parametrize(
    ("run", "verify"),
    (
        (run_w16_upper_bound_sanity, verify_w16_upper_bound_sanity),
        (run_w17_upper_bound_sanity, verify_w17_upper_bound_sanity),
    ),
)
def test_extension_reports_are_canonical_json_roundtrippable(run, verify) -> None:
    report = run()
    raw = canonical_json_bytes(report)
    decoded = json.loads(raw.decode("utf-8"))
    assert canonical_json_bytes(decoded) == raw
    verify(decoded)


@pytest.mark.parametrize(
    "run",
    (run_w16_upper_bound_sanity, run_w17_upper_bound_sanity),
)
def test_randomized_custody_is_normalized_to_a_deterministic_pack_source(run) -> None:
    first = run()
    second = run()
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert (
        first["extension_source"]["randomized_commitment_material_persisted"] is False
    )


@pytest.mark.parametrize(
    ("run", "verify"),
    (
        (run_w16_upper_bound_sanity, verify_w16_upper_bound_sanity),
        (run_w17_upper_bound_sanity, verify_w17_upper_bound_sanity),
    ),
)
def test_resigned_formal_scope_authority_escalation_is_rejected(run, verify) -> None:
    report = run()
    report["scope_boundary"]["revealed_extension"]["formal_scope_authority"] = True
    report["scope_boundary"]["revealed_extension"][
        "formal_scope_manifest_materialized"
    ] = True
    report["scope_boundary"][
        "legacy_ad_hoc_extension_scope_digest_accepted_as_formal"
    ] = True
    report["verification_summary"]["formal_scope_authority"] = True
    forged = _resign(report)
    with pytest.raises(ProtocolViolation, match="scope|summary|authority"):
        verify(forged)


def test_w16_resigned_posterior_tamper_is_rejected_by_live_replay() -> None:
    report = run_w16_upper_bound_sanity()
    report["cells"][1]["class_posterior"] = {"C0": 0.5, "C1": 0.5}
    forged = _resign(report, cells_changed=True)
    with pytest.raises(ProtocolViolation, match="live extension behaviour"):
        verify_w16_upper_bound_sanity(forged)


def test_w17_resigned_treatment_direction_tamper_is_rejected_by_live_replay() -> None:
    report = run_w17_upper_bound_sanity()
    report["cells"][1]["a2_effect_direction"] = "up"
    report["cells"][1]["a2_preferred_on_panel"] = False
    forged = _resign(report, cells_changed=True)
    with pytest.raises(ProtocolViolation, match="live extension behaviour"):
        verify_w17_upper_bound_sanity(forged)


@pytest.mark.parametrize(
    ("run", "verify"),
    (
        (run_w16_upper_bound_sanity, verify_w16_upper_bound_sanity),
        (run_w17_upper_bound_sanity, verify_w17_upper_bound_sanity),
    ),
)
def test_resigned_source_digest_tamper_is_rejected_against_exact_bytes(
    run, verify
) -> None:
    report = run()
    report["source_anchor"]["artifact_digest"] = digest_bytes(b"forged source")
    report["source_anchor"]["replay_digest"] = report["source_anchor"][
        "artifact_digest"
    ]
    forged = _resign(report)
    with pytest.raises(ProtocolViolation, match="exact canonical source bytes"):
        verify(forged)


@pytest.mark.parametrize(
    ("run", "verify"),
    (
        (run_w16_upper_bound_sanity, verify_w16_upper_bound_sanity),
        (run_w17_upper_bound_sanity, verify_w17_upper_bound_sanity),
    ),
)
def test_resigned_dependency_closure_tamper_is_rejected(run, verify) -> None:
    report = run()
    report["source_closure"]["members"][-1]["digest"] = digest_bytes(
        b"forged dependency"
    )
    report["source_closure"]["closure_root"] = digest_json(
        {
            "protocol": report["source_closure"]["protocol"],
            "members": report["source_closure"]["members"],
        }
    )
    forged = _resign(report)
    with pytest.raises(ProtocolViolation, match="source closure"):
        verify(forged)


@pytest.mark.parametrize(
    ("run", "verify"),
    (
        (run_w16_upper_bound_sanity, verify_w16_upper_bound_sanity),
        (run_w17_upper_bound_sanity, verify_w17_upper_bound_sanity),
    ),
)
def test_resigned_state_model_digest_detached_from_source_closure_is_rejected(
    run, verify
) -> None:
    report = run()
    report["states"]["primary_shared"]["record"]["model_digest"] = digest_bytes(
        b"detached model"
    )
    forged = _resign(report)
    with pytest.raises(ProtocolViolation, match="state|model|live reconstruction"):
        verify(forged)


@pytest.mark.parametrize(
    "relative",
    (
        "prototype/unified_map/upper_bound_evaluator_w16.py",
        "prototype/unified_map/worlds/w16.py",
        "prototype/unified_map/extensions.py",
    ),
)
def test_post_import_wrapper_world_or_helper_change_fails_closed(
    relative: str,
) -> None:
    report = run_w16_upper_bound_sanity()
    path = Path(relative)
    original = path.read_bytes()
    changed = original + b"\n# post-import-attestation-tamper\n"
    try:
        path.write_bytes(changed)
        changed_digest = digest_bytes(changed)
        for member in report["source_closure"]["members"]:
            if member["relpath"] == relative:
                member["byte_count"] = len(changed)
                member["digest"] = changed_digest
                member["loaded_source_digest"] = changed_digest
                member["live_matches_loaded_source"] = True
                break
        else:  # pragma: no cover - closed path list makes this unreachable
            raise AssertionError("tampered source is outside closure")
        report["source_closure"]["closure_root"] = digest_json(
            {
                "protocol": report["source_closure"]["protocol"],
                "members": report["source_closure"]["members"],
            }
        )
        if relative == DEFAULT_W16_ARTIFACT.as_posix():
            report["source_anchor"].update(
                {
                    "artifact_digest": changed_digest,
                    "artifact_bytes": len(changed),
                    "replay_digest": changed_digest,
                }
            )
        forged = _resign(report)
        with pytest.raises(ProtocolViolation, match="changed after import"):
            verify_w16_upper_bound_sanity(forged)
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize(
    ("run", "source"),
    (
        (run_w16_upper_bound_sanity, DEFAULT_W16_ARTIFACT),
        (run_w17_upper_bound_sanity, DEFAULT_W17_ARTIFACT),
    ),
)
def test_nonidentical_source_copy_cannot_be_substituted(
    tmp_path: Path, run, source: Path
) -> None:
    original = Path(source).read_bytes()
    tampered = tmp_path / source.name
    tampered.write_bytes(original + b"\n# tampered\n")
    with pytest.raises(ProtocolViolation, match="byte-identical"):
        run(source_artifact=tampered)


@pytest.mark.parametrize(
    ("run", "verify"),
    (
        (run_w16_upper_bound_sanity, verify_w16_upper_bound_sanity),
        (run_w17_upper_bound_sanity, verify_w17_upper_bound_sanity),
    ),
)
def test_resigned_revealed_operator_tamper_cannot_open_commitment(run, verify) -> None:
    report = run()
    operator = report["extension_source"]["revealed_pack"]["operator"]
    operator["cost"] = float(operator["cost"]) + 0.01
    forged_pack = canonical_json_bytes(report["extension_source"]["revealed_pack"])
    report["extension_source"]["revealed_pack_bytes_hex"] = forged_pack.hex()
    report["extension_source"]["revealed_pack_digest"] = digest_bytes(forged_pack)
    forged = _resign(report)
    with pytest.raises(ProtocolViolation, match="open|commitment|opaque|pack"):
        verify(forged)


@pytest.mark.parametrize(
    ("run", "verify"),
    (
        (run_w16_upper_bound_sanity, verify_w16_upper_bound_sanity),
        (run_w17_upper_bound_sanity, verify_w17_upper_bound_sanity),
    ),
)
def test_resigned_noncanonical_hex_spelling_is_rejected(run, verify) -> None:
    report = run()
    report["extension_source"]["revealed_pack_bytes_hex"] = report["extension_source"][
        "revealed_pack_bytes_hex"
    ].upper()
    forged = _resign(report)
    with pytest.raises(ProtocolViolation, match="pack byte binding"):
        verify(forged)
