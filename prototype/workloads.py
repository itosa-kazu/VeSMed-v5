"""Frozen workload construction and loader for the T01--T50 / E01--E08 panel.

Every checked-in JSON file contains two physically separate trees:

``candidate_view``
    Public artifacts, model commitments and branch operations.  Only objects
    compiled from this tree are sent to a candidate.

``oracle_view``
    Runner-only assertions, hidden reference selectors and tolerances.  The
    benchmark never passes this tree, assertion IDs, or expected values to a
    candidate.

The builders below are kept deterministic so tests can prove that the 58
reviewable JSON files match the executable registry.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .reference_models import public_model, reference_output


PROTOCOL_VERSION = "archbench/1.0"
DEFAULT_WORKLOAD_ROOT = Path(__file__).resolve().parents[1] / "tests" / "workloads"


TITLES = {
    "T01": "support-dependent MAP remains distinct from natural MAP",
    "T02": "high-flow SpO2 retains oxygen context",
    "T03": "antipyretic changes manifestation, not inflammatory truth",
    "T04": "beta blockade and pacing contexts do not collide",
    "T05": "pre-culture antibiotics modify the observation process",
    "T06": "derived fever labels share one evidence root",
    "T07": "shared-source fever CRP and WBC are not presumed independent",
    "T08": "one phenotype can support multiple hypotheses",
    "T09": "immunosuppression locally changes observation relations",
    "T10": "conflicting oxygen records remain conflicting",
    "T11": "unmentioned rash remains unknown",
    "T12": "collection and availability times prevent future leakage",
    "T13": "final diagnosis is absent from presentation replay",
    "T14": "baseline context changes interpretation of equal creatinine",
    "T15": "task projections differ without mutating evidence",
    "T16": "unknown nonlinear interaction is not silently added",
    "T17": "state effects and observation effects remain distinct",
    "T18": "temporal succession alone does not establish causation",
    "T19": "expiry changes current but not historical visibility",
    "T20": "unseen disease can be reported out of model",
    "T21": "new disease is a local module extension",
    "T22": "new measurement method is an isolated extension",
    "T23": "as-then replay differs from reinterpret-now",
    "T24": "retraction invalidates only dependent claims",
    "T25": "arbitrary historical replay excludes future inputs",
    "T26": "safety invariant survives retrieval failure",
    "T27": "instrument roots and textual paraphrases are not conflated",
    "T28": "infection and sterile inflammation can coexist",
    "T29": "unknown device is typed quarantine with raw preservation",
    "T30": "equivalent language normalizes isomorphically",
    "T31": "rootless support cycles create no evidence",
    "T32": "late correction preserves old transaction-time view",
    "T33": "units convert only through a traceable legal conversion",
    "T34": "fan-out and fan-in do not multiply evidence roots",
    "T35": "approximation exposes solver seed and error status",
    "T36": "rule removal changes reinterpretation, not raw history",
    "T37": "only performed action intervals create effects",
    "T38": "incompatible component ports fail before execution",
    "T39": "incompatible probabilistic modules remain disagreement",
    "T40": "warm caches cannot inject future results into replay",
    "T41": "subject encounter and specimen scopes do not cross",
    "T42": "censoring and assay limits are not point values",
    "T43": "no observation opportunity is not a negative finding",
    "T44": "contradictions remain local and non-explosive",
    "T45": "normalization round-trips to raw evidence",
    "T46": "treatment optimum requires explicit goals and utility",
    "T47": "policy feedback and online updates are versioned",
    "T48": "action delivery is idempotent and cancellation stops effect",
    "T49": "general knowledge is not a patient fact without a bridge",
    "T50": "masked is distinct from absent and unknown",
}


T_MODES = {
    "T01": "pair", "T02": "pair", "T03": "no_illegal", "T04": "pair", "T05": "no_illegal",
    "T06": "root", "T07": "independence", "T08": "hypotheses", "T09": "pair", "T10": "conflict",
    "T11": "unknown", "T12": "future", "T13": "future", "T14": "pair", "T15": "task",
    "T16": "interaction_boundary", "T17": "dual_channel", "T18": "causal_boundary", "T19": "expiry", "T20": "ood",
    "T21": "extension", "T22": "extension", "T23": "replay", "T24": "retract", "T25": "future",
    "T26": "safety", "T27": "root_pair", "T28": "hypotheses", "T29": "quarantine", "T30": "paraphrase",
    "T31": "rootless_cycle", "T32": "correction", "T33": "units", "T34": "root", "T35": "numerical",
    "T36": "replay", "T37": "action", "T38": "ports", "T39": "model_conflict", "T40": "cache",
    "T41": "scope", "T42": "censored", "T43": "not_observed", "T44": "local_conflict", "T45": "raw_roundtrip",
    "T46": "utility", "T47": "model_version", "T48": "action_idempotency", "T49": "knowledge_scope", "T50": "masked",
}


CONCEPTS = {
    "T01": "mean_arterial_pressure", "T02": "oxygen_saturation", "T03": "inflammatory_activity",
    "T04": "heart_rate", "T05": "blood_culture_result", "T06": "fever_presence", "T07": "inflammation_panel",
    "T08": "diagnostic_hypothesis", "T09": "fever_presence", "T10": "oxygen_saturation", "T11": "rash_presence",
    "T12": "serum_creatinine", "T13": "final_diagnosis", "T14": "serum_creatinine", "T15": "case_projection",
    "T16": "combined_effect", "T17": "mean_arterial_pressure", "T18": "causal_effect", "T19": "medication_effect",
    "T20": "unseen_disease", "T21": "new_disease_hypothesis", "T22": "new_assay_measurement", "T23": "derived_severity",
    "T24": "fever_presence", "T25": "historical_state", "T26": "medication_safety", "T27": "evidence_root",
    "T28": "diagnostic_hypothesis", "T29": "device_measurement", "T30": "shortness_of_breath", "T31": "unsupported_claim",
    "T32": "serum_sodium", "T33": "serum_glucose", "T34": "derived_inflammation", "T35": "latent_state",
    "T36": "derived_severity", "T37": "drug_effect", "T38": "component_output", "T39": "posterior_hypothesis",
    "T40": "historical_state", "T41": "specimen_result", "T42": "viral_load", "T43": "rash_presence",
    "T44": "rash_presence", "T45": "serum_creatinine", "T46": "treatment_policy", "T47": "risk_prediction",
    "T48": "drug_effect", "T49": "patient_has_disease", "T50": "hiv_status",
}


def _time(hour: int) -> str:
    # Workloads use elapsed hours and several cross midnight.  Construct a
    # real instant instead of emitting the invalid ISO hour ``24``.
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour)
    return instant.isoformat().replace("+00:00", "Z")


def _artifact(
    artifact_id: str,
    concept: str,
    value: Any,
    *,
    source_id: str | None = None,
    role: str = "raw_observation",
    information_state: str = "present",
    effective: int = 8,
    available: int = 8,
    recorded: int | None = None,
    expires: int | None = None,
    subject: str = "P1",
    encounter: str = "E1",
    specimen: str | None = None,
    unit: str | None = None,
    method: str | None = None,
    source_family: str | None = None,
    supersedes: str | None = None,
    context: Mapping[str, Any] | None = None,
    raw: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "source_id": source_id or artifact_id,
        "semantic_role": role,
        "concept": concept,
        "scope": {"subject_id": subject, "encounter_id": encounter, "specimen_id": specimen},
        "clocks": {
            "effective_start": _time(effective), "effective_end": None, "collected_at": _time(effective),
            "available_at": _time(available), "recorded_at": _time(recorded if recorded is not None else available),
            "expires_at": _time(expires) if expires is not None else None,
        },
        "information_state": information_state,
        "value": value,
        "unit": unit,
        "method": method,
        "context": dict(context or {}),
        "reliability": 0.95,
        "source_family": source_family,
        "supersedes": supersedes,
        "raw_payload": dict(raw or {"source_text": f"{concept}={value}", "span": [0, 8]}),
        "mapping_version": "fixture-map-v1",
    }


def _query(
    query_id: str,
    kind: str,
    target: str,
    *,
    known: int = 12,
    valid: int | None = 8,
    task: str | None = None,
    intervention: Mapping[str, Any] | None = None,
    horizon: float | None = None,
    knowledge_version: str = "knowledge-v1",
    model_version: str | None = None,
    guarantees: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "query_id": query_id, "kind": kind, "target": target, "subject_id": "P1",
        "as_known_at": _time(known), "valid_at": _time(valid) if valid is not None else None,
        "task": task, "knowledge_version": knowledge_version, "model_version": model_version,
        "intervention": dict(intervention) if intervention is not None else None,
        "horizon_hours": horizon, "requested_guarantees": list(guarantees), "assumptions": [], "seed": 1103,
    }


def _assert(assertion_id: str, oracle_id: str, args: Mapping[str, Any], *, dimension: str, hard: bool = True) -> dict[str, Any]:
    return {
        "assertion_id": assertion_id, "oracle_id": oracle_id, "args": dict(args),
        "dimension": dimension, "hard_gate": hard,
    }


def _envelope(test_id: str, title: str, artifacts: list[dict[str, Any]], queries: list[dict[str, Any]], branches: list[dict[str, Any]], assertions: list[dict[str, Any]], *, modules: list[dict[str, Any]] | None = None, public: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "workload_id": test_id,
        "panel": test_id[0],
        "title": title,
        "severity": "HARD",
        "requirements": [f"ARCH-{test_id}"],
        "candidate_view": {
            "fixtures": {"artifacts": artifacts, "queries": queries, "modules": modules or []},
            "public_model": dict(public or {}),
            "branches": branches,
        },
        "oracle_view": {"assertions": assertions},
    }


def _branch(branch_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"branch_id": branch_id, "fresh_session": True, "steps": steps}


def _ingest(ids: Iterable[str], capture: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"op": "ingest", "artifact_ids": list(ids)}
    if capture:
        out["capture"] = capture
    return out


def _q(query_id: str, capture: str) -> dict[str, Any]:
    return {"op": "query", "query_id": query_id, "capture": capture}


def build_t_workload(test_id: str) -> dict[str, Any]:
    """Build one T workload.  Modes share runner mechanics, not answers."""

    title = TITLES[test_id]
    mode = T_MODES[test_id]
    concept = CONCEPTS[test_id]
    artifacts: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    modules: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    public: dict[str, Any] = {}

    if mode in {"pair", "task", "dual_channel"}:
        contexts = {
            "T01": ({"support": "norepinephrine", "channel": "observed"}, {"support": "none", "channel": "natural"}),
            "T02": ({"oxygen_support": "high_flow"}, {"oxygen_support": "room_air"}),
            "T04": ({"rate_context": "beta_blocker"}, {"rate_context": "pacemaker"}),
            "T09": ({"immune_status": "immunosuppressed"}, {"immune_status": "ordinary"}),
            "T14": ({"baseline_creatinine": 2.0}, {"baseline_creatinine": 0.8}),
            "T15": ({"projection": "diagnosis"}, {"projection": "medication_safety"}),
            "T17": ({"channel": "latent_state_effect"}, {"channel": "observation_effect"}),
        }
        left_context, right_context = contexts[test_id]
        artifacts.extend([
            _artifact("obs-a", concept, 70, context=left_context, unit="arb"),
            _artifact("obs-b", concept, 70, context=right_context, unit="arb"),
        ])
        queries.extend([
            _query("q-left", "project", concept, task=left_context.get("projection")),
            _query("q-right", "project", concept, task=right_context.get("projection")),
        ])
        branches.extend([
            _branch("left", [_ingest(["obs-a"]), _q("q-left", "result")]),
            _branch("right", [_ingest(["obs-b"]), _q("q-right", "result")]),
        ])
        assertions.append(_assert("context-distinct", "result.distinct@1", {"left": "left:result", "right": "right:result", "semantic_only": True}, dimension="epistemic"))

    elif mode == "no_illegal":
        # Negative-only tests are vacuous: an implementation returning an empty
        # result would satisfy ``not_contains``.  The same projection must also
        # carry its real observation root, which is the liveness/control arm.
        context = {"performed_antipyretic": True} if test_id == "T03" else {"antibiotic_before_collection": True}
        value = 36.8 if test_id == "T03" else "negative"
        observed_concept = "body_temperature" if test_id == "T03" else concept
        artifacts.append(_artifact("obs-main", observed_concept, value, context=context, unit="Cel" if test_id == "T03" else None))
        queries.append(_query("q-main", "project", concept))
        steps = [_ingest(["obs-main"]), _q("q-main", "result")]
        live_ref = "main:result"
        if test_id == "T03":
            # Liveness is a normal projection requirement.  Requiring a
            # separate ``evidence_view`` query kind here unfairly tested API
            # surface rather than whether the observation remained available.
            queries.append(_query("q-observed", "project", observed_concept))
            steps.append(_q("q-observed", "observed"))
            live_ref = "main:observed"
        branches.append(_branch("main", steps))
        forbidden = "no_inflammation" if test_id == "T03" else "no_infection"
        assertions.extend([
            _assert("no-illegal-inference", "result.not_contains@1", {"result": "main:result", "forbidden": forbidden, "allow_ineligible_statuses": ["insufficient"]}, dimension="epistemic"),
            _assert("observation-remains-live", "evidence.root_present@1", {"result": live_ref, "root": "obs-main"}, dimension="audit"),
        ])

    elif mode in {"root", "root_pair"}:
        count = 1 if test_id in {"T06", "T34"} else 2
        source_family = "shared-tube" if count == 1 else None
        artifacts.extend([
            _artifact("obs-a", concept, True, source_id="root-1", source_family=source_family),
            _artifact("obs-b", concept, True, source_id="root-1" if count == 1 else "root-2", source_family=source_family, context={"paraphrase": True}),
        ])
        queries.append(_query("q-main", "project", concept, guarantees=("evidence_roots",)))
        branches.append(_branch("main", [_ingest(["obs-a", "obs-b"]), _q("q-main", "result")]))
        assertions.append(_assert("root-cardinality", "evidence.root_count@1", {"result": "main:result", "expected": count}, dimension="audit"))

    elif mode == "independence":
        artifacts.extend([
            _artifact("obs-fever", "fever_presence", True, source_family="same-encounter"),
            _artifact("obs-crp", "c_reactive_protein", 12.0, unit="mg/L", source_family="same-encounter"),
            _artifact("obs-wbc", "white_blood_cell_count", 14.0, unit="10^9/L", source_family="same-encounter"),
        ])
        queries.append(_query("q-main", "project", concept, guarantees=("independence_explicit",)))
        branches.append(_branch("main", [_ingest(["obs-fever", "obs-crp", "obs-wbc"]), _q("q-main", "result")]))
        assertions.append(_assert("no-invented-independence", "evidence.no_unasserted_independence@1", {"result": "main:result", "source_family": "same-encounter"}, dimension="audit"))

    elif mode == "hypotheses":
        artifacts.extend([
            _artifact("hyp-a", concept, "infection", role="hypothesis"),
            _artifact("hyp-b", concept, "sterile_inflammation", role="hypothesis"),
        ])
        queries.append(_query("q-main", "project", concept))
        branches.append(_branch("main", [_ingest(["hyp-a", "hyp-b"]), _q("q-main", "result")]))
        assertions.append(_assert("coexisting-hypotheses", "result.contains_all@1", {"result": "main:result", "expected": ["infection", "sterile_inflammation"]}, dimension="epistemic"))

    elif mode in {"conflict", "local_conflict"}:
        other = "unrelated_glucose"
        artifacts.extend([
            _artifact("obs-positive", concept, True, source_id="source-a"),
            _artifact("obs-negative", concept, False, source_id="source-b", information_state="absent"),
            _artifact("obs-other", other, 100, unit="mg/dL"),
        ])
        queries.extend([_query("q-main", "project", concept), _query("q-other", "project", other)])
        branches.append(_branch("main", [_ingest(["obs-positive", "obs-negative", "obs-other"]), _q("q-main", "result"), _q("q-other", "other")]))
        assertions.extend([
            _assert("conflict-retained", "result.information_state@1", {"result": "main:result", "expected": ["conflicting"]}, dimension="epistemic"),
            _assert("unrelated-survives", "result.status@1", {"result": "main:other", "expected": ["ok"]}, dimension="safety"),
        ])

    elif mode == "model_conflict":
        # Two real probabilistic modules make incompatible commitments about
        # the same conditional.  No arbitration policy is supplied, so the
        # only sound result is explicit model disagreement/conflict, never an
        # unrecorded average of 0.9 and 0.1.
        modules.extend([
            {
                "module_id": "probabilistic-model-a", "family": "finite_probabilistic_model",
                "model_version": "model-a-v1",
                "public_model": {
                    "target": concept, "conditioning": {"phenotype": "present"},
                    "distribution": [{"value": True, "probability": 0.9}, {"value": False, "probability": 0.1}],
                    "assumptions": ["population-A"], "arbitration_policy": None,
                },
            },
            {
                "module_id": "probabilistic-model-b", "family": "finite_probabilistic_model",
                "model_version": "model-b-v1",
                "public_model": {
                    "target": concept, "conditioning": {"phenotype": "present"},
                    "distribution": [{"value": True, "probability": 0.1}, {"value": False, "probability": 0.9}],
                    "assumptions": ["population-B"], "arbitration_policy": None,
                },
            },
        ])
        artifacts.append(_artifact("phenotype-root", "phenotype", "present"))
        queries.append(_query("q-main", "condition", concept, guarantees=("model_disagreement", "no_implicit_averaging")))
        branches.append(_branch("main", [
            {"op": "register_module", "module_id": "probabilistic-model-a", "capture": "register-a"},
            {"op": "register_module", "module_id": "probabilistic-model-b", "capture": "register-b"},
            _ingest(["phenotype-root"]), _q("q-main", "result"),
        ]))
        assertions.extend([
            _assert("model-a-registered", "result.status@1", {"result": "main:register-a", "expected": ["ok"]}, dimension="composition"),
            _assert("model-b-registered", "result.status@1", {"result": "main:register-b", "expected": ["ok"]}, dimension="composition"),
            _assert("unresolved-disagreement-retained", "result.information_state@1", {"result": "main:result", "expected": ["conflicting"]}, dimension="epistemic"),
            _assert("conditioning-root-live", "evidence.root_present@1", {"result": "main:result", "root": "phenotype-root"}, dimension="audit"),
        ])

    elif mode == "unknown":
        artifacts.append(_artifact("obs-other", "cough_presence", True))
        queries.append(_query("q-main", "project", concept))
        branches.append(_branch("main", [_ingest(["obs-other"]), _q("q-main", "result")]))
        assertions.append(_assert("unknown-not-negative", "result.information_state@1", {"result": "main:result", "expected": ["not_asked", "not_tested", "insufficient", "unknown"], "allow_ineligible_statuses": ["insufficient"]}, dimension="epistemic"))

    elif mode in {"future", "expiry", "cache"}:
        available = 12 if mode != "expiry" else 8
        expires = 10 if mode == "expiry" else None
        artifacts.append(_artifact("late-root", concept, "visible-value", available=available, expires=expires))
        queries.extend([_query("q-early", "project", concept, known=9, valid=9), _query("q-late", "project", concept, known=13, valid=13)])
        if mode == "cache":
            branches.extend([
                _branch("warm", [_ingest(["late-root"]), _q("q-late", "warm-late"), _q("q-early", "early")]),
                _branch("cold", [_ingest(["late-root"]), _q("q-early", "early")]),
            ])
            assertions.extend([
                _assert("cache-invariance", "result.equivalent@1", {"left": "warm:early", "right": "cold:early", "semantic_only": True, "allow_ineligible_statuses": ["insufficient"]}, dimension="temporal"),
                _assert("warmed-late-value-live", "temporal.root_visibility@1", {"result": "warm:warm-late", "root": "late-root", "visible": True}, dimension="temporal"),
                _assert("warm-path-future-hidden", "temporal.root_visibility@1", {"result": "warm:early", "root": "late-root", "visible": False, "allow_ineligible_statuses": ["insufficient"]}, dimension="temporal"),
                _assert("cold-path-future-hidden", "temporal.root_visibility@1", {"result": "cold:early", "root": "late-root", "visible": False, "allow_ineligible_statuses": ["insufficient"]}, dimension="temporal"),
            ])
        else:
            branches.append(_branch("main", [_ingest(["late-root"]), _q("q-early", "early"), _q("q-late", "late")]))
            if mode == "expiry":
                assertions.extend([
                    _assert("historical-visible", "temporal.root_visibility@1", {"result": "main:early", "root": "late-root", "visible": True}, dimension="temporal"),
                    _assert("expired-current-hidden", "temporal.root_visibility@1", {"result": "main:late", "root": "late-root", "visible": False, "allow_ineligible_statuses": ["insufficient"]}, dimension="temporal"),
                ])
            else:
                assertions.extend([
                    _assert("future-hidden", "temporal.root_visibility@1", {"result": "main:early", "root": "late-root", "visible": False, "allow_ineligible_statuses": ["insufficient"]}, dimension="temporal"),
                    _assert("later-visible", "temporal.root_visibility@1", {"result": "main:late", "root": "late-root", "visible": True}, dimension="temporal"),
                ])

    elif mode in {"interaction_boundary", "causal_boundary", "ood", "utility"}:
        if mode == "causal_boundary":
            # Treatment precedes improvement, but there is no exchangeability,
            # instrument, randomized assignment or structural model.  Temporal
            # succession alone must never be reported as identified causation.
            artifacts.extend([
                _artifact("treatment-root", "treatment_delivery", "drug-X", role="performed_intervention", effective=8, available=8, context={"stage": "performed"}),
                _artifact("outcome-root", "symptom_severity", 2.0, effective=10, available=10, context={"previous_value": 7.0}),
            ])
            queries.append(_query("q-main", "intervene", concept, known=12, valid=10, intervention={"variable": "treatment", "value": 1}, guarantees=("identification_status",)))
            branches.append(_branch("main", [_ingest(["treatment-root", "outcome-root"]), _q("q-main", "result")]))
        elif mode == "ood":
            # OOD is a coverage question over a diagnostic projection, not an
            # invariant-check API smoke test.  Known hypotheses are deliberately
            # enumerated and the requested target is not one of them.
            artifacts.append(_artifact("phenotype-root", "unmapped_phenotype", {"feature": "novel-pattern"}))
            public.update({
                "coverage_registry": {
                    "registered_hypotheses": ["known-disease-A", "known-disease-B"],
                    "open_world": True,
                    "unknown_target": concept,
                }
            })
            queries.append(_query("q-main", "project", concept, guarantees=("coverage_status",)))
            branches.append(_branch("main", [_ingest(["phenotype-root"]), _q("q-main", "result")]))
        else:
            queries.append(_query("q-main", "check_invariant", concept))
            branches.append(_branch("main", [_q("q-main", "result")]))
        if mode == "causal_boundary":
            assertions.append(_assert("identification-not-invented", "result.identification_boundary@1", {"result": "main:result"}, dimension="causal"))
        elif mode == "ood":
            assertions.append(_assert("coverage-explicit", "result.axis@1", {"result": "main:result", "axis": "coverage_status", "expected": ["out_of_model"]}, dimension="safety"))
        else:
            assertions.append(_assert("typed-boundary", "result.typed_boundary@1", {"result": "main:result", "allowed": ["unsupported", "insufficient", "out_of_model"]}, dimension="composition" if mode == "interaction_boundary" else "safety"))

    elif mode == "extension":
        module_id = "extension-module"
        modules.append({"module_id": module_id, "family": "typed_extension", "concept": concept, "closed_ir": {"op": "identity", "target": concept}})
        queries.append(_query("q-main", "project", concept))
        branches.extend([
            _branch("before", [_q("q-main", "result")]),
            _branch("after", [{"op": "register_module", "module_id": module_id, "capture": "registration"}, _q("q-main", "result")]),
        ])
        assertions.extend([
            _assert("registration-called", "result.status@1", {"result": "after:registration", "expected": ["ok"]}, dimension="extension", hard=False),
            _assert("extension-behavior", "result.distinct@1", {"left": "before:result", "right": "after:result", "semantic_only": True}, dimension="extension"),
        ])

    elif mode in {"replay", "model_version"}:
        # The two cuts reference executable, public, versioned modules.  This
        # prevents a query-echo implementation from manufacturing distinction
        # merely from the two knowledge_version strings.
        if test_id == "T23":
            raw_concept = "severity_score_raw"
            target = "derived_severity"
            modules.extend([
                {
                    "module_id": "severity-rule-v1", "family": "versioned_knowledge_rule",
                    "knowledge_version": "knowledge-v1", "model_version": "severity-v1",
                    "public_model": {"input": raw_concept, "output": target, "closed_ir": {"op": "threshold", "ge": 4.0, "then": "high", "else": "low"}},
                },
                {
                    "module_id": "severity-rule-v2", "family": "versioned_knowledge_rule",
                    "knowledge_version": "knowledge-v2", "model_version": "severity-v2",
                    "public_model": {"input": raw_concept, "output": target, "closed_ir": {"op": "threshold", "ge": 5.0, "then": "high", "else": "low"}},
                },
            ])
            artifacts.append(_artifact("raw-root", raw_concept, 4.5))
        elif test_id == "T36":
            raw_concept = "severity_marker_raw"
            target = "derived_severity"
            modules.extend([
                {
                    "module_id": "active-rule-v1", "family": "versioned_knowledge_rule",
                    "knowledge_version": "knowledge-v1", "model_version": "severity-v1",
                    "public_model": {"input": raw_concept, "output": target, "closed_ir": {"op": "map", "from": "marker-positive", "to": "high"}},
                },
                {
                    "module_id": "retired-rule-v2", "family": "versioned_knowledge_rule",
                    "knowledge_version": "knowledge-v2", "model_version": "severity-v2",
                    "public_model": {"input": raw_concept, "output": target, "closed_ir": {"op": "retired", "replaces": "active-rule-v1", "rules": []}},
                },
            ])
            artifacts.append(_artifact("raw-root", raw_concept, "marker-positive"))
        else:  # T47: policy-induced data remain a distinct, versioned channel.
            raw_concept = "policy_induced_outcome"
            target = "risk_prediction"
            modules.extend([
                {
                    "module_id": "risk-model-v1", "family": "versioned_probabilistic_model",
                    "knowledge_version": "knowledge-v1", "model_version": "risk-v1",
                    "public_model": {"input": raw_concept, "output": target, "channel": "pre_policy", "closed_ir": {"op": "affine", "slope": 0.10, "intercept": 0.10}},
                },
                {
                    "module_id": "risk-model-v2", "family": "versioned_probabilistic_model",
                    "knowledge_version": "knowledge-v2", "model_version": "risk-v2",
                    "public_model": {"input": raw_concept, "output": target, "channel": "policy_induced", "policy_id": "policy-A", "closed_ir": {"op": "affine", "slope": 0.05, "intercept": 0.20}},
                },
            ])
            artifacts.append(_artifact("raw-root", raw_concept, 4.0, context={"policy_id": "policy-A", "exposure": "recommended-treatment"}))
        queries.extend([
            _query("q-old", "replay_as_then", target, knowledge_version="knowledge-v1", model_version=modules[-2]["model_version"]),
            _query("q-now", "reinterpret_now", target, knowledge_version="knowledge-v2", model_version=modules[-1]["model_version"]),
        ])
        branches.append(_branch("main", [
            {"op": "register_module", "module_id": modules[-2]["module_id"], "capture": "register-old"},
            {"op": "register_module", "module_id": modules[-1]["module_id"], "capture": "register-now"},
            _ingest(["raw-root"]), _q("q-old", "old"), _q("q-now", "now"),
        ]))
        version_args = {"left": "main:old", "right": "main:now", "semantic_only": True}
        roots_args = {"left": "main:old", "right": "main:now"}
        if test_id == "T36":
            # With v2 the derivation is legitimately absent/insufficient, but
            # the raw input must remain auditable at both knowledge cuts.
            version_args["allow_ineligible_statuses"] = ["insufficient"]
            roots_args["allow_ineligible_statuses"] = ["insufficient"]
        assertions.extend([
            _assert("versioned-interpretation", "result.distinct@1", version_args, dimension="temporal"),
            _assert("raw-root-preserved", "evidence.same_roots@1", roots_args, dimension="audit"),
        ])
        if test_id == "T23":
            assertions.extend([
                _assert("old-rule-output", "result.contains_all@1", {"result": "main:old", "expected": ["high"]}, dimension="temporal"),
                _assert("new-rule-output", "result.contains_all@1", {"result": "main:now", "expected": ["low"]}, dimension="temporal"),
            ])
        elif test_id == "T36":
            assertions.extend([
                _assert("old-rule-live", "result.contains_all@1", {"result": "main:old", "expected": ["high"]}, dimension="temporal"),
                _assert("retired-rule-not-used", "result.not_contains@1", {"result": "main:now", "forbidden": "high", "allow_ineligible_statuses": ["insufficient"]}, dimension="temporal"),
            ])
        else:
            assertions.extend([
                _assert("pre-policy-model-output", "result.contains_all@1", {"result": "main:old", "expected": [0.5]}, dimension="causal"),
                _assert("policy-aware-model-output", "result.contains_all@1", {"result": "main:now", "expected": [0.4]}, dimension="causal"),
            ])

    elif mode in {"retract", "correction"}:
        first = _artifact("version-1", concept, 1, source_id="stable-source")
        if mode == "retract":
            second = _artifact("version-2", concept, 1, source_id="independent-source", effective=8, available=8)
        else:
            second = _artifact(
                "version-2", concept, 2, source_id="stable-source-v2", supersedes="stable-source",
                effective=8, available=12, recorded=12,
            )
        artifacts.extend([first, second])
        queries.extend([_query("q-old", "project", concept, known=9), _query("q-new", "project", concept, known=13)])
        initial_ids = ["version-1", "version-2"] if mode == "retract" else ["version-1", "version-1"]
        steps = [_ingest(initial_ids), _q("q-old", "old")]
        if mode == "retract":
            steps.append({"op": "retract", "source_id": "stable-source", "known_at": _time(12), "capture": "revision"})
        else:
            steps.append(_ingest(["version-2"]))
        steps.extend([_q("q-new", "incremental"), {"op": "clean_rebuild"}, _q("q-new", "rebuilt")])
        branches.append(_branch("main", steps))
        assertions.extend([
            _assert("old-root-live", "evidence.root_present@1", {"result": "main:old", "root": "stable-source"}, dimension="audit"),
            _assert("incremental-clean-equivalence", "result.equivalent@1", {"left": "main:incremental", "right": "main:rebuilt", "semantic_only": True}, dimension="audit"),
        ])
        if mode == "retract":
            assertions.extend([
                _assert("retracted-root-gone", "temporal.root_visibility@1", {"result": "main:incremental", "root": "stable-source", "visible": False}, dimension="audit"),
                _assert("independent-support-survives", "evidence.root_present@1", {"result": "main:incremental", "root": "independent-source"}, dimension="audit"),
                _assert("exactly-one-independent-root", "evidence.root_count@1", {"result": "main:incremental", "expected": 1}, dimension="audit"),
            ])
        else:
            assertions.extend([
                _assert("superseded-root-gone", "temporal.root_visibility@1", {"result": "main:incremental", "root": "stable-source", "visible": False}, dimension="temporal"),
                _assert("correction-root-live", "evidence.root_present@1", {"result": "main:incremental", "root": "stable-source-v2"}, dimension="temporal"),
            ])

    elif mode == "action_idempotency":
        # Duplicate delivery retries use the same idempotency key/source.  The
        # stop event has its own source and later effective/transaction times;
        # therefore the effect is live exactly once at hour 9 and absent after
        # cancellation at hour 12.
        performed = _artifact(
            "action-performed", concept, {"dose": 1.0, "drug": "drug-X"},
            source_id="action-A1-performed", role="performed_intervention",
            effective=8, available=8,
            context={"action_id": "A1", "stage": "performed", "idempotency_key": "A1/dose/1"},
        )
        stopped = _artifact(
            "action-stopped", concept, {"action_id": "A1"},
            source_id="action-A1-stop", role="stopped_intervention",
            effective=12, available=12, recorded=12, supersedes="action-A1-performed",
            context={"action_id": "A1", "stage": "cancelled", "idempotency_key": "A1/stop/1"},
        )
        artifacts.extend([performed, stopped])
        queries.extend([
            _query("q-during", "project", concept, known=9, valid=9, guarantees=("action_interval", "idempotent_delivery")),
            _query("q-after", "project", concept, known=13, valid=13, guarantees=("action_interval", "idempotent_delivery")),
        ])
        branches.append(_branch("main", [
            _ingest(["action-performed", "action-performed"]), _q("q-during", "during"),
            _ingest(["action-stopped"]), _q("q-after", "after"),
            {"op": "clean_rebuild"}, _q("q-after", "rebuilt"),
        ]))
        assertions.extend([
            _assert("delivery-idempotent-one-root", "evidence.root_count@1", {"result": "main:during", "expected": 1}, dimension="audit"),
            _assert("performed-live-during", "temporal.root_visibility@1", {"result": "main:during", "root": "action-A1-performed", "visible": True}, dimension="temporal"),
            _assert("performed-stopped-after-cancel", "temporal.root_visibility@1", {"result": "main:after", "root": "action-A1-performed", "visible": False, "allow_ineligible_statuses": ["insufficient"]}, dimension="temporal"),
            _assert("no-effect-roots-after-cancel", "evidence.root_count@1", {"result": "main:after", "expected": 0, "allow_ineligible_statuses": ["insufficient"]}, dimension="causal"),
            _assert("cancel-clean-equivalence", "result.equivalent@1", {"left": "main:after", "right": "main:rebuilt", "semantic_only": True, "allow_ineligible_statuses": ["insufficient"]}, dimension="audit"),
        ])

    elif mode == "safety":
        public.update({"retrieval_control": {"semantic_retriever_hits": [], "deterministic_invariants_must_still_run": True}})
        modules.append({"module_id": "safety-invariant", "family": "invariant", "closed_ir": {"op": "forbid", "condition": "allergy_match"}})
        artifacts.append(_artifact("allergy-root", "drug_allergy", "drug-X"))
        queries.append(_query("q-main", "check_invariant", concept, guarantees=("safety",)))
        branches.append(_branch("main", [{"op": "register_module", "module_id": "safety-invariant"}, _ingest(["allergy-root"]), _q("q-main", "result")]))
        assertions.extend([
            _assert("safety-not-silent", "result.status@1", {"result": "main:result", "expected": ["ok", "conflicting"]}, dimension="safety"),
            _assert("safety-consumes-allergy-root", "evidence.root_present@1", {"result": "main:result", "root": "allergy-root"}, dimension="audit"),
        ])

    elif mode == "paraphrase":
        artifacts.extend([
            _artifact("phrase-a", concept, True, raw={"source_text": "shortness of breath", "span": [0, 19]}),
            _artifact("phrase-b", concept, True, raw={"source_text": "dyspnoea", "span": [0, 8]}),
        ])
        queries.append(_query("q-main", "project", concept))
        branches.extend([
            _branch("a", [_ingest(["phrase-a"]), _q("q-main", "result")]),
            _branch("b", [_ingest(["phrase-b"]), _q("q-main", "result")]),
        ])
        assertions.extend([
            _assert("semantic-isomorphism", "result.equivalent@1", {"left": "a:result", "right": "b:result", "semantic_only": True, "ignore_roots": True}, dimension="extension"),
            _assert("first-wording-live", "evidence.root_present@1", {"result": "a:result", "root": "phrase-a"}, dimension="audit"),
            _assert("second-wording-live", "evidence.root_present@1", {"result": "b:result", "root": "phrase-b"}, dimension="audit"),
        ])

    elif mode == "rootless_cycle":
        modules.append({"module_id": "cycle", "family": "rewrite", "rules": [{"if": "B", "then": concept}, {"if": concept, "then": "B"}]})
        artifacts.append(_artifact("ground-root", "B", True))
        queries.append(_query("q-main", "reachability", concept, guarantees=("rooted_support",)))
        branches.extend([
            _branch("rootless", [{"op": "register_module", "module_id": "cycle"}, _q("q-main", "result")]),
            _branch("grounded-control", [{"op": "register_module", "module_id": "cycle"}, _ingest(["ground-root"]), _q("q-main", "result")]),
        ])
        assertions.extend([
            _assert("no-rootless-support", "evidence.root_count@1", {"result": "rootless:result", "expected": 0, "allow_ineligible_statuses": ["insufficient"]}, dimension="audit"),
            _assert("grounded-cycle-is-live", "evidence.root_present@1", {"result": "grounded-control:result", "root": "ground-root"}, dimension="audit"),
        ])

    elif mode == "units":
        modules.append({
            "module_id": "glucose-unit-adapter-v1", "family": "typed_unit_adapter",
            "model_version": "ucum-glucose-v1",
            "public_model": {
                "input_concept": "serum_glucose_raw", "output_concept": concept,
                "from_unit": "mg/dL", "to_unit": "mmol/L",
                "closed_ir": {"op": "multiply", "factor": 0.0555},
            },
        })
        artifacts.extend([
            _artifact("convertible", "serum_glucose_raw", 100, unit="mg/dL", raw={"source_text": "glucose 100 mg/dL", "span": [8, 17]}),
            _artifact("incompatible", "serum_glucose_raw", 5, unit="meters", raw={"source_text": "glucose 5 meters", "span": [8, 16]}),
        ])
        queries.extend([
            _query("q-raw", "project", "serum_glucose_raw", guarantees=("raw_roundtrip",)),
            _query("q-canonical", "project", concept, guarantees=("typed_unit_conversion", "conversion_trace")),
        ])
        branches.extend([
            _branch("legal", [
                {"op": "register_module", "module_id": "glucose-unit-adapter-v1", "capture": "registration"},
                _ingest(["convertible"], "ingest"), _q("q-raw", "raw"), _q("q-canonical", "canonical"),
            ]),
            _branch("illegal", [
                {"op": "register_module", "module_id": "glucose-unit-adapter-v1", "capture": "registration"},
                _ingest(["incompatible"], "ingest"), _q("q-raw", "raw"), _q("q-canonical", "canonical"),
            ]),
        ])
        assertions.extend([
            _assert("legal-conversion-live", "result.status@1", {"result": "legal:canonical", "expected": ["ok"]}, dimension="extension"),
            _assert("legal-raw-preserved", "evidence.raw_roundtrip@1", {"result": "legal:raw", "root": "convertible", "raw_value": 100, "raw_unit": "mg/dL", "span": [8, 17], "mapping_version": "fixture-map-v1"}, dimension="audit"),
            _assert("incompatible-raw-preserved", "evidence.raw_roundtrip@1", {"result": "illegal:raw", "root": "incompatible", "raw_value": 5, "raw_unit": "meters", "span": [8, 16], "mapping_version": "fixture-map-v1"}, dimension="audit"),
            _assert("incompatible-canonical-typed", "result.typed_boundary@1", {"result": "illegal:canonical", "allowed": ["invalid", "unsupported", "insufficient", "out_of_model"]}, dimension="safety"),
        ])

    elif mode == "numerical":
        recurrence_ir = {
            "op": "linear_recurrence",
            "state": concept,
            "coefficient": 0.8,
            "input": 0.1,
            "initial": 0.2,
            "step_hours": 1.0,
            "horizon_hours": 24.0,
        }
        modules.append({
            "module_id": "numeric-model", "family": "state_space",
            "public_model": {"closed_ir": dict(recurrence_ir)},
        })
        queries.append(_query("q-main", "forecast", concept, horizon=24, guarantees=("solver_diagnostics",)))
        branches.append(_branch("main", [{"op": "register_module", "module_id": "numeric-model"}, _q("q-main", "result")]))
        assertions.extend([
            _assert(
                "numeric-diagnostics", "result.numeric_contract@1",
                {
                    "result": "main:result",
                    "allowed_computation": ["exact", "approx", "approximate", "nonconverged", "not_converged", "numerical_failure"],
                    "required_diagnostics": {"seed": True, "error_any_of": ["error", "error_bound", "tolerance", "residual"]},
                },
                dimension="dynamic", hard=True,
            ),
            _assert(
                "recurrence-value-and-horizon", "reference.closed_recurrence@1",
                {
                    "result": "main:result",
                    "closed_recurrence": dict(recurrence_ir),
                    "target": concept,
                    "horizon_hours": 24.0,
                    "absolute_tolerance": 1e-12,
                    "relative_tolerance": 1e-12,
                },
                dimension="dynamic", hard=True,
            ),
        ])

    elif mode == "quarantine":
        artifacts.append(
            _artifact(
                "unknown-device-root",
                concept,
                77,
                method="unregistered-device-v99",
                unit="vendor-unit-v99",
                raw={"device_packet": "opaque-but-preserved", "span": [0, 20]},
            )
        )
        queries.extend([
            _query("q-raw", "project", concept, guarantees=("raw_roundtrip",)),
            _query("q-canonical", "project", "canonical_device_measurement", guarantees=("registered_device_adapter",)),
        ])
        branches.append(_branch("main", [
            _ingest(["unknown-device-root"], "ingest"), _q("q-raw", "raw"), _q("q-canonical", "canonical"),
        ]))
        assertions.extend([
            _assert("raw-ingest-accepted", "result.status@1", {"result": "main:ingest", "expected": ["ok"]}, dimension="audit"),
            _assert("unknown-device-raw-preserved", "evidence.raw_roundtrip@1", {"result": "main:raw", "root": "unknown-device-root", "raw_value": 77, "raw_unit": "vendor-unit-v99", "span": [0, 20], "mapping_version": "fixture-map-v1"}, dimension="audit"),
            _assert("unknown-device-canonical-typed", "result.typed_boundary@1", {"result": "main:canonical", "allowed": ["invalid", "unsupported", "insufficient", "out_of_model"]}, dimension="safety"),
        ])

    elif mode == "action":
        artifacts.extend([
            _artifact("ordered", concept, "drug-X", role="order", context={"performed": False, "stage": "ordered"}),
            _artifact("performed", concept, "drug-X", role="performed_intervention", context={"stage": "performed", "actual_interval": [_time(8), _time(10)]}),
        ])
        queries.append(_query("q-main", "project", concept))
        branches.extend([
            _branch("ordered", [_ingest(["ordered"]), _q("q-main", "result")]),
            _branch("performed", [_ingest(["performed"]), _q("q-main", "result")]),
        ])
        assertions.extend([
            _assert("action-stage-distinct", "result.distinct@1", {"left": "ordered:result", "right": "performed:result", "semantic_only": True, "allow_ineligible_statuses": ["insufficient"]}, dimension="causal"),
            # Allowing the ordered arm to be explicitly insufficient is sound
            # only because the performed arm must still expose its real root.
            _assert("performed-action-live", "evidence.root_present@1", {"result": "performed:result", "root": "performed"}, dimension="audit"),
        ])

    elif mode == "ports":
        modules.append({"module_id": "bad-wiring", "family": "typed_composition", "ports": [{"from": "Observation[MAP]", "to": "LatentState[renal]", "compatible": False}]})
        queries.append(_query("q-main", "check_invariant", concept))
        branches.append(_branch("main", [{"op": "register_module", "module_id": "bad-wiring", "capture": "registration"}, _q("q-main", "result")]))
        assertions.append(_assert("port-failure", "result.typed_boundary@1", {"result": "main:registration", "allowed": ["invalid", "unsupported"]}, dimension="composition"))

    elif mode == "scope":
        artifacts.extend([
            _artifact("p1-root", concept, "positive", subject="P1", encounter="E1", specimen="S1"),
            _artifact("p2-root", concept, "negative", subject="P2", encounter="E2", specimen="S2"),
        ])
        queries.append(_query("q-main", "project", concept))
        branches.append(_branch("main", [_ingest(["p1-root", "p2-root"]), _q("q-main", "result")]))
        assertions.extend([
            _assert("own-scope-visible", "temporal.root_visibility@1", {"result": "main:result", "root": "p1-root", "visible": True}, dimension="safety"),
            _assert("foreign-scope-hidden", "temporal.root_visibility@1", {"result": "main:result", "root": "p2-root", "visible": False}, dimension="safety"),
        ])

    elif mode == "censored":
        artifacts.append(_artifact("censored-root", concept, {"comparator": "<", "limit": 20}, information_state="censored_low", unit="copies/mL", method="assay-v2"))
        queries.append(_query("q-main", "project", concept))
        branches.append(_branch("main", [_ingest(["censored-root"]), _q("q-main", "result")]))
        assertions.extend([
            _assert("censoring-preserved", "result.information_state@1", {"result": "main:result", "expected": ["censored_low"], "allow_ineligible_statuses": ["insufficient"]}, dimension="epistemic"),
            _assert("censored-root-preserved", "evidence.root_present@1", {"result": "main:result", "root": "censored-root", "allow_ineligible_statuses": ["insufficient"]}, dimension="audit"),
        ])

    elif mode == "not_observed":
        artifacts.append(_artifact("not-tested", concept, None, information_state="not_tested", context={"ascertainment_opportunity": False}))
        queries.append(_query("q-main", "project", concept))
        branches.append(_branch("main", [_ingest(["not-tested"]), _q("q-main", "result")]))
        assertions.extend([
            _assert("not-tested-preserved", "result.information_state@1", {"result": "main:result", "expected": ["not_tested"], "allow_ineligible_statuses": ["insufficient"]}, dimension="epistemic"),
            _assert("not-tested-root-preserved", "evidence.root_present@1", {"result": "main:result", "root": "not-tested", "allow_ineligible_statuses": ["insufficient"]}, dimension="audit"),
        ])

    elif mode == "raw_roundtrip":
        raw = {"source_text": "Cr 1.8 mg/dL", "span": [0, 13], "payload_sha256": "sha256:fixture", "mapping_version": "fixture-map-v1"}
        artifacts.append(_artifact("raw-root", concept, 1.8, unit="mg/dL", raw=raw))
        queries.append(_query("q-main", "project", concept, guarantees=("raw_roundtrip",)))
        branches.append(_branch("main", [_ingest(["raw-root"]), _q("q-main", "result")]))
        assertions.extend([
            _assert("raw-root-trace", "evidence.root_present@1", {"result": "main:result", "root": "raw-root"}, dimension="audit"),
            _assert("raw-fields-roundtrip", "evidence.raw_roundtrip@1", {"result": "main:result", "root": "raw-root", "raw_value": 1.8, "raw_unit": "mg/dL", "span": [0, 13], "mapping_version": "fixture-map-v1"}, dimension="audit"),
        ])

    elif mode == "knowledge_scope":
        artifacts.extend([
            _artifact(
                "knowledge-root", "disease_knowledge_rule",
                {"antecedent": "exposure-X", "consequent": concept}, role="general_knowledge",
            ),
            _artifact("patient-root", concept, "P1_has_condition", role="raw_observation"),
        ])
        queries.append(_query("q-main", "project", concept))
        branches.extend([
            _branch("knowledge-only", [_ingest(["knowledge-root"]), _q("q-main", "result")]),
            _branch("patient-control", [_ingest(["knowledge-root", "patient-root"]), _q("q-main", "result")]),
        ])
        assertions.extend([
            _assert("knowledge-not-patient-fact", "result.not_contains@1", {"result": "knowledge-only:result", "forbidden": "P1_has_condition", "allow_ineligible_statuses": ["insufficient"]}, dimension="safety"),
            _assert("patient-evidence-is-live", "result.contains_all@1", {"result": "patient-control:result", "expected": ["P1_has_condition"]}, dimension="safety"),
            _assert("patient-root-trace", "evidence.root_present@1", {"result": "patient-control:result", "root": "patient-root"}, dimension="audit"),
        ])

    elif mode == "masked":
        artifacts.extend([
            _artifact("masked-root", concept, None, information_state="masked", role="masked_artifact"),
            _artifact("negative-root", concept, False, information_state="absent"),
        ])
        queries.append(_query("q-main", "project", concept))
        branches.extend([
            _branch("masked", [_ingest(["masked-root"]), _q("q-main", "result")]),
            _branch("negative", [_ingest(["negative-root"]), _q("q-main", "result")]),
        ])
        assertions.extend([
            _assert("masked-state", "result.information_state@1", {"result": "masked:result", "expected": ["masked"], "allow_ineligible_statuses": ["insufficient"]}, dimension="safety"),
            _assert("masked-not-negative", "result.distinct@1", {"left": "masked:result", "right": "negative:result", "semantic_only": True, "allow_ineligible_statuses": ["insufficient"]}, dimension="safety"),
            _assert("masked-root-preserved", "evidence.root_present@1", {"result": "masked:result", "root": "masked-root", "allow_ineligible_statuses": ["insufficient"]}, dimension="audit"),
            _assert("negative-state-preserved", "result.information_state@1", {"result": "negative:result", "expected": ["absent", "refuted"]}, dimension="safety"),
            _assert("negative-root-preserved", "evidence.root_present@1", {"result": "negative:result", "root": "negative-root"}, dimension="audit"),
        ])
    else:  # pragma: no cover - registry exhaustiveness test protects this
        raise KeyError(f"unimplemented T workload mode: {test_id} / {mode}")

    return _envelope(test_id, title, artifacts, queries, branches, assertions, modules=modules, public=public)


E_TITLES = {
    "E01": "treatment-masked latent filtering forecast and counterfactual",
    "E02": "confounding reverses observational and interventional signs",
    "E03": "individual counterfactual shares abduced exogenous background",
    "E04": "irregular nonlinear lagged dynamics with pulse intervention",
    "E05": "same phenotype two mechanisms and selective interventions",
    "E06": "nonlinear three-module composition and explicit interaction",
    "E07": "composition bracketing registration and update-order robustness",
    "E08": "valid feedback versus rootless epistemic self-support",
}


def build_e_workload(experiment_id: str) -> dict[str, Any]:
    model = public_model(experiment_id)
    modules = [{"module_id": "public-model", "family": model["model_kind"], "public_model": model}]
    artifacts: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = [{"op": "register_module", "module_id": "public-model", "capture": "registration"}]
    assertions: list[dict[str, Any]] = []

    if experiment_id == "E01":
        ref = reference_output("E01")
        for index, row in enumerate(ref["observations"]):
            artifacts.append(_artifact(f"obs-{index}", "mean_arterial_pressure", row["MAP"], effective=int(row["hour"]), available=int(row["hour"]), unit="mmHg", context={"performed_support_U": row["U"]}))
        queries.extend([
            _query("q-filter", "filter", "S", known=12, valid=9),
            _query("q-forecast", "forecast", "S", known=12, valid=12, horizon=12),
            _query("q-cf", "counterfactual", "S", known=12, valid=12, intervention={"variable": "U", "value": 0}, horizon=12),
        ])
        steps += [_ingest([a["artifact_id"] for a in artifacts]), _q("q-filter", "filter"), _q("q-forecast", "forecast"), _q("q-cf", "counterfactual")]
        assertions.extend([
            _assert("filter-reference", "reference.scalar@1", {"result": "main:filter", "reference_id": "E01", "reference_path": "/state_trajectory/0/S", "candidate_paths": ["/value/probability", "/value/state", "/value/S"], "absolute_tolerance": 0.15}, dimension="dynamic"),
            _assert("forecast-not-cf", "result.distinct@1", {"left": "main:forecast", "right": "main:counterfactual", "semantic_only": True}, dimension="causal"),
        ])
    elif experiment_id == "E02":
        for name, kind, treatment in (("obs1", "condition", 1), ("obs0", "condition", 0), ("do1", "intervene", 1), ("do0", "intervene", 0)):
            queries.append(_query(f"q-{name}", kind, "Y_bad", intervention={"variable": "T", "value": treatment} if kind == "intervene" else None, task=f"T={treatment}"))
            steps.append(_q(f"q-{name}", name))
        ref_paths = {"obs1": "/P_bad_given_T1", "obs0": "/P_bad_given_T0", "do1": "/P_bad_given_do_T1", "do0": "/P_bad_given_do_T0"}
        for capture, path in ref_paths.items():
            assertions.append(_assert(f"{capture}-exact", "reference.scalar@1", {"result": f"main:{capture}", "reference_id": "E02", "reference_path": path, "candidate_paths": ["/value/probability", "/value"], "absolute_tolerance": 1e-9}, dimension="causal"))
        assertions.append(_assert("see-do-distinct", "result.distinct@1", {"left": "main:obs1", "right": "main:do1", "semantic_only": True}, dimension="causal"))
    elif experiment_id == "E03":
        queries.extend([
            _query("q-cf", "counterfactual", "Y", intervention={"variable": "T", "value": 0}, task="individual", guarantees=("share_abduced_exogenous",)),
            _query("q-pop", "intervene", "Y", intervention={"variable": "T", "value": 0}, task="population"),
        ])
        factual = _artifact("factual", "factual_T1_Y2", {"T": 1, "Y": 2})
        artifacts.append(factual); steps += [_ingest(["factual"]), _q("q-cf", "cf"), _q("q-pop", "population")]
        assertions.extend([
            _assert("individual-exact", "reference.scalar@1", {"result": "main:cf", "reference_id": "E03", "reference_path": "/individual_counterfactual_Y_T0", "candidate_paths": ["/value/probability", "/value/mean", "/value"], "absolute_tolerance": 1e-9}, dimension="causal"),
            _assert("population-exact", "reference.scalar@1", {"result": "main:population", "reference_id": "E03", "reference_path": "/population_do_mean_Y_T0", "candidate_paths": ["/value/probability", "/value/mean", "/value"], "absolute_tolerance": 1e-9}, dimension="causal"),
        ])
    elif experiment_id == "E04":
        queries.extend([_query("q-filter", "filter", "C", known=16, valid=16), _query("q-forecast", "forecast", "C", known=24, valid=24, horizon=16)])
        steps += [_q("q-filter", "filter"), _q("q-forecast", "forecast")]
        assertions.append(_assert("trajectory-reference", "reference.trajectory@1", {"result": "main:forecast", "reference_id": "E04", "reference_path": "/trajectory", "absolute_tolerance": 0.08, "relative_tolerance": 0.15}, dimension="dynamic"))
    elif experiment_id == "E05":
        artifacts.extend([_artifact("phenotype", "fever_crp_phenotype", True), _artifact("antipyretic", "antipyretic_response", True, role="performed_intervention"), _artifact("antibiotic", "antibiotic_mechanism_response", True, role="performed_intervention")])
        queries.extend([_query("q-pre", "filter", "diagnostic_hypothesis", known=8), _query("q-antipyretic", "filter", "diagnostic_hypothesis", known=9), _query("q-antibiotic", "filter", "diagnostic_hypothesis", known=10)])
        steps += [_ingest(["phenotype"]), _q("q-pre", "pre"), _ingest(["antipyretic"]), _q("q-antipyretic", "antipyretic"), _ingest(["antibiotic"]), _q("q-antibiotic", "antibiotic")]
        assertions.extend([
            _assert("antipyretic-nonselective", "result.equivalent@1", {"left": "main:pre", "right": "main:antipyretic", "semantic_only": True}, dimension="causal"),
            _assert("antibiotic-selective", "result.distinct@1", {"left": "main:antipyretic", "right": "main:antibiotic", "semantic_only": True}, dimension="causal"),
            _assert("selective-reference", "reference.scalar@1", {"result": "main:antibiotic", "reference_id": "E05", "reference_path": "/after_antibiotic_response/infection", "candidate_paths": ["/value/probability", "/value/infection_probability", "/value"], "absolute_tolerance": 1e-9}, dimension="causal"),
        ])
    elif experiment_id == "E06":
        queries.append(_query("q-forecast", "forecast", "burden", horizon=24, guarantees=("explicit_interaction",)))
        steps.append(_q("q-forecast", "forecast"))
        assertions.append(_assert("nonlinear-composition", "reference.trajectory@1", {"result": "main:forecast", "reference_id": "E06", "reference_path": "/trajectory", "absolute_tolerance": 0.08, "relative_tolerance": 0.15}, dimension="composition"))
    elif experiment_id == "E07":
        queries.append(_query("q-compose", "check_invariant", "composition_result", guarantees=("associativity", "all_modules_used")))
        steps.append(_q("q-compose", "composition"))
        assertions.extend([
            _assert("composition-reference", "reference.scalar@1", {"result": "main:composition", "reference_id": "E07", "reference_path": "/left_bracket", "candidate_paths": ["/value/result", "/value"], "absolute_tolerance": 1e-12}, dimension="composition"),
            _assert("all-modules-used", "result.contains_all@1", {"result": "main:composition", "expected": ["A", "B", "C"]}, dimension="composition"),
        ])
    elif experiment_id == "E08":
        queries.extend([_query("q-fixed", "check_invariant", "contraction"), _query("q-cycle", "reachability", "rootless_support"), _query("q-no", "check_invariant", "no_solution"), _query("q-many", "check_invariant", "non_unique")])
        steps += [_q("q-fixed", "fixed"), _q("q-cycle", "cycle"), _q("q-no", "no_solution"), _q("q-many", "non_unique")]
        assertions.extend([
            _assert("fixed-point", "reference.scalar@1", {"result": "main:fixed", "reference_id": "E08", "reference_path": "/contraction/value", "candidate_paths": ["/value/value", "/value"], "absolute_tolerance": 1e-8}, dimension="dynamic"),
            _assert("rootless-empty", "evidence.root_count@1", {"result": "main:cycle", "expected": 0, "allow_ineligible_statuses": ["insufficient"]}, dimension="audit"),
            _assert("no-solution-explicit", "result.computation@1", {"result": "main:no_solution", "expected": ["no_solution"]}, dimension="numerical"),
            _assert("non-unique-explicit", "result.computation@1", {"result": "main:non_unique", "expected": ["multiple_solutions"]}, dimension="numerical"),
        ])
    else:  # pragma: no cover
        raise KeyError(experiment_id)

    return _envelope(experiment_id, E_TITLES[experiment_id], artifacts, queries, [_branch("main", steps)], assertions, modules=modules, public=model)


def build_all_workloads() -> dict[str, dict[str, Any]]:
    workloads = {test_id: build_t_workload(test_id) for test_id in sorted(TITLES)}
    workloads.update({experiment_id: build_e_workload(experiment_id) for experiment_id in sorted(E_TITLES)})
    return workloads


def candidate_view(workload: Mapping[str, Any]) -> dict[str, Any]:
    """Return only public candidate input; asserts physical oracle separation."""

    if "candidate_view" not in workload or "oracle_view" not in workload:
        raise ValueError("workload must contain candidate_view and oracle_view")
    view = copy.deepcopy(workload["candidate_view"])
    encoded = json.dumps(view, sort_keys=True)
    for forbidden in ("oracle_view", "assertion_id", "reference_path", "expected"):
        if forbidden in encoded:
            raise ValueError(f"candidate view leaked runner-only field: {forbidden}")
    return view


def oracle_view(workload: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(workload["oracle_view"])


def save_workloads(root: str | Path = DEFAULT_WORKLOAD_ROOT) -> list[Path]:
    root_path = Path(root)
    written: list[Path] = []
    for workload_id, workload in build_all_workloads().items():
        panel = workload["panel"]
        target = root_path / panel / f"{workload_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(workload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(target)
    return written


def load_workloads(root: str | Path = DEFAULT_WORKLOAD_ROOT) -> dict[str, dict[str, Any]]:
    root_path = Path(root)
    loaded: dict[str, dict[str, Any]] = {}
    for path in sorted(root_path.glob("[TE]/*.json")):
        workload = json.loads(path.read_text(encoding="utf-8"))
        workload_id = workload.get("workload_id")
        if not isinstance(workload_id, str) or path.stem != workload_id:
            raise ValueError(f"workload/file ID mismatch: {path}")
        if workload_id in loaded:
            raise ValueError(f"duplicate workload ID: {workload_id}")
        candidate_view(workload)  # leak check at load time
        loaded[workload_id] = workload
    return loaded


__all__ = [
    "DEFAULT_WORKLOAD_ROOT", "PROTOCOL_VERSION", "build_all_workloads", "build_e_workload",
    "build_t_workload", "candidate_view", "load_workloads", "oracle_view", "save_workloads",
]
