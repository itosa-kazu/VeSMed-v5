#!/usr/bin/env python3
"""Write-once, schema-checked primary-holdout JSON evidence packager.

Only frozen producer artifacts and the frozen scoring policy determine results.
The CLI deliberately has no result/PASS argument.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence

from producer_replay_verifier import build_invocation_descriptor, invocation_sha256

ROOT = Path(__file__).resolve().parents[2]
SCORING = "holdout/PRIMARY_HOLDOUT_SCORING_v1.json"
GATES = "holdout/PERFECT_LANDING_GATES.json"
SEAL = "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json"
INPUT_SCHEMA = "holdout/schemas/primary_json_evidence_packager_input.schema.json"
RECEIPT_SCHEMA = "holdout/schemas/primary_json_evidence_package.schema.json"
EVENT_SCHEMA = "holdout/schemas/primary_json_packager_event_replay_report.schema.json"
STRUCT_SCHEMA = "holdout/tools/structural_gate_results.schema.json"
EVAL_SCHEMA = "holdout/schemas/primary_case_gate_evaluation.schema.json"
MANIFEST_SCHEMA = "holdout/schemas/primary_case_gate_evaluator_input.schema.json"
EVIDENCE_SCHEMA = "holdout/schemas/primary_gate_evidence.schema.json"
GATE_BUNDLE_SCHEMA = "holdout/schemas/primary_gate_evidence_bundle.schema.json"
COVERAGE_SCHEMA = "holdout/schemas/primary_complex_case_coverage_bundle.schema.json"
STRUCT_TOOL = "holdout/tools/structural_gate_harness.py"
EVENT_TOOL = "holdout/tools/event_ledger_replay.py"
EVAL_TOOL = "holdout/tools/primary_case_gate_evaluator.py"
THIS_TOOL = "holdout/tools/package_primary_holdout_json.py"
REPORT_GATE = "PL-REPORT-001"
COVERAGE_ORDER = (
    "recursive_updates", "at_least_two_local_domains",
    "concurrent_process_target_from_oracle", "delayed_information",
    "reliable_negative_evidence", "performed_action_lifecycle_with_response",
    "prospective_pre_next_cut_forecasts",
)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PackagingError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise PackagingError(message)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode() + b"\n"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        fail(f"{label} missing/non-file/symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"{label} is not UTF-8 JSON: {exc}")
    if not isinstance(value, Mapping):
        fail(f"{label} must be an object")
    return value


# Exact dependency-free subset used by the frozen schemas in this pipeline.
def _schema_ref(root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        fail(f"non-local schema ref forbidden: {ref}")
    node: Any = root
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or key not in node:
            fail(f"unresolvable schema ref: {ref}")
        node = node[key]
    if not isinstance(node, Mapping):
        fail(f"schema ref does not resolve to object: {ref}")
    return node


def _kind(value: Any, kind: str) -> bool:
    return {
        "object": isinstance(value, Mapping), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool)
                  and math.isfinite(float(value)), "null": value is None,
    }.get(kind, False)


def schema_validate(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any], at: str = "$") -> None:
    if "$ref" in schema:
        schema_validate(value, _schema_ref(root, str(schema["$ref"])), root, at)
        return
    if "oneOf" in schema:
        hits = 0
        for option in schema["oneOf"]:
            try:
                schema_validate(value, option, root, at); hits += 1
            except PackagingError:
                pass
        if hits != 1:
            fail(f"schema {at}: oneOf matched {hits}")
        return
    if "const" in schema and value != schema["const"]:
        fail(f"schema {at}: const")
    if "enum" in schema and value not in schema["enum"]:
        fail(f"schema {at}: enum")
    declared = schema.get("type")
    if declared is not None:
        kinds = [declared] if isinstance(declared, str) else list(declared)
        if not any(_kind(value, str(item)) for item in kinds):
            fail(f"schema {at}: type")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            fail(f"schema {at}: minLength")
        if "pattern" in schema and re.search(str(schema["pattern"]), value) is None:
            fail(f"schema {at}: pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            fail(f"schema {at}: minimum")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            fail(f"schema {at}: minItems")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            fail(f"schema {at}: maxItems")
        if schema.get("uniqueItems"):
            items = [json.dumps(x, sort_keys=True, separators=(",", ":")) for x in value]
            if len(items) != len(set(items)):
                fail(f"schema {at}: uniqueItems")
        if "items" in schema:
            for index, item in enumerate(value):
                schema_validate(item, schema["items"], root, f"{at}[{index}]")
    if isinstance(value, Mapping):
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            fail(f"schema {at}: missing {missing}")
        if len(value) < int(schema.get("minProperties", 0)):
            fail(f"schema {at}: minProperties")
        props, extra = schema.get("properties", {}), schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                schema_validate(item, props[key], root, f"{at}.{key}")
            elif extra is False:
                fail(f"schema {at}.{key}: additional property")
            elif isinstance(extra, Mapping):
                schema_validate(item, extra, root, f"{at}.{key}")
        if isinstance(schema.get("propertyNames"), Mapping):
            for key in value:
                schema_validate(key, schema["propertyNames"], root, f"{at}.<key>")


def validate(root: Path, value: Any, schema_rel: str, label: str) -> None:
    schema = load(root / schema_rel, f"{label} schema")
    schema_validate(value, schema, schema)


def rel(root: Path, path: Path, exists: bool = True) -> str:
    resolved = path.resolve(strict=exists)
    try:
        parts = resolved.relative_to(root).parts
    except ValueError:
        fail(f"path outside study root: {path}")
    cursor = root
    for part in parts:
        cursor /= part
        if cursor.is_symlink():
            fail(f"symlink path forbidden: {path}")
    return PurePosixPath(*parts).as_posix()


def content_ref(root: Path, path: Path) -> dict[str, Any]:
    raw = path.resolve(strict=True).read_bytes()
    if not raw:
        fail(f"empty artifact: {path}")
    return {"path": rel(root, path), "sha256": sha(raw), "bytes": len(raw)}


def resolve_ref(root: Path, ref: Any, label: str) -> Path:
    if not isinstance(ref, Mapping) or set(ref) != {"path", "sha256", "bytes"}:
        fail(f"{label} content ref malformed")
    p, digest, size = ref.get("path"), ref.get("sha256"), ref.get("bytes")
    if (not isinstance(p, str) or Path(p).is_absolute() or ".." in Path(p).parts
            or Path(p).as_posix() != p or not isinstance(digest, str)
            or SHA_RE.fullmatch(digest) is None or isinstance(size, bool)
            or not isinstance(size, int) or size < 1):
        fail(f"{label} content ref fields invalid")
    path = root / p
    rel(root, path)
    raw = path.read_bytes()
    if len(raw) != size or sha(raw) != digest:
        fail(f"{label} hash/bytes mismatch")
    return path


def named(name: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {"ref_id": name, **{k: row[k] for k in ("path", "sha256", "bytes")}}


def same(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return all(a.get(k) == b.get(k) for k in ("path", "sha256", "bytes"))


def pointer(value: Any, expression: str) -> Any:
    if not expression.startswith("/"):
        fail(f"invalid JSON pointer: {expression}")
    node = value
    for raw in expression[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            try: node = node[int(token)]
            except (ValueError, IndexError): fail(f"unresolved pointer: {expression}")
        elif isinstance(node, Mapping) and token in node:
            node = node[token]
        else:
            fail(f"unresolved pointer: {expression}")
    return node


def strict_eq(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def operator(op: str, observed: Any, expected: Any) -> bool:
    if op == "EQ": return strict_eq(observed, expected)
    if op == "NE": return not strict_eq(observed, expected)
    if op == "GT": return observed > expected
    if op == "GTE": return observed >= expected
    if op == "LT": return observed < expected
    if op == "LTE": return observed <= expected
    if op == "CONTAINS": return expected in observed
    if op == "NOT_CONTAINS": return expected not in observed
    if op == "SET_EQUALS": return set(observed) == set(expected)
    if op == "LENGTH_EQ": return len(observed) == expected
    fail(f"unknown assertion operator: {op}")


def verify_seal(root: Path, ref_row: Mapping[str, Any]) -> Mapping[str, Any]:
    path = resolve_ref(root, ref_row, "combined seal")
    if path.resolve() != (root / SEAL).resolve():
        fail("combined seal is not canonical")
    from build_pre_primary_holdout_seal import verify_seal as verify
    result = verify(root)
    if result.get("status") != "PASS":
        fail("combined pre-primary seal verification failed")
    doc = load(path, "combined seal")
    if doc.get("payload_sha256") != result.get("payload_sha256"):
        fail("combined seal payload mismatch")
    return doc


def policies(scoring: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = scoring.get("final_scorer_contract", {}).get("evidence_producer_policy", {}).get("sealed_automated_generators")
    if not isinstance(rows, list):
        fail("frozen producer policy missing")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("producer_id"), str) or row["producer_id"] in result:
            fail("producer policy malformed/duplicate")
        result[str(row["producer_id"])] = row
    required = {"structural-gate-harness-v1", "event-ledger-fresh-replay-v1",
                "primary-case-gate-evaluator-case-v1", "primary-case-gate-evaluator-report-v1"}
    if not required.issubset(result):
        fail("required producer policy missing")
    return result


def sealed_tool(root: Path, seal: Mapping[str, Any], key: str, expected: str) -> dict[str, Any]:
    try: row = seal["bindings"]["primary_execution"][key]
    except (KeyError, TypeError): fail(f"sealed tool binding missing: {key}")
    if not isinstance(row, Mapping) or set(row) != {"path", "sha256", "bytes"} or row.get("path") != expected:
        fail(f"sealed tool binding malformed: {key}")
    actual = content_ref(root, root / expected)
    if dict(row) != actual:
        fail(f"sealed tool bytes drifted: {key}")
    return actual


def rows_by_subject(artifact: Mapping[str, Any], contract: Mapping[str, Any], kind: str) -> tuple[str, dict[str, tuple[int, Mapping[str, Any]]]]:
    base = contract.get("result_array_json_pointers", {}).get(kind)
    id_field, kind_field = contract.get("subject_id_field"), contract.get("subject_kind_field")
    if not isinstance(base, str) or not isinstance(id_field, str):
        fail(f"assertion contract has no {kind} result array")
    rows = pointer(artifact, base)
    if not isinstance(rows, list):
        fail(f"result array is not an array: {base}")
    result: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not isinstance(row.get(id_field), str):
            fail(f"malformed result row: {base}/{index}")
        if kind_field is not None and row.get(kind_field) != kind:
            fail(f"subject kind mismatch: {base}/{index}")
        subject = str(row[id_field])
        if subject in result:
            fail(f"duplicate subject: {kind}:{subject}")
        result[subject] = (index, row)
    return base, result


def exact_scope(artifact: Mapping[str, Any], policy: Mapping[str, Any], kind: str) -> None:
    _, actual = rows_by_subject(artifact, policy["assertion_contract"], kind)
    expected = policy.get("allowed_subjects", {}).get(kind, [])
    if list(actual) != list(expected):
        fail(f"{kind} subject scope/order differs from scoring policy: {list(actual)} != {expected}")


def producer(root: Path, seal: Mapping[str, Any], policy: Mapping[str, Any], producer_id: str,
             key: str, tool: str, source_refs: Mapping[str, Mapping[str, Any]],
             replay: dict[str, Any]) -> dict[str, Any]:
    tool_ref = sealed_tool(root, seal, key, tool)
    descriptor = build_invocation_descriptor(
        producer_id=producer_id, tool_ref=tool_ref,
        replay_policy=policy["replay_contract"], replay_claim=replay,
        source_refs=source_refs, output_ref_id="producer_artifact")
    replay["invocation_sha256"] = invocation_sha256(descriptor)
    return {"policy": "SEALED_AUTOMATED_GENERATOR", "producer_id": producer_id,
            "tool_ref": tool_ref, "artifact_ref_id": "producer_artifact", "replay": replay}


def evidence(root: Path, seal: Mapping[str, Any], policy: Mapping[str, Any], producer_id: str,
             artifact: Mapping[str, Any], kind: str, subject: str,
             source_refs: Mapping[str, Mapping[str, Any]], replay: dict[str, Any],
             tool_key: str, tool: str) -> dict[str, Any]:
    allowed = policy.get("allowed_subjects", {}).get(kind, [])
    if subject not in allowed:
        fail(f"producer not allowed for {kind}:{subject}")
    contract = policy.get("assertion_contract")
    if not isinstance(contract, Mapping):
        fail("assertion contract missing")
    assertions: list[dict[str, Any]] = []
    truth: list[bool] = []
    mode = contract.get("mode")
    if mode in {"SUBJECT_RESULT_ROW_EXACT_V1", "SUBJECT_RESULT_ROW_EXHAUSTIVE_CHECKS_V1"}:
        base, by_id = rows_by_subject(artifact, contract, kind)
        if subject not in by_id:
            fail(f"subject missing: {kind}:{subject}")
        index, row = by_id[subject]
        result_field = contract.get("result_field")
        claimed = row.get(result_field)
        if claimed not in {"PASS", "FAIL"}:
            fail(f"incomplete result: {kind}:{subject}")
        result_pointer = f"{base}/{index}/{result_field}"
        assertions.append({"assertion_id": f"{subject}.result", "source_ref_id": "producer_artifact",
                           "observed_json_pointer": result_pointer, "observed": claimed,
                           "expected": claimed, "operator": "EQ"})
        truth.append(True)
        if mode.endswith("EXHAUSTIVE_CHECKS_V1"):
            checks_field = contract.get("checks_field")
            fields = [contract.get(name) for name in (
                "check_id_field", "check_observed_field", "check_expected_field",
                "check_operator_field", "check_pass_field")]
            if not isinstance(checks_field, str) or any(not isinstance(x, str) for x in fields):
                fail("exhaustive assertion contract malformed")
            idf, obf, exf, opf, paf = fields
            checks = row.get(checks_field)
            if not isinstance(checks, list) or not checks:
                fail(f"checks missing: {kind}:{subject}")
            seen: set[str] = set()
            derived: list[bool] = []
            for ci, check in enumerate(checks):
                if not isinstance(check, Mapping) or not isinstance(check.get(idf), str) or check[idf] in seen:
                    fail("check malformed/duplicate")
                seen.add(str(check[idf]))
                passed = check.get(paf)
                if not isinstance(passed, bool) or not isinstance(check.get(opf), str):
                    fail("check pass/operator malformed")
                actual = operator(str(check[opf]), check.get(obf), check.get(exf))
                if actual is not passed:
                    fail("check passed flag is not recomputable")
                derived.append(actual); truth.append(passed)
                assertions.append({"assertion_id": f"{subject}.check.{ci}", "source_ref_id": "producer_artifact",
                                   "observed_json_pointer": f"{base}/{index}/{checks_field}/{ci}/{paf}",
                                   "observed": passed, "expected": True, "operator": "EQ"})
            if claimed != ("PASS" if all(derived) else "FAIL"):
                fail("computed_result does not derive from exhaustive checks")
        elif claimed == "FAIL":
            # Fixed exact-result policy cannot create the false assertion the
            # scorer requires for a complete FAIL. Never invent one.
            fail(f"exact-result policy cannot package complete FAIL evidence: {subject}")
    elif mode == "SUBJECT_EXACT_POINTERS_V1":
        specs = contract.get("subject_assertions", {}).get(kind, {}).get(subject)
        if not isinstance(specs, list) or not specs:
            fail(f"fixed assertions missing: {kind}:{subject}")
        for index, spec in enumerate(specs):
            if not isinstance(spec, Mapping) or set(spec) != {"json_pointer", "expected", "operator"}:
                fail("fixed assertion malformed")
            observed = pointer(artifact, spec["json_pointer"])
            passed = operator(spec["operator"], observed, spec["expected"])
            truth.append(passed)
            assertions.append({"assertion_id": f"{subject}.fixed.{index}", "source_ref_id": "producer_artifact",
                               "observed_json_pointer": spec["json_pointer"], "observed": observed,
                               "expected": spec["expected"], "operator": spec["operator"]})
        claimed = "PASS" if all(truth) else "FAIL"
    else:
        fail(f"unsupported assertion contract: {mode}")
    prod = producer(root, seal, policy, producer_id, tool_key, tool, source_refs, replay)
    doc = {"schema_version": "ncf.primary-gate-evidence.v3", "subject_kind": kind,
           "subject_id": subject, "claimed_result": claimed, "producer": prod,
           "source_artifact_refs": [dict(row) for row in source_refs.values()],
           "assertions": assertions}
    validate(root, doc, EVIDENCE_SCHEMA, f"{kind}:{subject} evidence")
    if claimed == "PASS" and not all(truth):
        fail("PASS not supported by assertions")
    if claimed == "FAIL" and all(truth):
        fail("FAIL has no false assertion")
    return doc


def validate_eval_pair(root: Path, eval_path: Path, manifest_path: Path,
                       evaluation: Mapping[str, Any], manifest: Mapping[str, Any],
                       stage: str, evaluation_kind: str) -> None:
    validate(root, evaluation, EVAL_SCHEMA, "evaluation")
    validate(root, manifest, MANIFEST_SCHEMA, "evaluator manifest")
    if manifest.get("stage") != stage or evaluation.get("evaluation_kind") != evaluation_kind:
        fail("evaluation stage/kind mismatch")
    raw = manifest_path.read_bytes()
    digest = evaluation.get("input_manifest_digest")
    if not isinstance(digest, Mapping) or digest.get("sha256") != sha(raw) or digest.get("bytes") != len(raw):
        fail("evaluation is not bound to evaluator manifest bytes")


def write_once(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fail(f"refusing to overwrite: {path}")
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical(value)); handle.flush(); os.fsync(handle.fileno())


def future_ref(root: Path, staging: Path, final: Path) -> dict[str, Any]:
    raw = staging.read_bytes()
    return {"path": rel(root, final, False), "sha256": sha(raw), "bytes": len(raw)}


def prepare_output(root: Path, requested: Path) -> tuple[Path, Path]:
    final = requested.resolve(strict=False)
    try: final.relative_to(root)
    except ValueError: fail("output must be inside study root")
    if final.exists():
        fail(f"refusing to overwrite output directory: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    parent = final.parent.resolve(strict=True)
    parent.relative_to(root)
    staging = parent / f".{final.name}.staging-{os.getpid()}"
    if staging.exists():
        fail(f"staging already exists: {staging}")
    staging.mkdir()
    return final, staging


def package_digest(receipt: Mapping[str, Any]) -> str:
    payload = dict(receipt); payload.pop("package_digest", None)
    return sha(canonical(payload)[:-1])


def check_receipt(root: Path, receipt: Mapping[str, Any]) -> None:
    validate(root, receipt, RECEIPT_SCHEMA, "package receipt")
    if receipt.get("package_digest") != package_digest(receipt):
        fail("package receipt digest mismatch")


def common(root: Path, inputs: Mapping[str, Any]) -> dict[str, Any]:
    paths = {name: resolve_ref(root, row, name) for name, row in inputs.items()}
    seal = verify_seal(root, inputs["combined_preprimary_seal"])
    scoring, gates = load(root / SCORING, "scoring"), load(root / GATES, "gates")
    order = [row.get("id") for row in gates.get("gates", []) if isinstance(row, Mapping)]
    if len(order) != 30 or len(set(order)) != 30 or order[-1] != REPORT_GATE:
        fail("gate contract is not exact ordered 30")
    policy = policies(scoring)
    structural, event = load(paths["structural_results"], "structural"), load(paths["event_replay_report"], "event replay")
    case_eval, case_manifest = load(paths["case_evaluation"], "case evaluation"), load(paths["case_evaluator_manifest"], "case manifest")
    validate(root, structural, STRUCT_SCHEMA, "structural")
    validate(root, event, EVENT_SCHEMA, "event replay")
    validate_eval_pair(root, paths["case_evaluation"], paths["case_evaluator_manifest"],
                       case_eval, case_manifest, "CASE_EVALUATION", "CASE_AND_COVERAGE")
    exact_scope(structural, policy["structural-gate-harness-v1"], "GATE")
    exact_scope(case_eval, policy["primary-case-gate-evaluator-case-v1"], "GATE")
    exact_scope(case_eval, policy["primary-case-gate-evaluator-case-v1"], "COMPLEX_COVERAGE")
    return {"paths": paths, "seal": seal, "scoring": scoring, "gates": gates,
            "order": order, "policy": policy, "structural": structural,
            "event": event, "case_eval": case_eval}


def build_pre_evidence(root: Path, c: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    p, paths, seal = c["policy"], c["paths"], c["seal"]
    sr = named("producer_artifact", content_ref(root, paths["structural_results"]))
    gates: dict[str, Mapping[str, Any]] = {}
    # Routing is policy-derived. This supports the frozen 23 structural +
    # 6 case routing (PL-IND-001 is no longer hard-coded to either producer).
    for subject in p["structural-gate-harness-v1"]["allowed_subjects"]["GATE"]:
        if subject == "PL-LED-002":
            continue  # fresh replay is the authoritative producer
        replay = {"adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1", "input_ref_ids": {},
                  "check_args": {"generated_at": str(c["structural"].get("generated_at"))},
                  "invocation_sha256": "0" * 64}
        gates[subject] = evidence(root, seal, p["structural-gate-harness-v1"],
            "structural-gate-harness-v1", c["structural"], "GATE", subject,
            {"producer_artifact": sr}, replay, "structural_gate_harness", STRUCT_TOOL)
    er = {
        "bundle": named("bundle", content_ref(root, paths["event_replay_bundle"])),
        "model": named("model", content_ref(root, paths["model"])),
        "producer_artifact": named("producer_artifact", content_ref(root, paths["event_replay_report"])),
    }
    replay = {"adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
              "input_ref_ids": {"bundle": "bundle", "model": "model"},
              "check_args": {}, "invocation_sha256": "0" * 64}
    gates["PL-LED-002"] = evidence(root, seal, p["event-ledger-fresh-replay-v1"],
        "event-ledger-fresh-replay-v1", c["event"], "GATE", "PL-LED-002",
        er, replay, "event_ledger_replay", EVENT_TOOL)
    replay2 = {"adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
               "input_ref_ids": {"bundle": "bundle", "model": "model"},
               "check_args": {}, "invocation_sha256": "0" * 64}
    coverage: dict[str, Mapping[str, Any]] = {"recursive_updates": evidence(
        root, seal, p["event-ledger-fresh-replay-v1"], "event-ledger-fresh-replay-v1",
        c["event"], "COMPLEX_COVERAGE", "recursive_updates", er, replay2,
        "event_ledger_replay", EVENT_TOOL)}
    cr = {
        "input_manifest": named("input_manifest", content_ref(root, paths["case_evaluator_manifest"])),
        "producer_artifact": named("producer_artifact", content_ref(root, paths["case_evaluation"])),
    }
    cp = p["primary-case-gate-evaluator-case-v1"]
    for kind, ids, target in (("GATE", cp["allowed_subjects"]["GATE"], gates),
                              ("COMPLEX_COVERAGE", cp["allowed_subjects"]["COMPLEX_COVERAGE"], coverage)):
        for subject in ids:
            replay = {"adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
                      "input_ref_ids": {"input_manifest": "input_manifest"},
                      "check_args": {"subcommand": "evaluate-case"},
                      "invocation_sha256": "0" * 64}
            target[subject] = evidence(root, seal, cp,
                "primary-case-gate-evaluator-case-v1", c["case_eval"], kind,
                subject, cr, replay, "primary_case_gate_evaluator", EVAL_TOOL)
    expected = set(c["order"][:-1])
    if set(gates) != expected or len(gates) != 29:
        fail(f"pre-report gate routing is not exact: missing={expected-set(gates)}, unknown={set(gates)-expected}")
    if set(coverage) != set(COVERAGE_ORDER) or len(coverage) != 7:
        fail("coverage routing is not exact seven")
    return gates, coverage


def write_evidence(root: Path, staging: Path, final: Path, doc: Mapping[str, Any]) -> dict[str, Any]:
    name = f"{doc['subject_kind']}-{doc['subject_id']}.json"
    path = staging / "evidence" / name
    write_once(path, doc)
    return future_ref(root, path, final / "evidence" / name)


def result_rows(index: Mapping[str, tuple[str, Mapping[str, Any]]], order: Sequence[str], key: str) -> list[dict[str, Any]]:
    if set(index) != set(order) or len(index) != len(order):
        fail(f"{key} missing/duplicate/unknown")
    return [{key: item, "result": index[item][0], "evidence_refs": [dict(index[item][1])]} for item in order]


def base_receipt(root: Path, phase: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ncf.primary-json-evidence-package.v1", "phase": phase,
        "packager_tool": content_ref(root, root / THIS_TOOL),
        "frozen_contracts": {"scoring": content_ref(root, root / SCORING),
            "gates": content_ref(root, root / GATES),
            "combined_preprimary_seal": dict(inputs["combined_preprimary_seal"])},
        "inputs": {key: dict(inputs[key]) for key in sorted(inputs)},
        "invariants": {"write_once": True, "schema_validated": True,
            "all_results_source_derived": True, "manual_pass_forbidden": True,
            "exact_gate_set": True, "exact_coverage_set": True,
            "unknown_duplicate_missing_rejected": True},
    }


def package_pre(root: Path, manifest: Mapping[str, Any], output: Path) -> dict[str, Path]:
    inputs = manifest["inputs"]
    required = {"structural_results", "event_replay_report", "event_replay_bundle",
                "model", "case_evaluation", "case_evaluator_manifest",
                "combined_preprimary_seal"}
    if set(inputs) != required:
        fail(f"PRE_REPORT inputs not exact: missing={required-set(inputs)}, unknown={set(inputs)-required}")
    c = common(root, inputs)
    gate_docs, coverage_docs = build_pre_evidence(root, c)
    final, staging = prepare_output(root, output)
    try:
        gi: dict[str, tuple[str, Mapping[str, Any]]] = {}
        ci: dict[str, tuple[str, Mapping[str, Any]]] = {}
        for subject in c["order"][:-1]:
            ref = write_evidence(root, staging, final, gate_docs[subject])
            gi[subject] = (str(gate_docs[subject]["claimed_result"]), ref)
        for subject in COVERAGE_ORDER:
            ref = write_evidence(root, staging, final, coverage_docs[subject])
            ci[subject] = (str(coverage_docs[subject]["claimed_result"]), ref)
        gates = {"schema_version": "ncf.primary-gate-evidence-bundle.v1",
            "contract_id": c["gates"]["contract_id"],
            "contract_version": c["gates"]["contract_version"],
            "correct_diagnosis_reported": False,
            "gate_results": result_rows(gi, c["order"][:-1], "gate_id")}
        coverage = {"schema_version": "ncf.primary-complex-case-coverage.v1",
                    "checks": result_rows(ci, COVERAGE_ORDER, "coverage_id")}
        validate(root, gates, GATE_BUNDLE_SCHEMA, "pre-report bundle")
        validate(root, coverage, COVERAGE_SCHEMA, "coverage bundle")
        gp, cp = staging / "pre_report_gate_results.json", staging / "complex_case_coverage.json"
        write_once(gp, gates); write_once(cp, coverage)
        receipt = base_receipt(root, "PRE_REPORT", inputs)
        receipt.update({
            "gate_evidence": [{"subject_id": s, "result": gi[s][0], "evidence_ref": dict(gi[s][1])} for s in c["order"][:-1]],
            "coverage_evidence": [{"subject_id": s, "result": ci[s][0], "evidence_ref": dict(ci[s][1])} for s in COVERAGE_ORDER],
            "gate_bundle": future_ref(root, gp, final / gp.name),
            "coverage_bundle": future_ref(root, cp, final / cp.name),
        })
        receipt["package_digest"] = package_digest(receipt); check_receipt(root, receipt)
        rp = staging / "package_receipt.json"; write_once(rp, receipt)
        staging.rename(final)
        return {"gate_bundle": final / gp.name, "coverage_bundle": final / cp.name,
                "receipt": final / rp.name}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True); raise


def verify_old_evidence(root: Path, row: Mapping[str, Any], kind: str, id_key: str) -> None:
    refs = row.get("evidence_refs")
    if not isinstance(refs, list) or len(refs) != 1:
        fail("bundle row evidence ref cardinality")
    doc = load(resolve_ref(root, refs[0], "prior evidence"), "prior evidence")
    validate(root, doc, EVIDENCE_SCHEMA, "prior evidence")
    if (doc.get("subject_kind") != kind or doc.get("subject_id") != row.get(id_key)
            or doc.get("claimed_result") != row.get("result")
            or doc.get("producer", {}).get("policy") != "SEALED_AUTOMATED_GENERATOR"):
        fail("prior evidence subject/result/producer mismatch")


def verify_pre(root: Path, inputs: Mapping[str, Any], c: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    receipt = load(resolve_ref(root, inputs["pre_report_receipt"], "pre receipt"), "pre receipt")
    check_receipt(root, receipt)
    if receipt.get("phase") != "PRE_REPORT":
        fail("pre receipt phase mismatch")
    base_keys = ("structural_results", "event_replay_report", "event_replay_bundle",
                 "model", "case_evaluation", "case_evaluator_manifest",
                 "combined_preprimary_seal")
    for key in base_keys:
        if not same(receipt.get("inputs", {}).get(key, {}), inputs[key]):
            fail(f"source changed after pre-report packaging: {key}")
    if not same(receipt.get("gate_bundle", {}), inputs["pre_report_gate_bundle"]):
        fail("pre gate bundle ref differs from receipt")
    if not same(receipt.get("coverage_bundle", {}), inputs["coverage_bundle"]):
        fail("coverage bundle ref differs from receipt")
    gates = load(resolve_ref(root, inputs["pre_report_gate_bundle"], "pre gates"), "pre gates")
    coverage = load(resolve_ref(root, inputs["coverage_bundle"], "coverage"), "coverage")
    validate(root, gates, GATE_BUNDLE_SCHEMA, "pre gates")
    validate(root, coverage, COVERAGE_SCHEMA, "coverage")
    rows, checks = gates.get("gate_results"), coverage.get("checks")
    if not isinstance(rows, list) or [r.get("gate_id") for r in rows] != list(c["order"][:-1]):
        fail("pre bundle is not exact ordered 29")
    if not isinstance(checks, list) or [r.get("coverage_id") for r in checks] != list(COVERAGE_ORDER):
        fail("coverage is not exact ordered seven")
    for row in rows: verify_old_evidence(root, row, "GATE", "gate_id")
    for row in checks: verify_old_evidence(root, row, "COMPLEX_COVERAGE", "coverage_id")
    return receipt, gates, coverage


def package_final(root: Path, manifest: Mapping[str, Any], output: Path) -> dict[str, Path]:
    inputs = manifest["inputs"]
    required = {"structural_results", "event_replay_report", "event_replay_bundle",
        "model", "case_evaluation", "case_evaluator_manifest", "combined_preprimary_seal",
        "report_evaluation", "report_evaluator_manifest", "pre_report_receipt",
        "pre_report_gate_bundle", "coverage_bundle"}
    if set(inputs) != required:
        fail(f"FINAL inputs not exact: missing={required-set(inputs)}, unknown={set(inputs)-required}")
    c = common(root, inputs)
    pre_receipt, pre_gates, coverage = verify_pre(root, inputs, c)
    report_eval = load(c["paths"]["report_evaluation"], "report evaluation")
    report_manifest = load(c["paths"]["report_evaluator_manifest"], "report manifest")
    validate_eval_pair(root, c["paths"]["report_evaluation"], c["paths"]["report_evaluator_manifest"],
                       report_eval, report_manifest, "REPORT_CONSISTENCY", "REPORT_CONSISTENCY")
    rp = c["policy"]["primary-case-gate-evaluator-report-v1"]
    exact_scope(report_eval, rp, "GATE")
    if report_eval.get("coverage_results") != []:
        fail("report evaluation may not assert coverage")
    refs = {"input_manifest": named("input_manifest", content_ref(root, c["paths"]["report_evaluator_manifest"])),
            "producer_artifact": named("producer_artifact", content_ref(root, c["paths"]["report_evaluation"]))}
    replay = {"adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
              "input_ref_ids": {"input_manifest": "input_manifest"},
              "check_args": {"subcommand": "evaluate-report"},
              "invocation_sha256": "0" * 64}
    report_doc = evidence(root, c["seal"], rp,
        "primary-case-gate-evaluator-report-v1", report_eval, "GATE", REPORT_GATE,
        refs, replay, "primary_case_gate_evaluator", EVAL_TOOL)
    final, staging = prepare_output(root, output)
    try:
        report_ref = write_evidence(root, staging, final, report_doc)
        final_rows = [dict(row) for row in pre_gates["gate_results"]] + [{
            "gate_id": REPORT_GATE, "result": report_doc["claimed_result"],
            "evidence_refs": [report_ref]}]
        if [r["gate_id"] for r in final_rows] != list(c["order"]):
            fail("final bundle is not exact ordered 30")
        bundle = {"schema_version": "ncf.primary-gate-evidence-bundle.v1",
            "contract_id": c["gates"]["contract_id"],
            "contract_version": c["gates"]["contract_version"],
            "correct_diagnosis_reported": False, "gate_results": final_rows}
        validate(root, bundle, GATE_BUNDLE_SCHEMA, "final gate bundle")
        gp = staging / "final_gate_results.json"; write_once(gp, bundle)
        receipt = base_receipt(root, "FINAL", inputs)
        receipt.update({
            "gate_evidence": [{"subject_id": r["gate_id"], "result": r["result"],
                               "evidence_ref": dict(r["evidence_refs"][0])} for r in final_rows],
            "coverage_evidence": [dict(row) for row in pre_receipt["coverage_evidence"]],
            "gate_bundle": future_ref(root, gp, final / gp.name),
            "coverage_bundle": dict(inputs["coverage_bundle"]),
            "pre_report_receipt": dict(inputs["pre_report_receipt"]),
        })
        receipt["package_digest"] = package_digest(receipt); check_receipt(root, receipt)
        rpath = staging / "package_receipt.json"; write_once(rpath, receipt)
        staging.rename(final)
        return {"gate_bundle": final / gp.name,
                "coverage_bundle": resolve_ref(root, inputs["coverage_bundle"], "coverage"),
                "receipt": final / rpath.name}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True); raise


def package(root: Path, manifest_path: Path, output: Path) -> dict[str, Path]:
    root = root.resolve(strict=True)
    manifest = load(manifest_path, "packager manifest")
    validate(root, manifest, INPUT_SCHEMA, "packager manifest")
    if manifest.get("phase") == "PRE_REPORT":
        return package_pre(root, manifest, output)
    if manifest.get("phase") == "FINAL":
        return package_final(root, manifest, output)
    fail("unknown phase")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        outputs = package(args.study_root, args.manifest, args.output_dir)
        print(json.dumps({"status": "PASS", **{k: str(v) for k, v in outputs.items()}}, sort_keys=True))
        return 0
    except (PackagingError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
