"""可复查的原型规模、复杂度与反测试特例计量。

这个模块只做静态结构计量和 manifest 盘点；它不运行 workload，也不读取
benchmark oracle。这样生成的快照可以作为扩展实验前后的比较输入，而不会
把评分器本身混入候选实现。

默认用法::

    python -m prototype.metrics --output results/metrics-current.json

后续扩展实验可把基线作为比较输入::

    python -m prototype.metrics --baseline results/metrics-current.json \
        --output results/metrics-after-extension.json

除非显式传入 ``--force``，输出文件已存在时会拒绝覆盖。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .candidates.causal_state import CausalStateCandidate
from .candidates.rewrite_open import RewriteOpenCandidate
from .candidates.temporal_ledger import TemporalEvidenceLedger
from .contract import ArchitectureCandidate
from .kernel import ClinicalKernel
from .model_subkernel import ExperimentalModelSubkernel


SCHEMA_VERSION = "1.0.0"

# 这里只列评分器/测试身份字段。临床 case_id 不是测试身份，因此有意不列入。
SUSPICIOUS_IDENTIFIERS = frozenset(
    {
        "workload_id",
        "test_id",
        "oracle",
        "oracle_view",
        "reference_output",
        "expected_output",
        "expected_result",
    }
)
SUSPICIOUS_STRING_FIELDS = SUSPICIOUS_IDENTIFIERS
TEST_ID_RE = re.compile(r"(?<![A-Za-z0-9_])[TE]\d{2}(?![A-Za-z0-9_])")
RULE_CLASS_RE = re.compile(
    r"(?:Rule|Premise|Guard|Constraint|Factor|Equation|Transition|Module)$"
)
REFERENCE_MODULE_PARTS = frozenset(
    {
        "benchmark",
        "workloads",
        "reference_models",
        "isolated_benchmark",
        "isolated_worker",
    }
)


@dataclass(frozen=True)
class CandidateTarget:
    """候选实现和其静态计量边界。"""

    key: str
    module_name: str
    source_files: tuple[str, ...]
    factory: Callable[[], ArchitectureCandidate]


DEFAULT_TARGETS: tuple[CandidateTarget, ...] = (
    CandidateTarget(
        key="temporal_ledger",
        module_name="prototype.candidates.temporal_ledger",
        source_files=("prototype/candidates/temporal_ledger.py",),
        factory=TemporalEvidenceLedger,
    ),
    CandidateTarget(
        key="causal_state",
        module_name="prototype.candidates.causal_state",
        source_files=("prototype/candidates/causal_state.py",),
        factory=CausalStateCandidate,
    ),
    CandidateTarget(
        key="rewrite_open",
        module_name="prototype.candidates.rewrite_open",
        source_files=("prototype/candidates/rewrite_open.py",),
        factory=RewriteOpenCandidate,
    ),
    CandidateTarget(
        key="clinical_kernel",
        module_name="prototype.kernel",
        source_files=("prototype/kernel.py",),
        factory=ClinicalKernel,
    ),
    CandidateTarget(
        key="model_subkernel",
        module_name="prototype.model_subkernel",
        source_files=("prototype/model_subkernel.py",),
        factory=ExperimentalModelSubkernel,
    ),
)

FIXED_CORE_GROUPS: Mapping[str, tuple[str, ...]] = {
    "shared_control_plane": (
        "prototype/contract.py",
        "prototype/ir.py",
    ),
    "candidate_engines": tuple(
        source
        for target in DEFAULT_TARGETS
        for source in target.source_files
    ),
}

HARNESS_FILES: tuple[str, ...] = (
    "prototype/benchmark.py",
    "prototype/workloads.py",
    "prototype/reference_models.py",
    "prototype/isolated_benchmark.py",
    "prototype/isolated_worker.py",
    "prototype/experiment.py",
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_source(path: Path) -> tuple[bytes, str, ast.Module]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    return raw, text, ast.parse(text, filename=path.as_posix())


def _decision_points(tree: ast.AST) -> int:
    """返回有明确口径的 cyclomatic-complexity 近似决策点数。"""

    points = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While)):
            points += 1
        elif isinstance(node, ast.Try):
            points += len(node.handlers)
        elif isinstance(node, ast.Match):
            points += max(0, len(node.cases) - 1)
        elif isinstance(node, ast.BoolOp):
            points += max(0, len(node.values) - 1)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            points += len(node.generators)
            points += sum(len(generator.ifs) for generator in node.generators)
    return points


def _definition_counts(tree: ast.Module) -> dict[str, Any]:
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    top_level_functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    method_count = sum(
        1
        for cls in classes
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    rule_classes = sorted({node.name for node in classes if RULE_CLASS_RE.search(node.name)})
    return {
        "class_count": len(classes),
        "class_names": sorted(node.name for node in classes),
        "function_count_including_methods_and_nested": len(functions),
        "top_level_function_count": len(top_level_functions),
        "method_count": method_count,
        "async_function_count": sum(isinstance(node, ast.AsyncFunctionDef) for node in functions),
        "closed_ir_rule_like_class_count": len(rule_classes),
        "closed_ir_rule_like_class_names": rule_classes,
    }


def _relative_import_module(current_module: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package_parts = current_module.split(".")[:-1]
    ascend = max(0, node.level - 1)
    if ascend:
        package_parts = package_parts[:-ascend]
    if node.module:
        package_parts.extend(node.module.split("."))
    return ".".join(package_parts)


def _imports(tree: ast.Module, current_module: str) -> list[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(_relative_import_module(current_module, node))
    return sorted(item for item in imported if item)


def _condition_nodes(tree: ast.Module) -> Iterable[tuple[ast.AST, ast.AST]]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            yield node, node.test
        elif isinstance(node, ast.Match):
            yield node, node.subject


def _suspicious_tokens(node: ast.AST) -> tuple[set[str], set[str]]:
    identifiers: set[str] = set()
    literals: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in SUSPICIOUS_IDENTIFIERS:
            identifiers.add(child.id)
        elif isinstance(child, ast.Attribute) and child.attr in SUSPICIOUS_IDENTIFIERS:
            identifiers.add(child.attr)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            if child.value in SUSPICIOUS_STRING_FIELDS:
                identifiers.add(child.value)
            literals.update(TEST_ID_RE.findall(child.value))
    return identifiers, literals


def _anti_dispatch_scan(text: str, tree: ast.Module, imports: Sequence[str]) -> dict[str, Any]:
    lines = text.splitlines()
    literal_locations: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        for match in TEST_ID_RE.finditer(line):
            literal_locations.append(
                {"line": line_number, "literal": match.group(0), "text": line.strip()[:240]}
            )

    identifier_counts: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in SUSPICIOUS_IDENTIFIERS:
            identifier_counts[node.id] += 1
        elif isinstance(node, ast.Attribute) and node.attr in SUSPICIOUS_IDENTIFIERS:
            identifier_counts[node.attr] += 1
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in SUSPICIOUS_STRING_FIELDS
        ):
            identifier_counts[node.value] += 1

    dispatch_sites: list[dict[str, Any]] = []
    for owner, condition in _condition_nodes(tree):
        identifiers, literals = _suspicious_tokens(condition)
        if not identifiers and not literals:
            continue
        source = ast.get_source_segment(text, condition) or ""
        dispatch_sites.append(
            {
                "line": getattr(owner, "lineno", None),
                "node_type": type(owner).__name__,
                "suspicious_identifiers": sorted(identifiers),
                "test_id_literals": sorted(literals),
                "condition": " ".join(source.split())[:500],
            }
        )

    forbidden_imports = [
        module
        for module in imports
        if any(part in REFERENCE_MODULE_PARTS for part in module.split("."))
    ]
    return {
        "literal_test_id_count": len(literal_locations),
        "literal_test_id_locations": literal_locations,
        "suspicious_identifier_occurrences": dict(sorted(identifier_counts.items())),
        "test_or_oracle_dispatch_site_count": len(dispatch_sites),
        "test_or_oracle_dispatch_sites": dispatch_sites,
        "forbidden_harness_or_reference_import_count": len(forbidden_imports),
        "forbidden_harness_or_reference_imports": forbidden_imports,
        # 这是保守静态下界，不等于对所有领域特例的完备证明。
        "static_special_case_indicator_count": (
            len(literal_locations) + len(dispatch_sites) + len(forbidden_imports)
        ),
    }


def _file_metrics(path: Path, relative_path: str, module_name: str) -> dict[str, Any]:
    raw, text, tree = _read_source(path)
    lines = text.splitlines()
    blank = sum(not line.strip() for line in lines)
    comment_only = sum(line.lstrip().startswith("#") for line in lines)
    statement_count = sum(isinstance(node, ast.stmt) for node in ast.walk(tree))
    decision_points = _decision_points(tree)
    imports = _imports(tree, module_name)
    metrics: dict[str, Any] = {
        "path": relative_path,
        "sha256": _sha256_bytes(raw),
        "bytes": len(raw),
        "loc": {
            "physical_lines": len(lines),
            "blank_lines": blank,
            "comment_only_lines": comment_only,
            "nonblank_non_comment_lines": len(lines) - blank - comment_only,
            "ast_statement_count": statement_count,
        },
        "definitions": _definition_counts(tree),
        "complexity_proxy": {
            "decision_points": decision_points,
            "module_cyclomatic_proxy": decision_points + 1,
        },
        "imports": imports,
    }
    metrics["anti_dispatch_scan"] = _anti_dispatch_scan(text, tree, imports)
    return metrics


def _sum_file_metrics(files: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    loc_keys = (
        "physical_lines",
        "blank_lines",
        "comment_only_lines",
        "nonblank_non_comment_lines",
        "ast_statement_count",
    )
    definition_keys = (
        "class_count",
        "function_count_including_methods_and_nested",
        "top_level_function_count",
        "method_count",
        "async_function_count",
        "closed_ir_rule_like_class_count",
    )
    return {
        "file_count": len(files),
        "loc": {
            key: sum(int(file["loc"][key]) for file in files)
            for key in loc_keys
        },
        "definitions": {
            key: sum(int(file["definitions"][key]) for file in files)
            for key in definition_keys
        },
        "complexity_proxy": {
            "decision_points": sum(
                int(file["complexity_proxy"]["decision_points"]) for file in files
            ),
            "per_file_cyclomatic_proxy_sum": sum(
                int(file["complexity_proxy"]["module_cyclomatic_proxy"])
                for file in files
            ),
        },
        "anti_dispatch_scan": {
            "literal_test_id_count": sum(
                int(file["anti_dispatch_scan"]["literal_test_id_count"])
                for file in files
            ),
            "test_or_oracle_dispatch_site_count": sum(
                int(file["anti_dispatch_scan"]["test_or_oracle_dispatch_site_count"])
                for file in files
            ),
            "forbidden_harness_or_reference_import_count": sum(
                int(file["anti_dispatch_scan"]["forbidden_harness_or_reference_import_count"])
                for file in files
            ),
            "static_special_case_indicator_count": sum(
                int(file["anti_dispatch_scan"]["static_special_case_indicator_count"])
                for file in files
            ),
        },
    }


def _manifest_metrics(candidate: ArchitectureCandidate) -> dict[str, Any]:
    manifest = candidate.manifest
    groups: dict[str, list[str]] = {
        str(group): [str(item) for item in items]
        for group, items in manifest.primitive_profile.items()
    }
    primitive_items = [item for items in groups.values() for item in items]
    unique_primitives = sorted(set(primitive_items))
    return {
        "candidate_id": manifest.candidate_id,
        "version": manifest.version,
        "primitive_profile": groups,
        "primitive_group_count": len(groups),
        "primitive_item_count": len(primitive_items),
        "unique_primitive_count": len(unique_primitives),
        "unique_primitives": unique_primitives,
        "formal_signature_count": len(manifest.formal_signature),
        "formal_signature": list(manifest.formal_signature),
        "execution_semantics_count": len(manifest.execution_semantics),
        "execution_semantics": list(manifest.execution_semantics),
        "companion_layer_count": len(manifest.companion_layers),
        "companion_layers": list(manifest.companion_layers),
        "foreign_boundary_count": len(manifest.foreign_boundaries),
        "foreign_boundaries": _jsonable(manifest.foreign_boundaries),
        "declared_query_capability_count": len(manifest.declared_query_capabilities),
        "declared_query_capabilities": [
            query.value for query in manifest.declared_query_capabilities
        ],
        "declared_failure_type_count": len(manifest.failure_types),
        "declared_failure_types": [status.value for status in manifest.failure_types],
    }


def _fingerprint_file(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    if not path.is_file():
        return {"path": relative_path, "exists": False}
    raw = path.read_bytes()
    text = raw.decode("utf-8") if path.suffix == ".py" else None
    result: dict[str, Any] = {
        "path": relative_path,
        "exists": True,
        "sha256": _sha256_bytes(raw),
        "bytes": len(raw),
    }
    if text is not None:
        result["physical_lines"] = len(text.splitlines())
    return result


def _extension_files(root: Path) -> list[str]:
    extension_root = root / "examples" / "extensions"
    if not extension_root.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in extension_root.rglob("*")
        if path.is_file()
    )


def _snapshot_digest(report: Mapping[str, Any]) -> str:
    stable = deepcopy(dict(report))
    stable.pop("generated_at_utc", None)
    stable.pop("report_sha256", None)
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(payload.encode("utf-8"))


def collect_metrics(
    root: str | Path,
    *,
    targets: Sequence[CandidateTarget] = DEFAULT_TARGETS,
) -> dict[str, Any]:
    """采集一个不运行 workload 的可重放静态计量快照。"""

    root_path = Path(root).resolve()
    candidates: dict[str, Any] = {}
    for target in targets:
        files = [
            _file_metrics(root_path / relative, relative, target.module_name)
            for relative in target.source_files
        ]
        candidates[target.key] = {
            "source_files": files,
            "totals": _sum_file_metrics(files),
            "manifest": _manifest_metrics(target.factory()),
        }

    fixed_core: dict[str, list[dict[str, Any]]] = {
        group: [_fingerprint_file(root_path, path) for path in paths]
        for group, paths in FIXED_CORE_GROUPS.items()
    }
    harness = [_fingerprint_file(root_path, path) for path in HARNESS_FILES]
    extensions = [_fingerprint_file(root_path, path) for path in _extension_files(root_path)]

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": root_path.as_posix(),
        "measurement_semantics": {
            "loc": (
                "physical_lines=splitlines; nonblank_non_comment excludes blank and lines whose "
                "first non-space character is #; ast_statement_count counts ast.stmt nodes"
            ),
            "complexity_proxy": (
                "1 + static decision points (if/loop/handler/match/bool/comprehension); "
                "not a runtime or maintainability score"
            ),
            "core_primitive_count": (
                "unique leaf strings explicitly declared in CandidateManifest.primitive_profile; "
                "profile group names are not counted as primitives"
            ),
            "special_case_indicator": (
                "static lower-bound scan for literal Txx/Exx IDs, condition dispatch on test/oracle "
                "identity fields, and imports from benchmark/workload/reference modules; zero is "
                "evidence against these mechanisms, not proof that all domain special cases are absent"
            ),
            "extension_blast_radius": (
                "compare SHA-256 fingerprints of fixed core before and after a data/module extension; "
                "harness and examples/extensions are reported separately"
            ),
        },
        "candidates": candidates,
        "extension_blast_radius_input": {
            "fixed_core_groups": fixed_core,
            "fixed_core_file_count": sum(len(files) for files in fixed_core.values()),
            "evaluation_harness": harness,
            "knowledge_extension_files": extensions,
            "knowledge_extension_file_count": len(extensions),
        },
        "limitations": [
            "静态 LOC/AST 计量不代表医学正确性、临床效用或形式正确性。",
            "manifest 原语数是实现自声明口径；它可审计，但不自动证明原语独立或最小。",
            "rule-like class count 只按类型名后缀计数，不等于运行时加载的知识规则数。",
            "特例扫描只覆盖测试身份/oracle/reference 耦合；领域硬编码仍需代码审查和 holdout 验证。",
            "blast radius 只有与扩展前基线比较时才是观测值；单个快照只是输入。",
        ],
    }
    report["report_sha256"] = _snapshot_digest(report)
    return report


def _fingerprint_map(
    report: Mapping[str, Any],
    section: str,
) -> dict[str, Mapping[str, Any]]:
    blast = report.get("extension_blast_radius_input", {})
    if not isinstance(blast, Mapping):
        return {}
    if section == "fixed_core":
        groups = blast.get("fixed_core_groups", {})
        if not isinstance(groups, Mapping):
            return {}
        items = [item for group in groups.values() for item in group]
    else:
        items = blast.get(section, [])
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return {}
    return {
        str(item["path"]): item
        for item in items
        if isinstance(item, Mapping) and "path" in item
    }


def _compare_file_section(
    baseline: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    before_paths = set(baseline)
    after_paths = set(current)
    shared = before_paths & after_paths
    changed = sorted(
        path
        for path in shared
        if baseline[path].get("sha256") != current[path].get("sha256")
        or baseline[path].get("exists") != current[path].get("exists")
    )
    return {
        "modified_count": len(changed),
        "modified": changed,
        "added_count": len(after_paths - before_paths),
        "added": sorted(after_paths - before_paths),
        "removed_count": len(before_paths - after_paths),
        "removed": sorted(before_paths - after_paths),
    }


def compare_reports(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    """比较扩展前后快照，给出 fixed-core 修改范围。"""

    fixed = _compare_file_section(
        _fingerprint_map(baseline, "fixed_core"),
        _fingerprint_map(current, "fixed_core"),
    )
    harness = _compare_file_section(
        _fingerprint_map(baseline, "evaluation_harness"),
        _fingerprint_map(current, "evaluation_harness"),
    )
    extensions = _compare_file_section(
        _fingerprint_map(baseline, "knowledge_extension_files"),
        _fingerprint_map(current, "knowledge_extension_files"),
    )
    return {
        "baseline_report_sha256": baseline.get("report_sha256"),
        "current_report_sha256": current.get("report_sha256"),
        "fixed_core": fixed,
        "evaluation_harness": harness,
        "knowledge_extensions": extensions,
        "extension_blast_radius_core_files": (
            fixed["modified_count"] + fixed["added_count"] + fixed["removed_count"]
        ),
        "interpretation": (
            "For a knowledge-only extension, expected fixed-core blast radius is 0. "
            "Any nonzero value requires review; it is not automatically wrong."
        ),
    }


def write_report(path: str | Path, report: Mapping[str, Any], *, force: bool = False) -> Path:
    """原子写入 JSON；默认拒绝覆盖已有证据。"""

    destination = Path(path)
    if destination.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing metrics report: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(destination)
    return destination


def _load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"metrics baseline must be a JSON object: {path}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    report = collect_metrics(args.root)
    if args.baseline is not None:
        report["extension_blast_radius_comparison"] = compare_reports(
            _load_json(args.baseline), report
        )
        report["report_sha256"] = _snapshot_digest(report)

    if args.output is None:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        destination = write_report(args.output, report, force=args.force)
        print(destination.resolve())
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
