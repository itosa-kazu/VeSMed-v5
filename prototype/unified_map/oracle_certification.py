"""Executable certification for UCM benchmark counterfactual oracles.

The benchmark needs two *independently implemented* ways to answer every
oracle query.  A method label or a claimed ``absolute_error_bound`` is not
evidence of agreement.  This module therefore:

* invokes production and reference callables on the exact same public
  history, policy, horizon, and explicit oracle draw;
* compares a closed canonical semantic output recursively, using measured
  numeric errors and a frozen tolerance policy;
* fingerprints source/bytecode and both statically reachable and actually
  executed Python code, rejecting a shared substantive implementation;
* reruns both callables after swapping judge-private fields while holding the
  public history fixed, requiring byte-identical full outputs; and
* emits a closed, canonical, seed-commitment-only DTO suitable for inclusion
  in freeze-manifest metadata.

This is a judge-side audit API.  Its callable signature intentionally matches
``MicroWorld.counterfactual`` so that the metamorphic audit can expose a
malicious implementation that reads ``PrivateEpisode`` fields.  Passing this
audit is evidence that the probed calls did not depend on those fields; it is
not a capability boundary.  The candidate-facing API remains ``VisibleHistory``.
"""

from __future__ import annotations

import inspect
import math
import sys
import textwrap
import types
from dataclasses import dataclass
from typing import Any, Callable

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    domain_digest,
    validate_json_like,
)
from .schema import ActionPlan
from .worlds.base import CounterfactualOracle, PrivateEpisode


CERTIFICATION_PROTOCOL = "ucm-oracle-certification/1"
SEMANTIC_OUTPUT_PROTOCOL = "ucm-oracle-semantic-output/1"
FULL_OUTPUT_PROTOCOL = "ucm-oracle-full-output/1"

REASON_SOURCE_UNAVAILABLE = "OC-SOURCE-UNAVAILABLE"
REASON_ENTRY_IMPLEMENTATION_SHARED = "OC-ENTRY-IMPLEMENTATION-SHARED"
REASON_SOURCE_TEXT_SHARED = "OC-SOURCE-TEXT-SHARED"
REASON_RUNTIME_IMPLEMENTATION_SHARED = "OC-RUNTIME-IMPLEMENTATION-SHARED"
REASON_INVOCATION_FAILURE = "OC-INVOCATION-FAILURE"
REASON_OUTPUT_MISMATCH = "OC-OUTPUT-MISMATCH"
REASON_PRIVATE_SWAP_DEPENDENCE = "OC-PRIVATE-SWAP-DEPENDENCE"

HARNESS_INCOMPLETE_CODE = "UCM-E003-HARNESS_INCOMPLETE"

OracleCallable = Callable[
    [PrivateEpisode, ActionPlan, int, int], CounterfactualOracle
]


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _uint128(value: object, label: str) -> int:
    if type(value) is not int or value < 0 or value >= 2**128:
        raise ProtocolViolation(f"{label} must be an unsigned 128-bit integer")
    return value


def _finite_nonnegative(value: object, label: str) -> float:
    if type(value) not in {int, float}:
        raise ProtocolViolation(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ProtocolViolation(f"{label} must be finite and non-negative")
    return result


def _seed_digest(seed: int) -> str:
    """Commit to, but never serialize, a private oracle draw."""

    _uint128(seed, "oracle draw")
    return domain_digest(
        b"ucm-oracle-certification-draw-v1\0",
        [seed.to_bytes(16, "big", signed=False)],
    )


@dataclass(frozen=True, slots=True)
class PathTolerance:
    """A longest-prefix numeric tolerance override for a JSON path."""

    path_prefix: str
    absolute: float
    relative: float

    def __post_init__(self) -> None:
        _name(self.path_prefix, "path_prefix")
        if not (
            self.path_prefix == "$"
            or self.path_prefix.startswith("$.")
            or self.path_prefix.startswith("$[")
        ):
            raise ProtocolViolation("path_prefix must be a canonical rooted JSON path")
        object.__setattr__(
            self, "absolute", _finite_nonnegative(self.absolute, "absolute tolerance")
        )
        object.__setattr__(
            self, "relative", _finite_nonnegative(self.relative, "relative tolerance")
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "path_prefix": self.path_prefix,
            "absolute": self.absolute,
            "relative": self.relative,
        }


@dataclass(frozen=True, slots=True)
class NumericTolerance:
    absolute: float = 1e-9
    relative: float = 1e-9
    path_overrides: tuple[PathTolerance, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "absolute", _finite_nonnegative(self.absolute, "absolute tolerance")
        )
        object.__setattr__(
            self, "relative", _finite_nonnegative(self.relative, "relative tolerance")
        )
        if type(self.path_overrides) is not tuple or any(
            type(item) is not PathTolerance for item in self.path_overrides
        ):
            raise ProtocolViolation("path_overrides must be a tuple of PathTolerance")
        prefixes = [item.path_prefix for item in self.path_overrides]
        if len(prefixes) != len(set(prefixes)):
            raise ProtocolViolation("numeric tolerance path prefixes must be unique")
        if tuple(sorted(prefixes, key=lambda item: item.encode("utf-8"))) != tuple(
            prefixes
        ):
            raise ProtocolViolation("numeric tolerance overrides must be path-sorted")

    def for_path(self, path: str) -> tuple[float, float]:
        chosen: PathTolerance | None = None
        for item in self.path_overrides:
            prefix = item.path_prefix
            if path == prefix or path.startswith(prefix + ".") or path.startswith(
                prefix + "["
            ):
                if chosen is None or len(prefix) > len(chosen.path_prefix):
                    chosen = item
        if chosen is None:
            return self.absolute, self.relative
        return chosen.absolute, chosen.relative

    def to_wire(self) -> dict[str, Any]:
        return {
            "absolute": self.absolute,
            "relative": self.relative,
            "path_overrides": [item.to_wire() for item in self.path_overrides],
        }


@dataclass(frozen=True, slots=True)
class SourceSeparationPolicy:
    """Frozen rules for deciding which shared frames are neutral plumbing."""

    allowed_shared_module_prefixes: tuple[str, ...] = (
        "prototype.unified_map.oracle_certification",
        "collections",
        "dataclasses",
        "enum",
        "numpy",
    )
    # Project-owned modules are never neutral merely because of their module
    # name.  Only the exact DTO/canonical frames below may be shared by the two
    # solvers.  This prevents a substantive algorithm from being hidden inside
    # ``worlds.base`` or ``schema`` and then waived wholesale.
    allowed_shared_frames: tuple[tuple[str, str], ...] = (
        ("prototype.unified_map.canonical", "validate_json_like"),
        (
            "prototype.unified_map.canonical",
            "validate_json_like.<locals>.walk",
        ),
        (
            "prototype.unified_map.worlds.base",
            "__create_fn__.<locals>.__init__",
        ),
        (
            "prototype.unified_map.worlds.base",
            "CounterfactualOracle.__post_init__",
        ),
        (
            "prototype.unified_map.schema",
            "__create_fn__.<locals>.__init__",
        ),
        ("prototype.unified_map.schema", "ActionPlan.__post_init__"),
        ("prototype.unified_map.schema", "ActionPlan.to_wire"),
        # CPython 3.12 may lazily compile a regular expression while the
        # runtime observer is active.  This exact stdlib cache/compiler frame
        # is neutral plumbing; do not waive the whole ``re`` module because a
        # world-specific regex parser could otherwise hide substantive work.
        ("re", "_compile"),
    )
    allowed_shared_code_digests: tuple[str, ...] = ()
    require_source_text: bool = True
    reject_shared_runtime_code: bool = True

    def __post_init__(self) -> None:
        if type(self.allowed_shared_module_prefixes) is not tuple or any(
            type(item) is not str or not item
            for item in self.allowed_shared_module_prefixes
        ):
            raise ProtocolViolation(
                "allowed_shared_module_prefixes must be non-empty strings"
            )
        if type(self.allowed_shared_frames) is not tuple or any(
            type(item) is not tuple
            or len(item) != 2
            or any(type(value) is not str or not value for value in item)
            for item in self.allowed_shared_frames
        ):
            raise ProtocolViolation(
                "allowed_shared_frames must contain exact module/qualname pairs"
            )
        if len(self.allowed_shared_frames) != len(set(self.allowed_shared_frames)):
            raise ProtocolViolation("allowed_shared_frames must be unique")
        if type(self.allowed_shared_code_digests) is not tuple or any(
            type(item) is not str
            or not item.startswith("sha256:")
            or len(item) != 71
            for item in self.allowed_shared_code_digests
        ):
            raise ProtocolViolation(
                "allowed_shared_code_digests must be sha256-prefixed digests"
            )
        try:
            for item in self.allowed_shared_code_digests:
                int(item[7:], 16)
        except ValueError as exc:
            raise ProtocolViolation(
                "allowed_shared_code_digests must be hexadecimal"
            ) from exc
        if type(self.require_source_text) is not bool:
            raise ProtocolViolation("require_source_text must be boolean")
        if type(self.reject_shared_runtime_code) is not bool:
            raise ProtocolViolation("reject_shared_runtime_code must be boolean")

    def module_is_neutral(self, module: str) -> bool:
        return any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in self.allowed_shared_module_prefixes
        )

    def row_is_neutral(self, row: "CodeEvidence") -> bool:
        return self.module_is_neutral(row.module) or (
            row.module,
            row.qualname,
        ) in self.allowed_shared_frames

    def to_wire(self) -> dict[str, Any]:
        return {
            "allowed_shared_module_prefixes": list(
                self.allowed_shared_module_prefixes
            ),
            "allowed_shared_frames": [list(item) for item in self.allowed_shared_frames],
            "allowed_shared_code_digests": sorted(
                self.allowed_shared_code_digests
            ),
            "require_source_text": self.require_source_text,
            "reject_shared_runtime_code": self.reject_shared_runtime_code,
        }


@dataclass(frozen=True, slots=True)
class OracleProbe:
    probe_id: str
    episode: PrivateEpisode
    policy: ActionPlan
    horizon: int
    oracle_seed: int

    def __post_init__(self) -> None:
        _name(self.probe_id, "probe_id")
        if type(self.episode) is not PrivateEpisode:
            raise ProtocolViolation("probe episode must be PrivateEpisode")
        if type(self.policy) is not ActionPlan:
            raise ProtocolViolation("probe policy must be ActionPlan")
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ProtocolViolation("probe horizon must be a positive integer")
        _uint128(self.oracle_seed, "oracle_seed")


def _private_material(episode: PrivateEpisode) -> dict[str, Any]:
    return {
        "case_key": episode.case_key,
        "environment_key": episode.environment_key,
        "split": episode.split.value,
        "generator_draw": episode.generator_seed,
        "hidden_state_at_cut": episode.hidden_state_at_cut,
        "invariant_parameters": episode.invariant_parameters,
        "diagnostic_target": episode.diagnostic_target,
        "factual_future": episode.factual_future,
        "action_propensities": episode.action_propensities,
        "factual_utility": episode.factual_utility,
        "oracle_anchor": episode.oracle_anchor,
    }


@dataclass(frozen=True, slots=True)
class PrivateSwapProbe:
    probe_id: str
    first: PrivateEpisode
    swapped: PrivateEpisode
    policy: ActionPlan
    horizon: int
    oracle_seed: int

    def __post_init__(self) -> None:
        _name(self.probe_id, "private swap probe_id")
        if type(self.first) is not PrivateEpisode or type(self.swapped) is not PrivateEpisode:
            raise ProtocolViolation("private swap members must be PrivateEpisode")
        if self.first.public_history.digest != self.swapped.public_history.digest:
            raise ProtocolViolation(
                "private swap requires byte-equivalent public histories"
            )
        if digest_json(_private_material(self.first)) == digest_json(
            _private_material(self.swapped)
        ):
            raise ProtocolViolation(
                "private swap must change at least one judge-private field"
            )
        if type(self.policy) is not ActionPlan:
            raise ProtocolViolation("private swap policy must be ActionPlan")
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ProtocolViolation("private swap horizon must be positive")
        _uint128(self.oracle_seed, "private swap oracle_seed")


def oracle_output_wire(
    value: CounterfactualOracle, *, include_numerical_diagnostics: bool
) -> dict[str, Any]:
    """Convert an exact oracle DTO to a closed canonical comparison object."""

    if type(value) is not CounterfactualOracle:
        raise ProtocolViolation("oracle callable must return CounterfactualOracle")
    wire: dict[str, Any] = {
        "protocol": (
            FULL_OUTPUT_PROTOCOL
            if include_numerical_diagnostics
            else SEMANTIC_OUTPUT_PROTOCOL
        ),
        "policy": value.policy.to_wire(),
        "horizon": value.horizon,
        "observation_distribution": value.observation_distribution,
        "latent_distribution": value.latent_distribution,
        "outcome_distribution": value.outcome_distribution,
        "expected_utility": value.expected_utility,
    }
    if include_numerical_diagnostics:
        wire["numerical_diagnostics"] = value.numerical_diagnostics
    validate_json_like(wire)
    return wire


def _json_path_key(path: str, key: str) -> str:
    if key and all(character.isalnum() or character == "_" for character in key):
        return f"{path}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{path}['{escaped}']"


@dataclass(frozen=True, slots=True)
class NumericComparison:
    passed: bool
    numeric_values_compared: int
    numeric_mismatch_count: int
    structural_mismatch_count: int
    max_absolute_error: float
    max_relative_error: float
    mismatch_examples: tuple[dict[str, Any], ...]
    mismatch_examples_truncated: bool

    def to_wire(self) -> dict[str, Any]:
        wire = {
            "passed": self.passed,
            "numeric_values_compared": self.numeric_values_compared,
            "numeric_mismatch_count": self.numeric_mismatch_count,
            "structural_mismatch_count": self.structural_mismatch_count,
            "max_absolute_error": self.max_absolute_error,
            "max_relative_error": self.max_relative_error,
            "mismatch_examples": list(self.mismatch_examples),
            "mismatch_examples_truncated": self.mismatch_examples_truncated,
        }
        validate_json_like(wire)
        return wire


def compare_canonical_outputs(
    production: dict[str, Any],
    reference: dict[str, Any],
    tolerance: NumericTolerance,
    *,
    max_mismatch_examples: int = 64,
) -> NumericComparison:
    """Compare closed output trees and independently measure every error.

    No field in ``numerical_diagnostics`` influences this function.  In normal
    certification it receives semantic outputs from :func:`oracle_output_wire`,
    which omit those self-reported diagnostics entirely.
    """

    if type(production) is not dict or type(reference) is not dict:
        raise ProtocolViolation("canonical outputs must be exact dictionaries")
    if type(tolerance) is not NumericTolerance:
        raise ProtocolViolation("tolerance must be NumericTolerance")
    if type(max_mismatch_examples) is not int or max_mismatch_examples < 0:
        raise ProtocolViolation("max_mismatch_examples must be non-negative")
    validate_json_like(production, path="$.production")
    validate_json_like(reference, path="$.reference")

    numeric_count = 0
    numeric_mismatches = 0
    structural_mismatches = 0
    max_absolute = 0.0
    max_relative = 0.0
    examples: list[dict[str, Any]] = []

    def add_example(row: dict[str, Any]) -> None:
        if len(examples) < max_mismatch_examples:
            validate_json_like(row)
            examples.append(row)

    def walk(left: Any, right: Any, path: str) -> None:
        nonlocal numeric_count, numeric_mismatches, structural_mismatches
        nonlocal max_absolute, max_relative
        left_type = type(left)
        right_type = type(right)
        numeric_types = {int, float}

        if left_type in numeric_types and right_type in numeric_types:
            numeric_count += 1
            try:
                left_number = float(left)
                right_number = float(right)
            except OverflowError:
                structural_mismatches += 1
                add_example({"path": path, "kind": "numeric-overflow"})
                return
            if not math.isfinite(left_number) or not math.isfinite(right_number):
                # validate_json_like already rejects non-finite floats, but very
                # large integers can overflow during conversion.
                structural_mismatches += 1
                add_example({"path": path, "kind": "numeric-overflow"})
                return
            absolute_error = abs(left_number - right_number)
            scale = max(abs(left_number), abs(right_number))
            relative_error = 0.0 if absolute_error == 0.0 else absolute_error / scale
            absolute_tol, relative_tol = tolerance.for_path(path)
            allowed = absolute_tol + relative_tol * scale
            max_absolute = max(max_absolute, absolute_error)
            max_relative = max(max_relative, relative_error)
            if absolute_error > allowed:
                numeric_mismatches += 1
                add_example(
                    {
                        "path": path,
                        "kind": "numeric",
                        "absolute_error": absolute_error,
                        "relative_error": relative_error,
                        "allowed_error": allowed,
                    }
                )
            return

        if left_type is not right_type:
            structural_mismatches += 1
            add_example(
                {
                    "path": path,
                    "kind": "type",
                    "production_type": left_type.__name__,
                    "reference_type": right_type.__name__,
                }
            )
            return
        if left_type is dict:
            left_keys = set(left)
            right_keys = set(right)
            if left_keys != right_keys:
                structural_mismatches += 1
                add_example(
                    {
                        "path": path,
                        "kind": "keys",
                        "production_only": sorted(left_keys - right_keys),
                        "reference_only": sorted(right_keys - left_keys),
                    }
                )
            for key in sorted(left_keys & right_keys, key=lambda item: item.encode("utf-8")):
                walk(left[key], right[key], _json_path_key(path, key))
            return
        if left_type is list:
            if len(left) != len(right):
                structural_mismatches += 1
                add_example(
                    {
                        "path": path,
                        "kind": "length",
                        "production_length": len(left),
                        "reference_length": len(right),
                    }
                )
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                walk(left_item, right_item, f"{path}[{index}]")
            return
        if left != right:
            structural_mismatches += 1
            add_example(
                {
                    "path": path,
                    "kind": "value",
                    "production_value_digest": digest_json(left),
                    "reference_value_digest": digest_json(right),
                }
            )

    walk(production, reference, "$")
    mismatch_count = numeric_mismatches + structural_mismatches
    return NumericComparison(
        passed=mismatch_count == 0,
        numeric_values_compared=numeric_count,
        numeric_mismatch_count=numeric_mismatches,
        structural_mismatch_count=structural_mismatches,
        max_absolute_error=max_absolute,
        max_relative_error=max_relative,
        mismatch_examples=tuple(examples),
        mismatch_examples_truncated=mismatch_count > len(examples),
    )


def _constant_wire(value: Any) -> Any:
    kind = type(value)
    if value is None or kind in {bool, int, str}:
        return value
    if kind is float:
        return {"float": repr(value)}
    if kind is bytes:
        return {"bytes_digest": digest_bytes(value)}
    if kind is tuple:
        return {"tuple": [_constant_wire(item) for item in value]}
    if kind is frozenset:
        rows = [_constant_wire(item) for item in value]
        rows.sort(key=lambda item: canonical_json_bytes(item))
        return {"frozenset": rows}
    if kind is types.CodeType:
        return {"nested_code_digest": _code_digest(value)}
    if value is Ellipsis:
        return {"singleton": "ellipsis"}
    return {"constant_type": f"{kind.__module__}.{kind.__qualname__}"}


def _code_digest(code: types.CodeType) -> str:
    payload = {
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "flags": code.co_flags,
        "bytecode": code.co_code.hex(),
        "exception_table": getattr(code, "co_exceptiontable", b"").hex(),
        "constants": [_constant_wire(item) for item in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
    }
    return digest_json(payload)


def _source_digest(target: Any) -> str | None:
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        return None
    normalized = textwrap.dedent(source).replace("\r\n", "\n").encode("utf-8")
    return digest_bytes(normalized)


def _entry_function(callable_value: OracleCallable) -> types.FunctionType:
    if inspect.ismethod(callable_value):
        function = callable_value.__func__
    else:
        function = callable_value
    if not inspect.isfunction(function):
        raise ProtocolViolation(
            "oracle callable must be a Python function or bound Python method"
        )
    return function


@dataclass(frozen=True, slots=True)
class CodeEvidence:
    module: str
    qualname: str
    code_digest: str
    source_digest: str | None
    observed_at_runtime: bool
    statically_reachable: bool

    def to_wire(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "qualname": self.qualname,
            "code_digest": self.code_digest,
            "source_digest": self.source_digest,
            "observed_at_runtime": self.observed_at_runtime,
            "statically_reachable": self.statically_reachable,
        }


def _code_evidence_from_function(
    function: types.FunctionType,
    *,
    observed_at_runtime: bool,
    statically_reachable: bool,
) -> CodeEvidence:
    return CodeEvidence(
        module=function.__module__,
        qualname=function.__qualname__,
        code_digest=_code_digest(function.__code__),
        source_digest=_source_digest(function),
        observed_at_runtime=observed_at_runtime,
        statically_reachable=statically_reachable,
    )


def _static_function_graph(function: types.FunctionType) -> dict[str, CodeEvidence]:
    pending = [function]
    seen_objects: set[int] = set()
    rows: dict[str, CodeEvidence] = {}
    while pending:
        current = pending.pop()
        if id(current) in seen_objects:
            continue
        seen_objects.add(id(current))
        row = _code_evidence_from_function(
            current, observed_at_runtime=False, statically_reachable=True
        )
        rows[row.code_digest] = row
        for name in current.__code__.co_names:
            target = current.__globals__.get(name)
            if inspect.isfunction(target):
                pending.append(target)
        closure = current.__closure__ or ()
        for cell in closure:
            try:
                target = cell.cell_contents
            except ValueError:
                continue
            if inspect.isfunction(target):
                pending.append(target)
    return rows


def _frame_evidence(frame: types.FrameType) -> CodeEvidence:
    module = str(frame.f_globals.get("__name__", "<unknown>"))
    qualname = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
    return CodeEvidence(
        module=module,
        qualname=qualname,
        code_digest=_code_digest(frame.f_code),
        source_digest=_source_digest(frame.f_code),
        observed_at_runtime=True,
        statically_reachable=False,
    )


@dataclass(slots=True)
class _Invocation:
    success: bool
    semantic_wire: dict[str, Any] | None
    full_wire: dict[str, Any] | None
    semantic_digest: str | None
    full_digest: str | None
    declared_method: str | None
    method_digest: str | None
    diagnostics_digest: str | None
    error_type: str | None
    error_digest: str | None
    trace: dict[str, CodeEvidence]


def _invoke(
    callable_value: OracleCallable,
    probe_episode: PrivateEpisode,
    policy: ActionPlan,
    horizon: int,
    oracle_seed: int,
) -> _Invocation:
    trace: dict[str, CodeEvidence] = {}
    previous_profile = sys.getprofile()

    def profiler(frame: types.FrameType, event: str, arg: Any) -> None:
        if event == "call":
            row = _frame_evidence(frame)
            existing = trace.get(row.code_digest)
            if existing is None:
                trace[row.code_digest] = row
            elif not existing.observed_at_runtime:
                trace[row.code_digest] = CodeEvidence(
                    module=existing.module,
                    qualname=existing.qualname,
                    code_digest=existing.code_digest,
                    source_digest=existing.source_digest,
                    observed_at_runtime=True,
                    statically_reachable=existing.statically_reachable,
                )
        if previous_profile is not None:
            previous_profile(frame, event, arg)

    output: CounterfactualOracle | None = None
    caught: Exception | None = None
    try:
        sys.setprofile(profiler)
        output = callable_value(probe_episode, policy, horizon, oracle_seed)
    except Exception as exc:  # evidence row, not a harness crash
        caught = exc
    finally:
        sys.setprofile(previous_profile)

    if caught is not None:
        error_type = f"{type(caught).__module__}.{type(caught).__qualname__}"
        return _Invocation(
            success=False,
            semantic_wire=None,
            full_wire=None,
            semantic_digest=None,
            full_digest=None,
            declared_method=None,
            method_digest=None,
            diagnostics_digest=None,
            error_type=error_type,
            error_digest=domain_digest(
                b"ucm-oracle-certification-error-v1\0",
                [error_type.encode("utf-8"), str(caught).encode("utf-8")],
            ),
            trace=trace,
        )

    try:
        if type(output) is not CounterfactualOracle:
            raise ProtocolViolation("oracle callable returned the wrong DTO type")
        if canonical_json_bytes(output.policy.to_wire()) != canonical_json_bytes(
            policy.to_wire()
        ):
            raise ProtocolViolation("oracle output policy differs from query policy")
        if output.horizon != horizon:
            raise ProtocolViolation("oracle output horizon differs from query horizon")
        semantic = oracle_output_wire(output, include_numerical_diagnostics=False)
        full = oracle_output_wire(output, include_numerical_diagnostics=True)
        method = output.numerical_diagnostics.get("method")
        if type(method) is not str:
            method = None
        diagnostics_digest = digest_json(output.numerical_diagnostics)
        method_digest = digest_json(
            {
                "declared_method": method,
                "diagnostics_digest": diagnostics_digest,
            }
        )
        return _Invocation(
            success=True,
            semantic_wire=semantic,
            full_wire=full,
            semantic_digest=digest_json(semantic),
            full_digest=digest_json(full),
            declared_method=method,
            method_digest=method_digest,
            diagnostics_digest=diagnostics_digest,
            error_type=None,
            error_digest=None,
            trace=trace,
        )
    except Exception as exc:
        error_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
        return _Invocation(
            success=False,
            semantic_wire=None,
            full_wire=None,
            semantic_digest=None,
            full_digest=None,
            declared_method=None,
            method_digest=None,
            diagnostics_digest=None,
            error_type=error_type,
            error_digest=domain_digest(
                b"ucm-oracle-certification-error-v1\0",
                [error_type.encode("utf-8"), str(exc).encode("utf-8")],
            ),
            trace=trace,
        )


def _merge_code_rows(
    target: dict[str, CodeEvidence], source: dict[str, CodeEvidence]
) -> None:
    for digest, row in source.items():
        old = target.get(digest)
        if old is None:
            target[digest] = row
            continue
        target[digest] = CodeEvidence(
            module=old.module,
            qualname=old.qualname,
            code_digest=digest,
            source_digest=old.source_digest or row.source_digest,
            observed_at_runtime=old.observed_at_runtime or row.observed_at_runtime,
            statically_reachable=old.statically_reachable or row.statically_reachable,
        )


@dataclass(frozen=True, slots=True)
class ImplementationEvidence:
    role: str
    callable_module: str
    callable_qualname: str
    entry_source_digest: str | None
    entry_code_digest: str
    code_rows: tuple[CodeEvidence, ...]
    implementation_digest: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "callable_module": self.callable_module,
            "callable_qualname": self.callable_qualname,
            "entry_source_digest": self.entry_source_digest,
            "entry_code_digest": self.entry_code_digest,
            "code_rows": [row.to_wire() for row in self.code_rows],
            "implementation_digest": self.implementation_digest,
        }


def _implementation_evidence(
    role: str,
    function: types.FunctionType,
    rows: dict[str, CodeEvidence],
) -> ImplementationEvidence:
    entry_source = _source_digest(function)
    entry_code = _code_digest(function.__code__)
    ordered = tuple(
        sorted(
            rows.values(),
            key=lambda row: (
                row.code_digest,
                row.module.encode("utf-8"),
                row.qualname.encode("utf-8"),
            ),
        )
    )
    implementation_digest = digest_json(
        {
            "entry_source_digest": entry_source,
            "entry_code_digest": entry_code,
            "code_digests": [row.code_digest for row in ordered],
        }
    )
    return ImplementationEvidence(
        role=role,
        callable_module=function.__module__,
        callable_qualname=function.__qualname__,
        entry_source_digest=entry_source,
        entry_code_digest=entry_code,
        code_rows=ordered,
        implementation_digest=implementation_digest,
    )


@dataclass(frozen=True, slots=True)
class SourceSeparationEvidence:
    passed: bool
    reason_codes: tuple[str, ...]
    shared_substantive_code_digests: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason_codes": list(self.reason_codes),
            "shared_substantive_code_digests": list(
                self.shared_substantive_code_digests
            ),
        }


def _source_separation(
    production: ImplementationEvidence,
    reference: ImplementationEvidence,
    policy: SourceSeparationPolicy,
) -> SourceSeparationEvidence:
    reasons: list[str] = []
    if policy.require_source_text and (
        production.entry_source_digest is None
        or reference.entry_source_digest is None
    ):
        reasons.append(REASON_SOURCE_UNAVAILABLE)
    if production.entry_code_digest == reference.entry_code_digest:
        reasons.append(REASON_ENTRY_IMPLEMENTATION_SHARED)
    if (
        production.entry_source_digest is not None
        and production.entry_source_digest == reference.entry_source_digest
    ):
        reasons.append(REASON_SOURCE_TEXT_SHARED)

    production_rows = {row.code_digest: row for row in production.code_rows}
    reference_rows = {row.code_digest: row for row in reference.code_rows}
    allowed = set(policy.allowed_shared_code_digests)
    shared: list[str] = []
    for digest in sorted(set(production_rows) & set(reference_rows)):
        left = production_rows[digest]
        right = reference_rows[digest]
        if digest in allowed:
            continue
        if policy.row_is_neutral(left) and policy.row_is_neutral(right):
            continue
        shared.append(digest)
    if policy.reject_shared_runtime_code and shared:
        reasons.append(REASON_RUNTIME_IMPLEMENTATION_SHARED)
    return SourceSeparationEvidence(
        passed=not reasons,
        reason_codes=tuple(sorted(set(reasons))),
        shared_substantive_code_digests=tuple(shared),
    )


def _invocation_wire(invocation: _Invocation) -> dict[str, Any]:
    return {
        "success": invocation.success,
        "semantic_output_digest": invocation.semantic_digest,
        "full_output_digest": invocation.full_digest,
        "declared_method": invocation.declared_method,
        "method_digest": invocation.method_digest,
        "numerical_diagnostics_digest": invocation.diagnostics_digest,
        "error_type": invocation.error_type,
        "error_digest": invocation.error_digest,
    }


@dataclass(frozen=True, slots=True)
class ProbeCertification:
    probe_id: str
    public_history_digest: str
    policy_digest: str
    horizon: int
    oracle_seed_digest: str
    production: dict[str, Any]
    reference: dict[str, Any]
    comparison: NumericComparison | None
    passed: bool

    def to_wire(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "public_history_digest": self.public_history_digest,
            "policy_digest": self.policy_digest,
            "horizon": self.horizon,
            "oracle_seed_digest": self.oracle_seed_digest,
            "production": self.production,
            "reference": self.reference,
            "comparison": self.comparison.to_wire() if self.comparison else None,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class PrivateSwapCertification:
    probe_id: str
    public_history_digest: str
    policy_digest: str
    horizon: int
    oracle_seed_digest: str
    private_inputs_distinct: bool
    production_exact_invariant: bool
    reference_exact_invariant: bool
    production_first: dict[str, Any]
    production_swapped: dict[str, Any]
    reference_first: dict[str, Any]
    reference_swapped: dict[str, Any]
    passed: bool

    def to_wire(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "public_history_digest": self.public_history_digest,
            "policy_digest": self.policy_digest,
            "horizon": self.horizon,
            "oracle_seed_digest": self.oracle_seed_digest,
            "private_inputs_distinct": self.private_inputs_distinct,
            "production_exact_invariant": self.production_exact_invariant,
            "reference_exact_invariant": self.reference_exact_invariant,
            "production_first": self.production_first,
            "production_swapped": self.production_swapped,
            "reference_first": self.reference_first,
            "reference_swapped": self.reference_swapped,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class OracleCertificationReport:
    benchmark_id: str
    tolerance: NumericTolerance
    source_policy: SourceSeparationPolicy
    production_implementation: ImplementationEvidence
    reference_implementation: ImplementationEvidence
    source_separation: SourceSeparationEvidence
    probes: tuple[ProbeCertification, ...]
    private_swap_probes: tuple[PrivateSwapCertification, ...]
    reason_codes: tuple[str, ...]
    passed: bool
    harness_status: str

    def to_wire(self) -> dict[str, Any]:
        wire = {
            "protocol": CERTIFICATION_PROTOCOL,
            "benchmark_id": self.benchmark_id,
            "tolerance": self.tolerance.to_wire(),
            "source_policy": self.source_policy.to_wire(),
            "production_implementation": self.production_implementation.to_wire(),
            "reference_implementation": self.reference_implementation.to_wire(),
            "source_separation": self.source_separation.to_wire(),
            "probes": [probe.to_wire() for probe in self.probes],
            "private_swap_probes": [probe.to_wire() for probe in self.private_swap_probes],
            "reason_codes": list(self.reason_codes),
            "passed": self.passed,
            "harness_status": self.harness_status,
        }
        validate_json_like(wire)
        return wire

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


def certify_oracle_pair(
    *,
    benchmark_id: str,
    production: OracleCallable,
    reference: OracleCallable,
    probes: tuple[OracleProbe, ...],
    private_swap_probes: tuple[PrivateSwapProbe, ...],
    tolerance: NumericTolerance = NumericTolerance(),
    source_policy: SourceSeparationPolicy = SourceSeparationPolicy(),
) -> OracleCertificationReport:
    """Execute a complete production/reference and private-swap audit."""

    _name(benchmark_id, "benchmark_id")
    production_function = _entry_function(production)
    reference_function = _entry_function(reference)
    if type(probes) is not tuple or not probes or any(
        type(item) is not OracleProbe for item in probes
    ):
        raise ProtocolViolation("probes must be a non-empty tuple of OracleProbe")
    if type(private_swap_probes) is not tuple or not private_swap_probes or any(
        type(item) is not PrivateSwapProbe for item in private_swap_probes
    ):
        raise ProtocolViolation(
            "private_swap_probes must be a non-empty tuple of PrivateSwapProbe"
        )
    if type(tolerance) is not NumericTolerance:
        raise ProtocolViolation("tolerance must be NumericTolerance")
    if type(source_policy) is not SourceSeparationPolicy:
        raise ProtocolViolation("source_policy must be SourceSeparationPolicy")
    all_ids = [item.probe_id for item in probes] + [
        item.probe_id for item in private_swap_probes
    ]
    if len(all_ids) != len(set(all_ids)):
        raise ProtocolViolation("oracle certification probe IDs must be unique")

    production_rows = _static_function_graph(production_function)
    reference_rows = _static_function_graph(reference_function)
    certified_probes: list[ProbeCertification] = []
    swap_results: list[PrivateSwapCertification] = []
    reasons: set[str] = set()

    for probe in probes:
        production_result = _invoke(
            production,
            probe.episode,
            probe.policy,
            probe.horizon,
            probe.oracle_seed,
        )
        reference_result = _invoke(
            reference,
            probe.episode,
            probe.policy,
            probe.horizon,
            probe.oracle_seed,
        )
        _merge_code_rows(production_rows, production_result.trace)
        _merge_code_rows(reference_rows, reference_result.trace)
        comparison: NumericComparison | None = None
        if production_result.success and reference_result.success:
            assert production_result.semantic_wire is not None
            assert reference_result.semantic_wire is not None
            comparison = compare_canonical_outputs(
                production_result.semantic_wire,
                reference_result.semantic_wire,
                tolerance,
            )
            if not comparison.passed:
                reasons.add(REASON_OUTPUT_MISMATCH)
        else:
            reasons.add(REASON_INVOCATION_FAILURE)
        passed = (
            production_result.success
            and reference_result.success
            and comparison is not None
            and comparison.passed
        )
        certified_probes.append(
            ProbeCertification(
                probe_id=probe.probe_id,
                public_history_digest=probe.episode.public_history.digest,
                policy_digest=digest_json(probe.policy.to_wire()),
                horizon=probe.horizon,
                oracle_seed_digest=_seed_digest(probe.oracle_seed),
                production=_invocation_wire(production_result),
                reference=_invocation_wire(reference_result),
                comparison=comparison,
                passed=passed,
            )
        )

    for probe in private_swap_probes:
        production_first = _invoke(
            production, probe.first, probe.policy, probe.horizon, probe.oracle_seed
        )
        production_swapped = _invoke(
            production, probe.swapped, probe.policy, probe.horizon, probe.oracle_seed
        )
        reference_first = _invoke(
            reference, probe.first, probe.policy, probe.horizon, probe.oracle_seed
        )
        reference_swapped = _invoke(
            reference, probe.swapped, probe.policy, probe.horizon, probe.oracle_seed
        )
        for invocation in (production_first, production_swapped):
            _merge_code_rows(production_rows, invocation.trace)
        for invocation in (reference_first, reference_swapped):
            _merge_code_rows(reference_rows, invocation.trace)
        production_invariant = (
            production_first.success
            and production_swapped.success
            and production_first.full_digest == production_swapped.full_digest
        )
        reference_invariant = (
            reference_first.success
            and reference_swapped.success
            and reference_first.full_digest == reference_swapped.full_digest
        )
        if not all(
            invocation.success
            for invocation in (
                production_first,
                production_swapped,
                reference_first,
                reference_swapped,
            )
        ):
            reasons.add(REASON_INVOCATION_FAILURE)
        if not production_invariant or not reference_invariant:
            reasons.add(REASON_PRIVATE_SWAP_DEPENDENCE)
        swap_results.append(
            PrivateSwapCertification(
                probe_id=probe.probe_id,
                public_history_digest=probe.first.public_history.digest,
                policy_digest=digest_json(probe.policy.to_wire()),
                horizon=probe.horizon,
                oracle_seed_digest=_seed_digest(probe.oracle_seed),
                private_inputs_distinct=True,
                production_exact_invariant=production_invariant,
                reference_exact_invariant=reference_invariant,
                production_first=_invocation_wire(production_first),
                production_swapped=_invocation_wire(production_swapped),
                reference_first=_invocation_wire(reference_first),
                reference_swapped=_invocation_wire(reference_swapped),
                passed=production_invariant and reference_invariant,
            )
        )

    production_evidence = _implementation_evidence(
        "production", production_function, production_rows
    )
    reference_evidence = _implementation_evidence(
        "reference", reference_function, reference_rows
    )
    separation = _source_separation(
        production_evidence, reference_evidence, source_policy
    )
    reasons.update(separation.reason_codes)
    all_passed = (
        separation.passed
        and all(item.passed for item in certified_probes)
        and all(item.passed for item in swap_results)
    )
    report = OracleCertificationReport(
        benchmark_id=benchmark_id,
        tolerance=tolerance,
        source_policy=source_policy,
        production_implementation=production_evidence,
        reference_implementation=reference_evidence,
        source_separation=separation,
        probes=tuple(certified_probes),
        private_swap_probes=tuple(swap_results),
        reason_codes=tuple(sorted(reasons)),
        passed=all_passed,
        harness_status="PASS" if all_passed else HARNESS_INCOMPLETE_CODE,
    )
    # This is the final closed-schema/freeze-embeddability boundary.  No raw
    # private draw is serialized; every draw appears only as a domain digest.
    report.canonical_bytes
    return report


__all__ = [
    "CERTIFICATION_PROTOCOL",
    "HARNESS_INCOMPLETE_CODE",
    "NumericComparison",
    "NumericTolerance",
    "OracleCertificationReport",
    "OracleProbe",
    "PathTolerance",
    "PrivateSwapProbe",
    "SourceSeparationPolicy",
    "certify_oracle_pair",
    "compare_canonical_outputs",
    "oracle_output_wire",
]
