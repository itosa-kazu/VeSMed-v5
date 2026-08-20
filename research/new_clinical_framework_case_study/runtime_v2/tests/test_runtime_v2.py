from __future__ import annotations

import copy
import json
import math
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from runtime_v2 import (
    PublicEvent,
    RuntimeV2,
    SharedPatientState,
    attach_event_ledger_proof,
    build_event_ledger_proof,
    evaluate_behavioral_collision,
    execute_local_refinement,
    import_legacy_v1_state,
    load_events_json,
    load_state_json,
    migrate_v2_state,
    save_state_json,
    architecture_state_hash,
)


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"
EVENTS_PATH = ROOT / "examples" / "neutral_events.json"


def model_dict() -> dict:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def activation_marginals(state: SharedPatientState) -> dict[str, float]:
    return {
        row["process_id"]: row["p_active"]
        for row in state.to_dict()["active_process_posterior"]["process_marginals"]
    }


def local_state(state: SharedPatientState, process_id: str) -> dict:
    return next(row for row in state.to_dict()["local_states"] if row["process_id"] == process_id)


def local_modes(state: SharedPatientState, process_id: str) -> dict[str, float]:
    return {row["mode_id"]: row["probability"] for row in local_state(state, process_id)["mode_posterior"]}


def action_instance(state: SharedPatientState, exposure_id: str) -> dict:
    return next(
        row for row in state.to_dict()["action_memory"]["instances"]
        if row["action_instance_id"] == exposure_id
    )


def observation(
    event_id: str,
    concept_id: str,
    value: object,
    *,
    at: float = 0.0,
    source_id: str | None = None,
) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": event_id,
            "event_type": "ObservationAvailable",
            "available_at": at,
            "recorded_at": at,
            "occurred_time": {"lower": at, "upper": at},
            "sample_time": {"lower": at, "upper": at},
            "result_at": at,
            "concept_id": concept_id,
            "value": value,
            "provenance": {"source_result_id": source_id or event_id},
        }
    )


def action_event(
    event_id: str,
    kind: str,
    *,
    at: float,
    dose: float | None = None,
    available_at: float | None = None,
    occurred_lower: float | None = None,
    occurred_upper: float | None = None,
    source_id: str | None = None,
    action_id: str = "ACTION_REDUCE_A",
    exposure_id: str = "exposure-a",
    dose_unit: str | None = None,
) -> PublicEvent:
    available = at if available_at is None else available_at
    lower = at if occurred_lower is None else occurred_lower
    upper = at if occurred_upper is None else occurred_upper
    row = {
        "event_id": event_id,
        "event_type": kind,
        "available_at": available,
        "recorded_at": available,
        "occurred_time": {"lower": lower, "upper": upper},
        "provenance": {"source_result_id": source_id or event_id},
        "action_id": action_id,
        "exposure_id": exposure_id,
    }
    if dose is not None:
        row["dose"] = dose
    if dose_unit is not None:
        row["dose_unit"] = dose_unit
    return PublicEvent.from_dict(row)


class FactorialInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeV2.from_json(MODEL_PATH)

    def test_joint_is_normalized_and_allows_concurrent_processes(self) -> None:
        state = self.runtime.initialize(
            [
                observation("a", "OBS_A_MARKER", True),
                observation("b", "OBS_B_MARKER", True),
            ],
            cut=0,
        )
        wire = state.to_dict()
        hypotheses = wire["active_process_posterior"]["joint_hypotheses"]
        self.assertAlmostEqual(sum(row["probability"] for row in hypotheses), 1.0)
        self.assertGreater(activation_marginals(state)["PROCESS_A"], 0.7)
        self.assertGreater(activation_marginals(state)["PROCESS_B"], 0.7)
        coactive = sum(
            row["probability"]
            for row in hypotheses
            if {"PROCESS_A", "PROCESS_B"}.issubset(row["active_process_ids"])
        )
        a_only = sum(
            row["probability"]
            for row in hypotheses
            if "PROCESS_A" in row["active_process_ids"] and "PROCESS_B" not in row["active_process_ids"]
        )
        b_only = sum(
            row["probability"]
            for row in hypotheses
            if "PROCESS_B" in row["active_process_ids"] and "PROCESS_A" not in row["active_process_ids"]
        )
        self.assertGreater(coactive, a_only)
        self.assertGreater(coactive, b_only)

    def test_reliable_negative_evidence_produces_signed_refutation(self) -> None:
        prior = self.runtime.initialize([], cut=0)
        negative = self.runtime.initialize([observation("a-neg", "OBS_A_MARKER", False)], cut=0)
        self.assertLess(
            activation_marginals(negative)["PROCESS_A"],
            activation_marginals(prior)["PROCESS_A"],
        )
        message = negative.to_dict()["factor_graph_state"]["factor_messages"][0]
        self.assertLess(
            message["log_likelihood_by_hypothesis"]["process:PROCESS_A:active"]
            - message["log_likelihood_by_hypothesis"]["process:PROCESS_A:inactive"],
            0.0,
        )
        marginal = next(row for row in negative.to_dict()["active_process_posterior"]["process_marginals"] if row["process_id"] == "PROCESS_A")
        self.assertIn("FACTOR_A_MARKER", marginal["opposing_factor_ids"])

    def test_topology_changes_inference_and_is_traced(self) -> None:
        off = RuntimeV2(model_dict(), topology_enabled=False)
        on = RuntimeV2(model_dict(), topology_enabled=True)
        event = observation("a", "OBS_A_MARKER", True)
        state_off = off.initialize([event], cut=0)
        state_on = on.initialize([event], cut=0)
        self.assertGreater(
            activation_marginals(state_on)["PROCESS_B"],
            activation_marginals(state_off)["PROCESS_B"],
        )
        message = state_on.to_dict()["factor_graph_state"]["factor_messages"][0]
        self.assertIn("topology:PROCESS_A->PROCESS_B", message["log_likelihood_by_hypothesis"])
        self.assertLess(on.branch_distance("PROCESS_A", "PROCESS_B"), on.branch_distance("PROCESS_A", "PROCESS_C"))

    def test_per_process_modes_can_point_in_opposite_directions(self) -> None:
        state = self.runtime.initialize(
            [
                observation("a-dir", "OBS_A_DIRECTION", "falling"),
                observation("b-dir", "OBS_B_DIRECTION", "rising"),
            ],
            cut=0,
        )
        for pid, expected in (("PROCESS_A", "recovering"), ("PROCESS_B", "decompensated"), ("PROCESS_C", "compensated")):
            modes = local_modes(state, pid)
            self.assertEqual(max(modes, key=modes.get), expected)

    def test_coordinate_updates_are_process_local(self) -> None:
        state = self.runtime.initialize([observation("a-load", "OBS_A_LOAD", 0.9)], cut=0)
        a = next(row for row in local_state(state, "PROCESS_A")["coordinates"] if row["coordinate_id"] == "a_burden")
        b = next(row for row in local_state(state, "PROCESS_B")["coordinates"] if row["coordinate_id"] == "b_burden")
        self.assertGreater(a["distribution"]["mean"], 0.7)
        self.assertEqual(b["distribution"]["mean"], 0.2)


class EventAndStateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeV2.from_json(MODEL_PATH)

    def test_future_event_cannot_change_earlier_state(self) -> None:
        now = observation("now", "OBS_A_MARKER", True, at=0)
        future = observation("future", "OBS_B_MARKER", True, at=2)
        state_a = self.runtime.initialize([now], cut=0)
        state_b = self.runtime.initialize([now, future], cut=0)
        self.assertEqual(state_a.to_bytes(), state_b.to_bytes())
        self.assertEqual(
            state_a.to_bytes(),
            self.runtime.update(state_a, [future], advance_to=0).to_bytes(),
        )

    def test_serialized_recursive_update_is_byte_exact(self) -> None:
        state = self.runtime.initialize([observation("a", "OBS_A_MARKER", True)], cut=0)
        delta = [observation("b", "OBS_B_MARKER", True, at=1)]
        direct = self.runtime.update(state, delta, advance_to=1)
        restored = SharedPatientState.from_bytes(state.to_bytes())
        proof = build_event_ledger_proof(state)
        cold = RuntimeV2.from_json(MODEL_PATH).update(
            restored, delta, advance_to=1, event_ledger_proof=proof
        )
        self.assertEqual(direct.to_bytes(), cold.to_bytes())
        self.assertEqual(direct.to_dict()["event_lineage"]["parent_state_hash"], state.state_hash)

    def test_duplicate_event_delivery_is_exactly_once_and_conflict_fails(self) -> None:
        first = observation("same-id", "OBS_A_MARKER", True)
        state = self.runtime.initialize([first], cut=0)
        duplicate = self.runtime.update(state, [first], advance_to=0)
        self.assertEqual(
            activation_marginals(state),
            activation_marginals(duplicate),
        )
        self.assertEqual(state.to_dict()["epistemic_residual"], duplicate.to_dict()["epistemic_residual"])
        self.assertEqual(duplicate.to_bytes(), state.to_bytes())
        changed = observation("same-id", "OBS_A_MARKER", False)
        with self.assertRaisesRegex(ValueError, "event_id collision"):
            self.runtime.update(state, [changed], advance_to=0)

    def test_cold_duplicate_requires_and_validates_content_addressed_proof(self) -> None:
        first = observation("cold-id", "OBS_A_MARKER", True)
        warm = self.runtime.initialize([first], cut=0)
        cold = SharedPatientState.from_bytes(warm.to_bytes())
        with self.assertRaisesRegex(ValueError, "content-addressed event ledger proof"):
            RuntimeV2.from_json(MODEL_PATH).update(cold, [first], advance_to=0)
        proof = build_event_ledger_proof(warm)
        replayed = RuntimeV2.from_json(MODEL_PATH).update(
            cold, [first], advance_to=0, event_ledger_proof=proof
        )
        self.assertEqual(replayed.to_bytes(), warm.to_bytes())
        changed = observation("cold-id", "OBS_A_MARKER", False)
        with self.assertRaisesRegex(ValueError, "event_id collision"):
            RuntimeV2.from_json(MODEL_PATH).update(
                cold, [changed], advance_to=0, event_ledger_proof=proof
            )

    def test_ledger_proof_tampering_fails_closed(self) -> None:
        state = self.runtime.initialize([observation("proof-id", "OBS_A_MARKER", True)], cut=0)
        proof = build_event_ledger_proof(state)
        cold = SharedPatientState.from_bytes(state.to_bytes())
        for mutate in ("state_hash", "event_digest", "event_ledger_digest"):
            bad = copy.deepcopy(proof)
            if mutate == "state_hash":
                bad["state_hash"] = "0" * 64
            elif mutate == "event_digest":
                bad["entries"][0]["event_digest"] = "0" * 64
            else:
                bad["event_ledger_digest"] = "0" * 64
            with self.assertRaises(ValueError):
                attach_event_ledger_proof(cold, bad)

    def test_same_cut_event_order_is_canonical(self) -> None:
        left = observation("order-a", "OBS_A_MARKER", True)
        right = observation("order-b", "OBS_B_MARKER", True)
        self.assertEqual(
            self.runtime.initialize([left, right], cut=0).to_bytes(),
            self.runtime.initialize([right, left], cut=0).to_bytes(),
        )

    def test_factor_source_copy_does_not_multiply_evidence(self) -> None:
        one = observation("one", "OBS_A_MARKER", True, source_id="same-source")
        copy_event = observation("copy", "OBS_A_MARKER", True, source_id="same-source")
        state_one = self.runtime.initialize([one], cut=0)
        state_copy = self.runtime.initialize([one, copy_event], cut=0)
        self.assertEqual(
            activation_marginals(state_one),
            activation_marginals(state_copy),
        )
        self.assertEqual(len(state_copy.to_dict()["factor_graph_state"]["recognized_result_ids"]), 1)
        self.assertEqual(len(state_copy.to_dict()["factor_graph_state"]["factor_messages"]), 1)

    def test_equivalent_new_event_id_same_source_is_byte_identical(self) -> None:
        first = observation(
            "render-1",
            "OBS_A_MARKER",
            True,
            source_id="same-public-result",
        )
        equivalent_render = observation(
            "render-2",
            "OBS_A_MARKER",
            True,
            source_id="same-public-result",
        )
        state = self.runtime.initialize([first], cut=0)
        updated = self.runtime.update(state, [equivalent_render], advance_to=0)
        self.assertEqual(state.to_bytes(), updated.to_bytes())

    def test_different_child_factors_with_one_common_source_do_not_multiply(self) -> None:
        spec = model_dict()
        child = copy.deepcopy(
            next(row for row in spec["observations"] if row["concept_id"] == "OBS_A_MARKER")
        )
        child["concept_id"] = "OBS_A_MARKER_CHILD"
        child["factor_id"] = "FACTOR_A_MARKER_CHILD"
        spec["observations"].append(child)
        runtime = RuntimeV2(spec)
        parent = observation("parent-factor", "OBS_A_MARKER", True, source_id="common-parent")
        derived = observation("child-factor", "OBS_A_MARKER_CHILD", True, source_id="common-parent")
        self.assertEqual(
            activation_marginals(runtime.initialize([parent], cut=0)),
            activation_marginals(runtime.initialize([parent, derived], cut=0)),
        )

    def test_canonical_wire_not_private_cache_is_query_authority(self) -> None:
        state = self.runtime.initialize(
            [observation("authority", "OBS_A_LOAD", 0.8)], cut=0
        )
        expected = self.runtime.forecast(state, horizon=1)
        evil = self.runtime._empty_payload(0)
        evil["per_process"]["PROCESS_A"]["coordinates"]["a_burden"]["mean"] = 0.0
        poisoned = SharedPatientState(
            state.to_dict(), evil, copy.deepcopy(state._event_ledger_proof)
        )
        self.assertEqual(expected, self.runtime.forecast(poisoned, horizon=1))

    def test_rehashed_control_plane_edit_is_rejected_semantically(self) -> None:
        state = self.runtime.initialize([], cut=0)
        for field in ("cross_couplings", "geometry_state"):
            wire = state.to_dict()
            if field == "cross_couplings":
                wire[field][0]["activity_probability"] = 0.999
            else:
                wire[field]["stratum_memberships"][0]["probability"] = 0.999
            wire["integrity"]["state_hash"] = architecture_state_hash(wire)
            controlled = SharedPatientState.from_dict(wire)
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                self.runtime.forecast(controlled, horizon=1)

    def test_rehashed_scope_or_identifiability_edit_cannot_change_authority(self) -> None:
        state = self.runtime.initialize([], cut=0)

        scope_wire = state.to_dict()
        scope_wire["scope"]["horizon"]["value"] = 999.0
        scope_wire["integrity"]["state_hash"] = architecture_state_hash(scope_wire)
        with self.assertRaisesRegex(ValueError, "scope is inconsistent"):
            self.runtime.forecast(SharedPatientState.from_dict(scope_wire), horizon=1)

        claim_wire = state.to_dict()
        action_claim = next(
            row for row in claim_wire["identifiability_claims"]
            if row["query_id"] == "action:ACTION_REDUCE_A"
        )
        action_claim["status"] = "IDENTIFIED_WITHIN_SCOPE"
        action_claim["reason"] = "caller-fabricated authorization"
        action_claim["compatible_world_ids"] = ["FABRICATED_WORLD"]
        claim_wire["integrity"]["state_hash"] = architecture_state_hash(claim_wire)
        tampered = SharedPatientState.from_dict(claim_wire)
        with self.assertRaisesRegex(ValueError, "identifiability_claims"):
            self.runtime.plan(
                tampered,
                [{"policy_id": "ACT", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]}],
                horizon=1,
            )

    def test_rehashed_redundant_state_views_must_be_semantically_closed(self) -> None:
        state = self.runtime.initialize(
            [observation("closure-obs", "OBS_A_LOAD", 0.8)], cut=0
        )

        mutations = []

        def marginal(wire: dict) -> None:
            next(
                row for row in wire["active_process_posterior"]["process_marginals"]
                if row["process_id"] == "PROCESS_A"
            )["p_active"] = 0.9
        mutations.append((marginal, "active_process_posterior"))

        def mode(wire: dict) -> None:
            local = next(row for row in wire["local_states"] if row["process_id"] == "PROCESS_C")
            local["mode_posterior"][0]["probability"] = 0.9
            local["mode_posterior"][1]["probability"] = 0.5
            local["mode_posterior"][2]["probability"] = 0.1
        mutations.append((mode, "mode posterior"))

        def coordinate_sd(wire: dict) -> None:
            wire["local_states"][0]["coordinates"][0]["distribution"]["sd"] = 0.987654
        mutations.append((coordinate_sd, "local_states"))

        def model_registry(wire: dict) -> None:
            wire["model_lineage"]["dynamics_digest"] = "0" * 64
        mutations.append((model_registry, "model_lineage"))

        def factor_digest(wire: dict) -> None:
            wire["factor_graph_state"]["messages_digest"] = "1" * 64
        mutations.append((factor_digest, "messages_digest"))

        def action_digest(wire: dict) -> None:
            wire["action_memory"]["history_digest"] = "2" * 64
        mutations.append((action_digest, "history_digest"))

        def action_policy(wire: dict) -> None:
            wire["action_memory"]["current_policy_id"] = "CALLER_FAKE_POLICY"
        mutations.append((action_policy, "action_memory"))

        def summary_digest(wire: dict) -> None:
            wire["history_summary"]["summary_digest"] = "3" * 64
        mutations.append((summary_digest, "summary_digest"))

        for mutation, error in mutations:
            with self.subTest(error=error):
                wire = state.to_dict()
                mutation(wire)
                wire["integrity"]["state_hash"] = architecture_state_hash(wire)
                with self.assertRaisesRegex(ValueError, error):
                    self.runtime.forecast(SharedPatientState.from_dict(wire), horizon=1)

    def test_all_queries_are_pure_and_share_exact_hash(self) -> None:
        state = self.runtime.initialize(
            [observation("a", "OBS_A_LOAD", 0.8), observation("b", "OBS_B_LOAD", 0.8)],
            cut=0,
        )
        before = state.to_bytes()
        diagnosis = self.runtime.diagnose(state)
        forecast = self.runtime.forecast(state, horizon=2)
        plan = self.runtime.plan(
            state,
            [
                {"policy_id": "NO_NEW_ACTION", "start_actions": []},
                {"policy_id": "ACT", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]},
            ],
            horizon=2,
        )
        self.assertEqual(
            {diagnosis["consumed_state_hash"], forecast["consumed_state_hash"], plan["consumed_state_hash"]},
            {state.state_hash},
        )
        self.assertEqual(state.to_bytes(), before)

    def test_json_loader_and_state_round_trip(self) -> None:
        events = load_events_json(EVENTS_PATH)
        state = self.runtime.initialize(events, cut=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state_json(state, path)
            restored = load_state_json(path)
        self.assertEqual(restored.to_bytes(), state.to_bytes())
        self.assertEqual(restored.state_hash, state.state_hash)

    def test_public_event_requires_provenance_and_explicit_partial_order_times(self) -> None:
        base = {
            "event_id": "typed-event",
            "event_type": "ObservationAvailable",
            "occurred_time": {"lower": 0, "upper": 0},
            "sample_time": {"lower": 0, "upper": 0},
            "result_at": 0,
            "recorded_at": 0,
            "available_at": 0,
            "concept_id": "OBS_A_MARKER",
            "value": True,
        }
        with self.assertRaisesRegex(ValueError, "provenance"):
            PublicEvent.from_dict(base)
        invalid_order = {
            **base,
            "provenance": {"source_result_id": "typed-source"},
            "sample_time": {"lower": 2, "upper": 3},
        }
        with self.assertRaisesRegex(ValueError, "sample lower"):
            PublicEvent.from_dict(invalid_order)

    def test_nonrankable_observation_has_explicit_record_only_disposition(self) -> None:
        row = observation("record-only", "OBS_A_MARKER", True).to_dict()
        row["rankable"] = False
        state = self.runtime.initialize([row], cut=0)
        factor = state.to_dict()["factor_graph_state"]["factor_messages"][0]
        self.assertEqual(factor["factor_type"], "measurement")
        self.assertEqual(
            factor["variable_ids"], ["DISPOSITION:record_only_nonrankable"]
        )
        self.assertIn(
            "record-only",
            state.to_dict()["factor_graph_state"]["recognized_result_ids"],
        )

    def test_conflicting_independent_measurements_raise_model_misfit(self) -> None:
        positive = observation("positive", "OBS_A_MARKER", True, source_id="source-positive")
        negative = observation("negative", "OBS_A_MARKER", False, source_id="source-negative")
        before = self.runtime.initialize([positive], cut=0)
        after = self.runtime.update(before, [negative], advance_to=0)
        self.assertGreater(
            after.to_dict()["epistemic_residual"]["model_misfit"],
            before.to_dict()["epistemic_residual"]["model_misfit"],
        )
        self.assertTrue(
            any(
                row["reason"] == "conflicting_measurements"
                for row in after.to_dict()["epistemic_residual"]["unexplained_observations"]
            )
        )
        same_batch = self.runtime.initialize([positive, negative], cut=0)
        self.assertTrue(
            any(
                row["reason"] == "conflicting_measurements"
                for row in same_batch.to_dict()["epistemic_residual"]["unexplained_observations"]
            )
        )

    def test_canonical_wire_conforms_to_frozen_architecture_schema(self) -> None:
        events = load_events_json(EVENTS_PATH)
        state = self.runtime.initialize(events, cut=5)
        self.assertEqual(state.to_dict()["integrity"]["state_hash"], architecture_state_hash(state.to_dict()))
        schema_path = ROOT.parent / "architecture_final_v1.schema.json"
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            save_state_json(state, state_path)
            command = (
                f"$json=Get-Content -Raw -LiteralPath '{state_path}'; "
                f"$schema=Get-Content -Raw -LiteralPath '{schema_path}'; "
                "if (-not ($json | Test-Json -Schema $schema -ErrorAction Stop)) { exit 1 }"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_exact_factorial_boundary_supports_twelve_processes_and_rejects_thirteen(self) -> None:
        spec = model_dict()
        template = spec["processes"][2]
        for index in range(4, 13):
            process = copy.deepcopy(template)
            process["process_id"] = f"PROCESS_{index}"
            old_cid = process["coordinates"][0]["coordinate_id"]
            new_cid = f"burden_{index}"
            process["coordinates"][0]["coordinate_id"] = new_cid
            for mode in process["modes"]:
                mode["coordinate_drift"] = {new_cid: mode["coordinate_drift"][old_cid]}
            spec["processes"].append(process)
        started = time.perf_counter()
        runtime = RuntimeV2(spec)
        state = runtime.initialize([], cut=0)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(state.to_dict()["active_process_posterior"]["joint_hypotheses"]), 8192)
        self.assertLess(elapsed, 10.0)
        thirteen = copy.deepcopy(spec)
        extra = copy.deepcopy(thirteen["processes"][-1])
        extra["process_id"] = "PROCESS_13"
        extra["coordinates"][0]["coordinate_id"] = "burden_13"
        for mode in extra["modes"]:
            mode["coordinate_drift"] = {"burden_13": next(iter(mode["coordinate_drift"].values()))}
        thirteen["processes"].append(extra)
        with self.assertRaisesRegex(ValueError, "limited to 12"):
            RuntimeV2(thirteen)


class ActionDynamicsAndOODTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeV2.from_json(MODEL_PATH)

    def test_planned_action_is_record_only(self) -> None:
        baseline = self.runtime.initialize([], cut=0)
        planned = PublicEvent.from_dict(
            {
                "event_id": "plan",
                "event_type": "PlannedAction",
                "available_at": 0,
                "recorded_at": 0,
                "occurred_time": {"lower": 0, "upper": 0},
                "provenance": {"source_result_id": "plan"},
                "action_id": "ACTION_REDUCE_A",
            }
        )
        state = self.runtime.update(baseline, [planned], advance_to=0)
        self.assertEqual(
            [row for row in state.to_dict()["action_memory"]["instances"] if row["status"] != "planned"],
            [],
        )
        self.assertEqual(
            self.runtime.forecast(state, horizon=1)["final_coordinates"],
            self.runtime.forecast(baseline, horizon=1)["final_coordinates"],
        )

    def test_action_occurrence_and_availability_are_accounted_in_causal_order(self) -> None:
        early = self.runtime.initialize(
            [action_event("early-start", "ActionStarted", at=0, dose=1.0)],
            cut=0,
        )
        early_at_two = self.runtime.update(early, [], advance_to=2)
        self.assertAlmostEqual(
            action_instance(early_at_two, "exposure-a")["cumulative_exposure"]["value"],
            2.0,
        )

        # Merely backfilling cumulative dose for this delayed record would
        # leave coordinates/modes/activation on the untreated path and falsely
        # disagree with early_at_two.  Until complete replay/smoothing exists,
        # the runtime must reject the retrospective path rather than claim a
        # precise factual state.
        with self.assertRaisesRegex(ValueError, "complete replay or smoothing"):
            self.runtime.initialize(
                [
                    action_event(
                        "late-start",
                        "ActionStarted",
                        at=0,
                        available_at=2,
                        dose=1.0,
                    )
                ],
                cut=2,
            )

        # Exact-time ties at one availability cut are still deterministic:
        # lifecycle rank, not reverse-lexical transport id, applies start
        # before stop.
        bounded = self.runtime.initialize(
            [
                action_event("z-start", "ActionStarted", at=2, dose=1.0),
                action_event("a-stop", "ActionStopped", at=2),
            ],
            cut=2,
        )
        instance = action_instance(bounded, "exposure-a")
        self.assertAlmostEqual(instance["cumulative_exposure"]["value"], 0.0)
        self.assertEqual(instance["status"], "residual")
        self.assertAlmostEqual(instance["washout"]["estimated_remaining_fraction"], 1.0)

    def test_same_source_action_exact_once_requires_same_event_id_and_plan_start_has_one_lineage(self) -> None:
        started = self.runtime.initialize(
            [
                action_event(
                    "render-a",
                    "ActionStarted",
                    at=0,
                    dose=1.0,
                    source_id="source:administration:1",
                )
            ],
            cut=0,
        )
        exact_duplicate = self.runtime.update(
            started,
            [
                action_event(
                    "render-a",
                    "ActionStarted",
                    at=0,
                    dose=1.0,
                    source_id="source:administration:1",
                )
            ],
            advance_to=0,
        )
        self.assertEqual(started.to_bytes(), exact_duplicate.to_bytes())
        with self.assertRaisesRegex(ValueError, "action source_result_id|action source proof"):
            self.runtime.update(
                started,
                [
                    action_event(
                        "render-b",
                        "ActionStarted",
                        at=0,
                        dose=1.0,
                        source_id="source:administration:1",
                    )
                ],
                advance_to=0,
            )

        plan = PublicEvent.from_dict(
            {
                "event_id": "plan-render",
                "event_type": "PlannedAction",
                "available_at": 0,
                "recorded_at": 0,
                "occurred_time": {"lower": 0, "upper": 0},
                "provenance": {"source_result_id": "source:order:1"},
                "action_id": "ACTION_REDUCE_A",
                "exposure_id": "course-1",
            }
        )
        start = action_event(
            "start-render",
            "ActionStarted",
            at=0,
            dose=1.0,
            source_id="source:administration:course-1",
            exposure_id="course-1",
        )
        linked = self.runtime.initialize([start, plan], cut=0)
        instances = linked.to_dict()["action_memory"]["instances"]
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]["action_instance_id"], "course-1")
        self.assertEqual(instances[0]["status"], "active")
        self.assertIsNotNone(instances[0]["planned_cursor"])
        self.assertEqual(
            instances[0]["source_event_ids"],
            ["plan-render", "start-render"],
        )
        self.assertTrue(
            set(instances[0]["source_event_ids"]).issubset(
                set(linked.to_dict()["event_lineage"]["processed_event_ids"])
            )
        )

    def test_same_action_source_changed_semantics_rejected_after_canonical_roundtrip(self) -> None:
        first = action_event(
            "source-event-original",
            "ActionStarted",
            at=0,
            dose=1.0,
            source_id="source:administration:canonical",
        )
        warm = self.runtime.initialize([first], cut=0)
        changed = action_event(
            "source-event-rerendered",
            "ActionStarted",
            at=0,
            dose=2.0,
            source_id="source:administration:canonical",
        )
        with self.assertRaisesRegex(ValueError, "action source_result_id|action source proof"):
            self.runtime.update(warm, [changed], advance_to=0)

        cold = SharedPatientState.from_bytes(warm.to_bytes())
        proof = build_event_ledger_proof(warm)
        with self.assertRaisesRegex(ValueError, "action source_result_id|action source proof"):
            RuntimeV2.from_json(MODEL_PATH).update(
                cold,
                [changed],
                advance_to=0,
                event_ledger_proof=proof,
            )

    def test_policy_validation_lifecycle_output_and_query_purity(self) -> None:
        active = self.runtime.initialize(
            [action_event("policy-start", "ActionStarted", at=0, dose=1.0)],
            cut=0,
        )
        before = active.to_bytes()
        invalid = [
            {"policy_id": "NEG", "dose_changes": [{"exposure_id": "exposure-a", "dose": -1}]},
            {"policy_id": "NAN", "dose_changes": [{"exposure_id": "exposure-a", "dose": math.nan}]},
            {"policy_id": "UNKNOWN", "unknown_operation": []},
            {"policy_id": "UNKNOWN_ITEM", "hold_actions": [{"exposure_id": "exposure-a", "mystery": 1}]},
            {
                "policy_id": "CONFLICT",
                "hold_actions": [{"exposure_id": "exposure-a"}],
                "stop_actions": [{"exposure_id": "exposure-a"}],
            },
        ]
        for policy in invalid:
            with self.subTest(policy=policy["policy_id"]):
                with self.assertRaises(ValueError):
                    self.runtime.rollout(active, policy, horizon=1)
                self.assertEqual(active.to_bytes(), before)

        states = {}
        for key, expected in (
            ("hold_actions", "held"),
            ("stop_actions", "stopped"),
            ("complete_actions", "completed"),
        ):
            result = self.runtime.rollout(
                active,
                {"policy_id": key, key: [{"exposure_id": "exposure-a"}]},
                horizon=1,
            )
            states[key] = result["final_action_lifecycle"][0]["status"]
            self.assertEqual(states[key], expected)
        self.assertEqual(len(set(states.values())), 3)

    def test_completed_schema_exposure_identity_units_and_unknown_action_fail_closed(self) -> None:
        active = self.runtime.initialize(
            [action_event("complete-start", "ActionStarted", at=0, dose=1.0)],
            cut=0,
        )
        completed = self.runtime.update(
            active,
            [action_event("complete-end", "ActionCompleted", at=1)],
            advance_to=1,
        )
        completed_instance = action_instance(completed, "exposure-a")
        self.assertEqual(completed_instance["status"], "completed")
        self.assertEqual(completed_instance["dose_history"][-1]["operation"], "stop")
        # Construction itself validates against the frozen architecture wire;
        # a cold parse supplies an independent schema pass.
        SharedPatientState.from_bytes(completed.to_bytes())

        with self.assertRaisesRegex(ValueError, "exposure_id already exists"):
            self.runtime.update(
                completed,
                [action_event("reuse", "ActionStarted", at=2, dose=1.0)],
                advance_to=2,
            )

        unit_spec = model_dict()
        next(
            row for row in unit_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )["dose_unit"] = "mg"
        unit_runtime = RuntimeV2(unit_spec)
        mg_state = unit_runtime.initialize(
            [
                action_event(
                    "mg-start",
                    "ActionStarted",
                    at=0,
                    dose=1.0,
                    dose_unit="mg",
                )
            ],
            cut=0,
        )
        with self.assertRaisesRegex(ValueError, "dose unit"):
            unit_runtime.update(
                mg_state,
                [
                    action_event(
                        "mcg-change",
                        "ActionDoseChanged",
                        at=1,
                        dose=1000.0,
                        dose_unit="mcg",
                    )
                ],
                advance_to=1,
            )

        with self.assertRaisesRegex(ValueError, "unregistered performed action"):
            self.runtime.initialize(
                [
                    action_event(
                        "unknown-action",
                        "ActionStarted",
                        at=0,
                        dose=1.0,
                        action_id="ACTION_NOT_REGISTERED",
                    )
                ],
                cut=0,
            )

        # Invalid future actions fail at the public event boundary rather than
        # being treated as valid objects and silently skipped before their cut.
        with self.assertRaisesRegex(ValueError, "finite non-negative"):
            action_event("future-negative", "ActionStarted", at=5, dose=-1.0)
        with self.assertRaisesRegex(ValueError, "finite non-negative"):
            action_event("future-nan", "ActionStarted", at=5, dose=math.nan)
        with self.assertRaisesRegex(ValueError, "non-empty string"):
            action_event("future-empty-unit", "ActionStarted", at=5, dose=1.0, dose_unit="")
        with self.assertRaisesRegex(ValueError, "explicit dose"):
            action_event("future-dose-change-missing", "ActionDoseChanged", at=5)

    def test_overlapping_action_and_observation_intervals_do_not_create_response(self) -> None:
        start = action_event(
            "interval-start",
            "ActionStarted",
            at=0,
            available_at=2,
            occurred_lower=0,
            occurred_upper=2,
            dose=1.0,
        )
        result = PublicEvent.from_dict(
            {
                "event_id": "interval-result",
                "event_type": "ObservationAvailable",
                "available_at": 2,
                "recorded_at": 2,
                "occurred_time": {"lower": 1, "upper": 1},
                "sample_time": {"lower": 1, "upper": 1},
                "result_at": 1,
                "provenance": {"source_result_id": "interval-result"},
                "concept_id": "OBS_A_LOAD",
                "value": 0.1,
            }
        )
        state = self.runtime.initialize([result, start], cut=2)
        self.assertEqual(state.to_dict()["history_summary"]["action_response_windows"], [])
        self.assertTrue(state.to_dict()["epistemic_residual"]["unexplained_observations"])

    def test_partial_action_requires_bounded_robust_value_and_ood_abstention_is_operative(self) -> None:
        spec = model_dict()
        action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
        action["causal_status"] = "PARTIALLY_IDENTIFIED"
        action["action_cost"] = 0.0
        runtime = RuntimeV2(spec)
        policies = [
            {"policy_id": "NO_NEW_ACTION", "start_actions": []},
            {"policy_id": "ACT", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]},
        ]
        state = runtime.initialize([observation("known", "OBS_A_LOAD", 0.9)], cut=0)
        self.assertEqual(runtime.plan(state, policies, horizon=1)["selected_policy_id"], "NO_NEW_ACTION")

        action["identified_set"] = {
            "lower": 0.0,
            "upper": 3.0,
            "unit": "declared_coordinate_burden",
        }
        bounded_runtime = RuntimeV2(spec)
        bounded_state = bounded_runtime.initialize([observation("known-bounded", "OBS_A_LOAD", 0.9)], cut=0)
        bounded_plan = bounded_runtime.plan(bounded_state, policies, horizon=1)
        self.assertIsNone(bounded_plan["selected_policy_id"])
        self.assertEqual(bounded_plan["execution_status"], "ABSTAIN_NO_ROBUST_DOMINANCE")

        identified_spec = model_dict()
        identified_action = next(
            row for row in identified_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )
        identified_action["causal_status"] = "IDENTIFIED_WITHIN_SCOPE"
        identified_action["action_cost"] = 0.0
        identified_runtime = RuntimeV2(identified_spec)
        ood_state = identified_runtime.initialize(
            [observation("unknown-public", "OBS_NOT_IN_MODEL", "novel")],
            cut=0,
        )
        ood_plan = identified_runtime.plan(ood_state, policies, horizon=1)
        self.assertIsNone(ood_plan["selected_policy_id"])
        self.assertEqual(ood_plan["execution_status"], "ABSTAIN_UNMODELED")

    def test_compatible_world_values_form_operative_identified_set_or_abstain(self) -> None:
        spec = model_dict()
        action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
        action["causal_status"] = "PARTIALLY_IDENTIFIED"
        action["action_cost"] = 0.0
        action["compatible_world_values"] = {
            "WORLD_BENEFIT": 0.0,
            "WORLD_HARM": 3.0,
        }
        action["compatible_world_value_unit"] = "declared_coordinate_burden"
        runtime = RuntimeV2(spec)
        state = runtime.initialize([observation("world-state", "OBS_A_LOAD", 0.9)], cut=0)
        action_policy = {
            "policy_id": "ACT",
            "start_actions": [{"action_id": "ACTION_REDUCE_A"}],
        }
        rollout = runtime.rollout(state, action_policy, horizon=1)
        self.assertEqual(
            rollout["decision_value_interval"],
            {
                "lower": 0.0,
                "upper": 3.0,
                "unit": "declared_coordinate_burden",
                "basis": "externally_supplied_complete_outcome_identified_set",
            },
        )
        self.assertEqual(
            rollout["identifiability"]["compatible_world_ids"],
            ["WORLD_BENEFIT", "WORLD_HARM"],
        )
        singleton = runtime.plan(state, [action_policy], horizon=1)
        self.assertIsNone(singleton["selected_policy_id"])
        self.assertEqual(singleton["execution_status"], "ABSTAIN_NO_ROBUST_DOMINANCE")
        compared = runtime.plan(
            state,
            [
                {"policy_id": "NO_NEW_ACTION", "start_actions": []},
                action_policy,
            ],
            horizon=1,
        )
        self.assertIsNone(compared["selected_policy_id"])
        self.assertEqual(compared["execution_status"], "ABSTAIN_NO_ROBUST_DOMINANCE")

    def test_action_effect_bounds_cannot_masquerade_as_outcome_bounds(self) -> None:
        spec = model_dict()
        action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
        action["causal_status"] = "PARTIALLY_IDENTIFIED"
        action["identified_set"] = {
            "lower": -0.3,
            "upper": -0.2,
            "unit": "declared_coordinate_effect",
        }
        with self.assertRaisesRegex(ValueError, "complete post-policy|unit must equal"):
            RuntimeV2(spec)

    def test_partial_outcome_set_excluding_declared_model_point_forces_abstention(self) -> None:
        spec = model_dict()
        action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
        action["causal_status"] = "PARTIALLY_IDENTIFIED"
        action["identified_set"] = {
            "lower": 0.0,
            "upper": 0.0,
            "unit": "declared_coordinate_burden",
        }
        runtime = RuntimeV2(spec)
        state = runtime.initialize([observation("outside-set", "OBS_A_LOAD", 0.9)], cut=0)
        policy = {"policy_id": "ACT", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]}
        rollout = runtime.rollout(state, policy, horizon=1)
        self.assertGreater(rollout["total_objective"], 0.0)
        self.assertEqual(rollout["status"], "UNIDENTIFIABLE")
        self.assertIsNone(rollout["decision_value_interval"])
        self.assertIn(
            "effect bounds cannot be used as outcome bounds",
            " ".join(rollout["identifiability"]["reasons"]),
        )
        plan = runtime.plan(state, [policy], horizon=1)
        self.assertIsNone(plan["selected_policy_id"])

    def test_no_new_action_objective_point_is_inside_derived_support(self) -> None:
        runtime = RuntimeV2(model_dict())
        state = runtime.initialize(
            [
                observation("support-a-marker", "OBS_A_MARKER", True),
                observation("support-b-marker", "OBS_B_MARKER", True),
                observation("support-a-load", "OBS_A_LOAD", 1.0),
                observation("support-b-load", "OBS_B_LOAD", 1.0),
            ],
            cut=0,
        )
        forecast = runtime.forecast(state, horizon=1)
        interval = forecast["decision_value_interval"]
        self.assertIsNotNone(interval)
        self.assertEqual(interval["unit"], "declared_coordinate_burden")
        self.assertGreater(interval["upper"], 1.0)
        self.assertLessEqual(interval["lower"], forecast["total_objective"])
        self.assertGreaterEqual(interval["upper"], forecast["total_objective"])

    def test_action_start_dose_continue_stop_and_washout_are_distinct(self) -> None:
        state0 = self.runtime.initialize([action_event("start", "ActionStarted", at=0, dose=1.0)], cut=0)
        state2 = self.runtime.update(
            state0, [action_event("dose", "ActionDoseChanged", at=2, dose=2.0)], advance_to=2
        )
        self.assertAlmostEqual(action_instance(state2, "exposure-a")["cumulative_exposure"]["value"], 2.0)
        state3 = self.runtime.update(
            state2, [action_event("continue", "ActionContinued", at=3)], advance_to=3
        )
        self.assertAlmostEqual(action_instance(state3, "exposure-a")["cumulative_exposure"]["value"], 4.0)
        stopped4 = self.runtime.update(
            state3, [action_event("stop", "ActionStopped", at=4)], advance_to=4
        )
        continued4 = self.runtime.update(
            state3, [action_event("continue-4", "ActionContinued", at=4)], advance_to=4
        )
        self.assertAlmostEqual(action_instance(stopped4, "exposure-a")["cumulative_exposure"]["value"], 6.0)
        self.assertEqual(action_instance(stopped4, "exposure-a")["status"], "residual")
        stopped5 = self.runtime.update(stopped4, [], advance_to=5)
        continued5 = self.runtime.update(continued4, [], advance_to=5)
        self.assertAlmostEqual(action_instance(stopped5, "exposure-a")["washout"]["estimated_remaining_fraction"], 0.5)
        self.assertNotEqual(
            self.runtime.forecast(stopped5, horizon=1)["action_effective_dose_trace"],
            self.runtime.forecast(continued5, horizon=1)["action_effective_dose_trace"],
        )
        washout_rollout = self.runtime.forecast(stopped4, horizon=3)
        self.assertEqual(
            [row["effective_dose"] for row in washout_rollout["action_effective_dose_trace"]],
            [2.0, 1.0, 0.0],
        )

    def test_action_hold_resume_complete_and_policy_lifecycle_are_executable(self) -> None:
        active = self.runtime.initialize(
            [action_event("life-start", "ActionStarted", at=0, dose=2.0)], cut=0
        )
        held = self.runtime.update(
            active, [action_event("life-hold", "ActionHeld", at=1)], advance_to=1
        )
        self.assertEqual(action_instance(held, "exposure-a")["status"], "held")
        resumed = self.runtime.update(
            held, [action_event("life-resume", "ActionContinued", at=2, dose=1.5)], advance_to=2
        )
        self.assertEqual(action_instance(resumed, "exposure-a")["status"], "active")
        completed = self.runtime.update(
            resumed, [action_event("life-complete", "ActionCompleted", at=3)], advance_to=3
        )
        self.assertEqual(action_instance(completed, "exposure-a")["status"], "completed")
        self.assertAlmostEqual(
            action_instance(completed, "exposure-a")["washout"]["estimated_remaining_fraction"],
            1.0,
        )
        self.assertEqual(
            [
                row["effective_dose"]
                for row in self.runtime.forecast(completed, horizon=3)["action_effective_dose_trace"]
            ],
            [1.5, 0.75, 0.0],
        )
        completed_next = self.runtime.update(completed, [], advance_to=4)
        self.assertEqual(action_instance(completed_next, "exposure-a")["status"], "completed")
        self.assertAlmostEqual(
            action_instance(completed_next, "exposure-a")["washout"]["estimated_remaining_fraction"],
            0.5,
        )
        # Canonical serialization is authoritative: a cold deserialization
        # must preserve the completed lifecycle and its residual rollout.
        completed_cold = SharedPatientState.from_bytes(completed.to_bytes())
        self.assertEqual(
            self.runtime.forecast(completed_cold, horizon=3)["action_effective_dose_trace"],
            self.runtime.forecast(completed, horizon=3)["action_effective_dose_trace"],
        )

        # Terminalizing an already-held exposure changes lifecycle identity
        # but must never restore residual effect that decayed while held.
        held_after_decay = self.runtime.update(held, [], advance_to=2)
        held_remaining = action_instance(held_after_decay, "exposure-a")["washout"][
            "estimated_remaining_fraction"
        ]
        stopped_from_held = self.runtime.update(
            held_after_decay,
            [action_event("life-stop-held", "ActionStopped", at=2)],
            advance_to=2,
        )
        completed_from_held = self.runtime.update(
            held_after_decay,
            [action_event("life-complete-held", "ActionCompleted", at=2)],
            advance_to=2,
        )
        self.assertEqual(action_instance(stopped_from_held, "exposure-a")["status"], "residual")
        self.assertEqual(action_instance(completed_from_held, "exposure-a")["status"], "completed")
        self.assertAlmostEqual(
            action_instance(stopped_from_held, "exposure-a")["washout"][
                "estimated_remaining_fraction"
            ],
            held_remaining,
        )
        self.assertAlmostEqual(
            action_instance(completed_from_held, "exposure-a")["washout"][
                "estimated_remaining_fraction"
            ],
            held_remaining,
        )

        hold_policy = {
            "policy_id": "HOLD_EXISTING",
            "hold_actions": [{"exposure_id": "exposure-a"}],
        }
        hold_rollout = self.runtime.rollout(active, hold_policy, horizon=2)
        self.assertEqual(hold_rollout["policy_lifecycle_trace"][0]["operation"], "hold")
        self.assertEqual(
            [row["effective_dose"] for row in hold_rollout["action_effective_dose_trace"]],
            [2.0, 1.0],
        )
        dose_policy = {
            "policy_id": "DOSE_EXISTING",
            "dose_changes": [{"exposure_id": "exposure-a", "dose": 0.5}],
        }
        self.assertEqual(
            self.runtime.rollout(active, dose_policy, horizon=1)["action_effective_dose_trace"][0]["effective_dose"],
            0.5,
        )
        stop_policy = {
            "policy_id": "STOP_EXISTING",
            "stop_actions": [{"exposure_id": "exposure-a"}],
        }
        self.assertEqual(
            self.runtime.rollout(active, stop_policy, horizon=1)["policy_lifecycle_trace"][0]["operation"],
            "stop",
        )

    def test_planner_excludes_unidentifiable_action_policies(self) -> None:
        state = self.runtime.initialize([], cut=0)
        action_policy = {
            "policy_id": "UNIDENTIFIED_ACTION",
            "start_actions": [{"action_id": "ACTION_REDUCE_A"}],
        }
        plan = self.runtime.plan(
            state,
            [{"policy_id": "NO_NEW_ACTION", "start_actions": []}, action_policy],
            horizon=1,
        )
        self.assertEqual(plan["selected_policy_id"], "NO_NEW_ACTION")
        self.assertEqual(plan["excluded_policy_ids"], ["UNIDENTIFIED_ACTION"])
        only_unidentified = self.runtime.plan(state, [action_policy], horizon=1)
        self.assertIsNone(only_unidentified["selected_policy_id"])

    def test_forecast_with_ongoing_unidentifiable_exposure_remains_unidentifiable(self) -> None:
        active = self.runtime.initialize(
            [action_event("ongoing-unidentified", "ActionStarted", at=0, dose=1.0)],
            cut=0,
        )
        forecast = self.runtime.forecast(active, horizon=1)
        self.assertEqual(forecast["status"], "UNIDENTIFIABLE")
        self.assertEqual(forecast["identifiability"]["status"], "UNIDENTIFIABLE")
        self.assertIn(
            "declared-toy-action-effect",
            forecast["identifiability"]["assumption_ids"],
        )

    def test_unresolved_behavioral_collision_excludes_otherwise_selectable_action(self) -> None:
        spec = model_dict()
        action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
        action["causal_status"] = "PARTIALLY_IDENTIFIED"
        action["action_cost"] = 0.0
        runtime = RuntimeV2(spec)
        state = runtime.initialize([observation("collision-load", "OBS_A_LOAD", 0.9)], cut=0)
        policies = [
            {"policy_id": "NO_NEW_ACTION", "start_actions": []},
            {"policy_id": "ACT", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]},
        ]
        worlds = [
            {"world_id": "W1", "old_state": {"x": 1}, "action_outcomes": {"NO": 0, "ACTION_REDUCE_A": 1}},
            {"world_id": "W2", "old_state": {"x": 1}, "action_outcomes": {"NO": 0, "ACTION_REDUCE_A": -1}},
        ]
        collision = evaluate_behavioral_collision(
            worlds, old_action_ids=["NO"], new_action_id="ACTION_REDUCE_A"
        )
        without = runtime.plan(state, policies, horizon=1)
        with_collision = runtime.plan(
            state, policies, horizon=1, collision_witnesses=[collision]
        )
        # A caller-supplied collision witness is not the only safety barrier:
        # the partially identified action lacks a bounded decision value and
        # therefore cannot win by its declared-model point estimate even when
        # the witness is omitted.
        self.assertEqual(without["selected_policy_id"], "NO_NEW_ACTION")
        self.assertEqual(with_collision["selected_policy_id"], "NO_NEW_ACTION")
        self.assertIn("ACT", with_collision["excluded_policy_ids"])

    def test_unmapped_information_raises_separate_ood_residuals(self) -> None:
        baseline = self.runtime.initialize([], cut=0)
        unknown = observation("u", "OBS_NOT_IN_MODEL", "novel")
        state = self.runtime.update(baseline, [unknown], advance_to=0)
        before = baseline.to_dict()["epistemic_residual"]
        after = state.to_dict()["epistemic_residual"]
        self.assertGreater(after["unmodeled_process"], before["unmodeled_process"])
        self.assertGreater(after["mapping_gap"], before["mapping_gap"])
        self.assertEqual(len(after["unexplained_observations"]), 1)
        self.assertEqual(self.runtime.diagnose(state)["abstention_status"], "partial_answer_only")

    def test_forecast_emits_scoreable_continuous_and_discrete_support(self) -> None:
        state = self.runtime.initialize(
            [observation("support-load", "OBS_A_LOAD", 0.6)], cut=0
        )
        forecast = self.runtime.forecast(state, horizon=2)
        support = forecast["predictive_support"]
        self.assertEqual(support["schema_version"], "ncf.predictive-support.v1")
        realized = {
            "coordinates": {
                pid: {cid: estimate["mean"] for cid, estimate in rows.items()}
                for pid, rows in forecast["final_coordinates"].items()
            },
            "coordinate_directions": {
                row["process_id"]: {
                    row["coordinate_id"]: max(
                        row["probabilities"], key=row["probabilities"].get
                    )
                }
                for row in support["coordinate_directions"]
            },
            "modes": {
                pid: max(probabilities, key=probabilities.get)
                for pid, probabilities in forecast["final_mode_posteriors"].items()
            },
            "process_activation": {
                row["process_id"]: row["p_active"] >= 0.5
                for row in support["process_activation"]
            },
        }
        score = self.runtime.score_predictive_support(forecast, realized)
        self.assertEqual(score["status"], "SUPPORTED")
        self.assertIsInstance(score["aggregate_log_score"], float)
        self.assertEqual(
            score["observed_component_count"], score["required_component_count"]
        )
        empty = self.runtime.score_predictive_support(forecast, {})
        self.assertEqual(empty["status"], "ZERO_OR_UNDEFINED_SUPPORT")
        self.assertEqual(empty["aggregate_log_score"], None)
        self.assertEqual(
            len(empty["missing_component_ids"]), empty["required_component_count"]
        )
        partial = self.runtime.score_predictive_support(
            forecast,
            {
                "coordinates": {
                    "PROCESS_A": {
                        "a_burden": forecast["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"]
                    }
                }
            },
        )
        self.assertEqual(partial["status"], "ZERO_OR_UNDEFINED_SUPPORT")
        self.assertGreater(len(partial["missing_component_ids"]), 0)
        outside = copy.deepcopy(realized)
        outside["coordinates"]["PROCESS_A"]["a_burden"] = 2.0
        rejected = self.runtime.score_predictive_support(forecast, outside)
        self.assertEqual(rejected["status"], "ZERO_OR_UNDEFINED_SUPPORT")
        self.assertIn(
            "coordinate:PROCESS_A:a_burden",
            rejected["zero_or_undefined_support_ids"],
        )

    def test_observed_post_action_coordinate_change_populates_response_memory(self) -> None:
        active = self.runtime.initialize(
            [action_event("response-start", "ActionStarted", at=0, dose=1.0)], cut=0
        )
        responded = self.runtime.update(
            active,
            [observation("response-result", "OBS_A_LOAD", 0.1, at=1)],
            advance_to=1,
        )
        wire = responded.to_dict()
        self.assertEqual(len(wire["history_summary"]["action_response_windows"]), 1)
        instance = action_instance(responded, "exposure-a")
        self.assertEqual(len(instance["response_summaries"]), 1)
        self.assertEqual(instance["response_summaries"][0]["attribution_status"], "descriptive_only")

    def test_topology_changes_rollout_but_partial_action_is_not_point_selected(self) -> None:
        spec = model_dict()
        action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
        action["action_cost"] = 0.27
        action["causal_status"] = "PARTIALLY_IDENTIFIED"
        off = RuntimeV2(spec, topology_enabled=False)
        on = RuntimeV2(spec, topology_enabled=True)
        events = [
            observation("a-marker", "OBS_A_MARKER", True),
            observation("b-marker", "OBS_B_MARKER", True),
            observation("a-load", "OBS_A_LOAD", 0.8),
            observation("b-load", "OBS_B_LOAD", 0.8),
        ]
        state_off = off.initialize(events, cut=0)
        state_on = on.initialize(events, cut=0)
        policies = [
            {"policy_id": "NO_NEW_ACTION", "start_actions": []},
            {"policy_id": "ACT", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]},
        ]
        off_plan = off.plan(state_off, policies, horizon=1)
        on_plan = on.plan(state_on, policies, horizon=1)
        self.assertNotEqual(off.model_digest, on.model_digest)
        with self.assertRaisesRegex(ValueError, "another model digest"):
            on.plan(state_off, policies, horizon=1)
        self.assertEqual(off_plan["selected_policy_id"], "NO_NEW_ACTION")
        self.assertEqual(on_plan["selected_policy_id"], "NO_NEW_ACTION")
        act_rollout = next(row for row in on_plan["policy_rollouts"] if row["policy_id"] == "ACT")
        self.assertTrue(act_rollout["topology_effect_trace"])
        self.assertEqual(act_rollout["status"], "UNIDENTIFIABLE")
        self.assertIsNone(act_rollout["decision_value_interval"])
        self.assertTrue(act_rollout["identifiability"]["assumption_ids"])
        self.assertIn("scope_digest", act_rollout["identifiability"]["scope"])
        self.assertIn("causal_nonidentifiability", act_rollout["identifiability"]["uncertainty"])

    def test_declared_process_coupling_enters_forward_core(self) -> None:
        state = self.runtime.initialize([observation("a-load", "OBS_A_LOAD", 0.8)], cut=0)
        result = self.runtime.forecast(state, horizon=1)
        self.assertTrue(result["process_coupling_trace"])
        self.assertEqual(result["process_coupling_trace"][0]["target_process_id"], "PROCESS_B")
        self.assertTrue(result["mode_coupling_trace"])
        self.assertGreater(
            result["final_mode_posteriors"]["PROCESS_B"]["decompensated"],
            local_modes(state, "PROCESS_B")["decompensated"],
        )

    def test_mode_guard_hysteresis_is_executable_and_ablatable(self) -> None:
        spec = model_dict()
        process = next(row for row in spec["processes"] if row["process_id"] == "PROCESS_A")
        process["coordinates"][0]["prior_mean"] = 0.8
        for mode in process["modes"]:
            mode["prior"] = 0.98 if mode["mode_id"] == "compensated" else 0.01
            if mode["mode_id"] == "decompensated":
                mode["coordinate_drift"]["a_burden"] = 0.1
            else:
                mode["coordinate_drift"]["a_burden"] = 0.0
        process["mode_guards"] = [
            {
                "guard_id": "A_ENTER_DECOMP",
                "coordinate_id": "a_burden",
                "source_mode_id": "compensated",
                "target_mode_id": "decompensated",
                "direction": "above",
                "enter_threshold": 0.7,
                "exit_threshold": 0.5,
                "transition_probability": 1.0,
            }
        ]
        enabled = RuntimeV2(spec, mode_guards_enabled=True)
        disabled = RuntimeV2(spec, mode_guards_enabled=False)
        enabled_state = enabled.initialize([], cut=0)
        disabled_state = disabled.initialize([], cut=0)
        enabled_result = enabled.forecast(enabled_state, horizon=2)
        disabled_result = disabled.forecast(disabled_state, horizon=2)
        self.assertNotEqual(enabled.model_digest, disabled.model_digest)
        with self.assertRaisesRegex(ValueError, "another model digest"):
            disabled.forecast(enabled_state, horizon=2)
        self.assertEqual(
            max(enabled_result["final_mode_posteriors"]["PROCESS_A"], key=enabled_result["final_mode_posteriors"]["PROCESS_A"].get),
            "decompensated",
        )
        self.assertGreater(
            enabled_result["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"],
            disabled_result["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"],
        )
        self.assertTrue(any(row["transition"] == "compensated->decompensated" for row in enabled_result["mode_guard_trace"]))

        hold_spec = copy.deepcopy(spec)
        hold_process = next(row for row in hold_spec["processes"] if row["process_id"] == "PROCESS_A")
        hold_process["coordinates"][0]["prior_mean"] = 0.6
        for mode in hold_process["modes"]:
            mode["prior"] = 0.98 if mode["mode_id"] == "decompensated" else 0.01
            mode["coordinate_drift"]["a_burden"] = 0.0
        hold_result = RuntimeV2(hold_spec).forecast(RuntimeV2(hold_spec).initialize([], cut=0), horizon=1)
        self.assertTrue(any(row["transition"] == "HYSTERESIS_HOLD" for row in hold_result["mode_guard_trace"]))
        self.assertEqual(
            max(hold_result["final_mode_posteriors"]["PROCESS_A"], key=hold_result["final_mode_posteriors"]["PROCESS_A"].get),
            "decompensated",
        )


class CollisionAndRefinementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = model_dict()
        self.runtime = RuntimeV2(self.spec)
        self.worlds = [
            {
                "world_id": "WORLD_POSITIVE_RESPONSE",
                "old_state": {"PROCESS_A": {"burden": 0.5, "mode": "compensated"}},
                "action_outcomes": {"OLD_NOOP": 0.2, "NEW_ACTION": 1.0},
            },
            {
                "world_id": "WORLD_NEGATIVE_RESPONSE",
                "old_state": {"PROCESS_A": {"burden": 0.5, "mode": "compensated"}},
                "action_outcomes": {"OLD_NOOP": 0.2, "NEW_ACTION": -1.0},
            },
        ]
        self.collision = evaluate_behavioral_collision(
            self.worlds,
            old_action_ids=["OLD_NOOP"],
            new_action_id="NEW_ACTION",
        )
        self.refinement = {
            "target_model_id": "neutral-factorial-model-refined",
            "process_id": "PROCESS_A",
            "child_strata": [
                {
                    "stratum_id": "stratum:PROCESS_A:positive-response",
                    "prior": 0.5,
                    "compatible_world_ids": ["WORLD_POSITIVE_RESPONSE"],
                    "likelihood": {"family": "bernoulli", "p_true": 0.9},
                },
                {
                    "stratum_id": "stratum:PROCESS_A:negative-response",
                    "prior": 0.5,
                    "compatible_world_ids": ["WORLD_NEGATIVE_RESPONSE"],
                    "likelihood": {"family": "bernoulli", "p_true": 0.1},
                },
            ],
            "separating_observation": {
                "concept_id": "OBS_RESPONSE_SEPARATOR",
                "factor_id": "FACTOR_RESPONSE_SEPARATOR",
                "neutral_process_likelihood": {"family": "bernoulli", "p_true": 0.5},
            },
            "new_action_spec": {
                "action_id": "NEW_ACTION",
                "dose_reference": 1.0,
                "washout_steps": 1.0,
                "action_cost": 0.01,
                "causal_status": "UNIDENTIFIABLE",
                "assumption_ids": ["behavioral-collision-refinement-witness"],
                "identifiability_reason": "The action is registered for explicit collision/refinement testing only.",
                "effects": [
                    {
                        "process_id": "PROCESS_A",
                        "coordinate_id": "a_burden",
                        "delta_per_unit_step": -0.25,
                    }
                ],
            },
        }

    def test_collision_without_separator_is_typed_unidentifiable(self) -> None:
        self.assertEqual(self.collision["status"], "COLLISION_WITNESS")
        state = self.runtime.initialize([], cut=0)
        result = execute_local_refinement(
            state,
            self.spec,
            self.collision,
            self.refinement,
            separating_event=None,
            migration_id="unused-without-separator",
        )
        self.assertEqual(result["status"], "UNIDENTIFIABLE")
        self.assertFalse(result["model_changed"])
        self.assertEqual(len(result["compatible_world_ids"]), 2)

    def test_separator_splits_only_local_stratum_with_migration_and_non_regression(self) -> None:
        state = self.runtime.initialize(
            [observation("pre-refine", "OBS_B_MARKER", True)], cut=0
        )
        separating_event = observation(
            "separator-result", "OBS_RESPONSE_SEPARATOR", True, at=1
        )
        execution = execute_local_refinement(
            state,
            self.spec,
            self.collision,
            self.refinement,
            separating_event=separating_event,
            migration_id="local-stratum-refinement-v1",
        )
        self.assertEqual(execution.report["status"], "REFINED")
        self.assertTrue(execution.report["old_scope_process_posterior_non_regression"])
        self.assertTrue(all(execution.report["unrelated_processes_unchanged"].values()))
        non_regression = execution.report["old_scope_query_non_regression"]
        self.assertEqual(non_regression["status"], "PASS")
        self.assertEqual(non_regression["absolute_tolerance"], 1e-12)
        self.assertEqual(
            set(non_regression["query_manifest"]),
            {
                "diagnose",
                "forecast_no_new_action",
                "rollout_unaffected:ACTION_REDUCE_A",
                "rollout_unaffected:ACTION_REDUCE_C",
                "plan_unaffected_policies",
            },
        )
        self.assertTrue(
            all(
                row["within_tolerance"]
                for row in non_regression["query_manifest"].values()
            )
        )
        self.assertEqual(
            execution.migrated_state.to_dict()["model_lineage"]["migration_id"],
            "local-stratum-refinement-v1",
        )
        old_marginals = activation_marginals(state)
        migrated_marginals = activation_marginals(execution.migrated_state)
        refined_marginals = activation_marginals(execution.refined_state)
        for pid in self.runtime.process_ids:
            self.assertAlmostEqual(old_marginals[pid], migrated_marginals[pid])
            self.assertAlmostEqual(old_marginals[pid], refined_marginals[pid])
        strata = execution.runtime.diagnose(execution.refined_state)["local_stratum_posteriors"]
        self.assertGreater(strata["PROCESS_A"]["stratum:PROCESS_A:positive-response"], 0.8)
        self.assertEqual(list(strata["PROCESS_B"]), ["stratum:PROCESS_B"])
        source_forecast = self.runtime.forecast(state, horizon=1)
        migrated_forecast = execution.runtime.forecast(execution.migrated_state, horizon=1)
        self.assertAlmostEqual(
            source_forecast["expected_coordinate_burden"],
            migrated_forecast["expected_coordinate_burden"],
        )

    def test_opposite_refined_strata_modulate_action_dynamics_in_opposite_directions(self) -> None:
        spec = model_dict()
        source_runtime = RuntimeV2(spec)
        source = source_runtime.initialize(
            [observation("refined-load", "OBS_A_LOAD", 0.7)], cut=0
        )
        worlds = [
            {
                "world_id": "ACTION_POSITIVE_WORLD",
                "old_state": {"same": True},
                "action_outcomes": {"NO": 0.0, "ACTION_REDUCE_A": 1.0},
            },
            {
                "world_id": "ACTION_NEGATIVE_WORLD",
                "old_state": {"same": True},
                "action_outcomes": {"NO": 0.0, "ACTION_REDUCE_A": -1.0},
            },
        ]
        collision = evaluate_behavioral_collision(
            worlds, old_action_ids=["NO"], new_action_id="ACTION_REDUCE_A"
        )
        refinement = copy.deepcopy(self.refinement)
        refinement.pop("new_action_spec")
        refinement["child_strata"][0]["compatible_world_ids"] = ["ACTION_POSITIVE_WORLD"]
        refinement["child_strata"][1]["compatible_world_ids"] = ["ACTION_NEGATIVE_WORLD"]
        positive = execute_local_refinement(
            source,
            spec,
            collision,
            refinement,
            separating_event=observation("positive-separator", "OBS_RESPONSE_SEPARATOR", True, at=1),
            migration_id="action-stratum-positive",
        )
        negative = execute_local_refinement(
            source,
            spec,
            collision,
            refinement,
            separating_event=observation("negative-separator", "OBS_RESPONSE_SEPARATOR", False, at=1),
            migration_id="action-stratum-negative",
        )
        policy = {"policy_id": "ACT", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]}
        positive_noop = positive.runtime.forecast(positive.refined_state, horizon=1)
        negative_noop = negative.runtime.forecast(negative.refined_state, horizon=1)
        positive_action = positive.runtime.rollout(positive.refined_state, policy, horizon=1)
        negative_action = negative.runtime.rollout(negative.refined_state, policy, horizon=1)
        positive_effect = (
            positive_action["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"]
            - positive_noop["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"]
        )
        negative_effect = (
            negative_action["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"]
            - negative_noop["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"]
        )
        self.assertLess(positive_effect * negative_effect, 0.0)
        self.assertNotEqual(
            positive_action["action_stratum_modifier_trace"],
            negative_action["action_stratum_modifier_trace"],
        )


class MigrationTests(unittest.TestCase):
    def test_changed_model_digest_fails_without_migration(self) -> None:
        source_runtime = RuntimeV2.from_json(MODEL_PATH)
        source_state = source_runtime.initialize([], cut=0)
        target_spec = model_dict()
        target_spec["model_id"] = "neutral-revision"
        target_runtime = RuntimeV2(target_spec)
        with self.assertRaisesRegex(ValueError, "explicit migration required"):
            target_runtime.diagnose(source_state)

    def test_v2_to_v2_migration_preserves_mapped_joint_and_adds_new_process(self) -> None:
        source_spec = model_dict()
        source_runtime = RuntimeV2(source_spec)
        source_state = source_runtime.initialize(
            [observation("a", "OBS_A_MARKER", True), observation("b", "OBS_B_MARKER", True)],
            cut=0,
        )
        target_spec = model_dict()
        target_spec["model_id"] = "neutral-with-process-d"
        process_d = copy.deepcopy(target_spec["processes"][2])
        process_d["process_id"] = "PROCESS_D"
        process_d["organ_or_domain"] = "DOMAIN_D"
        process_d["coordinates"][0]["coordinate_id"] = "d_burden"
        for mode in process_d["modes"]:
            value = mode["coordinate_drift"].pop("c_burden")
            mode["coordinate_drift"]["d_burden"] = value
        target_spec["processes"].append(process_d)
        target_runtime = RuntimeV2(target_spec)
        migration = {
            "migration_id": "add-process-d-v1",
            "from_model_digest": source_runtime.model_digest,
            "to_model_digest": target_runtime.model_digest,
            "process_map": {pid: pid for pid in source_runtime.process_ids},
            "coordinate_maps": {
                "PROCESS_A": {"a_burden": "a_burden"},
                "PROCESS_B": {"b_burden": "b_burden"},
                "PROCESS_C": {"c_burden": "c_burden"}
            },
            "mode_maps": {
                pid: {mid: mid for mid in ("compensated", "decompensated", "recovering")}
                for pid in source_runtime.process_ids
            },
            "action_map": {action_id: action_id for action_id in source_runtime.actions},
        }
        migrated = migrate_v2_state(source_state, source_spec, target_runtime, migration)
        for pid in source_runtime.process_ids:
            self.assertAlmostEqual(
                activation_marginals(migrated)[pid],
                activation_marginals(source_state)[pid],
            )
        self.assertAlmostEqual(
            activation_marginals(migrated)["PROCESS_D"],
            process_d["activation_prior"],
        )
        self.assertEqual(migrated.to_dict()["event_lineage"]["parent_state_hash"], source_state.state_hash)
        self.assertEqual(migrated.to_dict()["model_lineage"]["migration_id"], "add-process-d-v1")

    def test_legacy_simplex_import_is_executable_and_marks_information_loss(self) -> None:
        runtime = RuntimeV2.from_json(MODEL_PATH)
        legacy = {
            "protocol_version": "new-clinical-framework-minimum/1",
            "model_digest": "legacy-model-digest",
            "available_cut": 3,
            "branch_posterior": {"OLD_A": 0.4, "OLD_B": 0.3, "OLD_C": 0.1},
            "unknown_mass": 0.2,
            "per_branch": {
                "OLD_A": {
                    "local_coordinates": {"old_load": 0.7},
                    "mode_posterior": {"recovering": 0.8, "compensated": 0.2},
                },
                "OLD_B": {"local_coordinates": {}, "mode_posterior": {"decompensated": 1.0}},
                "OLD_C": {"local_coordinates": {}, "mode_posterior": {"compensated": 1.0}},
            },
            "history_summary": {},
            "action_exposure": {},
            "recognized_observation_count": 3,
            "unrecognized_observation_count": 1,
        }
        migration = {
            "migration_id": "legacy-import-1",
            "process_map": {"OLD_A": "PROCESS_A", "OLD_B": "PROCESS_B", "OLD_C": "PROCESS_C"},
            "coordinate_maps": {"OLD_A": {"old_load": "a_burden"}},
            "mode_maps": {
                "OLD_A": {"recovering": "recovering", "compensated": "compensated"},
                "OLD_B": {"decompensated": "decompensated"},
                "OLD_C": {"compensated": "compensated"},
            },
            "action_map": {},
        }
        migrated = import_legacy_v1_state(legacy, runtime, migration)
        marginals = activation_marginals(migrated)
        self.assertAlmostEqual(marginals["PROCESS_A"], 0.4)
        self.assertAlmostEqual(marginals["PROCESS_B"], 0.3)
        self.assertAlmostEqual(migrated.to_dict()["epistemic_residual"]["unmodeled_process"], 0.2)
        coactive = sum(
            row["probability"]
            for row in migrated.to_dict()["active_process_posterior"]["joint_hypotheses"]
            if {"PROCESS_A", "PROCESS_B"}.issubset(row["active_process_ids"])
        )
        self.assertGreater(coactive, 0.0)
        self.assertEqual(migrated.to_dict()["model_lineage"]["migration_id"], "legacy-import-1")


if __name__ == "__main__":
    unittest.main()
