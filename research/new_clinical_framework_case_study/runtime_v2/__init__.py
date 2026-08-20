"""Stable public interface for the independent new-clinical-framework runtime v2."""

from .engine import RuntimeV2, log_likelihood
from .io import load_events_json, load_state_json, save_state_json
from .migration import import_legacy_v1_state, migrate_v2_state
from .ledger import (
    LEDGER_PROOF_SCHEMA_VERSION,
    attach_event_ledger_proof,
    build_event_ledger_proof,
)
from .refinement import (
    RefinementExecution,
    evaluate_behavioral_collision,
    execute_local_refinement,
)
from .schema import (
    ARCHITECTURE_VERSION,
    EVENT_SCHEMA_VERSION,
    MODEL_SCHEMA_VERSION,
    RUNTIME_VERSION,
    STATE_SCHEMA_VERSION,
    PublicEvent,
    SharedPatientState,
    architecture_state_hash,
    canonical_json_bytes,
    digest,
    validate_model_spec,
    validate_architecture_state_payload,
    validate_state_payload,
)

__all__ = [
    "ARCHITECTURE_VERSION",
    "EVENT_SCHEMA_VERSION",
    "LEDGER_PROOF_SCHEMA_VERSION",
    "MODEL_SCHEMA_VERSION",
    "RUNTIME_VERSION",
    "STATE_SCHEMA_VERSION",
    "PublicEvent",
    "RefinementExecution",
    "RuntimeV2",
    "SharedPatientState",
    "architecture_state_hash",
    "attach_event_ledger_proof",
    "build_event_ledger_proof",
    "canonical_json_bytes",
    "digest",
    "evaluate_behavioral_collision",
    "execute_local_refinement",
    "import_legacy_v1_state",
    "load_events_json",
    "load_state_json",
    "log_likelihood",
    "migrate_v2_state",
    "save_state_json",
    "validate_model_spec",
    "validate_architecture_state_payload",
    "validate_state_payload",
]
