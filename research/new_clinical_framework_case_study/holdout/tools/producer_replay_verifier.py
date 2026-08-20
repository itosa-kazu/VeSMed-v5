#!/usr/bin/env python3
"""Fresh-process verifier for automated primary-gate evidence producers.

An automated evidence JSON is not trusted merely because it names a sealed
tool or copies that tool's ``produced_by``/schema fields.  This module derives
one exact invocation from a *sealed policy*, copies every post-seal input by
content address into an isolated directory, runs the exact sealed Python tool
in a fresh subprocess, and compares the regenerated JSON artifact byte for
byte and semantically with the cited artifact.

The application-level socket guard is an auditable offline control, not an OS
sandbox.  The producer source is itself sealed and is expected not to bypass
that guard through native APIs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


POLICY_SCHEMA_VERSION = "ncf.producer-replay-policy.v1"
VERIFICATION_SCHEMA_VERSION = "ncf.producer-replay-verification.v1"
ADAPTER_ID = "CONFIGURED_CLI_EXACT_JSON_V1"
COMPARISON_MODE = "EXACT_BYTES_AND_CANONICAL_JSON"
_PLACEHOLDER = re.compile(
    r"^\{(input|check|output):([A-Za-z][A-Za-z0-9_]*)\}$|^\{(output|output_dir|study_root)\}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProducerReplayError(RuntimeError):
    """A fail-closed replay-policy, invocation, or execution failure."""


@dataclass(frozen=True)
class ReplayVerification:
    schema_version: str
    status: str
    invocation_sha256: str
    output_sha256: str
    output_bytes: int
    output_semantic_sha256: str
    network_control: str
    outputs: Mapping[str, Mapping[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "status": self.status,
            "invocation_sha256": self.invocation_sha256,
            "output_sha256": self.output_sha256,
            "output_bytes": self.output_bytes,
            "output_semantic_sha256": self.output_semantic_sha256,
            "network_control": self.network_control,
        }
        if self.outputs is not None:
            value["outputs"] = {key: dict(self.outputs[key]) for key in sorted(self.outputs)}
        return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_json_equal(left: Any, right: Any) -> bool:
    try:
        return canonical_json_bytes(left) == canonical_json_bytes(right)
    except (TypeError, ValueError):
        return False


def _content_ref(ref: Mapping[str, Any]) -> dict[str, Any]:
    return {"path": ref["path"], "sha256": ref["sha256"], "bytes": ref["bytes"]}


def _validate_ref_shape(ref: Any, *, named: bool) -> Mapping[str, Any]:
    expected = {"path", "sha256", "bytes"} | ({"ref_id"} if named else set())
    if not isinstance(ref, Mapping) or set(ref) != expected:
        raise ProducerReplayError("content_ref_shape_invalid")
    if (
        not isinstance(ref.get("path"), str)
        or Path(str(ref["path"])).is_absolute()
        or ".." in Path(str(ref["path"])).parts
        or Path(str(ref["path"])).as_posix() != ref["path"]
        or not isinstance(ref.get("sha256"), str)
        or _SHA256.fullmatch(str(ref["sha256"])) is None
        or isinstance(ref.get("bytes"), bool)
        or not isinstance(ref.get("bytes"), int)
        or int(ref["bytes"]) < 1
        or (named and (not isinstance(ref.get("ref_id"), str) or not ref["ref_id"]))
    ):
        raise ProducerReplayError("content_ref_value_invalid")
    return ref


def _verify_file_ref(root: Path, path: Path, ref: Mapping[str, Any], *, named: bool) -> None:
    _validate_ref_shape(ref, named=named)
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ProducerReplayError("content_ref_path_outside_root_or_missing") from exc
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ProducerReplayError("content_ref_symlink_forbidden")
    if not resolved.is_file() or relative.as_posix() != ref["path"]:
        raise ProducerReplayError("content_ref_path_binding_mismatch")
    raw = resolved.read_bytes()
    if len(raw) != ref["bytes"] or sha256_bytes(raw) != ref["sha256"]:
        raise ProducerReplayError("content_ref_hash_or_bytes_mismatch")


def _validate_policy(policy: Any) -> Mapping[str, Any]:
    required = {
        "schema_version",
        "adapter_id",
        "argv_template",
        "required_input_slots",
        "check_arg_contract",
        "output_contract",
        "timeout_seconds",
        "working_directory",
        "network_policy",
        "comparison",
    }
    if not isinstance(policy, Mapping) or set(policy) != required:
        raise ProducerReplayError("replay_policy_shape_invalid")
    if (
        policy.get("schema_version") != POLICY_SCHEMA_VERSION
        or policy.get("adapter_id") != ADAPTER_ID
        or policy.get("working_directory") != "STUDY_ROOT"
        or policy.get("network_policy") != "APPLICATION_SOCKET_GUARD_OFFLINE"
        or policy.get("comparison") != COMPARISON_MODE
    ):
        raise ProducerReplayError("replay_policy_identity_or_boundary_invalid")
    timeout = policy.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 900:
        raise ProducerReplayError("replay_timeout_policy_invalid")
    slots = policy.get("required_input_slots")
    checks = policy.get("check_arg_contract")
    if not isinstance(slots, Mapping) or not isinstance(checks, Mapping):
        raise ProducerReplayError("replay_input_or_check_contract_invalid")
    for slot, spec in slots.items():
        if not isinstance(slot, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", slot) is None:
            raise ProducerReplayError("replay_input_slot_invalid")
        if (
            not isinstance(spec, Mapping)
            or set(spec) not in ({"json_schema_versions"}, {"json_schema_versions", "materialization"})
        ):
            raise ProducerReplayError("replay_input_slot_contract_invalid")
        versions = spec.get("json_schema_versions")
        if not isinstance(versions, list) or not versions or any(not isinstance(x, str) or not x for x in versions):
            raise ProducerReplayError("replay_input_schema_allowlist_invalid")
        if spec.get("materialization", "ISOLATED_COPY") not in {
            "ISOLATED_COPY",
            "VERIFIED_ORIGINAL_PATH",
        }:
            raise ProducerReplayError("replay_input_materialization_invalid")
    for name, spec in checks.items():
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) is None:
            raise ProducerReplayError("replay_check_arg_name_invalid")
        if not isinstance(spec, Mapping) or set(spec) not in (
            {"source", "allowed_values"},
            {"source", "json_pointer", "pattern"},
        ):
            raise ProducerReplayError("replay_check_arg_contract_invalid")
        if spec.get("source") == "SEALED_ENUM":
            allowed = spec.get("allowed_values")
            if not isinstance(allowed, list) or not allowed or any(
                not isinstance(x, str) or not x for x in allowed
            ):
                raise ProducerReplayError("replay_check_arg_enum_invalid")
        elif spec.get("source") == "OUTPUT_JSON_POINTER":
            if not isinstance(spec.get("json_pointer"), str) or not isinstance(spec.get("pattern"), str):
                raise ProducerReplayError("replay_check_arg_output_binding_invalid")
            try:
                re.compile(str(spec["pattern"]))
            except re.error as exc:
                raise ProducerReplayError("replay_check_arg_pattern_invalid") from exc
        else:
            raise ProducerReplayError("replay_check_arg_source_invalid")
    argv = policy.get("argv_template")
    if not isinstance(argv, list) or not argv or any(not isinstance(token, str) or not token for token in argv):
        raise ProducerReplayError("replay_argv_template_invalid")
    referenced_inputs: list[str] = []
    referenced_checks: list[str] = []
    unnamed_outputs: list[str] = []
    named_outputs: list[str] = []
    for token in argv:
        match = _PLACEHOLDER.fullmatch(token)
        if "{" in token or "}" in token:
            if match is None:
                raise ProducerReplayError("replay_argv_placeholder_invalid")
            if match.group(1) == "input":
                referenced_inputs.append(str(match.group(2)))
            elif match.group(1) == "check":
                referenced_checks.append(str(match.group(2)))
            elif match.group(1) == "output":
                named_outputs.append(str(match.group(2)))
            elif match.group(3) in {"output", "output_dir"}:
                unnamed_outputs.append(str(match.group(3)))
            else:
                # {study_root} is a sealed, deterministic runtime value and
                # does not consume an output slot.
                pass
    if sorted(referenced_inputs) != sorted(slots) or len(referenced_inputs) != len(set(referenced_inputs)):
        raise ProducerReplayError("replay_argv_input_slots_not_exact")
    if sorted(referenced_checks) != sorted(checks) or len(referenced_checks) != len(set(referenced_checks)):
        raise ProducerReplayError("replay_argv_check_args_not_exact")
    output = policy.get("output_contract")
    if not isinstance(output, Mapping):
        raise ProducerReplayError("replay_output_contract_invalid")
    if output.get("mode") not in {"SINGLE_FILE", "DIRECTORY_MANIFEST", "NAMED_FILES"}:
        raise ProducerReplayError("replay_output_mode_invalid")
    if output.get("mode") == "SINGLE_FILE":
        if set(output) != {"mode", "json_schema_versions"} or unnamed_outputs != ["output"] or named_outputs:
            raise ProducerReplayError("replay_output_contract_invalid")
    elif output.get("mode") == "DIRECTORY_MANIFEST":
        if (
            set(output)
            != {"mode", "artifact_relative_path", "manifest_json_pointer", "manifest_path_field", "json_schema_versions"}
            or unnamed_outputs != ["output_dir"]
            or named_outputs
        ):
            raise ProducerReplayError("replay_output_contract_invalid")
        rel = Path(str(output.get("artifact_relative_path", "")))
        if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != output.get("artifact_relative_path"):
            raise ProducerReplayError("replay_output_artifact_path_invalid")
        if not isinstance(output.get("manifest_json_pointer"), str) or not isinstance(
            output.get("manifest_path_field"), str
        ):
            raise ProducerReplayError("replay_output_manifest_contract_invalid")
    else:
        if set(output) != {"mode", "outputs"} or unnamed_outputs:
            raise ProducerReplayError("replay_output_contract_invalid")
        specs = output.get("outputs")
        if not isinstance(specs, Mapping) or not specs or set(named_outputs) != set(specs) or len(named_outputs) != len(set(named_outputs)):
            raise ProducerReplayError("replay_named_outputs_not_exact")
        for name, spec in specs.items():
            if (
                not isinstance(name, str)
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) is None
                or not isinstance(spec, Mapping)
                or set(spec) != {"artifact_relative_path", "json_schema_versions"}
            ):
                raise ProducerReplayError("replay_named_output_contract_invalid")
            rel = Path(str(spec.get("artifact_relative_path", "")))
            if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != spec.get("artifact_relative_path") or rel.as_posix() in {"", "."}:
                raise ProducerReplayError("replay_named_output_path_invalid")
            versions = spec.get("json_schema_versions")
            if not isinstance(versions, list) or not versions or any(not isinstance(x, str) or not x for x in versions):
                raise ProducerReplayError("replay_named_output_schema_allowlist_invalid")
        paths = [spec["artifact_relative_path"] for spec in specs.values()]
        if len(paths) != len(set(paths)):
            raise ProducerReplayError("replay_named_output_paths_duplicate")
    if output.get("mode") != "NAMED_FILES":
        versions = output.get("json_schema_versions")
        if not isinstance(versions, list) or not versions or any(not isinstance(x, str) or not x for x in versions):
            raise ProducerReplayError("replay_output_schema_allowlist_invalid")
    elif any(spec.get("source") == "OUTPUT_JSON_POINTER" for spec in checks.values()):
        # A named-output policy must not ambiguously derive an argv value from
        # one of several outputs.  Seal such values as enums or move them into
        # an input manifest instead.
        raise ProducerReplayError("replay_named_output_check_binding_ambiguous")
    return policy


def _json_pointer(value: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ProducerReplayError("json_pointer_invalid")
    current = value
    if pointer == "":
        return current
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ProducerReplayError("json_pointer_not_found")
    return current


def build_invocation_descriptor(
    *,
    producer_id: str,
    tool_ref: Mapping[str, Any],
    replay_policy: Mapping[str, Any],
    replay_claim: Mapping[str, Any],
    source_refs: Mapping[str, Mapping[str, Any]],
    output_ref_id: str | None = None,
) -> dict[str, Any]:
    """Build the canonical invocation preimage used by producers and scorer."""

    policy = _validate_policy(replay_policy)
    _validate_ref_shape(tool_ref, named=False)
    named_mode = policy["output_contract"]["mode"] == "NAMED_FILES"
    claim_keys = {
        "adapter_id",
        "input_ref_ids",
        "check_args",
        "invocation_sha256",
    } | ({"output_ref_ids"} if named_mode else set())
    if not isinstance(replay_claim, Mapping) or set(replay_claim) != claim_keys:
        raise ProducerReplayError("replay_claim_shape_invalid")
    if replay_claim.get("adapter_id") != policy["adapter_id"]:
        raise ProducerReplayError("replay_adapter_drift")
    input_ids = replay_claim.get("input_ref_ids")
    checks = replay_claim.get("check_args")
    if not isinstance(input_ids, Mapping) or set(input_ids) != set(policy["required_input_slots"]):
        raise ProducerReplayError("replay_input_slots_drift")
    if not isinstance(checks, Mapping) or set(checks) != set(policy["check_arg_contract"]):
        raise ProducerReplayError("replay_check_args_drift")
    if named_mode:
        output_ids = replay_claim.get("output_ref_ids")
        expected_names = set(policy["output_contract"]["outputs"])
        if not isinstance(output_ids, Mapping) or set(output_ids) != expected_names:
            raise ProducerReplayError("replay_named_output_ref_slots_drift")
        if any(not isinstance(ref_id, str) or ref_id not in source_refs for ref_id in output_ids.values()):
            raise ProducerReplayError("replay_named_output_ref_missing")
        if len(set(output_ids.values())) != len(output_ids):
            raise ProducerReplayError("replay_named_output_refs_duplicate")
        canonical_outputs = {
            name: {"ref_id": output_ids[name], **_content_ref(source_refs[output_ids[name]])}
            for name in sorted(output_ids)
        }
        forbidden_output_ids = set(output_ids.values())
    else:
        if not isinstance(output_ref_id, str) or output_ref_id not in source_refs:
            raise ProducerReplayError("replay_output_ref_missing")
        canonical_outputs = None
        forbidden_output_ids = {output_ref_id}
    canonical_inputs: dict[str, Any] = {}
    used_ref_ids: set[str] = set()
    for slot in sorted(input_ids):
        ref_id = input_ids[slot]
        if not isinstance(ref_id, str) or ref_id in forbidden_output_ids or ref_id in used_ref_ids or ref_id not in source_refs:
            raise ProducerReplayError("replay_input_ref_binding_invalid")
        used_ref_ids.add(ref_id)
        canonical_inputs[slot] = {"ref_id": ref_id, **_content_ref(source_refs[ref_id])}
    descriptor = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "producer_id": producer_id,
        "tool_ref": _content_ref(tool_ref),
        "adapter_id": policy["adapter_id"],
        "policy_sha256": sha256_bytes(canonical_json_bytes(policy)),
        "argv_template": policy["argv_template"],
        "inputs": canonical_inputs,
        "check_args": {key: checks[key] for key in sorted(checks)},
        "working_directory": policy["working_directory"],
        "network_policy": policy["network_policy"],
        "comparison": policy["comparison"],
    }
    if named_mode:
        descriptor["output_refs"] = canonical_outputs
    else:
        descriptor["output_ref"] = {"ref_id": output_ref_id, **_content_ref(source_refs[output_ref_id])}
    return descriptor


def invocation_sha256(descriptor: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(descriptor))


def _write_socket_guard(directory: Path) -> None:
    # Python imports sitecustomize during fresh interpreter startup.  This
    # closes the ordinary socket APIs used by the sealed Python producers.
    (directory / "sitecustomize.py").write_text(
        "import socket\n"
        "def _offline(*args, **kwargs):\n"
        "    raise RuntimeError('NCF producer replay is offline')\n"
        "socket.create_connection = _offline\n"
        "socket.getaddrinfo = _offline\n"
        "_original_socket = socket.socket\n"
        "class _OfflineSocket(_original_socket):\n"
        "    def connect(self, *args, **kwargs): return _offline(*args, **kwargs)\n"
        "    def connect_ex(self, *args, **kwargs): return _offline(*args, **kwargs)\n"
        "socket.socket = _OfflineSocket\n",
        encoding="utf-8",
    )


def _safe_environment(guard_dir: Path) -> dict[str, str]:
    keep = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH") if key in os.environ}
    keep.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(guard_dir),
            "TZ": "UTC",
            "NO_PROXY": "*",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
        }
    )
    return keep


def _validate_check_args(policy: Mapping[str, Any], checks: Mapping[str, Any], artifact: Mapping[str, Any]) -> None:
    for name, spec in policy["check_arg_contract"].items():
        value = checks[name]
        if not isinstance(value, str):
            raise ProducerReplayError("replay_check_arg_not_string")
        if spec["source"] == "SEALED_ENUM":
            if value not in spec["allowed_values"]:
                raise ProducerReplayError("replay_check_arg_not_in_sealed_allowlist")
        else:
            observed = _json_pointer(artifact, spec["json_pointer"])
            if observed != value or re.fullmatch(spec["pattern"], value) is None:
                raise ProducerReplayError("replay_check_arg_not_output_bound")


def _validate_input_schemas(
    policy: Mapping[str, Any], input_ids: Mapping[str, str], source_values: Mapping[str, Any]
) -> None:
    for slot, ref_id in input_ids.items():
        value = source_values.get(ref_id)
        allowed = policy["required_input_slots"][slot]["json_schema_versions"]
        if not isinstance(value, Mapping) or value.get("schema_version") not in allowed:
            raise ProducerReplayError("replay_input_schema_not_allowed")


def _render_argv(
    template: Sequence[str],
    *,
    copied_inputs: Mapping[str, Path],
    checks: Mapping[str, str],
    output: Path,
    output_dir: Path,
    named_outputs: Mapping[str, Path],
    study_root: Path,
) -> list[str]:
    rendered: list[str] = []
    for token in template:
        match = _PLACEHOLDER.fullmatch(token)
        if match is None:
            rendered.append(token)
        elif match.group(1) == "input":
            rendered.append(str(copied_inputs[str(match.group(2))]))
        elif match.group(1) == "check":
            rendered.append(checks[str(match.group(2))])
        elif match.group(1) == "output":
            rendered.append(str(named_outputs[str(match.group(2))]))
        elif match.group(3) == "output":
            rendered.append(str(output))
        elif match.group(3) == "output_dir":
            rendered.append(str(output_dir))
        else:
            rendered.append(str(study_root))
    return rendered


def _validate_output_set(
    output_dir: Path,
    artifact: Mapping[str, Any] | None,
    contract: Mapping[str, Any],
    artifact_path: Path | None,
    named_paths: Mapping[str, Path],
) -> None:
    actual = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    }
    if contract["mode"] == "SINGLE_FILE":
        assert artifact_path is not None
        expected = {artifact_path.relative_to(output_dir).as_posix()}
    elif contract["mode"] == "DIRECTORY_MANIFEST":
        assert artifact is not None and artifact_path is not None
        manifest = _json_pointer(artifact, contract["manifest_json_pointer"])
        field = contract["manifest_path_field"]
        if not isinstance(manifest, list):
            raise ProducerReplayError("replay_output_manifest_not_array")
        expected = {contract["artifact_relative_path"]}
        for row in manifest:
            if not isinstance(row, Mapping) or not isinstance(row.get(field), str):
                raise ProducerReplayError("replay_output_manifest_row_invalid")
            rel = Path(row[field])
            if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != row[field]:
                raise ProducerReplayError("replay_output_manifest_path_invalid")
            expected.add(row[field])
    else:
        expected = {path.relative_to(output_dir).as_posix() for path in named_paths.values()}
    if actual != expected:
        raise ProducerReplayError("replay_extra_or_missing_output_files")


def verify_automated_producer_replay(
    *,
    study_root: Path,
    producer_id: str,
    tool_ref: Mapping[str, Any],
    tool_path: Path,
    replay_policy: Mapping[str, Any],
    replay_claim: Mapping[str, Any],
    source_refs: Mapping[str, Mapping[str, Any]],
    source_paths: Mapping[str, Path],
    source_values: Mapping[str, Any],
    output_ref_id: str | None = None,
) -> ReplayVerification:
    """Re-execute one exact automated producer invocation or fail closed."""

    root = study_root.resolve(strict=True)
    policy = _validate_policy(replay_policy)
    _verify_file_ref(root, tool_path, tool_ref, named=False)
    for ref_id, ref in source_refs.items():
        if ref_id not in source_paths:
            raise ProducerReplayError("source_ref_path_missing")
        _verify_file_ref(root, source_paths[ref_id], ref, named=True)
    descriptor = build_invocation_descriptor(
        producer_id=producer_id,
        tool_ref=tool_ref,
        replay_policy=policy,
        replay_claim=replay_claim,
        source_refs=source_refs,
        output_ref_id=output_ref_id,
    )
    computed_invocation = invocation_sha256(descriptor)
    if replay_claim.get("invocation_sha256") != computed_invocation:
        raise ProducerReplayError("replay_invocation_sha256_mismatch")
    output_contract = policy["output_contract"]
    named_mode = output_contract["mode"] == "NAMED_FILES"
    if named_mode:
        output_ids = replay_claim["output_ref_ids"]
        output_values: dict[str, Mapping[str, Any]] = {}
        output_source_paths: dict[str, Path] = {}
        for name, spec in output_contract["outputs"].items():
            ref_id = output_ids[name]
            value = source_values.get(ref_id)
            path = source_paths.get(ref_id)
            if not isinstance(value, Mapping) or path is None:
                raise ProducerReplayError("replay_named_output_source_invalid")
            if value.get("schema_version") not in spec["json_schema_versions"]:
                raise ProducerReplayError("replay_named_output_schema_not_allowed")
            output_values[name] = value
            output_source_paths[name] = path
        check_artifact: Mapping[str, Any] = next(iter(output_values.values()))
    else:
        output_value = source_values.get(output_ref_id)
        output_source_path = source_paths.get(output_ref_id)
        if not isinstance(output_value, Mapping) or output_source_path is None:
            raise ProducerReplayError("replay_output_source_invalid")
        if output_value.get("schema_version") not in output_contract["json_schema_versions"]:
            raise ProducerReplayError("replay_output_schema_not_allowed")
        output_values = {"output": output_value}
        output_source_paths = {"output": output_source_path}
        check_artifact = output_value
    input_ids = replay_claim["input_ref_ids"]
    checks = replay_claim["check_args"]
    _validate_input_schemas(policy, input_ids, source_values)
    _validate_check_args(policy, checks, check_artifact)

    before = {ref_id: source_paths[ref_id].read_bytes() for ref_id in input_ids.values()}
    # Some sealed producers intentionally reject manifests outside the study
    # root.  Materialize the isolated copies beneath that root while keeping
    # them in a unique, automatically removed directory.  The producer sees
    # copies only; original inputs are still checked for pre/post drift.
    with (
        tempfile.TemporaryDirectory(prefix=".ncf-producer-replay-", dir=root) as raw_temp,
        tempfile.TemporaryDirectory(prefix="ncf-producer-offline-guard-") as raw_guard,
    ):
        temp = Path(raw_temp)
        input_dir = temp / "inputs"
        output_dir = temp / "outputs"
        # Keep the injected application guard outside the study tree.  The
        # structural producer intentionally records workspace module imports;
        # placing sitecustomize under the tree would become a false dependency.
        guard_dir = Path(raw_guard)
        input_dir.mkdir()
        output_dir.mkdir()
        _write_socket_guard(guard_dir)
        copied: dict[str, Path] = {}
        for slot, ref_id in sorted(input_ids.items()):
            source = source_paths[ref_id]
            materialization = policy["required_input_slots"][slot].get(
                "materialization", "ISOLATED_COPY"
            )
            if materialization == "VERIFIED_ORIGINAL_PATH":
                # Some sealed CLIs consume a manifest whose content-addressed
                # children are resolved relative to the real study root.  In
                # that case copying only the manifest would change its
                # semantics.  Give the fresh process the exact verified
                # original path and retain the pre/post drift check below.
                copied[slot] = source
            else:
                suffix = source.suffix if source.suffix else ".bin"
                destination = input_dir / f"{slot}{suffix}"
                destination.write_bytes(before[ref_id])
                copied[slot] = destination
        if output_contract["mode"] == "SINGLE_FILE":
            output_path = output_dir / "artifact.json"
            named_paths: dict[str, Path] = {}
        elif output_contract["mode"] == "DIRECTORY_MANIFEST":
            output_path = output_dir / output_contract["artifact_relative_path"]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            named_paths = {}
        else:
            output_path = output_dir / "unused-artifact.json"
            named_paths = {
                name: output_dir / spec["artifact_relative_path"]
                for name, spec in output_contract["outputs"].items()
            }
            for path in named_paths.values():
                path.parent.mkdir(parents=True, exist_ok=True)
        argv = _render_argv(
            policy["argv_template"],
            copied_inputs=copied,
            checks=checks,
            output=output_path,
            output_dir=output_dir,
            named_outputs=named_paths,
            study_root=root,
        )
        command = [sys.executable, str(tool_path), *argv]
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=_safe_environment(guard_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=policy["timeout_seconds"],
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProducerReplayError("replay_subprocess_timeout") from exc
        if completed.returncode != 0:
            raise ProducerReplayError(f"replay_subprocess_nonzero:{completed.returncode}")
        replay_bytes_by_name: dict[str, bytes] = {}
        replay_values_by_name: dict[str, Mapping[str, Any]] = {}
        replay_paths = named_paths if named_mode else {"output": output_path}
        for name, path in replay_paths.items():
            if not path.is_file() or path.is_symlink():
                raise ProducerReplayError("replay_output_missing_or_symlink")
            raw = path.read_bytes()
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProducerReplayError("replay_output_not_utf8_json") from exc
            if not isinstance(value, Mapping):
                raise ProducerReplayError("replay_output_not_object")
            replay_bytes_by_name[name] = raw
            replay_values_by_name[name] = value
        manifest_artifact = replay_values_by_name.get("output")
        _validate_output_set(
            output_dir,
            manifest_artifact,
            output_contract,
            None if named_mode else output_path,
            named_paths,
        )

    # Ensure the producer did not modify cited original inputs, even though it
    # was only given copies.
    if any(source_paths[ref_id].read_bytes() != raw for ref_id, raw in before.items()):
        raise ProducerReplayError("replay_original_input_drift")
    verified_outputs: dict[str, dict[str, Any]] = {}
    for name in sorted(replay_bytes_by_name):
        raw = replay_bytes_by_name[name]
        value = replay_values_by_name[name]
        source_bytes = output_source_paths[name].read_bytes()
        if raw != source_bytes:
            raise ProducerReplayError("replay_output_exact_bytes_mismatch")
        if not _strict_json_equal(value, output_values[name]):
            raise ProducerReplayError("replay_output_semantic_mismatch")
        output_sha = sha256_bytes(raw)
        ref_id = replay_claim["output_ref_ids"][name] if named_mode else output_ref_id
        output_ref = source_refs[ref_id]
        if output_sha != output_ref["sha256"] or len(raw) != output_ref["bytes"]:
            raise ProducerReplayError("replay_output_content_ref_mismatch")
        verified_outputs[name] = {
            "ref_id": ref_id,
            "sha256": output_sha,
            "bytes": len(raw),
            "semantic_sha256": sha256_bytes(canonical_json_bytes(value)),
        }
    aggregate = canonical_json_bytes(verified_outputs)
    primary = verified_outputs[sorted(verified_outputs)[0]]
    return ReplayVerification(
        schema_version=VERIFICATION_SCHEMA_VERSION,
        status="PASS",
        invocation_sha256=computed_invocation,
        output_sha256=sha256_bytes(aggregate) if named_mode else primary["sha256"],
        output_bytes=sum(row["bytes"] for row in verified_outputs.values()),
        output_semantic_sha256=sha256_bytes(aggregate) if named_mode else primary["semantic_sha256"],
        network_control="APPLICATION_SOCKET_GUARD_OFFLINE_NOT_OS_SANDBOX",
        outputs=verified_outputs if named_mode else None,
    )


__all__ = [
    "ADAPTER_ID",
    "COMPARISON_MODE",
    "POLICY_SCHEMA_VERSION",
    "VERIFICATION_SCHEMA_VERSION",
    "ProducerReplayError",
    "ReplayVerification",
    "build_invocation_descriptor",
    "canonical_json_bytes",
    "invocation_sha256",
    "verify_automated_producer_replay",
]
