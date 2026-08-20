from __future__ import annotations

import copy
import json
import math
import unittest
from pathlib import Path

from runtime_v2 import (
    PublicEvent,
    RuntimeV2,
    SharedPatientState,
    architecture_state_hash,
    attach_event_ledger_proof,
    build_event_ledger_proof,
)
from runtime_v2.schema import digest


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"


def model_dict() -> dict:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def observation(
    event_id: str,
    concept_id: str,
    value: object,
    *,
    source_id: str | None = None,
    available_at: float = 0.0,
    sample_at: float | None = None,
    reliability: float = 1.0,
    **extra: object,
) -> PublicEvent:
    sample = available_at if sample_at is None else sample_at
    row = {
        "event_id": event_id,
        "event_type": "ObservationAvailable",
        "occurred_time": {"lower": sample, "upper": sample},
        "sample_time": {"lower": sample, "upper": sample},
        "result_at": sample,
        "recorded_at": available_at,
        "available_at": available_at,
        "concept_id": concept_id,
        "value": value,
        "reliability": reliability,
        "provenance": {"source_result_id": source_id or event_id, "method": "fixture"},
        **extra,
    }
    return PublicEvent.from_dict(row)


def action_started(event_id: str, *, at: float = 0.0) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": event_id,
            "event_type": "ActionStarted",
            "occurred_time": {"lower": at, "upper": at},
            "recorded_at": at,
            "available_at": at,
            "action_id": "ACTION_REDUCE_A",
            "exposure_id": "support-exposure",
            "dose": 1.0,
            "dose_unit": "normalized",
            "provenance": {"source_result_id": event_id},
        }
    )


def record_only(
    event_id: str,
    *,
    source_id: str = "record-source",
    note: str = "administrative context",
) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": event_id,
            "event_type": "RecordOnly",
            "occurred_time": {"lower": 0, "upper": 0},
            "recorded_at": 0,
            "available_at": 0,
            "concept_id": "ADMIN_CONTEXT",
            "note": note,
            "provenance": {"source_result_id": source_id, "method": "fixture"},
        }
    )


def marginal(state: SharedPatientState, process_id: str) -> float:
    return next(
        row["p_active"]
        for row in state.to_dict()["active_process_posterior"]["process_marginals"]
        if row["process_id"] == process_id
    )


def coordinate(state: SharedPatientState, process_id: str, coordinate_id: str) -> dict:
    local = next(
        row for row in state.to_dict()["local_states"] if row["process_id"] == process_id
    )
    return next(row for row in local["coordinates"] if row["coordinate_id"] == coordinate_id)


class EvidenceReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeV2.from_json(MODEL_PATH)

    def test_reliability_tempers_positive_negative_coordinate_mode_and_stratum(self) -> None:
        prior = self.runtime.initialize([], cut=0)
        high_positive = self.runtime.initialize(
            [observation("hp", "OBS_A_MARKER", True, reliability=1.0)], cut=0
        )
        low_positive = self.runtime.initialize(
            [observation("lp", "OBS_A_MARKER", True, reliability=0.2)], cut=0
        )
        high_negative = self.runtime.initialize(
            [observation("hn", "OBS_A_MARKER", False, reliability=1.0)], cut=0
        )
        low_negative = self.runtime.initialize(
            [observation("ln", "OBS_A_MARKER", False, reliability=0.2)], cut=0
        )
        self.assertLess(marginal(prior, "PROCESS_A"), marginal(low_positive, "PROCESS_A"))
        self.assertLess(marginal(low_positive, "PROCESS_A"), marginal(high_positive, "PROCESS_A"))
        self.assertLess(marginal(high_negative, "PROCESS_A"), marginal(low_negative, "PROCESS_A"))
        self.assertLess(marginal(low_negative, "PROCESS_A"), marginal(prior, "PROCESS_A"))
        self.assertEqual(
            low_positive.to_dict()["factor_graph_state"]["factor_messages"][0]["reliability"],
            0.2,
        )

        high_load = self.runtime.initialize(
            [observation("hl", "OBS_A_LOAD", 0.9, reliability=1.0)], cut=0
        )
        low_load = self.runtime.initialize(
            [observation("ll", "OBS_A_LOAD", 0.9, reliability=0.2)], cut=0
        )
        prior_mean = coordinate(prior, "PROCESS_A", "a_burden")["distribution"]["mean"]
        self.assertGreater(
            coordinate(high_load, "PROCESS_A", "a_burden")["distribution"]["mean"] - prior_mean,
            coordinate(low_load, "PROCESS_A", "a_burden")["distribution"]["mean"] - prior_mean,
        )
        self.assertGreater(
            coordinate(high_load, "PROCESS_A", "a_burden")["knownness"],
            coordinate(low_load, "PROCESS_A", "a_burden")["knownness"],
        )

        high_mode = self.runtime.initialize(
            [observation("hm", "OBS_A_DIRECTION", "falling", reliability=1.0)], cut=0
        )
        low_mode = self.runtime.initialize(
            [observation("lm", "OBS_A_DIRECTION", "falling", reliability=0.2)], cut=0
        )
        def recovering(state: SharedPatientState) -> float:
            local = next(row for row in state.to_dict()["local_states"] if row["process_id"] == "PROCESS_A")
            return next(row["probability"] for row in local["mode_posterior"] if row["mode_id"] == "recovering")
        self.assertGreater(recovering(high_mode), recovering(low_mode))

        spec = model_dict()
        process_a = next(row for row in spec["processes"] if row["process_id"] == "PROCESS_A")
        process_a["strata"] = [
            {"stratum_id": "A_LOW", "prior": 0.5},
            {"stratum_id": "A_HIGH", "prior": 0.5},
        ]
        marker = next(row for row in spec["observations"] if row["concept_id"] == "OBS_A_MARKER")
        marker["emissions"][0]["stratum_likelihoods"] = {
            "A_LOW": {"family": "bernoulli", "p_true": 0.1},
            "A_HIGH": {"family": "bernoulli", "p_true": 0.9},
        }
        stratified = RuntimeV2(spec)
        high = stratified.initialize([observation("sh", "OBS_A_MARKER", True)], cut=0)
        low = stratified.initialize(
            [observation("sl", "OBS_A_MARKER", True, reliability=0.2)], cut=0
        )
        def high_stratum(state: SharedPatientState) -> float:
            membership = next(
                row["probability"]
                for row in state.to_dict()["geometry_state"]["stratum_memberships"]
                if row["stratum_id"] == "A_HIGH"
            )
            return membership / marginal(state, "PROCESS_A")
        self.assertGreater(high_stratum(high), high_stratum(low))

    def test_invalid_reliability_fails_closed(self) -> None:
        for value in (-0.1, 1.1, math.nan, math.inf, True, "bad"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "reliability"):
                    observation("bad", "OBS_A_MARKER", True, reliability=value)  # type: ignore[arg-type]

    def test_support_masking_is_operative_and_withheld_is_not_no_event(self) -> None:
        unsupported = self.runtime.initialize(
            [observation("plain", "OBS_A_LOAD", 0.1)], cut=0
        )
        supported = self.runtime.initialize(
            [
                action_started("support-start"),
                observation(
                    "masked",
                    "OBS_A_LOAD",
                    0.1,
                    measurement_condition={
                        "active_support_exposure_ids": ["support-exposure"]
                    },
                ),
            ],
            cut=0,
        )
        prior = self.runtime.initialize([action_started("support-only")], cut=0)
        self.assertLess(marginal(unsupported, "PROCESS_A"), marginal(supported, "PROCESS_A"))
        self.assertAlmostEqual(marginal(supported, "PROCESS_A"), marginal(prior, "PROCESS_A"))
        self.assertEqual(
            supported.to_dict()["factor_graph_state"]["factor_messages"][0]["reliability"],
            0.0,
        )

        withheld_row = observation("withheld", "OBS_A_MARKER", True).to_dict()
        withheld_row.update(
            {"rankable": False, "mapper_disposition_reason": "SUPPORT_MASKED"}
        )
        no_event = self.runtime.initialize([], cut=0)
        withheld = self.runtime.initialize([withheld_row], cut=0)
        self.assertGreater(
            withheld.to_dict()["epistemic_residual"]["measurement_uncertainty"],
            no_event.to_dict()["epistemic_residual"]["measurement_uncertainty"],
        )
        self.assertTrue(
            any(
                row["reason"] == "unknown_measurement_condition"
                for row in withheld.to_dict()["epistemic_residual"]["unexplained_observations"]
            )
        )


class EvidenceIdentityAndTemporalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeV2.from_json(MODEL_PATH)

    def test_generic_record_only_is_lineage_bound_queryable_and_exact_once_warm_or_cold(self) -> None:
        prior = self.runtime.initialize([], cut=0)
        state = self.runtime.initialize([record_only("record-1")], cut=0)
        factor = state.to_dict()["factor_graph_state"]["factor_messages"][0]
        self.assertEqual(factor["factor_type"], "constraint")
        self.assertEqual(factor["variable_ids"], ["DISPOSITION:record_only_event"])
        self.assertEqual(marginal(state, "PROCESS_A"), marginal(prior, "PROCESS_A"))
        self.assertEqual(
            state.to_dict()["epistemic_residual"]["measurement_uncertainty"],
            prior.to_dict()["epistemic_residual"]["measurement_uncertainty"],
        )

        cold = SharedPatientState.from_bytes(state.to_bytes())
        self.assertEqual(self.runtime.diagnose(cold), self.runtime.diagnose(state))
        self.assertEqual(
            self.runtime.forecast(cold, horizon=1),
            self.runtime.forecast(state, horizon=1),
        )
        self.assertEqual(
            self.runtime.plan(cold, ["NO_NEW_ACTION"], horizon=1),
            self.runtime.plan(state, ["NO_NEW_ACTION"], horizon=1),
        )

        duplicate = record_only("record-2")
        self.assertEqual(
            self.runtime.update(state, [duplicate], advance_to=0).to_bytes(),
            state.to_bytes(),
        )
        cold_with_proof = attach_event_ledger_proof(
            cold, build_event_ledger_proof(state)
        )
        self.assertEqual(
            self.runtime.update(cold_with_proof, [duplicate], advance_to=0).to_bytes(),
            state.to_bytes(),
        )
        with self.assertRaisesRegex(ValueError, "changed evidence"):
            self.runtime.update(
                cold_with_proof,
                [record_only("record-3", note="changed semantic content")],
                advance_to=0,
            )

    def test_same_source_distinct_concepts_are_members_exact_once_and_order_invariant(self) -> None:
        a = observation("member-a", "OBS_A_MARKER", True, source_id="panel-1")
        b = observation("member-b", "OBS_B_MARKER", True, source_id="panel-1")
        state = self.runtime.initialize([a, b], cut=0)
        reversed_state = self.runtime.initialize([b, a], cut=0)
        self.assertEqual(state.to_bytes(), reversed_state.to_bytes())
        self.assertGreater(marginal(state, "PROCESS_A"), 0.7)
        self.assertGreater(marginal(state, "PROCESS_B"), 0.7)
        factor_state = state.to_dict()["factor_graph_state"]
        self.assertEqual(len(factor_state["factor_messages"]), 2)
        self.assertEqual(factor_state["recognized_result_ids"], ["panel-1"])

        duplicate_a = observation("member-a-copy", "OBS_A_MARKER", True, source_id="panel-1")
        self.assertEqual(
            self.runtime.update(state, [duplicate_a], advance_to=0).to_bytes(),
            state.to_bytes(),
        )
        changed = observation("member-a-changed", "OBS_A_MARKER", False, source_id="panel-1")
        with self.assertRaisesRegex(ValueError, "member collision"):
            self.runtime.update(state, [changed], advance_to=0)
        cold = attach_event_ledger_proof(
            SharedPatientState.from_bytes(state.to_bytes()), build_event_ledger_proof(state)
        )
        with self.assertRaisesRegex(ValueError, "member collision"):
            self.runtime.update(cold, [changed], advance_to=0)

    def test_source_semantic_fingerprint_covers_all_inference_fields(self) -> None:
        base = observation("base", "OBS_A_MARKER", True, source_id="one-result", available_at=2)
        state = self.runtime.initialize([base], cut=2)
        mutations = []
        for label, patch in (
            ("value", {"value": False}),
            ("unit", {"unit": "other"}),
            ("sample", {"sample_time": {"lower": 1, "upper": 1}}),
            ("occurred", {"occurred_time": {"lower": 1, "upper": 1}}),
            (
                "result",
                {"sample_time": {"lower": 1, "upper": 1}, "result_at": 1},
            ),
            ("condition", {"measurement_condition": {"support_masking": 0.2}}),
            ("rankable", {"rankable": False, "mapper_disposition_reason": "LOW_RELIABILITY"}),
            ("reliability", {"reliability": 0.5}),
            ("method", {"provenance": {"source_result_id": "one-result", "method": "other"}}),
        ):
            row = base.to_dict()
            row["event_id"] = f"changed-{label}"
            row.update(copy.deepcopy(patch))
            mutations.append((label, PublicEvent.from_dict(row)))
        for label, event in mutations:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "member collision"):
                    self.runtime.update(state, [event], advance_to=2)

    def test_delayed_identity_updates_posterior_but_stale_numeric_is_typed_ood(self) -> None:
        baseline = self.runtime.initialize([], cut=5)
        delayed_identity = observation(
            "identity-delayed",
            "OBS_A_MARKER",
            True,
            available_at=5,
            sample_at=0,
        )
        identity_state = self.runtime.update(baseline, [delayed_identity], advance_to=5)
        self.assertGreater(marginal(identity_state, "PROCESS_A"), marginal(baseline, "PROCESS_A"))
        message = identity_state.to_dict()["factor_graph_state"]["factor_messages"][0]
        self.assertTrue(
            any(key.startswith("provenance:event:") for key in message["log_likelihood_by_hypothesis"])
        )
        self.assertTrue(
            any(
                key.startswith("provenance:temporal:sample=0,0;")
                and ";available=5" in key
                for key in message["log_likelihood_by_hypothesis"]
            )
        )

        delayed_numeric = observation(
            "numeric-delayed",
            "OBS_A_LOAD",
            0.9,
            available_at=5,
            sample_at=0,
        )
        stale_state = self.runtime.update(baseline, [delayed_numeric], advance_to=5)
        immediate_state = self.runtime.update(
            baseline,
            [observation("numeric-now", "OBS_A_LOAD", 0.9, available_at=5, sample_at=5)],
            advance_to=5,
        )
        prior_mean = coordinate(baseline, "PROCESS_A", "a_burden")["distribution"]["mean"]
        self.assertEqual(
            coordinate(stale_state, "PROCESS_A", "a_burden")["distribution"]["mean"],
            prior_mean,
        )
        self.assertGreater(
            coordinate(immediate_state, "PROCESS_A", "a_burden")["distribution"]["mean"],
            prior_mean,
        )
        self.assertNotEqual(stale_state.to_bytes(), immediate_state.to_bytes())
        self.assertTrue(
            any(
                row["reason"] == "unknown_measurement_condition"
                for row in stale_state.to_dict()["epistemic_residual"]["unexplained_observations"]
            )
        )

    def test_stale_recursive_event_fails_closed_but_duplicates_and_current_availability_work(self) -> None:
        historical = observation(
            "historical",
            "OBS_A_MARKER",
            True,
            source_id="historical-source",
            available_at=1,
            sample_at=1,
        )
        # Replay from the beginning is valid: evidence is absorbed at t=1 and
        # the resulting posterior is then propagated to the requested cut.
        replayed = self.runtime.initialize([historical], cut=5)
        baseline_at_five = self.runtime.initialize([], cut=5)

        # Recursive absorption after the state has crossed t=1 is not the same
        # operation and must not silently produce a second valid-looking state.
        with self.assertRaisesRegex(ValueError, "stale recursive event"):
            self.runtime.update(baseline_at_five, [historical], advance_to=5)

        cold_baseline = SharedPatientState.from_bytes(baseline_at_five.to_bytes())
        cold_baseline = attach_event_ledger_proof(
            cold_baseline, build_event_ledger_proof(baseline_at_five)
        )
        with self.assertRaisesRegex(ValueError, "stale recursive event"):
            self.runtime.update(cold_baseline, [historical], advance_to=5)

        # Exact and semantic-source duplicates remain idempotent even though
        # their original availability precedes the current state time.
        self.assertEqual(
            self.runtime.update(replayed, [historical], advance_to=5).to_bytes(),
            replayed.to_bytes(),
        )
        equivalent_transport = observation(
            "historical-rerendered",
            "OBS_A_MARKER",
            True,
            source_id="historical-source",
            available_at=1,
            sample_at=1,
        )
        self.assertEqual(
            self.runtime.update(replayed, [equivalent_transport], advance_to=5).to_bytes(),
            replayed.to_bytes(),
        )

        # Delayed result availability is a separate supported case: its sample
        # may be old as long as the result first becomes available at the
        # current cut.  Existing identity-vs-local temporal rules then apply.
        delayed_identity = observation(
            "current-availability-old-sample",
            "OBS_A_MARKER",
            True,
            available_at=5,
            sample_at=1,
        )
        delayed_state = self.runtime.update(
            baseline_at_five, [delayed_identity], advance_to=5
        )
        self.assertGreater(
            marginal(delayed_state, "PROCESS_A"),
            marginal(baseline_at_five, "PROCESS_A"),
        )

    def test_known_factor_generation_misfit_is_typed_and_survives_cold(self) -> None:
        state = self.runtime.initialize(
            [observation("wild", "OBS_A_LOAD", 100.0)], cut=0
        )
        misfit = next(
            row
            for row in state.to_dict()["epistemic_residual"]["unexplained_observations"]
            if row["reason"] == "model_misfit"
        )
        self.assertEqual(misfit["result_id"], "wild")
        self.assertGreater(misfit["surprisal"], 6.0)
        cold = SharedPatientState.from_bytes(state.to_bytes())
        self.assertEqual(self.runtime.diagnose(cold), self.runtime.diagnose(state))
        restored = attach_event_ledger_proof(cold, build_event_ledger_proof(state))
        self.assertEqual(
            self.runtime.update(
                restored,
                [observation("wild-copy", "OBS_A_LOAD", 100.0, source_id="wild")],
                advance_to=0,
            ).to_bytes(),
            state.to_bytes(),
        )

    def test_all_queries_accept_canonical_cold_bytes_without_sidecars_and_forged_factor_fails(self) -> None:
        state = self.runtime.initialize(
            [observation("cold-query", "OBS_A_MARKER", True)], cut=0
        )
        cold = SharedPatientState.from_bytes(state.to_bytes())
        self.assertEqual(self.runtime.diagnose(cold), self.runtime.diagnose(state))
        self.assertEqual(self.runtime.forecast(cold, horizon=1), self.runtime.forecast(state, horizon=1))
        policies = [{"policy_id": "NO_NEW_ACTION"}]
        self.assertEqual(self.runtime.plan(cold, policies, horizon=1), self.runtime.plan(state, policies, horizon=1))

        empty = self.runtime.initialize([], cut=0).to_dict()
        message = copy.deepcopy(state.to_dict()["factor_graph_state"]["factor_messages"][0])
        empty["factor_graph_state"]["factor_messages"] = [message]
        empty["factor_graph_state"]["messages_digest"] = digest([message])
        empty["factor_graph_state"]["recognized_result_ids"] = ["FORGED_SOURCE"]
        message["source_result_ids"] = ["FORGED_SOURCE"]
        empty["factor_graph_state"]["messages_digest"] = digest([message])
        empty["integrity"]["state_hash"] = architecture_state_hash(empty)
        with self.assertRaises(ValueError):
            self.runtime.diagnose(SharedPatientState.from_dict(empty))


class JointCommonCauseFactorTests(unittest.TestCase):
    def test_multi_process_observation_requires_and_executes_joint_factor(self) -> None:
        spec = model_dict()
        a_marker = copy.deepcopy(
            next(row for row in spec["observations"] if row["concept_id"] == "OBS_A_MARKER")
        )
        b_emission = copy.deepcopy(
            next(row for row in spec["observations"] if row["concept_id"] == "OBS_B_MARKER")["emissions"][0]
        )
        a_marker["concept_id"] = "OBS_SHARED_MARKER"
        a_marker["factor_id"] = "FACTOR_SHARED_COMMON_CAUSE"
        a_marker["emissions"].append(b_emission)
        spec["observations"].append(a_marker)
        with self.assertRaisesRegex(ValueError, "joint_likelihoods"):
            RuntimeV2(spec)

        a_marker["joint_likelihoods"] = {
            "-": {"family": "bernoulli", "p_true": 0.05},
            "PROCESS_A": {"family": "bernoulli", "p_true": 0.80},
            "PROCESS_B": {"family": "bernoulli", "p_true": 0.80},
            "PROCESS_A,PROCESS_B": {"family": "bernoulli", "p_true": 0.80},
        }
        runtime = RuntimeV2(spec)
        prior = runtime.initialize([], cut=0)
        after = runtime.initialize(
            [observation("joint", "OBS_SHARED_MARKER", True)], cut=0
        )

        def probability(state: SharedPatientState, active: list[str]) -> float:
            return next(
                row["probability"]
                for row in state.to_dict()["active_process_posterior"]["joint_hypotheses"]
                if row["active_process_ids"] == active
            )

        prior_ratio = probability(prior, ["PROCESS_A", "PROCESS_B"]) / probability(
            prior, ["PROCESS_A"]
        )
        after_ratio = probability(after, ["PROCESS_A", "PROCESS_B"]) / probability(
            after, ["PROCESS_A"]
        )
        self.assertAlmostEqual(prior_ratio, after_ratio)
        message = after.to_dict()["factor_graph_state"]["factor_messages"][0]
        self.assertIn(
            "joint:known=PROCESS_A,PROCESS_B",
            message["log_likelihood_by_hypothesis"],
        )


class SharedLatentCommonCauseTests(unittest.TestCase):
    @staticmethod
    def _categorical(
        true_true: float,
        true_false: float,
        false_true: float,
        false_false: float,
    ) -> dict:
        return {
            "family": "categorical",
            "probabilities": {
                '{"OBS_SHARED_A":false,"OBS_SHARED_B":false}': false_false,
                '{"OBS_SHARED_A":false,"OBS_SHARED_B":true}': false_true,
                '{"OBS_SHARED_A":true,"OBS_SHARED_B":false}': true_false,
                '{"OBS_SHARED_A":true,"OBS_SHARED_B":true}': true_true,
            },
        }

    @classmethod
    def _spec(cls, *, with_common_cause: bool = True) -> dict:
        spec = model_dict()
        for concept_id, factor_id in (
            ("OBS_SHARED_A", "FACTOR_SHARED_A"),
            ("OBS_SHARED_B", "FACTOR_SHARED_B"),
        ):
            spec["observations"].append(
                {
                    "concept_id": concept_id,
                    "factor_id": factor_id,
                    "emissions": [
                        {
                            "process_id": "PROCESS_A",
                            "active_likelihood": {
                                "family": "bernoulli",
                                "p_true": 0.9,
                            },
                            "inactive_likelihood": {
                                "family": "bernoulli",
                                "p_true": 0.1,
                            },
                        }
                    ],
                }
            )
        if with_common_cause:
            spec["common_cause_factors"] = [
                {
                    "factor_id": "COMMON_SHARED_SENSOR",
                    "member_concept_ids": ["OBS_SHARED_A", "OBS_SHARED_B"],
                    "binding_mode": "SHARED_LATENT_INSTANCE",
                    "value_encoding": "CANONICAL_MEMBER_OBJECT",
                    "reliability_aggregation": "MINIMUM",
                    # The shared cause supplies one LR=3.5 update for two true
                    # projections.  Treating the projections independently
                    # would incorrectly multiply LR=9 twice.
                    "joint_value_likelihoods": {
                        "-": cls._categorical(0.2, 0.1, 0.1, 0.6),
                        "PROCESS_A": cls._categorical(0.7, 0.1, 0.1, 0.1),
                    },
                }
            ]
        return spec

    @staticmethod
    def _members(
        *,
        reverse: bool = False,
        instance_a: str = "latent-1",
        instance_b: str = "latent-1",
        source_a: str = "source-a",
        source_b: str = "source-b",
        available_b: float = 0.0,
    ) -> list[PublicEvent]:
        members = [
            observation(
                "shared-a",
                "OBS_SHARED_A",
                True,
                source_id=source_a,
                provenance={
                    "source_result_id": source_a,
                    "method": "fixture",
                    "common_cause_instance_id": instance_a,
                },
            ),
            observation(
                "shared-b",
                "OBS_SHARED_B",
                True,
                source_id=source_b,
                available_at=available_b,
                sample_at=available_b,
                provenance={
                    "source_result_id": source_b,
                    "method": "fixture",
                    "common_cause_instance_id": instance_b,
                },
            ),
        ]
        return list(reversed(members)) if reverse else members

    def test_shared_latent_factor_updates_once_is_permutation_exact_and_cold_replay_safe(self) -> None:
        runtime = RuntimeV2(self._spec())
        forward = runtime.initialize(self._members(), cut=0)
        reverse = runtime.initialize(self._members(reverse=True), cut=0)
        self.assertEqual(forward.to_bytes(), reverse.to_bytes())

        messages = forward.to_dict()["factor_graph_state"]["factor_messages"]
        self.assertEqual(len(messages), 1)
        message = messages[0]
        self.assertEqual(message["factor_id"], "COMMON_SHARED_SENSOR")
        self.assertEqual(message["factor_type"], "common_cause")
        self.assertEqual(message["source_result_ids"], ["source-a", "source-b"])
        self.assertNotIn(
            "process:PROCESS_A:active",
            message["log_likelihood_by_hypothesis"],
        )
        self.assertIn(
            "joint:known=PROCESS_A",
            message["log_likelihood_by_hypothesis"],
        )
        provenance_terms = [
            key
            for key in message["log_likelihood_by_hypothesis"]
            if key.startswith("provenance:binding64:")
        ]
        self.assertEqual(len(provenance_terms), 2)

        independent = RuntimeV2(self._spec(with_common_cause=False)).initialize(
            self._members(), cut=0
        )
        self.assertGreater(
            marginal(independent, "PROCESS_A"),
            marginal(forward, "PROCESS_A"),
        )

        cold = SharedPatientState.from_bytes(forward.to_bytes())
        self.assertEqual(runtime.diagnose(cold), runtime.diagnose(forward))
        self.assertEqual(
            runtime.forecast(cold, horizon=1),
            runtime.forecast(forward, horizon=1),
        )
        restored = attach_event_ledger_proof(cold, build_event_ledger_proof(forward))
        rerendered = [
            observation(
                "shared-a-rerendered",
                "OBS_SHARED_A",
                True,
                source_id="source-a",
                provenance={
                    "source_result_id": "source-a",
                    "method": "fixture",
                    "common_cause_instance_id": "latent-1",
                },
            ),
            observation(
                "shared-b-rerendered",
                "OBS_SHARED_B",
                True,
                source_id="source-b",
                provenance={
                    "source_result_id": "source-b",
                    "method": "fixture",
                    "common_cause_instance_id": "latent-1",
                },
            ),
        ]
        self.assertEqual(
            runtime.update(restored, rerendered, advance_to=0).to_bytes(),
            forward.to_bytes(),
        )

    def test_shared_latent_members_must_be_complete_synchronous_and_cross_source(self) -> None:
        runtime = RuntimeV2(self._spec())
        with self.assertRaisesRegex(ValueError, "incomplete common-cause batch"):
            runtime.initialize(self._members()[:1], cut=0)
        with self.assertRaisesRegex(ValueError, "incomplete common-cause batch"):
            runtime.initialize(
                self._members(instance_a="latent-a", instance_b="latent-b"),
                cut=0,
            )
        with self.assertRaisesRegex(ValueError, "common_cause_instance_id"):
            no_instance = self._members()
            row = no_instance[0].to_dict()
            row["provenance"].pop("common_cause_instance_id")
            runtime.initialize([PublicEvent.from_dict(row), no_instance[1]], cut=0)
        with self.assertRaisesRegex(ValueError, "distinct source"):
            runtime.initialize(
                self._members(source_a="same-source", source_b="same-source"),
                cut=0,
            )
        with self.assertRaisesRegex(ValueError, "identical temporal semantics"):
            runtime.initialize(self._members(available_b=1), cut=1)

    def test_same_source_multi_concept_factor_is_one_content_bound_message(self) -> None:
        spec = self._spec()
        spec["common_cause_factors"][0]["binding_mode"] = "SAME_SOURCE_RESULT"
        runtime = RuntimeV2(spec)
        events = self._members(
            source_a="panel-result",
            source_b="panel-result",
            # SAME_SOURCE_RESULT is keyed by the source identity; unrelated
            # optional latent labels must not split the atomic panel result.
            instance_a="transport-label-a",
            instance_b="transport-label-b",
        )
        state = runtime.initialize(events, cut=0)
        message = state.to_dict()["factor_graph_state"]["factor_messages"][0]
        self.assertEqual(message["factor_type"], "common_cause")
        self.assertEqual(message["source_result_ids"], ["panel-result"])
        self.assertIn(
            "common_cause:instance=panel-result",
            message["log_likelihood_by_hypothesis"],
        )
        self.assertEqual(
            len(
                [
                    key
                    for key in message["log_likelihood_by_hypothesis"]
                    if key.startswith("provenance:binding64:")
                ]
            ),
            2,
        )
        self.assertEqual(
            state.to_bytes(),
            runtime.initialize(list(reversed(events)), cut=0).to_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
