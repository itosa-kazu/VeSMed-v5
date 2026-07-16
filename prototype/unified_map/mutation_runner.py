"""Execute the currently portable UCM mutation controls into matrix evidence.

Only observed detector outcomes are converted to kill records.  The static
mapping below selects which already-executed gate is decisive; it never turns
a crash, timeout, missing failure code, or unrelated rejection into a kill.
The resulting content-addressed raw bundle contains the recomputed partial
matrix and remains intentionally HARNESS_INCOMPLETE until all public benchmark
mutants and specificity controls have real executions.
"""

from __future__ import annotations

import builtins
import dis
import inspect
import platform
import sys
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from functools import lru_cache
from pathlib import PurePosixPath
from types import CodeType
from typing import Any

from .candidate_protocol import (
    _delta_from_wire,
    _diagnosis_query_from_wire,
    _history_from_wire,
    _rollout_query_from_wire,
)
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from .compliance import (
    PORTABLE_SEMANTIC_PROBE_PROTOCOL,
    ComplianceFinding,
    ComplianceVerdict,
    control_entrypoint,
    evaluate_candidate_compliance,
)
from .mutation_matrix import (
    MutationObservation,
    ObservationOutcome,
    SubjectKind,
    evaluate_mutation_matrix,
)
from .mutation_evidence import (
    BENCHMARK_ID,
    MutationEvidenceBuilder,
    MutationEvidenceBundle,
    portable_runner_contract,
)
from .schema import DiagnosisQuery, RolloutQuery, VisibleDelta, VisibleHistory


RUNNER_PROTOCOL = "ucm-portable-mutation-runner/17"


def _runtime_metadata() -> dict[str, Any]:
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "byteorder": sys.byteorder,
    }


def _registered_runtime_reference(value: Any, label: str) -> dict[str, Any]:
    anchors = globals().get("_SOURCE_IDENTITY_ANCHORS")
    if type(anchors) is dict:
        for anchor_name, expected in anchors.get(
            "external_runtime_objects", {}
        ).items():
            if value is expected:
                return {
                    "kind": "anchored-runtime-object",
                    "anchor": anchor_name,
                    "type": f"{type(value).__module__}.{type(value).__qualname__}",
                    "identity_verified": True,
                }
    value_type = type(value)
    module_name = getattr(value_type, "__module__", None)
    if type(module_name) is not str:
        raise ProtocolViolation(f"unowned runtime value for {label}")
    owner = sys.modules.get(module_name)
    if owner is None:
        raise ProtocolViolation(f"unregistered runtime owner for {label}")
    aliases = sorted(
        name for name, candidate in vars(owner).items() if candidate is value
    )
    if not aliases:
        raise ProtocolViolation(f"runtime singleton has no registered alias for {label}")
    safe_singletons = {
        ("dataclasses", "MISSING"),
        ("dataclasses", "_HAS_DEFAULT_FACTORY"),
    }
    if not any((module_name, alias) in safe_singletons for alias in aliases):
        raise ProtocolViolation(f"unsafe runtime object for {label}")
    return {
        "kind": "registered-reference",
        "owner": module_name,
        "aliases": aliases,
        "type": f"{value_type.__module__}.{value_type.__qualname__}",
    }


def _registered_class_binding(value: Any, label: str) -> dict[str, Any]:
    if not inspect.isclass(value):
        raise ProtocolViolation(f"runtime value is not a class for {label}")
    # Bypass an attacker-controlled metaclass ``__getattribute__``.  A class
    # entering the source transcript must be described by the actual type
    # slots, not by strings synthesized by its metaclass.
    module_name = type.__getattribute__(value, "__module__")
    if type(module_name) is not str:
        raise ProtocolViolation(f"runtime class has no owner for {label}")
    owner = sys.modules.get(module_name)
    if owner is None:
        raise ProtocolViolation(f"unregistered runtime class owner for {label}")
    aliases = sorted(
        f"{module_name}.{name}"
        for name, candidate in vars(owner).items()
        if candidate is value
    )
    anchors = globals().get("_SOURCE_IDENTITY_ANCHORS")
    if type(anchors) is dict:
        for logical_name, rows in anchors["aliases"].items():
            anchor_module = anchors["modules"][logical_name]
            aliases.extend(
                f"{anchor_module.__name__}.{name}"
                for name, (kind, candidate) in rows.items()
                if kind == "class" and candidate is value
            )
        aliases = sorted(set(aliases))
    if not aliases:
        raise ProtocolViolation(f"runtime class has no registered owner alias for {label}")
    qualname = type.__getattribute__(value, "__qualname__")
    if type(qualname) is not str:
        raise ProtocolViolation(f"runtime class has malformed qualname for {label}")

    def descriptor(candidate: type, where: str) -> dict[str, Any]:
        candidate_module = type.__getattribute__(candidate, "__module__")
        candidate_qualname = type.__getattribute__(candidate, "__qualname__")
        if type(candidate_module) is not str or type(candidate_qualname) is not str:
            raise ProtocolViolation(f"malformed class dependency for {where}")
        candidate_owner = sys.modules.get(candidate_module)
        if candidate_owner is None:
            raise ProtocolViolation(f"unregistered class dependency for {where}")
        candidate_aliases = sorted(
            f"{candidate_module}.{name}"
            for name, item in vars(candidate_owner).items()
            if item is candidate
        )
        if type(anchors) is dict:
            for logical_name, rows in anchors["aliases"].items():
                anchor_module = anchors["modules"][logical_name]
                candidate_aliases.extend(
                    f"{anchor_module.__name__}.{name}"
                    for name, (kind, item) in rows.items()
                    if kind == "class" and item is candidate
                )
            candidate_aliases = sorted(set(candidate_aliases))
        if not candidate_aliases:
            raise ProtocolViolation(f"class dependency has no owner alias for {where}")
        return {
            "owner": candidate_module,
            "qualname": candidate_qualname,
            "aliases": candidate_aliases,
        }

    metaclass = type(value)
    mro = type.__getattribute__(value, "__mro__")
    if type(mro) is not tuple or any(not inspect.isclass(base) for base in mro):
        raise ProtocolViolation(f"runtime class has malformed MRO for {label}")
    return {
        "kind": "class",
        "owner": module_name,
        "qualname": qualname,
        "aliases": aliases,
        "metaclass": descriptor(metaclass, f"{label}.metaclass"),
        "mro": [
            descriptor(base, f"{label}.__mro__[{index}]")
            for index, base in enumerate(mro)
        ],
    }


def _stable_code_constant_binding(
    value: Any,
    label: str,
    *,
    _seen: set[int],
    _depth: int,
) -> Any:
    """Bind exact Python code constants without ``marshal`` or ``repr``.

    ``marshal.dumps(code)`` is an interpreter serialization detail and is not
    a stable semantic transcript.  Code constants have a deliberately narrow
    set of compiler-produced types; anything outside that set fails closed.
    """

    if _depth > 32:
        raise ProtocolViolation(f"code constant depth exceeded for {label}")
    kind = type(value)
    if value is None or kind in {bool, int, str}:
        return value
    if kind is float:
        return value
    if kind is complex:
        return {
            "kind": "complex",
            "real": value.real,
            "imag": value.imag,
        }
    if kind is bytes:
        return {
            "kind": "bytes",
            "length": len(value),
            "digest": digest_bytes(value),
        }
    if value is Ellipsis:
        return {"kind": "ellipsis"}
    if value is NotImplemented:
        return {"kind": "not-implemented"}
    if kind in {tuple, frozenset}:
        identity = id(value)
        if identity in _seen:
            raise ProtocolViolation(f"cyclic code constant for {label}")
        _seen.add(identity)
        try:
            items = [
                _stable_code_constant_binding(
                    item,
                    f"{label}[{index}]",
                    _seen=_seen,
                    _depth=_depth + 1,
                )
                for index, item in enumerate(value)
            ]
            if kind is frozenset:
                items.sort(key=digest_json)
            return {"kind": kind.__name__, "items": items}
        finally:
            _seen.remove(identity)
    if kind is CodeType:
        return _stable_code_binding(
            value,
            label,
            _seen=_seen,
            _depth=_depth + 1,
        )
    raise ProtocolViolation(
        f"unsupported code constant {kind.__module__}.{kind.__qualname__} "
        f"for {label}"
    )


def _stable_code_binding(
    code: CodeType,
    label: str,
    *,
    _seen: set[int] | None = None,
    _depth: int = 0,
) -> dict[str, Any]:
    """Canonicalize an exact code object independently of adaptive caches."""

    if type(code) is not CodeType:
        raise ProtocolViolation(f"runtime value is not an exact code object for {label}")
    if _depth > 32:
        raise ProtocolViolation(f"code binding depth exceeded for {label}")
    if _seen is None:
        _seen = set()
    identity = id(code)
    if identity in _seen:
        raise ProtocolViolation(f"cyclic code object for {label}")
    _seen.add(identity)
    try:
        try:
            instructions = []
            for instruction in dis.get_instructions(
                code, adaptive=False, show_caches=False
            ):
                positions = instruction.positions
                instructions.append(
                    {
                        "opname": instruction.opname,
                        "arg": instruction.arg,
                        "offset": instruction.offset,
                        "starts_line": instruction.starts_line,
                        "is_jump_target": instruction.is_jump_target,
                        "positions": (
                            None
                            if positions is None
                            else [
                                positions.lineno,
                                positions.end_lineno,
                                positions.col_offset,
                                positions.end_col_offset,
                            ]
                        ),
                    }
                )
        except Exception as exc:
            raise ProtocolViolation(
                f"cannot canonicalize code instructions for {label}: "
                f"{type(exc).__name__}"
            ) from exc
        return {
            "kind": "code",
            "argcount": code.co_argcount,
            "posonlyargcount": code.co_posonlyargcount,
            "kwonlyargcount": code.co_kwonlyargcount,
            "nlocals": code.co_nlocals,
            "stacksize": code.co_stacksize,
            "flags": code.co_flags,
            "name": code.co_name,
            "qualname": code.co_qualname,
            # Absolute checkout/runtime paths are packaging details, not live
            # semantics.  Module source bytes and the normalized basename bind
            # the implementation without making evidence host-specific.
            "filename": code.co_filename.replace("\\", "/").rsplit("/", 1)[-1],
            "firstlineno": code.co_firstlineno,
            "names": list(code.co_names),
            "varnames": list(code.co_varnames),
            "freevars": list(code.co_freevars),
            "cellvars": list(code.co_cellvars),
            "constants": [
                _stable_code_constant_binding(
                    constant,
                    f"{label}.co_consts[{index}]",
                    _seen=_seen,
                    _depth=_depth + 1,
                )
                for index, constant in enumerate(code.co_consts)
            ],
            "linetable_digest": digest_bytes(code.co_linetable),
            "exceptiontable_digest": digest_bytes(code.co_exceptiontable),
            "instructions": instructions,
        }
    finally:
        _seen.remove(identity)


def _static_wrapped_value(value: Any, label: str) -> tuple[bool, Any]:
    """Return an explicitly stored ``__wrapped__`` link.

    Python functions and the standard callable wrappers used by this harness
    keep the link in their instance dictionary.  Refusing inherited/dynamic
    descriptors prevents an attacker-controlled property from being executed
    while the binding transcript is built.
    """

    try:
        namespace = vars(value)
    except TypeError:
        namespace = {}
    if type(namespace) is not dict:
        return False, None
    if "__wrapped__" not in namespace:
        return False, None
    return True, namespace["__wrapped__"]


def _is_bindable_callable(value: Any, label: str) -> bool:
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    if inspect.isfunction(value):
        code = value.__code__
        if type(code) is not CodeType:
            raise ProtocolViolation(f"malformed callable code for {label}")
        return True
    has_wrapped, _ = _static_wrapped_value(value, label)
    return has_wrapped


def _code_global_names(code: CodeType, label: str) -> tuple[str, ...]:
    """Return globals read by *code*, including nested code constants.

    Looking at ``co_names`` alone incorrectly treats attribute names as module
    globals.  The non-adaptive instruction stream is both precise and stable
    after CPython quickening, and walking nested code closes dependencies used
    by comprehensions and inner functions.
    """

    if type(code) is not CodeType:
        raise ProtocolViolation(f"runtime value is not an exact code object for {label}")
    pending = [code]
    seen: set[int] = set()
    names: set[str] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            instructions = dis.get_instructions(
                current, adaptive=False, show_caches=False
            )
            for instruction in instructions:
                if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}:
                    if type(instruction.argval) is not str:
                        raise ProtocolViolation(
                            f"malformed global instruction for {label}"
                        )
                    names.add(instruction.argval)
        except ProtocolViolation:
            raise
        except Exception as exc:
            raise ProtocolViolation(
                f"cannot inspect global dependencies for {label}: "
                f"{type(exc).__name__}"
            ) from exc
        pending.extend(
            constant
            for constant in current.co_consts
            if type(constant) is CodeType
        )
    return tuple(sorted(names))


def _code_stored_global_names(code: CodeType, label: str) -> tuple[str, ...]:
    """Return module slots explicitly mutated by a callable or nested code."""

    if type(code) is not CodeType:
        raise ProtocolViolation(f"runtime value is not an exact code object for {label}")
    pending = [code]
    seen: set[int] = set()
    names: set[str] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            for instruction in dis.get_instructions(
                current, adaptive=False, show_caches=False
            ):
                if instruction.opname in {"STORE_GLOBAL", "DELETE_GLOBAL"}:
                    if type(instruction.argval) is not str:
                        raise ProtocolViolation(
                            f"malformed stored-global instruction for {label}"
                        )
                    names.add(instruction.argval)
        except ProtocolViolation:
            raise
        except Exception as exc:
            raise ProtocolViolation(
                f"cannot inspect stored globals for {label}: "
                f"{type(exc).__name__}"
            ) from exc
        pending.extend(
            constant
            for constant in current.co_consts
            if type(constant) is CodeType
        )
    return tuple(sorted(names))


@lru_cache(maxsize=64)
def _stored_global_names_for_codes(codes: tuple[CodeType, ...]) -> frozenset[str]:
    names: set[str] = set()
    for index, code in enumerate(codes):
        names.update(_code_stored_global_names(code, f"module-code[{index}]"))
    return frozenset(names)


def _module_live_codes(globals_mapping: dict[str, Any]) -> tuple[CodeType, ...]:
    codes: list[CodeType] = []
    for candidate in globals_mapping.values():
        if inspect.isfunction(candidate) and candidate.__globals__ is globals_mapping:
            codes.append(candidate.__code__)
            continue
        if not inspect.isclass(candidate):
            continue
        for member in vars(candidate).values():
            if isinstance(member, (staticmethod, classmethod)):
                member = member.__func__
            method_candidates = (
                (member.fget, member.fset, member.fdel)
                if isinstance(member, property)
                else (member,)
            )
            codes.extend(
                method_candidate.__code__
                for method_candidate in method_candidates
                if inspect.isfunction(method_candidate)
                and method_candidate.__globals__ is globals_mapping
            )
    # Sorting by stable code semantics would redo the expensive work this cache
    # avoids.  Namespace insertion order is deterministic for a loaded module;
    # a monkeypatch changes at least one object/code key and therefore the cache
    # key regardless of position.
    return tuple(codes)


def _registered_callable_reference(value: Any, label: str) -> dict[str, Any]:
    """Describe a referenced callable without recursively expanding its graph.

    Every Python function alias in the benchmark modules is independently
    included by :func:`_live_module_code_binding`.  A shallow edge here closes
    the dependency graph while avoiding false cycles between mutually
    recursive helpers.
    """

    module_name = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if type(module_name) is not str or type(qualname) is not str:
        raise ProtocolViolation(f"unowned callable dependency for {label}")
    owner = sys.modules.get(module_name)
    if owner is None:
        raise ProtocolViolation(f"unregistered callable owner for {label}")
    aliases = sorted(
        name for name, candidate in vars(owner).items() if candidate is value
    )
    bound_module_aliases: list[str] | None = None
    implementation = "bound-by-live-module-alias"
    if not aliases and "<locals>" not in qualname:
        # An imported Python function can remain a live dependency after its
        # defining-module alias is replaced.  Permit that narrow case only when
        # the function is demonstrably defined by the canonical owner globals
        # and still has an identity alias in an anchored source module.  Such
        # aliases are independently expanded by ``_live_module_code_binding``.
        # Builtins and arbitrary sys.modules consumers do not get this fallback.
        if not inspect.isfunction(value) or value.__globals__ is not vars(owner):
            raise ProtocolViolation(
                f"callable dependency has no owner alias for {label}"
            )
        anchors = globals().get("_SOURCE_IDENTITY_ANCHORS")
        bound_modules = (
            anchors.get("modules") if type(anchors) is dict else None
        )
        if type(bound_modules) is not dict:
            raise ProtocolViolation(f"malformed source module anchors for {label}")
        anchored_owner = False
        for anchored_module in bound_modules.values():
            anchored_name = getattr(anchored_module, "__name__", None)
            if (
                anchored_module is owner
                and anchored_name == module_name
                and sys.modules.get(anchored_name) is anchored_module
            ):
                anchored_owner = True
                break
        if not anchored_owner:
            raise ProtocolViolation(
                f"callable dependency has no anchored owner for {label}"
            )
        discovered: set[str] = set()
        for bound_module in bound_modules.values():
            bound_name = getattr(bound_module, "__name__", None)
            if (
                type(bound_name) is not str
                or sys.modules.get(bound_name) is not bound_module
            ):
                raise ProtocolViolation(f"unregistered source module anchor for {label}")
            discovered.update(
                f"{bound_name}.{name}"
                for name, candidate in vars(bound_module).items()
                if candidate is value
            )
        if not discovered:
            raise ProtocolViolation(
                f"callable dependency has no owner alias for {label}"
            )
        bound_module_aliases = sorted(discovered)
        implementation = "bound-by-live-import-alias"
    # Nested closure functions need not have a module alias: the containing
    # callable binds their code/defaults/closure directly.  A referenced
    # module-global callable, however, must have either its authoritative owner
    # alias or the narrowly verified anchored-import alias above.
    code = getattr(value, "__code__", None)
    if code is not None and type(code) is not CodeType:
        raise ProtocolViolation(f"malformed callable dependency for {label}")
    binding = {
        "kind": "callable-reference",
        "owner": module_name,
        "qualname": qualname,
        "aliases": aliases,
        "implementation": implementation,
    }
    if bound_module_aliases is not None:
        binding["bound_module_aliases"] = bound_module_aliases
    return binding


def _module_reference_binding(value: Any, label: str) -> dict[str, Any]:
    name = getattr(value, "__name__", None)
    if type(name) is not str or sys.modules.get(name) is not value:
        raise ProtocolViolation(f"foreign module value for {label}")
    return {
        "kind": "module-reference",
        "name": name,
        "package": getattr(value, "__package__", None),
    }


def _global_dependency_binding(
    value: Any,
    label: str,
    *,
    mutable_slot: bool,
    _seen: set[int],
    _depth: int,
) -> Any:
    """Bind one resolved global edge without executing dynamic descriptors."""

    if inspect.ismodule(value):
        return _module_reference_binding(value, label)
    if inspect.isclass(value):
        return _registered_class_binding(value, label)
    if inspect.isfunction(value) or inspect.isbuiltin(value):
        return _registered_callable_reference(value, label)
    if mutable_slot:
        # The identity and name of a process-local cache are source semantics;
        # its patient-dependent contents are execution state and must not make
        # an otherwise identical source digest change after a run.
        return {
            "kind": "mutable-runtime-global-slot",
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
        }
    return _runtime_value_binding(
        value,
        label,
        _seen=_seen,
        _depth=_depth + 1,
    )


def _resolved_global_dependencies(
    code: CodeType,
    globals_mapping: dict[str, Any],
    label: str,
    *,
    _seen: set[int],
    _depth: int,
) -> dict[str, Any]:
    """Resolve every live ``LOAD_GLOBAL`` edge against module/builtins state."""

    # Mutation and warm-cache controls often store a global in one method and
    # read it in another.  Determine mutability from the whole owning module,
    # not only from the current function.  The code-tuple cache invalidates on
    # every live function replacement.
    stored_names = _stored_global_names_for_codes(
        _module_live_codes(globals_mapping)
    )
    builtins_value = globals_mapping.get("__builtins__", builtins)
    if inspect.ismodule(builtins_value):
        if builtins_value is not builtins:
            raise ProtocolViolation(f"foreign builtins module for {label}")
        builtins_mapping = vars(builtins)
    elif type(builtins_value) is dict:
        if builtins_value is not vars(builtins):
            raise ProtocolViolation(f"foreign builtins mapping for {label}")
        builtins_mapping = builtins_value
    else:
        raise ProtocolViolation(f"malformed builtins binding for {label}")

    dependencies: dict[str, Any] = {}
    for name in _code_global_names(code, label):
        if name in globals_mapping:
            dependencies[name] = {
                "resolution": "module-global",
                "binding": _global_dependency_binding(
                    globals_mapping[name],
                    f"{label}.globals[{name}]",
                    mutable_slot=(
                        name in stored_names or name == "_SOURCE_IDENTITY_ANCHORS"
                    ),
                    _seen=_seen,
                    _depth=_depth + 1,
                ),
            }
            continue
        if name not in builtins_mapping:
            # A missing global is semantically meaningful: calling that path
            # raises NameError.  Preserve it rather than silently omitting it.
            dependencies[name] = {"resolution": "missing"}
            continue
        builtin_value = builtins_mapping[name]
        canonical_builtin = vars(builtins).get(name)
        if builtin_value is not canonical_builtin:
            raise ProtocolViolation(f"rewritten builtin dependency {name!r} for {label}")
        dependencies[name] = {
            "resolution": "builtins",
            "binding": (
                _registered_class_binding(builtin_value, f"{label}.builtins[{name}]")
                if inspect.isclass(builtin_value)
                else _registered_callable_reference(
                    builtin_value, f"{label}.builtins[{name}]"
                )
                if inspect.isbuiltin(builtin_value)
                else _runtime_value_binding(
                    builtin_value,
                    f"{label}.builtins[{name}]",
                    _seen=_seen,
                    _depth=_depth + 1,
                )
            ),
        }
    return dependencies


def _runtime_value_binding(
    value: Any,
    label: str,
    *,
    _seen: set[int] | None = None,
    _depth: int = 0,
) -> Any:
    """Canonicalize live defaults, closures and frozen registries.

    Unsupported custom objects and cycles fail closed rather than falling back
    to ``repr`` (which may execute code or contain process-specific addresses).
    """

    if _depth > 32:
        raise ProtocolViolation(f"runtime binding depth exceeded for {label}")
    kind = type(value)
    if value is None or kind in {bool, int, str}:
        return value
    if value is Ellipsis:
        return {"kind": "ellipsis"}
    if value is NotImplemented:
        return {"kind": "not-implemented"}
    if kind is float:
        # digest_json performs the finite-value check.
        return value
    if kind is complex:
        return {"kind": "complex", "real": value.real, "imag": value.imag}
    if kind is bytes:
        return {
            "kind": "bytes",
            "length": len(value),
            "digest": digest_bytes(value),
        }
    anchors = globals().get("_SOURCE_IDENTITY_ANCHORS")
    if type(anchors) is dict:
        external_aliases = sorted(
            name
            for name, expected in anchors.get(
                "external_attributes", {}
            ).items()
            if value is expected
        )
        if external_aliases:
            return {
                "kind": "anchored-external-attribute-reference",
                "anchors": external_aliases,
                "owner": getattr(value, "__module__", None),
                "qualname": getattr(value, "__qualname__", None),
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
            }
        surface_aliases: list[str] = []
        for surface_name, surface in anchors.get(
            "external_class_surfaces", {}
        ).items():
            if value is surface.get("class"):
                surface_aliases.append(surface_name)
            for descriptor_name, (_, descriptor) in surface.get(
                "descriptors", {}
            ).items():
                if value is descriptor:
                    surface_aliases.append(descriptor_name)
        if surface_aliases:
            return {
                "kind": "anchored-external-class-surface-reference",
                "anchors": sorted(set(surface_aliases)),
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
            }
    if isinstance(value, Enum):
        return {
            "kind": "enum-member",
            "enum": _registered_class_binding(
                type(value), f"{label}.enum_class"
            ),
            "name": value.name,
            "value": _runtime_value_binding(
                value.value,
                f"{label}.value",
                _seen=_seen,
                _depth=_depth + 1,
            ),
        }
    if inspect.ismodule(value):
        registered = sys.modules.get(value.__name__)
        if registered is not value:
            raise ProtocolViolation(f"foreign module value for {label}")
        return {"kind": "module", "name": value.__name__}
    if inspect.isclass(value):
        return _registered_class_binding(value, label)
    if inspect.isbuiltin(value):
        return _registered_callable_reference(value, label)
    if inspect.isfunction(value) or _is_bindable_callable(value, label):
        return _live_callable_binding(
            value,
            label,
            _seen=_seen,
            _depth=_depth + 1,
        )

    if _seen is None:
        _seen = set()
    tracked = kind in {tuple, list, dict, set, frozenset} or is_dataclass(value)
    if tracked:
        identity = id(value)
        if identity in _seen:
            raise ProtocolViolation(f"cyclic runtime value for {label}")
        _seen.add(identity)
    try:
        if kind in {tuple, list}:
            return {
                "kind": kind.__name__,
                "items": [
                    _runtime_value_binding(
                        item,
                        f"{label}[{index}]",
                        _seen=_seen,
                        _depth=_depth + 1,
                    )
                    for index, item in enumerate(value)
                ],
            }
        if kind in {set, frozenset}:
            items = [
                _runtime_value_binding(
                    item,
                    f"{label}[]",
                    _seen=_seen,
                    _depth=_depth + 1,
                )
                for item in value
            ]
            return {
                "kind": kind.__name__,
                "items": sorted(items, key=digest_json),
            }
        if kind is dict:
            entries = [
                {
                    "key": _runtime_value_binding(
                        key,
                        f"{label}.key",
                        _seen=_seen,
                        _depth=_depth + 1,
                    ),
                    "value": _runtime_value_binding(
                        item,
                        f"{label}.value",
                        _seen=_seen,
                        _depth=_depth + 1,
                    ),
                }
                for key, item in value.items()
            ]
            return {"kind": "dict", "entries": sorted(entries, key=digest_json)}
        if is_dataclass(value) and not inspect.isclass(value):
            return {
                "kind": "dataclass",
                "type": _registered_class_binding(
                    kind, f"{label}.dataclass_type"
                ),
                "fields": {
                    field.name: _runtime_value_binding(
                        getattr(value, field.name),
                        f"{label}.{field.name}",
                        _seen=_seen,
                        _depth=_depth + 1,
                    )
                    for field in fields(value)
                },
            }
        return _registered_runtime_reference(value, label)
    finally:
        if tracked:
            _seen.remove(id(value))


def _live_callable_binding(
    value: Any,
    label: str,
    *,
    _seen: set[int] | None = None,
    _depth: int = 0,
    _bind_global_dependencies: bool = True,
) -> dict[str, Any]:
    if _depth > 32:
        raise ProtocolViolation(f"live callable binding depth exceeded for {label}")
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    code = getattr(value, "__code__", None)
    if code is not None and type(code) is not CodeType:
        raise ProtocolViolation(f"malformed live callable code for {label}")
    has_wrapped, wrapped = _static_wrapped_value(value, label)
    if code is None and not has_wrapped:
        raise ProtocolViolation(f"cannot bind live detector code for {label}")
    if _seen is None:
        _seen = set()
    callable_identity = id(value)
    if callable_identity in _seen:
        raise ProtocolViolation(f"cyclic live callable reference for {label}")
    _seen.add(callable_identity)
    globals_mapping = getattr(value, "__globals__", None) if code is not None else None
    globals_owner: str | None = None
    global_dependencies: dict[str, Any] | None = None
    try:
        if globals_mapping is not None:
            if type(globals_mapping) is not dict:
                raise ProtocolViolation(
                    f"live callable globals are malformed for {label}"
                )
            globals_owner_value = globals_mapping.get("__name__")
            if type(globals_owner_value) is not str:
                raise ProtocolViolation(
                    f"live callable globals lack an owner for {label}"
                )
            registered_owner = sys.modules.get(globals_owner_value)
            if (
                registered_owner is None
                or vars(registered_owner) is not globals_mapping
            ):
                raise ProtocolViolation(
                    f"live callable uses foreign globals for {label}"
                )
            globals_owner = globals_owner_value
            if _bind_global_dependencies:
                global_dependencies = _resolved_global_dependencies(
                    code,
                    globals_mapping,
                    label,
                    _seen=_seen,
                    _depth=_depth + 1,
                )
        closure_binding: list[Any] | None = None
        if code is not None:
            closure = getattr(value, "__closure__", None)
            if closure is not None:
                closure_binding = []
                for index, cell in enumerate(closure):
                    try:
                        cell_value = cell.cell_contents
                    except ValueError:
                        closure_binding.append({"kind": "empty-cell"})
                        continue
                    closure_binding.append(
                        _runtime_value_binding(
                            cell_value,
                            f"{label}.closure[{index}]",
                            _seen=_seen,
                            _depth=_depth + 1,
                        )
                    )
        wrapper_instance_state: Any = None
        callable_class: Any = None
        if code is None:
            callable_class = _registered_class_binding(
                type(value), f"{label}.callable_class"
            )
            wrapper_instance_state = _runtime_value_binding(
                {
                    key: item
                    for key, item in vars(value).items()
                    if key != "__wrapped__"
                },
                f"{label}.wrapper_state",
                _seen=_seen,
                _depth=_depth + 1,
            )
        wrapped_binding = (
            _live_callable_binding(
                wrapped,
                f"{label}.__wrapped__",
                _seen=_seen,
                _depth=_depth + 1,
                _bind_global_dependencies=_bind_global_dependencies,
            )
            if has_wrapped
            else None
        )
        return {
            "kind": "live-callable",
            "qualname": getattr(value, "__qualname__", None),
            "code": (
                _stable_code_binding(code, f"{label}.__code__")
                if code is not None
                else None
            ),
            "globals_owner": globals_owner,
            "global_dependencies": global_dependencies,
            "defaults": (
                _runtime_value_binding(
                    getattr(value, "__defaults__", None),
                    f"{label}.__defaults__",
                    _seen=_seen,
                    _depth=_depth + 1,
                )
                if code is not None
                else None
            ),
            "kwdefaults": (
                _runtime_value_binding(
                    getattr(value, "__kwdefaults__", None),
                    f"{label}.__kwdefaults__",
                    _seen=_seen,
                    _depth=_depth + 1,
                )
                if code is not None
                else None
            ),
            "closure": closure_binding,
            "callable_class": callable_class,
            "wrapper_instance_state": wrapper_instance_state,
            "wrapped": wrapped_binding,
        }
    finally:
        _seen.remove(callable_identity)


def _live_callable_digest(
    value: Any,
    label: str,
    *,
    _bind_global_dependencies: bool = True,
) -> str:
    return digest_json(
        _live_callable_binding(
            value,
            label,
            _bind_global_dependencies=_bind_global_dependencies,
        )
    )


def _live_module_code_binding(module: Any) -> dict[str, Any]:
    """Bind every live Python function alias and locally-defined class method.

    Module source alone does not bind monkeypatched globals.  Including all
    callable aliases also captures transitive parsers/adjudicators imported by
    the runner rather than relying on an inevitably incomplete hand list.
    """

    functions: dict[str, str] = {}
    classes: dict[str, dict[str, str]] = {}
    bound_module_names = {
        value.__name__
        for value in _SOURCE_IDENTITY_ANCHORS["modules"].values()
    }
    for name, value in sorted(vars(module).items()):
        if _is_bindable_callable(value, f"{module.__name__}.{name}"):
            function_globals = getattr(value, "__globals__", None)
            function_owner = (
                function_globals.get("__name__")
                if type(function_globals) is dict
                else None
            )
            functions[name] = _live_callable_digest(
                value,
                f"{module.__name__}.{name}",
                _bind_global_dependencies=function_owner in bound_module_names,
            )
        if not inspect.isclass(value) or value.__module__ != module.__name__:
            continue
        methods: dict[str, str] = {}
        for method_name, member in sorted(vars(value).items()):
            candidates: list[tuple[str, Any]] = [(method_name, member)]
            if isinstance(member, property):
                candidates = [
                    (f"{method_name}.fget", member.fget),
                    (f"{method_name}.fset", member.fset),
                    (f"{method_name}.fdel", member.fdel),
                ]
            for label, candidate in candidates:
                if candidate is None:
                    continue
                unwrapped_candidate = (
                    candidate.__func__
                    if isinstance(candidate, (staticmethod, classmethod))
                    else candidate
                )
                candidate_code = getattr(unwrapped_candidate, "__code__", None)
                if (
                    is_dataclass(value)
                    and type(candidate_code) is CodeType
                    and (
                        candidate_code.co_filename == "<string>"
                        or candidate_code.co_filename.replace("\\", "/").endswith(
                            "/dataclasses.py"
                        )
                    )
                ):
                    # Slot dataclasses retain a stale pre-slots class in some
                    # generated closures, so the ordinary closure walker cannot
                    # safely bind them.  The executable code/defaults still
                    # affect the live protocol, however, and must not disappear
                    # from the transcript merely because dataclasses generated
                    # them.  Bind those executable parts explicitly while the
                    # module source/runtime metadata bind the generator itself.
                    methods[label] = digest_json(
                        {
                            "kind": "generated-dataclass-method",
                            "code": _stable_code_binding(
                                candidate_code,
                                (
                                    f"{module.__name__}."
                                    f"{value.__qualname__}.{label}.__code__"
                                ),
                            ),
                            "defaults": _runtime_value_binding(
                                getattr(unwrapped_candidate, "__defaults__", None),
                                (
                                    f"{module.__name__}."
                                    f"{value.__qualname__}.{label}.__defaults__"
                                ),
                            ),
                            "kwdefaults": _runtime_value_binding(
                                getattr(unwrapped_candidate, "__kwdefaults__", None),
                                (
                                    f"{module.__name__}."
                                    f"{value.__qualname__}.{label}.__kwdefaults__"
                                ),
                            ),
                        }
                    )
                    continue
                if _is_bindable_callable(
                    candidate,
                    f"{module.__name__}.{value.__qualname__}.{label}",
                ):
                    methods[label] = _live_callable_digest(
                        candidate,
                        f"{module.__name__}.{value.__qualname__}.{label}",
                    )
        if methods:
            classes[value.__qualname__] = methods
    return {"functions": functions, "classes": classes}


def _external_class_surface(value: type, label: str) -> dict[str, tuple[str, Any]]:
    """Capture every executable/dispatch descriptor on a trusted class MRO."""

    if not inspect.isclass(value):
        raise ProtocolViolation(f"external trust surface is not a class: {label}")
    rows: dict[str, tuple[str, Any]] = {}
    for base in type.__getattribute__(value, "__mro__"):
        base_module = type.__getattribute__(base, "__module__")
        base_qualname = type.__getattribute__(base, "__qualname__")
        for name, descriptor in vars(base).items():
            if type(descriptor) is staticmethod:
                kind = "staticmethod"
            elif type(descriptor) is classmethod:
                kind = "classmethod"
            elif type(descriptor) is property:
                kind = "property"
            elif inspect.isfunction(descriptor):
                kind = "function"
            elif inspect.isbuiltin(descriptor):
                kind = "builtin"
            elif inspect.ismethoddescriptor(descriptor):
                kind = "method-descriptor"
            else:
                continue
            rows[f"{base_module}.{base_qualname}.{name}"] = (kind, descriptor)
    if not rows:
        raise ProtocolViolation(f"external trust surface is empty: {label}")
    return rows


def _external_python_global_roots(
    class_surfaces: dict[str, dict[str, Any]],
    external_attributes: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the transitive direct globals of trusted external Python code.

    Arbitrary module state is not serialized here.  The resulting objects are
    retained only as import-time identity/code anchors, which covers dispatch
    roots such as ``tempfile.mkdtemp`` without trying to canonicalize mutable
    stdlib singletons (locks, encoders, weak sets, compiled regexes, ...).
    """

    pending: list[Any] = []
    for surface in class_surfaces.values():
        for kind, descriptor in surface["descriptors"].values():
            if kind in {"staticmethod", "classmethod"}:
                descriptor = descriptor.__func__
            if type(descriptor) is property:
                pending.extend(
                    accessor
                    for accessor in (descriptor.fget, descriptor.fset, descriptor.fdel)
                    if inspect.isfunction(accessor)
                )
            elif inspect.isfunction(descriptor):
                pending.append(descriptor)
    pending.extend(
        value for value in external_attributes.values() if inspect.isfunction(value)
    )

    seen_functions: set[int] = set()
    roots: dict[str, Any] = {}
    while pending:
        function = pending.pop()
        identity = id(function)
        if identity in seen_functions:
            continue
        seen_functions.add(identity)
        globals_mapping = function.__globals__
        module_name = globals_mapping.get("__name__")
        if type(module_name) is not str:
            raise ProtocolViolation("external Python callable has no module name")
        for name in _code_global_names(
            function.__code__, f"external-global-root.{module_name}"
        ):
            if name not in globals_mapping:
                continue
            value = globals_mapping[name]
            roots[f"{module_name}.{name}"] = value
            if inspect.isfunction(value) and id(value) not in seen_functions:
                pending.append(value)
        if len(roots) > 4096 or len(seen_functions) > 4096:
            raise ProtocolViolation("external Python global closure exceeds limit")
    return roots


def _nested_external_dispatch_roots(candidate_protocol: Any) -> dict[str, Any]:
    """Return platform/module attribute dispatch roots hidden behind globals."""

    roots: dict[str, Any] = {}

    def add(label: str, owner: Any, attribute: str) -> None:
        if owner is not None and hasattr(owner, attribute):
            roots[label] = getattr(owner, attribute)

    add("tempfile.mkdtemp", candidate_protocol.tempfile, "mkdtemp")
    add(
        "threading._start_joinable_thread",
        candidate_protocol.threading,
        "_start_joinable_thread",
    )
    add(
        "threading._start_new_thread",
        candidate_protocol.threading,
        "_start_new_thread",
    )
    add("subprocess._fork_exec", candidate_protocol.subprocess, "_fork_exec")
    winapi = getattr(candidate_protocol.subprocess, "_winapi", None)
    add("subprocess._winapi.CreateProcess", winapi, "CreateProcess")
    pathlib_module = sys.modules.get(candidate_protocol.Path.__module__)
    pathlib_io = getattr(pathlib_module, "io", None)
    add("pathlib.io.open", pathlib_io, "open")
    add("os.path.realpath", candidate_protocol.os.path, "realpath")
    add("json._default_encoder", candidate_protocol.json, "_default_encoder")
    return roots


def _capture_source_identity_anchors() -> dict[str, Any]:
    """Snapshot clean module/class aliases once, during module import.

    Qualified names are not identity: an Enum or executor clone can copy the
    original name, MRO, methods and even synchronize every consumer alias.
    Object identity itself is intentionally *not* serialized (it is process
    specific); it is used only to produce a stable verified contract or fail
    closed before attacker-controlled metaclass behavior is inspected.
    """

    from . import (
        candidate_protocol,
        canonical,
        compliance,
        mutation_evidence,
        mutation_matrix,
        schema,
        state,
    )

    # ``tempfile`` resolves its default directory and creates its process-wide
    # candidate-name sequence lazily.
    # Source-witness construction itself uses ``TemporaryDirectory`` while
    # preparing the bound runtime inventory, so capturing ``_name_sequence``
    # as ``None`` would make the first legitimate witness change the anchored
    # stdlib roots and every later witness fail closed.  Initialize both values
    # before any external Python-global identities are captured.  Merely
    # obtaining the shared iterator does not consume a candidate name.
    candidate_protocol.tempfile.gettempdir()
    candidate_protocol.tempfile._get_candidate_names()

    runner_module = sys.modules.get(__name__)
    if runner_module is None:
        raise ProtocolViolation("cannot capture mutation runner identity anchor")
    modules = {
        "canonical": canonical,
        "candidate_protocol": candidate_protocol,
        "compliance": compliance,
        "mutation_evidence": mutation_evidence,
        "mutation_matrix": mutation_matrix,
        "schema": schema,
        "state": state,
        "mutation_runner": runner_module,
    }
    aliases: dict[str, dict[str, tuple[str, Any]]] = {}
    for logical_name, module in modules.items():
        module_aliases: dict[str, tuple[str, Any]] = {}
        for alias, value in vars(module).items():
            if inspect.ismodule(value):
                module_aliases[alias] = ("module", value)
            elif inspect.isclass(value):
                module_aliases[alias] = ("class", value)
        aliases[logical_name] = module_aliases
    # Module identity alone does not bind attributes resolved at call time.
    # These call sites are freeze-critical: replacing one can change process
    # launch, inventory scope/path normalization, snapshot materialization, or
    # semantic comparison without changing the consumer module's Python
    # source/code object.
    concrete_path_type = type(candidate_protocol.Path.cwd())
    external_class_surfaces = {
        "candidate_protocol.subprocess.Popen": {
            "class": candidate_protocol.subprocess.Popen,
            "descriptors": _external_class_surface(
                candidate_protocol.subprocess.Popen, "subprocess.Popen"
            ),
        },
        "candidate_protocol.threading.Thread": {
            "class": candidate_protocol.threading.Thread,
            "descriptors": _external_class_surface(
                candidate_protocol.threading.Thread, "threading.Thread"
            ),
        },
        "candidate_protocol.queue.Queue": {
            "class": candidate_protocol.queue.Queue,
            "descriptors": _external_class_surface(
                candidate_protocol.queue.Queue, "queue.Queue"
            ),
        },
        "candidate_protocol.tempfile.TemporaryDirectory": {
            "class": candidate_protocol.tempfile.TemporaryDirectory,
            "descriptors": _external_class_surface(
                candidate_protocol.tempfile.TemporaryDirectory,
                "tempfile.TemporaryDirectory",
            ),
        },
        "candidate_protocol.Path": {
            "class": candidate_protocol.Path,
            "descriptors": _external_class_surface(
                candidate_protocol.Path, "pathlib.Path"
            ),
        },
        "candidate_protocol.concrete_Path": {
            "class": concrete_path_type,
            "descriptors": _external_class_surface(
                concrete_path_type, "concrete pathlib.Path"
            ),
        },
    }
    external_attributes = {
        "candidate_protocol.subprocess.Popen": candidate_protocol.subprocess.Popen,
        "candidate_protocol.subprocess.Popen.__new__": (
            candidate_protocol.subprocess.Popen.__new__
        ),
        "candidate_protocol.subprocess.Popen.__init__": (
            candidate_protocol.subprocess.Popen.__init__
        ),
        "candidate_protocol.subprocess.Popen.wait": (
            candidate_protocol.subprocess.Popen.wait
        ),
        "candidate_protocol.subprocess.Popen.poll": (
            candidate_protocol.subprocess.Popen.poll
        ),
        "candidate_protocol.subprocess.Popen.kill": (
            candidate_protocol.subprocess.Popen.kill
        ),
        "candidate_protocol.subprocess.Popen.terminate": (
            candidate_protocol.subprocess.Popen.terminate
        ),
        "candidate_protocol.subprocess.TimeoutExpired": (
            candidate_protocol.subprocess.TimeoutExpired
        ),
        "candidate_protocol.threading.Lock": candidate_protocol.threading.Lock,
        "candidate_protocol.threading.Thread": candidate_protocol.threading.Thread,
        "candidate_protocol.threading.Thread.__new__": (
            candidate_protocol.threading.Thread.__new__
        ),
        "candidate_protocol.threading.Thread.__init__": (
            candidate_protocol.threading.Thread.__init__
        ),
        "candidate_protocol.threading.Thread.start": (
            candidate_protocol.threading.Thread.start
        ),
        "candidate_protocol.threading.Thread.join": (
            candidate_protocol.threading.Thread.join
        ),
        "candidate_protocol.threading.Thread.is_alive": (
            candidate_protocol.threading.Thread.is_alive
        ),
        "candidate_protocol.queue.Queue": candidate_protocol.queue.Queue,
        "candidate_protocol.queue.Queue.__new__": (
            candidate_protocol.queue.Queue.__new__
        ),
        "candidate_protocol.queue.Queue.__init__": (
            candidate_protocol.queue.Queue.__init__
        ),
        "candidate_protocol.queue.Queue.put": candidate_protocol.queue.Queue.put,
        "candidate_protocol.queue.Queue.get": candidate_protocol.queue.Queue.get,
        "candidate_protocol.queue.Queue.get_nowait": (
            candidate_protocol.queue.Queue.get_nowait
        ),
        "candidate_protocol.queue.Empty": candidate_protocol.queue.Empty,
        "candidate_protocol.tempfile.TemporaryDirectory": (
            candidate_protocol.tempfile.TemporaryDirectory
        ),
        "candidate_protocol.tempfile.TemporaryDirectory.__new__": (
            candidate_protocol.tempfile.TemporaryDirectory.__new__
        ),
        "candidate_protocol.tempfile.TemporaryDirectory.__init__": (
            candidate_protocol.tempfile.TemporaryDirectory.__init__
        ),
        "candidate_protocol.tempfile.TemporaryDirectory.__enter__": (
            candidate_protocol.tempfile.TemporaryDirectory.__enter__
        ),
        "candidate_protocol.tempfile.TemporaryDirectory.__exit__": (
            candidate_protocol.tempfile.TemporaryDirectory.__exit__
        ),
        "candidate_protocol.sysconfig.get_paths": (
            candidate_protocol.sysconfig.get_paths
        ),
        "candidate_protocol.sysconfig.get_config_var": (
            candidate_protocol.sysconfig.get_config_var
        ),
        "candidate_protocol.os.fspath": candidate_protocol.os.fspath,
        "candidate_protocol.os.fsdecode": candidate_protocol.os.fsdecode,
        "candidate_protocol.os.path.normcase": candidate_protocol.os.path.normcase,
        "candidate_protocol.os.open": candidate_protocol.os.open,
        "candidate_protocol.os.write": candidate_protocol.os.write,
        "candidate_protocol.os.fsync": candidate_protocol.os.fsync,
        "candidate_protocol.os.close": candidate_protocol.os.close,
        "candidate_protocol.os.dup": candidate_protocol.os.dup,
        "candidate_protocol.os.dup2": candidate_protocol.os.dup2,
        "candidate_protocol.os.read": candidate_protocol.os.read,
        "candidate_protocol.os.pipe": candidate_protocol.os.pipe,
        "candidate_protocol.os.urandom": candidate_protocol.os.urandom,
        "candidate_protocol.Path.__new__": candidate_protocol.Path.__new__,
        "candidate_protocol.Path.read_bytes": candidate_protocol.Path.read_bytes,
        "candidate_protocol.Path.open": candidate_protocol.Path.open,
        "candidate_protocol.Path.stat": candidate_protocol.Path.stat,
        "candidate_protocol.Path.resolve": candidate_protocol.Path.resolve,
        "candidate_protocol.Path.relative_to": candidate_protocol.Path.relative_to,
        "candidate_protocol.Path.as_posix": candidate_protocol.Path.as_posix,
        "candidate_protocol.Path.is_file": candidate_protocol.Path.is_file,
        "candidate_protocol.Path.is_dir": candidate_protocol.Path.is_dir,
        "candidate_protocol.Path.is_symlink": candidate_protocol.Path.is_symlink,
        "candidate_protocol.Path.mkdir": candidate_protocol.Path.mkdir,
        "candidate_protocol.Path.write_bytes": candidate_protocol.Path.write_bytes,
        "candidate_protocol.Path.chmod": candidate_protocol.Path.chmod,
        "candidate_protocol.Path.cwd.__func__": candidate_protocol.Path.cwd.__func__,
        "candidate_protocol.Path.exists": candidate_protocol.Path.exists,
        "candidate_protocol.Path.is_absolute": candidate_protocol.Path.is_absolute,
        "candidate_protocol.Path.joinpath": candidate_protocol.Path.joinpath,
        "candidate_protocol.Path.with_suffix": candidate_protocol.Path.with_suffix,
        "candidate_protocol.Path.__truediv__": candidate_protocol.Path.__truediv__,
        "candidate_protocol.Path.__fspath__": candidate_protocol.Path.__fspath__,
        "candidate_protocol.Path.__str__": candidate_protocol.Path.__str__,
        "candidate_protocol.Path.parents": candidate_protocol.Path.parents,
        "candidate_protocol.Path.parent": candidate_protocol.Path.parent,
        "candidate_protocol.Path.suffix": candidate_protocol.Path.suffix,
        "candidate_protocol.Path.parts": candidate_protocol.Path.parts,
        "candidate_protocol.importlib.util.cache_from_source": (
            candidate_protocol.importlib.util.cache_from_source
        ),
        "candidate_protocol.importlib.import_module": (
            candidate_protocol.importlib.import_module
        ),
        "candidate_protocol.time.monotonic": candidate_protocol.time.monotonic,
        "candidate_protocol.os.walk": candidate_protocol.os.walk,
        "candidate_protocol.os.stat": candidate_protocol.os.stat,
        "candidate_protocol.json.loads": candidate_protocol.json.loads,
        "candidate_protocol.json.dumps": candidate_protocol.json.dumps,
        "candidate_protocol.math.isfinite": candidate_protocol.math.isfinite,
        "candidate_protocol.base64.b64encode": candidate_protocol.base64.b64encode,
        "candidate_protocol.base64.b64decode": candidate_protocol.base64.b64decode,
        "candidate_protocol.re.compile": candidate_protocol.re.compile,
        "candidate_protocol.re.fullmatch": candidate_protocol.re.fullmatch,
        "canonical.hashlib.sha256": canonical.hashlib.sha256,
        "canonical.json.dumps": canonical.json.dumps,
        "compliance.math.isclose": compliance.math.isclose,
        "mutation_runner.dis.get_instructions": dis.get_instructions,
        "mutation_runner.inspect.getsource": inspect.getsource,
        "mutation_runner.inspect.isfunction": inspect.isfunction,
        "mutation_runner.inspect.isclass": inspect.isclass,
        "mutation_runner.inspect.ismodule": inspect.ismodule,
        "mutation_runner.inspect.isbuiltin": inspect.isbuiltin,
    }
    for name in (
        "read_bytes",
        "open",
        "stat",
        "resolve",
        "relative_to",
        "as_posix",
        "is_file",
        "is_dir",
        "is_symlink",
        "mkdir",
        "write_bytes",
        "chmod",
        "exists",
        "is_absolute",
        "joinpath",
        "with_suffix",
        "__truediv__",
        "__fspath__",
        "__str__",
        "parents",
        "parent",
        "suffix",
        "parts",
    ):
        external_attributes[
            f"candidate_protocol.concrete_Path.{name}"
        ] = getattr(concrete_path_type, name)
    external_attributes["candidate_protocol.concrete_Path.cwd.__func__"] = (
        concrete_path_type.cwd.__func__
    )
    external_runtime_objects = {
        "candidate_protocol._RUNTIME_IMPORT_CACHE_LOCK": (
            candidate_protocol._RUNTIME_IMPORT_CACHE_LOCK
        ),
        "candidate_protocol.os.environ": candidate_protocol.os.environ,
    }
    executable_value = candidate_protocol.sys.executable
    if type(executable_value) is not str or not executable_value:
        raise ProtocolViolation("cannot anchor the candidate worker executable")
    executable_path = candidate_protocol.Path(executable_value).resolve()
    executable_raw = executable_path.read_bytes()
    external_values = {
        "candidate_protocol.__file__": candidate_protocol.__file__,
        "candidate_protocol.sys.executable": executable_value,
        "candidate_protocol.sys.base_prefix": candidate_protocol.sys.base_prefix,
        "candidate_protocol.os.devnull": candidate_protocol.os.devnull,
        "candidate_protocol.subprocess.PIPE": candidate_protocol.subprocess.PIPE,
        "candidate_protocol.os.O_WRONLY": candidate_protocol.os.O_WRONLY,
        "candidate_protocol.os.O_RDWR": candidate_protocol.os.O_RDWR,
        "candidate_protocol.os.O_CREAT": candidate_protocol.os.O_CREAT,
        "candidate_protocol.os.O_TRUNC": candidate_protocol.os.O_TRUNC,
        "candidate_protocol.os.O_APPEND": candidate_protocol.os.O_APPEND,
        "candidate_protocol.os.O_EXCL": candidate_protocol.os.O_EXCL,
        "candidate_protocol.worker_bootstrap_environment": [
            [key, candidate_protocol.os.environ.get(key)]
            for key in ("SystemRoot", "WINDIR")
        ],
    }
    prewarm_callable_names = (
        "_runtime_import_read_allowlist",
        "_check_preparation_deadline",
        "_runtime_import_roots",
        "_approved_runtime_zip_paths",
        "_runtime_path_is_approved",
        "_iter_import_files",
        "_normalized_file_path",
        "_write_import_allowlist_manifest",
        "_read_inventory_file",
        "_module_origin_relative_path",
        "_source_cache_relative_path",
        "_candidate_inventory_scan_root",
        "_byte_inventory_digest",
        "_approved_interpreter_wire",
        "_runtime_identity_wire",
        "canonical_json_bytes",
        "digest_bytes",
        "digest_json",
        "validate_json_like",
    )
    prewarm_callables: dict[str, dict[str, Any]] = {}
    for name in prewarm_callable_names:
        value = getattr(candidate_protocol, name, None)
        if not inspect.isfunction(value):
            raise ProtocolViolation(
                f"cannot anchor runtime inventory callable candidate_protocol.{name}"
            )
        prewarm_callables[name] = {
            "value": value,
            "code": value.__code__,
            "defaults": _runtime_value_binding(
                value.__defaults__, f"prewarm.{name}.__defaults__"
            ),
            "kwdefaults": _runtime_value_binding(
                value.__kwdefaults__, f"prewarm.{name}.__kwdefaults__"
            ),
            "closure": _runtime_value_binding(
                None
                if value.__closure__ is None
                else tuple(cell.cell_contents for cell in value.__closure__),
                f"prewarm.{name}.__closure__",
            ),
        }
    prewarm_constant_names = (
        "MAX_IMPORT_FILES",
        "MAX_IMPORT_ALLOWED_PATHS",
        "MAX_IMPORT_FILE_BYTES",
        "MAX_IMPORT_TOTAL_BYTES",
        "MAX_IMPORT_MANIFEST_BYTES",
        "_IMPORT_FILE_SUFFIXES",
        "_IMPORT_TREE_PRUNE",
        "_HARNESS_SOURCE_RELATIVE_PATHS",
        "IMPORT_INVENTORY_PROTOCOL",
        "RUNTIME_IMPORT_CLOSURE_PROTOCOL",
        "RUNTIME_BINDING_KIND",
        "HARNESS_BUNDLE_PROTOCOL",
        "BOOTSTRAP_PROTOCOL",
        "_UNIFIED_WORKER_BOOTSTRAP",
    )
    prewarm_constants = {
        name: _runtime_value_binding(
            getattr(candidate_protocol, name), f"prewarm.constant.{name}"
        )
        for name in prewarm_constant_names
    }
    runtime_roots = tuple(
        candidate_protocol._normalized_file_path(root)
        for root in candidate_protocol._runtime_import_roots()
    )
    approved_runtime_archives = [
        candidate_protocol._normalized_file_path(path)
        for path in candidate_protocol._approved_runtime_zip_paths()
    ]
    # Some stdlib globals (notably sysconfig caches) are initialized by the
    # clean anchor preparation above.  Capture the dispatch closure only after
    # those legitimate one-time transitions have completed.
    external_global_roots = {
        label: {
            "value": value,
            "code": value.__code__ if inspect.isfunction(value) else None,
        }
        for label, value in _external_python_global_roots(
            external_class_surfaces, external_attributes
        ).items()
    }
    nested_external_dispatch_roots = {
        label: {
            "value": value,
            "code": value.__code__ if inspect.isfunction(value) else None,
        }
        for label, value in _nested_external_dispatch_roots(
            candidate_protocol
        ).items()
    }
    return {
        "modules": modules,
        "aliases": aliases,
        "external_attributes": external_attributes,
        "external_runtime_objects": external_runtime_objects,
        "external_values": external_values,
        "external_class_surfaces": external_class_surfaces,
        "external_global_roots": external_global_roots,
        "nested_external_dispatch_roots": nested_external_dispatch_roots,
        "prewarm_callables": prewarm_callables,
        "prewarm_constants": prewarm_constants,
        "runtime_import_roots": tuple(sorted(set(runtime_roots))),
        "approved_runtime_archives": tuple(
            sorted(set(approved_runtime_archives))
        ),
        "runtime_path_separator": candidate_protocol.os.sep,
        "worker_executable": {
            "resolved_path": str(executable_path),
            "size_bytes": len(executable_raw),
            "sha256": digest_bytes(executable_raw),
        },
        "concrete_path_type": concrete_path_type,
    }


def _source_identity_anchor_contract(
    bound_modules: dict[str, Any],
) -> list[dict[str, Any]]:
    """Verify the import-time identity of all module and class dependencies."""

    expected_modules = _SOURCE_IDENTITY_ANCHORS["modules"]
    expected_aliases = _SOURCE_IDENTITY_ANCHORS["aliases"]
    if set(bound_modules) != set(expected_modules):
        raise ProtocolViolation("source identity anchor module set mismatch")
    rows: list[dict[str, Any]] = []
    for logical_name in sorted(expected_modules):
        module = bound_modules[logical_name]
        if module is not expected_modules[logical_name]:
            raise ProtocolViolation(
                f"critical alias identity mismatch: module {logical_name}"
            )
        namespace = vars(module)
        for alias, (kind, expected) in sorted(
            expected_aliases[logical_name].items()
        ):
            current = namespace.get(alias)
            if current is not expected:
                raise ProtocolViolation(
                    "critical alias identity mismatch: "
                    f"{logical_name}.{alias} import-time {kind} anchor"
                )
            if kind == "module":
                target = {
                    "name": expected.__name__,
                    "package": getattr(expected, "__package__", None),
                }
            else:
                target = {
                    "owner": type.__getattribute__(expected, "__module__"),
                    "qualname": type.__getattribute__(expected, "__qualname__"),
                    "metaclass": (
                        f"{type(expected).__module__}."
                        f"{type(expected).__qualname__}"
                    ),
                    "mro": [
                        f"{type.__getattribute__(base, '__module__')}."
                        f"{type.__getattribute__(base, '__qualname__')}"
                        for base in type.__getattribute__(expected, "__mro__")
                    ],
                }
            rows.append(
                {
                    "consumer": f"{module.__name__}.{alias}",
                    "kind": kind,
                    "target": target,
                    "identity_verified": True,
                }
            )
    return rows


def _external_callable_identity_binding(value: Any, label: str) -> dict[str, Any]:
    """Bind one identity-anchored external callable without invoking it."""

    if type(value) is property:
        return {
            "kind": "property",
            "getter": (
                None
                if value.fget is None
                else _live_callable_binding(
                    value.fget,
                    f"{label}.fget",
                    _bind_global_dependencies=False,
                )
            ),
            "setter": (
                None
                if value.fset is None
                else _live_callable_binding(
                    value.fset,
                    f"{label}.fset",
                    _bind_global_dependencies=False,
                )
            ),
            "deleter": (
                None
                if value.fdel is None
                else _live_callable_binding(
                    value.fdel,
                    f"{label}.fdel",
                    _bind_global_dependencies=False,
                )
            ),
        }
    if value is object.__new__:
        return {
            "kind": "builtin-type-slot",
            "owner": "builtins.object",
            "slot": "__new__",
        }
    if inspect.isclass(value):
        return _registered_class_binding(value, label)
    if inspect.isfunction(value):
        return _live_callable_binding(
            value, label, _bind_global_dependencies=False
        )
    if inspect.isbuiltin(value):
        return _registered_callable_reference(value, label)
    raise ProtocolViolation(f"critical external attribute is not callable: {label}")


def _external_attribute_identity_contract(
    *, candidate_protocol: Any, canonical: Any, compliance: Any
) -> list[dict[str, Any]]:
    """Bind freeze-critical attributes looked up through external modules."""

    concrete_path_type = _SOURCE_IDENTITY_ANCHORS["concrete_path_type"]
    expected = _SOURCE_IDENTITY_ANCHORS["external_attributes"]
    # Verify parent classes before dereferencing their methods.  Otherwise a
    # rewritten class alias could turn evidence construction itself into an
    # AttributeError instead of a typed source-integrity rejection.
    for label, value in {
        "candidate_protocol.subprocess.Popen": candidate_protocol.subprocess.Popen,
        "candidate_protocol.threading.Thread": candidate_protocol.threading.Thread,
        "candidate_protocol.queue.Queue": candidate_protocol.queue.Queue,
        "candidate_protocol.tempfile.TemporaryDirectory": (
            candidate_protocol.tempfile.TemporaryDirectory
        ),
    }.items():
        if value is not expected[label]:
            raise ProtocolViolation(
                f"critical external attribute identity mismatch: {label}"
            )
    current = {
        "candidate_protocol.subprocess.Popen": candidate_protocol.subprocess.Popen,
        "candidate_protocol.subprocess.Popen.__new__": (
            candidate_protocol.subprocess.Popen.__new__
        ),
        "candidate_protocol.subprocess.Popen.__init__": (
            candidate_protocol.subprocess.Popen.__init__
        ),
        "candidate_protocol.subprocess.Popen.wait": (
            candidate_protocol.subprocess.Popen.wait
        ),
        "candidate_protocol.subprocess.Popen.poll": (
            candidate_protocol.subprocess.Popen.poll
        ),
        "candidate_protocol.subprocess.Popen.kill": (
            candidate_protocol.subprocess.Popen.kill
        ),
        "candidate_protocol.subprocess.Popen.terminate": (
            candidate_protocol.subprocess.Popen.terminate
        ),
        "candidate_protocol.subprocess.TimeoutExpired": (
            candidate_protocol.subprocess.TimeoutExpired
        ),
        "candidate_protocol.threading.Lock": candidate_protocol.threading.Lock,
        "candidate_protocol.threading.Thread": candidate_protocol.threading.Thread,
        "candidate_protocol.threading.Thread.__new__": (
            candidate_protocol.threading.Thread.__new__
        ),
        "candidate_protocol.threading.Thread.__init__": (
            candidate_protocol.threading.Thread.__init__
        ),
        "candidate_protocol.threading.Thread.start": (
            candidate_protocol.threading.Thread.start
        ),
        "candidate_protocol.threading.Thread.join": (
            candidate_protocol.threading.Thread.join
        ),
        "candidate_protocol.threading.Thread.is_alive": (
            candidate_protocol.threading.Thread.is_alive
        ),
        "candidate_protocol.queue.Queue": candidate_protocol.queue.Queue,
        "candidate_protocol.queue.Queue.__new__": (
            candidate_protocol.queue.Queue.__new__
        ),
        "candidate_protocol.queue.Queue.__init__": (
            candidate_protocol.queue.Queue.__init__
        ),
        "candidate_protocol.queue.Queue.put": candidate_protocol.queue.Queue.put,
        "candidate_protocol.queue.Queue.get": candidate_protocol.queue.Queue.get,
        "candidate_protocol.queue.Queue.get_nowait": (
            candidate_protocol.queue.Queue.get_nowait
        ),
        "candidate_protocol.queue.Empty": candidate_protocol.queue.Empty,
        "candidate_protocol.tempfile.TemporaryDirectory": (
            candidate_protocol.tempfile.TemporaryDirectory
        ),
        "candidate_protocol.tempfile.TemporaryDirectory.__new__": (
            candidate_protocol.tempfile.TemporaryDirectory.__new__
        ),
        "candidate_protocol.tempfile.TemporaryDirectory.__init__": (
            candidate_protocol.tempfile.TemporaryDirectory.__init__
        ),
        "candidate_protocol.tempfile.TemporaryDirectory.__enter__": (
            candidate_protocol.tempfile.TemporaryDirectory.__enter__
        ),
        "candidate_protocol.tempfile.TemporaryDirectory.__exit__": (
            candidate_protocol.tempfile.TemporaryDirectory.__exit__
        ),
        "candidate_protocol.sysconfig.get_paths": (
            candidate_protocol.sysconfig.get_paths
        ),
        "candidate_protocol.sysconfig.get_config_var": (
            candidate_protocol.sysconfig.get_config_var
        ),
        "candidate_protocol.os.fspath": candidate_protocol.os.fspath,
        "candidate_protocol.os.fsdecode": candidate_protocol.os.fsdecode,
        "candidate_protocol.os.path.normcase": candidate_protocol.os.path.normcase,
        "candidate_protocol.os.open": candidate_protocol.os.open,
        "candidate_protocol.os.write": candidate_protocol.os.write,
        "candidate_protocol.os.fsync": candidate_protocol.os.fsync,
        "candidate_protocol.os.close": candidate_protocol.os.close,
        "candidate_protocol.os.dup": candidate_protocol.os.dup,
        "candidate_protocol.os.dup2": candidate_protocol.os.dup2,
        "candidate_protocol.os.read": candidate_protocol.os.read,
        "candidate_protocol.os.pipe": candidate_protocol.os.pipe,
        "candidate_protocol.os.urandom": candidate_protocol.os.urandom,
        "candidate_protocol.Path.__new__": candidate_protocol.Path.__new__,
        "candidate_protocol.Path.read_bytes": candidate_protocol.Path.read_bytes,
        "candidate_protocol.Path.open": candidate_protocol.Path.open,
        "candidate_protocol.Path.stat": candidate_protocol.Path.stat,
        "candidate_protocol.Path.resolve": candidate_protocol.Path.resolve,
        "candidate_protocol.Path.relative_to": candidate_protocol.Path.relative_to,
        "candidate_protocol.Path.as_posix": candidate_protocol.Path.as_posix,
        "candidate_protocol.Path.is_file": candidate_protocol.Path.is_file,
        "candidate_protocol.Path.is_dir": candidate_protocol.Path.is_dir,
        "candidate_protocol.Path.is_symlink": candidate_protocol.Path.is_symlink,
        "candidate_protocol.Path.mkdir": candidate_protocol.Path.mkdir,
        "candidate_protocol.Path.write_bytes": candidate_protocol.Path.write_bytes,
        "candidate_protocol.Path.chmod": candidate_protocol.Path.chmod,
        "candidate_protocol.Path.cwd.__func__": candidate_protocol.Path.cwd.__func__,
        "candidate_protocol.Path.exists": candidate_protocol.Path.exists,
        "candidate_protocol.Path.is_absolute": candidate_protocol.Path.is_absolute,
        "candidate_protocol.Path.joinpath": candidate_protocol.Path.joinpath,
        "candidate_protocol.Path.with_suffix": candidate_protocol.Path.with_suffix,
        "candidate_protocol.Path.__truediv__": candidate_protocol.Path.__truediv__,
        "candidate_protocol.Path.__fspath__": candidate_protocol.Path.__fspath__,
        "candidate_protocol.Path.__str__": candidate_protocol.Path.__str__,
        "candidate_protocol.Path.parents": candidate_protocol.Path.parents,
        "candidate_protocol.Path.parent": candidate_protocol.Path.parent,
        "candidate_protocol.Path.suffix": candidate_protocol.Path.suffix,
        "candidate_protocol.Path.parts": candidate_protocol.Path.parts,
        "candidate_protocol.importlib.util.cache_from_source": (
            candidate_protocol.importlib.util.cache_from_source
        ),
        "candidate_protocol.importlib.import_module": (
            candidate_protocol.importlib.import_module
        ),
        "candidate_protocol.time.monotonic": candidate_protocol.time.monotonic,
        "candidate_protocol.os.walk": candidate_protocol.os.walk,
        "candidate_protocol.os.stat": candidate_protocol.os.stat,
        "candidate_protocol.json.loads": candidate_protocol.json.loads,
        "candidate_protocol.json.dumps": candidate_protocol.json.dumps,
        "candidate_protocol.math.isfinite": candidate_protocol.math.isfinite,
        "candidate_protocol.base64.b64encode": candidate_protocol.base64.b64encode,
        "candidate_protocol.base64.b64decode": candidate_protocol.base64.b64decode,
        "candidate_protocol.re.compile": candidate_protocol.re.compile,
        "candidate_protocol.re.fullmatch": candidate_protocol.re.fullmatch,
        "canonical.hashlib.sha256": canonical.hashlib.sha256,
        "canonical.json.dumps": canonical.json.dumps,
        "compliance.math.isclose": compliance.math.isclose,
        "mutation_runner.dis.get_instructions": dis.get_instructions,
        "mutation_runner.inspect.getsource": inspect.getsource,
        "mutation_runner.inspect.isfunction": inspect.isfunction,
        "mutation_runner.inspect.isclass": inspect.isclass,
        "mutation_runner.inspect.ismodule": inspect.ismodule,
        "mutation_runner.inspect.isbuiltin": inspect.isbuiltin,
    }
    for name in (
        "read_bytes",
        "open",
        "stat",
        "resolve",
        "relative_to",
        "as_posix",
        "is_file",
        "is_dir",
        "is_symlink",
        "mkdir",
        "write_bytes",
        "chmod",
        "exists",
        "is_absolute",
        "joinpath",
        "with_suffix",
        "__truediv__",
        "__fspath__",
        "__str__",
        "parents",
        "parent",
        "suffix",
        "parts",
    ):
        current[f"candidate_protocol.concrete_Path.{name}"] = getattr(
            concrete_path_type, name
        )
    current["candidate_protocol.concrete_Path.cwd.__func__"] = (
        concrete_path_type.cwd.__func__
    )
    if set(current) != set(expected):
        raise ProtocolViolation("external attribute identity set mismatch")
    for label in sorted(expected):
        if current[label] is not expected[label]:
            raise ProtocolViolation(
                f"critical external attribute identity mismatch: {label}"
            )
    rows: list[dict[str, Any]] = []
    for label in sorted(expected):
        value = current[label]
        rows.append(
            {
                "attribute": label,
                "binding": _external_callable_identity_binding(value, label),
                "identity_verified": True,
            }
        )
    return rows


def _external_global_dispatch_contract(
    *, candidate_protocol: Any
) -> dict[str, Any]:
    """Verify transitive stdlib Python globals and selected C/module slots."""

    expected_roots = _SOURCE_IDENTITY_ANCHORS["external_global_roots"]
    live_roots: dict[str, Any] = {}
    for label in expected_roots:
        module_name, _, attribute = label.rpartition(".")
        owner = sys.modules.get(module_name)
        if owner is None or attribute not in vars(owner):
            raise ProtocolViolation(
                f"external Python global dispatch root set mismatch: {label}"
            )
        live_roots[label] = vars(owner)[attribute]

    def verify(
        live: dict[str, Any], expected: dict[str, dict[str, Any]], kind: str
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for label in sorted(expected):
            value = live[label]
            anchor = expected[label]
            if value is not anchor["value"]:
                raise ProtocolViolation(
                    f"critical external {kind} identity mismatch: {label}"
                )
            if inspect.isfunction(value):
                if value.__code__ is not anchor["code"]:
                    raise ProtocolViolation(
                        f"critical external {kind} code mismatch: {label}"
                    )
                binding: dict[str, Any] = {
                    "type": "python-function",
                    "code_digest": digest_json(
                        _stable_code_binding(value.__code__, label)
                    ),
                }
            else:
                binding = {
                    "type": f"{type(value).__module__}.{type(value).__qualname__}",
                    "owner": getattr(value, "__module__", None),
                    "qualname": getattr(value, "__qualname__", None),
                }
            rows.append(
                {
                    "root": label,
                    "binding": binding,
                    "identity_verified": True,
                }
            )
        return rows

    python_rows = verify(live_roots, expected_roots, "Python-global root")
    live_nested = _nested_external_dispatch_roots(candidate_protocol)
    expected_nested = _SOURCE_IDENTITY_ANCHORS[
        "nested_external_dispatch_roots"
    ]
    if set(live_nested) != set(expected_nested):
        raise ProtocolViolation("nested external dispatch root set mismatch")
    nested_rows = verify(live_nested, expected_nested, "nested-dispatch root")
    return {
        "python_global_roots": python_rows,
        "nested_dispatch_roots": nested_rows,
    }


def _external_class_descriptor_binding(
    kind: str, descriptor: Any, label: str
) -> dict[str, Any]:
    if kind in {"staticmethod", "classmethod"}:
        function = descriptor.__func__
        return {
            "kind": kind,
            "callable": _external_callable_identity_binding(function, label),
        }
    if kind in {"method-descriptor", "builtin"} and descriptor is not object.__new__:
        owner = getattr(descriptor, "__objclass__", None)
        name = getattr(descriptor, "__name__", None)
        if not inspect.isclass(owner) or type(name) is not str:
            return _external_callable_identity_binding(descriptor, label)
        if vars(owner).get(name) is not descriptor:
            raise ProtocolViolation(f"unowned external class descriptor: {label}")
        return {
            "kind": kind,
            "owner": (
                f"{type.__getattribute__(owner, '__module__')}."
                f"{type.__getattribute__(owner, '__qualname__')}"
            ),
            "name": name,
        }
    return _external_callable_identity_binding(descriptor, label)


def _external_class_surface_contract(
    *, candidate_protocol: Any
) -> list[dict[str, Any]]:
    """Verify full method/property dispatch surfaces for external trust classes."""

    concrete_path_type = _SOURCE_IDENTITY_ANCHORS["concrete_path_type"]
    current_classes = {
        "candidate_protocol.subprocess.Popen": candidate_protocol.subprocess.Popen,
        "candidate_protocol.threading.Thread": candidate_protocol.threading.Thread,
        "candidate_protocol.queue.Queue": candidate_protocol.queue.Queue,
        "candidate_protocol.tempfile.TemporaryDirectory": (
            candidate_protocol.tempfile.TemporaryDirectory
        ),
        "candidate_protocol.Path": candidate_protocol.Path,
        "candidate_protocol.concrete_Path": concrete_path_type,
    }
    expected_surfaces = _SOURCE_IDENTITY_ANCHORS["external_class_surfaces"]
    if set(current_classes) != set(expected_surfaces):
        raise ProtocolViolation("external class trust surface set mismatch")
    result: list[dict[str, Any]] = []
    for label in sorted(expected_surfaces):
        expected = expected_surfaces[label]
        value = current_classes[label]
        if value is not expected["class"]:
            raise ProtocolViolation(
                f"critical external class identity mismatch: {label}"
            )
        current = _external_class_surface(value, label)
        expected_descriptors = expected["descriptors"]
        if set(current) != set(expected_descriptors):
            raise ProtocolViolation(
                f"critical external class surface set mismatch: {label}"
            )
        descriptors: list[dict[str, Any]] = []
        for descriptor_label in sorted(expected_descriptors):
            expected_kind, expected_descriptor = expected_descriptors[descriptor_label]
            current_kind, current_descriptor = current[descriptor_label]
            if (
                current_kind != expected_kind
                or current_descriptor is not expected_descriptor
            ):
                raise ProtocolViolation(
                    "critical external class descriptor identity mismatch: "
                    f"{descriptor_label}"
                )
            descriptors.append(
                {
                    "descriptor": descriptor_label,
                    "descriptor_kind": current_kind,
                    "binding": _external_class_descriptor_binding(
                        current_kind, current_descriptor, descriptor_label
                    ),
                    "identity_verified": True,
                }
            )
        result.append(
            {
                "class": label,
                "class_binding": _registered_class_binding(value, label),
                "descriptors": descriptors,
            }
        )
    return result


def _external_runtime_object_identity_contract(
    *, candidate_protocol: Any
) -> list[dict[str, Any]]:
    """Verify stable process-local synchronization objects by identity."""

    current = {
        "candidate_protocol._RUNTIME_IMPORT_CACHE_LOCK": (
            candidate_protocol._RUNTIME_IMPORT_CACHE_LOCK
        ),
        "candidate_protocol.os.environ": candidate_protocol.os.environ,
    }
    expected = _SOURCE_IDENTITY_ANCHORS["external_runtime_objects"]
    if set(current) != set(expected):
        raise ProtocolViolation("external runtime object identity set mismatch")
    rows: list[dict[str, Any]] = []
    for label in sorted(expected):
        value = current[label]
        if value is not expected[label]:
            raise ProtocolViolation(
                f"critical external runtime object identity mismatch: {label}"
            )
        rows.append(
            {
                "object": label,
                "binding": _registered_runtime_reference(value, label),
                "identity_verified": True,
            }
        )
    return rows


def _external_runtime_value_contract(*, candidate_protocol: Any) -> dict[str, Any]:
    """Verify scalar spawn/audit roots and the approved interpreter bytes."""

    current = {
        "candidate_protocol.__file__": candidate_protocol.__file__,
        "candidate_protocol.sys.executable": candidate_protocol.sys.executable,
        "candidate_protocol.sys.base_prefix": candidate_protocol.sys.base_prefix,
        "candidate_protocol.os.devnull": candidate_protocol.os.devnull,
        "candidate_protocol.subprocess.PIPE": candidate_protocol.subprocess.PIPE,
        "candidate_protocol.os.O_WRONLY": candidate_protocol.os.O_WRONLY,
        "candidate_protocol.os.O_RDWR": candidate_protocol.os.O_RDWR,
        "candidate_protocol.os.O_CREAT": candidate_protocol.os.O_CREAT,
        "candidate_protocol.os.O_TRUNC": candidate_protocol.os.O_TRUNC,
        "candidate_protocol.os.O_APPEND": candidate_protocol.os.O_APPEND,
        "candidate_protocol.os.O_EXCL": candidate_protocol.os.O_EXCL,
        "candidate_protocol.worker_bootstrap_environment": [
            [key, candidate_protocol.os.environ.get(key)]
            for key in ("SystemRoot", "WINDIR")
        ],
    }
    expected = _SOURCE_IDENTITY_ANCHORS["external_values"]
    if current != expected:
        changed = sorted(
            name
            for name in set(current) | set(expected)
            if current.get(name) != expected.get(name)
        )
        raise ProtocolViolation(
            "critical external runtime value mismatch: " + ", ".join(changed)
        )
    executable = current["candidate_protocol.sys.executable"]
    if type(executable) is not str or not executable:
        raise ProtocolViolation("candidate worker executable is malformed")
    executable_path = candidate_protocol.Path(executable).resolve()
    executable_raw = executable_path.read_bytes()
    live_executable = {
        "resolved_path": str(executable_path),
        "size_bytes": len(executable_raw),
        "sha256": digest_bytes(executable_raw),
    }
    if live_executable != _SOURCE_IDENTITY_ANCHORS["worker_executable"]:
        raise ProtocolViolation("candidate worker executable identity changed")
    return {
        "values": current,
        "worker_executable": live_executable,
        "identity_verified": True,
    }


def _prewarm_internal_callable_contract(
    *, candidate_protocol: Any
) -> list[dict[str, Any]]:
    """Verify the exact inventory builder and its Python dependencies.

    This contract is intentionally evaluated *before* the runtime inventory
    cache is populated.  A transient wrapper must not be able to poison the
    cache, restore the public alias, and then disappear from the ordinary
    pre/post source witnesses.
    """

    expected = _SOURCE_IDENTITY_ANCHORS["prewarm_callables"]
    rows: list[dict[str, Any]] = []
    for name in sorted(expected):
        anchor = expected[name]
        value = getattr(candidate_protocol, name, None)
        if value is not anchor["value"]:
            raise ProtocolViolation(
                f"runtime inventory callable identity mismatch: candidate_protocol.{name}"
            )
        if not inspect.isfunction(value) or value.__code__ is not anchor["code"]:
            raise ProtocolViolation(
                f"runtime inventory callable code mismatch: candidate_protocol.{name}"
            )
        defaults = _runtime_value_binding(
            value.__defaults__, f"prewarm.{name}.__defaults__"
        )
        kwdefaults = _runtime_value_binding(
            value.__kwdefaults__, f"prewarm.{name}.__kwdefaults__"
        )
        closure = _runtime_value_binding(
            None
            if value.__closure__ is None
            else tuple(cell.cell_contents for cell in value.__closure__),
            f"prewarm.{name}.__closure__",
        )
        if (
            defaults != anchor["defaults"]
            or kwdefaults != anchor["kwdefaults"]
            or closure != anchor["closure"]
        ):
            raise ProtocolViolation(
                f"runtime inventory callable defaults/closure mismatch: "
                f"candidate_protocol.{name}"
            )
        rows.append(
            {
                "callable": f"{candidate_protocol.__name__}.{name}",
                "code_digest": digest_json(
                    _stable_code_binding(value.__code__, f"prewarm.{name}")
                ),
                "identity_verified": True,
            }
        )

    current_constants = {
        name: _runtime_value_binding(
            getattr(candidate_protocol, name), f"prewarm.constant.{name}"
        )
        for name in _SOURCE_IDENTITY_ANCHORS["prewarm_constants"]
    }
    if current_constants != _SOURCE_IDENTITY_ANCHORS["prewarm_constants"]:
        raise ProtocolViolation("runtime inventory limit/authority constants changed")
    return rows


def _prewarm_runtime_inventory_authority_contract() -> dict[str, Any]:
    """Validate every anchored authority used before calling the cache builder."""

    from . import (
        candidate_protocol,
        canonical,
        compliance,
        mutation_evidence,
        mutation_matrix,
        schema,
        state,
    )

    runner_module = sys.modules.get(__name__)
    if runner_module is None:
        raise ProtocolViolation("cannot resolve mutation runner source module")
    bound_modules = {
        "canonical": canonical,
        "candidate_protocol": candidate_protocol,
        "compliance": compliance,
        "mutation_evidence": mutation_evidence,
        "mutation_matrix": mutation_matrix,
        "schema": schema,
        "state": state,
        "mutation_runner": runner_module,
    }
    # Reject rewritten module/class aliases before dereferencing any of their
    # attributes.  In particular, a hostile replacement for ``Path`` or one
    # of the worker classes must produce a typed source-integrity failure, not
    # an incidental AttributeError while the external-attribute transcript is
    # being assembled.
    source_identities = _source_identity_anchor_contract(bound_modules)
    # Guard the primitives used to construct every later transcript before
    # invoking inspect/dis/json/hash helpers themselves.
    external_attributes = _external_attribute_identity_contract(
        candidate_protocol=candidate_protocol,
        canonical=canonical,
        compliance=compliance,
    )
    internal_callables = _prewarm_internal_callable_contract(
        candidate_protocol=candidate_protocol
    )
    external_global_dispatch = _external_global_dispatch_contract(
        candidate_protocol=candidate_protocol
    )
    external_surfaces = _external_class_surface_contract(
        candidate_protocol=candidate_protocol
    )
    external_objects = _external_runtime_object_identity_contract(
        candidate_protocol=candidate_protocol
    )
    external_values = _external_runtime_value_contract(
        candidate_protocol=candidate_protocol
    )
    critical_aliases = _critical_alias_identity_contract(
        candidate_protocol=candidate_protocol,
        canonical=canonical,
        compliance=compliance,
        mutation_evidence=mutation_evidence,
        mutation_matrix=mutation_matrix,
        runner_module=runner_module,
        schema=schema,
        state=state,
    )
    return {
        "protocol": "ucm-runtime-inventory-prewarm-authority/1",
        "source_identities_digest": digest_json(source_identities),
        "internal_callables": internal_callables,
        "external_attributes_digest": digest_json(external_attributes),
        "external_global_dispatch_digest": digest_json(
            external_global_dispatch
        ),
        "external_class_surfaces_digest": digest_json(external_surfaces),
        "external_runtime_objects_digest": digest_json(external_objects),
        "external_runtime_values_digest": digest_json(external_values),
        "critical_aliases_digest": digest_json(critical_aliases),
    }


def _runtime_import_cache_contract(*, candidate_protocol: Any) -> dict[str, Any]:
    """Validate and summarize the exact immutable runtime import authority."""

    cache = candidate_protocol._RUNTIME_IMPORT_CACHE
    if type(cache) is not tuple or len(cache) != 5:
        raise ProtocolViolation("runtime import cache must be one exact 5-tuple")
    entries, absent_paths, allowed_paths, actual_files, total_bytes = cache
    if (
        type(entries) is not tuple
        or type(absent_paths) is not tuple
        or type(allowed_paths) is not tuple
        or type(actual_files) is not int
        or type(total_bytes) is not int
    ):
        raise ProtocolViolation("runtime import cache fields have malformed types")
    if actual_files < 0 or total_bytes < 0:
        raise ProtocolViolation("runtime import cache counts cannot be negative")

    roots = _SOURCE_IDENTITY_ANCHORS["runtime_import_roots"]
    archives = frozenset(_SOURCE_IDENTITY_ANCHORS["approved_runtime_archives"])
    separator = _SOURCE_IDENTITY_ANCHORS["runtime_path_separator"]
    if type(separator) is not str or not separator:
        raise ProtocolViolation("runtime path separator anchor is malformed")
    forbidden_parts = {
        part.casefold()
        for part in candidate_protocol._IMPORT_TREE_PRUNE
        if part != "__pycache__"
    }

    def canonical_path(value: Any, label: str) -> str:
        if type(value) is not str or not value:
            raise ProtocolViolation(f"{label} must be a non-empty exact string")
        if candidate_protocol._normalized_file_path(value) != value:
            raise ProtocolViolation(f"{label} is not a canonical normalized path")
        parts = {
            part.casefold()
            for part in value.replace("\\", "/").split("/")
            if part
        }
        if parts & forbidden_parts:
            raise ProtocolViolation(f"{label} enters a pruned import tree")
        return value

    def under_runtime_root(path: str) -> bool:
        return any(
            path == root or path.startswith(root.rstrip(separator) + separator)
            for root in roots
        )

    entry_rows: list[dict[str, Any]] = []
    entry_paths: list[str] = []
    observed_total_bytes = 0
    for index, entry in enumerate(entries):
        if type(entry) is not tuple or len(entry) != 3:
            raise ProtocolViolation(f"runtime import entry {index} is malformed")
        raw_path, size_bytes, sha256 = entry
        path = canonical_path(raw_path, f"runtime import entry {index} path")
        if (
            type(size_bytes) is not int
            or size_bytes < 0
            or size_bytes > candidate_protocol.MAX_IMPORT_FILE_BYTES
        ):
            raise ProtocolViolation(f"runtime import entry {index} size is invalid")
        digest = _exact_digest(sha256, f"runtime import entry {index} digest")
        if not under_runtime_root(path) and path not in archives:
            raise ProtocolViolation(
                f"runtime import entry {index} exceeds anchored runtime roots"
            )
        if candidate_protocol.Path(path).suffix.lower() not in (
            candidate_protocol._IMPORT_FILE_SUFFIXES
        ):
            raise ProtocolViolation(
                f"runtime import entry {index} has an unapproved suffix"
            )
        entry_paths.append(path)
        observed_total_bytes += size_bytes
        entry_rows.append(
            {"path": path, "size_bytes": size_bytes, "sha256": digest}
        )
    if entry_paths != sorted(set(entry_paths)):
        raise ProtocolViolation("runtime import entries must be sorted and unique")
    if actual_files != len(entry_rows) or total_bytes != observed_total_bytes:
        raise ProtocolViolation("runtime import cache count/byte totals drifted")
    if (
        actual_files > candidate_protocol.MAX_IMPORT_FILES
        or total_bytes > candidate_protocol.MAX_IMPORT_TOTAL_BYTES
    ):
        raise ProtocolViolation("runtime import cache exceeds frozen limits")

    def canonical_path_tuple(
        values: tuple[Any, ...], label: str, *, absent: bool
    ) -> tuple[str, ...]:
        normalized: list[str] = []
        for index, raw_path in enumerate(values):
            path = canonical_path(raw_path, f"{label} {index}")
            if not under_runtime_root(path) and (absent or path not in archives):
                raise ProtocolViolation(f"{label} {index} exceeds runtime roots")
            if absent and candidate_protocol.Path(path).suffix.lower() != ".pyc":
                raise ProtocolViolation(f"{label} {index} is not a bytecode cache")
            normalized.append(path)
        if normalized != sorted(set(normalized)):
            raise ProtocolViolation(f"{label} must be sorted and unique")
        return tuple(normalized)

    absent = canonical_path_tuple(absent_paths, "runtime absent path", absent=True)
    allowed = canonical_path_tuple(allowed_paths, "runtime allowed path", absent=False)
    expected_allowed = tuple(sorted(set(entry_paths) | set(absent)))
    if allowed != expected_allowed:
        raise ProtocolViolation(
            "runtime allowed paths do not equal exact entries plus sealed absences"
        )
    existing_archives = {
        path
        for path in archives
        if candidate_protocol.Path(path).is_file()
        and not candidate_protocol.Path(path).is_symlink()
    }
    if not existing_archives.issubset(set(entry_paths)):
        raise ProtocolViolation(
            "runtime import cache omitted an existing approved runtime archive"
        )
    if len(allowed) > candidate_protocol.MAX_IMPORT_ALLOWED_PATHS:
        raise ProtocolViolation("runtime import allowlist exceeds frozen path limit")

    cache_wire = {
        "protocol": candidate_protocol.RUNTIME_IMPORT_CLOSURE_PROTOCOL,
        "entries": entry_rows,
        "absent_paths": list(absent),
        "allowed_paths": list(allowed),
        "actual_files": actual_files,
        "total_bytes": total_bytes,
    }
    return {
        "protocol": "ucm-runtime-import-cache-binding/1",
        "cache_digest": digest_json(cache_wire),
        "entry_rows_digest": digest_json(entry_rows),
        "absent_paths_digest": digest_json(list(absent)),
        "allowed_paths_digest": digest_json(list(allowed)),
        "entry_count": actual_files,
        "absent_path_count": len(absent),
        "allowed_path_count": len(allowed),
        "total_bytes": total_bytes,
        "anchored_runtime_roots_digest": digest_json(list(roots)),
        "approved_runtime_archives_digest": digest_json(sorted(archives)),
    }


def _prepare_runtime_import_cache() -> dict[str, Any]:
    """Clean-rebuild the runtime cache after binding its complete authority.

    No module-global ``verified`` flag is trusted here.  Such a flag and a
    matching, incomplete cache can be pre-seeded together before the runner is
    entered.  Every suite therefore obtains its baseline from this compulsory
    clean rebuild and carries only the resulting digest in a local variable.
    """

    from . import candidate_protocol

    _prewarm_runtime_inventory_authority_contract()
    observed_before_rebuild = candidate_protocol._RUNTIME_IMPORT_CACHE
    candidate_protocol._RUNTIME_IMPORT_CACHE = None
    rebuilt = candidate_protocol._runtime_import_read_allowlist(
        deadline=candidate_protocol.time.monotonic() + 60.0
    )
    if observed_before_rebuild is not None and observed_before_rebuild != rebuilt:
        raise ProtocolViolation(
            "pre-existing runtime import cache did not match clean rebuild"
        )
    contract = _runtime_import_cache_contract(candidate_protocol=candidate_protocol)
    return contract


def _verify_runtime_import_cache(
    expected_contract_digest: str,
) -> dict[str, Any]:
    """Verify the current cache against one suite-local clean baseline."""

    from . import candidate_protocol

    expected_contract_digest = _exact_digest(
        expected_contract_digest,
        "expected runtime import cache contract digest",
    )
    _prewarm_runtime_inventory_authority_contract()
    candidate_protocol._runtime_import_read_allowlist(
        deadline=candidate_protocol.time.monotonic() + 60.0
    )
    contract = _runtime_import_cache_contract(candidate_protocol=candidate_protocol)
    if digest_json(contract) != expected_contract_digest:
        raise ProtocolViolation("suite-local runtime import cache baseline drifted")
    return contract


def _expected_live_execution_binding(control_class_name: str) -> dict[str, str]:
    """Rebuild the exact live snapshot binding before/after one execution."""

    from . import candidate_protocol, compliance

    entrypoint = compliance.control_entrypoint(control_class_name)
    with candidate_protocol.tempfile.TemporaryDirectory(
        prefix="ucm-source-binding-"
    ) as directory:
        prepared = candidate_protocol._write_import_allowlist_manifest(
            candidate_protocol.Path(directory),
            entrypoint,
            deadline=candidate_protocol.time.monotonic() + 60.0,
        )
        binding = {
            "candidate_bundle_digest": _exact_digest(
                prepared.candidate_bundle_digest,
                "expected candidate_bundle_digest",
            ),
            "candidate_model_digest": _exact_digest(
                prepared.candidate_model_digest,
                "expected candidate_model_digest",
            ),
            "harness_bundle_digest": _exact_digest(
                prepared.harness_bundle_digest,
                "expected harness_bundle_digest",
            ),
            "import_inventory_digest": _exact_digest(
                prepared.import_inventory_digest,
                "expected import_inventory_digest",
            ),
            "module_origin": prepared.module_origin,
        }
    module_origin = binding["module_origin"]
    module_path = PurePosixPath(module_origin)
    if (
        not module_origin
        or module_origin.strip() != module_origin
        or module_path.is_absolute()
        or module_path.as_posix() != module_origin
        or "\\" in module_origin
        or any(
            part in {"", ".", ".."} or ":" in part
            for part in module_path.parts
        )
    ):
        raise ProtocolViolation("expected module_origin is not canonical")
    return binding


@dataclass(frozen=True, slots=True)
class PortableMutationCase:
    matrix_subject_id: str
    control_class_name: str
    decisive_gate: str
    expected_failure_code: str
    semantic_probes: frozenset[str] = frozenset()


PORTABLE_MUTATION_CASES: tuple[PortableMutationCase, ...] = (
    PortableMutationCase(
        "GlobalSecondState",
        "GlobalSecondStateControl",
        "C04",
        "UCM-F006-HIDDEN_PATIENT_CACHE",
    ),
    PortableMutationCase(
        "FileHandleState",
        "FileHandleStateControl",
        "C07",
        "UCM-F008-STATE_NOT_CLOSED",
    ),
    PortableMutationCase(
        "RawHistoryHead",
        "RawHistoryHeadControl",
        "C02",
        "UCM-F004-HEAD_HISTORY_ACCESS",
    ),
    PortableMutationCase(
        "TrainerTargetSmuggler",
        "TrainerTargetSmugglerControl",
        "C08",
        "UCM-F002-ORACLE_TRUE_STATE_ACCESS",
    ),
    PortableMutationCase(
        "QueryReencoder",
        "QueryReencoderControl",
        "C02",
        "UCM-F004-HEAD_HISTORY_ACCESS",
    ),
    PortableMutationCase(
        "MutableCheckpoint",
        "MutableCheckpointControl",
        "C06",
        "UCM-F009-MODEL_MUTATION",
    ),
    PortableMutationCase(
        "TrueStateReader",
        "TrueStateReaderControl",
        "C08",
        "UCM-F002-ORACLE_TRUE_STATE_ACCESS",
    ),
    PortableMutationCase(
        "FutureReader",
        "FutureReaderControl",
        "C08",
        "UCM-F001-FUTURE_LEAK",
    ),
    PortableMutationCase(
        "CounterfactualMutator",
        "QueryMutatorControl",
        "C16",
        "UCM-F012-QUERY_MUTATES_FACT",
    ),
    PortableMutationCase(
        "ImplicitRNGState",
        "ImplicitRNGControl",
        "C30",
        "UCM-F020-NONREPRODUCIBLE",
    ),
    PortableMutationCase(
        "HistoryInBlob",
        "HistoryInBlobControl",
        "C27",
        "UCM-F018-FULL_HISTORY_MISCLAIM",
        frozenset({"full_history_disclosure"}),
    ),
    PortableMutationCase(
        "WarmFutureCache",
        "WarmFutureCacheControl",
        "C23",
        "UCM-F001-FUTURE_LEAK",
        frozenset({"warm_future_old_cut"}),
    ),
    PortableMutationCase(
        "ReplayBatchDivergence",
        "ReplayBatchDivergenceControl",
        "C22",
        "UCM-F019-UPDATE_INCONSISTENT",
        frozenset({"update_consistency"}),
    ),
    PortableMutationCase(
        "DoubleCountEvent",
        "DoubleCountEventControl",
        "C22",
        "UCM-F019-UPDATE_INCONSISTENT",
        frozenset({"update_consistency"}),
    ),
)


PORTABLE_SPECIFICITY_CASES: tuple[
    tuple[str, str, str, frozenset[str]], ...
] = (
    (
        "ExplicitSeedStochasticState",
        "HonestSeededControl",
        "ordinary_candidate",
        frozenset(
            {
                "full_history_disclosure",
                "update_consistency",
                "warm_future_old_cut",
            }
        ),
    ),
    (
        "BehaviorEquivalentSerialization",
        "BehaviorEquivalentSerializationControl",
        "ordinary_candidate",
        frozenset({"update_consistency"}),
    ),
    (
        "DeclaredFullHistoryBaseline",
        "DeclaredFullHistoryBaselineControl",
        "baseline_only",
        frozenset({"full_history_disclosure"}),
    ),
)


def _finding_wire(finding: ComplianceFinding) -> dict[str, Any]:
    return {
        "gate": finding.gate,
        "verdict": finding.verdict.value,
        "failure_code": finding.failure_code,
        "detail": finding.detail,
        "evidence": finding.evidence,
    }


def _exact_digest(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
    ):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    if any(character not in "0123456789abcdef" for character in value[7:]):
        raise ProtocolViolation(f"{label} must be lowercase hexadecimal")
    return value


def _report_execution_binding(
    report: Any,
    *,
    expected_candidate: str,
    expected_execution_binding: dict[str, str] | None = None,
) -> dict[str, str]:
    """Extract the exact worker snapshot identity committed by a report."""

    if getattr(report, "candidate", None) != expected_candidate:
        raise ProtocolViolation("report candidate identity does not match execution")
    bundle = _exact_digest(
        getattr(report, "candidate_bundle_digest", None),
        "report candidate_bundle_digest",
    )
    model = _exact_digest(
        getattr(report, "candidate_model_digest", None),
        "report candidate_model_digest",
    )
    harness = _exact_digest(
        getattr(report, "harness_bundle_digest", None),
        "report harness_bundle_digest",
    )
    inventory = _exact_digest(
        getattr(report, "import_inventory_digest", None),
        "report import_inventory_digest",
    )
    module_origin = getattr(report, "module_origin", None)
    if (
        type(module_origin) is not str
        or not module_origin
        or module_origin.strip() != module_origin
    ):
        raise ProtocolViolation("report module_origin must be a non-empty exact string")
    module_path = PurePosixPath(module_origin)
    if (
        module_path.is_absolute()
        or module_path.as_posix() != module_origin
        or "\\" in module_origin
        or any(
            part in {"", ".", ".."} or ":" in part
            for part in module_path.parts
        )
    ):
        raise ProtocolViolation(
            "report module_origin must be a canonical bundle-relative POSIX path"
        )
    binding = {
        "candidate_bundle_digest": bundle,
        "candidate_model_digest": model,
        "harness_bundle_digest": harness,
        "import_inventory_digest": inventory,
        "module_origin": module_origin,
    }
    head_records = getattr(report, "head_records", None)
    if type(head_records) is not tuple:
        raise ProtocolViolation("report head_records must be an exact tuple")
    for index, record in enumerate(head_records):
        if type(record) is not dict:
            raise ProtocolViolation(f"report head record {index} must be an exact dict")
        record_binding = {
            "candidate_bundle_digest": _exact_digest(
                record.get("candidate_bundle_digest"),
                f"report head record {index} candidate_bundle_digest",
            ),
            "candidate_model_digest": _exact_digest(
                record.get("candidate_model_digest"),
                f"report head record {index} candidate_model_digest",
            ),
            "harness_bundle_digest": _exact_digest(
                record.get("harness_bundle_digest"),
                f"report head record {index} harness_bundle_digest",
            ),
            "import_inventory_digest": _exact_digest(
                record.get("import_inventory_digest"),
                f"report head record {index} import_inventory_digest",
            ),
            "module_origin": record.get("module_origin"),
        }
        if record_binding != binding:
            raise ProtocolViolation(
                f"report head record {index} execution binding drifted"
            )
    if expected_execution_binding is not None:
        if (
            type(expected_execution_binding) is not dict
            or set(expected_execution_binding) != set(binding)
            or any(
                type(value) is not str
                for value in expected_execution_binding.values()
            )
        ):
            raise ProtocolViolation("live expected execution binding is malformed")
        if binding != expected_execution_binding:
            raise ProtocolViolation(
                "worker execution binding does not match live source snapshot"
            )
    return binding


def _execution_bound_source_witness(
    harness_witness: dict[str, Any], execution_binding: dict[str, str]
) -> dict[str, Any]:
    return {
        "protocol": "ucm-portable-executed-source-binding/2",
        "harness_witness": harness_witness,
        "execution_binding": execution_binding,
    }


def _unavailable_source_witness(stage: str, error: Exception) -> dict[str, str]:
    """Return bounded, deterministic evidence for a failed witness stage."""

    return {
        "protocol": "ucm-portable-source-witness-unavailable/1",
        "stage": stage,
        "exception_type": f"{type(error).__module__}.{type(error).__qualname__}",
    }


def _specificity_report_eligible(report: Any) -> bool:
    probe_incomplete = any(
        finding.verdict is ComplianceVerdict.INCOMPLETE
        and finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
        for finding in report.findings
    )
    return (
        report.operational_state_closure is ComplianceVerdict.PASS
        and not report.failure_codes
        and not probe_incomplete
    )


def paired_serialization_equivalence_evidence(
    *,
    history: VisibleHistory,
    diagnosis_query: DiagnosisQuery,
    rollout_query: RolloutQuery,
    delta: VisibleDelta | None,
    seed: int,
) -> dict[str, Any]:
    """Compare Honest and affine states on the same scored behavior surfaces."""

    from . import (
        candidate_protocol,
        canonical,
        compliance,
        mutation_matrix,
        schema,
        state,
    )
    from .candidate_protocol import DiagnoseResponse, RolloutResponse
    from .state import CandidateStateInput, StatePayload

    honest = compliance.HonestSeededControl()
    affine = compliance.BehaviorEquivalentSerializationControl()

    def state_digest(payload: StatePayload) -> str:
        return digest_json(
            {
                "payload_digest": digest_bytes(payload.payload),
                "codec": payload.codec,
                "schema_version": payload.schema_version,
                "state_class": payload.state_class.value,
            }
        )

    def behavior(candidate: Any, payload: StatePayload) -> dict[str, Any]:
        state = CandidateStateInput(payload)
        diagnosis = DiagnoseResponse(
            candidate.diagnose(
                state,
                diagnosis_query,
                query_seed=seed + 1,
            )
        )
        rollout = RolloutResponse(
            candidate.rollout(
                state,
                rollout_query,
                query_seed=seed + 2,
            )
        )
        return {
            "diagnosis": compliance._semantic_behavior_projection(diagnosis),
            "rollout": compliance._semantic_behavior_projection(rollout),
        }

    honest_state = honest.initialize(history, inference_seed=seed)
    affine_state = affine.initialize(history, inference_seed=seed)
    phases: list[dict[str, Any]] = []

    def append_phase(name: str) -> None:
        honest_behavior = behavior(honest, honest_state_by_phase[name])
        affine_behavior = behavior(affine, affine_state_by_phase[name])
        phases.append(
            {
                "phase": name,
                "honest_state_digest": state_digest(honest_state_by_phase[name]),
                "affine_state_digest": state_digest(affine_state_by_phase[name]),
                "state_serializations_distinct": (
                    state_digest(honest_state_by_phase[name])
                    != state_digest(affine_state_by_phase[name])
                ),
                "honest_behavior_digest": digest_json(honest_behavior),
                "affine_behavior_digest": digest_json(affine_behavior),
                "semantic_behavior_equivalent": (
                    compliance._semantic_behavior_equal(
                        honest_behavior, affine_behavior
                    )
                ),
            }
        )

    honest_state_by_phase = {"initialize": honest_state}
    affine_state_by_phase = {"initialize": affine_state}
    append_phase("initialize")
    if delta is not None:
        honest_state_by_phase["update"] = honest.update(
            CandidateStateInput(honest_state),
            delta,
            inference_seed=seed + 3,
        )
        affine_state_by_phase["update"] = affine.update(
            CandidateStateInput(affine_state),
            delta,
            inference_seed=seed + 3,
        )
        append_phase("update")

    passed = all(
        phase["state_serializations_distinct"]
        and phase["semantic_behavior_equivalent"]
        for phase in phases
    )
    return {
        "protocol": compliance.PORTABLE_SEMANTIC_PROBE_PROTOCOL,
        "comparison": "paired-honest-vs-affine-scored-semantics",
        "absolute_tolerance": compliance.SEMANTIC_ABS_TOLERANCE,
        "relative_tolerance": compliance.SEMANTIC_REL_TOLERANCE,
        "phases": phases,
        "passed": passed,
    }


def _portable_runner_contract() -> dict[str, Any]:
    if type(RUNNER_PROTOCOL) is not str or not RUNNER_PROTOCOL:
        raise ProtocolViolation("runner protocol must be a non-empty string")
    if type(PORTABLE_MUTATION_CASES) is not tuple:
        raise ProtocolViolation("portable mutation cases must be an exact tuple")
    mutation_cases: list[dict[str, Any]] = []
    for index, case in enumerate(PORTABLE_MUTATION_CASES):
        if type(case) is not PortableMutationCase:
            raise ProtocolViolation(f"portable mutation case {index} is malformed")
        mutation_cases.append(
            {
                "matrix_subject_id": case.matrix_subject_id,
                "control_class_name": case.control_class_name,
                "decisive_gate": case.decisive_gate,
                "expected_failure_code": case.expected_failure_code,
                "semantic_probes": sorted(case.semantic_probes),
            }
        )
    if type(PORTABLE_SPECIFICITY_CASES) is not tuple:
        raise ProtocolViolation("portable specificity cases must be an exact tuple")
    specificity_cases: list[dict[str, Any]] = []
    for index, row in enumerate(PORTABLE_SPECIFICITY_CASES):
        if type(row) is not tuple or len(row) != 4:
            raise ProtocolViolation(
                f"portable specificity case {index} is malformed"
            )
        subject_id, control_class_name, classification, probes = row
        if (
            type(subject_id) is not str
            or type(control_class_name) is not str
            or type(classification) is not str
            or type(probes) is not frozenset
            or any(type(probe) is not str for probe in probes)
        ):
            raise ProtocolViolation(
                f"portable specificity case {index} fields are malformed"
            )
        specificity_cases.append(
            {
                "subject_id": subject_id,
                "control_class_name": control_class_name,
                "classification": classification,
                "semantic_probes": sorted(probes),
            }
        )
    return {
        "runner_protocol": RUNNER_PROTOCOL,
        "runner_semantic_probe_protocol_alias": PORTABLE_SEMANTIC_PROBE_PROTOCOL,
        "mutation_cases": mutation_cases,
        "specificity_cases": specificity_cases,
    }


def _active_portable_execution_rows(
    code_owned_contract: dict[str, Any],
) -> tuple[
    tuple[tuple[int, PortableMutationCase, str], ...],
    tuple[tuple[int, tuple[str, str, str, frozenset[str]], str], ...],
]:
    """Bind an active subset to immutable full-registry row indices."""

    if type(code_owned_contract) is not dict or set(code_owned_contract) != {
        "runner_protocol",
        "runner_semantic_probe_protocol_alias",
        "update_consistency_lineage_xor_mask",
        "mutation_cases",
        "specificity_cases",
    }:
        raise ProtocolViolation("code-owned portable runner contract is malformed")
    from . import compliance

    active_contract = _portable_runner_contract()
    if (
        code_owned_contract["runner_protocol"] != RUNNER_PROTOCOL
        or code_owned_contract["runner_semantic_probe_protocol_alias"]
        != PORTABLE_SEMANTIC_PROBE_PROTOCOL
        or code_owned_contract["update_consistency_lineage_xor_mask"]
        != compliance.UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
    ):
        raise ProtocolViolation("code-owned portable runner protocol aliases drifted")
    code_owned_mutants = code_owned_contract["mutation_cases"]
    code_owned_controls = code_owned_contract["specificity_cases"]
    if type(code_owned_mutants) is not list or type(code_owned_controls) is not list:
        raise ProtocolViolation("code-owned portable runner rows must be exact lists")

    mutant_rows: list[tuple[int, PortableMutationCase, str]] = []
    seen_indices: set[int] = set()
    for case, payload in zip(
        PORTABLE_MUTATION_CASES,
        active_contract["mutation_cases"],
        strict=True,
    ):
        matches = [
            (index, expected.get("head_record_shape"))
            for index, expected in enumerate(code_owned_mutants)
            if type(expected) is dict
            and set(expected) == set(payload) | {"head_record_shape"}
            and all(expected[key] == value for key, value in payload.items())
            and expected.get("head_record_shape") in {"empty", "replay_ddrr"}
        ]
        if len(matches) != 1 or matches[0][0] in seen_indices:
            raise ProtocolViolation(
                f"active mutant {case.matrix_subject_id!r} is not one unique "
                "code-owned portable row"
            )
        row_index, head_record_shape = matches[0]
        seen_indices.add(row_index)
        mutant_rows.append((row_index, case, head_record_shape))

    control_rows: list[
        tuple[int, tuple[str, str, str, frozenset[str]], str]
    ] = []
    for row, payload in zip(
        PORTABLE_SPECIFICITY_CASES,
        active_contract["specificity_cases"],
        strict=True,
    ):
        matches = [
            (index, expected.get("head_record_shape"))
            for index, expected in enumerate(code_owned_controls)
            if type(expected) is dict
            and set(expected) == set(payload) | {"head_record_shape"}
            and all(expected[key] == value for key, value in payload.items())
            and expected.get("head_record_shape") in {"empty", "replay_ddrr"}
        ]
        full_row_index = (
            len(code_owned_mutants) + matches[0][0] if len(matches) == 1 else -1
        )
        if len(matches) != 1 or full_row_index in seen_indices:
            raise ProtocolViolation(
                f"active specificity control {row[0]!r} is not one unique "
                "code-owned portable row"
        )
        seen_indices.add(full_row_index)
        control_rows.append((full_row_index, row, matches[0][1]))
    return tuple(mutant_rows), tuple(control_rows)


def _enum_runtime_contract(value: Any, label: str) -> dict[str, Any]:
    if not inspect.isclass(value) or not issubclass(value, Enum):
        raise ProtocolViolation(f"{label} is not a live enum class")
    return {
        "class": _registered_class_binding(value, label),
        "members": [
            {
                "name": member.name,
                "value": _runtime_value_binding(
                    member.value, f"{label}.{member.name}"
                ),
            }
            for member in value
        ],
    }


def _freeze_critical_runtime_contract(
    *,
    candidate_protocol: Any,
    compliance: Any,
    mutation_evidence: Any,
    mutation_matrix: Any,
    runner_module: Any,
    schema: Any,
    state: Any,
) -> dict[str, Any]:
    constant_names = {
        "candidate_protocol": (
            candidate_protocol,
            (
                "REQUEST_PROTOCOL",
                "RESPONSE_PROTOCOL",
                "WORKER_PROTOCOL",
                "SESSION_WORKER_PROTOCOL",
                "SESSION_REQUEST_PROTOCOL",
                "MAX_STATE_PAYLOAD_BYTES",
                "MAX_SESSION_REQUESTS",
                "MAX_SESSION_FRAME_BYTES",
                "MAX_CAPTURED_STREAM_BYTES",
                "MAX_AUDIT_EVENTS",
                "MAX_AUDIT_EVENT_ARGS",
                "MAX_IMPORT_FILES",
                "MAX_IMPORT_ALLOWED_PATHS",
                "MAX_IMPORT_FILE_BYTES",
                "MAX_IMPORT_TOTAL_BYTES",
                "MAX_IMPORT_MANIFEST_BYTES",
                "MAX_SEQUENTIAL_AGGREGATE_BYTES",
                "MAX_RESPONSE_FRAME_BYTES",
                "IMPORT_INVENTORY_PROTOCOL",
                "RUNTIME_IMPORT_CLOSURE_PROTOCOL",
                "RUNTIME_BINDING_KIND",
                "HARNESS_BUNDLE_PROTOCOL",
                "BOOTSTRAP_PROTOCOL",
                "IMPORT_ALLOWLIST_PROTOCOL",
                "_IMPORT_FILE_SUFFIXES",
                "_IMPORT_TREE_PRUNE",
                "_WORKER_BOOTSTRAP",
                "_SESSION_WORKER_BOOTSTRAP",
                "_UNIFIED_WORKER_BOOTSTRAP",
                "_CANDIDATE_FAILURE_PHASES",
                "_HARNESS_FAILURE_PHASES",
                "_WORKER_FAILURE_PHASES",
                "_DENIED_AUDIT_EVENTS",
                "_PIPE_EOF",
                "_PIPE_OVERFLOW",
            ),
        ),
        "compliance": (
            compliance,
            (
                "PORTABLE_SEMANTIC_PROBES",
                "PORTABLE_SEMANTIC_PROBE_PROTOCOL",
                "SEMANTIC_ABS_TOLERANCE",
                "SEMANTIC_REL_TOLERANCE",
                "UPDATE_CONSISTENCY_LINEAGE_XOR_MASK",
                "_HISTORY_MAX_PAYLOAD_BYTES",
                "_HISTORY_MAX_DEPTH",
                "_HISTORY_MAX_NODES",
                "_HISTORY_MAX_STRINGS",
                "_HISTORY_MAX_STRING_CHARS",
                "_HISTORY_MAX_DECODE_ATTEMPTS",
                "_HISTORY_MAX_TOTAL_COMPRESSED_BYTES",
                "_HISTORY_MAX_SINGLE_EXPANDED_BYTES",
                "_HISTORY_MAX_TOTAL_EXPANDED_BYTES",
            ),
        ),
        "mutation_matrix": (
            mutation_matrix,
            (
                "MATRIX_PROTOCOL",
                "GATE_SPECS",
                "MUTANT_SPECS",
                "SPECIFICITY_CONTROLS",
                "REGISTRY_DIGEST",
            ),
        ),
        "mutation_evidence": (
            mutation_evidence,
            (
                "MUTATION_EVIDENCE_PROTOCOL",
                "MUTATION_EXECUTION_CONTEXT_PROTOCOL",
                "MUTATION_INPUT_PREIMAGE_PROTOCOL",
                "MUTATION_PRE_SOURCE_WITNESS_PROTOCOL",
                "MUTATION_POST_SOURCE_WITNESS_PROTOCOL",
                "MUTATION_SOURCE_RECORD_PROTOCOL",
                "MUTATION_REPORT_TRANSCRIPT_PROTOCOL",
                "MUTATION_ERROR_TRANSCRIPT_PROTOCOL",
                "MUTATION_DECISION_RECORD_PROTOCOL",
                "MUTATION_DECISIVE_RECORD_PROTOCOL",
                "BENCHMARK_ID",
                "PRE_FREEZE_STATUS",
                "ISOLATION_INCOMPLETE_CODE",
                "HARNESS_INCOMPLETE_CODE",
                "MUTATION_EVIDENCE_BLOCKERS",
                "UPDATE_CONSISTENCY_LINEAGE_XOR_MASK",
            ),
        ),
        "mutation_runner": (
            runner_module,
            (
                "RUNNER_PROTOCOL",
                "PORTABLE_SEMANTIC_PROBE_PROTOCOL",
                "PORTABLE_MUTATION_CASES",
                "PORTABLE_SPECIFICITY_CASES",
            ),
        ),
        "schema": (schema, ("PRIVILEGED_FIELD_NAMES",)),
        "state": (state, ("ALLOWED_INERT_CODECS",)),
    }
    constants: dict[str, Any] = {}
    for group, (module, names) in constant_names.items():
        constants[group] = {
            name: _runtime_value_binding(
                getattr(module, name), f"{module.__name__}.{name}"
            )
            for name in names
        }

    enum_names = {
        "candidate_protocol": (
            candidate_protocol,
            ("Operation", "ResultStatus", "_PipeSignal"),
        ),
        "compliance": (compliance, ("ComplianceVerdict",)),
        "mutation_matrix": (
            mutation_matrix,
            ("SubjectKind", "ObservationOutcome"),
        ),
        "schema": (schema, ("EventKind", "PlanKind")),
        "state": (state, ("StateClass",)),
    }
    enums = {
        group: {
            name: _enum_runtime_contract(
                getattr(module, name), f"{module.__name__}.{name}"
            )
            for name in names
        }
        for group, (module, names) in enum_names.items()
    }
    return {"constants_and_registries": constants, "enums": enums}


def _critical_alias_identity_contract(
    *,
    candidate_protocol: Any,
    canonical: Any,
    compliance: Any,
    mutation_evidence: Any,
    mutation_matrix: Any,
    runner_module: Any,
    schema: Any,
    state: Any,
) -> list[dict[str, str]]:
    modules = {
        "candidate_protocol": candidate_protocol,
        "canonical": canonical,
        "compliance": compliance,
        "mutation_evidence": mutation_evidence,
        "mutation_matrix": mutation_matrix,
        "mutation_runner": runner_module,
        "schema": schema,
        "state": state,
    }
    specs = {
        "candidate_protocol": {
            "ProtocolViolation": ("canonical", "ProtocolViolation"),
            "canonical_json_bytes": ("canonical", "canonical_json_bytes"),
            "digest_bytes": ("canonical", "digest_bytes"),
            "digest_json": ("canonical", "digest_json"),
            "validate_json_like": ("canonical", "validate_json_like"),
            "ActionPlan": ("schema", "ActionPlan"),
            "CandidateVisibleEvent": ("schema", "CandidateVisibleEvent"),
            "DiagnosisQuery": ("schema", "DiagnosisQuery"),
            "EventKind": ("schema", "EventKind"),
            "PlanKind": ("schema", "PlanKind"),
            "PlannedAction": ("schema", "PlannedAction"),
            "RolloutQuery": ("schema", "RolloutQuery"),
            "VisibleDelta": ("schema", "VisibleDelta"),
            "VisibleHistory": ("schema", "VisibleHistory"),
            "CandidateStateInput": ("state", "CandidateStateInput"),
            "SealedState": ("state", "SealedState"),
            "StateClass": ("state", "StateClass"),
            "StatePayload": ("state", "StatePayload"),
        },
        "compliance": {
            "ProtocolViolation": ("canonical", "ProtocolViolation"),
            "canonical_json_bytes": ("canonical", "canonical_json_bytes"),
            "digest_json": ("canonical", "digest_json"),
            "CandidateEntrypoint": (
                "candidate_protocol",
                "CandidateEntrypoint",
            ),
            "CandidateCallViolation": (
                "candidate_protocol",
                "CandidateCallViolation",
            ),
            "DiagnoseRequest": ("candidate_protocol", "DiagnoseRequest"),
            "DiagnoseResponse": ("candidate_protocol", "DiagnoseResponse"),
            "DiagnosisResult": ("candidate_protocol", "DiagnosisResult"),
            "FreshProcessExecutor": (
                "candidate_protocol",
                "FreshProcessExecutor",
            ),
            "HeadExecution": ("candidate_protocol", "HeadExecution"),
            "InitializeRequest": ("candidate_protocol", "InitializeRequest"),
            "InvocationOutcome": ("candidate_protocol", "InvocationOutcome"),
            "Operation": ("candidate_protocol", "Operation"),
            "ResultStatus": ("candidate_protocol", "ResultStatus"),
            "RolloutRequest": ("candidate_protocol", "RolloutRequest"),
            "RolloutResponse": ("candidate_protocol", "RolloutResponse"),
            "RolloutResult": ("candidate_protocol", "RolloutResult"),
            "SequentialProcessExecutor": (
                "candidate_protocol",
                "SequentialProcessExecutor",
            ),
            "StateResponse": ("candidate_protocol", "StateResponse"),
            "UpdateRequest": ("candidate_protocol", "UpdateRequest"),
            "WorkerInvocationError": (
                "candidate_protocol",
                "WorkerInvocationError",
            ),
            "assert_shared_state_fanout": (
                "candidate_protocol",
                "assert_shared_state_fanout",
            ),
            "invoke_diagnose": ("candidate_protocol", "invoke_diagnose"),
            "invoke_rollout": ("candidate_protocol", "invoke_rollout"),
            "DiagnosisQuery": ("schema", "DiagnosisQuery"),
            "RolloutQuery": ("schema", "RolloutQuery"),
            "VisibleDelta": ("schema", "VisibleDelta"),
            "VisibleHistory": ("schema", "VisibleHistory"),
            "event_sort_key": ("schema", "event_sort_key"),
            "CandidateStateInput": ("state", "CandidateStateInput"),
            "StatePayload": ("state", "StatePayload"),
            "StateClass": ("state", "StateClass"),
            "seal_state": ("state", "seal_state"),
        },
        "mutation_matrix": {
            "ProtocolViolation": ("canonical", "ProtocolViolation"),
            "canonical_json_bytes": ("canonical", "canonical_json_bytes"),
            "digest_json": ("canonical", "digest_json"),
        },
        "mutation_evidence": {
            "ProtocolViolation": ("canonical", "ProtocolViolation"),
            "canonical_json_bytes": ("canonical", "canonical_json_bytes"),
            "digest_bytes": ("canonical", "digest_bytes"),
            "digest_json": ("canonical", "digest_json"),
            "validate_json_like": ("canonical", "validate_json_like"),
            "MutationObservation": (
                "mutation_matrix",
                "MutationObservation",
            ),
            "REGISTRY_DIGEST": ("mutation_matrix", "REGISTRY_DIGEST"),
            "ObservationOutcome": (
                "mutation_matrix",
                "ObservationOutcome",
            ),
            "SubjectKind": ("mutation_matrix", "SubjectKind"),
            "evaluate_mutation_matrix": (
                "mutation_matrix",
                "evaluate_mutation_matrix",
            ),
        },
        "mutation_runner": {
            "ProtocolViolation": ("canonical", "ProtocolViolation"),
            "canonical_json_bytes": ("canonical", "canonical_json_bytes"),
            "digest_bytes": ("canonical", "digest_bytes"),
            "digest_json": ("canonical", "digest_json"),
            "_delta_from_wire": ("candidate_protocol", "_delta_from_wire"),
            "_diagnosis_query_from_wire": (
                "candidate_protocol",
                "_diagnosis_query_from_wire",
            ),
            "_history_from_wire": ("candidate_protocol", "_history_from_wire"),
            "_rollout_query_from_wire": (
                "candidate_protocol",
                "_rollout_query_from_wire",
            ),
            "ComplianceFinding": ("compliance", "ComplianceFinding"),
            "ComplianceVerdict": ("compliance", "ComplianceVerdict"),
            "control_entrypoint": ("compliance", "control_entrypoint"),
            "evaluate_candidate_compliance": (
                "compliance",
                "evaluate_candidate_compliance",
            ),
            "MutationObservation": (
                "mutation_matrix",
                "MutationObservation",
            ),
            "ObservationOutcome": (
                "mutation_matrix",
                "ObservationOutcome",
            ),
            "SubjectKind": ("mutation_matrix", "SubjectKind"),
            "evaluate_mutation_matrix": (
                "mutation_matrix",
                "evaluate_mutation_matrix",
            ),
            "BENCHMARK_ID": ("mutation_evidence", "BENCHMARK_ID"),
            "MutationEvidenceBuilder": (
                "mutation_evidence",
                "MutationEvidenceBuilder",
            ),
            "MutationEvidenceBundle": (
                "mutation_evidence",
                "MutationEvidenceBundle",
            ),
            "portable_runner_contract": (
                "mutation_evidence",
                "portable_runner_contract",
            ),
        },
        "schema": {
            "ProtocolViolation": ("canonical", "ProtocolViolation"),
            "canonical_json_bytes": ("canonical", "canonical_json_bytes"),
            "digest_json": ("canonical", "digest_json"),
            "reject_privileged_keys": (
                "canonical",
                "reject_privileged_keys",
            ),
            "validate_json_like": ("canonical", "validate_json_like"),
        },
        "state": {
            "ProtocolViolation": ("canonical", "ProtocolViolation"),
            "canonical_json_bytes": ("canonical", "canonical_json_bytes"),
            "domain_digest": ("canonical", "domain_digest"),
        },
    }
    bound: list[dict[str, str]] = []
    for consumer_name, aliases in specs.items():
        consumer = modules[consumer_name]
        for alias, (owner_name, owner_attribute) in aliases.items():
            owner = modules[owner_name]
            actual = getattr(consumer, alias, None)
            expected = getattr(owner, owner_attribute, None)
            if actual is not expected:
                raise ProtocolViolation(
                    f"critical alias identity mismatch: {consumer_name}.{alias}"
                )
            bound.append(
                {
                    "consumer": f"{consumer.__name__}.{alias}",
                    "owner": f"{owner.__name__}.{owner_attribute}",
                }
            )
    return bound


def _source_binding_witness(
    control_class_name: str,
    semantic_probes: frozenset[str],
    *,
    execution_seed: int | None = None,
    expected_runtime_import_cache_contract_digest: str | None = None,
) -> dict[str, Any]:
    """Return the canonical live implementation transcript for one control."""

    if execution_seed is not None and (
        type(execution_seed) is not int or not 0 <= execution_seed < 2**64
    ):
        raise ProtocolViolation("source witness execution_seed must be uint64 or null")

    from . import (
        candidate_protocol,
        canonical,
        compliance,
        mutation_evidence,
        mutation_matrix,
        schema,
        state,
    )

    # Direct callers of the source witness receive the same prewarm protection
    # as the batch runner.  The returned summary is committed below, so a cache
    # cannot be populated once and then silently widened between executions.
    runtime_import_cache = (
        _prepare_runtime_import_cache()
        if expected_runtime_import_cache_contract_digest is None
        else _verify_runtime_import_cache(
            expected_runtime_import_cache_contract_digest
        )
    )

    runner_module = sys.modules.get(__name__)
    if runner_module is None:
        raise ProtocolViolation("cannot resolve mutation runner source module")
    bound_modules = {
        "canonical": canonical,
        "candidate_protocol": candidate_protocol,
        "compliance": compliance,
        "mutation_evidence": mutation_evidence,
        "mutation_matrix": mutation_matrix,
        "schema": schema,
        "state": state,
        "mutation_runner": runner_module,
    }
    # Perform identity validation before inspecting the selected class or any
    # live module namespace.  This keeps a synchronized clone with a malicious
    # metaclass from executing during source-evidence construction.
    source_identity_anchors = _source_identity_anchor_contract(bound_modules)
    external_attribute_identities = _external_attribute_identity_contract(
        candidate_protocol=candidate_protocol,
        canonical=canonical,
        compliance=compliance,
    )
    external_global_dispatch = _external_global_dispatch_contract(
        candidate_protocol=candidate_protocol
    )
    external_class_surfaces = _external_class_surface_contract(
        candidate_protocol=candidate_protocol
    )
    external_runtime_object_identities = (
        _external_runtime_object_identity_contract(
            candidate_protocol=candidate_protocol
        )
    )
    external_runtime_values = _external_runtime_value_contract(
        candidate_protocol=candidate_protocol
    )
    value = getattr(compliance, control_class_name, None)
    if type(value) is not type:
        raise ProtocolViolation(f"unknown portable control {control_class_name!r}")
    mro_sources = [
        {
            "qualified_name": f"{base.__module__}.{base.__qualname__}",
            "class_contract": _registered_class_binding(
                base, f"control_mro.{base.__qualname__}"
            ),
            "source_digest": digest_bytes(inspect.getsource(base).encode("utf-8")),
            "live_method_code_digests": {
                name: _live_callable_digest(member, f"{base.__qualname__}.{name}")
                for name, member in sorted(base.__dict__.items())
                if inspect.isfunction(member)
            },
        }
        for base in value.__mro__
        if base.__module__ == compliance.__name__
    ]
    module_source_digests = {
        name: digest_bytes(inspect.getsource(module).encode("utf-8"))
        for name, module in bound_modules.items()
    }
    live_module_code_bindings = {
        name: _live_module_code_binding(module)
        for name, module in bound_modules.items()
    }
    detector_names = (
        "_recovers_full_history",
        "_head_behavior",
        "_semantic_behavior_projection",
        "_semantic_behavior_equal",
        "_report",
        "evaluate_candidate_compliance",
    )
    live_detector_code_digests = {
        name: _live_callable_digest(getattr(compliance, name), name)
        for name in detector_names
    }
    live_protocol_code_digests = {
        "FreshProcessExecutor.invoke": _live_callable_digest(
            candidate_protocol.FreshProcessExecutor.invoke,
            "FreshProcessExecutor.invoke",
        ),
        "_worker_main": _live_callable_digest(
            candidate_protocol._worker_main, "_worker_main"
        ),
        "SequentialProcessExecutor.invoke_sequence": _live_callable_digest(
            candidate_protocol.SequentialProcessExecutor.invoke_sequence,
            "SequentialProcessExecutor.invoke_sequence",
        ),
        "_session_worker_main": _live_callable_digest(
            candidate_protocol._session_worker_main, "_session_worker_main"
        ),
        "_CandidateAuditBoundary.__call__": _live_callable_digest(
            candidate_protocol._CandidateAuditBoundary.__call__,
            "_CandidateAuditBoundary.__call__",
        ),
    }
    live_runtime_constants = {
        "runner_protocol": RUNNER_PROTOCOL,
        "portable_compliance_probe_timeout_seconds": (
            compliance.PORTABLE_COMPLIANCE_PROBE_TIMEOUT_SECONDS
        ),
        "semantic_abs_tolerance": compliance.SEMANTIC_ABS_TOLERANCE,
        "semantic_rel_tolerance": compliance.SEMANTIC_REL_TOLERANCE,
        "history_max_payload_bytes": compliance._HISTORY_MAX_PAYLOAD_BYTES,
        "history_max_depth": compliance._HISTORY_MAX_DEPTH,
        "history_max_nodes": compliance._HISTORY_MAX_NODES,
        "history_max_strings": compliance._HISTORY_MAX_STRINGS,
        "history_max_string_chars": compliance._HISTORY_MAX_STRING_CHARS,
        "history_max_decode_attempts": compliance._HISTORY_MAX_DECODE_ATTEMPTS,
        "history_max_total_compressed_bytes": (
            compliance._HISTORY_MAX_TOTAL_COMPRESSED_BYTES
        ),
        "history_max_single_expanded_bytes": (
            compliance._HISTORY_MAX_SINGLE_EXPANDED_BYTES
        ),
        "history_max_total_expanded_bytes": (
            compliance._HISTORY_MAX_TOTAL_EXPANDED_BYTES
        ),
        "request_protocol": candidate_protocol.REQUEST_PROTOCOL,
        "response_protocol": candidate_protocol.RESPONSE_PROTOCOL,
        "worker_protocol": candidate_protocol.WORKER_PROTOCOL,
        "session_worker_protocol": candidate_protocol.SESSION_WORKER_PROTOCOL,
        "session_request_protocol": candidate_protocol.SESSION_REQUEST_PROTOCOL,
        "import_inventory_protocol": candidate_protocol.IMPORT_INVENTORY_PROTOCOL,
        "runtime_import_closure_protocol": (
            candidate_protocol.RUNTIME_IMPORT_CLOSURE_PROTOCOL
        ),
        "runtime_binding_kind": candidate_protocol.RUNTIME_BINDING_KIND,
        "harness_bundle_protocol": candidate_protocol.HARNESS_BUNDLE_PROTOCOL,
        "bootstrap_protocol": candidate_protocol.BOOTSTRAP_PROTOCOL,
        "max_session_requests": candidate_protocol.MAX_SESSION_REQUESTS,
        "max_session_frame_bytes": candidate_protocol.MAX_SESSION_FRAME_BYTES,
    }
    freeze_critical_runtime_contract = _freeze_critical_runtime_contract(
        candidate_protocol=candidate_protocol,
        compliance=compliance,
        mutation_evidence=mutation_evidence,
        mutation_matrix=mutation_matrix,
        runner_module=runner_module,
        schema=schema,
        state=state,
    )
    critical_alias_identities = _critical_alias_identity_contract(
        candidate_protocol=candidate_protocol,
        canonical=canonical,
        compliance=compliance,
        mutation_evidence=mutation_evidence,
        mutation_matrix=mutation_matrix,
        runner_module=runner_module,
        schema=schema,
        state=state,
    )
    expected_live_execution_binding = _expected_live_execution_binding(
        control_class_name
    )
    expected_entrypoint = compliance.control_entrypoint(control_class_name)
    expected_candidate = (
        f"{expected_entrypoint.module}:{expected_entrypoint.qualname}"
    )
    return {
        "protocol": "ucm-portable-control-source-binding/17",
        "control": control_class_name,
        "execution_seed": execution_seed,
        "control_mro": mro_sources,
        "source_identity_anchors": source_identity_anchors,
        "external_attribute_identities": external_attribute_identities,
        "external_global_dispatch": external_global_dispatch,
        "external_class_surfaces": external_class_surfaces,
        "external_runtime_object_identities": external_runtime_object_identities,
        "external_runtime_values": external_runtime_values,
        "runtime_import_cache": runtime_import_cache,
        "module_source_digests": module_source_digests,
        "live_module_code_bindings": live_module_code_bindings,
        "live_detector_code_digests": live_detector_code_digests,
        "live_protocol_code_digests": live_protocol_code_digests,
        "live_runtime_constants": live_runtime_constants,
        "freeze_critical_runtime_contract": freeze_critical_runtime_contract,
        "critical_alias_identities": critical_alias_identities,
        "expected_candidate": expected_candidate,
        "expected_live_execution_binding": expected_live_execution_binding,
        "portable_runner_contract": portable_runner_contract(RUNNER_PROTOCOL),
        "semantic_probe_contract": compliance.PORTABLE_SEMANTIC_PROBE_PROTOCOL,
        "enabled_semantic_probes": sorted(semantic_probes),
        "runtime_metadata": _runtime_metadata(),
    }


def _source_digest(
    control_class_name: str, semantic_probes: frozenset[str]
) -> str:
    """Digest :func:`_source_binding_witness` using canonical JSON bytes."""

    return digest_json(_source_binding_witness(control_class_name, semantic_probes))


def _decisive_finding(
    findings: tuple[ComplianceFinding, ...], expected_failure_code: str
) -> ComplianceFinding | None:
    matches = [
        finding
        for finding in findings
        if finding.verdict is ComplianceVerdict.FAIL
        and finding.failure_code == expected_failure_code
    ]
    if len(matches) > 1:
        # Ambiguous duplicates are not silently selected because the matrix is
        # supposed to point to one decisive detector record.
        raise ProtocolViolation(
            f"multiple decisive findings for {expected_failure_code}"
        )
    return matches[0] if matches else None


def _finding_gate_tokens(finding: ComplianceFinding) -> frozenset[str]:
    return frozenset(
        token
        for token in finding.gate.replace("/", " ").replace("-", " ").split()
        if len(token) == 3 and token.startswith("C") and token[1:].isdigit()
    )


def _typed_execution_error(stage: str, error: Exception) -> dict[str, str]:
    """Return a JSON-only error record without losing its execution stage."""

    try:
        message = str(error)
    except Exception as rendering_error:
        message = (
            "unrenderable exception message: "
            f"{type(rendering_error).__module__}.{type(rendering_error).__qualname__}"
        )
    try:
        message.encode("utf-8")
    except UnicodeEncodeError:
        message = message.encode("utf-8", "backslashreplace").decode("utf-8")
    return {
        "stage": stage,
        "exception_type": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": message,
    }


def _execution_input_wire(
    history: VisibleHistory,
    diagnosis_query: DiagnosisQuery,
    rollout_query: RolloutQuery,
    delta: VisibleDelta | None,
) -> dict[str, Any]:
    """Return the exact runner input preimage without retaining caller aliases."""

    if type(history) is not VisibleHistory:
        raise ProtocolViolation("runner history must be an exact VisibleHistory")
    if type(diagnosis_query) is not DiagnosisQuery:
        raise ProtocolViolation(
            "runner diagnosis_query must be an exact DiagnosisQuery"
        )
    if type(rollout_query) is not RolloutQuery:
        raise ProtocolViolation("runner rollout_query must be an exact RolloutQuery")
    if delta is not None and type(delta) is not VisibleDelta:
        raise ProtocolViolation("runner delta must be an exact VisibleDelta or null")
    return {
        "history": history.to_wire(),
        "diagnosis_query": diagnosis_query.to_wire(),
        "rollout_query": rollout_query.to_wire(),
        "delta": None if delta is None else delta.to_wire(),
    }


def _decode_execution_input_snapshot(snapshot: bytes) -> dict[str, Any]:
    """Decode one canonical immutable input snapshot into detached inert data."""

    if type(snapshot) is not bytes:
        raise ProtocolViolation("runner input snapshot must be exact bytes")
    from . import candidate_protocol

    try:
        payload = candidate_protocol.json.loads(snapshot)
    except Exception as error:
        raise ProtocolViolation("runner input snapshot is not valid JSON") from error
    if type(payload) is not dict or set(payload) != {
        "history",
        "diagnosis_query",
        "rollout_query",
        "delta",
    }:
        raise ProtocolViolation("runner input snapshot has an invalid closed schema")
    if canonical_json_bytes(payload) != snapshot:
        raise ProtocolViolation("runner input snapshot is not canonical JSON bytes")
    return payload


def _fresh_execution_inputs(
    snapshot: bytes,
) -> tuple[VisibleHistory, DiagnosisQuery, RolloutQuery, VisibleDelta | None]:
    """Reparse a fresh typed copy from the same immutable canonical snapshot."""

    payload = _decode_execution_input_snapshot(snapshot)
    history = _history_from_wire(payload["history"])
    diagnosis_query = _diagnosis_query_from_wire(payload["diagnosis_query"])
    rollout_query = _rollout_query_from_wire(payload["rollout_query"])
    delta_payload = payload["delta"]
    delta = None if delta_payload is None else _delta_from_wire(delta_payload)
    if (
        type(history) is not VisibleHistory
        or type(diagnosis_query) is not DiagnosisQuery
        or type(rollout_query) is not RolloutQuery
        or (delta is not None and type(delta) is not VisibleDelta)
    ):
        raise ProtocolViolation("runner input reparse returned an inexact schema type")
    if canonical_json_bytes(
        _execution_input_wire(history, diagnosis_query, rollout_query, delta)
    ) != snapshot:
        raise ProtocolViolation("runner input typed reparse did not round-trip exactly")
    return history, diagnosis_query, rollout_query, delta


def _assert_execution_inputs_unchanged(
    snapshot: bytes,
    execution_inputs: tuple[
        VisibleHistory,
        DiagnosisQuery,
        RolloutQuery,
        VisibleDelta | None,
    ],
) -> None:
    """Prove one execution did not mutate its detached typed input copy."""

    if type(execution_inputs) is not tuple or len(execution_inputs) != 4:
        raise ProtocolViolation("runner execution inputs are not one exact 4-tuple")
    if canonical_json_bytes(_execution_input_wire(*execution_inputs)) != snapshot:
        raise ProtocolViolation(
            "runner execution mutated its canonical input snapshot copy"
        )


def _execution_input_incomplete_error(
    stage: str, error: Exception
) -> dict[str, str]:
    """Retain the typed cause while classifying input closure as E003."""

    typed_error = _typed_execution_error(stage, error)
    return {
        "stage": stage,
        "exception_type": "UCM-E003-HARNESS_INCOMPLETE",
        "message": (
            f"{typed_error['exception_type']}: {typed_error['message']}"
        ),
    }


def _attempt_source_witness(
    control_class_name: str,
    semantic_probes: frozenset[str],
    *,
    stage: str,
    execution_seed: int,
    runtime_import_cache_contract_digest: str | None,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Capture one live witness, returning a typed unavailable preimage on error."""

    try:
        if runtime_import_cache_contract_digest is None:
            witness = _source_binding_witness(
                control_class_name,
                semantic_probes,
                execution_seed=execution_seed,
            )
        else:
            witness = _source_binding_witness(
                control_class_name,
                semantic_probes,
                execution_seed=execution_seed,
                expected_runtime_import_cache_contract_digest=(
                    runtime_import_cache_contract_digest
                ),
            )
        expected_entrypoint = control_entrypoint(control_class_name)
        expected_candidate = (
            f"{expected_entrypoint.module}:{expected_entrypoint.qualname}"
        )
        if witness.get("control") != control_class_name:
            raise ProtocolViolation("source witness control identity drifted")
        if witness.get("execution_seed") != execution_seed:
            raise ProtocolViolation("source witness execution seed drifted")
        if witness.get("expected_candidate") != expected_candidate:
            raise ProtocolViolation("source witness candidate identity drifted")
        if witness.get("enabled_semantic_probes") != sorted(semantic_probes):
            raise ProtocolViolation("source witness semantic probe set drifted")
        digest_json(witness)
        return witness, None
    except Exception as error:
        return (
            {
                **_unavailable_source_witness(stage, error),
                "control": control_class_name,
                "execution_seed": execution_seed,
                "enabled_semantic_probes": sorted(semantic_probes),
            },
            _typed_execution_error(stage, error),
        )


def _validate_complete_report_transcript(
    transcript: dict[str, Any],
    *,
    pre_source_witness: dict[str, Any],
    post_source_witness: dict[str, Any],
    expected_head_record_shape: str,
) -> None:
    """Reject a report that cannot support a raw decisive observation."""

    required_fields = {
        "runner_protocol",
        "control_class_name",
        "expected_candidate",
        "execution_seed",
        "candidate",
        "operational_state_closure",
        "semantic_unity",
        "isolation_completeness",
        "isolation_assurance",
        "failure_codes",
        "candidate_bundle_digest",
        "candidate_model_digest",
        "harness_bundle_digest",
        "import_inventory_digest",
        "module_origin",
        "execution_binding",
        "execution_binding_error",
        "pre_source_witness_digest",
        "post_source_witness_digest",
        "post_source_witness_error",
        "harness_stable_during_execution",
        "findings",
        "head_records",
        "paired_semantic_equivalence",
        "input_preimage_digest",
        "invocation_transcript_digest",
        "request_records",
    }
    if set(transcript) != required_fields:
        raise ProtocolViolation("report transcript does not have its exact 27 fields")
    if transcript["runner_protocol"] != RUNNER_PROTOCOL:
        raise ProtocolViolation("report transcript runner protocol drifted")
    for label in ("control_class_name", "expected_candidate", "isolation_assurance"):
        value = transcript[label]
        if type(value) is not str or not value or value.strip() != value:
            raise ProtocolViolation(f"report transcript {label} is not canonical")
    if transcript["candidate"] != transcript["expected_candidate"]:
        raise ProtocolViolation("report candidate differs from expected candidate")
    execution_seed = transcript["execution_seed"]
    if type(execution_seed) is not int or not 0 <= execution_seed < 2**64:
        raise ProtocolViolation("report execution seed must be uint64")
    for verdict_field in (
        "operational_state_closure",
        "semantic_unity",
        "isolation_completeness",
    ):
        if transcript[verdict_field] not in {"pass", "fail", "incomplete"}:
            raise ProtocolViolation(f"report {verdict_field} has an unknown verdict")

    _exact_digest(
        transcript["input_preimage_digest"],
        "report transcript input_preimage_digest",
    )
    request_records = transcript["request_records"]
    request_record_fields = {
        "operation",
        "seed",
        "execution_mode",
        "status",
        "request_wire",
        "request_digest",
        "request_fully_sent",
        "received_request_digest",
        "response_wire",
        "response_digest",
        "failure_origin",
        "failure_code",
    }
    if type(request_records) is not list:
        raise ProtocolViolation("report request_records must be an exact list")
    if not request_records:
        raise ProtocolViolation(
            "report request_records cannot prove that candidate execution started"
        )
    for index, request_record in enumerate(request_records):
        if type(request_record) is not dict or set(request_record) != request_record_fields:
            raise ProtocolViolation(
                f"report request record {index} is not one exact 12-field record"
            )
        canonical_json_bytes(request_record)
    invocation_transcript_digest = digest_json(request_records)
    _exact_digest(
        transcript["invocation_transcript_digest"],
        "report transcript invocation_transcript_digest",
    )
    if transcript["invocation_transcript_digest"] != invocation_transcript_digest:
        raise ProtocolViolation("report invocation transcript digest drifted")

    findings = transcript["findings"]
    failure_codes = transcript["failure_codes"]
    if type(findings) is not list or type(failure_codes) is not list:
        raise ProtocolViolation("report findings/failure_codes must be exact lists")
    derived_failure_codes: list[str] = []
    for index, finding in enumerate(findings):
        if type(finding) is not dict or set(finding) != {
            "gate",
            "verdict",
            "failure_code",
            "detail",
            "evidence",
        }:
            raise ProtocolViolation(f"report finding {index} is not a closed record")
        gate = finding["gate"]
        if type(gate) is not str or not gate or gate.strip() != gate:
            raise ProtocolViolation(f"report finding {index} gate is not canonical")
        verdict = finding["verdict"]
        if verdict not in {"pass", "fail", "incomplete"}:
            raise ProtocolViolation(f"report finding {index} has an unknown verdict")
        failure_code = finding["failure_code"]
        if failure_code is not None and (
            type(failure_code) is not str
            or not failure_code
            or failure_code.strip() != failure_code
        ):
            raise ProtocolViolation(
                f"report finding {index} failure code is not canonical"
            )
        if verdict == "fail":
            if failure_code is None:
                raise ProtocolViolation(
                    f"report failed finding {index} lacks a failure code"
                )
            if failure_code not in derived_failure_codes:
                derived_failure_codes.append(failure_code)
        elif verdict == "pass" and failure_code is not None:
            raise ProtocolViolation(
                f"report passed finding {index} carries a failure code"
            )
        detail = finding["detail"]
        if type(detail) is not str:
            raise ProtocolViolation(f"report finding {index} detail is not a string")
        detail.encode("utf-8")
        if type(finding["evidence"]) is not dict:
            raise ProtocolViolation(f"report finding {index} evidence is not an object")
    if failure_codes != derived_failure_codes:
        raise ProtocolViolation(
            "report failure_codes differ from ordered unique failed findings"
        )

    binding = transcript["execution_binding"]
    binding_keys = {
        "candidate_bundle_digest",
        "candidate_model_digest",
        "harness_bundle_digest",
        "import_inventory_digest",
        "module_origin",
    }
    if type(binding) is not dict or set(binding) != binding_keys:
        raise ProtocolViolation("report execution binding is not closed")
    if transcript["execution_binding_error"] is not None:
        raise ProtocolViolation("report execution binding is incomplete")
    for field_name in binding_keys:
        if transcript[field_name] != binding[field_name]:
            raise ProtocolViolation(f"report top-level {field_name} binding drifted")
    for digest_field in binding_keys.difference({"module_origin"}):
        _exact_digest(binding[digest_field], f"report binding {digest_field}")

    if pre_source_witness.get("control") != transcript["control_class_name"]:
        raise ProtocolViolation("report control differs from its pre witness")
    if pre_source_witness.get("expected_candidate") != transcript["candidate"]:
        raise ProtocolViolation("report candidate differs from its pre witness")
    if pre_source_witness.get("execution_seed") != execution_seed:
        raise ProtocolViolation("report seed differs from its pre witness")
    if pre_source_witness.get("expected_live_execution_binding") != binding:
        raise ProtocolViolation("report binding differs from its pre witness")
    if transcript["post_source_witness_error"] is not None:
        raise ProtocolViolation("report has a post-source witness error")
    if digest_json(pre_source_witness) != digest_json(post_source_witness):
        raise ProtocolViolation("report pre/post source witnesses drifted")
    if transcript["harness_stable_during_execution"] is not True:
        raise ProtocolViolation("report does not prove stable harness execution")
    if transcript["pre_source_witness_digest"] != digest_json(pre_source_witness):
        raise ProtocolViolation("report pre-source witness digest drifted")
    if transcript["post_source_witness_digest"] != digest_json(post_source_witness):
        raise ProtocolViolation("report post-source witness digest drifted")

    head_records = transcript["head_records"]
    head_keys = binding_keys | {
        "consumed_state_hash",
        "isolation",
        "operation",
        "request_digest",
        "response_digest",
        "seed",
    }
    if expected_head_record_shape == "empty":
        if type(head_records) is not list or head_records:
            raise ProtocolViolation(
                "report head_records differ from the code-owned empty shape"
            )
        return
    if expected_head_record_shape != "replay_ddrr":
        raise ProtocolViolation("unknown code-owned head record shape")
    if type(head_records) is not list or len(head_records) != 4:
        raise ProtocolViolation(
            "report head_records must contain exactly two diagnose and two rollout records"
        )
    observed_operations: list[tuple[str, int]] = []
    for index, head_record in enumerate(head_records):
        if type(head_record) is not dict or set(head_record) != head_keys:
            raise ProtocolViolation(f"report head record {index} is not closed")
        if any(head_record[field] != binding[field] for field in binding_keys):
            raise ProtocolViolation(f"report head record {index} binding drifted")
        operation = head_record["operation"]
        expected_seed = {
            "diagnose": execution_seed + 1,
            "rollout": execution_seed + 2,
        }.get(operation)
        if type(head_record["seed"]) is not int or head_record["seed"] != expected_seed:
            raise ProtocolViolation(
                f"report head record {index} operation/seed binding drifted"
            )
        observed_operations.append((operation, head_record["seed"]))
        for digest_field in (
            "consumed_state_hash",
            "request_digest",
            "response_digest",
        ):
            _exact_digest(
                head_record[digest_field],
                f"report head record {index} {digest_field}",
            )
        isolation = head_record["isolation"]
        if type(isolation) is not str or not isolation or isolation.strip() != isolation:
            raise ProtocolViolation(
                f"report head record {index} isolation is not canonical"
            )
    expected_operations = [
        ("diagnose", execution_seed + 1),
        ("diagnose", execution_seed + 1),
        ("rollout", execution_seed + 2),
        ("rollout", execution_seed + 2),
    ]
    if sorted(observed_operations) != sorted(expected_operations):
        raise ProtocolViolation("report replay operation/seed multiset drifted")


def _complete_report_transcript(
    report: Any,
    *,
    control_class_name: str,
    expected_candidate: str,
    execution_seed: int,
    execution_binding: dict[str, str],
    execution_binding_error: str | None,
    pre_source_witness: dict[str, Any],
    post_source_witness: dict[str, Any],
    post_source_witness_error: dict[str, str] | None,
    paired_semantic_equivalence: dict[str, Any] | None,
    input_preimage_digest: str,
) -> dict[str, Any]:
    """Materialize every scored field of one compliance report as raw JSON."""

    request_record_view = report.request_records
    if type(request_record_view) is not tuple:
        raise ProtocolViolation(
            "compliance report request_records must be an exact immutable tuple view"
        )
    request_records = list(request_record_view)
    # The report property returns a fresh decode of its immutable byte snapshot.
    # Preserve that exact ordered view; never regenerate planned calls from the
    # input or the code-owned runner contract.
    canonical_json_bytes(request_records)
    invocation_transcript_digest = digest_json(request_records)
    transcript = {
        "runner_protocol": RUNNER_PROTOCOL,
        "control_class_name": control_class_name,
        "expected_candidate": expected_candidate,
        "execution_seed": execution_seed,
        "candidate": report.candidate,
        "operational_state_closure": report.operational_state_closure.value,
        "semantic_unity": report.semantic_unity.value,
        "isolation_completeness": report.isolation_completeness.value,
        "isolation_assurance": report.isolation_assurance,
        "failure_codes": list(report.failure_codes),
        "candidate_bundle_digest": getattr(
            report, "candidate_bundle_digest", None
        ),
        "candidate_model_digest": getattr(report, "candidate_model_digest", None),
        "harness_bundle_digest": getattr(report, "harness_bundle_digest", None),
        "import_inventory_digest": getattr(report, "import_inventory_digest", None),
        "module_origin": getattr(report, "module_origin", None),
        "execution_binding": execution_binding,
        "execution_binding_error": execution_binding_error,
        "pre_source_witness_digest": digest_json(pre_source_witness),
        "post_source_witness_digest": digest_json(post_source_witness),
        "post_source_witness_error": post_source_witness_error,
        "harness_stable_during_execution": (
            post_source_witness_error is None
            and digest_json(pre_source_witness) == digest_json(post_source_witness)
        ),
        "findings": [_finding_wire(finding) for finding in report.findings],
        "head_records": list(report.head_records),
        "paired_semantic_equivalence": paired_semantic_equivalence,
        "input_preimage_digest": input_preimage_digest,
        "invocation_transcript_digest": invocation_transcript_digest,
        "request_records": request_records,
    }
    # Canonical materialization is separate from decisive eligibility.  A
    # complete but ineligible report (for example, an early failure with no
    # replay heads) is retained as raw evidence and later classified CRASHED.
    digest_json(transcript)
    return transcript


def _raw_source_record(
    *,
    pre_source_witness: dict[str, Any],
    post_source_witness: dict[str, Any],
    execution_binding: dict[str, str],
    harness_stable: bool,
) -> dict[str, Any]:
    executed = _execution_bound_source_witness(
        pre_source_witness, execution_binding
    )
    return {
        "runner_protocol": RUNNER_PROTOCOL,
        "execution_bound_source_witness": executed,
        "execution_bound_source_witness_digest": digest_json(executed),
        "pre_source_witness_digest": digest_json(pre_source_witness),
        "post_source_witness_digest": digest_json(post_source_witness),
        "harness_stable_during_execution": harness_stable,
    }


def _preflight_decisive_record(
    *,
    run_id: str,
    base_seed: int,
    input_preimage: dict[str, Any],
    execution_context: dict[str, Any],
    record_kwargs: dict[str, Any],
) -> None:
    """Apply the bundle's full code-owned validator before claiming a decision."""

    preflight = MutationEvidenceBuilder(
        run_id=run_id,
        runner_protocol=RUNNER_PROTOCOL,
        base_seed=base_seed,
        input_preimage=input_preimage,
        execution_context=execution_context,
    )
    preflight.add_record(**record_kwargs)
    preflight.finalize()


def run_portable_mutation_evidence(
    *,
    run_id: str,
    history: VisibleHistory,
    diagnosis_query: DiagnosisQuery,
    rollout_query: RolloutQuery,
    delta: VisibleDelta | None = None,
    seed: int,
) -> MutationEvidenceBundle:
    """Execute the portable matrix once and retain every canonical preimage."""

    from . import candidate_protocol, compliance

    # MutationObservation uses a uint128 storage field, but the executable
    # candidate protocol is deliberately uint64.  Every compliance execution
    # derives up to three additional operation seeds, so reject a base seed
    # that this producer could not actually send on its last row.
    if type(run_id) is not str or not run_id or run_id.strip() != run_id:
        raise ProtocolViolation("run_id must be a canonical non-empty string")
    if type(seed) is not int or seed < 0:
        raise ProtocolViolation(
            "seed and all derived operation seeds must fit unsigned 64-bit integer"
        )
    code_owned_contract = portable_runner_contract(RUNNER_PROTOCOL)
    active_mutant_rows, active_control_rows = _active_portable_execution_rows(
        code_owned_contract
    )
    code_owned_rows = (
        code_owned_contract["mutation_cases"]
        + code_owned_contract["specificity_cases"]
    )
    for row_index, row in enumerate(code_owned_rows):
        if type(row) is not dict or type(row.get("semantic_probes")) is not list:
            raise ProtocolViolation("code-owned portable semantic probes are malformed")
        semantic_probes = row["semantic_probes"]
        execution_seed = seed + row_index
        if execution_seed + 3 >= 2**64:
            raise ProtocolViolation(
                "seed and all derived operation seeds must fit unsigned 64-bit integer"
            )
        if (
            "update_consistency" in semantic_probes
            and (
                execution_seed
                ^ code_owned_contract["update_consistency_lineage_xor_mask"]
            )
            + 2
            >= 2**64
        ):
            raise ProtocolViolation(
                "update-consistency lineage seeds must fit unsigned 64-bit integer"
            )

    try:
        runtime_import_cache_baseline = _prepare_runtime_import_cache()
        runtime_import_cache_baseline_digest = digest_json(
            runtime_import_cache_baseline
        )
        source_preparation_error: Exception | None = None
        source_preparation_record: dict[str, str] | None = None
    except Exception as error:
        # The failed preparation is captured in the same-run context and every
        # row.  No candidate starts, but the finally path below still attempts
        # a post witness; no candidate is ever rerun to manufacture evidence.
        runtime_import_cache_baseline_digest = None
        source_preparation_error = error
        source_preparation_record = _typed_execution_error(
            "runtime-import-preparation", error
        )

    # This is the only read of caller-owned input objects.  The canonical bytes
    # are the execution authority as well as the bundle preimage.  Reparse once
    # now to fail closed on schema/type/round-trip drift, then deliberately drop
    # every caller reference.  Each execution below reparses its own fresh copy
    # from these immutable bytes, so nested payload/parameters dicts cannot
    # create capture-A/use-B or cross-row aliasing.
    input_snapshot = canonical_json_bytes(
        _execution_input_wire(history, diagnosis_query, rollout_query, delta)
    )
    input_preimage = _decode_execution_input_snapshot(input_snapshot)
    _fresh_execution_inputs(input_snapshot)
    del history, diagnosis_query, rollout_query, delta
    execution_context = {
        "benchmark_id": BENCHMARK_ID,
        "runtime_metadata": _runtime_metadata(),
        "portable_runner_contract": code_owned_contract,
        "runtime_import_cache_contract_digest": (
            runtime_import_cache_baseline_digest
        ),
        "source_preparation_error": source_preparation_record,
    }
    builder = MutationEvidenceBuilder(
        run_id=run_id,
        runner_protocol=RUNNER_PROTOCOL,
        base_seed=seed,
        input_preimage=input_preimage,
        execution_context=execution_context,
    )
    input_preimage_digest = builder.input_preimage_digest

    for row_index, case, expected_head_record_shape in active_mutant_rows:
        execution_seed = seed + row_index
        errors: list[dict[str, str]] = []
        if source_preparation_record is not None:
            errors.append(source_preparation_record)
            pre_source_witness = {
                **_unavailable_source_witness(
                    "pre-execution", source_preparation_error
                ),
                "control": case.control_class_name,
                "execution_seed": execution_seed,
                "enabled_semantic_probes": sorted(case.semantic_probes),
            }
            pre_source_error = _typed_execution_error(
                "pre-execution", source_preparation_error
            )
            errors.append(pre_source_error)
        else:
            pre_source_witness, pre_source_error = _attempt_source_witness(
                case.control_class_name,
                case.semantic_probes,
                stage="pre-execution",
                execution_seed=execution_seed,
                runtime_import_cache_contract_digest=(
                    runtime_import_cache_baseline_digest
                ),
            )
            if pre_source_error is not None:
                errors.append(pre_source_error)

        report: Any | None = None
        expected_candidate: str | None = None
        execution_input_closure_ok = True
        try:
            if pre_source_error is None:
                try:
                    execution_inputs = _fresh_execution_inputs(input_snapshot)
                except Exception as error:
                    execution_input_closure_ok = False
                    errors.append(
                        _execution_input_incomplete_error(
                            "execution-input-reparse", error
                        )
                    )
                else:
                    try:
                        entrypoint = control_entrypoint(case.control_class_name)
                        expected_candidate = (
                            f"{entrypoint.module}:{entrypoint.qualname}"
                        )
                        report = evaluate_candidate_compliance(
                            entrypoint,
                            history=execution_inputs[0],
                            diagnosis_query=execution_inputs[1],
                            rollout_query=execution_inputs[2],
                            delta=execution_inputs[3],
                            seed=execution_seed,
                            semantic_probes=case.semantic_probes,
                        )
                        if report is None:
                            raise ProtocolViolation(
                                "candidate compliance evaluator returned no report"
                            )
                    except Exception as error:
                        errors.append(
                            _typed_execution_error("candidate-evaluation", error)
                        )
                    finally:
                        try:
                            _assert_execution_inputs_unchanged(
                                input_snapshot, execution_inputs
                            )
                        except Exception as error:
                            execution_input_closure_ok = False
                            errors.append(
                                _execution_input_incomplete_error(
                                    "execution-input-postcondition", error
                                )
                            )
        finally:
            post_source_witness, post_source_error = _attempt_source_witness(
                case.control_class_name,
                case.semantic_probes,
                stage="post-execution",
                execution_seed=execution_seed,
                runtime_import_cache_contract_digest=(
                    runtime_import_cache_baseline_digest
                ),
            )
            if post_source_error is not None:
                errors.append(post_source_error)

        harness_stable = (
            pre_source_error is None
            and post_source_error is None
            and digest_json(pre_source_witness) == digest_json(post_source_witness)
        )
        if (
            pre_source_error is None
            and post_source_error is None
            and not harness_stable
        ):
            errors.append(
                {
                    "stage": "post-execution",
                    "exception_type": "UCM-E003-HARNESS_INCOMPLETE",
                    "message": "pre/post source witness drifted during execution",
                }
            )
        execution_binding: dict[str, str] = {}
        execution_binding_complete = False
        binding_error: str | None = None
        decisive: ComplianceFinding | None = None
        harness_incomplete = not execution_input_closure_ok
        decision_processing_complete = (
            report is not None and execution_input_closure_ok
        )
        report_transcript: dict[str, Any] | None = None
        if report is not None:
            try:
                execution_binding = _report_execution_binding(
                    report,
                    expected_candidate=expected_candidate,
                    expected_execution_binding=pre_source_witness[
                        "expected_live_execution_binding"
                    ],
                )
                execution_binding_complete = True
            except Exception as error:
                typed_error = _typed_execution_error("report-binding", error)
                binding_error = (
                    f"{typed_error['exception_type']}: {typed_error['message']}"
                )
                errors.append(typed_error)
            try:
                decisive = _decisive_finding(
                    report.findings, case.expected_failure_code
                )
                if (
                    decisive is not None
                    and case.decisive_gate not in _finding_gate_tokens(decisive)
                ):
                    decisive = None
                harness_incomplete = harness_incomplete or any(
                    finding.verdict is ComplianceVerdict.INCOMPLETE
                    and finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
                    for finding in report.findings
                )
                if harness_incomplete:
                    errors.append(
                        {
                            "stage": "compliance-report",
                            "exception_type": "UCM-E003-HARNESS_INCOMPLETE",
                            "message": "compliance report contains harness-incomplete finding",
                        }
                    )
            except Exception as error:
                decisive = None
                decision_processing_complete = False
                errors.append(_typed_execution_error("mutation-decision", error))
            try:
                report_transcript = _complete_report_transcript(
                    report,
                    control_class_name=case.control_class_name,
                    expected_candidate=expected_candidate,
                    execution_seed=execution_seed,
                    execution_binding=execution_binding,
                    execution_binding_error=binding_error,
                    pre_source_witness=pre_source_witness,
                    post_source_witness=post_source_witness,
                    post_source_witness_error=post_source_error,
                    paired_semantic_equivalence=None,
                    input_preimage_digest=input_preimage_digest,
                )
                try:
                    _validate_complete_report_transcript(
                        report_transcript,
                        pre_source_witness=pre_source_witness,
                        post_source_witness=post_source_witness,
                        expected_head_record_shape=expected_head_record_shape,
                    )
                except Exception as error:
                    typed_error = _typed_execution_error(
                        "report-decisive-validation", error
                    )
                    errors.append(
                        {
                            "stage": typed_error["stage"],
                            "exception_type": "UCM-E003-HARNESS_INCOMPLETE",
                            "message": (
                                f"{typed_error['exception_type']}: "
                                f"{typed_error['message']}"
                            ),
                        }
                    )
                    harness_incomplete = True
                    decision_processing_complete = False
            except Exception as error:
                report_transcript = None
                decision_processing_complete = False
                errors.append(_typed_execution_error("report-transcript", error))

        if (
            not harness_stable
            or not execution_binding_complete
            or harness_incomplete
            or not decision_processing_complete
            or report_transcript is None
        ):
            decisive = None
        outcome = (
            ObservationOutcome.KILLED
            if decisive is not None
            else (
                ObservationOutcome.CRASHED
                if (
                    report is None
                    or not harness_stable
                    or not execution_binding_complete
                    or harness_incomplete
                    or not decision_processing_complete
                    or report_transcript is None
                )
                else ObservationOutcome.SURVIVED
            )
        )
        actual_gate = case.decisive_gate if decisive is not None else None
        actual_failure_code = (
            decisive.failure_code if decisive is not None else None
        )
        source_record = _raw_source_record(
            pre_source_witness=pre_source_witness,
            post_source_witness=post_source_witness,
            execution_binding=execution_binding,
            harness_stable=harness_stable,
        )
        invocation_transcript_digest = (
            report_transcript["invocation_transcript_digest"]
            if report_transcript is not None
            else digest_json([])
        )
        decision_record = {
            "runner_protocol": RUNNER_PROTOCOL,
            "decision_kind": "mutant-observation",
            "expected_gate": case.decisive_gate,
            "expected_failure_code": case.expected_failure_code,
            "report_available": report_transcript is not None,
            "harness_stable_during_execution": harness_stable,
            "execution_binding_complete": execution_binding_complete,
            "harness_incomplete": harness_incomplete,
            "decision_processing_complete": decision_processing_complete,
            "derived_outcome": outcome.value,
            "actual_gate": actual_gate,
            "actual_failure_code": actual_failure_code,
            "input_preimage_digest": input_preimage_digest,
            "invocation_transcript_digest": invocation_transcript_digest,
        }
        decisive_record = (
            {
                "runner_protocol": RUNNER_PROTOCOL,
                "decision_kind": "mutant_kill",
                "candidate": report_transcript["candidate"],
                "finding": _finding_wire(decisive),
                "source_record_payload_digest": digest_json(source_record),
                "report_transcript_payload_digest": digest_json(
                    report_transcript
                ),
                "decision_record_payload_digest": digest_json(decision_record),
                "runtime_metadata": _runtime_metadata(),
                "input_preimage_digest": input_preimage_digest,
                "invocation_transcript_digest": invocation_transcript_digest,
            }
            if decisive is not None and report_transcript is not None
            else None
        )
        error_transcript = {
            "runner_protocol": RUNNER_PROTOCOL,
            "status": "error" if errors else "none",
            "errors": errors,
        }
        record_kwargs = {
            "subject_id": case.matrix_subject_id,
            "subject_kind": SubjectKind.MUTANT,
            "execution_seed": execution_seed,
            "outcome": outcome,
            "actual_gate": actual_gate,
            "actual_failure_code": actual_failure_code,
            "classification": None,
            "pre_source_witness": pre_source_witness,
            "post_source_witness": post_source_witness,
            "source_record": source_record,
            "report_transcript": report_transcript,
            "error_transcript": error_transcript,
            "decision_record": decision_record,
            "decisive_record": decisive_record,
        }
        if decisive_record is not None:
            try:
                _preflight_decisive_record(
                    run_id=run_id,
                    base_seed=seed,
                    input_preimage=input_preimage,
                    execution_context=execution_context,
                    record_kwargs=record_kwargs,
                )
            except Exception as error:
                errors.append(
                    _typed_execution_error("decisive-evidence-validation", error)
                )
                decisive = None
                outcome = ObservationOutcome.CRASHED
                actual_gate = None
                actual_failure_code = None
                decision_processing_complete = False
                decision_record.update(
                    {
                        "decision_processing_complete": False,
                        "derived_outcome": outcome.value,
                        "actual_gate": None,
                        "actual_failure_code": None,
                    }
                )
                error_transcript = {
                    "runner_protocol": RUNNER_PROTOCOL,
                    "status": "error",
                    "errors": errors,
                }
                record_kwargs.update(
                    {
                        "outcome": outcome,
                        "actual_gate": None,
                        "actual_failure_code": None,
                        "error_transcript": error_transcript,
                        "decision_record": decision_record,
                        "decisive_record": None,
                    }
                )
        builder.add_record(**record_kwargs)

    for row_index, (
        subject_id,
        control_class_name,
        classification,
        semantic_probes,
    ), expected_head_record_shape in active_control_rows:
        execution_seed = seed + row_index
        errors: list[dict[str, str]] = []
        if source_preparation_record is not None:
            errors.append(source_preparation_record)
            pre_source_witness = {
                **_unavailable_source_witness(
                    "pre-execution", source_preparation_error
                ),
                "control": control_class_name,
                "execution_seed": execution_seed,
                "enabled_semantic_probes": sorted(semantic_probes),
            }
            pre_source_error = _typed_execution_error(
                "pre-execution", source_preparation_error
            )
            errors.append(pre_source_error)
        else:
            pre_source_witness, pre_source_error = _attempt_source_witness(
                control_class_name,
                semantic_probes,
                stage="pre-execution",
                execution_seed=execution_seed,
                runtime_import_cache_contract_digest=(
                    runtime_import_cache_baseline_digest
                ),
            )
            if pre_source_error is not None:
                errors.append(pre_source_error)

        control_report: Any | None = None
        expected_candidate: str | None = None
        paired_evidence: dict[str, Any] | None = None
        paired_probe_incomplete = False
        execution_input_closure_ok = True
        paired_input_closure_ok = True
        try:
            if pre_source_error is None:
                try:
                    execution_inputs = _fresh_execution_inputs(input_snapshot)
                except Exception as error:
                    execution_input_closure_ok = False
                    errors.append(
                        _execution_input_incomplete_error(
                            "execution-input-reparse", error
                        )
                    )
                else:
                    try:
                        entrypoint = control_entrypoint(control_class_name)
                        expected_candidate = (
                            f"{entrypoint.module}:{entrypoint.qualname}"
                        )
                        control_report = evaluate_candidate_compliance(
                            entrypoint,
                            history=execution_inputs[0],
                            diagnosis_query=execution_inputs[1],
                            rollout_query=execution_inputs[2],
                            delta=execution_inputs[3],
                            seed=execution_seed,
                            semantic_probes=semantic_probes,
                        )
                        if control_report is None:
                            raise ProtocolViolation(
                                "candidate compliance evaluator returned no report"
                            )
                    except Exception as error:
                        errors.append(
                            _typed_execution_error("candidate-evaluation", error)
                        )
                    finally:
                        try:
                            _assert_execution_inputs_unchanged(
                                input_snapshot, execution_inputs
                            )
                        except Exception as error:
                            execution_input_closure_ok = False
                            errors.append(
                                _execution_input_incomplete_error(
                                    "execution-input-postcondition", error
                                )
                            )

                    if (
                        control_report is not None
                        and subject_id == "BehaviorEquivalentSerialization"
                    ):
                        try:
                            paired_inputs = _fresh_execution_inputs(input_snapshot)
                        except Exception as error:
                            paired_input_closure_ok = False
                            paired_probe_incomplete = True
                            errors.append(
                                _execution_input_incomplete_error(
                                    "paired-input-reparse", error
                                )
                            )
                        else:
                            try:
                                paired_result = paired_serialization_equivalence_evidence(
                                    history=paired_inputs[0],
                                    diagnosis_query=paired_inputs[1],
                                    rollout_query=paired_inputs[2],
                                    delta=paired_inputs[3],
                                    seed=execution_seed,
                                )
                                if type(paired_result) is not dict:
                                    raise ProtocolViolation(
                                        "paired semantic probe returned a non-object"
                                    )
                                paired_evidence = paired_result
                            except Exception as error:
                                paired_probe_incomplete = True
                                typed_error = _typed_execution_error(
                                    "paired-semantic-probe", error
                                )
                                errors.append(typed_error)
                                paired_evidence = {
                                    "protocol": PORTABLE_SEMANTIC_PROBE_PROTOCOL,
                                    "passed": False,
                                    "probe_incomplete": (
                                        f"{typed_error['exception_type']}: "
                                        f"{typed_error['message']}"
                                    ),
                                }
                            finally:
                                try:
                                    _assert_execution_inputs_unchanged(
                                        input_snapshot, paired_inputs
                                    )
                                except Exception as error:
                                    paired_input_closure_ok = False
                                    paired_probe_incomplete = True
                                    errors.append(
                                        _execution_input_incomplete_error(
                                            "paired-input-postcondition", error
                                        )
                                    )
        finally:
            # This follows every parent-side semantic probe.  A probe cannot
            # mutate the parent harness after the witness and still pass.
            post_source_witness, post_source_error = _attempt_source_witness(
                control_class_name,
                semantic_probes,
                stage="post-execution",
                execution_seed=execution_seed,
                runtime_import_cache_contract_digest=(
                    runtime_import_cache_baseline_digest
                ),
            )
            if post_source_error is not None:
                errors.append(post_source_error)

        harness_stable = (
            pre_source_error is None
            and post_source_error is None
            and digest_json(pre_source_witness) == digest_json(post_source_witness)
        )
        if (
            pre_source_error is None
            and post_source_error is None
            and not harness_stable
        ):
            errors.append(
                {
                    "stage": "post-execution",
                    "exception_type": "UCM-E003-HARNESS_INCOMPLETE",
                    "message": "pre/post source witness drifted during execution",
                }
            )
        execution_binding: dict[str, str] = {}
        execution_binding_complete = False
        binding_error: str | None = None
        report_transcript: dict[str, Any] | None = None
        report_processing_complete = (
            control_report is not None
            and execution_input_closure_ok
            and paired_input_closure_ok
        )
        probe_incomplete = (
            paired_probe_incomplete
            or not execution_input_closure_ok
            or not paired_input_closure_ok
        )
        eligible = False
        if control_report is not None:
            try:
                execution_binding = _report_execution_binding(
                    control_report,
                    expected_candidate=expected_candidate,
                    expected_execution_binding=pre_source_witness[
                        "expected_live_execution_binding"
                    ],
                )
                execution_binding_complete = True
            except Exception as error:
                typed_error = _typed_execution_error("report-binding", error)
                binding_error = (
                    f"{typed_error['exception_type']}: {typed_error['message']}"
                )
                errors.append(typed_error)
            try:
                report_harness_incomplete = any(
                    finding.verdict is ComplianceVerdict.INCOMPLETE
                    and finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
                    for finding in control_report.findings
                )
                probe_incomplete = probe_incomplete or report_harness_incomplete
                if report_harness_incomplete:
                    errors.append(
                        {
                            "stage": "compliance-report",
                            "exception_type": "UCM-E003-HARNESS_INCOMPLETE",
                            "message": "specificity report contains harness-incomplete finding",
                        }
                    )
                eligible = _specificity_report_eligible(control_report)
            except Exception as error:
                report_processing_complete = False
                errors.append(_typed_execution_error("specificity-decision", error))
            try:
                report_transcript = _complete_report_transcript(
                    control_report,
                    control_class_name=control_class_name,
                    expected_candidate=expected_candidate,
                    execution_seed=execution_seed,
                    execution_binding=execution_binding,
                    execution_binding_error=binding_error,
                    pre_source_witness=pre_source_witness,
                    post_source_witness=post_source_witness,
                    post_source_witness_error=post_source_error,
                    paired_semantic_equivalence=paired_evidence,
                    input_preimage_digest=input_preimage_digest,
                )
                try:
                    _validate_complete_report_transcript(
                        report_transcript,
                        pre_source_witness=pre_source_witness,
                        post_source_witness=post_source_witness,
                        expected_head_record_shape=expected_head_record_shape,
                    )
                except Exception as error:
                    typed_error = _typed_execution_error(
                        "report-decisive-validation", error
                    )
                    errors.append(
                        {
                            "stage": typed_error["stage"],
                            "exception_type": "UCM-E003-HARNESS_INCOMPLETE",
                            "message": (
                                f"{typed_error['exception_type']}: "
                                f"{typed_error['message']}"
                            ),
                        }
                    )
                    probe_incomplete = True
                    report_processing_complete = False
            except Exception as error:
                report_transcript = None
                report_processing_complete = False
                errors.append(_typed_execution_error("report-transcript", error))

        passed = (
            eligible
            and harness_stable
            and execution_binding_complete
            and report_processing_complete
            and report_transcript is not None
            and not probe_incomplete
        )
        if paired_evidence is not None:
            passed = passed and paired_evidence.get("passed") is True
        outcome = (
            ObservationOutcome.PASSED
            if passed
            else (
                ObservationOutcome.CRASHED
                if (
                    control_report is None
                    or not harness_stable
                    or not execution_binding_complete
                    or probe_incomplete
                    or not report_processing_complete
                    or report_transcript is None
                )
                else ObservationOutcome.REJECTED
            )
        )
        source_record = _raw_source_record(
            pre_source_witness=pre_source_witness,
            post_source_witness=post_source_witness,
            execution_binding=execution_binding,
            harness_stable=harness_stable,
        )
        invocation_transcript_digest = (
            report_transcript["invocation_transcript_digest"]
            if report_transcript is not None
            else digest_json([])
        )
        decision_record = {
            "runner_protocol": RUNNER_PROTOCOL,
            "decision_kind": "specificity-observation",
            "classification": classification,
            "report_available": report_transcript is not None,
            "harness_stable_during_execution": harness_stable,
            "execution_binding_complete": execution_binding_complete,
            "probe_incomplete": probe_incomplete,
            "report_processing_complete": report_processing_complete,
            "semantic_equivalence_passed": (
                None
                if paired_evidence is None
                else paired_evidence.get("passed") is True
            ),
            "derived_outcome": outcome.value,
            "input_preimage_digest": input_preimage_digest,
            "invocation_transcript_digest": invocation_transcript_digest,
        }
        decisive_record = (
            {
                "runner_protocol": RUNNER_PROTOCOL,
                "decision_kind": "specificity_pass",
                "candidate": report_transcript["candidate"],
                "classification": classification,
                "source_record_payload_digest": digest_json(source_record),
                "report_transcript_payload_digest": digest_json(
                    report_transcript
                ),
                "decision_record_payload_digest": digest_json(decision_record),
                "runtime_metadata": _runtime_metadata(),
                "input_preimage_digest": input_preimage_digest,
                "invocation_transcript_digest": invocation_transcript_digest,
            }
            if passed and report_transcript is not None
            else None
        )
        error_transcript = {
            "runner_protocol": RUNNER_PROTOCOL,
            "status": "error" if errors else "none",
            "errors": errors,
        }
        record_kwargs = {
            "subject_id": subject_id,
            "subject_kind": SubjectKind.SPECIFICITY_CONTROL,
            "execution_seed": execution_seed,
            "outcome": outcome,
            "actual_gate": None,
            "actual_failure_code": None,
            "classification": classification,
            "pre_source_witness": pre_source_witness,
            "post_source_witness": post_source_witness,
            "source_record": source_record,
            "report_transcript": report_transcript,
            "error_transcript": error_transcript,
            "decision_record": decision_record,
            "decisive_record": decisive_record,
        }
        if decisive_record is not None:
            try:
                _preflight_decisive_record(
                    run_id=run_id,
                    base_seed=seed,
                    input_preimage=input_preimage,
                    execution_context=execution_context,
                    record_kwargs=record_kwargs,
                )
            except Exception as error:
                errors.append(
                    _typed_execution_error("decisive-evidence-validation", error)
                )
                passed = False
                outcome = ObservationOutcome.CRASHED
                report_processing_complete = False
                decision_record.update(
                    {
                        "report_processing_complete": False,
                        "derived_outcome": outcome.value,
                    }
                )
                error_transcript = {
                    "runner_protocol": RUNNER_PROTOCOL,
                    "status": "error",
                    "errors": errors,
                }
                record_kwargs.update(
                    {
                        "outcome": outcome,
                        "error_transcript": error_transcript,
                        "decision_record": decision_record,
                        "decisive_record": None,
                    }
                )
        builder.add_record(**record_kwargs)

    # The builder recomputes the partial matrix and closes every raw digest.
    # Its protocol deliberately retains fixed E002/E003 PRE-FREEZE blockers.
    return builder.finalize()


# Capture after every runner class/function has been created, but before any
# caller can request mutation evidence.  The snapshot contains live object
# references for verification only; no process-specific identity is serialized.
_SOURCE_IDENTITY_ANCHORS = _capture_source_identity_anchors()


__all__ = [
    "PORTABLE_MUTATION_CASES",
    "PORTABLE_SPECIFICITY_CASES",
    "RUNNER_PROTOCOL",
    "PortableMutationCase",
    "paired_serialization_equivalence_evidence",
    "run_portable_mutation_evidence",
]
