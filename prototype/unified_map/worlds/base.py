"""Candidate-neutral contracts shared by all executable microworlds."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..canonical import ProtocolViolation, digest_json, validate_json_like
from ..schema import (
    ActionPlan,
    JudgePrivateCase,
    TrainerOnlyTargets,
    TrainingExample,
    VisibleHistory,
)


def _name(value: object, label: str) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a non-empty canonical string")


def _range(value: tuple[float, float] | None, label: str) -> None:
    if value is None:
        return
    if (
        type(value) is not tuple
        or len(value) != 2
        or any(type(item) not in {int, float} for item in value)
        or value[0] > value[1]
    ):
        raise ProtocolViolation(f"{label} must be an ordered numeric pair")


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    channel_id: str
    value_type: str = "continuous"
    unit: str = "normalized"
    valid_range: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        _name(self.channel_id, "channel_id")
        if self.value_type not in {"continuous", "binary", "categorical"}:
            raise ProtocolViolation("unsupported channel value_type")
        _name(self.unit, "unit")
        _range(self.valid_range, "channel valid_range")

    def to_wire(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "value_type": self.value_type,
            "unit": self.unit,
            "valid_range": list(self.valid_range) if self.valid_range else None,
        }


@dataclass(frozen=True, slots=True)
class ActionSpec:
    action_id: str
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0

    def __post_init__(self) -> None:
        _name(self.action_id, "action_id")
        if type(self.parameter_schema) is not dict:
            raise ProtocolViolation("parameter_schema must be an exact dict")
        validate_json_like(self.parameter_schema)
        if type(self.cost) not in {int, float}:
            raise ProtocolViolation("action cost must be numeric")
        validate_json_like(self.cost)

    def to_wire(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "parameter_schema": self.parameter_schema,
            "cost": self.cost,
        }


@dataclass(frozen=True, slots=True)
class CheckSpec:
    check_id: str
    result_channels: tuple[str, ...]
    delay_support: tuple[int, int]
    cost: float = 0.0

    def __post_init__(self) -> None:
        _name(self.check_id, "check_id")
        if type(self.result_channels) is not tuple or not self.result_channels:
            raise ProtocolViolation("check result_channels must be non-empty")
        for channel in self.result_channels:
            _name(channel, "check result channel")
        if (
            type(self.delay_support) is not tuple
            or len(self.delay_support) != 2
            or any(type(value) is not int or value < 0 for value in self.delay_support)
            or self.delay_support[0] > self.delay_support[1]
        ):
            raise ProtocolViolation("delay_support must be ordered non-negative ticks")
        if type(self.cost) not in {int, float}:
            raise ProtocolViolation("check cost must be numeric")
        validate_json_like(self.cost)

    def to_wire(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "result_channels": list(self.result_channels),
            "delay_support": list(self.delay_support),
            "cost": self.cost,
        }


@dataclass(frozen=True, slots=True)
class PublicCatalog:
    observations: tuple[ChannelSpec, ...]
    actions: tuple[ActionSpec, ...]
    checks: tuple[CheckSpec, ...]
    diagnostic_labels: tuple[str, ...]
    horizons: tuple[int, ...]
    time_unit: str = "tick"

    def __post_init__(self) -> None:
        for values, kind in (
            (self.observations, ChannelSpec),
            (self.actions, ActionSpec),
            (self.checks, CheckSpec),
        ):
            if type(values) is not tuple or any(type(item) is not kind for item in values):
                raise ProtocolViolation(f"catalog {kind.__name__} values must be a tuple")
        identifiers = [item.channel_id for item in self.observations]
        identifiers += [item.action_id for item in self.actions]
        identifiers += [item.check_id for item in self.checks]
        if len(identifiers) != len(set(identifiers)):
            raise ProtocolViolation("catalog identifiers must be globally unique")
        for check in self.checks:
            missing = set(check.result_channels) - {
                item.channel_id for item in self.observations
            }
            if missing:
                raise ProtocolViolation(
                    f"check references unknown channels: {sorted(missing)!r}"
                )
        if type(self.diagnostic_labels) is not tuple or not self.diagnostic_labels:
            raise ProtocolViolation("diagnostic_labels must be non-empty")
        for label in self.diagnostic_labels:
            _name(label, "diagnostic label")
        if len(self.diagnostic_labels) != len(set(self.diagnostic_labels)):
            raise ProtocolViolation("diagnostic labels must be unique")
        if (
            type(self.horizons) is not tuple
            or not self.horizons
            or any(type(horizon) is not int or horizon <= 0 for horizon in self.horizons)
            or tuple(sorted(set(self.horizons))) != self.horizons
        ):
            raise ProtocolViolation("horizons must be sorted unique positive integers")
        _name(self.time_unit, "time_unit")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-public-catalog/1",
            "observations": [item.to_wire() for item in self.observations],
            "actions": [item.to_wire() for item in self.actions],
            "checks": [item.to_wire() for item in self.checks],
            "diagnostic_labels": list(self.diagnostic_labels),
            "horizons": list(self.horizons),
            "time_unit": self.time_unit,
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


class WorldSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    SEALED_TEST = "sealed_test"


@dataclass(frozen=True, slots=True)
class PrivateEpisode:
    """One complete judge-side unit; only projections cross candidate walls."""

    case_key: str
    environment_key: str
    split: WorldSplit
    generator_seed: int
    public_history: VisibleHistory
    hidden_state_at_cut: dict[str, Any]
    invariant_parameters: dict[str, Any]
    diagnostic_target: dict[str, float]
    factual_future: list[dict[str, Any]]
    action_propensities: list[dict[str, Any]]
    factual_utility: float
    oracle_anchor: dict[str, Any]

    def __post_init__(self) -> None:
        for value, label in (
            (self.case_key, "case_key"),
            (self.environment_key, "environment_key"),
        ):
            _name(value, label)
        if type(self.split) is not WorldSplit:
            raise ProtocolViolation("episode split must be WorldSplit")
        if type(self.generator_seed) is not int or self.generator_seed < 0:
            raise ProtocolViolation("generator_seed must be a non-negative integer")
        if type(self.public_history) is not VisibleHistory:
            raise ProtocolViolation("public_history must be VisibleHistory")
        for value in (
            self.hidden_state_at_cut,
            self.invariant_parameters,
            self.diagnostic_target,
            self.factual_future,
            self.action_propensities,
            self.oracle_anchor,
        ):
            validate_json_like(value)
        validate_json_like(self.factual_utility)

    def training_example(self) -> TrainingExample:
        return TrainingExample(
            history=self.public_history,
            targets=TrainerOnlyTargets(
                diagnostic_target=self.diagnostic_target,
                factual_future=self.factual_future,
                action_propensities=self.action_propensities,
                factual_utility=self.factual_utility,
            ),
        )

    def judge_case(self) -> JudgePrivateCase:
        return JudgePrivateCase(
            case_key=self.case_key,
            environment_key=self.environment_key,
            split=self.split.value,
            generator_seed=self.generator_seed,
            public_history=self.public_history,
            hidden_state={
                "state_at_cut": self.hidden_state_at_cut,
                "parameters": self.invariant_parameters,
            },
            oracle_targets={"anchor": self.oracle_anchor},
        )


@dataclass(frozen=True, slots=True)
class CounterfactualOracle:
    policy: ActionPlan
    horizon: int
    observation_distribution: dict[str, Any]
    latent_distribution: dict[str, Any]
    outcome_distribution: dict[str, Any]
    expected_utility: float
    numerical_diagnostics: dict[str, Any]

    def __post_init__(self) -> None:
        if type(self.policy) is not ActionPlan:
            raise ProtocolViolation("oracle policy must be ActionPlan")
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ProtocolViolation("oracle horizon must be positive")
        for value in (
            self.observation_distribution,
            self.latent_distribution,
            self.outcome_distribution,
            self.numerical_diagnostics,
        ):
            validate_json_like(value)
        validate_json_like(self.expected_utility)


class MicroWorld(ABC):
    """A complete executable world with a private oracle."""

    @property
    @abstractmethod
    def environment_key(self) -> str:
        """Judge-only key.  It must never enter a candidate request."""

    @property
    @abstractmethod
    def catalog(self) -> PublicCatalog:
        """Candidate-visible semantic catalog without an evaluation ID."""

    @abstractmethod
    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        """Generate one deterministic episode and its factual training record."""

    @abstractmethod
    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        """Return every policy that the v1 oracle must score."""

    @abstractmethod
    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        """Return a distribution under do(policy), never a factual condition."""
