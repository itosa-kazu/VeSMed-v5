"""Schema constants, canonical wrappers, and fail-closed model validation.

The JSON Schema artifacts in ``schemas/`` are the interchange description.
This module enforces the semantic references and probability invariants needed
by the executable skeleton without adding a third-party dependency.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from .frozen_schema_validator import validate_frozen_architecture_schema


MODEL_SCHEMA_VERSION = "new-clinical-runtime.model.v2.0"
STATE_SCHEMA_VERSION = "ncf.shared_patient_state.v1"
EVENT_SCHEMA_VERSION = "new-clinical-runtime.event.v2.1"
RUNTIME_VERSION = "new-clinical-runtime/2.1"
ARCHITECTURE_VERSION = "NCF-ARCH-1.0.0"


def validate_migration_spec(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete migration interchange envelope fail-closed."""

    migration = copy.deepcopy(dict(value))
    allowed = {
        "migration_id",
        "from_model_digest",
        "to_model_digest",
        "process_map",
        "drop_processes",
        "coordinate_maps",
        "mode_maps",
        "stratum_maps",
        "history_stratum_maps",
        "factor_map",
        "action_map",
        "action_transports",
        "validated_posterior_transport",
        "merge_kernels",
        "refinement_lineage",
    }
    unknown = set(migration).difference(allowed)
    if unknown:
        raise ValueError(f"migration contains unknown fields: {sorted(unknown)}")
    for required in ("migration_id", "from_model_digest", "to_model_digest", "process_map"):
        if required not in migration:
            raise ValueError(f"migration missing required field: {required}")
    if not isinstance(migration["migration_id"], str) or not migration["migration_id"]:
        raise ValueError("migration_id must be a non-empty string")
    for key in ("from_model_digest", "to_model_digest"):
        raw = migration[key]
        if raw is not None and (
            not isinstance(raw, str)
            or len(raw) != 64
            or any(char not in "0123456789abcdef" for char in raw)
        ):
            raise ValueError(f"{key} must be a SHA-256 digest")
    mapping_fields = (
        "process_map",
        "coordinate_maps",
        "mode_maps",
        "stratum_maps",
        "history_stratum_maps",
        "factor_map",
        "action_map",
        "action_transports",
        "merge_kernels",
    )
    for key in mapping_fields:
        if key in migration and not isinstance(migration[key], Mapping):
            raise ValueError(f"{key} must be an object")
    if "drop_processes" in migration and not isinstance(migration["drop_processes"], list):
        raise ValueError("drop_processes must be an array")
    if "refinement_lineage" in migration and not isinstance(
        migration["refinement_lineage"], Mapping
    ):
        raise ValueError("refinement_lineage must be an object")
    transport = migration.get("validated_posterior_transport")
    if transport is not None:
        if not isinstance(transport, Mapping):
            raise ValueError("validated_posterior_transport must be an object")
        required_transport = {
            "source_state_hash",
            "from_factor_graph_digest",
            "to_factor_graph_digest",
            "validation_artifact_digest",
        }
        if set(transport) != required_transport:
            raise ValueError(
                "validated_posterior_transport must contain exactly its four bound digests"
            )
        for key in required_transport:
            raw = transport[key]
            if not isinstance(raw, str) or len(raw) != 64 or any(
                char not in "0123456789abcdef" for char in raw
            ):
                raise ValueError(f"validated_posterior_transport.{key} must be SHA-256")
    return migration


def _jcs_number(value: float) -> str:
    """ECMAScript-compatible shortest formatting for finite IEEE-754 values."""

    if not math.isfinite(value):
        raise ValueError("RFC8785-JCS forbids NaN and Infinity")
    if value == 0.0:
        return "0"
    raw = repr(float(value)).lower()
    sign = ""
    if raw.startswith("-"):
        sign, raw = "-", raw[1:]
    if "e" in raw:
        mantissa, exp_text = raw.split("e", 1)
        exponent = int(exp_text)
        digits = mantissa.replace(".", "").lstrip("0") or "0"
    else:
        if "." in raw:
            integer, fraction = raw.split(".", 1)
            digits = (integer + fraction).lstrip("0") or "0"
            exponent = len(integer.lstrip("0")) - 1 if integer.lstrip("0") else -len(fraction) + len(fraction.lstrip("0")) - 1
        else:
            digits = raw.lstrip("0") or "0"
            exponent = len(raw) - 1
    digits = digits.rstrip("0") or "0"
    absolute = abs(value)
    if 1e-6 <= absolute < 1e21:
        decimal_position = exponent + 1
        if decimal_position <= 0:
            body = "0." + "0" * (-decimal_position) + digits
        elif decimal_position >= len(digits):
            body = digits + "0" * (decimal_position - len(digits))
        else:
            body = digits[:decimal_position] + "." + digits[decimal_position:]
        return sign + body
    mantissa = digits[0] + (("." + digits[1:]) if len(digits) > 1 else "")
    exponent_text = f"+{exponent}" if exponent >= 0 else str(exponent)
    return sign + mantissa + "e" + exponent_text


def _jcs_encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _jcs_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_jcs_encode(item) for item in value) + "]"
    if isinstance(value, Mapping):
        keys = sorted(value, key=lambda key: str(key).encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(
            _jcs_encode(str(key)) + ":" + _jcs_encode(value[key]) for key in keys
        ) + "}"
    raise TypeError(f"value is not JSON serializable: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """RFC8785-JCS canonical bytes used by the architecture wire contract."""

    return _jcs_encode(value).encode("utf-8")


def digest(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class PublicEvent:
    """Canonical public event; availability is separate from occurrence time."""

    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicEvent":
        row = copy.deepcopy(dict(value))
        row.setdefault("schema_version", EVENT_SCHEMA_VERSION)
        required = {
            "event_id",
            "event_type",
            "occurred_time",
            "recorded_at",
            "available_at",
            "provenance",
        }
        missing = required.difference(row)
        if missing:
            raise ValueError(f"event missing fields: {sorted(missing)}")
        if row["schema_version"] != EVENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported event schema: {row['schema_version']}")
        if not isinstance(row["event_id"], str) or not row["event_id"]:
            raise ValueError("event_id must be a non-empty string")
        allowed_event_types = {
            "ObservationAvailable",
            "ActionStarted",
            "ActionContinued",
            "ActionDoseChanged",
            "ActionHeld",
            "ActionStopped",
            "ActionCompleted",
            "PlannedAction",
            "PlannedTreatment",
            "RecordOnly",
        }
        if row["event_type"] not in allowed_event_types:
            raise ValueError(f"unsupported event_type: {row['event_type']}")
        occurred = row["occurred_time"]
        if not isinstance(occurred, Mapping) or not {"lower", "upper"}.issubset(occurred):
            raise ValueError("event occurred_time requires explicit lower/upper bounds")
        lower = float(occurred["lower"])
        upper = float(occurred["upper"])
        recorded = float(row["recorded_at"])
        available = float(row["available_at"])
        if not all(math.isfinite(value) for value in (lower, upper, recorded, available)):
            raise ValueError("event temporal fields must be finite")
        if lower > upper or upper > recorded or recorded > available:
            raise ValueError("event time order must satisfy occurred lower <= upper <= recorded <= available")
        provenance = row["provenance"]
        if (
            not isinstance(provenance, Mapping)
            or not isinstance(provenance.get("source_result_id"), str)
            or not provenance.get("source_result_id")
        ):
            raise ValueError("event provenance requires source_result_id")
        if row["event_type"] == "ObservationAvailable":
            if not row.get("concept_id"):
                raise ValueError("observation event needs concept_id")
            if "value" not in row:
                raise ValueError("observation event needs value")
            if "sample_time" not in row or "result_at" not in row:
                raise ValueError("observation event needs sample_time and result_at")
            sample = row["sample_time"]
            if not isinstance(sample, Mapping) or not {"lower", "upper"}.issubset(sample):
                raise ValueError("observation sample_time requires explicit lower/upper bounds")
            sample_lower = float(sample["lower"])
            sample_upper = float(sample["upper"])
            result_at = float(row["result_at"])
            if not all(math.isfinite(value) for value in (sample_lower, sample_upper, result_at)):
                raise ValueError("observation temporal fields must be finite")
            if sample_lower > sample_upper or sample_upper > result_at or result_at > recorded:
                raise ValueError("observation time order must satisfy sample lower <= upper <= result <= recorded")
            reliability = row.get("reliability", 1.0)
            if isinstance(reliability, bool):
                raise ValueError("observation reliability must be a finite probability")
            try:
                reliability_value = float(reliability)
            except (TypeError, ValueError) as exc:
                raise ValueError("observation reliability must be a finite probability") from exc
            if not math.isfinite(reliability_value) or not 0.0 <= reliability_value <= 1.0:
                raise ValueError("observation reliability must be in [0,1]")
            row["reliability"] = reliability_value
            if "rankable" in row and not isinstance(row["rankable"], bool):
                raise ValueError("observation rankable must be boolean")
            disposition = row.get("mapper_disposition_reason")
            allowed_dispositions = {
                "LOW_RELIABILITY",
                "INVALID_METHOD",
                "SUPPORT_MASKED",
                "UNKNOWN_CONDITION",
            }
            if disposition is not None and disposition not in allowed_dispositions:
                raise ValueError(
                    "unsupported mapper_disposition_reason; expected one of "
                    f"{sorted(allowed_dispositions)}"
                )
            condition = row.get("measurement_condition")
            if condition is not None:
                if not isinstance(condition, Mapping):
                    raise ValueError("measurement_condition must be an object")
                masking = condition.get("support_masking", 0.0)
                if isinstance(masking, bool):
                    raise ValueError("measurement_condition.support_masking must be a finite probability")
                try:
                    masking_value = float(masking)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "measurement_condition.support_masking must be a finite probability"
                    ) from exc
                if not math.isfinite(masking_value) or not 0.0 <= masking_value <= 1.0:
                    raise ValueError("measurement_condition.support_masking must be in [0,1]")
                exposure_ids = condition.get("active_support_exposure_ids", [])
                if (
                    not isinstance(exposure_ids, list)
                    or any(not isinstance(item, str) or not item for item in exposure_ids)
                    or len(exposure_ids) != len(set(exposure_ids))
                ):
                    raise ValueError(
                        "measurement_condition.active_support_exposure_ids must be unique non-empty ids"
                    )
        if row["event_type"] in {
            "ActionStarted", "ActionContinued", "ActionDoseChanged", "ActionHeld",
            "ActionStopped", "ActionCompleted"
        }:
            if (
                not isinstance(row.get("action_id"), str)
                or not row.get("action_id")
                or not isinstance(row.get("exposure_id"), str)
                or not row.get("exposure_id")
            ):
                raise ValueError("performed action event needs action_id and exposure_id")
        if "dose" in row:
            if isinstance(row["dose"], bool):
                raise ValueError("action dose must be a finite non-negative number")
            try:
                dose = float(row["dose"])
            except (TypeError, ValueError) as exc:
                raise ValueError("action dose must be a finite non-negative number") from exc
            if not math.isfinite(dose) or dose < 0.0:
                raise ValueError("action dose must be a finite non-negative number")
            row["dose"] = dose
        if row["event_type"] == "ActionDoseChanged" and "dose" not in row:
            raise ValueError("ActionDoseChanged requires an explicit dose")
        if "dose_unit" in row and row["dose_unit"] is not None and (
            not isinstance(row["dose_unit"], str) or not row["dose_unit"]
        ):
            raise ValueError("action dose_unit must be a non-empty string or null")
        if row["event_type"] in {"PlannedAction", "PlannedTreatment"} and (
            not isinstance(row.get("action_id"), str) or not row.get("action_id")
        ):
            raise ValueError("planned action event needs action_id")
        return cls(row)

    @property
    def event_id(self) -> str:
        return str(self.payload["event_id"])

    @property
    def event_digest(self) -> str:
        return digest(self.payload)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.payload)


@dataclass(frozen=True)
class SharedPatientState:
    """Canonical SharedPatientStateV1 wire plus optional private runtime cache."""

    payload: dict[str, Any]
    _internal_payload: dict[str, Any] | None = None
    # Deliberately not part of SharedPatientStateV1 canonical bytes.  The
    # frozen architecture schema exposes only an aggregate ledger digest, so
    # a content-addressed proof is the explicit sidecar needed to validate a
    # duplicate event after a cold restore.
    _event_ledger_proof: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SharedPatientState":
        row = copy.deepcopy(dict(value))
        validate_architecture_state_payload(row)
        return cls(row)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "SharedPatientState":
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("state bytes must decode to an object")
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.payload)

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload)

    @property
    def state_hash(self) -> str:
        return str(self.payload["integrity"]["state_hash"])


def architecture_state_hash(value: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(value))
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("architecture wire lacks integrity object")
    integrity.pop("state_hash", None)
    return digest(payload)


def validate_architecture_state_payload(payload: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "architecture_version", "state_id", "as_of", "scope",
        "model_lineage", "event_lineage", "active_process_posterior", "local_states",
        "cross_couplings", "action_memory", "factor_graph_state", "geometry_state",
        "history_summary", "epistemic_residual", "identifiability_claims", "integrity",
    }
    if set(payload) != required:
        raise ValueError(
            f"architecture wire top-level mismatch; missing={sorted(required.difference(payload))}, "
            f"extra={sorted(set(payload).difference(required))}"
        )
    if payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported state schema: {payload.get('schema_version')}")
    if payload.get("architecture_version") != ARCHITECTURE_VERSION:
        raise ValueError(f"unsupported architecture: {payload.get('architecture_version')}")
    # The canonical deserialization boundary must enforce the complete frozen
    # nested schema.  An external Test-Json invocation is evidence, not a
    # runtime guard; malformed nested state must never survive from_dict().
    validate_frozen_architecture_schema(payload)
    integrity = payload.get("integrity", {})
    if integrity.get("canonicalization") != "RFC8785-JCS" or integrity.get("hash_algorithm") != "SHA-256":
        raise ValueError("invalid architecture integrity declaration")
    expected = architecture_state_hash(payload)
    if integrity.get("state_hash") != expected:
        raise ValueError("architecture state hash mismatch")


def _unique(rows: list[dict[str, Any]], key: str, label: str) -> set[str]:
    ids = [str(row.get(key) or "") for row in rows]
    if any(not value for value in ids):
        raise ValueError(f"{label} contains blank {key}")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} contains duplicate {key}")
    return set(ids)


def _finite_number(value: Any, where: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{where} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{where} must be a finite number")
    return number


def _validate_distribution(spec: Mapping[str, Any], where: str) -> None:
    family = spec.get("family")
    if family == "bernoulli":
        p = _finite_number(spec.get("p_true", -1.0), f"{where}.p_true")
        if not 0.0 < p < 1.0:
            raise ValueError(f"{where}: bernoulli p_true must be in (0,1)")
    elif family == "categorical":
        probabilities = spec.get("probabilities")
        if not isinstance(probabilities, Mapping) or not probabilities:
            raise ValueError(f"{where}: categorical probabilities required")
        values = [_finite_number(v, f"{where}.probabilities") for v in probabilities.values()]
        if any(v <= 0.0 for v in values):
            raise ValueError(f"{where}: categorical probabilities must be positive")
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError(f"{where}: categorical probabilities must sum to one")
    elif family == "gaussian":
        _finite_number(spec.get("mean", math.nan), f"{where}.mean")
        sd = _finite_number(spec.get("sd", 0.0), f"{where}.sd")
        if not sd > 0.0:
            raise ValueError(f"{where}: gaussian sd must be positive")
    else:
        raise ValueError(f"{where}: unsupported likelihood family {family!r}")


def validate_model_spec(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate references and the finite exact-runtime boundary."""

    spec = copy.deepcopy(dict(value))
    if spec.get("schema_version") != MODEL_SCHEMA_VERSION:
        raise ValueError(f"unsupported model schema: {spec.get('schema_version')}")
    if not spec.get("model_id"):
        raise ValueError("model_id is required")
    scope = spec.get("scope")
    required_scope = {
        "scope_id", "scope_version", "population_id", "horizon", "outcome_ids",
        "distance_metric_id", "tolerance",
    }
    if not isinstance(scope, Mapping) or not required_scope.issubset(scope):
        raise ValueError(f"scope must declare {sorted(required_scope)}")
    if not isinstance(scope["horizon"], Mapping) or not scope["horizon"].get("unit"):
        raise ValueError("scope.horizon needs positive value and unit")
    horizon_value = _finite_number(scope["horizon"].get("value"), "scope.horizon.value")
    if horizon_value <= 0.0:
        raise ValueError("scope.horizon needs positive value and unit")
    tolerance = _finite_number(scope.get("tolerance"), "scope.tolerance")
    if tolerance < 0.0:
        raise ValueError("scope.tolerance must be non-negative")
    if (
        not isinstance(scope["outcome_ids"], list)
        or not scope["outcome_ids"]
        or any(not isinstance(value, str) or not value for value in scope["outcome_ids"])
        or len(set(scope["outcome_ids"])) != len(scope["outcome_ids"])
    ):
        raise ValueError("scope.outcome_ids must be non-empty")

    # The wire carries one local coordinate/mode state per process, not a
    # dormant-state distribution nor the full joint distribution between
    # activation and every local variable.  Make that approximation an
    # explicit, digest-bound model contract instead of an implementation
    # detail that callers could mistake for exact full-X inference.
    posterior_factorization = spec.get("posterior_factorization")
    if not isinstance(posterior_factorization, Mapping):
        raise ValueError("posterior_factorization must be declared")
    required_factorization_keys = {
        "representation",
        "local_state_semantics",
        "assumption_ids",
        "error_tolerance",
        "unsupported_correlations_policy",
    }
    if set(posterior_factorization) != required_factorization_keys:
        raise ValueError(
            "posterior_factorization must contain exactly "
            f"{sorted(required_factorization_keys)}"
        )
    if (
        posterior_factorization.get("representation")
        != "conditional_active_mean_field_over_process_local_state"
    ):
        raise ValueError(
            "posterior_factorization.representation must be "
            "conditional_active_mean_field_over_process_local_state"
        )
    if posterior_factorization.get("local_state_semantics") != "q(x,m|process_active)":
        raise ValueError(
            "posterior_factorization.local_state_semantics must be "
            "q(x,m|process_active)"
        )
    assumption_ids = posterior_factorization.get("assumption_ids")
    if (
        not isinstance(assumption_ids, list)
        or not assumption_ids
        or any(not isinstance(item, str) or not item for item in assumption_ids)
        or len(set(assumption_ids)) != len(assumption_ids)
    ):
        raise ValueError(
            "posterior_factorization.assumption_ids must be non-empty unique strings"
        )
    error_tolerance = posterior_factorization.get("error_tolerance")
    if not isinstance(error_tolerance, Mapping) or set(error_tolerance) != {
        "reference",
        "epsilon",
    }:
        raise ValueError(
            "posterior_factorization.error_tolerance must contain exactly "
            "reference and epsilon"
        )
    if error_tolerance.get("reference") != "scope.tolerance":
        raise ValueError(
            "posterior_factorization.error_tolerance.reference must be scope.tolerance"
        )
    factorization_epsilon = _finite_number(
        error_tolerance.get("epsilon"),
        "posterior_factorization.error_tolerance.epsilon",
    )
    if factorization_epsilon < 0.0:
        raise ValueError(
            "posterior_factorization.error_tolerance.epsilon must be non-negative"
        )
    if factorization_epsilon != tolerance:
        raise ValueError(
            "posterior_factorization.error_tolerance.epsilon must equal scope.tolerance"
        )
    if (
        posterior_factorization.get("unsupported_correlations_policy")
        != "OUT_OF_SCOPE"
    ):
        raise ValueError(
            "posterior_factorization.unsupported_correlations_policy must be OUT_OF_SCOPE"
        )

    processes = spec.get("processes")
    if not isinstance(processes, list) or not processes:
        raise ValueError("processes must be a non-empty list")
    process_ids = _unique(processes, "process_id", "processes")
    max_exact = int(spec.get("inference", {}).get("max_exact_processes", 12))
    if len(processes) > max_exact:
        raise ValueError(
            f"exact factorial runtime limited to {max_exact} processes; got {len(processes)}"
        )

    coordinate_ids: dict[str, set[str]] = {}
    mode_ids: dict[str, set[str]] = {}
    stratum_ids: dict[str, set[str]] = {}
    for process in processes:
        pid = process["process_id"]
        prior = _finite_number(process.get("activation_prior", -1.0), f"{pid}.activation_prior")
        if not 0.0 < prior < 1.0:
            raise ValueError(f"{pid}: activation_prior must be in (0,1)")
        coords = process.get("coordinates", [])
        coordinate_ids[pid] = _unique(coords, "coordinate_id", f"{pid}.coordinates")
        for coord in coords:
            bounds = coord.get("bounds", [])
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError(f"{pid}.{coord['coordinate_id']}: invalid bounds/prior")
            low = _finite_number(bounds[0], f"{pid}.{coord['coordinate_id']}.bounds[0]")
            high = _finite_number(bounds[1], f"{pid}.{coord['coordinate_id']}.bounds[1]")
            mean = _finite_number(
                coord.get("prior_mean", math.nan), f"{pid}.{coord['coordinate_id']}.prior_mean"
            )
            if not low < high or not low <= mean <= high:
                raise ValueError(f"{pid}.{coord['coordinate_id']}: invalid bounds/prior")
            uncertainty = _finite_number(
                coord.get("prior_uncertainty", 0.0),
                f"{pid}.{coord['coordinate_id']}.prior_uncertainty",
            )
            if uncertainty < 0.0:
                raise ValueError(f"{pid}.{coord['coordinate_id']}: prior_uncertainty must be non-negative")
            objective_weight = _finite_number(
                coord.get("objective_weight", 0.0),
                f"{pid}.{coord['coordinate_id']}.objective_weight",
            )
            if objective_weight < 0.0:
                raise ValueError(f"{pid}.{coord['coordinate_id']}: objective_weight must be non-negative")
        modes = process.get("modes", [])
        if not modes:
            raise ValueError(f"{pid}: at least one local mode is required")
        mode_ids[pid] = _unique(modes, "mode_id", f"{pid}.modes")
        activation_transition = process.get("activation_transition", {})
        if not isinstance(activation_transition, Mapping):
            raise ValueError(f"{pid}.activation_transition must be a mapping")
        unknown_transition_keys = set(activation_transition).difference(
            {
                "enter_hazard_per_step",
                "withdraw_hazard_per_step",
                "enter_log_hazard_shift_by_mode",
                "withdraw_log_hazard_shift_by_mode",
                "enter_log_hazard_shift_by_coordinate",
                "withdraw_log_hazard_shift_by_coordinate",
                "entry_initialization",
                "exit_policy",
                "parameter_status",
                "source_id",
                "version",
            }
        )
        if unknown_transition_keys:
            raise ValueError(
                f"{pid}.activation_transition has unknown keys {sorted(unknown_transition_keys)}"
            )
        for key in ("enter_hazard_per_step", "withdraw_hazard_per_step"):
            hazard = _finite_number(
                activation_transition.get(key, 0.0), f"{pid}.activation_transition.{key}"
            )
            if hazard < 0.0:
                raise ValueError(f"{pid}.activation_transition.{key} must be non-negative")
        if activation_transition:
            if activation_transition.get("parameter_status") not in {
                "STRUCTURAL_TOY_NONCALIBRATED",
                "MECHANISM_CONSTRAINED",
                "EMPIRICALLY_ESTIMATED",
            }:
                raise ValueError(f"{pid}.activation_transition requires valid parameter_status")
            if not activation_transition.get("source_id") or not activation_transition.get("version"):
                raise ValueError(f"{pid}.activation_transition requires source_id and version")
        entry_initialization = activation_transition.get("entry_initialization")
        exit_policy = activation_transition.get("exit_policy")
        has_activation_hazard = any(
            float(activation_transition.get(key, 0.0)) > 0.0
            for key in ("enter_hazard_per_step", "withdraw_hazard_per_step")
        )
        if has_activation_hazard and (
            not isinstance(entry_initialization, Mapping)
            or not isinstance(exit_policy, Mapping)
        ):
            raise ValueError(
                f"{pid}.activation_transition with a nonzero hazard requires "
                "entry_initialization and exit_policy"
            )
        if entry_initialization is not None:
            if not isinstance(entry_initialization, Mapping):
                raise ValueError(
                    f"{pid}.activation_transition.entry_initialization must be a mapping"
                )
            if set(entry_initialization) != {"policy"}:
                raise ValueError(
                    f"{pid}.activation_transition.entry_initialization requires only policy"
                )
            if entry_initialization.get("policy") not in {"CARRY", "RESET_TO_PRIOR"}:
                raise ValueError(
                    f"{pid}.activation_transition.entry_initialization.policy is invalid"
                )
        if exit_policy is not None:
            if not isinstance(exit_policy, Mapping):
                raise ValueError(
                    f"{pid}.activation_transition.exit_policy must be a mapping"
                )
            policy = exit_policy.get("policy")
            allowed_exit_keys = (
                {"policy", "decay_rate_per_step"}
                if policy == "DECAY_TO_PRIOR"
                else {"policy"}
            )
            if set(exit_policy) != allowed_exit_keys:
                raise ValueError(
                    f"{pid}.activation_transition.exit_policy has invalid fields for {policy}"
                )
            if policy not in {
                "CARRY",
                "RESET_TO_PRIOR",
                "DECAY_TO_PRIOR",
                "SURVIVOR_CARRY_REENTRY_RESET",
            }:
                raise ValueError(
                    f"{pid}.activation_transition.exit_policy.policy is invalid"
                )
            if policy == "DECAY_TO_PRIOR":
                decay_rate = _finite_number(
                    exit_policy.get("decay_rate_per_step"),
                    f"{pid}.activation_transition.exit_policy.decay_rate_per_step",
                )
                if decay_rate <= 0.0:
                    raise ValueError(
                        f"{pid}.activation_transition.exit_policy.decay_rate_per_step "
                        "must be positive"
                    )
        for key in (
            "enter_log_hazard_shift_by_mode",
            "withdraw_log_hazard_shift_by_mode",
        ):
            shifts = activation_transition.get(key, {})
            if not isinstance(shifts, Mapping) or not set(shifts).issubset(mode_ids[pid]):
                raise ValueError(f"{pid}.activation_transition.{key} has unknown mode")
            for mode_id, shift in shifts.items():
                _finite_number(shift, f"{pid}.activation_transition.{key}.{mode_id}")
        for key in (
            "enter_log_hazard_shift_by_coordinate",
            "withdraw_log_hazard_shift_by_coordinate",
        ):
            shifts = activation_transition.get(key, {})
            if not isinstance(shifts, Mapping) or not set(shifts).issubset(coordinate_ids[pid]):
                raise ValueError(f"{pid}.activation_transition.{key} has unknown coordinate")
            for coordinate_id, shift in shifts.items():
                _finite_number(shift, f"{pid}.activation_transition.{key}.{coordinate_id}")
        if has_activation_hazard:
            if entry_initialization.get("policy") != "RESET_TO_PRIOR":
                raise ValueError(
                    f"{pid}.activation_transition dynamic entry_initialization.policy "
                    "must be RESET_TO_PRIOR"
                )
            if exit_policy.get("policy") != "SURVIVOR_CARRY_REENTRY_RESET":
                raise ValueError(
                    f"{pid}.activation_transition dynamic exit_policy.policy must be "
                    "SURVIVOR_CARRY_REENTRY_RESET"
                )
            for key in (
                "enter_log_hazard_shift_by_mode",
                "withdraw_log_hazard_shift_by_mode",
                "enter_log_hazard_shift_by_coordinate",
                "withdraw_log_hazard_shift_by_coordinate",
            ):
                if activation_transition.get(key, {}):
                    raise ValueError(
                        f"{pid}.activation_transition.{key} must be empty: "
                        "local-state-dependent dynamic activation hazards are unsupported "
                        "by conditional-active mean-field factorization"
                    )
        strata = process.get("strata") or [
            {"stratum_id": f"stratum:{pid}", "prior": 1.0}
        ]
        stratum_ids[pid] = _unique(strata, "stratum_id", f"{pid}.strata")
        stratum_priors = [
            _finite_number(row.get("prior", 0.0), f"{pid}.strata.prior") for row in strata
        ]
        stratum_total = sum(stratum_priors)
        if any(value < 0.0 for value in stratum_priors):
            raise ValueError(f"{pid}: stratum priors cannot be negative")
        if abs(stratum_total - 1.0) > 1e-9:
            raise ValueError(f"{pid}: stratum priors must sum to one")
        mode_priors = [
            _finite_number(row.get("prior", 0.0), f"{pid}.modes.prior") for row in modes
        ]
        if any(value < 0.0 for value in mode_priors):
            raise ValueError(f"{pid}: mode priors cannot be negative")
        if abs(sum(mode_priors) - 1.0) > 1e-9:
            raise ValueError(f"{pid}: mode priors must sum to one")
        for mode in modes:
            unknown_coords = set(mode.get("coordinate_drift", {})).difference(coordinate_ids[pid])
            if unknown_coords:
                raise ValueError(f"{pid}.{mode['mode_id']}: drift references {sorted(unknown_coords)}")
            for coordinate_id, drift in mode.get("coordinate_drift", {}).items():
                _finite_number(drift, f"{pid}.{mode['mode_id']}.coordinate_drift.{coordinate_id}")
        for guard in process.get("mode_guards", []):
            if guard.get("coordinate_id") not in coordinate_ids[pid]:
                raise ValueError(f"{pid}: mode guard references unknown coordinate")
            if guard.get("source_mode_id") not in mode_ids[pid] or guard.get("target_mode_id") not in mode_ids[pid]:
                raise ValueError(f"{pid}: mode guard references unknown mode")
            direction = guard.get("direction")
            enter = _finite_number(guard.get("enter_threshold", math.nan), f"{pid}.guard.enter_threshold")
            exit_value = _finite_number(guard.get("exit_threshold", math.nan), f"{pid}.guard.exit_threshold")
            if direction == "above" and not exit_value < enter:
                raise ValueError(f"{pid}: above guard requires exit_threshold < enter_threshold")
            if direction == "below" and not exit_value > enter:
                raise ValueError(f"{pid}: below guard requires exit_threshold > enter_threshold")
            if direction not in {"above", "below"}:
                raise ValueError(f"{pid}: invalid mode guard direction")
            probability = _finite_number(
                guard.get("transition_probability", -1.0),
                f"{pid}.guard.transition_probability",
            )
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"{pid}: invalid mode guard transition probability")

    all_strata = [sid for values in stratum_ids.values() for sid in values]
    if len(all_strata) != len(set(all_strata)):
        raise ValueError(
            "stratum_id values must be globally unique because history transitions are stratum-addressed"
        )

    observations = spec.get("observations", [])
    observation_ids = _unique(observations, "concept_id", "observations")
    factor_ids: set[str] = set()
    for obs in observations:
        if not obs.get("factor_id"):
            raise ValueError(f"{obs['concept_id']}: factor_id is required")
        reliability = obs.get("reliability", 1.0)
        if isinstance(reliability, bool):
            raise ValueError(f"{obs['concept_id']}: reliability must be a finite probability")
        try:
            reliability_value = float(reliability)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{obs['concept_id']}: reliability must be a finite probability"
            ) from exc
        if not math.isfinite(reliability_value) or not 0.0 <= reliability_value <= 1.0:
            raise ValueError(f"{obs['concept_id']}: reliability must be in [0,1]")
        obs["reliability"] = reliability_value
        factor_ids.add(str(obs["factor_id"]))
        emissions = obs.get("emissions", [])
        if not emissions:
            raise ValueError(f"{obs['concept_id']}: at least one emission is required")
        seen_targets: set[str] = set()
        for index, emission in enumerate(emissions):
            pid = emission.get("process_id")
            if pid not in process_ids:
                raise ValueError(f"{obs['concept_id']}: unknown emission process {pid}")
            if pid in seen_targets:
                raise ValueError(f"{obs['concept_id']}: duplicate emission target {pid}")
            seen_targets.add(pid)
            _validate_distribution(emission.get("active_likelihood", {}), f"{obs['concept_id']}.emissions[{index}].active")
            _validate_distribution(emission.get("inactive_likelihood", {}), f"{obs['concept_id']}.emissions[{index}].inactive")
            update = emission.get("coordinate_update")
            if update and update.get("coordinate_id") not in coordinate_ids[pid]:
                raise ValueError(f"{obs['concept_id']}: unknown coordinate update target")
            if update:
                gain = _finite_number(
                    update.get("gain", 1.0),
                    f"{obs['concept_id']}.emissions[{index}].coordinate_update.gain",
                )
                if not 0.0 <= gain <= 1.0:
                    raise ValueError(f"{obs['concept_id']}: coordinate update gain must be in [0,1]")
            for mid, distribution in emission.get("mode_likelihoods", {}).items():
                if mid not in mode_ids[pid]:
                    raise ValueError(f"{obs['concept_id']}: unknown mode {pid}.{mid}")
                _validate_distribution(distribution, f"{obs['concept_id']}.{pid}.{mid}")
            stratum_likelihoods = emission.get("stratum_likelihoods", {})
            if stratum_likelihoods:
                if set(stratum_likelihoods) != stratum_ids[pid]:
                    raise ValueError(
                        f"{obs['concept_id']}: stratum likelihoods must cover exactly {sorted(stratum_ids[pid])}"
                    )
                for sid, distribution in stratum_likelihoods.items():
                    _validate_distribution(distribution, f"{obs['concept_id']}.{pid}.{sid}")
        joint_likelihoods = obs.get("joint_likelihoods")
        if len(seen_targets) > 1 and not isinstance(joint_likelihoods, Mapping):
            raise ValueError(
                f"{obs['concept_id']}: multi-process observation requires typed joint_likelihoods"
            )
        if joint_likelihoods is not None:
            if not isinstance(joint_likelihoods, Mapping):
                raise ValueError(f"{obs['concept_id']}: joint_likelihoods must be an object")
            expected_keys = {
                ",".join(sorted(pid for pid, enabled in zip(sorted(seen_targets), bits) if enabled))
                or "-"
                for bits in itertools.product((False, True), repeat=len(seen_targets))
            }
            if set(joint_likelihoods) != expected_keys:
                raise ValueError(
                    f"{obs['concept_id']}: joint_likelihoods must cover exactly {sorted(expected_keys)}"
                )
            for active_set, distribution in joint_likelihoods.items():
                _validate_distribution(
                    distribution,
                    f"{obs['concept_id']}.joint_likelihoods[{active_set}]",
                )
        if (obs.get("unknown_likelihood") is None) != (obs.get("reference_likelihood") is None):
            raise ValueError(f"{obs['concept_id']}: unknown/reference likelihood must be paired")
        if obs.get("unknown_likelihood") is not None:
            _validate_distribution(obs["unknown_likelihood"], f"{obs['concept_id']}.unknown")
            _validate_distribution(obs["reference_likelihood"], f"{obs['concept_id']}.reference")

    # Distinct observation events may be projections of one shared upstream
    # measurement/latent cause.  Such members are forbidden from entering the
    # factorial posterior independently: a declared complete factor supplies
    # one joint likelihood over their canonical member-value object.
    common_cause_factors = spec.get("common_cause_factors", [])
    if not isinstance(common_cause_factors, list):
        raise ValueError("common_cause_factors must be an array")
    _unique(common_cause_factors, "factor_id", "common_cause_factors") \
        if common_cause_factors else set()
    common_member_owner: dict[str, str] = {}
    observations_by_id = {str(row["concept_id"]): row for row in observations}
    for factor in common_cause_factors:
        factor_id = str(factor["factor_id"])
        members = factor.get("member_concept_ids")
        if (
            not isinstance(members, list)
            or len(members) < 2
            or any(not isinstance(value, str) or not value for value in members)
            or len(set(members)) != len(members)
        ):
            raise ValueError(
                f"{factor_id}: common-cause member_concept_ids must contain at least two unique ids"
            )
        if not set(members).issubset(observation_ids):
            raise ValueError(f"{factor_id}: common-cause factor references unknown member concept")
        for concept_id in members:
            if concept_id in common_member_owner:
                raise ValueError(
                    f"{concept_id}: observation cannot belong to multiple common-cause factors"
                )
            common_member_owner[concept_id] = factor_id
            member_observation = observations_by_id[concept_id]
            if len(member_observation.get("emissions", [])) != 1:
                raise ValueError(
                    f"{factor_id}: each common-cause member must have exactly one local emission"
                )
            if member_observation.get("joint_likelihoods") is not None:
                raise ValueError(
                    f"{factor_id}: member-level joint_likelihoods would double-count the common cause"
                )
        binding_mode = factor.get("binding_mode")
        if binding_mode not in {"SAME_SOURCE_RESULT", "SHARED_LATENT_INSTANCE"}:
            raise ValueError(
                f"{factor_id}: binding_mode must be SAME_SOURCE_RESULT or SHARED_LATENT_INSTANCE"
            )
        if factor.get("value_encoding") != "CANONICAL_MEMBER_OBJECT":
            raise ValueError(
                f"{factor_id}: value_encoding must be CANONICAL_MEMBER_OBJECT"
            )
        if factor.get("reliability_aggregation") != "MINIMUM":
            raise ValueError(f"{factor_id}: reliability_aggregation must be MINIMUM")
        target_processes = {
            str(emission["process_id"])
            for concept_id in members
            for emission in observations_by_id[concept_id]["emissions"]
        }
        expected_keys = {
            ",".join(
                sorted(pid for pid, enabled in zip(sorted(target_processes), bits) if enabled)
            )
            or "-"
            for bits in itertools.product((False, True), repeat=len(target_processes))
        }
        joint = factor.get("joint_value_likelihoods")
        if not isinstance(joint, Mapping) or set(joint) != expected_keys:
            raise ValueError(
                f"{factor_id}: joint_value_likelihoods must cover exactly {sorted(expected_keys)}"
            )
        for active_set, distribution in joint.items():
            _validate_distribution(
                distribution,
                f"{factor_id}.joint_value_likelihoods[{active_set}]",
            )
            if distribution.get("family") != "categorical":
                raise ValueError(
                    f"{factor_id}: canonical member-object likelihoods must be categorical"
                )
        if (factor.get("unknown_likelihood") is None) != (
            factor.get("reference_likelihood") is None
        ):
            raise ValueError(f"{factor_id}: unknown/reference likelihood must be paired")
        for key in ("unknown_likelihood", "reference_likelihood"):
            if factor.get(key) is not None:
                _validate_distribution(factor[key], f"{factor_id}.{key}")
                if factor[key].get("family") != "categorical":
                    raise ValueError(
                        f"{factor_id}: {key} must use canonical categorical member-object keys"
                    )

    topology = spec.get("topology", {})
    for edge in topology.get("edges", []):
        if edge.get("source") not in process_ids or edge.get("target") not in process_ids:
            raise ValueError(f"topology edge references unknown process: {edge}")
        if _finite_number(edge.get("distance", 0.0), "topology edge distance") <= 0.0:
            raise ValueError("topology edge distance must be positive")
    known_strata = set(all_strata)
    for edge in topology.get("stratum_edges", []):
        source = edge.get("source_stratum_id")
        target = edge.get("target_stratum_id")
        if source not in known_strata or target not in known_strata:
            raise ValueError(f"stratum topology edge references unknown stratum: {edge}")
        if source == target:
            raise ValueError("stratum topology edge cannot be a self-edge")
        if _finite_number(edge.get("distance", 0.0), "stratum edge distance") <= 0.0:
            raise ValueError("stratum topology edge distance must be positive")
    for bridge in topology.get("planning_bridges", []):
        source, target = bridge.get("source_process_id"), bridge.get("target_process_id")
        if source not in process_ids or target not in process_ids:
            raise ValueError(f"planning bridge references unknown process: {bridge}")
        if bridge.get("source_coordinate_id") not in coordinate_ids[source]:
            raise ValueError(f"planning bridge has unknown source coordinate: {bridge}")
        if bridge.get("target_coordinate_id") not in coordinate_ids[target]:
            raise ValueError(f"planning bridge has unknown target coordinate: {bridge}")
        _finite_number(bridge.get("scale", 1.0), "planning bridge scale")

    objective_id = str(scope["outcome_ids"][0])
    objective_upper = sum(
        float(coordinate.get("objective_weight", 0.0))
        for process in processes
        for coordinate in process.get("coordinates", [])
    )

    actions = spec.get("actions", [])
    action_ids = _unique(actions, "action_id", "actions") if actions else set()
    for action in actions:
        dose_reference = _finite_number(
            action.get("dose_reference", 0.0), f"{action['action_id']}.dose_reference"
        )
        washout_steps = _finite_number(
            action.get("washout_steps", 0.0), f"{action['action_id']}.washout_steps"
        )
        if dose_reference <= 0.0:
            raise ValueError(f"{action['action_id']}: dose_reference must be positive")
        if washout_steps < 0.0:
            raise ValueError(f"{action['action_id']}: washout_steps must be non-negative")
        action_cost = _finite_number(
            action.get("action_cost", 0.0), f"{action['action_id']}.action_cost"
        )
        if action_cost < 0.0:
            raise ValueError(f"{action['action_id']}: action_cost must be non-negative")
        if action.get("causal_status") not in {
            "IDENTIFIED_WITHIN_SCOPE", "PARTIALLY_IDENTIFIED", "UNIDENTIFIABLE", "OUT_OF_SCOPE"
        }:
            raise ValueError(f"{action['action_id']}: invalid causal_status")
        identified_set = action.get("identified_set")
        if identified_set is not None:
            if len(scope["outcome_ids"]) != 1:
                raise ValueError(
                    f"{action['action_id']}: scalar identified_set requires exactly one scope outcome"
                )
            if not isinstance(identified_set, Mapping):
                raise ValueError(f"{action['action_id']}: identified_set must be an object")
            lower = _finite_number(
                identified_set.get("lower"), f"{action['action_id']}.identified_set.lower"
            )
            upper = _finite_number(
                identified_set.get("upper"), f"{action['action_id']}.identified_set.upper"
            )
            if lower > upper or not identified_set.get("unit"):
                raise ValueError(f"{action['action_id']}: invalid identified_set")
            if str(identified_set["unit"]) != objective_id:
                raise ValueError(
                    f"{action['action_id']}: identified_set unit must equal scope objective {objective_id}"
                )
            if lower < -1e-12 or upper > objective_upper + 1e-12:
                raise ValueError(
                    f"{action['action_id']}: identified_set must bound the complete post-policy "
                    f"{objective_id} outcome in [0, {objective_upper}], not an action effect"
                )
            action["identified_set"] = {
                "lower": lower,
                "upper": upper,
                "unit": objective_id,
            }
            identified_set = action["identified_set"]
        world_values = action.get("compatible_world_values")
        if world_values is not None:
            if len(scope["outcome_ids"]) != 1:
                raise ValueError(
                    f"{action['action_id']}: compatible world values require exactly one scope outcome"
                )
            world_value_unit = action.get("compatible_world_value_unit")
            if world_value_unit != objective_id:
                raise ValueError(
                    f"{action['action_id']}: compatible_world_value_unit must equal scope objective "
                    f"{objective_id}; values must be complete post-policy outcomes"
                )
            if not isinstance(world_values, Mapping) or not world_values:
                raise ValueError(
                    f"{action['action_id']}: compatible_world_values must be a non-empty mapping"
                )
            normalized_world_values = {
                str(world_id): _finite_number(
                    value,
                    f"{action['action_id']}.compatible_world_values.{world_id}",
                )
                for world_id, value in world_values.items()
                if str(world_id)
            }
            if len(normalized_world_values) != len(world_values):
                raise ValueError(f"{action['action_id']}: compatible world ids must be non-empty")
            world_lower = min(normalized_world_values.values())
            world_upper = max(normalized_world_values.values())
            if world_lower < -1e-12 or world_upper > objective_upper + 1e-12:
                raise ValueError(
                    f"{action['action_id']}: compatible world values must be complete post-policy "
                    f"{objective_id} outcomes in [0, {objective_upper}]"
                )
            if identified_set is None:
                action["identified_set"] = {
                    "lower": world_lower,
                    "upper": world_upper,
                    "unit": objective_id,
                }
            elif (
                world_lower < float(identified_set["lower"])
                or world_upper > float(identified_set["upper"])
            ):
                raise ValueError(
                    f"{action['action_id']}: identified_set excludes a compatible world value"
                )
            action["compatible_world_values"] = normalized_world_values
        compatible_world_ids = action.get("compatible_world_ids")
        if compatible_world_ids is not None and (
            not isinstance(compatible_world_ids, list)
            or not compatible_world_ids
            or any(not isinstance(value, str) or not value for value in compatible_world_ids)
            or len(set(compatible_world_ids)) != len(compatible_world_ids)
        ):
            raise ValueError(f"{action['action_id']}: invalid compatible_world_ids")
        if action.get("dose_unit") is not None and (
            not isinstance(action["dose_unit"], str) or not action["dose_unit"]
        ):
            raise ValueError(f"{action['action_id']}: dose_unit must be a non-empty string")
        for effect in action.get("effects", []):
            pid = effect.get("process_id")
            if pid not in process_ids or effect.get("coordinate_id") not in coordinate_ids[pid]:
                raise ValueError(f"{action['action_id']}: invalid effect target {effect}")
            _finite_number(
                effect.get("delta_per_unit_step"),
                f"{action['action_id']}.effect.delta_per_unit_step",
            )
        for effect in action.get("activation_effects", []):
            pid = effect.get("process_id")
            if pid not in process_ids:
                raise ValueError(f"{action['action_id']}: invalid activation effect target {pid}")
            unknown_keys = set(effect).difference(
                {
                    "process_id",
                    "enter_log_hazard_shift_per_unit",
                    "withdraw_log_hazard_shift_per_unit",
                    "parameter_status",
                    "source_id",
                    "version",
                }
            )
            if unknown_keys:
                raise ValueError(
                    f"{action['action_id']}: activation effect has unknown keys {sorted(unknown_keys)}"
                )
            if not {
                "enter_log_hazard_shift_per_unit",
                "withdraw_log_hazard_shift_per_unit",
            }.intersection(effect):
                raise ValueError(f"{action['action_id']}: empty activation effect")
            if effect.get("parameter_status") not in {
                "STRUCTURAL_TOY_NONCALIBRATED",
                "MECHANISM_CONSTRAINED",
                "EMPIRICALLY_ESTIMATED",
            }:
                raise ValueError(
                    f"{action['action_id']}: activation effect requires valid parameter_status"
                )
            if not effect.get("source_id") or not effect.get("version"):
                raise ValueError(
                    f"{action['action_id']}: activation effect requires source_id and version"
                )
            for key in (
                "enter_log_hazard_shift_per_unit",
                "withdraw_log_hazard_shift_per_unit",
            ):
                if key in effect:
                    _finite_number(effect[key], f"{action['action_id']}.activation_effect.{key}")

    for process in processes:
        for stratum in process.get("strata", []):
            unknown_actions = set(stratum.get("action_effect_modifiers", {})).difference(action_ids)
            if unknown_actions:
                raise ValueError(
                    f"{process['process_id']}.{stratum['stratum_id']}: "
                    f"unknown action modifiers {sorted(unknown_actions)}"
                )
            if any(
                not math.isfinite(float(value))
                for value in stratum.get("action_effect_modifiers", {}).values()
            ):
                raise ValueError(f"{process['process_id']}: non-finite action effect modifier")

    for coupling in spec.get("process_couplings", []):
        source, target = coupling.get("source_process_id"), coupling.get("target_process_id")
        if source not in process_ids or target not in process_ids:
            raise ValueError(f"invalid process coupling: {coupling}")
        if coupling.get("source_coordinate_id") not in coordinate_ids[source]:
            raise ValueError(f"invalid coupling source coordinate: {coupling}")
        if coupling.get("target_coordinate_id") not in coordinate_ids[target]:
            raise ValueError(f"invalid coupling target coordinate: {coupling}")
        _finite_number(coupling.get("strength_per_step"), "process coupling strength_per_step")

    for coupling in spec.get("mode_couplings", []):
        source, target = coupling.get("source_process_id"), coupling.get("target_process_id")
        if source not in process_ids or target not in process_ids:
            raise ValueError(f"invalid mode coupling: {coupling}")
        if coupling.get("source_mode_id") not in mode_ids[source]:
            raise ValueError(f"invalid mode coupling source mode: {coupling}")
        if coupling.get("target_mode_id") not in mode_ids[target]:
            raise ValueError(f"invalid mode coupling target mode: {coupling}")
        _finite_number(coupling.get("log_potential_per_step"), "mode coupling log_potential_per_step")

    for interaction in spec.get("coactivation_interactions", []):
        if interaction.get("process_a") not in process_ids or interaction.get("process_b") not in process_ids:
            raise ValueError(f"invalid coactivation interaction: {interaction}")
        _finite_number(
            interaction.get("log_potential_when_coactive", 0.0),
            "coactivation interaction log_potential_when_coactive",
        )

    for coupling in spec.get("process_activation_couplings", []):
        source = coupling.get("source_process_id")
        target = coupling.get("target_process_id")
        if source not in process_ids or target not in process_ids:
            raise ValueError(f"invalid process activation coupling: {coupling}")
        unknown_keys = set(coupling).difference(
            {
                "coupling_id",
                "source_process_id",
                "target_process_id",
                "enter_log_hazard_shift_per_step",
                "withdraw_log_hazard_shift_per_step",
                "parameter_status",
                "source_id",
                "version",
            }
        )
        if unknown_keys:
            raise ValueError(
                f"process activation coupling has unknown keys {sorted(unknown_keys)}"
            )
        if not coupling.get("coupling_id"):
            raise ValueError("process activation coupling requires coupling_id")
        if coupling.get("parameter_status") not in {
            "STRUCTURAL_TOY_NONCALIBRATED",
            "MECHANISM_CONSTRAINED",
            "EMPIRICALLY_ESTIMATED",
        }:
            raise ValueError("process activation coupling requires valid parameter_status")
        if not coupling.get("source_id") or not coupling.get("version"):
            raise ValueError("process activation coupling requires source_id and version")
        if not {
            "enter_log_hazard_shift_per_step",
            "withdraw_log_hazard_shift_per_step",
        }.intersection(coupling):
            raise ValueError("process activation coupling must declare a hazard shift")
        for key in (
            "enter_log_hazard_shift_per_step",
            "withdraw_log_hazard_shift_per_step",
        ):
            if key in coupling:
                _finite_number(coupling[key], f"process activation coupling.{key}")

    spec.setdefault("actions", [])
    spec.setdefault("process_couplings", [])
    spec.setdefault("mode_couplings", [])
    spec.setdefault("coactivation_interactions", [])
    spec.setdefault("common_cause_factors", [])
    spec.setdefault("process_activation_couplings", [])
    spec.setdefault("epistemic", {})
    spec["epistemic"].setdefault("unknown_prior", 0.15)
    spec["epistemic"].setdefault("unmapped_event_log_bayes_factor", 0.7)
    spec["epistemic"].setdefault("mapping_beta_prior", [1.0, 1.0])
    spec["epistemic"].setdefault("known_factor_misfit_surprisal_threshold", 6.0)
    unknown_prior = _finite_number(spec["epistemic"]["unknown_prior"], "epistemic.unknown_prior")
    if not 0.0 < unknown_prior < 1.0:
        raise ValueError("epistemic.unknown_prior must be in (0,1)")
    _finite_number(
        spec["epistemic"]["unmapped_event_log_bayes_factor"],
        "epistemic.unmapped_event_log_bayes_factor",
    )
    beta_prior = spec["epistemic"]["mapping_beta_prior"]
    if not isinstance(beta_prior, list) or len(beta_prior) != 2:
        raise ValueError("epistemic.mapping_beta_prior must contain alpha and beta")
    beta_values = [_finite_number(value, "epistemic.mapping_beta_prior") for value in beta_prior]
    if any(value <= 0.0 for value in beta_values):
        raise ValueError("epistemic.mapping_beta_prior values must be positive")
    misfit_threshold = _finite_number(
        spec["epistemic"]["known_factor_misfit_surprisal_threshold"],
        "epistemic.known_factor_misfit_surprisal_threshold",
    )
    if misfit_threshold < 0.0:
        raise ValueError("epistemic.known_factor_misfit_surprisal_threshold must be finite and non-negative")
    spec.setdefault("topology", {})
    spec["topology"].setdefault("edges", [])
    spec["topology"].setdefault("stratum_edges", [])
    spec["topology"].setdefault("planning_bridges", [])
    spec["topology"].setdefault("distance_scale", 1.0)
    spec["topology"].setdefault("inference_coupling", 0.0)
    spec["topology"].setdefault("planning_coupling", 0.0)
    distance_scale = _finite_number(spec["topology"]["distance_scale"], "topology.distance_scale")
    if distance_scale <= 0.0:
        raise ValueError("topology.distance_scale must be positive")
    _finite_number(spec["topology"]["inference_coupling"], "topology.inference_coupling")
    _finite_number(spec["topology"]["planning_coupling"], "topology.planning_coupling")
    spec.setdefault("inference", {})
    spec["inference"].setdefault("max_exact_processes", max_exact)
    thresholds = spec["inference"].get("activation_status_thresholds")
    if not isinstance(thresholds, Mapping):
        raise ValueError("inference.activation_status_thresholds must be declared")
    inactive = _finite_number(thresholds.get("inactive_upper", -1.0), "inactive_upper")
    possible = _finite_number(thresholds.get("possible_lower", -1.0), "possible_lower")
    active = _finite_number(thresholds.get("active_lower", -1.0), "active_lower")
    if not 0.0 <= inactive <= possible <= active <= 1.0:
        raise ValueError("invalid activation status thresholds")
    return spec


def validate_state_payload(
    payload: Mapping[str, Any],
    model_spec: Mapping[str, Any],
    *,
    state_context: Mapping[str, Any] | None = None,
) -> None:
    """Validate one model-bound operational state, including history references.

    ``state_context`` is supplied at a canonical-wire boundary.  It carries the
    few lineage facts (the current public cursor, the immediately preceding
    state hash and the set of events added by this update) that are not part of
    the private operational cache.  Generated warm states are still checked
    without that optional context; cold/query boundaries get the stronger
    lineage checks.
    """

    if payload.get("internal_schema_version") != "new-clinical-runtime.internal.v2.1":
        raise ValueError("wrong internal state schema version")
    rows = payload.get("joint_hypotheses")
    if not isinstance(rows, list) or not rows:
        raise ValueError("joint_hypotheses must be non-empty")
    probabilities = [float(row.get("probability", math.nan)) for row in rows]
    if any(not math.isfinite(p) or p < 0.0 for p in probabilities):
        raise ValueError("invalid joint probability")
    if abs(sum(probabilities) - 1.0) > 1e-9:
        raise ValueError("joint probabilities do not sum to one")
    process_ids = {row["process_id"] for row in model_spec["processes"]}
    mode_ids = {
        row["process_id"]: {mode["mode_id"] for mode in row["modes"]}
        for row in model_spec["processes"]
    }
    stratum_ids = {
        row["process_id"]: (
            {stratum["stratum_id"] for stratum in row.get("strata", [])}
            or {f"stratum:{row['process_id']}"}
        )
        for row in model_spec["processes"]
    }
    for row in rows:
        active = row.get("active_processes", [])
        if len(active) != len(set(active)) or not set(active).issubset(process_ids):
            raise ValueError("joint hypothesis has invalid active process set")
    if set(payload.get("per_process", {})) != process_ids:
        raise ValueError("per_process keys do not match model process ids")
    for process in model_spec["processes"]:
        pid = process["process_id"]
        local = payload["per_process"][pid]
        modes = local.get("mode_posterior", {})
        if abs(sum(float(v) for v in modes.values()) - 1.0) > 1e-9:
            raise ValueError(f"{pid}: mode posterior does not sum to one")
        strata = local.get("stratum_posterior", {})
        expected_strata = {
            row["stratum_id"] for row in process.get("strata", [])
        } or {f"stratum:{pid}"}
        if set(strata) != expected_strata:
            raise ValueError(f"{pid}: stratum posterior ids do not match model")
        if abs(sum(float(v) for v in strata.values()) - 1.0) > 1e-9:
            raise ValueError(f"{pid}: stratum posterior does not sum to one")
        coord_spec = {row["coordinate_id"]: row for row in process["coordinates"]}
        for cid, estimate in local.get("coordinates", {}).items():
            low, high = map(float, coord_spec[cid]["bounds"])
            mean = float(estimate["mean"])
            if not low - 1e-12 <= mean <= high + 1e-12:
                raise ValueError(f"{pid}.{cid}: coordinate outside bounds")
    stratum_owner = {
        sid: pid for pid, ids in stratum_ids.items() for sid in ids
    }
    event_ids = {str(event_id) for event_id in payload.get("event_ledger", {})}
    event_cursor = len(event_ids)
    if state_context is not None:
        declared_cursor = state_context.get("event_cursor")
        if isinstance(declared_cursor, bool) or not isinstance(declared_cursor, int):
            raise ValueError("architecture event cursor must be an integer")
        if declared_cursor != event_cursor:
            raise ValueError(
                "architecture event cursor does not equal processed event cardinality"
            )
        retained = {str(value) for value in state_context.get("processed_event_ids", [])}
        if retained != event_ids:
            raise ValueError(
                "architecture processed event lineage disagrees with operational ledger"
            )
        new_event_ids = [str(value) for value in state_context.get("new_event_ids", [])]
        if len(new_event_ids) != len(set(new_event_ids)) or not set(new_event_ids).issubset(event_ids):
            raise ValueError("architecture new_event_ids are not a unique processed subset")
    else:
        new_event_ids = []

    factor_processes = {
        str(observation["factor_id"]): {
            str(emission["process_id"])
            for emission in observation.get("emissions", [])
        }
        for observation in model_spec.get("observations", [])
    }
    declared_guards = {
        process["process_id"]: {
            str(guard["guard_id"])
            for guard in process.get("mode_guards", [])
        }
        for process in model_spec["processes"]
    }
    latest_transition_cursor: dict[str, int] = {}
    seen_transition_slots: set[tuple[str, int]] = set()
    for transition in payload.get("mode_transitions", []):
        sid = str(transition.get("stratum_id") or "")
        pid = stratum_owner.get(sid)
        if pid is None:
            raise ValueError(f"mode transition references unknown stratum: {sid}")
        if transition.get("from_mode_id") not in mode_ids[pid]:
            raise ValueError(
                f"mode transition references unknown source mode: {pid}.{transition.get('from_mode_id')}"
            )
        if transition.get("to_mode_id") not in mode_ids[pid]:
            raise ValueError(
                f"mode transition references unknown target mode: {pid}.{transition.get('to_mode_id')}"
            )
        if transition.get("from_mode_id") == transition.get("to_mode_id"):
            raise ValueError("mode transition cannot record a no-op mode change")
        cursor = transition.get("event_cursor")
        if (
            isinstance(cursor, bool)
            or not isinstance(cursor, int)
            or cursor < 0
            or cursor > event_cursor
        ):
            raise ValueError("mode transition event_cursor is outside processed lineage")
        slot = (sid, cursor)
        if slot in seen_transition_slots:
            raise ValueError("mode transition duplicates a stratum/event cursor")
        seen_transition_slots.add(slot)
        latest_transition_cursor[pid] = max(
            cursor, latest_transition_cursor.get(pid, cursor)
        )
        guard_ids = [str(value) for value in transition.get("guard_ids", [])]
        if not guard_ids or len(guard_ids) != len(set(guard_ids)):
            raise ValueError("mode transition guard_ids must be non-empty and unique")
        for guard_id in guard_ids:
            if guard_id in declared_guards[pid]:
                continue
            if guard_id.startswith("emission:"):
                factor_id = guard_id.split(":", 1)[1]
                if pid in factor_processes.get(factor_id, set()):
                    continue
            raise ValueError(
                f"mode transition references undeclared guard/factor for {pid}: {guard_id}"
            )

    for pid in process_ids:
        declared_last = payload["per_process"][pid].get("last_transition_cursor")
        expected_last = latest_transition_cursor.get(pid)
        if declared_last != expected_last:
            raise ValueError(
                f"{pid}: last_transition_cursor disagrees with retained mode transitions"
            )

    # Numeric history is a retained-event materialized view.  Every source id
    # must therefore be part of the canonical processed-event set; otherwise a
    # caller could rehash a feature with invented provenance and have all query
    # heads consume it as longitudinal truth.
    for concept_id, summary in payload.get("history_summary", {}).items():
        source_ids = [str(value) for value in summary.get("source_event_ids", [])]
        if not source_ids or len(source_ids) != len(set(source_ids)):
            raise ValueError(
                f"trajectory history source_event_ids must be non-empty and unique: {concept_id}"
            )
        if not set(source_ids).issubset(event_ids):
            raise ValueError(
                f"trajectory history references unprocessed source events: {concept_id}"
            )

    action_ids = {str(row["action_id"]) for row in model_spec.get("actions", [])}
    action_instances = payload.get("action_instances", {})
    for exposure_id, instance in action_instances.items():
        if instance.get("action_id") not in action_ids:
            raise ValueError(
                f"action instance references unregistered action: {exposure_id}"
            )

    windows = payload.get("action_response_windows", [])
    seen_window_ids: set[str] = set()
    windows_by_id: dict[str, Mapping[str, Any]] = {}
    for window in windows:
        window_id = str(window.get("window_id") or "")
        if not window_id or window_id in seen_window_ids:
            raise ValueError("action response window ids must be non-empty and unique")
        seen_window_ids.add(window_id)
        windows_by_id[window_id] = window
        instance_ids = [str(value) for value in window.get("action_instance_ids", [])]
        if (
            not instance_ids
            or len(instance_ids) != len(set(instance_ids))
            or not set(instance_ids).issubset(action_instances)
        ):
            raise ValueError(
                f"action response window references unknown/duplicate action instances: {window_id}"
            )
        start = window.get("start_cursor")
        end = window.get("end_cursor")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
            or end > event_cursor
        ):
            raise ValueError(
                f"action response window cursor range is inconsistent: {window_id}"
            )
        for instance_id in instance_ids:
            started_cursor = action_instances[instance_id].get("started_cursor")
            if started_cursor is None or int(started_cursor) != start:
                raise ValueError(
                    f"action response window start does not match action start: {window_id}"
                )
        result_event_ids = [str(value) for value in window.get("result_event_ids", [])]
        if (
            not result_event_ids
            or len(result_event_ids) != len(set(result_event_ids))
            or not set(result_event_ids).issubset(event_ids)
        ):
            raise ValueError(
                f"action response window results are not a processed-event subset: {window_id}"
            )

        # The frozen wire carries only the immediately preceding state hash,
        # not the complete ancestry chain.  We can therefore prove the
        # baseline of a window created by *this* update, while an older or
        # migrated window remains an explicitly opaque historical digest.
        if state_context is not None and set(result_event_ids).intersection(new_event_ids):
            parent_hash = state_context.get("parent_state_hash")
            if parent_hash is not None:
                expected_baseline = str(parent_hash)
            else:
                expected_baseline = digest(
                    {
                        "kind": "within-update-response-baseline",
                        "model_digest": state_context.get("model_digest"),
                        "event_cursor": max(0, end - 1),
                    }
                )
            if window.get("baseline_state_hash") != expected_baseline:
                raise ValueError(
                    f"action response window baseline is not bound to this update: {window_id}"
                )

    # Response summaries are the action-side view of the same windows.  Close
    # the two materialized views so a forged window or summary cannot survive
    # merely by recomputing both outer content hashes.
    referenced_windows: set[str] = set()
    for instance_id, instance in action_instances.items():
        for summary in instance.get("response_summaries", []):
            window_id = str(summary.get("window_id") or "")
            window = windows_by_id.get(window_id)
            if window is None or instance_id not in window.get("action_instance_ids", []):
                raise ValueError(
                    f"action response summary references an unrelated/missing window: {window_id}"
                )
            source_ids = [str(value) for value in summary.get("source_event_ids", [])]
            if (
                not source_ids
                or len(source_ids) != len(set(source_ids))
                or not set(source_ids).issubset(set(window.get("result_event_ids", [])))
            ):
                raise ValueError(
                    f"action response summary provenance disagrees with its window: {window_id}"
                )
            referenced_windows.add(window_id)
    if set(windows_by_id) != referenced_windows:
        raise ValueError("action response window lacks a bound action response summary")


__all__ = [
    "ARCHITECTURE_VERSION",
    "EVENT_SCHEMA_VERSION",
    "MODEL_SCHEMA_VERSION",
    "RUNTIME_VERSION",
    "STATE_SCHEMA_VERSION",
    "PublicEvent",
    "SharedPatientState",
    "architecture_state_hash",
    "canonical_json_bytes",
    "digest",
    "validate_migration_spec",
    "validate_model_spec",
    "validate_architecture_state_payload",
    "validate_state_payload",
]
