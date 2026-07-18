from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

import prototype.unified_map.upper_bound_evaluator_w09 as evaluator_w09
import prototype.unified_map.upper_bound_evaluator_w10 as evaluator_w10
import prototype.unified_map.upper_bound_evaluator_w11 as evaluator_w11
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.upper_bound_evaluator import (
    _cell_root,
    compute_upper_bound_bundle_root,
)
from prototype.unified_map.upper_bound_evaluator_w09 import (
    DEFAULT_W09_SOURCE,
    run_w09_upper_bound_sanity,
    verify_w09_upper_bound_sanity,
    w09_upper_bound_artifact_bytes,
)
from prototype.unified_map.upper_bound_evaluator_w10 import (
    DEFAULT_W10_SOURCE,
    run_w10_upper_bound_sanity,
    verify_w10_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w11 import (
    DEFAULT_W11_SOURCE,
    run_w11_upper_bound_sanity,
    verify_w11_upper_bound_sanity,
)


@dataclass(frozen=True)
class _Adapter:
    source: Path
    run: Callable[..., dict]
    verify: Callable[..., None]


ADAPTERS = {
    "W09": _Adapter(
        DEFAULT_W09_SOURCE, run_w09_upper_bound_sanity, verify_w09_upper_bound_sanity
    ),
    "W10": _Adapter(
        DEFAULT_W10_SOURCE, run_w10_upper_bound_sanity, verify_w10_upper_bound_sanity
    ),
    "W11": _Adapter(
        DEFAULT_W11_SOURCE, run_w11_upper_bound_sanity, verify_w11_upper_bound_sanity
    ),
}


@pytest.fixture(scope="module")
def bundles() -> dict[str, dict]:
    return {slot: adapter.run() for slot, adapter in ADAPTERS.items()}


def _resign(bundle: dict) -> dict:
    bundle["cell_set_root"] = _cell_root(bundle["cells"])
    bundle["bundle_root"] = compute_upper_bound_bundle_root(bundle)
    return bundle


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_live_adapters_are_ineligible_pre_freeze_and_state_bound(
    world_slot: str, bundles: dict[str, dict]
) -> None:
    adapter = ADAPTERS[world_slot]
    bundle = bundles[world_slot]
    adapter.verify(bundle, source_artifact=adapter.source, replay_runtime=True)

    assert bundle["protocol"] == "ucm-pre-freeze-upper-bound-sanity/1"
    assert bundle["world_slot"] == world_slot
    assert bundle["ucm_eligible"] is False
    assert bundle["status_chain"] == {
        "analysis_weight": 0.0,
        "benchmark_freeze_evidence": False,
        "benchmark_status": "PRE-FREEZE",
        "candidate_eligible": False,
        "candidate_gate": "NOT_APPLICABLE",
        "eligibility": "upper_bound_only",
        "experiment_status": "NOT_COUNT_ELIGIBLE",
        "formal_run": False,
        "freeze_grade": False,
        "ledger_credit": 0,
        "privileged": True,
    }
    assert bundle["freeze_authority"] == {
        "claimed": False,
        "authorized_frozen": False,
        "issuer": None,
    }
    assert bundle["verification_summary"]["ledger_credit"] == 0
    assert bundle["bundle_root"] == compute_upper_bound_bundle_root(bundle)
    assert bundle["cell_set_root"] == _cell_root(bundle["cells"])
    state = bundle["states"]["initial"]
    state_hash = state["record"]["state_hash"]
    assert all(cell["state_hash"] == state_hash for cell in bundle["cells"])
    assert bundle["source_anchor"] == {
        "artifact_relpath": adapter.source.as_posix(),
        "artifact_digest": bundle["source_anchor"]["artifact_digest"],
        "artifact_bytes": adapter.source.stat().st_size,
        "artifact_protocol": "ucm-world-python-source/1",
        "replay_digest": bundle["source_anchor"]["artifact_digest"],
        "byte_identical_replay": True,
    }


def test_w09_baseline_certificate_preserves_public_context_boundary(
    bundles: dict[str, dict],
) -> None:
    certificate = bundles["W09"]["world_semantic_certificate"]
    collision = certificate["same_absolute_different_baseline"]
    assert collision["absolute_series"]
    assert len(set(collision["absolute_series"])) == 1
    assert (
        collision["baseline_measurements"][0] != collision["baseline_measurements"][1]
    )
    assert collision["best_policy_differs"] is True
    assert collision["best_policy_indices"][0] != collision["best_policy_indices"][1]
    assert certificate["joint_translation"]["passed"] is True
    assert certificate["private_decomposition_invariance"]["passed"] is True
    assert certificate["alpha_rename_invariance"]["passed"] is True


def test_w10_joint_covariance_prevents_repeated_evidence_false_precision(
    bundles: dict[str, dict],
) -> None:
    certificate = bundles["W10"]["world_semantic_certificate"]
    contract = certificate["joint_likelihood_contract"]
    grouping = certificate["same_values_different_grouping"]
    nullspace = certificate["posterior_equivalent_nullspace"]

    assert contract["shared_mechanism"] is True
    assert contract["covariance_source"] == "live-same-specimen-panel-oracle"
    assert contract["same_specimen_shared_disturbance_variance"] > 0.0
    assert contract["per_assay_sensor_variance"] > 0.0
    assert contract["iid_channel_product_likelihood_claimed"] is False
    assert contract["grouped_assay_count"] == 3
    assert contract["grouped_specimen_evidence_units"] == 1
    assert contract["effective_sample_size_claimed"] is False
    assert grouping["grouped_specimen_count"] == 1
    assert grouping["independent_specimen_count"] == 3
    assert grouping["all_grouped_variances_larger"] is True
    assert all(value > 0.0 for value in grouping["grouped_minus_independent_variance"])
    assert nullspace["passed"] is True
    assert nullspace["maximum_absolute_component_difference"] <= 1e-12


def test_w11_certificate_keeps_modes_and_resolves_them_with_public_contrast(
    bundles: dict[str, dict],
) -> None:
    certificate = bundles["W11"]["world_semantic_certificate"]
    ambiguous = certificate["sum_only_multimodal_posterior"]
    pair = certificate["public_contrast_distinguishable_pair"]
    equivalent = certificate["alpha_rename_equivalent_pair"]

    assert ambiguous["q1_present"] is False
    assert ambiguous["passed"] is True
    assert min(ambiguous["posterior"]) >= 0.05
    assert pair["obs_1_values"][0] == -pair["obs_1_values"][1]
    assert pair["posterior_mode_indices"] == [0, 1]
    assert pair["posterior_modes_differ"] is True
    assert pair["best_policy_differs"] is True
    assert pair["best_policy_indices"][0] != pair["best_policy_indices"][1]
    assert equivalent["history_digests_differ"] is True
    assert equivalent["all_policy_outputs_byte_identical"] is True
    assert (
        equivalent["left_policy_output_roots"]
        == equivalent["right_policy_output_roots"]
    )


@pytest.mark.parametrize(
    ("world_slot", "required_members"),
    (
        (
            "W09",
            {
                "prototype/unified_map/upper_bound_evaluator_w09.py",
                "prototype/unified_map/upper_bound_evaluator_w03.py",
                "prototype/unified_map/worlds/w09.py",
            },
        ),
        (
            "W10",
            {
                "prototype/unified_map/upper_bound_evaluator_w10.py",
                "prototype/unified_map/upper_bound_evaluator_w09.py",
                "prototype/unified_map/upper_bound_evaluator_w03.py",
                "prototype/unified_map/worlds/w10.py",
            },
        ),
        (
            "W11",
            {
                "prototype/unified_map/upper_bound_evaluator_w11.py",
                "prototype/unified_map/upper_bound_evaluator_w09.py",
                "prototype/unified_map/upper_bound_evaluator_w03.py",
                "prototype/unified_map/worlds/w11.py",
            },
        ),
    ),
)
def test_evaluator_source_closure_binds_wrapper_generic_helper_and_world(
    world_slot: str, required_members: set[str], bundles: dict[str, dict]
) -> None:
    bundle = bundles[world_slot]
    closure = bundle["evaluator_source_closure"]
    assert closure["protocol"] == "ucm-upper-bound-evaluator-source-closure/1"
    assert {row["relpath"] for row in closure["files"]} == required_members
    assert closure["closure_root"] == digest_json(
        {"protocol": closure["protocol"], "files": closure["files"]}
    )
    assert (
        bundle["states"]["initial"]["record"]["model_digest"] == closure["closure_root"]
    )
    for row in closure["files"]:
        attestation = row["runtime_attestation"]
        assert attestation["attested_digest"] == row["digest"]
        assert attestation["mode"] == (
            "exact-world-source-byte-compile"
            if row["roles"] == ["world_source"]
            else "import-time-source-digest-match"
        )


def test_semantic_certificates_ignore_stale_imported_world_classes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StaleWorld:
        def __init__(self) -> None:
            raise AssertionError("ordinary imported world class must not execute")

    monkeypatch.setattr(evaluator_w09, "World09", _StaleWorld)
    monkeypatch.setattr(evaluator_w10, "World10", _StaleWorld)
    monkeypatch.setattr(evaluator_w11, "World11", _StaleWorld)
    assert (
        evaluator_w09._w09_semantic_certificate()["formal_benchmark_claimed"] is False
    )
    assert (
        evaluator_w10._w10_semantic_certificate()["formal_benchmark_claimed"] is False
    )
    assert (
        evaluator_w11._w11_semantic_certificate()["formal_benchmark_claimed"] is False
    )


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_resigned_forged_source_anchor_is_rejected(
    world_slot: str, bundles: dict[str, dict]
) -> None:
    tampered = deepcopy(bundles[world_slot])
    tampered["source_anchor"].update(
        {
            "artifact_relpath": "forged/world.py",
            "artifact_digest": "sha256:" + "0" * 64,
            "artifact_bytes": 1,
        }
    )
    _resign(tampered)
    with pytest.raises(ProtocolViolation):
        ADAPTERS[world_slot].verify(tampered, replay_runtime=True)


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_supplied_source_must_equal_repository_owned_bytes(
    world_slot: str, tmp_path: Path, bundles: dict[str, dict]
) -> None:
    adapter = ADAPTERS[world_slot]
    forged = tmp_path / f"{world_slot.lower()}.py"
    forged.write_bytes(adapter.source.read_bytes() + b"\n# forged-byte-drift\n")
    with pytest.raises(ProtocolViolation):
        adapter.verify(bundles[world_slot], source_artifact=forged, replay_runtime=True)


def test_exact_source_copy_is_accepted(
    tmp_path: Path, bundles: dict[str, dict]
) -> None:
    copied = tmp_path / "w11.py"
    copied.write_bytes(DEFAULT_W11_SOURCE.read_bytes())
    verify_w11_upper_bound_sanity(
        bundles["W11"], source_artifact=copied, replay_runtime=True
    )


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_resigned_certificate_tamper_fails_live_reconstruction(
    world_slot: str, bundles: dict[str, dict]
) -> None:
    tampered = deepcopy(bundles[world_slot])
    tampered["world_semantic_certificate"]["formal_benchmark_claimed"] = True
    _resign(tampered)
    with pytest.raises(ProtocolViolation):
        ADAPTERS[world_slot].verify(tampered, replay_runtime=True)


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_resigned_shared_generic_digest_tamper_fails_live_rehash(
    world_slot: str, bundles: dict[str, dict]
) -> None:
    tampered = deepcopy(bundles[world_slot])
    closure = tampered["evaluator_source_closure"]
    generic = next(
        row
        for row in closure["files"]
        if row["relpath"].endswith("upper_bound_evaluator_w03.py")
    )
    generic["digest"] = "sha256:" + "f" * 64
    closure["closure_root"] = digest_json(
        {"protocol": closure["protocol"], "files": closure["files"]}
    )
    _resign(tampered)
    with pytest.raises(ProtocolViolation):
        ADAPTERS[world_slot].verify(tampered, replay_runtime=True)


def test_canonical_artifact_bytes_are_deterministic(bundles: dict[str, dict]) -> None:
    assert w09_upper_bound_artifact_bytes() == canonical_json_bytes(bundles["W09"])
