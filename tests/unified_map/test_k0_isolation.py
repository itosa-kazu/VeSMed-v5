from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "research" / "unified_map" / "K0_FROZEN_INVENTORY.json"
UCM_PACKAGE = ROOT / "prototype" / "unified_map"


def _manifest() -> dict[str, object]:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _filtered_blob_id(path: Path) -> str:
    relative = path.relative_to(ROOT).as_posix()
    return subprocess.check_output(
        [
            "git",
            "hash-object",
            f"--path={relative}",
            "--filters",
            relative,
        ],
        cwd=ROOT,
        text=True,
    ).strip()


def _base_blob_bytes(base: str, relative: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{base}:{relative}"], cwd=ROOT
    )


def _assert_matches_base_blob(row: dict[str, object], base: str) -> None:
    relative = str(row["path"])
    path = ROOT / relative
    assert _filtered_blob_id(path) == row["git_blob_sha1"]
    blob = _base_blob_bytes(base, relative)
    assert len(blob) == int(row["git_blob_bytes"])
    assert "sha256:" + hashlib.sha256(blob).hexdigest() == row[
        "git_blob_sha256"
    ]


def test_frozen_k0_result_tree_is_byte_identical() -> None:
    manifest = _manifest()
    base = str(manifest["base_commit"])
    tree = manifest["frozen_result_tree"]
    assert isinstance(tree, dict)
    expected_rows = tree["files"]
    assert isinstance(expected_rows, list)

    actual_paths = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / str(tree["path"])).rglob("*")
        if path.is_file()
    }
    expected_paths = {str(row["path"]) for row in expected_rows}
    assert actual_paths == expected_paths

    for row in expected_rows:
        assert isinstance(row, dict)
        _assert_matches_base_blob(row, base)


def test_historical_k0_decision_documents_are_byte_identical() -> None:
    manifest = _manifest()
    base = str(manifest["base_commit"])
    rows = manifest["historical_decision_documents"]
    assert isinstance(rows, list)
    assert rows
    for row in rows:
        assert isinstance(row, dict)
        _assert_matches_base_blob(row, base)


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _is_forbidden(module: str) -> bool:
    if module == "prototype.unified_map" or module.startswith(
        "prototype.unified_map."
    ):
        return False
    if module == "prototype" or module.startswith("prototype."):
        return True
    return module == "tests.workloads" or module.startswith(
        ("tests.workloads.", "tests.bridge_holdout")
    )


def test_ucm_package_has_no_import_dependency_on_k0_or_bridge() -> None:
    violations: list[str] = []
    for path in sorted(UCM_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in sorted(_imported_modules(tree)):
            if _is_forbidden(module):
                violations.append(
                    f"{path.relative_to(ROOT).as_posix()}: forbidden import {module}"
                )
    assert violations == []


def test_ucm_output_tree_is_disjoint_from_frozen_k0_results() -> None:
    ucm_results = (ROOT / "results" / "unified_map").resolve()
    frozen_results = (
        ROOT / "results" / "20260713T120910Z-panel-v3"
    ).resolve()
    assert ucm_results != frozen_results
    assert ucm_results not in frozen_results.parents
    assert frozen_results not in ucm_results.parents
