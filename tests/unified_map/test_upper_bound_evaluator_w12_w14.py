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
from prototype.unified_map.upper_bound_evaluator_w12 import (
    DEFAULT_W12_SOURCE,
    run_w12_upper_bound_sanity,
    verify_w12_upper_bound_sanity,
    w12_upper_bound_artifact_bytes,
)
from prototype.unified_map.upper_bound_evaluator_w13 import (
    DEFAULT_W13_SOURCE,
    run_w13_upper_bound_sanity,
    verify_w13_upper_bound_sanity,
    w13_upper_bound_artifact_bytes,
)
from prototype.unified_map.upper_bound_evaluator_w14 import (
    DEFAULT_W14_SOURCE,
    run_w14_upper_bound_sanity,
    verify_w14_upper_bound_sanity,
    w14_upper_bound_artifact_bytes,
)


@dataclass(frozen=True)
class _Adapter:
    source: Path
    adapter_source: Path
    run: Callable[..., dict]
    verify: Callable[..., None]
    artifact_bytes: Callable[..., bytes]


ADAPTERS = {
    "W12": _Adapter(
        DEFAULT_W12_SOURCE,
        Path("prototype/unified_map/upper_bound_evaluator_w12.py"),
        run_w12_upper_bound_sanity,
        verify_w12_upper_bound_sanity,
        w12_upper_bound_artifact_bytes,
    ),
    "W13": _Adapter(
        DEFAULT_W13_SOURCE,
        Path("prototype/unified_map/upper_bound_evaluator_w13.py"),
        run_w13_upper_bound_sanity,
        verify_w13_upper_bound_sanity,
        w13_upper_bound_artifact_bytes,
    ),
    "W14": _Adapter(
        DEFAULT_W14_SOURCE,
        Path("prototype/unified_map/upper_bound_evaluator_w14.py"),
        run_w14_upper_bound_sanity,
        verify_w14_upper_bound_sanity,
        w14_upper_bound_artifact_bytes,
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
def test_adapters_are_zero_credit_pre_freeze_and_close_shared_state_cells(
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
    assert bundle["verification_summary"]["reference_kind"] == ("expected_utility_only")
    assert bundle["bundle_root"] == compute_upper_bound_bundle_root(bundle)
    assert bundle["cell_set_root"] == _cell_root(bundle["cells"])

    state = bundle["states"]["initial"]
    state_hash = state["record"]["state_hash"]
    assert (
        state["record"]["model_digest"]
        == bundle["evaluator_source_closure"]["closure_root"]
    )
    assert all(cell["state_hash"] == state_hash for cell in bundle["cells"])
    assert {cell["cell_id"] for cell in bundle["cells"]} == {
        f"{world_slot}.initial.public_diagnosis",
        f"{world_slot}.initial.natural_forecast",
        f"{world_slot}.initial.intervention",
    }
    representation = state["payload"]["representation"]
    assert set(representation) == {
        "protocol",
        "world_slot",
        "as_of_available_at",
        "public_history",
    }
    state_bytes = canonical_json_bytes(representation)
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
def test_evaluator_source_closure_binds_adapter_generic_helper_and_world(
    world_slot: str, bundles: dict[str, dict]
) -> None:
    adapter = ADAPTERS[world_slot]
    closure = bundles[world_slot]["evaluator_source_closure"]
    assert closure["protocol"] == "ucm-upper-bound-evaluator-source-closure/1"
    assert closure["closure_root"] == digest_json(
        {"protocol": closure["protocol"], "files": closure["files"]}
    )
    by_path = {row["relpath"]: row for row in closure["files"]}
    expected = {
        adapter.source.as_posix(): "world_source",
        adapter.adapter_source.as_posix(): "adapter_entrypoint",
        "prototype/unified_map/upper_bound_evaluator_w03.py": "shared_evaluator",
        "prototype/unified_map/upper_bound_evaluator_w09.py": ("additional_dependency"),
    }
    assert set(by_path) == set(expected)
    for relpath, role in expected.items():
        assert role in by_path[relpath]["roles"]
        assert by_path[relpath]["bytes"] == Path(relpath).stat().st_size
        assert by_path[relpath]["digest"].startswith("sha256:")
        attestation = by_path[relpath]["runtime_attestation"]
        assert attestation["attested_digest"] == by_path[relpath]["digest"]
        assert attestation["mode"] == (
            "exact-world-source-byte-compile"
            if by_path[relpath]["roles"] == ["world_source"]
            else "import-time-source-digest-match"
        )


def test_w12_live_cells_separate_expression_mechanism_and_host_future(
    bundles: dict[str, dict],
) -> None:
    certificate = bundles["W12"]["world_semantic_certificate"]
    cells = {cell["cell_id"]: cell for cell in certificate["live_behavior_cells"]}
    expression = cells["W12.same_expression.host_state"]
    mechanism = cells["W12.same_mechanism.different_host_future"]
    equivalent = cells["W12.alpha_rename.equivalent"]

    assert certificate["source_limitations"][0] == (
        "reference-is-expected-utility-only-and-source-separation-not-certified"
    )

    assert expression["shared_routine_expression"] == pytest.approx(0.6)
    assert expression["public_host_markers"] == pytest.approx([0.6, 1.4])
    assert (
        expression["public_direct_mechanism_values"][0]
        != (expression["public_direct_mechanism_values"][1])
    )
    assert expression["all_policy_outputs_distinct"] is True
    assert mechanism["shared_public_direct_mechanism"] == pytest.approx(0.72)
    assert (
        mechanism["maximum_natural_latent_mean_drift"]
        <= (mechanism["latent_mean_absolute_tolerance"])
    )
    assert (
        mechanism["no_action_observed_expression_means"][0]
        != (mechanism["no_action_observed_expression_means"][1])
    )
    assert (
        mechanism["a1_host_dependent_latent_means"][0]
        != (mechanism["a1_host_dependent_latent_means"][1])
    )
    assert equivalent["history_digests_differ"] is True
    assert equivalent["all_policy_outputs_byte_identical"] is True


def test_w13_live_cells_exercise_nonlinear_threshold_not_a_smoke_wrapper(
    bundles: dict[str, dict],
) -> None:
    certificate = bundles["W13"]["world_semantic_certificate"]
    cells = {cell["cell_id"]: cell for cell in certificate["live_behavior_cells"]}
    threshold = cells["W13.threshold_pair.nonlinear_transition"]
    interaction = cells["W13.same_components.interaction_class"]
    equivalent = cells["W13.alpha_rename.equivalent"]

    assert certificate["source_limitations"][0] == (
        "reference-is-expected-utility-only-and-source-separation-not-certified"
    )

    assert threshold["shared_routine_total"] == pytest.approx(1.3)
    assert threshold["public_interaction_values"][0] == 0.0
    assert threshold["public_interaction_values"][1] > 0.0
    assert threshold["nonlinear_transition_residuals"][0] == [0.0, 0.0]
    assert min(threshold["nonlinear_transition_residuals"][1]) > 0.0
    assert (
        threshold["no_action_expected_utilities"][0]
        != (threshold["no_action_expected_utilities"][1])
    )
    assert threshold["all_policy_outputs_distinct"] is True
    assert interaction["shared_public_components"] == pytest.approx([0.75, 0.65])
    assert interaction["public_interaction_values"][0] > 0.0
    assert interaction["public_interaction_values"][1] < 0.0
    assert interaction["all_policy_outputs_distinct"] is True
    assert equivalent["history_digests_differ"] is True
    assert equivalent["all_policy_outputs_byte_identical"] is True


def test_w14_live_cells_prove_path_memory_and_finite_state_closure(
    bundles: dict[str, dict],
) -> None:
    certificate = bundles["W14"]["world_semantic_certificate"]
    cells = {cell["cell_id"]: cell for cell in certificate["live_behavior_cells"]}
    collision = cells["W14.same_current.different_path_memory"]
    convergent = cells["W14.different_paths.same_finite_state"]
    equivalent = cells["W14.alpha_rename.equivalent"]

    assert certificate["source_limitations"][0] == (
        "reference-is-expected-utility-only-and-source-separation-not-certified"
    )

    assert (
        collision["latest_observation_values"][0]
        == (collision["latest_observation_values"][1])
    )
    assert collision["latest_observation_only_collides"] is True
    assert (
        collision["public_finite_state_values"][0][0]
        == (collision["public_finite_state_values"][1][0])
    )
    assert (
        collision["public_finite_state_values"][0][1]
        != (collision["public_finite_state_values"][1][1])
    )
    assert collision["best_policy_differs"] is True
    assert collision["best_policy_indices"][0] != collision["best_policy_indices"][1]
    assert collision["history_deletion_changes_behavioral_state"] is True
    assert convergent["history_digests_differ"] is True
    assert convergent["all_policy_outputs_byte_identical"] is True
    assert (
        convergent["left_policy_output_roots"]
        == (convergent["right_policy_output_roots"])
    )
    assert equivalent["all_policy_outputs_byte_identical"] is True


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_resigned_forged_world_source_anchor_is_rejected(
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
def test_resigned_adapter_and_shared_dependency_digest_tamper_is_rejected(
    world_slot: str, bundles: dict[str, dict]
) -> None:
    relpaths = (
        "prototype/unified_map/upper_bound_evaluator_w03.py",
        "prototype/unified_map/upper_bound_evaluator_w09.py",
        ADAPTERS[world_slot].adapter_source.as_posix(),
    )
    for relpath in relpaths:
        tampered = deepcopy(bundles[world_slot])
        closure = tampered["evaluator_source_closure"]
        dependency = next(row for row in closure["files"] if row["relpath"] == relpath)
        dependency["digest"] = "sha256:" + "f" * 64
        closure["closure_root"] = digest_json(
            {"protocol": closure["protocol"], "files": closure["files"]}
        )
        _resign(tampered)
        with pytest.raises(ProtocolViolation, match="source dependency closure"):
            ADAPTERS[world_slot].verify(tampered, replay_runtime=True)

    if world_slot == "W12":
        # W09 supplies the imported certificate helper.  Verification must
        # attest its live bytes before executing that stale helper code.
        helper = Path("prototype/unified_map/upper_bound_evaluator_w09.py")
        original = helper.read_bytes()
        try:
            helper.write_bytes(original + b"\n# post-import-source-drift\n")
            with pytest.raises(
                ProtocolViolation,
                match="loaded evaluator source differs from live bytes",
            ):
                verify_w12_upper_bound_sanity(bundles["W12"], replay_runtime=True)
        finally:
            helper.write_bytes(original)


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
    copied = tmp_path / "w14.py"
    copied.write_bytes(DEFAULT_W14_SOURCE.read_bytes())
    verify_w14_upper_bound_sanity(
        bundles["W14"], source_artifact=copied, replay_runtime=True
    )


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_resigned_live_semantic_cell_tamper_fails_reconstruction(
    world_slot: str, bundles: dict[str, dict]
) -> None:
    tampered = deepcopy(bundles[world_slot])
    tampered["world_semantic_certificate"]["live_behavior_cells"][0]["passed"] = False
    _resign(tampered)
    with pytest.raises(ProtocolViolation, match="not the live replay"):
        ADAPTERS[world_slot].verify(tampered, replay_runtime=True)


def test_resigned_quantization_consistent_cell_tamper_fails_live_reconstruction(
    bundles: dict[str, dict],
) -> None:
    tampered = deepcopy(bundles["W13"])
    diagnosis = next(cell for cell in tampered["cells"] if "diagnosis" in cell["task"])
    projection = diagnosis["candidate_head"]["result"]["quantized_projection"]
    projection["raw_values"][0] += 1e-6
    projection["raw_digest"] = digest_json(projection["raw_values"])
    projection["integer_values"] = [
        int(round(value / projection["scale"])) for value in projection["raw_values"]
    ]
    _resign(tampered)
    with pytest.raises(ProtocolViolation):
        verify_w13_upper_bound_sanity(tampered, replay_runtime=True)


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_canonical_artifact_bytes_are_deterministic(
    world_slot: str, bundles: dict[str, dict]
) -> None:
    assert ADAPTERS[world_slot].artifact_bytes() == canonical_json_bytes(
        bundles[world_slot]
    )
