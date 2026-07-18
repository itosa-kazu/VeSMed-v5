from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)
from prototype.unified_map.upper_bound_evaluator import (
    _cell_root,
    compute_upper_bound_bundle_root,
)
from prototype.unified_map.upper_bound_evaluator_w03 import (
    DEFAULT_W03_SOURCE,
    run_w03_upper_bound_sanity,
    verify_w03_upper_bound_sanity,
    w03_upper_bound_artifact_bytes,
)
from prototype.unified_map.upper_bound_evaluator_w05 import (
    DEFAULT_W05_SOURCE,
    run_w05_upper_bound_sanity,
    verify_w05_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w06 import (
    DEFAULT_W06_SOURCE,
    run_w06_upper_bound_sanity,
    verify_w06_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w07 import (
    DEFAULT_W07_SOURCE,
    run_w07_upper_bound_sanity,
    verify_w07_upper_bound_sanity,
)
from prototype.unified_map.worlds.w03 import W03World


@dataclass(frozen=True)
class _Adapter:
    source: Path
    run: Callable[..., dict]
    verify: Callable[..., None]


ADAPTERS = {
    "W03": _Adapter(
        DEFAULT_W03_SOURCE, run_w03_upper_bound_sanity, verify_w03_upper_bound_sanity
    ),
    "W05": _Adapter(
        DEFAULT_W05_SOURCE, run_w05_upper_bound_sanity, verify_w05_upper_bound_sanity
    ),
    "W06": _Adapter(
        DEFAULT_W06_SOURCE, run_w06_upper_bound_sanity, verify_w06_upper_bound_sanity
    ),
    "W07": _Adapter(
        DEFAULT_W07_SOURCE, run_w07_upper_bound_sanity, verify_w07_upper_bound_sanity
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
def test_live_adapters_bind_one_public_state_and_keep_zero_credit(
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
    assert bundle["verification_summary"]["state_binding_count"] == 1
    assert bundle["bundle_root"] == compute_upper_bound_bundle_root(bundle)
    assert bundle["cell_set_root"] == _cell_root(bundle["cells"])

    state = bundle["states"]["initial"]
    closure = bundle["evaluator_source_closure"]
    assert closure["closure_root"] == digest_json(
        {"protocol": closure["protocol"], "files": closure["files"]}
    )
    assert state["record"]["model_digest"] == closure["closure_root"]
    paths = {row["relpath"]: row["roles"] for row in closure["files"]}
    assert adapter.source.as_posix() in paths
    assert "prototype/unified_map/upper_bound_evaluator_w03.py" in paths
    expected_adapter = (
        f"prototype/unified_map/upper_bound_evaluator_{world_slot.lower()}.py"
    )
    assert expected_adapter in paths
    for row in closure["files"]:
        attestation = row["runtime_attestation"]
        assert attestation["attested_digest"] == row["digest"]
        assert attestation["mode"] == (
            "exact-world-source-byte-compile"
            if row["roles"] == ["world_source"]
            else "import-time-source-digest-match"
        )
    state_hash = state["record"]["state_hash"]
    assert all(cell["state_hash"] == state_hash for cell in bundle["cells"])
    assert set(state["payload"]["representation"]) == {
        "protocol",
        "world_slot",
        "as_of_available_at",
        "public_history",
    }
    state_bytes = canonical_json_bytes(state["payload"]["representation"])
    for forbidden in (
        b"hidden_state_at_cut",
        b"invariant_parameters",
        b"diagnostic_target",
        b"factual_future",
        b"action_propensities",
        b"oracle_anchor",
    ):
        assert forbidden not in state_bytes


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_public_oracle_outputs_are_private_swap_invariant(
    world_slot: str, bundles: dict[str, dict]
) -> None:
    proof = bundles[world_slot]["candidate_visibility_proof"]
    assert proof["private_inputs_distinct"] is True
    assert proof["realized_target_changed"] is True
    assert proof["independent_world_instances"] is True
    assert proof["all_policy_outputs_byte_identical"] is True
    assert proof["policy_output_roots"] == proof["private_swap_output_roots"]
    assert (
        len(proof["policy_output_roots"])
        == bundles[world_slot]["verification_summary"]["policy_count"]
    )

    diagnosis = next(
        cell for cell in bundles[world_slot]["cells"] if "diagnosis" in cell["task"]
    )
    assert diagnosis["oracle_target"]["role"] == (
        "public_posterior_not_realized_true_class"
    )
    assert (
        bundles[world_slot]["scope_statement"]["realized_true_class_score_claimed"]
        is False
    )


@pytest.mark.parametrize(
    ("world_slot", "reference_kind"),
    (
        ("W03", "full_oracle"),
        ("W05", "full_oracle"),
        ("W06", "expected_utility_only"),
        ("W07", "expected_utility_only"),
    ),
)
def test_reference_capability_boundary_is_explicit(
    world_slot: str, reference_kind: str, bundles: dict[str, dict]
) -> None:
    bundle = bundles[world_slot]
    assert bundle["verification_summary"]["reference_kind"] == reference_kind
    intervention = next(
        cell for cell in bundle["cells"] if cell["task"] == "intervention_public_oracle"
    )
    assert intervention["metric"]["worst_regret"] == 0.0
    for evidence in intervention["reference_evidence"].values():
        assert evidence["kind"] == reference_kind
        assert evidence["source_distinct"] is False
        assert evidence["source_separation_certified"] is False
        if reference_kind == "full_oracle":
            assert evidence["comparison"]["passed"] is True
        else:
            assert evidence["passed"] is True
            assert evidence["absolute_error"] <= evidence["absolute_tolerance"]
    blocker = "reference-output-is-utility-only"
    assert (blocker in bundle["verification_summary"]["formalization_blockers"]) == (
        reference_kind == "expected_utility_only"
    )
    assert (
        "source-separation-certification-not-embedded"
        in bundle["verification_summary"]["formalization_blockers"]
    )
    assert bundle["scope_statement"]["source_distinct_full_reference_claimed"] is False
    assert (
        bundle["scope_statement"]["source_distinct_utility_reference_claimed"] is False
    )


def test_canonical_artifact_api_is_deterministic(bundles: dict[str, dict]) -> None:
    assert w03_upper_bound_artifact_bytes() == canonical_json_bytes(bundles["W03"])


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


def test_supplied_source_must_equal_repository_owned_bytes(
    tmp_path: Path, bundles: dict[str, dict]
) -> None:
    forged = tmp_path / "w03.py"
    raw = DEFAULT_W03_SOURCE.read_bytes()
    forged.write_bytes(raw + b"\n# forged-byte-drift\n")
    with pytest.raises(ProtocolViolation):
        verify_w03_upper_bound_sanity(
            bundles["W03"], source_artifact=forged, replay_runtime=True
        )


def test_exact_source_copy_is_accepted(
    tmp_path: Path, bundles: dict[str, dict]
) -> None:
    copied = tmp_path / "w07.py"
    copied.write_bytes(DEFAULT_W07_SOURCE.read_bytes())
    verify_w07_upper_bound_sanity(
        bundles["W07"], source_artifact=copied, replay_runtime=True
    )


def test_exact_world_bytes_not_stale_import_drive_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stale_import(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("stale imported class must not drive exact replay")

    monkeypatch.setattr(W03World, "counterfactual", stale_import)
    bundle = run_w03_upper_bound_sanity()
    assert bundle["world_slot"] == "W03"


def test_resigned_quantization_consistent_value_tamper_fails_live_reconstruction(
    bundles: dict[str, dict],
) -> None:
    tampered = deepcopy(bundles["W06"])
    diagnosis = next(cell for cell in tampered["cells"] if "diagnosis" in cell["task"])
    projection = diagnosis["candidate_head"]["result"]["quantized_projection"]
    projection["raw_values"][0] += 1e-6
    projection["raw_digest"] = digest_json(projection["raw_values"])
    projection["integer_values"] = [
        int(round(value / projection["scale"])) for value in projection["raw_values"]
    ]
    _resign(tampered)

    with pytest.raises(ProtocolViolation, match="exact live reconstruction"):
        verify_w06_upper_bound_sanity(tampered, replay_runtime=True)


def test_resigned_quantization_integer_tamper_fails_closed(
    bundles: dict[str, dict],
) -> None:
    tampered = deepcopy(bundles["W05"])
    intervention = next(
        cell
        for cell in tampered["cells"]
        if cell["task"] == "intervention_public_oracle"
    )
    intervention["utility_projection"]["integer_values"][0] += 1
    _resign(tampered)
    with pytest.raises(ProtocolViolation, match="integer projection mismatch"):
        verify_w05_upper_bound_sanity(tampered, replay_runtime=True)


def test_resigned_state_or_head_rebinding_is_rejected(bundles: dict[str, dict]) -> None:
    state_tamper = deepcopy(bundles["W03"])
    state_tamper["states"]["initial"]["payload"]["representation"]["world_slot"] = "W99"
    _resign(state_tamper)
    with pytest.raises(ProtocolViolation):
        verify_w03_upper_bound_sanity(state_tamper, replay_runtime=True)

    head_tamper = deepcopy(bundles["W07"])
    head_tamper["cells"][0]["state_hash"] = "sha256:" + "1" * 64
    _resign(head_tamper)
    with pytest.raises(ProtocolViolation, match="shared state"):
        verify_w07_upper_bound_sanity(head_tamper, replay_runtime=True)


@pytest.mark.parametrize("mutation", ("digest", "path"))
def test_resigned_shared_generic_dependency_tamper_is_rejected(
    mutation: str, bundles: dict[str, dict]
) -> None:
    tampered = deepcopy(bundles["W05"])
    closure = tampered["evaluator_source_closure"]
    generic = next(
        row
        for row in closure["files"]
        if row["relpath"] == "prototype/unified_map/upper_bound_evaluator_w03.py"
    )
    if mutation == "digest":
        generic["digest"] = "sha256:" + "a" * 64
    else:
        generic["relpath"] = "prototype/unified_map/forged_generic.py"
    closure["closure_root"] = digest_json(
        {"protocol": closure["protocol"], "files": closure["files"]}
    )
    _resign(tampered)
    with pytest.raises(ProtocolViolation, match="source dependency closure mismatch"):
        verify_w05_upper_bound_sanity(tampered, replay_runtime=True)

    # The on-disk closure must never bind fresh bytes to already-imported code.
    # Exercise both the shared evaluator and an adapter wrapper without leaving
    # the repository mutated if the assertion itself fails.
    drift_path, drift_verify, drift_bundle = (
        (
            Path("prototype/unified_map/upper_bound_evaluator_w03.py"),
            verify_w05_upper_bound_sanity,
            bundles["W05"],
        )
        if mutation == "digest"
        else (
            Path("prototype/unified_map/upper_bound_evaluator_w06.py"),
            verify_w06_upper_bound_sanity,
            bundles["W06"],
        )
    )
    original = drift_path.read_bytes()
    try:
        drift_path.write_bytes(original + b"\n# post-import-source-drift\n")
        with pytest.raises(
            ProtocolViolation, match="loaded evaluator source differs from live bytes"
        ):
            drift_verify(drift_bundle, replay_runtime=True)
    finally:
        drift_path.write_bytes(original)
