"""External first-pass judge for frozen bridge implementation A.

This file is intentionally outside ``prototype/bridge_holdout``.  It uses only
implementation A's public API and the post-seal portable corpus.  It does not
turn mutation names into hidden inputs: cases without a concrete payload are
reported as ``HARNESS_INCOMPLETE``.  Deterministically constructed diagnostics
are kept in the separate ``POST_SEAL_EXTERNAL_PROBE`` section and never count
as hidden-case results.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO / "tests" / "bridge_holdout" / "hidden_corpus.json"
SOURCE_PATH = REPO / "prototype" / "bridge_holdout" / "impl_a.py"
FREEZE_PATH = REPO / "results" / "bridge-holdout" / "freeze-manifest.json"
FIXTURE_MANIFEST_PATH = REPO / "results" / "bridge-holdout" / "fixture-manifest.json"
DEFAULT_OUTPUT = REPO / "results" / "bridge-holdout" / "implementation-a-audited-run-01.json"
RUNNER_SCHEMA = "vesmed.bridge-holdout.external-run-a/1"
PRODUCT_SEPARATOR = "::portable-member-state::"
EXPECTED_IMPL_A_SHA256 = "9acd79c967d05ca1dbeaf11e4238b3185d9e3e7e44c2fa478cb47a30ee554fff"
EXPECTED_FREEZE_SHA256 = "1eeddf4db162ae5c255e79d621785f912aa783382c794707cc46d8996b4ad6cb"
EXPECTED_FIXTURE_MANIFEST_SHA256 = "84d2a1feb7904414a7a5e905c4f49090b4dce16d4d8db0caf2c38015c2e96243"
EXPECTED_CORPUS_SHA256 = "9ed638f0f6d5b5db688f40581b4bb659bb1b6df29e377048fa628b970944f309"
FORBIDDEN_CANDIDATE_INPUT_KEYS = {
    "hidden_oracle",
    "oracle",
    "case_id",
    "expected",
    "authority_projection",
    "report_contract",
}


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)[:-1]).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_sha256_sidecar(path: Path) -> str:
    """Read either ``<hex>`` or the conventional ``<hex>  <filename>`` form."""

    tokens = path.read_text(encoding="utf-8").split()
    if not tokens or len(tokens[0]) != 64:
        raise ValueError(f"invalid SHA-256 sidecar: {path}")
    return tokens[0]


def assert_no_oracle_leak(value: Any, path: str = "$") -> None:
    """Fail before a candidate call if runner-only material leaked inward."""

    if type(value) is dict:
        forbidden = sorted(set(value) & FORBIDDEN_CANDIDATE_INPUT_KEYS)
        if forbidden:
            raise AssertionError(f"runner-only candidate input key(s) at {path}: {forbidden}")
        for key, child in value.items():
            assert_no_oracle_leak(child, f"{path}.{key}")
    elif type(value) in {list, tuple}:
        for index, child in enumerate(value):
            assert_no_oracle_leak(child, f"{path}[{index}]")


def assert_execution_only_projection(bundle: dict[str, Any]) -> None:
    """Make the non-permitted wrapper explicit before any diagnostic call."""

    for index, root in enumerate(bundle["roots"]):
        payload = root["raw_payload"]
        if type(payload) is not dict or set(payload) != {"portable_raw_payload", "portable_raw_digest"}:
            raise AssertionError(f"execution-only root wrapper missing at roots[{index}]")
    if not any(query["kind"] == "smooth" for query in bundle["queries"]):
        raise AssertionError("execution-only projection must contain the smooth clock conversion probe")


def load_impl_a() -> Any:
    module_name = "frozen_bridge_impl_a_external"
    spec = importlib.util.spec_from_file_location(module_name, SOURCE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen implementation A")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def as_float(pair: list[int]) -> float:
    return pair[0] / pair[1]


def scope_a(portable: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_id": portable["subject"],
        "encounter_id": portable.get("encounter"),
        "specimen_id": portable.get("specimen"),
        "device_id": portable.get("device"),
        "site_id": portable.get("site"),
        "body_site": portable.get("body_site"),
    }


def clocks_a(root: dict[str, Any], slice_id: str) -> dict[str, Any]:
    times = root["times"]
    clocks = {
        "effective_start": times["occurrence"],
        "available_at": times["available_to_actor"],
        "recorded_at": times["source_recorded"],
        "collected_at": times["collection"],
        "kernel_committed_at": times["kernel_committed"],
        "slice_id": slice_id,
    }
    if times.get("effective_end") is not None:
        clocks["effective_end"] = times["effective_end"]
    return clocks


def dbn_model_a(base: dict[str, Any]) -> dict[str, Any]:
    source = base["dbn"]
    states = [f"{member['member_id']}{PRODUCT_SEPARATOR}{state}" for member in source["epistemic_members"] for state in (0, 1)]
    prior: list[dict[str, Any]] = []
    for member in source["epistemic_members"]:
        weight = as_float(member["weight"])
        p1 = as_float(member["prior_x1"])
        prior.extend([
            {"state": f"{member['member_id']}{PRODUCT_SEPARATOR}0", "probability": weight * (1.0 - p1)},
            {"state": f"{member['member_id']}{PRODUCT_SEPARATOR}1", "probability": weight * p1},
        ])
    transitions: list[dict[str, Any]] = []
    for left, right in zip(source["timeline"], source["timeline"][1:]):
        for member in source["epistemic_members"]:
            for old in (0, 1):
                p1 = as_float(member["transition_no_action_p1"][str(old)])
                for target_member in source["epistemic_members"]:
                    for new in (0, 1):
                        probability = (p1 if new else 1.0 - p1) if target_member["member_id"] == member["member_id"] else 0.0
                        transitions.append({
                            "from_slice": left,
                            "to_slice": right,
                            "from_state": f"{member['member_id']}{PRODUCT_SEPARATOR}{old}",
                            "to_state": f"{target_member['member_id']}{PRODUCT_SEPARATOR}{new}",
                            "probability": probability,
                        })
    p_y1 = source["measurement"]["p_y1_given_x"]
    emissions: list[dict[str, Any]] = []
    for member in source["epistemic_members"]:
        for state in (0, 1):
            probability_y1 = as_float(p_y1[str(state)])
            for observed in (0, 1):
                emissions.append({
                    "concept": source["observation_concept"],
                    "state": f"{member['member_id']}{PRODUCT_SEPARATOR}{state}",
                    "observed_value": observed,
                    "probability": probability_y1 if observed else 1.0 - probability_y1,
                })
    return {
        "model_id": source["model_id"],
        "version": source["model_version"],
        "kernel": "finite_dbn",
        "state_variable": source["state_concept"],
        "states": states,
        "slices": list(source["timeline"]),
        "prior": prior,
        "transitions": transitions,
        "emissions": emissions,
        "uncertainty_semantics": "finite-member-product/epistemic+stochastic-transition/aleatoric+confusion-matrix/measurement",
        "coverage_contract": {
            "projection": "finite_epistemic_member_product_state",
            "marginalization": "split_product_state_and_sum_over_member",
            "product_separator": PRODUCT_SEPARATOR,
        },
    }


def scm_model_a(base: dict[str, Any]) -> dict[str, Any]:
    source = base["scm"]
    treatment, outcome = source["treatment_concept"], source["outcome_concept"]
    exogenous_name = "portable_world_identity"
    worlds = [
        {"world_id": row["world_id"], "probability": as_float(row["weight"]), "values": {exogenous_name: row["world_id"]}}
        for row in source["worlds"]
    ]
    t_cases = [{"when": {exogenous_name: row["world_id"]}, "value": row["observed_t"]} for row in source["worlds"]]
    y_cases = []
    for row in source["worlds"]:
        y_cases.extend([
            {"when": {exogenous_name: row["world_id"], treatment: 0}, "value": row["y0"]},
            {"when": {exogenous_name: row["world_id"], treatment: 1}, "value": row["y1"]},
        ])
    return {
        "model_id": source["model_id"],
        "version": source["model_version"],
        "kernel": "finite_scm",
        "endogenous_order": [treatment, outcome],
        "domains": {treatment: [0, 1], outcome: [0, 1]},
        "exogenous_worlds": worlds,
        "equations": [{"variable": treatment, "cases": t_cases}, {"variable": outcome, "cases": y_cases}],
        "observation_bindings": [{"concept": treatment, "variable": treatment}, {"concept": outcome, "variable": outcome}],
        "uncertainty_semantics": "finite_possible_world_probability_mass",
        "coverage_contract": {"population": "portable_all_worlds"},
        "identification_contracts": [source["identification_contract"]],
    }


def version_vector_a(base: dict[str, Any]) -> dict[str, str]:
    value = base["cut"]["version_vector"]
    return {
        "bridge": value["bridge"],
        "adapter": "runner-a-external-projection/1",
        "terminology": value["evidence_schema"],
        "knowledge": value["knowledge"],
        "model": value["model"],
        "policy": value["policy"],
        "solver": value["solver"],
        "mapping": value["mapping"],
        "model.finite_dbn": value["model_by_kernel"]["finite_dbn"],
        "model.finite_scm": value["model_by_kernel"]["finite_scm"],
        "model_schema.finite_dbn": value["model_schema_by_kernel"]["finite_dbn"],
        "model_schema.finite_scm": value["model_schema_by_kernel"]["finite_scm"],
    }


def dbn_bundle_a(base: dict[str, Any], *, include_smooth: bool) -> dict[str, Any]:
    projection = base["authority_projection"]
    observations = projection["dbn_observations"]
    by_root = {(row["root_ref"]["occurrence_id"], row["root_ref"]["version"]): row for row in observations}
    selected_roots = [root for root in base["roots"] if (root["root_occurrence_id"], root["root_version"]) in by_root]
    roots: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for root in selected_roots:
        key = (root["root_occurrence_id"], root["root_version"])
        observation = by_root[key]
        raw_envelope = {"portable_raw_payload": root["raw_payload"], "portable_raw_digest": root["raw_digest"]}
        roots.append({
            "occurrence_id": key[0],
            "version": key[1],
            "artifact_id": root["artifact_id"],
            "artifact_version": root["artifact_version"],
            "source_span": root["source_span"],
            "raw_payload": raw_envelope,
            "raw_digest": digest_value(raw_envelope),
            "dependence_families": list(root["dependence_families"]),
        })
        records.append({
            "statement_id": observation["record_id"],
            "logical_id": root["logical_id"],
            "version": root["root_version"],
            "concept": observation["concept"],
            "semantic_role": root["semantic_role"],
            "information_state": "present",
            "scope": scope_a(root["scope"]),
            "clocks": clocks_a(root, observation["slice"]),
            "measurement": copy.deepcopy(observation["measurement"]),
            "unit": root["value"].get("unit"),
            "method": f"{base['dbn']['measurement']['method_id']}@{base['dbn']['measurement']['method_version']}",
            "mapping_versions": [root["mapping_version"]],
            "root_refs": [{"occurrence_id": key[0], "version": key[1]}],
            "proof": {"kind": "authority_root", "root_occurrence_id": key[0], "root_version": key[1]},
        })
    cut = base["cut"]
    queries = [{
        "query_id": "filter_t1",
        "kind": "filter",
        "target": base["dbn"]["state_concept"],
        "at": projection["queries"]["filter_t1"]["target_slice"],
    }]
    if include_smooth:
        # Portable evidence_through is an effective-time bound; A's field is an
        # availability bound.  The explicit conversion to the frozen actor cut
        # is execution-only and therefore is not used for H01 round-trip proof.
        queries.append({
            "query_id": "smooth_t1_later_y2",
            "kind": "smooth",
            "target": base["dbn"]["state_concept"],
            "at": projection["queries"]["smooth_t1_later_y2"]["target_slice"],
            "later_evidence_cut": cut["actor_visibility_cut"],
        })
    first_scope = scope_a(selected_roots[0]["scope"])
    return {
        "schema_version": "vesmed.bridge-holdout.canonical/1",
        "bridge": {
            "bridge_id": "portable-db-observation-identity",
            "version": cut["version_vector"]["bridge"],
            "registered_at": base["dbn"]["timeline"][0],
            "source_kernel": "evidence_authority",
            "source_role": "observed",
            "target_role": "observed",
            "transform": "identity",
            "source_concept": base["dbn"]["observation_concept"],
            "target_concept": base["dbn"]["observation_concept"],
            "source_unit": "1",
            "target_unit": "1",
        },
        "scope": {"subject_id": first_scope["subject_id"], "encounter_id": first_scope["encounter_id"]},
        "temporal_cut": {
            "target_window": {"start": cut["target_window"][0], "end": cut["target_window"][1]},
            "actor_visibility_cut": cut["actor_visibility_cut"],
            "transaction_revision_cut": cut["transaction_revision_cut"],
            "evidence_use_policy": cut["evidence_use_policy"],
            "evidence_snapshot_id": cut["evidence_snapshot_id"],
            "external_response_snapshot": {"id": cut["external_response_snapshot"]},
            "randomness_policy": copy.deepcopy(cut["randomness_policy"]),
            "principal_authorization_snapshot": {"id": cut["principal_and_authorization"]},
        },
        "version_vector": version_vector_a(base),
        "roots": roots,
        "evidence_history": records,
        "deltas": [],
        "models": {"finite_dbn": dbn_model_a(base), "finite_scm": scm_model_a(base)},
        "queries": queries,
        "uncertainty_contract": {
            "belief_semantics": "finite_probability_mass",
            "unknown_policy": "preserve_not_zero",
            "conflict_policy": "reject_before_model",
            "dependence_policy": "model_declared_not_root_count",
            "version": "portable-three-channel-contract/1",
        },
    }


def lift_dbn_roots(recovered: dict[str, Any]) -> list[dict[str, Any]]:
    record_by_ref: dict[tuple[str, str], dict[str, Any]] = {}
    for record in recovered["evidence_history"]:
        for ref in record["root_refs"]:
            record_by_ref[(ref["occurrence_id"], ref["version"])] = record
    lifted = []
    for root in recovered["roots"]:
        key = (root["occurrence_id"], root["version"])
        record = record_by_ref[key]
        raw = root["raw_payload"]
        clocks = record["clocks"]
        lifted.append({
            "artifact_id": root["artifact_id"],
            "artifact_version": root["artifact_version"],
            "concept": record["concept"],
            "dependence_families": list(root["dependence_families"]),
            "logical_id": record["logical_id"],
            "mapping_version": record["mapping_versions"][0],
            "raw_digest": raw["portable_raw_digest"],
            "raw_payload": raw["portable_raw_payload"],
            "root_occurrence_id": root["occurrence_id"],
            "root_version": root["version"],
            "scope": {
                "body_site": record["scope"].get("body_site"),
                "device": record["scope"].get("device_id"),
                "encounter": record["scope"].get("encounter_id"),
                "site": record["scope"].get("site_id"),
                "specimen": record["scope"].get("specimen_id"),
                "subject": record["scope"]["subject_id"],
            },
            "semantic_role": record["semantic_role"],
            "source_span": root["source_span"],
            "times": {
                "available_to_actor": clocks["available_at"],
                "collection": clocks.get("collected_at"),
                "effective_end": clocks.get("effective_end"),
                "kernel_committed": clocks.get("kernel_committed_at"),
                "occurrence": clocks["effective_start"],
                "source_recorded": clocks["recorded_at"],
            },
            "value": {"kind": record["measurement"]["kind"], "unit": record["unit"], "value": record["measurement"].get("value")},
        })
    return sorted(lifted, key=lambda row: (row["root_occurrence_id"], row["root_version"]))


def marginal_p1(result: dict[str, Any]) -> float:
    total = 0.0
    for row in result["distribution"]:
        if row["value"].endswith(PRODUCT_SEPARATOR + "1"):
            total += row["probability"]
    return total


def case_result(case: dict[str, Any], status: str, assertions: dict[str, bool] | None = None, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "title": case["title"],
        "family": case["family"],
        "fixture": case.get("fixture"),
        "mutation": case.get("mutation"),
        "classification": status,
        "assertions": assertions or {},
        "evidence": evidence or {},
    }


def run(corpus: dict[str, Any], impl: Any) -> dict[str, Any]:
    """Run only mechanically defensible checks against the frozen A source.

    The portable fixture and A use different raw-digest semantics, so the
    execution bundle below deliberately wraps the portable raw pair.  That
    wrapper is *not* an allowed holdout projection.  Its results are therefore
    post-seal diagnostics only and can never promote H01/H08/H16 to PASS.
    """

    base = corpus["base"]
    cases_by_id = {row["case_id"]: row for row in corpus["cases"]}
    results: list[dict[str, Any]] = []

    portable_dbn_roots = sorted(
        [row for row in base["roots"] if row["concept"] == base["dbn"]["observation_concept"]],
        key=lambda row: (row["root_occurrence_id"], row["root_version"]),
    )
    digest_mismatches = []
    for root in portable_dbn_roots:
        candidate_digest = digest_value(root["raw_payload"])
        if candidate_digest != root["raw_digest"]:
            digest_mismatches.append(
                {
                    "root_occurrence_id": root["root_occurrence_id"],
                    "portable_raw_digest": root["raw_digest"],
                    "candidate_required_json_digest": candidate_digest,
                }
            )

    common_unrepresentable = {
        "native_invoked_for_hidden_case": False,
        "candidate_pass_fail_attribution_allowed": False,
        "permitted_projection_violation": "portable raw digest cannot be preserved by field renaming, ordering, alpha-renaming, DBN product-state lowering, or SCM world expansion",
        "raw_digest_mismatches": digest_mismatches,
        "execution_only_probe_ref": "PA-DBN-NUMERICS",
    }
    results.append(
        case_result(
            cases_by_id["H01"],
            "ADAPTER_UNREPRESENTABLE",
            evidence={
                **common_unrepresentable,
                "reason": "A recomputes SHA-256 over its own canonical JSON payload; the sealed portable digest names different raw bytes. Rehashing or wrapping would change the authority root.",
            },
        )
    )
    results.append(
        case_result(
            cases_by_id["H02"],
            "ADAPTER_UNREPRESENTABLE",
            evidence={
                "reason": "A has one global bridge.source_role and cannot losslessly preserve simultaneous performed_intervention and observed_outcome factual roles.",
                "portable_roles": sorted(
                    {row["semantic_role"] for row in base["authority_projection"]["scm_factual_observations"]}
                ),
                "candidate_role_cardinality": 1,
                "native_invoked_for_hidden_case": False,
                "candidate_pass_fail_attribution_allowed": False,
            },
        )
    )
    results.append(
        case_result(
            cases_by_id["H08"],
            "ADAPTER_UNREPRESENTABLE",
            evidence={
                **common_unrepresentable,
                "reason": "portable smooth evidence_through is an effective-time boundary, whereas A later_evidence_cut is an availability-time boundary; including the delayed result requires a non-permitted semantic clock conversion.",
                "portable_evidence_through": base["authority_projection"]["queries"]["smooth_t1_later_y2"]["evidence_through"],
                "execution_only_candidate_cut": base["cut"]["actor_visibility_cut"],
            },
        )
    )
    results.append(
        case_result(
            cases_by_id["H16"],
            "ADAPTER_UNREPRESENTABLE",
            evidence={
                **common_unrepresentable,
                "reason": "the concrete base cannot enter A with exact root identity; a separate A-native diagnostic nevertheless tests whether typed results expose all three uncertainty channels.",
                "execution_only_probe_ref": "PA-UNCERTAINTY-CHANNELS",
            },
        )
    )

    concrete_classified = {"H01", "H02", "H08", "H16"}
    for case in corpus["cases"]:
        if case["case_id"] in concrete_classified:
            continue
        dangling = [query for query in case.get("queries", []) if query not in base["authority_projection"]["queries"]]
        reason = (
            "corpus query reference is dangling and no executable query object is supplied"
            if dangling
            else "corpus entry contains a mutation descriptor/oracle prose but no concrete mutated authority object"
        )
        results.append(
            case_result(
                case,
                "HARNESS_INCOMPLETE",
                evidence={
                    "reason": reason,
                    "dangling_query_refs": dangling,
                    "candidate_verdict": "not_scored",
                    "candidate_pass_fail_attribution_allowed": False,
                },
            )
        )
    results.sort(key=lambda row: int(row["case_id"][1:]))

    # Execution-only projection: valid input for A, but not a valid portable
    # hidden-case adapter because it envelopes raw payload/digest and converts
    # the smooth clock.  Candidate calls are guarded against oracle leakage.
    execution_bundle = dbn_bundle_a(base, include_smooth=True)
    assert_execution_only_projection(execution_bundle)
    assert_no_oracle_leak(execution_bundle)
    native = impl.compile_bundle(execution_bundle, "finite_dbn")
    recovered = impl.recover_bundle(native)
    filtered = impl.execute(native, "filter_t1")
    smoothed = impl.execute(native, "smooth_t1_later_y2")

    filter_p1 = marginal_p1(filtered)
    smooth_p1 = marginal_p1(smoothed)
    filter_oracle = corpus["hidden_oracle"]["dbn"]["filter_x1"]
    smooth_oracle = corpus["hidden_oracle"]["dbn"]["smooth_x1"]
    expected_filter = float(Fraction(filter_oracle["numerator"], filter_oracle["denominator"]))
    expected_smooth = float(Fraction(smooth_oracle["numerator"], smooth_oracle["denominator"]))
    numeric_assertions = {
        "stored_filter_decimal_matches_exact_fraction": expected_filter == filter_oracle["decimal"],
        "stored_smooth_decimal_matches_exact_fraction": expected_smooth == smooth_oracle["decimal"],
        "filter_exact": abs(filter_p1 - expected_filter) <= 1e-12,
        "smooth_exact": abs(smooth_p1 - expected_smooth) <= 1e-12,
        "filter_not_smooth": not math.isclose(filter_p1, smooth_p1, rel_tol=0.0, abs_tol=1e-15),
        "operator_distinct": (filtered["operator"], smoothed["operator"]) == ("filter", "smooth"),
        "policy_witness_distinct": filtered["native_witness"] != smoothed["native_witness"],
    }
    numeric_probe = {
        "probe_id": "PA-DBN-NUMERICS",
        "title": "A-native product-state filter/smooth core",
        "evidence_class": "post_seal_external_probe",
        "counts_as_mechanically_generated_hidden_case": False,
        "classification": "CANDIDATE_PASS" if all(numeric_assertions.values()) else "CANDIDATE_FAIL",
        "projection_limitations": [
            "portable raw payload and digest are stored in an A-digest-valid envelope",
            "portable effective evidence_through is mapped to actor availability cut",
            "portable action_concept and performed-action transition are omitted; this probe is no-action only",
            "three-channel uncertainty semantics is manually declared in the product-state projection",
        ],
        "assertions": numeric_assertions,
        "evidence": {
            "projected_input_sha256": digest_value(execution_bundle),
            "a_native_recovery_python_equality": recovered == execution_bundle,
            "a_native_recovery_equality_note": "not a scoring predicate; A canonicalizes collection order and hidden exact round-trip is already classified ADAPTER_UNREPRESENTABLE",
            "filter_p1": filter_p1,
            "oracle_filter_p1": expected_filter,
            "filter_absolute_error": abs(filter_p1 - expected_filter),
            "smooth_p1": smooth_p1,
            "oracle_smooth_p1": expected_smooth,
            "smooth_absolute_error": abs(smooth_p1 - expected_smooth),
            "filter_used_root_refs": filtered["used_evidence"]["root_refs"],
            "smooth_used_root_refs": smoothed["used_evidence"]["root_refs"],
        },
    }

    uncertainty_keys = set(filtered["uncertainty"])
    uncertainty_assertions = {
        "epistemic_product_state_present": all(
            PRODUCT_SEPARATOR in state for state in native["native_model"]["states"]
        ),
        "aleatoric_transition_present": bool(native["native_model"]["transitions"]),
        "measurement_emission_present": bool(native["native_model"]["emissions"]),
        "result_reports_aleatoric": "aleatoric" in uncertainty_keys,
        "result_reports_epistemic": "epistemic" in uncertainty_keys,
        "result_reports_measurement": "measurement" in uncertainty_keys,
        "no_flat_confidence": "confidence" not in uncertainty_keys,
    }
    uncertainty_probe = {
        "probe_id": "PA-UNCERTAINTY-CHANNELS",
        "title": "Typed result preserves aleatoric, epistemic, and measurement channels",
        "evidence_class": "post_seal_external_probe",
        "counts_as_mechanically_generated_hidden_case": False,
        "classification": "CANDIDATE_PASS" if all(uncertainty_assertions.values()) else "CANDIDATE_FAIL",
        "assertions": uncertainty_assertions,
        "evidence": {
            "result_uncertainty_keys": sorted(uncertainty_keys),
            "native_uncertainty_semantics": native["native_model"]["uncertainty_semantics"],
        },
    }

    # M01 has two arms.  The target model is live, but the unused other-kernel
    # model can change recovery/digest without changing this native execution.
    # Therefore A supplies only partial evidence and does not kill M01.
    stale = copy.deepcopy(native)
    for row in stale["native_model"]["emissions"]:
        row["probability"] = 1.0 - row["probability"]
    stale_failed_closed = False
    stale_error = None
    try:
        impl.recover_bundle(stale)
    except Exception as exc:  # Candidate exceptions are diagnostic, never typed hidden PASS.
        stale_failed_closed = True
        stale_error = f"{type(exc).__name__}: {exc}"

    target_mutated = copy.deepcopy(stale)
    target_canonical = copy.deepcopy(recovered)
    target_canonical["models"]["finite_dbn"] = copy.deepcopy(target_mutated["native_model"])
    target_mutated["semantic_digest"] = digest_value(target_canonical)
    target_recovered = impl.recover_bundle(target_mutated)
    target_result = impl.execute(target_mutated, "filter_t1")

    sidecar_mutated = copy.deepcopy(native)
    sidecar_mutated["other_model_registry_entry"]["uncertainty_semantics"] += "|post-seal-mutated"
    sidecar_canonical = copy.deepcopy(recovered)
    sidecar_canonical["models"]["finite_scm"] = copy.deepcopy(sidecar_mutated["other_model_registry_entry"])
    sidecar_mutated["semantic_digest"] = digest_value(sidecar_canonical)
    sidecar_recovered = impl.recover_bundle(sidecar_mutated)
    sidecar_result = impl.execute(sidecar_mutated, "filter_t1")

    m01_assertions = {
        "stale_integrity_fails_closed": stale_failed_closed,
        "target_recovery_reflects_mutation": target_recovered["models"]["finite_dbn"] == target_mutated["native_model"],
        "target_execution_changes": not math.isclose(marginal_p1(target_result), filter_p1, rel_tol=0.0, abs_tol=1e-15),
        "other_kernel_recovery_reflects_mutation": sidecar_recovered["models"]["finite_scm"] == sidecar_mutated["other_model_registry_entry"],
        "other_kernel_mutation_changes_typed_execution_or_output": not math.isclose(
            marginal_p1(sidecar_result), filter_p1, rel_tol=0.0, abs_tol=1e-15
        ),
    }
    m01_probe = {
        "probe_id": "PA-M01-DESTRUCTIVE-ROUNDTRIP",
        "title": "Every externally supplied model field is live under destructive round-trip",
        "evidence_class": "post_seal_external_probe",
        "counts_as_mechanically_generated_hidden_case": False,
        "classification": "PARTIAL",
        "mutation_kill": "NOT_KILLED",
        "reason": "target finite_dbn tables are live, but the recoverable finite_scm registry entry is an unused sidecar for a finite_dbn native execution",
        "assertions": m01_assertions,
        "evidence": {
            "stale_error": stale_error,
            "original_filter_p1": filter_p1,
            "target_mutated_filter_p1": marginal_p1(target_result),
            "other_kernel_mutated_filter_p1": marginal_p1(sidecar_result),
            "target_digest_changed": target_mutated["semantic_digest"] != native["semantic_digest"],
            "other_kernel_digest_changed": sidecar_mutated["semantic_digest"] != native["semantic_digest"],
            "digest_recomputed_by": "runner independent canonical JSON SHA-256; candidate CodecA helper not used",
        },
    }

    probes = [numeric_probe, uncertainty_probe, m01_probe]
    mechanical_names = (
        "PASS",
        "CANDIDATE_FAIL",
        "ADAPTER_UNREPRESENTABLE",
        "HARNESS_INCOMPLETE",
        "HARNESS_ERROR",
    )
    mechanical_counts = {
        name: sum(row["classification"] == name for row in results) for name in mechanical_names
    }
    probe_names = ("CANDIDATE_PASS", "CANDIDATE_FAIL", "ADAPTER_UNREPRESENTABLE", "PARTIAL")
    probe_counts = {
        name: sum(row["classification"] == name for row in probes) for name in probe_names
    }
    case_classifications = {row["case_id"]: row["classification"] for row in results}
    return {
        "schema_version": RUNNER_SCHEMA,
        "implementation": "A",
        "run_metadata": {
            "run_id": "implementation-a-audited-run-01",
            "status": "audited_external_run_01",
            "candidate_source": str(SOURCE_PATH.relative_to(REPO)).replace("\\", "/"),
            "candidate_source_sha256": sha256_file(SOURCE_PATH),
            "corpus": str(CORPUS_PATH.relative_to(REPO)).replace("\\", "/"),
            "corpus_sha256": sha256_file(CORPUS_PATH),
            "freeze_manifest_sha256": sha256_file(FREEZE_PATH),
            "fixture_manifest_sha256": sha256_file(FIXTURE_MANIFEST_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "canonical_generation_command": "python tests/bridge_holdout/runner_a_external.py --output results/bridge-holdout/implementation-a-audited-run-01.json",
        },
        "classification_contract": {
            "mechanical_hidden_cases_require_concrete_fixture_and_permitted_projection": True,
            "descriptor_only_cases_are_harness_incomplete": True,
            "post_seal_external_probes_never_promoted_to_hidden_pass_fail": True,
            "candidate_exception_is_not_typed_failure": True,
            "adapter_oracle_rejection_is_not_candidate_pass": True,
            "candidate_input_forbidden_keys": sorted(FORBIDDEN_CANDIDATE_INPUT_KEYS),
        },
        "summary": {
            "mechanical_case_counts": mechanical_counts,
            "external_probe_counts": probe_counts,
            "candidate_hard_failure_observed_in_this_runner": uncertainty_probe["classification"] == "CANDIDATE_FAIL",
            "holdout_complete": mechanical_counts["HARNESS_INCOMPLETE"] == 0
            and mechanical_counts["HARNESS_ERROR"] == 0
            and mechanical_counts["ADAPTER_UNREPRESENTABLE"] == 0,
            "no_compensating_total_score": True,
        },
        "hard_assertions_by_dimension": {
            "root_scope_clock_version_roundtrip": {
                "classification": "ADAPTER_UNREPRESENTABLE",
                "evidence": ["H01", "H08"],
                "reason": "portable raw digest and smooth clock semantics cannot enter A through the permitted mechanical projection set",
            },
            "dbn_filter_smooth_exact": {
                "classification": "POST_SEAL_EXTERNAL_ONLY",
                "candidate_probe_result": numeric_probe["classification"],
                "hidden_case": case_classifications["H08"],
            },
            "scm_condition_do_aap": {
                "classification": "ADAPTER_UNREPRESENTABLE",
                "evidence": ["H02"],
            },
            "three_uncertainty_channels": {
                "classification": "POST_SEAL_EXTERNAL_FAIL",
                "candidate_probe_result": uncertainty_probe["classification"],
                "hidden_case": case_classifications["H16"],
            },
            "M01_destructive_roundtrip": {
                "classification": "PARTIAL_NOT_KILLED",
                "candidate_probe_result": m01_probe["classification"],
            },
        },
        "cases": results,
        "post_seal_external_probes": probes,
        "mutation_kills": {
            "M01": {
                "classification": "NOT_KILLED",
                "evidence": "PA-M01-DESTRUCTIVE-ROUNDTRIP",
            },
            "M02": {
                "classification": "NOT_EXECUTED_BY_RUNNER_A",
                "reason": "requires pairwise A/B independence audit",
            },
            **{
                f"M{index:02d}": {
                    "classification": "NOT_EXECUTED_BY_RUNNER_A",
                    "reason": "no concrete executable mutation object is bound in this A-only runner",
                }
                for index in range(3, 13)
            },
        },
        "metrics": {
            "runtime_telemetry_omitted_for_exact_byte_replay": True,
            "permitted_projection_used": [
                "finite epistemic-member product state with declared sum-over-member marginalization"
            ],
            "nonpermitted_execution_only_conversions": [
                "portable raw payload+digest reversible envelope",
                "portable effective evidence_through to actor availability cut",
            ],
            "extension_blast_radius": {"candidate_files_changed": 0, "schema_migrations": 0},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output and sidecar")
    args = parser.parse_args()

    output_sidecar = args.output.with_suffix(args.output.suffix + ".sha256")
    if (args.output.exists() or output_sidecar.exists()) and not args.overwrite:
        raise SystemExit(f"refusing to overwrite immutable run artifact: {args.output}; pass --overwrite explicitly")
    actual_freeze = sha256_file(FREEZE_PATH)
    if actual_freeze != EXPECTED_FREEZE_SHA256:
        raise SystemExit(f"freeze manifest hash mismatch: {actual_freeze} != {EXPECTED_FREEZE_SHA256}")
    actual_fixture_manifest = sha256_file(FIXTURE_MANIFEST_PATH)
    if actual_fixture_manifest != EXPECTED_FIXTURE_MANIFEST_SHA256:
        raise SystemExit(
            f"fixture manifest hash mismatch: {actual_fixture_manifest} != {EXPECTED_FIXTURE_MANIFEST_SHA256}"
        )
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    fixture_manifest = json.loads(FIXTURE_MANIFEST_PATH.read_text(encoding="utf-8"))
    if fixture_manifest["freeze"]["manifest_sha256"] != EXPECTED_FREEZE_SHA256:
        raise SystemExit("fixture manifest does not bind the pinned freeze manifest")
    if fixture_manifest["artifacts"]["fixture"]["sha256"] != EXPECTED_CORPUS_SHA256:
        raise SystemExit("fixture manifest does not bind the pinned corpus")
    actual_source = sha256_file(SOURCE_PATH)
    expected_source = freeze["implementations"]["impl_a"]["sha256"]
    if expected_source != EXPECTED_IMPL_A_SHA256 or actual_source != EXPECTED_IMPL_A_SHA256:
        raise SystemExit(
            f"frozen source hash mismatch: manifest={expected_source}, actual={actual_source}, pinned={EXPECTED_IMPL_A_SHA256}"
        )
    expected_corpus = read_sha256_sidecar(CORPUS_PATH.with_suffix(CORPUS_PATH.suffix + ".sha256"))
    actual_corpus = sha256_file(CORPUS_PATH)
    if expected_corpus != EXPECTED_CORPUS_SHA256 or actual_corpus != EXPECTED_CORPUS_SHA256:
        raise SystemExit(
            f"corpus hash mismatch: sidecar={expected_corpus}, actual={actual_corpus}, pinned={EXPECTED_CORPUS_SHA256}"
        )
    fixture_manifest_sidecar = read_sha256_sidecar(
        FIXTURE_MANIFEST_PATH.with_suffix(FIXTURE_MANIFEST_PATH.suffix + ".sha256")
    )
    if fixture_manifest_sidecar != EXPECTED_FIXTURE_MANIFEST_SHA256:
        raise SystemExit(
            f"fixture manifest sidecar mismatch: {fixture_manifest_sidecar} != {EXPECTED_FIXTURE_MANIFEST_SHA256}"
        )
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    report = run(corpus, load_impl_a())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(report))
    output_sha256 = sha256_file(args.output)
    output_sidecar.write_text(f"{output_sha256}  {args.output.name}\n", encoding="utf-8")
    m01 = next(row for row in report["post_seal_external_probes"] if row["probe_id"] == "PA-M01-DESTRUCTIVE-ROUNDTRIP")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": output_sha256,
                "summary": report["summary"],
                "m01": m01["classification"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
