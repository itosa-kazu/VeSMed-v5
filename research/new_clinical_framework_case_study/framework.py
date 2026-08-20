"""Transparent minimum implementation of the *new* clinical-map framework.

This research engine is deliberately independent of VeSMed V5.  It provides a
recursive, serializable shared belief state with branch posterior, branch-local
coordinates, discrete modes, typed factor evidence, action exposure, topology
distance, and one common rollout core.  Its numerical kernels are ordinal and
uncalibrated; passing the structural contracts is not clinical validation.
"""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value: Any) -> str:
    payload = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(payload).hexdigest()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _severity(value: Any) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        if 0.0 <= number <= 1.0:
            return number
        return _clamp(math.log1p(abs(number)) / 10.0)
    if isinstance(value, Mapping):
        for key in ("severity", "level", "ordinal", "value"):
            if key in value:
                return _severity(value[key])
        return 0.5
    text = str(value).strip().lower()
    exact = {
        "absent": 0.0,
        "none": 0.0,
        "none_or_reference": 0.0,
        "negative": 0.0,
        "normal": 0.0,
        "preserved": 0.05,
        "low": 0.2,
        "mild": 0.3,
        "intermediate": 0.5,
        "equivocal": 0.5,
        "indeterminate": 0.5,
        "present": 0.7,
        "positive": 0.75,
        "high": 0.75,
        "marked": 0.85,
        "extreme": 1.0,
    }
    if text in exact:
        return exact[text]
    for token, score in (
        ("extreme", 1.0), ("marked", 0.85), ("positive", 0.75),
        ("high", 0.75), ("mild", 0.3), ("negative", 0.0), ("absent", 0.0),
    ):
        if token in text:
            return score
    return 0.5


@dataclass(frozen=True)
class PublicEvent:
    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicEvent":
        row = copy.deepcopy(dict(value))
        required = {"event_id", "event_type", "available_at"}
        missing = required.difference(row)
        if missing:
            raise ValueError(f"PublicEvent missing fields: {sorted(missing)}")
        return cls(row)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.payload)

    @property
    def digest(self) -> str:
        return _hash(self.payload)


@dataclass(frozen=True)
class SharedPatientState:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.payload)

    def to_wire(self) -> dict[str, Any]:
        return self.to_dict()

    def to_bytes(self) -> bytes:
        return _canonical(self.payload)

    @property
    def state_hash(self) -> str:
        return _hash(self.to_bytes())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SharedPatientState":
        return cls(copy.deepcopy(dict(value)))

    @classmethod
    def from_bytes(cls, payload: bytes) -> "SharedPatientState":
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("shared state bytes must decode to an object")
        return cls(value)


class FrameworkModel:
    protocol_version = "new-clinical-framework-minimum/1"

    def __init__(self, spec: Mapping[str, Any]) -> None:
        self.spec = copy.deepcopy(dict(spec))
        self.model_digest = _hash(self.spec)
        self.scope_digest = _hash(
            self.spec.get("scope", self.spec.get("blind_scope", self.spec.get("purpose", {})))
        )
        self._branches, self._unknown_branch = self._read_branches()
        self._parents = self._read_parent_graph()
        self._charts = self._read_charts()
        self._observed_nodes, self._factors = self._read_factors()
        self._concept_factor = self._make_factor_assignment()
        self._branch_latents = self._read_branch_latents()
        self._factor_branches = self._make_factor_branch_map()
        self._actions = self._read_actions()
        self._modes = self._read_modes()

    @classmethod
    def from_dict(
        cls, spec: Mapping[str, Any], options: Mapping[str, bool] | None = None
    ) -> "FrameworkModel":
        model = cls(spec)
        model.default_options = model._options(options)
        return model

    def _options(self, options: Mapping[str, bool] | None) -> dict[str, bool]:
        result = {
            "factor_dependence": True,
            "history": True,
            "actions": True,
            "mode": True,
            "topology": True,
        }
        result.update({str(k): bool(v) for k, v in (options or {}).items() if k in result})
        return result

    def _read_branches(self) -> tuple[list[str], str]:
        if "branch_graph" in self.spec:
            nodes = self.spec["branch_graph"].get("nodes", [])
            ids = [row["branch_id"] for row in nodes if row.get("node_type") in {"candidate_process", "candidate_event_process"}]
            unknown = self.spec.get("unknown_branch", {}).get("branch_id", "B_UNKNOWN")
        else:
            nodes = self.spec.get("topology", {}).get("nodes", [])
            ids = [row["id"] for row in nodes if row.get("kind") == "candidate_branch"]
            unknown = self.spec.get("unknown_branch", {}).get("id", "unknown_open_world")
        if not ids:
            raise ValueError("model has no candidate branches")
        return ids, unknown

    def _read_parent_graph(self) -> dict[str, tuple[str, ...]]:
        graph: dict[str, tuple[str, ...]] = {}
        if "branch_graph" in self.spec:
            for row in self.spec["branch_graph"].get("nodes", []):
                graph[row["branch_id"]] = tuple(row.get("parents", []))
        else:
            topology = self.spec.get("topology", {})
            for row in topology.get("nodes", []):
                graph[row["id"]] = ()
            for edge in topology.get("parent_edges", []):
                if isinstance(edge, Mapping):
                    child = edge.get("child") or edge.get("to")
                    parent = edge.get("parent") or edge.get("from")
                else:
                    parent, child = edge
                if child and parent:
                    graph[child] = tuple((*graph.get(child, ()), parent))
        graph.setdefault(self._unknown_branch, ())
        return graph

    def _read_charts(self) -> dict[str, list[dict[str, Any]]]:
        raw = self.spec.get("branch_local_charts", {})
        charts: dict[str, list[dict[str, Any]]] = {}
        if isinstance(raw, Mapping):
            for branch, body in raw.items():
                charts[branch] = [
                    {"id": coord if isinstance(coord, str) else coord.get("id"), "latent_ref": coord if isinstance(coord, str) else coord.get("latent_ref")}
                    for coord in body.get("coordinates", [])
                ]
        else:
            for body in raw:
                charts[body["branch_id"]] = [
                    {"id": coord if isinstance(coord, str) else coord.get("id"), "latent_ref": coord if isinstance(coord, str) else coord.get("latent_ref")}
                    for coord in body.get("coordinates", [])
                ]
        return charts

    def _read_factors(self) -> tuple[set[str], list[dict[str, Any]]]:
        graph = self.spec.get("typed_factor_graph", {})
        nodes = graph.get("observed_nodes", graph.get("observation_nodes", []))
        observed = {row["id"] for row in nodes}
        factors = copy.deepcopy(graph.get("factors", []))
        if not factors:
            for row in nodes:
                factors.append({
                    "factor_id": f"factor:{row['id']}",
                    "parents": list(row.get("parents", [])),
                    "children": [row["id"]],
                    "factor_type": "declared_observation_factor",
                })
        return observed, factors

    def _factor_children(self, factor: Mapping[str, Any]) -> list[str]:
        children = list(factor.get("children", []))
        if factor.get("child"):
            children.append(factor["child"])
        for pair in factor.get("parent_child_pairs", []):
            if len(pair) == 2:
                children.append(pair[1])
        return children

    def _make_factor_assignment(self) -> dict[str, str]:
        candidates: dict[str, list[tuple[int, str]]] = {}
        for factor in self._factors:
            factor_id = factor.get("factor_id", _hash(factor)[:12])
            factor_type = factor.get("factor_type", "")
            priority = 0 if "joint" in factor_type or "block" in factor_type else 1
            for child in self._factor_children(factor):
                candidates.setdefault(child, []).append((priority, factor_id))
        return {child: sorted(rows)[0][1] for child, rows in candidates.items()}

    def _read_branch_latents(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {branch: set() for branch in self._branches}
        for branch, coords in self._charts.items():
            if branch in result:
                for row in coords:
                    if row.get("latent_ref"):
                        result[branch].add(str(row["latent_ref"]))
                    if row.get("id"):
                        result[branch].add(str(row["id"]))
        if "branch_graph" in self.spec:
            by_id = {r["branch_id"]: r for r in self.spec["branch_graph"].get("nodes", [])}
            for branch in result:
                row = by_id.get(branch, {})
                gate = row.get("activation_gate")
                if gate:
                    result[branch].add(str(gate))
                for parent in row.get("parents", []):
                    result[branch].update(by_id.get(parent, {}).get("shared_latents", []))
        return result

    def _make_factor_branch_map(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for factor in self._factors:
            factor_id = factor.get("factor_id", _hash(factor)[:12])
            parents = {str(x) for x in factor.get("parents", [])}
            for pair in factor.get("parent_child_pairs", []):
                if pair:
                    parents.add(str(pair[0]))
            branches = [b for b, latents in self._branch_latents.items() if parents & latents]
            upper = (factor_id + " " + " ".join(parents)).upper()
            keyword = {
                "COMPLEMENT": [b for b in self._branches if "COMPLEMENT" in b.upper()],
                "ADAMTS13": [b for b in self._branches if "TTP" in b.upper()],
                "ANTI_GBM": [b for b in self._branches if "ANTI_GBM" in b.upper()],
                "PROCEDURAL": [b for b in self._branches if "BIOPSY" in b.upper()],
                "HEMATOMA": [b for b in self._branches if "BIOPSY" in b.upper()],
                "PF4": [b for b in self._branches if "HIT" in b.upper()],
                "HEPARIN": [b for b in self._branches if "HIT" in b.upper()],
                "HEPATIC": [b for b in self._branches if "HEPAT" in b.upper() or "LIVER" in b.upper()],
                "TAKOTSUBO": [b for b in self._branches if "TAKOTSUBO" in b.upper()],
                "MYOCARDIAL": [b for b in self._branches if any(k in b.upper() for k in ("TAKOTSUBO", "MYOCARD", "CORONARY"))],
                "PUMP": [b for b in self._branches if any(k in b.upper() for k in ("TAKOTSUBO", "MYOCARD", "CORONARY", "SHOCK"))],
            }
            for token, matches in keyword.items():
                if token in upper:
                    branches.extend(matches)
            result[factor_id] = sorted(set(branches or self._branches))
        return result

    def _read_actions(self) -> dict[str, dict[str, Any]]:
        if "actions" in self.spec:
            rows = self.spec["actions"].get("catalog", [])
        else:
            rows = self.spec.get("dynamics", {}).get("action_catalog", [])
        result: dict[str, dict[str, Any]] = {}
        if isinstance(rows, Mapping):
            for key, value in rows.items():
                body = dict(value) if isinstance(value, Mapping) else {"effect": value}
                body.setdefault("action_id", key)
                result[key] = body
        else:
            for row in rows:
                action_id = row.get("action_id") or row.get("id")
                if action_id:
                    result[str(action_id)] = copy.deepcopy(dict(row))
        return result

    def _read_modes(self) -> tuple[str, ...]:
        raw = self.spec.get("modes", {})
        ids = raw.get("mode_ids") if isinstance(raw, Mapping) else None
        if ids is None and isinstance(raw, Mapping):
            ids = list(raw.get("definitions", {}).keys()) or list(raw.keys())
        normalized: list[str] = []
        for value in ids or []:
            text = str(value).lower()
            for standard in ("compensated", "strained", "decompensated", "recovering"):
                if standard in text and standard not in normalized:
                    normalized.append(standard)
        return tuple(normalized or ("compensated", "strained", "decompensated", "recovering"))

    def _empty_payload(self, cut: Any, options: dict[str, bool]) -> dict[str, Any]:
        prior = 1.0 / len(self._branches)
        branch = {b: prior * 0.8 for b in self._branches}
        return {
            "protocol_version": self.protocol_version,
            "model_digest": self.model_digest,
            "scope_digest": self.scope_digest,
            "available_cut": cut,
            "branch_posterior": branch,
            "unknown_mass": 0.2,
            "per_branch": {},
            "mode_posterior": {"compensated": 1.0},
            "history_summary": {},
            "action_exposure": {},
            "factor_observations": {},
            "factor_evidence_counts": {},
            "recognized_observation_count": 0,
            "unrecognized_observation_count": 0,
            "lineage": {"parent_state_hash": None, "consumed_event_digests": []},
            "options": options,
            "warnings": [],
        }

    def initialize(
        self,
        events: Iterable[PublicEvent | Mapping[str, Any]],
        cut: Any,
        options: Mapping[str, bool] | None = None,
    ) -> SharedPatientState:
        active_options = self._options(options if options is not None else getattr(self, "default_options", None))
        rows = self._coerce_events(events)
        available = [row for row in rows if self._available(row.payload["available_at"], cut)]
        if not active_options["history"]:
            latest: dict[str, PublicEvent] = {}
            passthrough: list[PublicEvent] = []
            for row in available:
                if row.payload.get("event_type") == "ObservationAvailable":
                    latest[str(row.payload.get("concept_id"))] = row
                else:
                    passthrough.append(row)
            available = [*passthrough, *latest.values()]
        payload = self._empty_payload(cut, active_options)
        payload = self._consume(payload, available, parent_hash=None, advance_to=cut)
        return SharedPatientState(payload)

    def update(
        self,
        state: SharedPatientState,
        events: Iterable[PublicEvent | Mapping[str, Any]],
        advance_to: Any,
    ) -> SharedPatientState:
        self._assert_state(state)
        rows = [row for row in self._coerce_events(events) if self._available(row.payload["available_at"], advance_to)]
        payload = state.to_dict()
        payload = self._consume(payload, rows, parent_hash=state.state_hash, advance_to=advance_to)
        return SharedPatientState(payload)

    def _coerce_events(self, values: Iterable[PublicEvent | Mapping[str, Any]]) -> list[PublicEvent]:
        rows = [value if isinstance(value, PublicEvent) else PublicEvent.from_dict(value) for value in values]
        return sorted(rows, key=lambda row: (str(row.payload.get("available_at")), str(row.payload["event_id"])))

    def _available(self, available_at: Any, cut: Any) -> bool:
        if isinstance(available_at, (int, float)) and isinstance(cut, (int, float)):
            return float(available_at) <= float(cut)
        return str(available_at) <= str(cut)

    def _consume(
        self,
        payload: dict[str, Any],
        events: Sequence[PublicEvent],
        *,
        parent_hash: str | None,
        advance_to: Any,
    ) -> dict[str, Any]:
        options = payload["options"]
        history = payload["history_summary"]
        factors = payload["factor_observations"]
        exposure = payload["action_exposure"]
        consumed: list[str] = []
        warnings = list(payload.get("warnings", []))
        for event in events:
            row = event.payload
            consumed.append(event.digest)
            kind = row.get("event_type")
            concept = str(row.get("concept_id") or "")
            if kind == "PerformedTreatment" and options["actions"]:
                exposure[concept] = {
                    "active": True,
                    "level": _severity(row.get("value")),
                    "last_available_at": row.get("available_at"),
                    "source_event_digest": event.digest,
                }
                continue
            if kind != "ObservationAvailable" or row.get("rankable", True) is False:
                continue
            factor_id = self._concept_factor.get(concept)
            if factor_id is None:
                payload["unrecognized_observation_count"] += 1
                warnings.append(f"unmapped observation: {concept}")
                continue
            payload["recognized_observation_count"] += 1
            score = _severity(row.get("value"))
            old = history.get(concept)
            history[concept] = {
                "latest": score,
                "previous": old.get("latest") if old and options["history"] else None,
                "trend": score - old.get("latest", score) if old and options["history"] else 0.0,
                "count": (old.get("count", 0) + 1) if old and options["history"] else 1,
                "latest_available_at": row.get("available_at"),
            }
            source_id = str(row.get("provenance", {}).get("source_result_id") or event.digest)
            block = factors.setdefault(factor_id, {})
            observation = block.setdefault(concept, {"sources": {}, "latest": score})
            observation["sources"][source_id] = score
            observation["latest"] = score

        payload["available_cut"] = advance_to
        payload["lineage"] = {
            "parent_state_hash": parent_hash,
            "consumed_event_digests": sorted(consumed),
        }
        payload["factor_evidence_counts"] = {
            factor_id: len({
                source_id
                for row in observations.values()
                for source_id in row["sources"]
            })
            for factor_id, observations in sorted(factors.items())
        }
        payload["warnings"] = sorted(set(warnings))
        self._recompute_belief(payload)
        return payload

    def _recompute_belief(self, payload: dict[str, Any]) -> None:
        options = payload["options"]
        scores = {branch: 0.0 for branch in self._branches}
        factor_strengths: dict[str, float] = {}
        # Canonical iteration order is part of the recursive-state contract.
        # A JSON round-trip sorts object keys; recomputation must therefore not
        # depend on Python insertion history or floating-point summation order.
        for factor_id in sorted(payload["factor_observations"]):
            observations = payload["factor_observations"][factor_id]
            child_values: list[float] = []
            independent_source_ids: set[str] = set()
            for concept_id in sorted(observations):
                row = observations[concept_id]
                child_values.append(float(row["latest"]))
                independent_source_ids.update(str(value) for value in row["sources"])
            if not child_values:
                continue
            independent_sources = len(independent_source_ids)
            if options["factor_dependence"]:
                strength = sum(child_values) / len(child_values)
                strength *= min(1.5, math.sqrt(max(1, independent_sources)))
            else:
                strength = sum(child_values) * max(1, independent_sources)
            factor_strengths[factor_id] = strength
            for branch in sorted(self._factor_branches.get(factor_id, self._branches)):
                scores[branch] += strength
        if not factor_strengths:
            probabilities = {b: 0.8 / len(self._branches) for b in self._branches}
        else:
            values = {b: math.exp(min(20.0, scores[b])) for b in self._branches}
            total = sum(values.values()) or 1.0
            unknown_ratio = payload["unrecognized_observation_count"] / max(
                1, payload["recognized_observation_count"] + payload["unrecognized_observation_count"]
            )
            unknown = _clamp(0.05 + 0.65 * unknown_ratio, 0.05, 0.75)
            probabilities = {b: (1.0 - unknown) * values[b] / total for b in self._branches}
        unknown_ratio = payload["unrecognized_observation_count"] / max(
            1, payload["recognized_observation_count"] + payload["unrecognized_observation_count"]
        )
        unknown_mass = _clamp(0.2 if not factor_strengths else 0.05 + 0.65 * unknown_ratio, 0.05, 0.75)
        scale = (1.0 - unknown_mass) / max(1e-12, sum(probabilities.values()))
        probabilities = {b: p * scale for b, p in probabilities.items()}

        trends = [
            float(payload["history_summary"][key].get("trend", 0.0))
            for key in sorted(payload["history_summary"])
        ]
        latest = [
            float(payload["history_summary"][key].get("latest", 0.0))
            for key in sorted(payload["history_summary"])
        ]
        mean_trend = sum(trends) / len(trends) if trends else 0.0
        mean_latest = sum(latest) / len(latest) if latest else 0.0
        if not options["mode"]:
            modes = {"continuous_only": 1.0}
        elif mean_trend < -0.08:
            modes = {"recovering": 0.72, "strained": 0.18, "compensated": 0.10}
        elif mean_trend > 0.08 and mean_latest > 0.55:
            modes = {"decompensated": 0.68, "strained": 0.27, "compensated": 0.05}
        elif mean_latest > 0.62:
            modes = {"strained": 0.62, "decompensated": 0.28, "compensated": 0.10}
        else:
            modes = {"compensated": 0.72, "strained": 0.23, "recovering": 0.05}

        per_branch: dict[str, Any] = {}
        for branch in self._branches:
            coord_rows = self._charts.get(branch, [])
            coordinates: dict[str, float] = {}
            branch_strengths = [
                factor_strengths[f]
                for f in sorted(self._factor_branches)
                if branch in self._factor_branches[f] and f in factor_strengths
            ]
            load = _clamp(sum(branch_strengths) / max(1, len(branch_strengths)))
            for row in coord_rows:
                coord_id = row.get("id")
                if coord_id:
                    if "recovery" in coord_id:
                        coordinates[coord_id] = _clamp(-mean_trend, -1.0, 1.0)
                    elif "reserve" in coord_id or "stability" in coord_id:
                        coordinates[coord_id] = _clamp(1.0 - load)
                    else:
                        coordinates[coord_id] = load
            per_branch[branch] = {
                "posterior_mass": probabilities[branch],
                "local_coordinates": coordinates,
                "mode_posterior": copy.deepcopy(modes),
            }
        payload["branch_posterior"] = probabilities
        payload["unknown_mass"] = unknown_mass
        payload["mode_posterior"] = modes
        payload["per_branch"] = per_branch

    def _assert_state(self, state: SharedPatientState) -> None:
        if state.payload.get("model_digest") != self.model_digest:
            raise ValueError("state belongs to a different model version")

    def diagnose(self, state: SharedPatientState) -> dict[str, Any]:
        self._assert_state(state)
        wire = state.to_dict()
        abstain = "unknown_branch_mass_high" if wire["unknown_mass"] >= 0.5 else None
        ranked = sorted(wire["branch_posterior"].items(), key=lambda row: (-row[1], row[0]))
        return {
            "consumed_state_hash": state.state_hash,
            "branch_posterior": dict(ranked),
            "mode_posterior": wire["mode_posterior"],
            "unknown_mass": wire["unknown_mass"],
            "abstain_reason": abstain,
            "inference_kind": "model_assumed_belief_readout",
        }

    def _policy_id(self, policy: Mapping[str, Any] | str) -> str:
        if isinstance(policy, str):
            return policy
        return str(policy.get("policy_id") or policy.get("action_id") or "")

    def _transition(self, state: SharedPatientState, policy: Mapping[str, Any] | str, horizon: int | float) -> dict[str, Any]:
        wire = state.to_dict()
        policy_id = self._policy_id(policy)
        no_action = policy_id in {"", "NoNewAction", "A_NO_NEW_ACTION", "no_new_action"}
        action = self._actions.get(policy_id)
        unidentified = False
        if not no_action and action is None:
            return {
                "status": "UNIDENTIFIABLE",
                "abstain_reason": "unregistered_action_for_sealed_scope",
                "trajectory": [],
                "branch_outcomes": {},
            }
        if action:
            causal_text = str(action.get("causal_status", action.get("status", ""))).lower()
            unidentified = any(token in causal_text for token in ("unidentified", "not_identified", "uncalibrated"))
        steps = max(1, int(math.ceil(float(horizon))))
        branch_outcomes: dict[str, Any] = {}
        for branch, mass in wire["branch_posterior"].items():
            coords = wire["per_branch"].get(branch, {}).get("local_coordinates", {})
            load_values = [v for k, v in coords.items() if "reserve" not in k and "stability" not in k and "recovery" not in k]
            load = sum(load_values) / len(load_values) if load_values else 0.5
            mode = max(wire["mode_posterior"], key=wire["mode_posterior"].get)
            drift = {"compensated": -0.025, "strained": 0.025, "decompensated": 0.10, "recovering": -0.10, "continuous_only": 0.0}.get(mode, 0.0)
            if wire["options"].get("mode") is False:
                drift = 0.0
            # Preserve all performed exposures in history, but only a registered
            # action class may affect the sealed transition model.  A diagnostic
            # procedure or an unmapped raw action must not become generic support
            # merely because it appeared in the action ledger.
            residual_support = (
                sum(
                    float(row.get("level", 0.0))
                    for action_id, row in wire["action_exposure"].items()
                    if action_id in self._actions
                )
                if wire["options"].get("actions")
                else 0.0
            )
            drift -= min(0.08, residual_support * 0.03)
            effect = 0.0
            if action:
                eligible = action.get("eligible_effect_branches", [])
                if not eligible or branch in eligible:
                    direction = str(action.get("nominal_direction", action.get("effect", ""))).lower()
                    if any(token in direction for token in ("reduce", "suppress", "improve", "support", "stop")):
                        effect = -0.08
                    elif any(token in direction for token in ("increase", "start", "harm")):
                        effect = 0.06
            final_load = _clamp(load + steps * (drift + effect))
            branch_outcomes[branch] = {
                "posterior_mass": mass,
                "initial_load": load,
                "final_load": final_load,
                "direction": "improve" if final_load < load - 1e-9 else "worsen" if final_load > load + 1e-9 else "stable",
            }
        expected = sum(row["posterior_mass"] * row["final_load"] for row in branch_outcomes.values())
        trajectory = [
            {"step": step, "expected_burden": expected}
            for step in range(1, steps + 1)
        ]
        return {
            "status": "PARTIALLY_IDENTIFIED" if unidentified else "MODEL_ASSUMED",
            "abstain_reason": "causal_edge_unidentified" if unidentified else None,
            "trajectory": trajectory,
            "branch_outcomes": branch_outcomes,
            "expected_final_burden": expected,
        }

    def rollout(
        self,
        state: SharedPatientState,
        policy: Mapping[str, Any] | str,
        horizon: int | float,
    ) -> dict[str, Any]:
        self._assert_state(state)
        result = self._transition(state, policy, horizon)
        result.update(
            {
                "consumed_state_hash": state.state_hash,
                "policy_id": self._policy_id(policy),
                "inference_kind": "factual_no_new_action" if self._policy_id(policy) in {"", "NoNewAction", "A_NO_NEW_ACTION", "no_new_action"} else "model_assumed_counterfactual",
            }
        )
        return result

    def plan(
        self,
        state: SharedPatientState,
        policies: Iterable[Mapping[str, Any] | str],
        horizon: int | float,
    ) -> dict[str, Any]:
        self._assert_state(state)
        rows = [self.rollout(state, policy, horizon) for policy in policies]
        valid = [row for row in rows if row.get("expected_final_burden") is not None and row.get("status") != "UNIDENTIFIABLE"]
        selected = min(valid, key=lambda row: row["expected_final_burden"])["policy_id"] if valid else None
        return {
            "consumed_state_hash": state.state_hash,
            "selected_policy_id": selected,
            "abstain_reason": None if selected else "no_identifiable_registered_policy",
            "policy_rollouts": rows,
        }

    def branch_distance(
        self,
        branch_a: str,
        coords_a: Mapping[str, float],
        branch_b: str,
        coords_b: Mapping[str, float],
    ) -> float:
        if branch_a == branch_b:
            keys = set(coords_a) | set(coords_b)
            return math.sqrt(sum((float(coords_a.get(k, 0.0)) - float(coords_b.get(k, 0.0))) ** 2 for k in keys))
        graph: dict[str, dict[str, float]] = {}
        for child, parents in self._parents.items():
            for parent in parents:
                graph.setdefault(child, {})[parent] = 1.0
                graph.setdefault(parent, {})[child] = 1.0
        queue = [(0.0, branch_a)]
        distance = {branch_a: 0.0}
        while queue:
            cost, node = heapq.heappop(queue)
            if node == branch_b:
                return cost
            if cost != distance[node]:
                continue
            for neighbor, edge in graph.get(node, {}).items():
                candidate = cost + edge
                if candidate < distance.get(neighbor, math.inf):
                    distance[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))
        return math.inf

    def refine(self, refinement: Mapping[str, Any]) -> "FrameworkModel":
        patch = copy.deepcopy(dict(refinement))
        affected = set(patch.get("affected_parent_strata", []))
        if not affected:
            raise ValueError("refinement must name affected_parent_strata")
        spec = copy.deepcopy(self.spec)
        children = patch.get("child_strata", [])
        if "branch_graph" in spec:
            nodes = spec["branch_graph"].setdefault("nodes", [])
            for child in children:
                row = copy.deepcopy(dict(child))
                row.setdefault("branch_id", row.get("id"))
                row.setdefault("node_type", "candidate_process")
                row.setdefault("parents", list(affected))
                nodes.append(row)
        else:
            nodes = spec.setdefault("topology", {}).setdefault("nodes", [])
            edges = spec["topology"].setdefault("parent_edges", [])
            for child in children:
                child_id = child.get("id") or child.get("branch_id")
                nodes.append({"id": child_id, "kind": "candidate_branch"})
                for parent in affected:
                    edges.append({"parent": parent, "child": child_id})
        new_observation = patch.get("new_observation")
        if new_observation:
            graph = spec.setdefault("typed_factor_graph", {})
            node_key = "observed_nodes" if "observed_nodes" in graph else "observation_nodes"
            graph.setdefault(node_key, []).append(copy.deepcopy(new_observation))
        new_action = patch.get("new_action")
        if new_action:
            if "actions" in spec:
                spec["actions"].setdefault("catalog", []).append(copy.deepcopy(new_action))
            else:
                spec.setdefault("dynamics", {}).setdefault("action_catalog", []).append(copy.deepcopy(new_action))
        spec["refinement_lineage"] = {
            "parent_model_digest": self.model_digest,
            "affected_parent_strata": sorted(affected),
            "refinement_digest": _hash(patch),
            "kind": "post_seal_local_refinement",
        }
        return FrameworkModel.from_dict(spec)


def model_from_dict(spec: Mapping[str, Any]) -> FrameworkModel:
    return FrameworkModel.from_dict(spec)
