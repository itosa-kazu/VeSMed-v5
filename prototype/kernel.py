"""K0 reference kernel: a typed control plane over three non-isomorphic kernels.

The module intentionally does **not** define a universal ``PatientState``.  It
routes a query to a temporal evidence cut, a finite causal/state posterior, or
a typed rewrite configuration and records which semantics produced the result.

Evidence may enter a model only through :class:`EvidenceModelBridge`.  A bridge
is immutable, versioned, closed data; it materialises one unambiguous evidence
claim into a fresh model run.  This prevents a mutable "latest state" cache from
silently changing an historical calculation.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping

from .candidates.causal_state import CausalStateCandidate, DynamicModule, FiniteSCMModule
from .candidates.rewrite_open import OpenComponent, RewriteModule, RewriteOpenCandidate
from .candidates.temporal_ledger import TemporalEvidenceLedger, TemporalRuleModule
from .contract import (
    ArchitectureCandidate,
    CandidateManifest,
    CapabilityResult,
    ClockSet,
    ContractError,
    InfoState,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
    Track,
    parse_time,
)


class Subkernel(str, Enum):
    """The three fixed semantic origins in K0."""

    EVIDENCE = "evidence"
    CAUSAL_STATE = "causal_state"
    REWRITE_OPEN = "rewrite_open"


class BridgeTransform(str, Enum):
    """Closed, deliberately tiny evidence-to-model transform vocabulary."""

    IDENTITY = "identity"
    BOOLEAN_TO_BINARY = "boolean_to_binary"


@dataclass(frozen=True)
class RoutedQuery:
    """An explicit query route; no target-name or workload-id dispatch."""

    route: Subkernel
    spec: QuerySpec

    def __post_init__(self) -> None:
        if not isinstance(self.route, Subkernel) or not isinstance(self.spec, QuerySpec):
            raise ContractError("RoutedQuery requires a Subkernel and QuerySpec")


@dataclass(frozen=True)
class EvidenceModelBridge:
    """Immutable mapping from one evidence claim to one model input concept.

    There is no callback or general payload field.  New transforms require a
    reviewed enum/operator implementation rather than arbitrary execution.
    """

    bridge_id: str
    version: str
    registered_at: str
    source_concept: str
    target_concept: str
    transform: BridgeTransform = BridgeTransform.IDENTITY
    source_unit: str | None = None
    target_unit: str | None = None
    accepted_roles: tuple[SemanticRole, ...] = (
        SemanticRole.RAW_OBSERVATION,
        SemanticRole.SUBJECT_STATEMENT,
        SemanticRole.DETERMINISTIC_DERIVATION,
    )
    target_role: SemanticRole = SemanticRole.RAW_OBSERVATION

    def __post_init__(self) -> None:
        if not self.bridge_id or not self.version or not self.source_concept or not self.target_concept:
            raise ContractError("bridge_id/version/source_concept/target_concept must be non-empty")
        parse_time(self.registered_at)
        if not isinstance(self.transform, BridgeTransform):
            raise ContractError("bridge transform must be a closed BridgeTransform")
        if not self.accepted_roles or not all(isinstance(role, SemanticRole) for role in self.accepted_roles):
            raise ContractError("accepted_roles must contain typed SemanticRole values")
        if self.target_role not in {
            SemanticRole.RAW_OBSERVATION,
            SemanticRole.SUBJECT_STATEMENT,
            SemanticRole.PERFORMED_INTERVENTION,
            SemanticRole.STOPPED_INTERVENTION,
        }:
            raise ContractError("bridge target_role is not a model evidence/action channel")
        action_roles = {SemanticRole.PERFORMED_INTERVENTION, SemanticRole.STOPPED_INTERVENTION}
        if self.target_role in action_roles and any(role not in action_roles for role in self.accepted_roles):
            raise ContractError("a plan/observation bridge cannot manufacture a performed action")
        if self.transform is BridgeTransform.BOOLEAN_TO_BINARY and (
            self.source_unit is not None or self.target_unit is not None
        ):
            raise ContractError("boolean_to_binary bridge must be unitless")
        if self.transform is BridgeTransform.IDENTITY and self.source_unit != self.target_unit:
            raise ContractError("identity bridge cannot silently convert units")


@dataclass(frozen=True)
class BridgedQuery:
    """An explicit evidence cut followed by a native causal/state query."""

    bridge_id: str
    bridge_version: str
    evidence_query: QuerySpec
    model_query: QuerySpec

    def __post_init__(self) -> None:
        if not self.bridge_id or not self.bridge_version:
            raise ContractError("bridge id and version are required")
        if not isinstance(self.evidence_query, QuerySpec) or not isinstance(self.model_query, QuerySpec):
            raise ContractError("BridgedQuery requires two QuerySpec objects")
        if self.evidence_query.kind not in {
            QueryKind.PROJECT,
            QueryKind.REPLAY_AS_THEN,
            QueryKind.REINTERPRET_NOW,
        }:
            raise ContractError("the upstream side must be an evidence projection query")
        if self.evidence_query.subject_id != self.model_query.subject_id:
            raise ContractError("bridge cannot cross subject identity")
        if self.evidence_query.as_known_at != self.model_query.as_known_at:
            raise ContractError("evidence and model queries must share one explicit knowledge cut")


def _contains_callable(value: Any) -> bool:
    if callable(value):
        return True
    if isinstance(value, Mapping):
        return any(_contains_callable(key) or _contains_callable(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_callable(item) for item in value)
    return False


def _json_digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()


def _scope_from_claim(claim: Mapping[str, Any]) -> Scope:
    data = claim.get("scope")
    if not isinstance(data, Mapping):
        raise ContractError("evidence claim lacks typed scope")
    return Scope(
        subject_id=str(data.get("subject_id", "")),
        encounter_id=data.get("encounter_id"),
        specimen_id=data.get("specimen_id"),
        device_id=data.get("device_id"),
        site_id=data.get("site_id"),
        body_site=data.get("body_site"),
    )


class ClinicalKernel(ArchitectureCandidate):
    """Runnable K0 orchestration layer.

    The Candidate API adapter selects a route from the *query kind* only.  For
    ambiguous operations such as ``PROJECT``, callers should use
    :class:`RoutedQuery` or an ``evidence::``, ``causal::`` or ``rewrite::``
    target prefix.  This adapter never inspects workload/test identifiers.
    """

    VERSION = "k0-reference-0.1.0"

    def __init__(self, track: Track = Track.NATIVE) -> None:
        super().__init__(Track(track))
        self.evidence = TemporalEvidenceLedger(Track.NATIVE)
        self.causal_state = CausalStateCandidate(Track.NATIVE)
        self.rewrite_open = RewriteOpenCandidate(Track.NATIVE)
        self._causal_modules: dict[tuple[str, str], DynamicModule | FiniteSCMModule] = {}
        self._bridges: dict[tuple[str, str], EvidenceModelBridge] = {}
        self._results: dict[str, CapabilityResult] = {}

    @property
    def manifest(self) -> CandidateManifest:
        capabilities = tuple(
            sorted(
                {
                    *self.evidence.manifest.declared_query_capabilities,
                    *self.causal_state.manifest.declared_query_capabilities,
                    *self.rewrite_open.manifest.declared_query_capabilities,
                },
                key=lambda kind: kind.value,
            )
        )
        return CandidateManifest(
            candidate_id="k0-typed-clinical-control-plane",
            version=self.VERSION,
            formal_signature=(
                "TypedArtifactRole + IdentityAndScope + TypedTimeAndCut",
                "VersionedDerivationAndProvenance + ClosedQueryAlgebra",
                "ProductResultAndFailure + InvariantEnforcement",
                "EvidenceCut --versioned closed bridge--> model input",
            ),
            execution_semantics=(
                "explicit semantic-subkernel routing",
                "append evidence + non-causal rewrite replica",
                "fresh causal run per bridged evidence cut",
                "origin/version/witness preserving product result",
            ),
            companion_layers=("versioned evidence-to-model materialisation bridge",),
            primitive_profile={
                "control_plane": (
                    "typed artifact qualification",
                    "explicit time cut",
                    "closed route",
                    "orthogonal failure",
                ),
                "non_unified_native_states": (
                    "temporal evidence cut",
                    "finite posterior/counterfactual world",
                    "typed rewrite configuration",
                ),
            },
            foreign_boundaries=(
                {
                    "boundary": "evidence_to_model",
                    "policy": "only registered EvidenceModelBridge",
                    "callbacks": False,
                    "fresh_run": True,
                },
                {
                    "boundary": "continuous/public benchmark models",
                    "policy": "unsupported until a typed audited adapter is installed",
                    "callbacks": False,
                },
            ),
            declared_query_capabilities=capabilities,
            failure_types=tuple(ResultStatus),
        )

    # ------------------------------------------------------------------
    # Result/control-plane helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _semantic_state_kind(route: Subkernel) -> str:
        return {
            Subkernel.EVIDENCE: "temporal_evidence_cut",
            Subkernel.CAUSAL_STATE: "model_posterior_or_causal_world",
            Subkernel.REWRITE_OPEN: "typed_rewrite_configuration",
        }[route]

    def _decorate(
        self,
        result: CapabilityResult,
        route: Subkernel,
        operation: str,
        result_id: str,
        *,
        bridge: EvidenceModelBridge | None = None,
        route_is_explicit: bool = True,
    ) -> CapabilityResult:
        out = deepcopy(result)
        candidate = self._candidate(route)
        origin = {
            "control_plane": "K0",
            "subkernel": route.value,
            "candidate_id": candidate.manifest.candidate_id,
            "candidate_version": candidate.manifest.version,
            "native_state_kind": self._semantic_state_kind(route),
            "universal_patient_state": False,
        }
        if bridge is not None:
            origin["bridge"] = f"{bridge.bridge_id}@{bridge.version}"
        out.native_witness = {**deepcopy(out.native_witness), "capability_origin": origin}
        out.versions = {
            **deepcopy(out.versions),
            "kernel": self.VERSION,
            "origin_candidate": candidate.manifest.version,
            **({"bridge": bridge.version} if bridge is not None else {}),
        }
        out.diagnostics = {
            **deepcopy(out.diagnostics),
            "kernel_operation": operation,
            "kernel_result_id": result_id,
            "route_is_explicit": route_is_explicit,
        }
        self._results[result_id] = deepcopy(out)
        return out

    def _candidate(self, route: Subkernel) -> ArchitectureCandidate:
        if route is Subkernel.EVIDENCE:
            return self.evidence
        if route is Subkernel.CAUSAL_STATE:
            return self.causal_state
        if route is Subkernel.REWRITE_OPEN:
            return self.rewrite_open
        raise ContractError(f"unknown route: {route!r}")

    def _failure(
        self,
        status: ResultStatus,
        operation: str,
        reason: str,
        *,
        capability: str = "native",
        identification: str = "not_applicable",
        route: Subkernel = Subkernel.EVIDENCE,
        result_id: str | None = None,
    ) -> CapabilityResult:
        result = CapabilityResult(
            status=status,
            validation="invalid" if status is ResultStatus.INVALID else "valid",
            capability=capability,
            epistemic=("insufficient" if status is ResultStatus.INSUFFICIENT else "not_applicable"),
            coverage_status="out_of_model" if status in {ResultStatus.OUT_OF_MODEL, ResultStatus.UNSUPPORTED} else "unknown",
            identification=identification,
            computation="not_started",
            diagnostics={"reason": reason},
        )
        return self._decorate(result, route, operation, result_id or f"{operation}:failure")

    # ------------------------------------------------------------------
    # Candidate API: raw evidence is broadcast only to evidence semantics.
    # It is deliberately not inserted directly into the causal/state kernel.
    # ------------------------------------------------------------------
    def ingest(self, artifact: SourceArtifact) -> CapabilityResult:
        if not isinstance(artifact, SourceArtifact) or _contains_callable(artifact):
            return self._failure(ResultStatus.INVALID, "ingest", "ingest requires closed SourceArtifact", result_id="ingest:invalid")
        ledger_receipt = self.evidence.ingest(artifact)
        if ledger_receipt.status is not ResultStatus.OK:
            return self._decorate(ledger_receipt, Subkernel.EVIDENCE, "ingest", f"ingest:{artifact.source_id}")
        rewrite_receipt = self.rewrite_open.ingest(artifact)
        status = ResultStatus.OK if rewrite_receipt.status is ResultStatus.OK else rewrite_receipt.status
        result = CapabilityResult(
            status=status,
            validation="valid" if status is ResultStatus.OK else rewrite_receipt.validation,
            capability="native",
            epistemic="asserted" if status is ResultStatus.OK else rewrite_receipt.epistemic,
            coverage_status="evidence_planes_complete" if status is ResultStatus.OK else "partial",
            computation="exact",
            value_kind="kernel_ingest_receipt",
            value={
                "source_id": artifact.source_id,
                "evidence": ledger_receipt.to_dict(),
                "rewrite_replica": rewrite_receipt.to_dict(),
                "causal_state_ingested": False,
            },
            evidence_witness={"root_sources": [artifact.source_id]},
            native_witness={
                "fanout": [Subkernel.EVIDENCE.value, Subkernel.REWRITE_OPEN.value],
                "fanout_is_not_state_merge": True,
                "causal_ingest_requires_versioned_bridge": True,
            },
            versions={
                "evidence": self.evidence.manifest.version,
                "rewrite_open": self.rewrite_open.manifest.version,
                "mapping": artifact.mapping_version,
            },
        )
        return self._decorate(result, Subkernel.EVIDENCE, "ingest", f"ingest:{artifact.source_id}")

    def retract(self, source_id: str, known_at: str) -> CapabilityResult:
        ledger_receipt = self.evidence.retract(source_id, known_at)
        rewrite_receipt = self.rewrite_open.retract(source_id, known_at)
        if ledger_receipt.status is not ResultStatus.OK:
            status = ledger_receipt.status
        elif rewrite_receipt.status is not ResultStatus.OK:
            status = rewrite_receipt.status
        else:
            status = ResultStatus.OK
        result = CapabilityResult(
            status=status,
            validation="valid" if status is not ResultStatus.INVALID else "invalid",
            capability="native",
            epistemic="retracted" if status is ResultStatus.OK else ledger_receipt.epistemic,
            coverage_status="evidence_planes_complete" if status is ResultStatus.OK else "partial",
            computation="exact",
            value_kind="kernel_retraction_receipt",
            value={"source_id": source_id, "evidence": ledger_receipt.to_dict(), "rewrite_replica": rewrite_receipt.to_dict()},
            evidence_witness={"retracted_root": source_id},
            native_witness={"causal_runs_are_ephemeral": True, "stale_materialized_model_state": False},
        )
        return self._decorate(result, Subkernel.EVIDENCE, "retract", f"retract:{source_id}:{known_at}")

    # ------------------------------------------------------------------
    # Closed module registration.  Specific methods are the preferred API;
    # register_module is the benchmark-compatible type dispatcher.
    # ------------------------------------------------------------------
    def register_evidence_module(self, module: TemporalRuleModule) -> CapabilityResult:
        if not isinstance(module, TemporalRuleModule):
            return self._failure(ResultStatus.INVALID, "register_evidence_module", "requires TemporalRuleModule")
        result = self.evidence.register_module(module)
        return self._decorate(result, Subkernel.EVIDENCE, "register_module", f"module:evidence:{module.module_id}@{module.version}")

    def register_causal_module(self, module: DynamicModule | FiniteSCMModule) -> CapabilityResult:
        if not isinstance(module, (DynamicModule, FiniteSCMModule)):
            return self._failure(ResultStatus.INVALID, "register_causal_module", "requires DynamicModule or FiniteSCMModule", route=Subkernel.CAUSAL_STATE)
        result = self.causal_state.register_module(module)
        if result.status is ResultStatus.OK:
            self._causal_modules[(module.module_id, module.version)] = deepcopy(module)
        return self._decorate(result, Subkernel.CAUSAL_STATE, "register_module", f"module:causal:{module.module_id}@{module.version}")

    def register_rewrite_module(self, module: RewriteModule | OpenComponent) -> CapabilityResult:
        if not isinstance(module, (RewriteModule, OpenComponent)):
            return self._failure(ResultStatus.INVALID, "register_rewrite_module", "requires RewriteModule or OpenComponent", route=Subkernel.REWRITE_OPEN)
        result = self.rewrite_open.register_module(module)
        module_id = module.module_id if isinstance(module, RewriteModule) else module.component_id
        return self._decorate(result, Subkernel.REWRITE_OPEN, "register_module", f"module:rewrite:{module_id}@{module.version}")

    def register_module(self, module: Any) -> CapabilityResult:
        if _contains_callable(module):
            return self._failure(ResultStatus.INVALID, "register_module", "callbacks/callables are forbidden")
        if isinstance(module, TemporalRuleModule):
            return self.register_evidence_module(module)
        if isinstance(module, (DynamicModule, FiniteSCMModule)):
            return self.register_causal_module(module)
        if isinstance(module, (RewriteModule, OpenComponent)):
            return self.register_rewrite_module(module)
        if isinstance(module, Mapping):
            # Existing native candidates accept closed declarative mappings.
            # Dispatch is by declared schema, never by workload/test id.
            if module.get("kind") in {"dynamic", "finite_scm"}:
                try:
                    parsed = (
                        DynamicModule.from_data(module)
                        if module.get("kind") == "dynamic"
                        else FiniteSCMModule.from_data(module)
                    )
                except (ContractError, TypeError, ValueError) as exc:
                    return self._failure(ResultStatus.INVALID, "register_module", str(exc), route=Subkernel.CAUSAL_STATE)
                return self.register_causal_module(parsed)
            if {"version", "registered_at"}.issubset(module):
                result = self.evidence.register_module(module)
                return self._decorate(result, Subkernel.EVIDENCE, "register_module", f"module:evidence:{module.get('module_id', 'unknown')}")
            if "public_model" in module:
                return self._failure(
                    ResultStatus.UNSUPPORTED,
                    "register_module",
                    "public continuous/reference model requires a typed audited adapter; no expression string is executed",
                    capability="unsupported",
                    route=Subkernel.CAUSAL_STATE,
                    result_id=f"module:public:{module.get('module_id', 'unknown')}",
                )
        return self._failure(ResultStatus.INVALID, "register_module", "unknown closed module type/schema")

    def register_bridge(self, bridge: EvidenceModelBridge) -> CapabilityResult:
        if not isinstance(bridge, EvidenceModelBridge):
            return self._failure(ResultStatus.INVALID, "register_bridge", "requires EvidenceModelBridge")
        key = (bridge.bridge_id, bridge.version)
        existing = self._bridges.get(key)
        if existing is not None and existing != bridge:
            return self._failure(ResultStatus.INVALID, "register_bridge", "same bridge id/version has different immutable content")
        self._bridges[key] = deepcopy(bridge)
        result = CapabilityResult(
            status=ResultStatus.OK,
            capability="companion",
            coverage_status="complete",
            computation="exact",
            value_kind="bridge_receipt",
            value={"bridge_id": bridge.bridge_id, "version": bridge.version, "idempotent": existing == bridge},
            native_witness={"closed_ir": True, "callbacks": False, "fingerprint": _json_digest(bridge.__dict__)},
            versions={"bridge": bridge.version},
        )
        return self._decorate(result, Subkernel.EVIDENCE, "register_bridge", f"bridge:{bridge.bridge_id}@{bridge.version}", bridge=bridge)

    # ------------------------------------------------------------------
    # Query routing
    # ------------------------------------------------------------------
    @staticmethod
    def _split_target_prefix(spec: QuerySpec) -> tuple[Subkernel | None, QuerySpec]:
        prefixes = {
            "evidence::": Subkernel.EVIDENCE,
            "causal::": Subkernel.CAUSAL_STATE,
            "rewrite::": Subkernel.REWRITE_OPEN,
        }
        for prefix, route in prefixes.items():
            if spec.target.startswith(prefix):
                return route, replace(spec, target=spec.target[len(prefix) :])
        return None, spec

    @staticmethod
    def _default_route(kind: QueryKind) -> Subkernel:
        if kind in {QueryKind.REACHABILITY, QueryKind.CHECK_INVARIANT}:
            return Subkernel.REWRITE_OPEN
        if kind in {
            QueryKind.CONDITION,
            QueryKind.FILTER,
            QueryKind.SMOOTH,
            QueryKind.FORECAST,
            QueryKind.INTERVENE,
            QueryKind.COUNTERFACTUAL,
            QueryKind.EVALUATE_POLICY,
        }:
            return Subkernel.CAUSAL_STATE
        return Subkernel.EVIDENCE

    def query(self, request: QuerySpec | RoutedQuery) -> CapabilityResult:
        if isinstance(request, RoutedQuery):
            prefixed, spec = self._split_target_prefix(request.spec)
            if prefixed is not None and prefixed is not request.route:
                return self._failure(ResultStatus.INVALID, "query", "explicit route conflicts with target prefix", route=request.route, result_id=request.spec.query_id)
            route = request.route
            explicit_route = True
        elif isinstance(request, QuerySpec):
            prefixed, spec = self._split_target_prefix(request)
            route = prefixed or self._default_route(spec.kind)
            explicit_route = prefixed is not None
        else:
            return self._failure(ResultStatus.INVALID, "query", "query requires QuerySpec or RoutedQuery")
        if spec.kind is QueryKind.EXPLAIN:
            return self.explain(spec.target)
        result = self._candidate(route).query(spec)
        return self._decorate(result, route, "query", spec.query_id, route_is_explicit=explicit_route)

    # ------------------------------------------------------------------
    # Explicit evidence cut -> fresh native model execution
    # ------------------------------------------------------------------
    def query_through_bridge(self, request: BridgedQuery) -> CapabilityResult:
        if not isinstance(request, BridgedQuery):
            return self._failure(ResultStatus.INVALID, "query_through_bridge", "requires BridgedQuery", route=Subkernel.CAUSAL_STATE)
        bridge = self._bridges.get((request.bridge_id, request.bridge_version))
        if bridge is None:
            return self._failure(
                ResultStatus.OUT_OF_MODEL,
                "query_through_bridge",
                "requested immutable bridge version is not registered",
                route=Subkernel.CAUSAL_STATE,
                result_id=request.model_query.query_id,
            )
        cut = parse_time(request.evidence_query.as_known_at)
        registered = parse_time(bridge.registered_at)
        assert cut is not None and registered is not None
        if registered > cut:
            return self._failure(
                ResultStatus.OUT_OF_MODEL,
                "query_through_bridge",
                "bridge version was not available at the requested knowledge cut",
                route=Subkernel.CAUSAL_STATE,
                result_id=request.model_query.query_id,
            )
        if request.evidence_query.target != bridge.source_concept:
            return self._failure(
                ResultStatus.INVALID,
                "query_through_bridge",
                "upstream target does not match bridge source_concept",
                route=Subkernel.CAUSAL_STATE,
                result_id=request.model_query.query_id,
            )
        upstream = self.evidence.query(request.evidence_query)
        if upstream.status is not ResultStatus.OK:
            blocked = CapabilityResult(
                status=upstream.status,
                validation=upstream.validation,
                capability="companion",
                epistemic=upstream.epistemic,
                coverage_status="bridge_blocked_by_upstream_evidence",
                identification="not_attempted",
                computation="not_started",
                value_kind="bridge_blocked",
                value=None,
                evidence_witness={"upstream": deepcopy(upstream.evidence_witness)},
                native_witness={"causal_kernel_invoked": False},
                diagnostics={"upstream_status": upstream.status.value},
                versions={"evidence": upstream.versions, "bridge": bridge.version},
            )
            return self._decorate(blocked, Subkernel.CAUSAL_STATE, "query_through_bridge", request.model_query.query_id, bridge=bridge)
        claims = upstream.value.get("claims", []) if isinstance(upstream.value, Mapping) else []
        eligible = [
            claim
            for claim in claims
            if claim.get("concept") == bridge.source_concept
            and claim.get("semantic_role") in {role.value for role in bridge.accepted_roles}
            and claim.get("information_state") == InfoState.PRESENT.value
        ]
        if len(eligible) != 1:
            status = ResultStatus.INSUFFICIENT if not eligible else ResultStatus.CONFLICTING
            return self._failure(
                status,
                "query_through_bridge",
                f"bridge requires exactly one unambiguous present claim; found {len(eligible)}",
                capability="companion",
                identification="not_attempted",
                route=Subkernel.CAUSAL_STATE,
                result_id=request.model_query.query_id,
            )
        claim = eligible[0]
        if claim.get("unit") != bridge.source_unit:
            return self._failure(
                ResultStatus.OUT_OF_MODEL,
                "query_through_bridge",
                "source claim unit does not match immutable bridge contract",
                capability="companion",
                route=Subkernel.CAUSAL_STATE,
                result_id=request.model_query.query_id,
            )
        try:
            mapped_value = self._transform_bridge_value(bridge, claim.get("value"))
            artifact = self._materialize_bridge_artifact(bridge, claim, mapped_value, request)
        except (ContractError, TypeError, ValueError) as exc:
            return self._failure(
                ResultStatus.OUT_OF_MODEL,
                "query_through_bridge",
                str(exc),
                capability="companion",
                route=Subkernel.CAUSAL_STATE,
                result_id=request.model_query.query_id,
            )

        # A fresh engine is the model execution context for exactly this cut.
        # No previous materialisation can leak into it.
        run = CausalStateCandidate(Track.NATIVE)
        for module in sorted(self._causal_modules.values(), key=lambda item: (item.module_id, item.version)):
            receipt = run.register_module(deepcopy(module))
            if receipt.status is not ResultStatus.OK:
                return self._failure(
                    ResultStatus.INVALID,
                    "query_through_bridge",
                    "registered causal module failed fresh validation",
                    route=Subkernel.CAUSAL_STATE,
                    result_id=request.model_query.query_id,
                )
        ingest_receipt = run.ingest(artifact)
        if ingest_receipt.status not in {ResultStatus.OK, ResultStatus.OUT_OF_MODEL}:
            return self._decorate(ingest_receipt, Subkernel.CAUSAL_STATE, "query_through_bridge", request.model_query.query_id, bridge=bridge)
        downstream = run.query(request.model_query)
        downstream.evidence_witness = {
            "upstream_evidence": deepcopy(upstream.evidence_witness),
            "bridge_materialization": {
                "artifact_id": artifact.artifact_id,
                "source_claim_id": claim.get("claim_id"),
                "root_sources": list(claim.get("root_sources", [])),
                "transform": bridge.transform.value,
                "fresh_model_run": True,
            },
            "downstream_direct": deepcopy(downstream.evidence_witness),
        }
        downstream.native_witness = {
            **deepcopy(downstream.native_witness),
            "bridge_boundary": {
                "bridge_id": bridge.bridge_id,
                "version": bridge.version,
                "closed_transform": bridge.transform.value,
                "callback": False,
            },
        }
        downstream.versions = {
            **deepcopy(downstream.versions),
            "bridge": bridge.version,
            "evidence_candidate": self.evidence.manifest.version,
            "evidence_knowledge": request.evidence_query.knowledge_version,
        }
        downstream.assumptions = [
            *downstream.assumptions,
            "bridge materialisation is an explicit companion boundary, not native causal lineage",
        ]
        return self._decorate(downstream, Subkernel.CAUSAL_STATE, "query_through_bridge", request.model_query.query_id, bridge=bridge)

    @staticmethod
    def _transform_bridge_value(bridge: EvidenceModelBridge, value: Any) -> Any:
        if bridge.transform is BridgeTransform.IDENTITY:
            if not isinstance(value, (str, int, float, bool)) or value is None:
                raise ContractError("identity bridge accepts only a scalar closed value")
            return value
        if bridge.transform is BridgeTransform.BOOLEAN_TO_BINARY:
            if not isinstance(value, bool):
                raise ContractError("boolean_to_binary requires an actual boolean claim")
            return 1 if value else 0
        raise ContractError("unknown closed bridge transform")

    @staticmethod
    def _materialize_bridge_artifact(
        bridge: EvidenceModelBridge,
        claim: Mapping[str, Any],
        value: Any,
        request: BridgedQuery,
    ) -> SourceArtifact:
        scope = _scope_from_claim(claim)
        if scope.subject_id != request.model_query.subject_id:
            raise ContractError("claim subject does not match model query")
        fingerprint = _json_digest(
            {
                "bridge": [bridge.bridge_id, bridge.version],
                "claim_id": claim.get("claim_id"),
                "cut": request.evidence_query.as_known_at,
                "target": bridge.target_concept,
                "value": value,
            }
        ).split(":", 1)[1]
        source_id = f"bridge:{bridge.bridge_id}:{fingerprint[:20]}"
        return SourceArtifact(
            artifact_id=f"artifact:{source_id}",
            source_id=source_id,
            semantic_role=bridge.target_role,
            concept=bridge.target_concept,
            scope=scope,
            clocks=ClockSet(
                effective_start=str(claim["effective_start"]),
                effective_end=claim.get("effective_end"),
                collected_at=claim.get("collected_at"),
                available_at=str(claim["available_at"]),
                recorded_at=str(claim["recorded_at"]),
                expires_at=claim.get("expires_at"),
            ),
            information_state=InfoState.PRESENT,
            value=value,
            unit=bridge.target_unit,
            method=f"closed-bridge:{bridge.transform.value}",
            context={
                "bridge_id": bridge.bridge_id,
                "bridge_version": bridge.version,
                "source_claim_id": str(claim.get("claim_id")),
            },
            source_family=f"bridge:{bridge.bridge_id}@{bridge.version}",
            mapping_version=f"bridge:{bridge.bridge_id}@{bridge.version}",
        )

    # ------------------------------------------------------------------
    # Audit and rebuild
    # ------------------------------------------------------------------
    def explain(self, result_id: str) -> CapabilityResult:
        stored = self._results.get(result_id)
        if stored is None:
            return self._failure(ResultStatus.OUT_OF_MODEL, "explain", f"unknown kernel result_id {result_id!r}", result_id=f"explain:{result_id}")
        stored_origin = stored.native_witness.get("capability_origin", {})
        try:
            route = Subkernel(stored_origin.get("subkernel", Subkernel.EVIDENCE.value))
        except ValueError:
            route = Subkernel.EVIDENCE
        result = CapabilityResult(
            status=ResultStatus.OK,
            capability="native",
            epistemic="explanation_of_recorded_result",
            coverage_status="same_as_explained_result",
            computation="exact",
            value_kind="kernel_explanation",
            value=stored.to_dict(),
            evidence_witness=deepcopy(stored.evidence_witness),
            native_witness={"immutable_result_snapshot": True, "explained_result_id": result_id},
            versions=deepcopy(stored.versions),
        )
        return self._decorate(result, route, "explain", f"explain:{result_id}")

    def clean_rebuild(self) -> "ClinicalKernel":
        rebuilt = type(self)(self.track)
        rebuilt.evidence = self.evidence.clean_rebuild()
        rebuilt.causal_state = self.causal_state.clean_rebuild()
        rebuilt.rewrite_open = self.rewrite_open.clean_rebuild()
        rebuilt._causal_modules = deepcopy(self._causal_modules)
        rebuilt._bridges = deepcopy(self._bridges)
        # Execution results are receipts, not reconstructible clinical inputs.
        rebuilt._results.clear()
        return rebuilt


def build_candidate(track: Track = Track.NATIVE) -> ClinicalKernel:
    """Benchmark/factory entry point with no hidden shared state."""

    return ClinicalKernel(track)


__all__ = [
    "BridgeTransform",
    "BridgedQuery",
    "ClinicalKernel",
    "EvidenceModelBridge",
    "RoutedQuery",
    "Subkernel",
    "build_candidate",
]
