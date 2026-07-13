#!/usr/bin/env python3
"""Private preregistered generator for the bridge holdout.

This is intentionally outside the repository until both implementations are
sealed.  It generates an implementation-neutral semantic corpus, not candidate
API calls.  The post-seal step may only bind the resulting objects to the
already-frozen public transport; it may not change case semantics or oracles.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable


CASE_ROWS = [
    ("H01", "DBN baseline audit round trip", "root scope time versions uncertainty"),
    ("H02", "SCM baseline audit round trip", "root scope time versions causal"),
    ("H03", "alias and fan-out root idempotence", "root proof order"),
    ("H04", "singleton multi-root refusal and time-series liveness", "root negative"),
    ("H05", "raw canary and no synthetic root", "root raw tamper"),
    ("H06", "availability boundary", "time boundary"),
    ("H07", "half-open end and unknown clock", "time boundary negative"),
    ("H08", "filter versus informative smooth", "time filter_smooth uncertainty"),
    ("H09", "equal numeric filter/smooth remain typed", "filter_smooth"),
    ("H10", "upstream/downstream cut mismatch", "time negative"),
    ("H11", "as-then versus current model", "versions replay"),
    ("H12", "future bridge and unavailable model version", "versions negative"),
    ("H13", "correction retraction clean rebuild", "root versions delta"),
    ("H14", "unresolved version fork", "versions negative taint"),
    ("H15", "schema mismatch without migration", "versions negative raw"),
    ("H16", "three uncertainty channels", "uncertainty"),
    ("H17", "uncertainty channel isolation", "uncertainty relational"),
    ("H18", "censor and interval discrimination", "measurement negative"),
    ("H19", "masked absent unknown conflict", "measurement taint negative"),
    ("H20", "confounded condition versus do", "causal condition_do_aap"),
    ("H21", "shared-world AAP", "causal condition_do_aap root"),
    ("H22", "AAP policy and factual visibility failures", "causal time negative"),
    ("H23", "plan/performed and forecast/do", "causal time negative"),
    ("H24", "scope and role crossing", "scope negative"),
    ("H25", "unknown mapping and legal conversion", "measurement versions negative raw"),
    ("H26", "digest/vector/oracle-field tamper", "tamper negative"),
    ("H27", "alpha rename and module permutation", "order alias"),
    ("H28", "warm cache cut isolation", "time versions cache"),
    ("H29", "full state cross case", "root time versions uncertainty filter_smooth delta"),
    ("H30", "full causal cross case", "root time versions uncertainty condition_do_aap delta"),
    ("H31", "DBN query target binding", "query filter_smooth negative"),
    ("H32", "root and dependence duplicate likelihood", "root uncertainty negative"),
    ("H33", "post-transaction correction invisibility", "time versions delta"),
    ("H34", "supersedes graph pathology", "root versions delta negative"),
    ("H35", "SCM population selector provenance", "root scope condition_do_aap negative"),
    ("H36", "encounter and specimen scope mismatch", "scope root negative"),
    ("H37", "post-cut correction and retraction pair", "root time delta"),
    ("H38", "absent and censored DBN semantics", "measurement uncertainty filter_smooth negative"),
    ("H39", "query outside target window", "query time negative"),
    ("H40", "SCM exogenous endogenous namespace collision", "condition_do_aap negative"),
    ("H41", "empty dependence family rejection", "root uncertainty negative"),
]


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def frac_value(value: Fraction) -> dict[str, Any]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": float(value),
    }


def opaque(seed: int, namespace: str, index: int = 0) -> str:
    data = f"{seed:064x}|{namespace}|{index}".encode()
    return f"{namespace[:2]}_{hashlib.sha256(data).hexdigest()[:14]}"


def bernoulli(value: int, p1: Fraction) -> Fraction:
    return p1 if value == 1 else 1 - p1


def enumerate_dbn(
    model: dict[str, Any], observations: dict[int, int], *, target: int
) -> Fraction:
    """Exact posterior P(X_target=1 | supplied observations)."""

    horizon = max([target, *observations.keys()])
    numerator = Fraction(0)
    denominator = Fraction(0)
    for member in model["epistemic_members"]:
        member_weight = Fraction(*member["weight"])
        prior = Fraction(*member["prior_x1"])
        transition = {
            int(x): Fraction(*p) for x, p in member["transition_no_action_p1"].items()
        }
        for path in itertools.product((0, 1), repeat=horizon + 1):
            probability = member_weight * bernoulli(path[0], prior)
            for time_index in range(horizon):
                probability *= bernoulli(path[time_index + 1], transition[path[time_index]])
            for time_index, observed in observations.items():
                p_y1 = Fraction(*model["measurement"]["p_y1_given_x"][str(path[time_index])])
                probability *= bernoulli(observed, p_y1)
            denominator += probability
            if path[target] == 1:
                numerator += probability
    if denominator == 0:
        raise ValueError("zero-probability DBN evidence")
    return numerator / denominator


def make_dbn(rng: random.Random, seed: int, aliases: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    for _ in range(10_000):
        member_weight = Fraction(rng.randint(38, 62), 100)
        prior = Fraction(rng.randint(38, 58), 100)
        base_q0 = Fraction(rng.randint(15, 23), 100)
        base_q1 = Fraction(rng.randint(78, 87), 100)
        delta0 = Fraction(rng.randint(2, 5), 100)
        delta1 = Fraction(rng.randint(2, 5), 100)
        fpr = Fraction(rng.randint(11, 20), 100)
        sens = Fraction(rng.randint(80, 91), 100)
        members = [
            {
                "member_id": opaque(seed, "theta", 0),
                "weight": [member_weight.numerator, member_weight.denominator],
                "prior_x1": [prior.numerator, prior.denominator],
                "transition_no_action_p1": {
                    "0": [base_q0.numerator, base_q0.denominator],
                    "1": [base_q1.numerator, base_q1.denominator],
                },
                "transition_performed_action_p1": {
                    "0": [max(Fraction(3, 100), base_q0 - Fraction(8, 100)).numerator,
                          max(Fraction(3, 100), base_q0 - Fraction(8, 100)).denominator],
                    "1": [max(Fraction(45, 100), base_q1 - Fraction(25, 100)).numerator,
                          max(Fraction(45, 100), base_q1 - Fraction(25, 100)).denominator],
                },
            },
            {
                "member_id": opaque(seed, "theta", 1),
                "weight": [(1 - member_weight).numerator, (1 - member_weight).denominator],
                "prior_x1": [prior.numerator, prior.denominator],
                "transition_no_action_p1": {
                    "0": [(base_q0 + delta0).numerator, (base_q0 + delta0).denominator],
                    "1": [(base_q1 - delta1).numerator, (base_q1 - delta1).denominator],
                },
                "transition_performed_action_p1": {
                    "0": [max(Fraction(3, 100), base_q0 + delta0 - Fraction(8, 100)).numerator,
                          max(Fraction(3, 100), base_q0 + delta0 - Fraction(8, 100)).denominator],
                    "1": [max(Fraction(45, 100), base_q1 - delta1 - Fraction(25, 100)).numerator,
                          max(Fraction(45, 100), base_q1 - delta1 - Fraction(25, 100)).denominator],
                },
            },
        ]
        model = {
            "model_kind": "finite_state_dbn",
            "schema_version": opaque(seed, "schema", 0),
            "model_id": opaque(seed, "model", 0),
            "model_version": opaque(seed, "modelv", 0),
            "state_concept": aliases["state"],
            "observation_concept": aliases["observation"],
            "action_concept": aliases["action"],
            "epistemic_members": members,
            "measurement": {
                "kind": "binary_confusion_matrix",
                "method_id": opaque(seed, "method", 0),
                "method_version": opaque(seed, "methodv", 0),
                "p_y1_given_x": {
                    "0": [fpr.numerator, fpr.denominator],
                    "1": [sens.numerator, sens.denominator],
                },
            },
            "uncertainty_contract": {
                "aleatoric": "stochastic_state_transition",
                "epistemic": "finite_fixed_member_ensemble",
                "measurement": "binary_confusion_matrix",
            },
        }
        filtered = enumerate_dbn(model, {0: 0, 1: 0}, target=1)
        smoothed = enumerate_dbn(model, {0: 0, 1: 0, 2: 1}, target=1)
        if abs(smoothed - filtered) >= Fraction(4, 100):
            oracle = {
                "filter_x1": frac_value(filtered),
                "smooth_x1": frac_value(smoothed),
                "minimum_separation": 0.04,
            }
            return model, oracle
    raise RuntimeError("could not generate a separated DBN fixture")


WORLD_SHAPES = [
    (1, 1, 1),
    (1, 1, 0),
    (1, 0, 1),
    (1, 0, 0),
    (0, 1, 1),
    (0, 1, 0),
    (0, 0, 1),
    (0, 0, 0),
]


def scm_values(worlds: list[dict[str, Any]]) -> dict[str, Fraction]:
    def total(predicate: Any) -> Fraction:
        return sum((Fraction(*w["weight"]) for w in worlds if predicate(w)), Fraction(0))

    t1 = total(lambda w: w["observed_t"] == 1)
    t0 = 1 - t1
    condition1 = total(lambda w: w["observed_t"] == 1 and w["y1"] == 1) / t1
    condition0 = total(lambda w: w["observed_t"] == 0 and w["y0"] == 1) / t0
    do1 = total(lambda w: w["y1"] == 1)
    do0 = total(lambda w: w["y0"] == 1)
    factual = total(lambda w: w["observed_t"] == 1 and w["y1"] == 1)
    aap0 = total(lambda w: w["observed_t"] == 1 and w["y1"] == 1 and w["y0"] == 1) / factual
    return {
        "condition_t1": condition1,
        "condition_t0": condition0,
        "do_t1": do1,
        "do_t0": do0,
        "aap_do_t0_given_factual_t1_y1": aap0,
    }


def make_scm(rng: random.Random, seed: int, aliases: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    template = [30, 15, 5, 5, 5, 15, 5, 20]
    for _ in range(10_000):
        counts = [max(1, item + rng.randint(-2, 2)) for item in template]
        denominator = sum(counts)
        worlds = []
        for index, (count, shape) in enumerate(zip(counts, WORLD_SHAPES)):
            t, y0, y1 = shape
            worlds.append(
                {
                    "world_id": opaque(seed, "world", index),
                    "weight": [count, denominator],
                    "observed_t": t,
                    "y0": y0,
                    "y1": y1,
                }
            )
        values = scm_values(worlds)
        if (
            values["condition_t1"] - values["condition_t0"] > Fraction(1, 10)
            and values["do_t0"] - values["do_t1"] > Fraction(1, 10)
            and values["aap_do_t0_given_factual_t1_y1"] - values["do_t0"] > Fraction(1, 10)
            and len(set(values.values())) >= 4
        ):
            rng.shuffle(worlds)
            model = {
                "model_kind": "finite_possible_world_scm",
                "schema_version": opaque(seed, "schema", 1),
                "model_id": opaque(seed, "model", 1),
                "model_version": opaque(seed, "modelv", 1),
                "treatment_concept": aliases["treatment"],
                "outcome_concept": aliases["outcome"],
                "worlds": worlds,
                "identification_contract": "explicit_finite_world_enumeration",
                "shared_world_policy": "retain_abduced_world_identity",
            }
            return model, {key: frac_value(value) for key, value in values.items()}
    raise RuntimeError("could not generate a separated SCM fixture")


def root(
    seed: int,
    index: int,
    concept: str,
    value: Any,
    occurrence: str,
    available: str,
    *,
    role: str = "observed",
    value_kind: str = "exact",
) -> dict[str, Any]:
    raw = {
        "reported_value": value,
        "reported_unit": "1",
        "source_text": f"opaque-{opaque(seed, 'canary', index)}",
        "source_span": [index * 11, index * 11 + 7],
    }
    return {
        "artifact_id": opaque(seed, "artifact", index),
        "artifact_version": opaque(seed, "artifactv", index),
        "logical_id": opaque(seed, "logical", index),
        "root_occurrence_id": opaque(seed, "root", index),
        "root_version": opaque(seed, "rootv", index),
        "semantic_role": role,
        "concept": concept,
        "value": {"kind": value_kind, "value": value, "unit": "1"},
        "scope": {
            "subject": opaque(seed, "subject", 0),
            "encounter": opaque(seed, "encounter", 0),
            "specimen": None,
            "device": opaque(seed, "device", index),
            "site": opaque(seed, "site", 0),
            "body_site": None,
        },
        "times": {
            "occurrence": occurrence,
            "collection": occurrence,
            "available_to_actor": available,
            "source_recorded": available,
            "kernel_committed": available,
            "effective_end": None,
        },
        "raw_payload": raw,
        "raw_digest": digest(raw),
        "source_span": {"start": index * 11, "end": index * 11 + 7},
        "mapping_version": opaque(seed, "mappingv", 0),
        "dependence_families": [opaque(seed, "dep", index)],
    }


def make_cases(seed: int, aliases: dict[str, str], roots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    common = {
        "positive_success": ["execution_completed", "native_invoked", "audit_roundtrip_isomorphic"],
        "negative_failure": ["typed_failure", "native_not_invoked", "no_disallowed_root_consumed"],
    }
    templates: dict[str, dict[str, Any]] = {
        "H01": {"family": "dbn", "fixture": "base_dbn", "oracle": common["positive_success"]},
        "H02": {"family": "scm", "fixture": "base_scm", "oracle": common["positive_success"]},
        "H03": {"family": "both", "mutation": "alias_fanout_fanin_same_root", "oracle": ["root_count=1", "proof_dag_isomorphic"]},
        "H04": {"family": "both", "mutation": "two_roots_singleton_port", "oracle": common["negative_failure"] + ["error=ambiguous_input", "time_series_control_accepts_both"]},
        "H05": {"family": "both", "mutation": "raw_canary_only", "oracle": ["model_value_equal_control", "raw_digest_differs", "no_synthetic_raw_root"]},
        "H06": {"family": "both", "mutation": "available_boundary_pair", "oracle": ["at_boundary_included", "plus_epsilon_excluded"]},
        "H07": {"family": "both", "mutation": "effective_end_and_unknown_clock", "oracle": ["half_open_end_excluded", "unknown_clock_typed_failure"]},
        "H08": {"family": "dbn", "fixture": "base_dbn", "queries": ["filter_t1", "smooth_t1_later_y2"], "oracle": ["exact_finite_values", "filter_value!=smooth_value", "operator_and_policy_distinct"]},
        "H09": {"family": "dbn", "mutation": "remove_later_evidence", "queries": ["filter_t1", "smooth_t1"], "oracle": ["values_equal", "operator_and_witness_distinct"]},
        "H10": {"family": "both", "mutation": "target_window_mismatch", "oracle": common["negative_failure"] + ["error=cut_mismatch"]},
        "H11": {"family": "both", "mutation": "version_v1_v2", "oracle": ["as_then_uses_v1", "reinterpret_uses_v2", "roots_equal", "outputs_differ"]},
        "H12": {"family": "both", "mutation": "future_bridge_or_missing_model", "oracle": common["negative_failure"] + ["error=version_unavailable"]},
        "H13": {"family": "both", "mutation": "correct_retract_alternative", "oracle": ["incremental_equals_clean", "old_cut_stable", "alternative_witness_shrinks"]},
        "H14": {"family": "both", "mutation": "unresolved_version_fork", "oracle": common["negative_failure"] + ["taint=conflicting_versions", "not_last_write_wins"]},
        "H15": {"family": "both", "mutation": "schema_without_migration", "oracle": common["negative_failure"] + ["error=migration_required", "raw_retained"]},
        "H16": {"family": "dbn", "fixture": "base_dbn", "oracle": ["three_uncertainty_channels_exact", "no_flat_confidence"]},
        "H17": {"family": "dbn", "mutation": "uncertainty_one_at_a_time", "oracle": ["channel_isolation_relations"]},
        "H18": {"family": "both", "mutation": "censor_interval_pairs", "oracle": ["sum_type_discriminants_preserved", "no_scalar_collapse"]},
        "H19": {"family": "both", "mutation": "masked_absent_unknown_conflict", "oracle": ["states_pairwise_distinct", "masked_no_payload", "taints_preserved"]},
        "H20": {"family": "scm", "fixture": "base_scm", "queries": ["condition_t1", "condition_t0", "do_t1", "do_t0"], "oracle": ["exact_finite_values", "observational_direction_reversed_from_do"]},
        "H21": {"family": "scm", "fixture": "base_scm", "queries": ["aap_do_t0_given_factual_t1_y1", "do_t0"], "oracle": ["exact_finite_values", "aap!=population_do", "factual_roots_consumed"]},
        "H22": {"family": "scm", "mutation": "missing_shared_policy_or_late_factual", "oracle": common["negative_failure"] + ["error_in=[not_identified,insufficient]"]},
        "H23": {"family": "both", "mutation": "plan_performed_forecast_do", "oracle": ["plan_equals_no_action", "performed_differs", "forecast_operator!=do_operator"]},
        "H24": {"family": "both", "mutation": "cross_scope_and_role_upgrade", "oracle": common["negative_failure"] + ["error_in=[scope_mismatch,illegal_role_coercion]"]},
        "H25": {"family": "both", "mutation": "unknown_mapping_and_legal_control", "oracle": ["unknown_quarantined_raw_retained", "legal_conversion_inverse_witness"]},
        "H26": {"family": "both", "mutation": "integrity_or_runner_field_tamper", "oracle": common["negative_failure"] + ["error_in=[integrity_failure,closed_schema_failure]"]},
        "H27": {"family": "both", "mutation": "alpha_rename_and_module_shuffle", "oracle": ["semantic_isomorphism", "no_name_or_order_dispatch"]},
        "H28": {"family": "both", "mutation": "warm_future_then_old_cut", "oracle": ["old_warm_equals_old_cold"]},
        "H29": {"family": "dbn", "mutation": "full_state_cross", "oracle": ["all_exact_roundtrip", "exact_smooth", "incremental_equals_clean"]},
        "H30": {"family": "scm", "mutation": "full_causal_cross", "oracle": ["all_exact_roundtrip", "exact_aap", "incremental_equals_clean"]},
        "H31": {"family": "dbn", "mutation": "query_target_unknown_or_cross_bound", "oracle": common["negative_failure"] + ["error=query_target_unbound", "no_posterior_under_wrong_target"]},
        "H32": {"family": "dbn", "mutation": "same_root_alias_and_same_dependence_family_duplicates", "oracle": ["same_root_duplicate_equals_single", "same_family_requires_declared_joint_model_or_typed_reject", "independent_family_control_changes_posterior", "consumed_roots_are_set_union"]},
        "H33": {"family": "both", "mutation": "correction_registered_after_transaction_cut", "oracle": ["old_cut_equals_clean_pre_correction", "post_cut_root_not_consumed", "new_cut_may_apply_correction"]},
        "H34": {"family": "both", "mutation": "supersedes_self_cycle_and_unresolved_fork", "oracle": common["negative_failure"] + ["error_in=[self_supersedes,cycle,conflicting_versions]", "not_last_write_wins"]},
        "H35": {"family": "scm", "mutation": "population_selector_requires_evidence", "oracle": ["selector_roots_consumed_or_typed_reject", "silent_unselected_population_forbidden", "selector_and_unselected_control_differ"]},
        "H36": {"family": "both", "mutation": "same_subject_other_encounter_or_specimen", "oracle": common["negative_failure"] + ["error=scope_mismatch", "no_subject_only_fallback"]},
        "H37": {"family": "both", "mutation": "correction_and_retraction_both_after_cut", "oracle": ["both_invisible_at_old_cut", "incremental_old_equals_clean_old", "later_cut_applies_in_transaction_order"]},
        "H38": {"family": "dbn", "mutation": "absent_and_below_detection_observations", "oracle": ["absent_not_silently_skipped_to_prior", "censored_executes_as_typed_likelihood_or_typed_unsupported", "no_green_prior_laundering"]},
        "H39": {"family": "both", "mutation": "query_time_before_or_after_target_window", "oracle": common["negative_failure"] + ["error=query_outside_frozen_target_window"]},
        "H40": {"family": "scm", "mutation": "same_symbol_exogenous_and_endogenous", "oracle": common["negative_failure"] + ["error=causal_namespace_collision", "no_environment_shadowing"]},
        "H41": {"family": "both", "mutation": "root_with_empty_dependence_families", "oracle": common["negative_failure"] + ["error=missing_dependence_family", "no_implicit_independence"]},
    }
    cases = []
    for case_id, title, coverage in CASE_ROWS:
        body = templates[case_id]
        cases.append({"case_id": case_id, "title": title, "coverage": coverage.split(), **body})
    return cases


def build(seed: int, *, seals: dict[str, str], reveal_time: str) -> dict[str, Any]:
    rng = random.Random(seed)
    aliases = {
        key: opaque(seed, key, 0)
        for key in ("state", "observation", "action", "treatment", "outcome")
    }
    iso_aliases = {
        key: opaque(seed, f"iso_{key}", 0)
        for key in aliases
    }
    dbn, dbn_oracle = make_dbn(rng, seed, aliases)
    scm, scm_oracle = make_scm(rng, seed, aliases)
    timeline = [
        "2037-04-11T08:00:00Z",
        "2037-04-11T09:00:00Z",
        "2037-04-11T10:00:00Z",
    ]
    dbn["timeline"] = timeline
    roots = [
        root(seed, 0, aliases["observation"], 0, "2037-04-11T08:00:00Z", "2037-04-11T08:00:00Z"),
        root(seed, 1, aliases["observation"], 0, "2037-04-11T09:00:00Z", "2037-04-11T09:00:00Z"),
        root(seed, 2, aliases["observation"], 1, "2037-04-11T10:00:00Z", "2037-04-11T10:45:00Z"),
        root(seed, 3, aliases["treatment"], 1, "2037-04-11T08:30:00Z", "2037-04-11T08:31:00Z", role="performed_intervention"),
        root(seed, 4, aliases["outcome"], 1, "2037-04-11T09:30:00Z", "2037-04-11T09:31:00Z", role="observed_outcome"),
    ]
    modules = [
        opaque(seed, "schema_module", 0),
        opaque(seed, "mapping_module", 0),
        dbn["model_id"],
        scm["model_id"],
    ]
    rng.shuffle(modules)
    cut = {
        "target_window": ["2037-04-11T09:00:00Z", "2037-04-11T09:00:00.001000Z"],
        "actor_visibility_cut": "2037-04-11T11:00:00Z",
        "transaction_revision_cut": "2037-04-11T11:00:00Z",
        "evidence_use_policy": opaque(seed, "evidence_policy", 0),
        "evidence_snapshot_id": opaque(seed, "snapshot", 0),
        "version_vector": {
            "evidence_schema": dbn["schema_version"],
            "bridge": opaque(seed, "bridgev", 0),
            "mapping": roots[0]["mapping_version"],
            "knowledge": opaque(seed, "knowledgev", 0),
            "model": f"{dbn['model_version']}+{scm['model_version']}",
            "model_by_kernel": {
                "finite_dbn": dbn["model_version"],
                "finite_scm": scm["model_version"],
            },
            "model_schema_by_kernel": {
                "finite_dbn": dbn["schema_version"],
                "finite_scm": scm["schema_version"],
            },
            "policy": opaque(seed, "policyv", 0),
            "solver": opaque(seed, "solverv", 0),
        },
        "external_response_snapshot": opaque(seed, "external", 0),
        "randomness_policy": {"kind": "exact_enumeration", "seed": None},
        "principal_and_authorization": opaque(seed, "principal", 0),
    }
    corpus = {
        "protocol_version": "bridge-holdout/1.0-preregistered",
        "status": "generated_after_implementation_seal",
        "generation": {
            "seed_hex": f"{seed:064x}",
            "generator_sha256": "FILLED_FROM_EXACT_GENERATOR_BYTES_AT_REVEAL",
            "generated_at": reveal_time,
            "canonical_json": "utf8-sort_keys-compact-no_nan-trailing_lf",
            "fixture_bytes_sha256": "RECORDED_IN_SIDECAR",
        },
        "implementation_seals": seals,
        "transport_binding": {
            "authority": "portable fixture semantics and hidden oracle; candidate envelopes are projections only",
            "implementation_a": {
                "source": "prototype/bridge_holdout/impl_a.py",
                "source_sha256": seals["implementation_a"],
                "canonical_schema": "vesmed.bridge-holdout.canonical/1",
                "native_schema": "vesmed.bridge-holdout.native-a/1",
                "calls": ["compile_bundle", "recover_bundle", "execute", "apply_delta"],
                "shape": "one strict bundle containing both finite_dbn and finite_scm plus named queries",
            },
            "implementation_b": {
                "source": "prototype/bridge_holdout/impl_b.py",
                "source_sha256": seals["implementation_b"],
                "canonical_schema": "vesmed.evidence-model-bridge/1",
                "native_schema": "vesmed.bridge-holdout.impl-b.native/1",
                "calls": ["compile_bundle", "recover_bundle", "execute", "apply_delta"],
                "shape": "separate finite_dbn and finite_scm envelopes with inert query mappings",
            },
            "schema_difference_rule": "A and B have incompatible frozen input envelopes; do not make either candidate parser the oracle",
            "runner_rule": "lower portable authority independently into A and B, recover each, lift to the same portable audit envelope, then compare semantic isomorphism",
            "forbidden_shared_code": ["candidate parser", "candidate canonicalizer", "candidate solver", "semantic fallback", "latest-version resolver"],
            "permitted_projection_operations": [
                "field renaming with an explicit inverse table",
                "unordered collection canonical ordering",
                "alpha-renaming of native-only nodes",
                "finite epistemic-member product state with a declared marginalization map",
                "finite SCM response-world to structural-case expansion with a declared inverse map",
            ],
        },
        "anti_tuning": {
            "opaque_aliases": aliases,
            "isomorphic_aliases": iso_aliases,
            "module_registration_order": modules,
            "second_order": list(reversed(modules)),
        },
        "semantic_contract": {
            "roundtrip": "audit_semantic_isomorphism_not_native_byte_equality",
            "exact_fields": [
                "root_occurrence_and_version", "artifact_and_logical_version", "scope",
                "clock_roles", "raw_digest_span_mapping", "value_variant",
                "dependence_families", "full_cut_and_version_vector", "query_constructor",
                "uncertainty_semantics", "materialized_and_consumed_source_mapping",
            ],
            "allowed_normalization": ["alpha_rename_native_nodes", "canonical_order_unordered_collections"],
            "numeric_tolerance": 1e-12,
            "positive_unsupported_is_failure": True,
            "negative_must_not_invoke_native": True,
        },
        "base": {
            "cut": cut,
            "roots": roots,
            "dbn": dbn,
            "scm": scm,
            "authority_projection": {
                "dbn_observations": [
                    {
                        "record_id": opaque(seed, "record", index),
                        "slice_index": index,
                        "slice": timeline[index],
                        "concept": aliases["observation"],
                        "measurement": {"kind": "exact", "value": value},
                        "root_ref": {
                            "occurrence_id": roots[index]["root_occurrence_id"],
                            "version": roots[index]["root_version"],
                        },
                        "available_at": roots[index]["times"]["available_to_actor"],
                        "transaction_revision": roots[index]["times"]["kernel_committed"],
                    }
                    for index, value in enumerate((0, 0, 1))
                ],
                "scm_factual_observations": [
                    {
                        "record_id": opaque(seed, "record", 3),
                        "variable": aliases["treatment"],
                        "value": 1,
                        "semantic_role": "performed_intervention",
                        "root_ref": {
                            "occurrence_id": roots[3]["root_occurrence_id"],
                            "version": roots[3]["root_version"],
                        },
                    },
                    {
                        "record_id": opaque(seed, "record", 4),
                        "variable": aliases["outcome"],
                        "value": 1,
                        "semantic_role": "observed_outcome",
                        "root_ref": {
                            "occurrence_id": roots[4]["root_occurrence_id"],
                            "version": roots[4]["root_version"],
                        },
                    },
                ],
                "queries": {
                    "filter_t1": {"operator": "filter", "target": aliases["state"], "target_slice": timeline[1]},
                    "smooth_t1_later_y2": {
                        "operator": "smooth",
                        "target": aliases["state"],
                        "target_slice": timeline[1],
                        "later_evidence_policy": "visible-through-explicit-cut",
                        "evidence_through": timeline[2],
                    },
                    "condition_t1": {"operator": "condition", "target": aliases["outcome"], "given": {aliases["treatment"]: 1}},
                    "do_t0": {"operator": "intervene", "target": aliases["outcome"], "do_set": {aliases["treatment"]: 0}, "population_selector": None},
                    "aap_t0_given_t1_y1": {
                        "operator": "aap",
                        "target": aliases["outcome"],
                        "factual": {aliases["treatment"]: 1, aliases["outcome"]: 1},
                        "do_set": {aliases["treatment"]: 0},
                        "shared_world_policy": "share_abduced_exogenous",
                        "stages": ["abduction", "action", "prediction"],
                    },
                },
            },
        },
        "hidden_oracle": {
            "dbn": dbn_oracle,
            "scm": scm_oracle,
            "relations": {
                "filter_not_smooth": True,
                "condition_not_do": True,
                "aap_not_population_do": True,
            },
        },
        "cases": make_cases(seed, aliases, roots),
        "report_contract": {
            "no_compensating_total_score": True,
            "required_metrics": [
                "hard_assertions_by_dimension", "a_b_disagreements", "roundtrip_field_loss",
                "finite_numeric_error", "mutation_kills", "adapter_non_comment_loc",
                "closed_transform_count", "manual_semantic_commitments", "latency_p50_p95",
                "trace_bytes_nodes", "incremental_clean_mismatch", "extension_blast_radius",
            ],
        },
        "external_gates": {
            "mutation_gate": {
                "path": "research_notes/bridge_mutation_gate_v1.json",
                "source_path": "prototype/bridge_mutation_gate.py",
                "required_mutants": [f"M{index:02d}" for index in range(1, 13)],
            },
            "public_panel": {
                "path": "research_notes/bridge_panel_protocol_v1.json",
                "implementations": ["prototype/bridge_holdout/panel_a.py", "prototype/bridge_holdout/panel_b.py"],
                "required_workloads": [f"E{index:02d}" for index in range(1, 7)],
            },
        },
    }
    return corpus


def coverage_markdown(corpus: dict[str, Any]) -> str:
    dimensions = [
        "root", "dependence", "scope", "time", "versions", "uncertainty", "measurement",
        "query", "filter_smooth", "condition_do_aap", "delta", "tamper", "negative", "order", "taint",
    ]
    lines = [
        "# Hidden bridge holdout coverage matrix",
        "",
        "`X` means the case has a decisive oracle for the dimension, not merely incidental fields.",
        "",
        "| Case | " + " | ".join(dimensions) + " |",
        "|---|" + "|".join("---" for _ in dimensions) + "|",
    ]
    synonyms = {
        "filter_smooth": {"filter_smooth"},
        "condition_do_aap": {"condition_do_aap", "causal"},
        "versions": {"versions", "replay"},
        "delta": {"delta"},
        "order": {"order", "alias", "cache"},
        "tamper": {"tamper", "raw"},
        "dependence": {"root", "uncertainty"},
        "measurement": {"measurement"},
        "query": {"query", "filter_smooth", "condition_do_aap"},
    }
    for case in corpus["cases"]:
        covered = set(case["coverage"])
        marks = []
        for dimension in dimensions:
            keys = synonyms.get(dimension, {dimension})
            marks.append("X" if covered.intersection(keys) else "")
        lines.append(f"| {case['case_id']} | " + " | ".join(marks) + " |")
    lines += [
        "",
        "## Expected failure modes",
        "",
        "- root alias/path multiplication; value-based dedup of true repeats; synthetic bridge roots",
        "- clock-role collapse, off-by-one eligibility, future leakage, target-window mismatch",
        "- current-version fallback, last-write-wins forks, stale/unkeyed caches",
        "- aleatoric/epistemic/measurement collapse or failure taint laundering",
        "- filter implemented as smooth (or vice versa), query labels without distinct semantics",
        "- conditioning used for do, action forecast labeled do, AAP resampling exogenous worlds",
        "- planned action treated as performed; cross-subject/specimen/semantic-scope coercion",
        "- censor/interval/masked states flattened; hidden unit or nearest-concept conversion",
        "- raw payload used as semantic input; digest/vector tamper accepted; oracle-field dispatch",
        "- alias or registration order affects semantics; incremental result differs from clean rebuild",
        "- DBN target not bound to the compiled state; query time outside the frozen target window",
        "- one root or one dependence family counted twice through aliases/duplicate records",
        "- post-cut correction/retraction leaks backward; self/cycle/fork supersedes is arbitrated by order",
        "- SCM population selector is ignored, or exogenous/endogenous names shadow one another",
        "- encounter/specimen mismatch degrades to subject-only matching; empty dependence family implies independence",
        "- absent/censored evidence is silently skipped and a prior is returned as a successful posterior",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-hex", required=True, help="256-bit post-seal seed")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seal-a", required=True)
    parser.add_argument("--seal-b", required=True)
    parser.add_argument("--seal-panel-a", required=True)
    parser.add_argument("--seal-panel-b", required=True)
    parser.add_argument("--freeze-manifest-sha256", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--reveal-time", required=True, help="frozen ISO-8601 reveal time")
    args = parser.parse_args()
    seed = int(args.seed_hex, 16)
    if seed < 0 or seed >= 2**256:
        raise SystemExit("seed must fit 256 bits")
    corpus = build(
        seed,
        seals={
            "implementation_a": args.seal_a,
            "implementation_b": args.seal_b,
            "panel_a": args.seal_panel_a,
            "panel_b": args.seal_panel_b,
            "freeze_manifest": args.freeze_manifest_sha256,
            "git_commit": args.git_commit,
        },
        reveal_time=args.reveal_time,
    )
    generator_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    corpus["generation"]["generator_sha256"] = "sha256:" + generator_hash
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(corpus)
    args.output.write_bytes(payload)
    sidecar = args.output.with_suffix(args.output.suffix + ".sha256")
    sidecar.write_text(hashlib.sha256(payload).hexdigest() + "  " + args.output.name + "\n", encoding="ascii")
    args.output.with_name("COVERAGE.md").write_text(coverage_markdown(corpus), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
