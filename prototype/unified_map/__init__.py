"""Isolated Unified Clinical Map research package.

The package intentionally has no dependency on the legacy K0 candidate or
bridge APIs.  Benchmark version 1 is not frozen until its freeze manifest and
all self-tests exist.
"""

from .canonical import ProtocolViolation, canonical_json_bytes, digest_json
from .schema import (
    ActionPlan,
    CandidateVisibleEvent,
    DiagnosisQuery,
    EventKind,
    JudgePrivateCase,
    PlanKind,
    PlannedAction,
    RolloutQuery,
    TrainerOnlyTargets,
    TrainingExample,
    VisibleDelta,
    VisibleHistory,
)
from .state import (
    CandidateStateInput,
    HarnessStateRecord,
    SealedState,
    StateClass,
    StatePayload,
    compute_state_hash,
    seal_state,
)

__all__ = [
    "ActionPlan",
    "CandidateStateInput",
    "CandidateVisibleEvent",
    "DiagnosisQuery",
    "EventKind",
    "HarnessStateRecord",
    "JudgePrivateCase",
    "PlanKind",
    "PlannedAction",
    "ProtocolViolation",
    "RolloutQuery",
    "SealedState",
    "StateClass",
    "StatePayload",
    "TrainerOnlyTargets",
    "TrainingExample",
    "VisibleDelta",
    "VisibleHistory",
    "canonical_json_bytes",
    "compute_state_hash",
    "digest_json",
    "seal_state",
]
