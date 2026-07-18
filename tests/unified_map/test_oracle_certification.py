from __future__ import annotations

import re

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.freeze import FreezeStatus, build_freeze_manifest
from prototype.unified_map.oracle_certification import (
    REASON_OUTPUT_MISMATCH,
    REASON_PRIVATE_SWAP_DEPENDENCE,
    REASON_RUNTIME_IMPLEMENTATION_SHARED,
    NumericTolerance,
    OracleProbe,
    PathTolerance,
    PrivateSwapProbe,
    SourceSeparationPolicy,
    certify_oracle_pair,
    compare_canonical_outputs,
)
from prototype.unified_map.schema import (
    ActionPlan,
    CandidateVisibleEvent,
    EventKind,
    PlanKind,
    VisibleHistory,
)
from prototype.unified_map.worlds.base import (
    ChannelSpec,
    CounterfactualOracle,
    PrivateEpisode,
    PublicCatalog,
    WorldSplit,
)
from prototype.unified_map.worlds import base as world_base


CATALOG = PublicCatalog(
    observations=(ChannelSpec("obs", valid_range=(-10.0, 10.0)),),
    actions=(),
    checks=(),
    diagnostic_labels=("C0", "C1"),
    horizons=(2,),
)
PLAN = ActionPlan(PlanKind.NO_NEW_ACTION)


def test_default_source_policy_waives_only_the_exact_stdlib_regex_compiler() -> None:
    policy = SourceSeparationPolicy()

    assert ("re", "_compile") in policy.allowed_shared_frames
    assert policy.module_is_neutral("re") is False
    assert ("re", "sub") not in policy.allowed_shared_frames


# A malicious benchmark author could otherwise hide one substantive solver in
# a broadly whitelisted project-owned plumbing module.  Define such a helper in
# the real ``worlds.base`` globals so the runtime frame genuinely carries that
# module identity; the certification policy must still reject it.
exec(
    compile(
        """
def _oracle_certification_malicious_shared_base(episode, policy, horizon, oracle_seed):
    del oracle_seed
    value = float(episode.public_history.events[-1].payload['value'])
    prediction = value + 0.25 * horizon
    return CounterfactualOracle(
        policy=policy,
        horizon=horizon,
        observation_distribution={'family': 'point', 'mean': prediction},
        latent_distribution={'family': 'point', 'mean': prediction},
        outcome_distribution={'family': 'point', 'expected_utility': -prediction},
        expected_utility=-prediction,
        numerical_diagnostics={'method': 'hidden-shared-base-core'},
    )
""",
        "<ucm-malicious-shared-base>",
        "exec",
    ),
    world_base.__dict__,
)
_SHARED_BASE_CORE = world_base._oracle_certification_malicious_shared_base


def _episode(*, private_bias: float, uid: str = "public-observation") -> PrivateEpisode:
    history = VisibleHistory(
        events=(
            CandidateVisibleEvent(
                kind=EventKind.OBSERVATION_AVAILABLE,
                occurred_at=0,
                available_at=0,
                event_uid=uid,
                payload={"channel_id": "obs", "value": 1.25},
                collected_at=0,
            ),
        ),
        as_of_available_at=0,
        catalog_digest=CATALOG.digest,
    )
    return PrivateEpisode(
        case_key=f"judge-private-{private_bias}",
        environment_key="judge-world",
        split=WorldSplit.SEALED_TEST,
        generator_seed=17 + int(private_bias),
        public_history=history,
        hidden_state_at_cut={"private_bias": private_bias},
        invariant_parameters={"private_class": int(private_bias > 0.0)},
        diagnostic_target={"C0": float(private_bias == 0.0), "C1": float(private_bias != 0.0)},
        factual_future=[{"private": private_bias}],
        action_propensities=[],
        factual_utility=-private_bias,
        oracle_anchor={"private_anchor": private_bias},
    )


def production_oracle(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    del oracle_seed
    observed = None
    for event in episode.public_history.events:
        if event.payload.get("channel_id") == "obs":
            observed = float(event.payload["value"])
    assert observed is not None
    prediction = observed + 0.25 * horizon
    utility = -prediction
    return CounterfactualOracle(
        policy=policy,
        horizon=horizon,
        observation_distribution={"family": "point", "mean": prediction},
        latent_distribution={"family": "point", "mean": prediction},
        outcome_distribution={"family": "point", "expected_utility": utility},
        expected_utility=utility,
        numerical_diagnostics={
            "method": "production-forward-formula",
            "absolute_error_bound": "a label is not evidence",
        },
    )


def reference_oracle(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    del oracle_seed
    public_values = [
        float(item.payload["value"])
        for item in episode.public_history.events
        if item.payload.get("channel_id") == "obs"
    ]
    prediction = public_values[-1]
    for _ in range(horizon):
        prediction += 0.25
    utility = 0.0 - prediction
    return CounterfactualOracle(
        policy=policy,
        horizon=horizon,
        observation_distribution={"family": "point", "mean": prediction},
        latent_distribution={"family": "point", "mean": prediction},
        outcome_distribution={"family": "point", "expected_utility": utility},
        expected_utility=utility,
        numerical_diagnostics={
            "method": "reference-step-enumeration",
            "absolute_error_bound": 0.0,
        },
    )


def near_reference_oracle(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    del oracle_seed
    scalar = tuple(
        float(row.payload["value"])
        for row in episode.public_history.events
        if row.payload.get("channel_id") == "obs"
    )[-1]
    prediction = scalar + horizon / 4.0 + 5e-7
    utility = -prediction
    return CounterfactualOracle(
        policy=policy,
        horizon=horizon,
        observation_distribution={"family": "point", "mean": prediction},
        latent_distribution={"family": "point", "mean": prediction},
        outcome_distribution={"family": "point", "expected_utility": utility},
        expected_utility=utility,
        numerical_diagnostics={"method": "reference-perturbed-quadrature"},
    )


def dishonest_bound_reference(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    del oracle_seed
    observations = episode.public_history.events
    base = float(observations[len(observations) - 1].payload["value"])
    prediction = base + horizon * 0.25 + 0.5
    utility = -prediction
    return CounterfactualOracle(
        policy=policy,
        horizon=horizon,
        observation_distribution={"family": "point", "mean": prediction},
        latent_distribution={"family": "point", "mean": prediction},
        outcome_distribution={"family": "point", "expected_utility": utility},
        expected_utility=utility,
        numerical_diagnostics={
            "method": "dishonest-reference",
            "absolute_error_bound": "999999999999",
        },
    )


def private_reader_oracle(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    del oracle_seed
    base = float(episode.public_history.events[-1].payload["value"])
    private_bias = float(episode.hidden_state_at_cut["private_bias"])
    prediction = base + horizon * 0.25 + private_bias
    utility = -prediction
    return CounterfactualOracle(
        policy=policy,
        horizon=horizon,
        observation_distribution={"family": "point", "mean": prediction},
        latent_distribution={"family": "point", "mean": prediction},
        outcome_distribution={"family": "point", "expected_utility": utility},
        expected_utility=utility,
        numerical_diagnostics={"method": "malicious-private-reader"},
    )


def _shared_algorithm(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    del oracle_seed
    value = float(episode.public_history.events[-1].payload["value"])
    prediction = value + 0.25 * horizon
    return CounterfactualOracle(
        policy=policy,
        horizon=horizon,
        observation_distribution={"family": "point", "mean": prediction},
        latent_distribution={"family": "point", "mean": prediction},
        outcome_distribution={"family": "point", "expected_utility": -prediction},
        expected_utility=-prediction,
        numerical_diagnostics={"method": "shared-core"},
    )


def shared_production(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    return _shared_algorithm(episode, policy, horizon, oracle_seed)


def shared_reference(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    return _shared_algorithm(episode, policy, horizon, oracle_seed)


def shared_base_production(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    return _SHARED_BASE_CORE(episode, policy, horizon, oracle_seed)


def shared_base_reference(
    episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> CounterfactualOracle:
    result = _SHARED_BASE_CORE(episode, policy, horizon, oracle_seed)
    return result


def _certify(
    production=production_oracle,
    reference=reference_oracle,
    *,
    tolerance: NumericTolerance = NumericTolerance(absolute=1e-12, relative=1e-12),
):
    first = _episode(private_bias=0.0)
    swapped = _episode(private_bias=2.0)
    return certify_oracle_pair(
        benchmark_id="ucm-oracle-cert-test",
        production=production,
        reference=reference,
        probes=(OracleProbe("ordinary", first, PLAN, 2, 12345),),
        private_swap_probes=(
            PrivateSwapProbe("private-swap", first, swapped, PLAN, 2, 12345),
        ),
        tolerance=tolerance,
    )


def test_independent_oracles_pass_and_emit_freeze_safe_canonical_evidence() -> None:
    report = _certify()
    assert report.passed
    assert report.source_separation.passed
    assert report.probes[0].comparison is not None
    assert report.probes[0].comparison.passed
    assert report.private_swap_probes[0].production_exact_invariant
    assert report.private_swap_probes[0].reference_exact_invariant
    assert report.production_implementation.implementation_digest != (
        report.reference_implementation.implementation_digest
    )
    assert report.probes[0].production["method_digest"].startswith("sha256:")

    wire = report.to_wire()
    assert canonical_json_bytes(wire) == report.canonical_bytes
    assert report.digest.startswith("sha256:")
    serialized = report.canonical_bytes.decode("utf-8")
    assert '"oracle_seed":' not in serialized
    assert '"seed":' not in serialized
    assert re.search(r'"oracle_seed_digest":"sha256:[0-9a-f]{64}"', serialized)

    # freeze.py recursively rejects raw seed/reveal material.  Successful
    # construction proves this DTO can be embedded without weakening that gate.
    manifest = build_freeze_manifest(
        benchmark_id="ucm-benchmark-v1",
        status=FreezeStatus.PRE_FREEZE,
        files=(),
        source_revision="test-revision",
        created_at="2026-07-15T00:00:00Z",
        prefreeze_blockers=("test-only",),
        required_paths=(),
        metadata={"oracle_certification": wire},
    )
    assert manifest["metadata"]["oracle_certification"]["passed"] is True


def test_configurable_tolerance_uses_measured_errors() -> None:
    passing = _certify(
        reference=near_reference_oracle,
        tolerance=NumericTolerance(absolute=1e-6, relative=0.0),
    )
    assert passing.passed
    comparison = passing.probes[0].comparison
    assert comparison is not None
    assert comparison.max_absolute_error == pytest.approx(5e-7)

    failing = _certify(
        reference=near_reference_oracle,
        tolerance=NumericTolerance(absolute=1e-9, relative=0.0),
    )
    assert not failing.passed
    assert REASON_OUTPUT_MISMATCH in failing.reason_codes


def test_path_override_and_structural_comparison_are_explicit() -> None:
    tolerance = NumericTolerance(
        absolute=0.0,
        relative=0.0,
        path_overrides=(PathTolerance("$.value", absolute=0.1, relative=0.0),),
    )
    accepted = compare_canonical_outputs(
        {"value": 1.0, "label": "same"},
        {"value": 1.05, "label": "same"},
        tolerance,
    )
    assert accepted.passed
    rejected = compare_canonical_outputs(
        {"value": 1.0, "label": "left"},
        {"value": 1.05, "label": "right"},
        tolerance,
    )
    assert not rejected.passed
    assert rejected.structural_mismatch_count == 1


def test_claimed_absolute_error_bound_is_never_trusted() -> None:
    report = _certify(reference=dishonest_bound_reference)
    assert not report.passed
    assert REASON_OUTPUT_MISMATCH in report.reason_codes
    comparison = report.probes[0].comparison
    assert comparison is not None
    assert comparison.max_absolute_error == pytest.approx(0.5)
    assert comparison.numeric_mismatch_count >= 1
    # The self-report is retained only by digest/method evidence, not parsed as
    # an acceptance threshold.
    assert report.probes[0].reference["numerical_diagnostics_digest"].startswith(
        "sha256:"
    )


def test_shared_substantive_implementation_control_is_killed() -> None:
    report = _certify(production=shared_production, reference=shared_reference)
    assert not report.passed
    assert not report.source_separation.passed
    assert REASON_RUNTIME_IMPLEMENTATION_SHARED in report.reason_codes
    assert report.source_separation.shared_substantive_code_digests


def test_substantive_helper_hidden_in_project_base_module_is_not_whitelisted() -> None:
    report = _certify(
        production=shared_base_production,
        reference=shared_base_reference,
    )
    assert not report.passed
    assert REASON_RUNTIME_IMPLEMENTATION_SHARED in report.reason_codes
    shared_rows = {
        row.code_digest: (row.module, row.qualname)
        for row in report.production_implementation.code_rows
    }
    assert any(
        shared_rows[digest]
        == (
            "prototype.unified_map.worlds.base",
            "_oracle_certification_malicious_shared_base",
        )
        for digest in report.source_separation.shared_substantive_code_digests
    )


def test_private_reader_control_is_killed_by_same_public_swap() -> None:
    report = _certify(production=private_reader_oracle)
    assert not report.passed
    assert REASON_PRIVATE_SWAP_DEPENDENCE in report.reason_codes
    gate = report.private_swap_probes[0]
    assert not gate.production_exact_invariant
    assert gate.reference_exact_invariant
    assert gate.production_first["full_output_digest"] != gate.production_swapped[
        "full_output_digest"
    ]


def test_private_swap_rejects_a_changed_public_history() -> None:
    first = _episode(private_bias=0.0)
    changed_public = _episode(private_bias=2.0, uid="different-public-uid")
    with pytest.raises(ProtocolViolation, match="byte-equivalent public"):
        PrivateSwapProbe(
            "not-a-private-swap", first, changed_public, PLAN, 2, 12345
        )
