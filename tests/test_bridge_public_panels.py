from __future__ import annotations

import ast
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

from prototype.reference_models import reference_output


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "research_notes" / "bridge_panel_protocol_v1.json"
PANEL_PATHS = {
    "a": ROOT / "prototype" / "bridge_holdout" / "panel_a.py",
    "b": ROOT / "prototype" / "bridge_holdout" / "panel_b.py",
}
FROZEN_SHA256 = {
    "a": "793e3cf8b9c1a851e7f45627f33880459b425d79fd3bd5aa0f24d62a537cab17",
    "b": "da03a5333accb195202289af68a5269d7707137a90f99efbb8ba3aaaacd27ca1",
}


def _protocol() -> dict[str, Any]:
    value = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert value["schema_version"] == "bridge-panel-protocol-v1"
    return value


def _run_isolated(panel: str, model: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    module_name = f"prototype.bridge_holdout.panel_{panel}"
    script = (
        "import importlib,json,sys; "
        f"m=importlib.import_module({module_name!r}); "
        "p=json.load(sys.stdin); "
        "json.dump(m.execute(p['model'],p['query']),sys.stdout,sort_keys=True)"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        input=json.dumps({"model": model, "query": query}, sort_keys=True),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
        timeout=60,
        env={"PYTHONPATH": str(ROOT)},
    )
    # ``-I`` intentionally ignores PYTHONPATH; add the repository explicitly
    # inside an otherwise isolated interpreter without importing shared code in
    # either candidate module.
    if completed.returncode != 0 and "No module named 'prototype'" in completed.stderr:
        isolated_script = (
            "import importlib,json,sys; "
            f"sys.path.insert(0,{str(ROOT)!r}); "
            f"m=importlib.import_module({module_name!r}); "
            "p=json.load(sys.stdin); "
            "json.dump(m.execute(p['model'],p['query']),sys.stdout,sort_keys=True)"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-c", isolated_script],
            input=json.dumps({"model": model, "query": query}, sort_keys=True),
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
            timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert type(result) is dict
    return result


def _assert_reference_subset(actual: Any, expected: Any, path: str = "$") -> None:
    if type(expected) is dict:
        assert type(actual) is dict, path
        for key, value in expected.items():
            assert key in actual, f"{path}.{key}"
            _assert_reference_subset(actual[key], value, f"{path}.{key}")
        return
    if type(expected) is list:
        assert type(actual) is list and len(actual) == len(expected), path
        for index, (left, right) in enumerate(zip(actual, expected)):
            _assert_reference_subset(left, right, f"{path}[{index}]")
        return
    if type(expected) in {int, float}:
        assert type(actual) in {int, float}, path
        assert math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6), (
            path,
            actual,
            expected,
        )
        return
    assert actual == expected, (path, actual, expected)


def test_frozen_panels_are_source_distinct_and_have_no_repository_imports() -> None:
    source_hashes: dict[str, str] = {}
    for panel, path in PANEL_PATHS.items():
        source = path.read_bytes()
        source_hashes[panel] = sha256(source).hexdigest()
        assert source_hashes[panel] == FROZEN_SHA256[panel]
        tree = ast.parse(source.decode("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0
                assert not (node.module or "").startswith("prototype")
            elif isinstance(node, ast.Import):
                assert all(not alias.name.startswith("prototype") for alias in node.names)
    assert source_hashes["a"] != source_hashes["b"]


def test_both_panels_match_the_external_e01_e06_reference_in_separate_processes() -> None:
    protocol = _protocol()
    for experiment_id in sorted(protocol["models"]):
        query = protocol["queries"][experiment_id]
        reference = reference_output(experiment_id)
        expected = {key: reference[key] for key in query["outputs"]}
        for panel in PANEL_PATHS:
            result = _run_isolated(panel, protocol["models"][experiment_id], query)
            assert set(result) == {"operator", "value", "trace", "diagnostics"}
            assert result["operator"] == query["operator"]
            _assert_reference_subset(result["value"], expected)


def test_panel_dispatch_is_id_invariant_parameter_sensitive_and_solver_distinct() -> None:
    protocol = _protocol()
    model = protocol["models"]["E02"]
    query = protocol["queries"]["E02"]
    mutated = deepcopy(model)
    mutated["P_severe"] = 0.61
    for panel in PANEL_PATHS:
        baseline = _run_isolated(panel, model, query)
        renamed_query = {**query, "query_id": "opaque-renamed-query"}
        renamed = _run_isolated(panel, model, renamed_query)
        changed = _run_isolated(panel, mutated, query)
        assert baseline["operator"] == renamed["operator"]
        assert baseline["value"] == renamed["value"]
        assert baseline["value"] != changed["value"]

    e01_model = protocol["models"]["E01"]
    e01_query = protocol["queries"]["E01"]
    a = _run_isolated("a", e01_model, e01_query)
    b = _run_isolated("b", e01_model, e01_query)
    assert a["trace"]["solver"]["method"] == "RK4"
    assert "adaptive_step_doubled_heun" in b["trace"]["solver"]

