"""Typed seed-panel and TRAIN5 precommit foundations for UCM benchmark v1.

This module deliberately stops before the hidden-seed confirmation chain.  It
defines the closed seed vocabulary, canonical five-replicate panels, the
zipped (not Cartesian-product) pairing authority, and the public TRAIN5
precommit which is published after semantic freeze and before training.

Raw TRAIN5 values belong in the public precommit.  The semantic scope manifest
binds only this protocol and the draw-program digest; it must not contain those
run-specific values.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    domain_digest,
)


SEED_PROTOCOL_VERSION = "ucm-seed-protocol/1"
TRAIN5_PRECOMMIT_PROTOCOL = "ucm-train5-precommit/1"
TRAIN5_PRECOMMIT_ARTIFACT_TYPE = "TRAIN5_PRECOMMIT"
TRAIN5_PRECOMMIT_STAGE = "post_freeze_pre_training"
ZIPPED_PAIRING_PROTOCOL = "ucm-zipped-seed-pairing-authority/1"
COMMITMENT_CONTEXT_PROTOCOL = "ucm-official-commitment-context/1"
FROZEN_BENCHMARK_REVISION = "FROZEN-v1"
OFFICIAL_COMMITMENT_HASH_DOMAIN = b"UCM-OFFICIAL-SEED-COMMITMENT-v2\0"

TRAINING_REPLICATE_IDS = tuple(f"train-{index:02d}" for index in range(1, 6))
EVALUATION_REPLICATE_IDS = tuple(f"eval-{index:02d}" for index in range(1, 6))
ZIPPED_REPLICATE_IDS = tuple(zip(TRAINING_REPLICATE_IDS, EVALUATION_REPLICATE_IDS))

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_TRAINING_TUPLE_DOMAIN = b"UCM-TRAINING-SEED-TUPLE-v1\0"
_EVALUATION_TUPLE_DOMAIN = b"UCM-EVALUATION-SEED-TUPLE-v1\0"
_TRAINING_PANEL_DOMAIN = b"UCM-TRAINING-SEED-PANEL-v1\0"
_EVALUATION_PANEL_DOMAIN = b"UCM-EVALUATION-SEED-PANEL-v1\0"
_PAIRING_AUTHORITY_DOMAIN = b"UCM-ZIPPED-SEED-PAIRING-v1\0"


class OfficialSeedDomain(str, Enum):
    """Closed official randomness domains named by the benchmark contract."""

    DEV5 = "DEV5"
    TRAIN5 = "TRAIN5"
    EVAL5 = "EVAL5"
    REPRO5 = "REPRO5"
    REDTEAM5 = "REDTEAM5"
    ANALYSIS = "analysis"


OFFICIAL_SEED_DOMAINS = tuple(domain.value for domain in OfficialSeedDomain)


class OfficialCommitmentDomain(str, Enum):
    """Closed blind-run families; these are never interchangeable."""

    CONFIRM = "CONFIRM5-v1"
    REPRO = "REPRO5-v1"
    REDTEAM = "REDTEAM5-v1"


class OfficialCommitmentStage(str, Enum):
    """Closed stages at which official randomness may be committed."""

    HIDDEN_EVALUATION = "hidden_evaluation_commitment"


_SEED_PROTOCOL_MANIFEST_WIRE = {
    "schema_version": SEED_PROTOCOL_VERSION,
    "artifact_type": "UCM_SEED_PROTOCOL_SEMANTICS",
    "official_seed_domains": list(OFFICIAL_SEED_DOMAINS),
    "training_seed_tuple_fields": [
        "model_initialization_seed",
        "training_data_seed",
        "training_order_seed",
    ],
    "evaluation_seed_tuple_fields": [
        "world_process_noise_seed",
        "observation_schedule_seed",
        "evaluation_episode_seed",
        "analysis_seed",
    ],
    "training_replicate_ids": list(TRAINING_REPLICATE_IDS),
    "evaluation_replicate_ids": list(EVALUATION_REPLICATE_IDS),
    "zipped_replicate_pairs": [
        {
            "training_replicate_id": training_id,
            "evaluation_replicate_id": evaluation_id,
        }
        for training_id, evaluation_id in ZIPPED_REPLICATE_IDS
    ],
    "train5_precommit": {
        "artifact_type": TRAIN5_PRECOMMIT_ARTIFACT_TYPE,
        "schema_version": TRAIN5_PRECOMMIT_PROTOCOL,
        "domain": OfficialSeedDomain.TRAIN5.value,
        "stage": TRAIN5_PRECOMMIT_STAGE,
        "benchmark_revision": FROZEN_BENCHMARK_REVISION,
        "previous_artifact_rule": "equals_freeze_manifest_digest",
        "committed_at_format": "canonical_rfc3339_utc_seconds",
        "required_authority_bindings": [
            "confirmation_id",
            "benchmark_id",
            "benchmark_revision",
            "previous_artifact_digest",
            "scope_digest",
            "scope_manifest_digest",
            "freeze_manifest_digest",
            "freeze_authorization_digest",
            "seed_protocol_digest",
            "draw_program_digest",
            "committed_at",
        ],
    },
    "official_commitment_context": {
        "schema_version": COMMITMENT_CONTEXT_PROTOCOL,
        "fields": [
            "confirmation_id",
            "benchmark_id",
            "benchmark_revision",
            "freeze_manifest_digest",
            "freeze_authorization_digest",
            "scope_digest",
            "scope_manifest_digest",
            "train5_precommit_digest",
            "training_panel_digest",
            "candidate_seals_artifact_digest",
            "candidate_seal_set_root",
            "candidate_seal_count",
            "candidate_ids_digest",
            "candidate_family_ids_digest",
            "seed_protocol_digest",
            "draw_program_digest",
            "evaluation_panel_digest",
            "zipped_pairing_digest",
            "commitment_domain",
            "commitment_stage",
            "committed_at",
        ],
        "candidate_seal_count_rule": "integer_at_least_15_divisible_by_5",
        "digest_rule": "sha256_canonical_exact_object",
        "hidden_seed_bytes": 32,
        "minimum_nonce_bytes": 16,
    },
    "commitment_domains": [domain.value for domain in OfficialCommitmentDomain],
    "commitment_stages": [stage.value for stage in OfficialCommitmentStage],
    "commitment_hash_domain": OFFICIAL_COMMITMENT_HASH_DOMAIN.decode("ascii"),
    "scope_binding": {
        "required_semantic_bindings": [
            "seed_protocol_digest",
            "draw_program_digest",
        ],
        "run_specific_raw_seed_values": "excluded_from_scope_manifest",
    },
}
SEED_PROTOCOL_MANIFEST_BYTES = canonical_json_bytes(_SEED_PROTOCOL_MANIFEST_WIRE)
SEED_PROTOCOL_DIGEST = digest_bytes(SEED_PROTOCOL_MANIFEST_BYTES)


_TRAINING_PANEL_DOMAINS = frozenset(
    {
        OfficialSeedDomain.DEV5,
        OfficialSeedDomain.TRAIN5,
        OfficialSeedDomain.REPRO5,
    }
)
_EVALUATION_PANEL_DOMAINS = frozenset(
    {
        OfficialSeedDomain.DEV5,
        OfficialSeedDomain.EVAL5,
        OfficialSeedDomain.REPRO5,
        OfficialSeedDomain.REDTEAM5,
    }
)


def _exact_nonnegative_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0 or value >= 2**64:
        raise ProtocolViolation(f"{label} must be an exact uint64 integer")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a lowercase sha256 digest")
    return value


def _identity(value: object, label: str) -> str:
    if type(value) is not str or _IDENTITY_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a canonical ASCII identity")
    return value


def _utc_timestamp(value: object, label: str) -> str:
    if type(value) is not str or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be canonical RFC3339 UTC seconds")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ProtocolViolation(f"{label} is not a real UTC timestamp") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ProtocolViolation(f"{label} must be canonical RFC3339 UTC seconds")
    return value


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ProtocolViolation(
            f"{label} keys mismatch: missing={missing}, extra={extra}"
        )
    return value


def _parse_domain(value: object, label: str) -> OfficialSeedDomain:
    if type(value) is not str:
        raise ProtocolViolation(f"{label} must be an exact string")
    try:
        return OfficialSeedDomain(value)
    except ValueError as error:
        raise ProtocolViolation(f"{label} is not an official seed domain") from error


def _canonical_json_object(payload: bytes, label: str) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation(f"{label} payload must be exact bytes")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except ProtocolViolation:
        raise
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise ProtocolViolation(f"{label} is not valid UTF-8 JSON") from error
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be a JSON object")
    try:
        canonical = canonical_json_bytes(value)
    except ProtocolViolation:
        raise
    except (RecursionError, UnicodeEncodeError, ValueError) as error:
        raise ProtocolViolation(f"{label} cannot be canonically encoded") from error
    if canonical != payload:
        raise ProtocolViolation(f"{label} must use canonical UTF-8 JSON + LF")
    return value


@dataclass(frozen=True, slots=True)
class TrainingSeedTuple:
    model_initialization_seed: int
    training_data_seed: int
    training_order_seed: int

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "model_initialization_seed",
            "training_data_seed",
            "training_order_seed",
        }
    )

    def __post_init__(self) -> None:
        _exact_nonnegative_integer(
            self.model_initialization_seed, "model_initialization_seed"
        )
        _exact_nonnegative_integer(self.training_data_seed, "training_data_seed")
        _exact_nonnegative_integer(self.training_order_seed, "training_order_seed")

    def to_wire(self) -> dict[str, int]:
        return {
            "model_initialization_seed": self.model_initialization_seed,
            "training_data_seed": self.training_data_seed,
            "training_order_seed": self.training_order_seed,
        }

    @classmethod
    def from_wire(cls, value: object) -> TrainingSeedTuple:
        row = _exact_keys(value, cls._KEYS, "training seed tuple")
        return cls(
            model_initialization_seed=_exact_nonnegative_integer(
                row["model_initialization_seed"], "model_initialization_seed"
            ),
            training_data_seed=_exact_nonnegative_integer(
                row["training_data_seed"], "training_data_seed"
            ),
            training_order_seed=_exact_nonnegative_integer(
                row["training_order_seed"], "training_order_seed"
            ),
        )

    def digest(self, domain: OfficialSeedDomain, replicate_id: str) -> str:
        if type(domain) is not OfficialSeedDomain:
            raise ProtocolViolation("training tuple domain must be OfficialSeedDomain")
        if domain not in _TRAINING_PANEL_DOMAINS:
            raise ProtocolViolation(f"{domain.value} is not a training panel domain")
        if replicate_id not in TRAINING_REPLICATE_IDS:
            raise ProtocolViolation("training replicate id is not canonical")
        return domain_digest(
            _TRAINING_TUPLE_DOMAIN,
            [
                domain.value.encode("ascii"),
                replicate_id.encode("ascii"),
                canonical_json_bytes(self.to_wire()),
            ],
        )


@dataclass(frozen=True, slots=True)
class EvaluationSeedTuple:
    world_process_noise_seed: int
    observation_schedule_seed: int
    evaluation_episode_seed: int
    analysis_seed: int

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "world_process_noise_seed",
            "observation_schedule_seed",
            "evaluation_episode_seed",
            "analysis_seed",
        }
    )

    def __post_init__(self) -> None:
        _exact_nonnegative_integer(
            self.world_process_noise_seed, "world_process_noise_seed"
        )
        _exact_nonnegative_integer(
            self.observation_schedule_seed, "observation_schedule_seed"
        )
        _exact_nonnegative_integer(
            self.evaluation_episode_seed, "evaluation_episode_seed"
        )
        _exact_nonnegative_integer(self.analysis_seed, "analysis_seed")

    def to_wire(self) -> dict[str, int]:
        return {
            "world_process_noise_seed": self.world_process_noise_seed,
            "observation_schedule_seed": self.observation_schedule_seed,
            "evaluation_episode_seed": self.evaluation_episode_seed,
            "analysis_seed": self.analysis_seed,
        }

    @classmethod
    def from_wire(cls, value: object) -> EvaluationSeedTuple:
        row = _exact_keys(value, cls._KEYS, "evaluation seed tuple")
        return cls(
            world_process_noise_seed=_exact_nonnegative_integer(
                row["world_process_noise_seed"], "world_process_noise_seed"
            ),
            observation_schedule_seed=_exact_nonnegative_integer(
                row["observation_schedule_seed"], "observation_schedule_seed"
            ),
            evaluation_episode_seed=_exact_nonnegative_integer(
                row["evaluation_episode_seed"], "evaluation_episode_seed"
            ),
            analysis_seed=_exact_nonnegative_integer(
                row["analysis_seed"], "analysis_seed"
            ),
        )

    def digest(self, domain: OfficialSeedDomain, replicate_id: str) -> str:
        if type(domain) is not OfficialSeedDomain:
            raise ProtocolViolation(
                "evaluation tuple domain must be OfficialSeedDomain"
            )
        if domain not in _EVALUATION_PANEL_DOMAINS:
            raise ProtocolViolation(f"{domain.value} is not an evaluation panel domain")
        if replicate_id not in EVALUATION_REPLICATE_IDS:
            raise ProtocolViolation("evaluation replicate id is not canonical")
        return domain_digest(
            _EVALUATION_TUPLE_DOMAIN,
            [
                domain.value.encode("ascii"),
                replicate_id.encode("ascii"),
                canonical_json_bytes(self.to_wire()),
            ],
        )


@dataclass(frozen=True, slots=True)
class TrainingSeedEntry:
    training_replicate_id: str
    seed_tuple: TrainingSeedTuple
    tuple_digest: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {"training_replicate_id", "seed_tuple", "tuple_digest"}
    )

    def validate(self, domain: OfficialSeedDomain) -> None:
        if self.training_replicate_id not in TRAINING_REPLICATE_IDS:
            raise ProtocolViolation("training replicate id is not canonical")
        _digest(self.tuple_digest, "training tuple digest")
        expected = self.seed_tuple.digest(domain, self.training_replicate_id)
        if self.tuple_digest != expected:
            raise ProtocolViolation("training tuple digest mismatch")

    def to_wire(self) -> dict[str, Any]:
        return {
            "training_replicate_id": self.training_replicate_id,
            "seed_tuple": self.seed_tuple.to_wire(),
            "tuple_digest": self.tuple_digest,
        }

    @classmethod
    def from_wire(cls, value: object, domain: OfficialSeedDomain) -> TrainingSeedEntry:
        row = _exact_keys(value, cls._KEYS, "training seed entry")
        if type(row["training_replicate_id"]) is not str:
            raise ProtocolViolation("training replicate id must be an exact string")
        result = cls(
            training_replicate_id=row["training_replicate_id"],
            seed_tuple=TrainingSeedTuple.from_wire(row["seed_tuple"]),
            tuple_digest=_digest(row["tuple_digest"], "training tuple digest"),
        )
        result.validate(domain)
        return result


@dataclass(frozen=True, slots=True)
class EvaluationSeedEntry:
    evaluation_replicate_id: str
    seed_tuple: EvaluationSeedTuple
    tuple_digest: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {"evaluation_replicate_id", "seed_tuple", "tuple_digest"}
    )

    def validate(self, domain: OfficialSeedDomain) -> None:
        if self.evaluation_replicate_id not in EVALUATION_REPLICATE_IDS:
            raise ProtocolViolation("evaluation replicate id is not canonical")
        _digest(self.tuple_digest, "evaluation tuple digest")
        expected = self.seed_tuple.digest(domain, self.evaluation_replicate_id)
        if self.tuple_digest != expected:
            raise ProtocolViolation("evaluation tuple digest mismatch")

    def to_wire(self) -> dict[str, Any]:
        return {
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "seed_tuple": self.seed_tuple.to_wire(),
            "tuple_digest": self.tuple_digest,
        }

    @classmethod
    def from_wire(
        cls, value: object, domain: OfficialSeedDomain
    ) -> EvaluationSeedEntry:
        row = _exact_keys(value, cls._KEYS, "evaluation seed entry")
        if type(row["evaluation_replicate_id"]) is not str:
            raise ProtocolViolation("evaluation replicate id must be an exact string")
        result = cls(
            evaluation_replicate_id=row["evaluation_replicate_id"],
            seed_tuple=EvaluationSeedTuple.from_wire(row["seed_tuple"]),
            tuple_digest=_digest(row["tuple_digest"], "evaluation tuple digest"),
        )
        result.validate(domain)
        return result


@dataclass(frozen=True, slots=True)
class TrainingSeedPanel:
    domain: OfficialSeedDomain
    entries: tuple[TrainingSeedEntry, ...]

    def __post_init__(self) -> None:
        if type(self.domain) is not OfficialSeedDomain:
            raise ProtocolViolation("training panel domain must be OfficialSeedDomain")
        if self.domain not in _TRAINING_PANEL_DOMAINS:
            raise ProtocolViolation(
                f"{self.domain.value} is not a training panel domain"
            )
        if type(self.entries) is not tuple or len(self.entries) != 5:
            raise ProtocolViolation("training panel must contain exactly five entries")
        if any(type(row) is not TrainingSeedEntry for row in self.entries):
            raise ProtocolViolation("training panel entries must be typed")
        replicate_ids = tuple(row.training_replicate_id for row in self.entries)
        if replicate_ids != TRAINING_REPLICATE_IDS:
            raise ProtocolViolation(
                "training panel entries must use canonical order train-01..05"
            )
        if len(set(replicate_ids)) != 5:
            raise ProtocolViolation("training panel replicate ids must be unique")
        for row in self.entries:
            row.validate(self.domain)

    @classmethod
    def from_tuples(
        cls,
        domain: OfficialSeedDomain,
        seed_tuples: tuple[TrainingSeedTuple, ...],
    ) -> TrainingSeedPanel:
        if type(seed_tuples) is not tuple or len(seed_tuples) != 5:
            raise ProtocolViolation("training panel requires exactly five typed tuples")
        entries: list[TrainingSeedEntry] = []
        for replicate_id, seed_tuple in zip(TRAINING_REPLICATE_IDS, seed_tuples):
            if type(seed_tuple) is not TrainingSeedTuple:
                raise ProtocolViolation("training panel tuples must be typed")
            entries.append(
                TrainingSeedEntry(
                    training_replicate_id=replicate_id,
                    seed_tuple=seed_tuple,
                    tuple_digest=seed_tuple.digest(domain, replicate_id),
                )
            )
        return cls(domain=domain, entries=tuple(entries))

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "entries": [row.to_wire() for row in self.entries],
        }

    @property
    def panel_digest(self) -> str:
        return domain_digest(
            _TRAINING_PANEL_DOMAIN, [canonical_json_bytes(self.preimage_wire())]
        )


@dataclass(frozen=True, slots=True)
class EvaluationSeedPanel:
    domain: OfficialSeedDomain
    entries: tuple[EvaluationSeedEntry, ...]

    def __post_init__(self) -> None:
        if type(self.domain) is not OfficialSeedDomain:
            raise ProtocolViolation(
                "evaluation panel domain must be OfficialSeedDomain"
            )
        if self.domain not in _EVALUATION_PANEL_DOMAINS:
            raise ProtocolViolation(
                f"{self.domain.value} is not an evaluation panel domain"
            )
        if type(self.entries) is not tuple or len(self.entries) != 5:
            raise ProtocolViolation(
                "evaluation panel must contain exactly five entries"
            )
        if any(type(row) is not EvaluationSeedEntry for row in self.entries):
            raise ProtocolViolation("evaluation panel entries must be typed")
        replicate_ids = tuple(row.evaluation_replicate_id for row in self.entries)
        if replicate_ids != EVALUATION_REPLICATE_IDS:
            raise ProtocolViolation(
                "evaluation panel entries must use canonical order eval-01..05"
            )
        if len(set(replicate_ids)) != 5:
            raise ProtocolViolation("evaluation panel replicate ids must be unique")
        for row in self.entries:
            row.validate(self.domain)

    @classmethod
    def from_tuples(
        cls,
        domain: OfficialSeedDomain,
        seed_tuples: tuple[EvaluationSeedTuple, ...],
    ) -> EvaluationSeedPanel:
        if type(seed_tuples) is not tuple or len(seed_tuples) != 5:
            raise ProtocolViolation(
                "evaluation panel requires exactly five typed tuples"
            )
        entries: list[EvaluationSeedEntry] = []
        for replicate_id, seed_tuple in zip(EVALUATION_REPLICATE_IDS, seed_tuples):
            if type(seed_tuple) is not EvaluationSeedTuple:
                raise ProtocolViolation("evaluation panel tuples must be typed")
            entries.append(
                EvaluationSeedEntry(
                    evaluation_replicate_id=replicate_id,
                    seed_tuple=seed_tuple,
                    tuple_digest=seed_tuple.digest(domain, replicate_id),
                )
            )
        return cls(domain=domain, entries=tuple(entries))

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "entries": [row.to_wire() for row in self.entries],
        }

    @property
    def panel_digest(self) -> str:
        return domain_digest(
            _EVALUATION_PANEL_DOMAIN, [canonical_json_bytes(self.preimage_wire())]
        )


@dataclass(frozen=True, slots=True)
class ZippedPairingAuthority:
    """Authority for the five required pairs; never a 5-by-5 search grid."""

    commitment_domain: OfficialCommitmentDomain
    training_panel_digest: str
    evaluation_panel_digest: str
    pairs: tuple[tuple[str, str], ...] = ZIPPED_REPLICATE_IDS

    def __post_init__(self) -> None:
        if type(self.commitment_domain) is not OfficialCommitmentDomain:
            raise ProtocolViolation("pairing commitment domain must be closed")
        if self.commitment_domain is OfficialCommitmentDomain.REDTEAM:
            raise ProtocolViolation("REDTEAM5 has no training-panel pairing authority")
        _digest(self.training_panel_digest, "training panel digest")
        _digest(self.evaluation_panel_digest, "evaluation panel digest")
        if type(self.pairs) is not tuple or self.pairs != ZIPPED_REPLICATE_IDS:
            raise ProtocolViolation(
                "pairing authority must use the canonical five zipped pairs"
            )

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": ZIPPED_PAIRING_PROTOCOL,
            "commitment_domain": self.commitment_domain.value,
            "training_panel_digest": self.training_panel_digest,
            "evaluation_panel_digest": self.evaluation_panel_digest,
            "pairs": [
                {
                    "training_replicate_id": training_id,
                    "evaluation_replicate_id": evaluation_id,
                }
                for training_id, evaluation_id in self.pairs
            ],
        }

    @property
    def pairing_digest(self) -> str:
        return domain_digest(
            _PAIRING_AUTHORITY_DOMAIN,
            [canonical_json_bytes(self.preimage_wire())],
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "pairing_digest": self.pairing_digest}


@dataclass(frozen=True, slots=True)
class OfficialCommitmentContext:
    """Exact authority roots which a hidden commitment must not escape."""

    confirmation_id: str
    benchmark_id: str
    benchmark_revision: str
    freeze_manifest_digest: str
    freeze_authorization_digest: str
    scope_digest: str
    scope_manifest_digest: str
    train5_precommit_digest: str
    training_panel_digest: str
    candidate_seals_artifact_digest: str
    candidate_seal_set_root: str
    candidate_seal_count: int
    candidate_ids_digest: str
    candidate_family_ids_digest: str
    seed_protocol_digest: str
    draw_program_digest: str
    evaluation_panel_digest: str
    zipped_pairing_digest: str
    commitment_domain: OfficialCommitmentDomain
    commitment_stage: OfficialCommitmentStage
    committed_at: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "confirmation_id",
            "benchmark_id",
            "benchmark_revision",
            "freeze_manifest_digest",
            "freeze_authorization_digest",
            "scope_digest",
            "scope_manifest_digest",
            "train5_precommit_digest",
            "training_panel_digest",
            "candidate_seals_artifact_digest",
            "candidate_seal_set_root",
            "candidate_seal_count",
            "candidate_ids_digest",
            "candidate_family_ids_digest",
            "seed_protocol_digest",
            "draw_program_digest",
            "evaluation_panel_digest",
            "zipped_pairing_digest",
            "commitment_domain",
            "commitment_stage",
            "committed_at",
        }
    )

    def __post_init__(self) -> None:
        _identity(self.confirmation_id, "commitment context confirmation id")
        _identity(self.benchmark_id, "commitment context benchmark id")
        if self.benchmark_revision != FROZEN_BENCHMARK_REVISION:
            raise ProtocolViolation(
                "commitment context benchmark revision must be FROZEN-v1"
            )
        _digest(
            self.freeze_manifest_digest,
            "commitment context freeze manifest digest",
        )
        _digest(
            self.freeze_authorization_digest,
            "commitment context freeze authorization digest",
        )
        _digest(self.scope_digest, "commitment context scope digest")
        _digest(
            self.scope_manifest_digest,
            "commitment context scope manifest digest",
        )
        _digest(
            self.train5_precommit_digest,
            "commitment context TRAIN5 precommit digest",
        )
        _digest(
            self.training_panel_digest,
            "commitment context training panel digest",
        )
        _digest(
            self.candidate_seals_artifact_digest,
            "commitment context candidate seals artifact digest",
        )
        _digest(
            self.candidate_seal_set_root,
            "commitment context candidate seal set root",
        )
        if (
            type(self.candidate_seal_count) is not int
            or self.candidate_seal_count < 15
            or self.candidate_seal_count % 5 != 0
        ):
            raise ProtocolViolation(
                "commitment context candidate seal count must be >=15 and divisible by 5"
            )
        _digest(
            self.candidate_ids_digest,
            "commitment context candidate ids digest",
        )
        _digest(
            self.candidate_family_ids_digest,
            "commitment context candidate family ids digest",
        )
        _digest(
            self.seed_protocol_digest,
            "commitment context seed protocol digest",
        )
        if self.seed_protocol_digest != SEED_PROTOCOL_DIGEST:
            raise ProtocolViolation(
                "commitment context must bind the code-owned seed protocol digest"
            )
        _digest(
            self.draw_program_digest,
            "commitment context draw program digest",
        )
        _digest(
            self.evaluation_panel_digest,
            "commitment context evaluation panel digest",
        )
        _digest(
            self.zipped_pairing_digest,
            "commitment context zipped pairing digest",
        )
        if type(self.commitment_domain) is not OfficialCommitmentDomain:
            raise ProtocolViolation("commitment context domain must be closed")
        if type(self.commitment_stage) is not OfficialCommitmentStage:
            raise ProtocolViolation("commitment context stage must be closed")
        _utc_timestamp(self.committed_at, "commitment context committed_at")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": COMMITMENT_CONTEXT_PROTOCOL,
            "confirmation_id": self.confirmation_id,
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "freeze_manifest_digest": self.freeze_manifest_digest,
            "freeze_authorization_digest": self.freeze_authorization_digest,
            "scope_digest": self.scope_digest,
            "scope_manifest_digest": self.scope_manifest_digest,
            "train5_precommit_digest": self.train5_precommit_digest,
            "training_panel_digest": self.training_panel_digest,
            "candidate_seals_artifact_digest": self.candidate_seals_artifact_digest,
            "candidate_seal_set_root": self.candidate_seal_set_root,
            "candidate_seal_count": self.candidate_seal_count,
            "candidate_ids_digest": self.candidate_ids_digest,
            "candidate_family_ids_digest": self.candidate_family_ids_digest,
            "seed_protocol_digest": self.seed_protocol_digest,
            "draw_program_digest": self.draw_program_digest,
            "evaluation_panel_digest": self.evaluation_panel_digest,
            "zipped_pairing_digest": self.zipped_pairing_digest,
            "commitment_domain": self.commitment_domain.value,
            "commitment_stage": self.commitment_stage.value,
            "committed_at": self.committed_at,
        }

    @classmethod
    def from_wire(cls, value: object) -> OfficialCommitmentContext:
        row = _exact_keys(value, cls._KEYS, "official commitment context")
        if row["schema_version"] != COMMITMENT_CONTEXT_PROTOCOL:
            raise ProtocolViolation("official commitment context schema mismatch")
        try:
            commitment_domain = OfficialCommitmentDomain(row["commitment_domain"])
            commitment_stage = OfficialCommitmentStage(row["commitment_stage"])
        except (TypeError, ValueError) as error:
            raise ProtocolViolation(
                "official commitment context domain/stage is not closed"
            ) from error
        return cls(
            confirmation_id=_identity(row["confirmation_id"], "confirmation id"),
            benchmark_id=_identity(row["benchmark_id"], "benchmark id"),
            benchmark_revision=row["benchmark_revision"],
            freeze_manifest_digest=_digest(
                row["freeze_manifest_digest"], "freeze manifest digest"
            ),
            freeze_authorization_digest=_digest(
                row["freeze_authorization_digest"], "freeze authorization digest"
            ),
            scope_digest=_digest(row["scope_digest"], "scope digest"),
            scope_manifest_digest=_digest(
                row["scope_manifest_digest"], "scope manifest digest"
            ),
            train5_precommit_digest=_digest(
                row["train5_precommit_digest"], "TRAIN5 precommit digest"
            ),
            training_panel_digest=_digest(
                row["training_panel_digest"], "training panel digest"
            ),
            candidate_seals_artifact_digest=_digest(
                row["candidate_seals_artifact_digest"],
                "candidate seals artifact digest",
            ),
            candidate_seal_set_root=_digest(
                row["candidate_seal_set_root"], "candidate seal set root"
            ),
            candidate_seal_count=_exact_nonnegative_integer(
                row["candidate_seal_count"], "candidate seal count"
            ),
            candidate_ids_digest=_digest(
                row["candidate_ids_digest"], "candidate ids digest"
            ),
            candidate_family_ids_digest=_digest(
                row["candidate_family_ids_digest"], "candidate family ids digest"
            ),
            seed_protocol_digest=_digest(
                row["seed_protocol_digest"], "seed protocol digest"
            ),
            draw_program_digest=_digest(
                row["draw_program_digest"], "draw program digest"
            ),
            evaluation_panel_digest=_digest(
                row["evaluation_panel_digest"], "evaluation panel digest"
            ),
            zipped_pairing_digest=_digest(
                row["zipped_pairing_digest"], "zipped pairing digest"
            ),
            commitment_domain=commitment_domain,
            commitment_stage=commitment_stage,
            committed_at=_utc_timestamp(row["committed_at"], "committed_at"),
        )

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def context_digest(self) -> str:
        return digest_json(self.to_wire())


def parse_official_commitment_context_bytes(
    payload: bytes,
) -> OfficialCommitmentContext:
    wire = _canonical_json_object(payload, "official commitment context")
    result = OfficialCommitmentContext.from_wire(wire)
    if result.to_bytes() != payload:
        raise ProtocolViolation("official commitment context reconstruction mismatch")
    return result


@dataclass(frozen=True, slots=True)
class Train5Precommit:
    confirmation_id: str
    benchmark_id: str
    benchmark_revision: str
    previous_artifact_digest: str
    scope_digest: str
    scope_manifest_digest: str
    freeze_manifest_digest: str
    freeze_authorization_digest: str
    seed_protocol_digest: str
    draw_program_digest: str
    committed_at: str
    panel: TrainingSeedPanel

    _TOP_LEVEL_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "artifact_type",
            "stage",
            "domain",
            "confirmation_id",
            "benchmark_id",
            "benchmark_revision",
            "previous_artifact_digest",
            "scope_digest",
            "scope_manifest_digest",
            "freeze_manifest_digest",
            "freeze_authorization_digest",
            "seed_protocol_digest",
            "draw_program_digest",
            "committed_at",
            "entries",
            "panel_digest",
        }
    )

    def __post_init__(self) -> None:
        _identity(self.confirmation_id, "TRAIN5 precommit confirmation id")
        _identity(self.benchmark_id, "TRAIN5 precommit benchmark id")
        if self.benchmark_revision != FROZEN_BENCHMARK_REVISION:
            raise ProtocolViolation(
                "TRAIN5 precommit benchmark revision must be FROZEN-v1"
            )
        _digest(self.previous_artifact_digest, "previous artifact digest")
        _digest(self.scope_digest, "scope digest")
        _digest(self.scope_manifest_digest, "scope manifest digest")
        _digest(self.freeze_manifest_digest, "freeze manifest digest")
        if self.previous_artifact_digest != self.freeze_manifest_digest:
            raise ProtocolViolation(
                "TRAIN5 precommit previous artifact must be the freeze manifest"
            )
        _digest(self.freeze_authorization_digest, "freeze authorization digest")
        _digest(self.seed_protocol_digest, "seed protocol digest")
        if self.seed_protocol_digest != SEED_PROTOCOL_DIGEST:
            raise ProtocolViolation(
                "TRAIN5 precommit must bind the code-owned seed protocol digest"
            )
        _digest(self.draw_program_digest, "draw program digest")
        _utc_timestamp(self.committed_at, "TRAIN5 precommit committed_at")
        if type(self.panel) is not TrainingSeedPanel:
            raise ProtocolViolation("TRAIN5 precommit panel must be typed")
        if self.panel.domain is not OfficialSeedDomain.TRAIN5:
            raise ProtocolViolation("TRAIN5 precommit panel domain must be TRAIN5")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": TRAIN5_PRECOMMIT_PROTOCOL,
            "artifact_type": TRAIN5_PRECOMMIT_ARTIFACT_TYPE,
            "stage": TRAIN5_PRECOMMIT_STAGE,
            "domain": OfficialSeedDomain.TRAIN5.value,
            "confirmation_id": self.confirmation_id,
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "previous_artifact_digest": self.previous_artifact_digest,
            "scope_digest": self.scope_digest,
            "scope_manifest_digest": self.scope_manifest_digest,
            "freeze_manifest_digest": self.freeze_manifest_digest,
            "freeze_authorization_digest": self.freeze_authorization_digest,
            "seed_protocol_digest": self.seed_protocol_digest,
            "draw_program_digest": self.draw_program_digest,
            "committed_at": self.committed_at,
            "entries": [row.to_wire() for row in self.panel.entries],
            "panel_digest": self.panel.panel_digest,
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())


def parse_train5_precommit_bytes(payload: bytes) -> Train5Precommit:
    wire = _exact_keys(
        _canonical_json_object(payload, "TRAIN5 precommit"),
        Train5Precommit._TOP_LEVEL_KEYS,
        "TRAIN5 precommit",
    )
    if wire["schema_version"] != TRAIN5_PRECOMMIT_PROTOCOL:
        raise ProtocolViolation("TRAIN5 precommit schema version mismatch")
    if wire["artifact_type"] != TRAIN5_PRECOMMIT_ARTIFACT_TYPE:
        raise ProtocolViolation("TRAIN5 precommit artifact type mismatch")
    if wire["stage"] != TRAIN5_PRECOMMIT_STAGE:
        raise ProtocolViolation("TRAIN5 precommit must be post-freeze and pre-training")
    domain = _parse_domain(wire["domain"], "TRAIN5 precommit domain")
    if domain is not OfficialSeedDomain.TRAIN5:
        raise ProtocolViolation("TRAIN5 precommit domain must be TRAIN5")
    if type(wire["entries"]) is not list:
        raise ProtocolViolation("TRAIN5 precommit entries must be a list")
    entries = tuple(TrainingSeedEntry.from_wire(row, domain) for row in wire["entries"])
    panel = TrainingSeedPanel(domain=domain, entries=entries)
    supplied_panel_digest = _digest(wire["panel_digest"], "training panel digest")
    if supplied_panel_digest != panel.panel_digest:
        raise ProtocolViolation("training panel digest mismatch")
    result = Train5Precommit(
        confirmation_id=_identity(wire["confirmation_id"], "confirmation id"),
        benchmark_id=_identity(wire["benchmark_id"], "benchmark id"),
        benchmark_revision=wire["benchmark_revision"],
        previous_artifact_digest=_digest(
            wire["previous_artifact_digest"], "previous artifact digest"
        ),
        scope_digest=_digest(wire["scope_digest"], "scope digest"),
        scope_manifest_digest=_digest(
            wire["scope_manifest_digest"], "scope manifest digest"
        ),
        freeze_manifest_digest=_digest(
            wire["freeze_manifest_digest"], "freeze manifest digest"
        ),
        freeze_authorization_digest=_digest(
            wire["freeze_authorization_digest"], "freeze authorization digest"
        ),
        seed_protocol_digest=_digest(
            wire["seed_protocol_digest"], "seed protocol digest"
        ),
        draw_program_digest=_digest(wire["draw_program_digest"], "draw program digest"),
        committed_at=_utc_timestamp(wire["committed_at"], "committed_at"),
        panel=panel,
    )
    if result.to_bytes() != payload:
        raise ProtocolViolation("TRAIN5 precommit canonical reconstruction mismatch")
    return result


def write_train5_precommit(path: Path, artifact: Train5Precommit) -> Path:
    if not isinstance(path, Path):
        raise ProtocolViolation("TRAIN5 precommit path must be pathlib.Path")
    if type(artifact) is not Train5Precommit:
        raise ProtocolViolation("TRAIN5 precommit artifact must be typed")
    payload = artifact.to_bytes()
    try:
        stream = path.open("xb")
    except FileExistsError as error:
        raise ProtocolViolation(
            "TRAIN5 precommit is append-only and already exists"
        ) from error
    try:
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if path.read_bytes() != payload:
        raise ProtocolViolation("TRAIN5 precommit write verification failed")
    parse_train5_precommit_bytes(payload)
    return path


def official_commitment_digest(
    *,
    commitment_domain: OfficialCommitmentDomain,
    stage: OfficialCommitmentStage,
    context: OfficialCommitmentContext,
    seed: bytes,
    nonce: bytes,
) -> str:
    """Commit secret bytes under a closed run family *and* lifecycle stage."""

    if type(commitment_domain) is not OfficialCommitmentDomain:
        raise ProtocolViolation("commitment domain must be OfficialCommitmentDomain")
    if type(stage) is not OfficialCommitmentStage:
        raise ProtocolViolation("commitment stage must be OfficialCommitmentStage")
    if type(context) is not OfficialCommitmentContext:
        raise ProtocolViolation("commitment context must be OfficialCommitmentContext")
    if commitment_domain is not context.commitment_domain:
        raise ProtocolViolation("commitment domain does not match context")
    if stage is not context.commitment_stage:
        raise ProtocolViolation("commitment stage does not match context")
    if type(seed) is not bytes or len(seed) != 32:
        raise ProtocolViolation("commitment seed must be exact 32-byte entropy")
    if type(nonce) is not bytes or len(nonce) < 16:
        raise ProtocolViolation(
            "commitment nonce must be exact bytes of at least 16 bytes"
        )
    return domain_digest(
        OFFICIAL_COMMITMENT_HASH_DOMAIN,
        [
            commitment_domain.value.encode("ascii"),
            stage.value.encode("ascii"),
            context.context_digest.encode("ascii"),
            seed,
            nonce,
        ],
    )


def train5_precommit_digest(artifact: Train5Precommit) -> str:
    if type(artifact) is not Train5Precommit:
        raise ProtocolViolation("TRAIN5 precommit artifact must be typed")
    return digest_bytes(artifact.to_bytes())


__all__ = [
    "COMMITMENT_CONTEXT_PROTOCOL",
    "EVALUATION_REPLICATE_IDS",
    "FROZEN_BENCHMARK_REVISION",
    "OFFICIAL_SEED_DOMAINS",
    "OFFICIAL_COMMITMENT_HASH_DOMAIN",
    "SEED_PROTOCOL_DIGEST",
    "SEED_PROTOCOL_MANIFEST_BYTES",
    "SEED_PROTOCOL_VERSION",
    "TRAIN5_PRECOMMIT_ARTIFACT_TYPE",
    "TRAIN5_PRECOMMIT_PROTOCOL",
    "TRAIN5_PRECOMMIT_STAGE",
    "TRAINING_REPLICATE_IDS",
    "ZIPPED_PAIRING_PROTOCOL",
    "ZIPPED_REPLICATE_IDS",
    "EvaluationSeedEntry",
    "EvaluationSeedPanel",
    "EvaluationSeedTuple",
    "OfficialCommitmentDomain",
    "OfficialCommitmentContext",
    "OfficialCommitmentStage",
    "OfficialSeedDomain",
    "Train5Precommit",
    "TrainingSeedEntry",
    "TrainingSeedPanel",
    "TrainingSeedTuple",
    "ZippedPairingAuthority",
    "official_commitment_digest",
    "parse_official_commitment_context_bytes",
    "parse_train5_precommit_bytes",
    "train5_precommit_digest",
    "write_train5_precommit",
]
