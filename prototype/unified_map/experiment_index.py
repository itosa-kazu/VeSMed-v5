"""Canonical, replayable registry for executed UCM experiments.

The index is an evidence index, not an experiment runner.  A bound entry must
replay against the immutable run manifest and summary.  An experiment for
which no run exists must remain an explicit ``evidence_gap`` and cannot count
toward the substantive-experiment total.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)


INDEX_PROTOCOL = "ucm-experiment-index/1"
RUN_MANIFEST_PROTOCOL = "ucm-benchmark-v1-run-manifest/1"
FAILED_MANIFEST_PROTOCOL = "ucm-failed-run-manifest/1"
INDEX_FILENAME = Path("research/unified_map/EXPERIMENT_INDEX.json")
_EXPERIMENT_RE = re.compile(r"EXP-(\d{3,})\Z")
_RUN_RE = re.compile(
    r"\d{8}T\d{6}Z-(EXP-\d{3,})-[0-9a-f]{10}\Z"
)
_FAILED_RUN_RE = re.compile(
    r"\d{8}T\d{6}Z-(EXP-\d{3,})-FAILED-[0-9a-f]{10}\Z"
)
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COUNTABLE_CLASSES = frozenset(
    {"architecture", "architecture_refinement", "ablation"}
)
_NONCOUNTABLE_CLASSES = frozenset(
    {"baseline_control", "repeat_full_evaluation", "upper_bound_control"}
)


def _decode_canonical(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} is unavailable or invalid") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ProtocolViolation(f"{label} keys mismatch")


def _require_digest(value: Any, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} is not a sha256 digest")
    return value


def _safe_artifact_path(
    repo_root: Path, relative: str, expected: PurePosixPath, label: str
) -> Path:
    if type(relative) is not str:
        raise ProtocolViolation(f"{label} must be a string")
    pure = PurePosixPath(relative)
    if pure != expected or pure.is_absolute() or ".." in pure.parts:
        raise ProtocolViolation(f"{label} is not at its canonical location")
    root = repo_root.resolve()
    resolved = (root / Path(*pure.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} escapes the repository") from exc
    return resolved


def _safe_run_path(repo_root: Path, relative: str, run_id: str) -> Path:
    return _safe_artifact_path(
        repo_root,
        relative,
        PurePosixPath("results/unified_map/runs") / run_id,
        "run_path",
    )


def _verify_artifact_binding(
    binding: Any,
    *,
    repo_root: Path,
    expected_path: PurePosixPath,
    label: str,
) -> dict[str, Any]:
    _require_exact_keys(binding, {"path", "sha256", "source_commit"}, label)
    path = _safe_artifact_path(repo_root, binding["path"], expected_path, f"{label} path")
    expected_digest = _require_digest(binding["sha256"], f"{label} digest")
    commit = binding["source_commit"]
    if commit is not None and (
        type(commit) is not str or _COMMIT_RE.fullmatch(commit) is None
    ):
        raise ProtocolViolation(f"{label} source_commit is invalid")
    value = _decode_canonical(path, label)
    raw = path.read_bytes()
    if digest_bytes(raw) != expected_digest:
        raise ProtocolViolation(f"{label} digest mismatch")
    if commit is not None:
        result = subprocess.run(
            ["git", "show", f"{commit}:{expected_path.as_posix()}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0 or result.stdout != raw:
            raise ProtocolViolation(f"{label} committed bytes mismatch")
    return value


def _verify_preregistration(
    entry: dict[str, Any], *, repo_root: Path
) -> dict[str, Any] | None:
    binding = entry.get("preregistration")
    if binding is None:
        return None
    experiment_id = entry["experiment_id"]
    value = _verify_artifact_binding(
        binding,
        repo_root=repo_root,
        expected_path=PurePosixPath(
            f"research/unified_map/experiment_cards/{experiment_id}.json"
        ),
        label=f"{experiment_id} preregistration",
    )
    if (
        value.get("protocol") != "ucm-experiment-preregistration/1"
        or value.get("experiment_id") != experiment_id
        or value.get("family_code") != entry["family"]
    ):
        raise ProtocolViolation(f"{experiment_id} preregistration identity mismatch")
    return value


def _verify_decision_artifact(
    entry: dict[str, Any], *, repo_root: Path
) -> dict[str, Any] | None:
    binding = entry.get("decision_artifact")
    if binding is None:
        return None
    experiment_id = entry["experiment_id"]
    value = _verify_artifact_binding(
        binding,
        repo_root=repo_root,
        expected_path=PurePosixPath(
            f"research/unified_map/experiment_decisions/{experiment_id}.json"
        ),
        label=f"{experiment_id} decision artifact",
    )
    if value.get("experiment_id") != experiment_id:
        raise ProtocolViolation(f"{experiment_id} decision artifact identity mismatch")
    result_binding = value.get("result_binding")
    if type(result_binding) is not dict or result_binding.get("run_id") != entry["run_id"]:
        raise ProtocolViolation(f"{experiment_id} decision run mismatch")
    decision = value.get("decision")
    if type(decision) is not str or decision.lower() != entry["decision"].lower():
        raise ProtocolViolation(f"{experiment_id} decision mismatch")
    from .experiment_decision import verify_experiment_decision

    verified = verify_experiment_decision(
        repo_root / Path(*PurePosixPath(binding["path"]).parts),
        repo_root=repo_root,
    )
    if verified != value:
        raise ProtocolViolation(f"{experiment_id} decision verifier disagreement")
    return value


def _read_bundle_member(run_path: Path, row: dict[str, Any]) -> bytes:
    _require_exact_keys(row, {"name", "byte_length", "sha256"}, "manifest file")
    name = row["name"]
    length = row["byte_length"]
    expected_digest = _require_digest(row["sha256"], "manifest file digest")
    if (
        type(name) is not str
        or PurePosixPath(name).name != name
        or type(length) is not int
        or length < 0
    ):
        raise ProtocolViolation("manifest file metadata is invalid")
    member = run_path / name
    if member.is_file():
        raw = member.read_bytes()
    else:
        sidecar = run_path / f"{name}.gz"
        if not sidecar.is_file():
            raise ProtocolViolation(f"run bundle member {name} is missing")
        try:
            with gzip.open(sidecar, "rb") as handle:
                raw = handle.read(length + 1)
        except (OSError, EOFError) as exc:
            raise ProtocolViolation(f"gzip sidecar for {name} is invalid") from exc
    if len(raw) != length or digest_bytes(raw) != expected_digest:
        raise ProtocolViolation(f"run bundle member {name} drifted")
    return raw


def _verify_source_binding(
    source: Any, *, experiment_id: str, expected_digest: str
) -> list[dict[str, Any]]:
    if type(source) is not dict or set(source) - {
        "files",
        "source_digest",
        "reference_bundle_root",
        "reference_run_id",
    }:
        raise ProtocolViolation(f"{experiment_id} source binding is invalid")
    source_files = source.get("files")
    if type(source_files) is not list or not source_files:
        raise ProtocolViolation(f"{experiment_id} source file binding is empty")
    for row in source_files:
        _require_exact_keys(
            row,
            {"relative_path", "byte_length", "sha256"},
            f"{experiment_id} source file",
        )
        if (
            type(row["relative_path"]) is not str
            or type(row["byte_length"]) is not int
            or row["byte_length"] < 0
        ):
            raise ProtocolViolation(f"{experiment_id} source file metadata is invalid")
        _require_digest(row["sha256"], f"{experiment_id} source file digest")
    source_candidates = {digest_json(source_files)}
    if len(source_files) == 1:
        source_candidates.add(source_files[0]["sha256"])
    declared_source = source.get("source_digest")
    if declared_source not in source_candidates or expected_digest != declared_source:
        raise ProtocolViolation(f"{experiment_id} source digest mismatch")
    return source_files


def _verify_config_against_preregistration(
    config: dict[str, Any], preregistration: dict[str, Any], experiment_id: str
) -> None:
    planned = preregistration.get("planned_screen_config")
    if planned is None:
        planned = preregistration.get("screen_config")
    if type(planned) is not dict:
        raise ProtocolViolation(f"{experiment_id} preregistered config is missing")
    expected = {
        "experiment_id": experiment_id,
        "family_code": preregistration["family_code"],
        "parameters": {},
        "world_slots": planned.get("world_slots"),
        "replicate_ids": planned.get("replicate_ids"),
        "train_episodes_per_panel": planned.get("train_episodes_per_panel"),
        "validation_episodes_per_panel": planned.get(
            "validation_episodes_per_panel"
        ),
        "test_episodes_per_panel": planned.get(
            "sealed_test_episodes_per_panel"
        ),
        "pair_probe_limit_per_declaration": planned.get(
            "pair_probe_limit_per_declaration"
        ),
        "complete_benchmark": False,
    }
    if config != expected:
        raise ProtocolViolation(f"{experiment_id} config differs from preregistration")


def _verify_bound_run(
    entry: dict[str, Any], *, repo_root: Path, freeze_root: str
) -> None:
    experiment_id = entry["experiment_id"]
    run_id = entry["run_id"]
    if type(run_id) is not str:
        raise ProtocolViolation("bound run_id must be a string")
    match = _RUN_RE.fullmatch(run_id)
    if match is None or match.group(1) != experiment_id:
        raise ProtocolViolation("run_id does not bind its experiment_id")
    run_path = _safe_run_path(repo_root, entry["run_path"], run_id)
    manifest_path = run_path / "manifest.json"
    summary_path = run_path / "summary.json"
    manifest = _decode_canonical(manifest_path, f"{experiment_id} manifest")
    summary = _decode_canonical(summary_path, f"{experiment_id} summary")

    _require_exact_keys(
        entry["digests"],
        {"bundle", "config", "manifest", "source", "summary"},
        f"{experiment_id} digests",
    )
    digests = entry["digests"]
    for key, value in digests.items():
        _require_digest(value, f"{experiment_id} {key} digest")

    if manifest.get("protocol") != RUN_MANIFEST_PROTOCOL:
        raise ProtocolViolation(f"{experiment_id} run manifest protocol mismatch")
    if manifest.get("run_id") != run_id or summary.get("run_id") != run_id:
        raise ProtocolViolation(f"{experiment_id} run id mismatch")
    if manifest.get("freeze_root") != freeze_root or summary.get("freeze_root") != freeze_root:
        raise ProtocolViolation(f"{experiment_id} freeze root mismatch")
    expected_bundle = digest_json(
        {key: value for key, value in manifest.items() if key != "bundle_root"}
    )
    if manifest.get("bundle_root") != expected_bundle or digests["bundle"] != expected_bundle:
        raise ProtocolViolation(f"{experiment_id} bundle root mismatch")
    if digest_bytes(manifest_path.read_bytes()) != digests["manifest"]:
        raise ProtocolViolation(f"{experiment_id} manifest digest mismatch")

    files = manifest.get("files")
    if type(files) is not list or not files:
        raise ProtocolViolation(f"{experiment_id} manifest files are invalid")
    names: set[str] = set()
    summary_digest = None
    for row in files:
        if type(row) is not dict:
            raise ProtocolViolation(f"{experiment_id} manifest file is invalid")
        _read_bundle_member(run_path, row)
        if row["name"] in names:
            raise ProtocolViolation(f"{experiment_id} manifest has duplicate files")
        names.add(row["name"])
        if row["name"] == "summary.json":
            summary_digest = row["sha256"]
    if summary_digest is None or summary_digest != digests["summary"]:
        raise ProtocolViolation(f"{experiment_id} summary digest is not manifest-bound")

    config = summary.get("config")
    if type(config) is not dict:
        raise ProtocolViolation(f"{experiment_id} summary config is invalid")
    if config.get("experiment_id") != experiment_id or config.get("family_code") != entry["family"]:
        raise ProtocolViolation(f"{experiment_id} summary identity mismatch")
    if digest_json(config) != digests["config"]:
        raise ProtocolViolation(f"{experiment_id} config digest mismatch")

    source_files = _verify_source_binding(
        summary.get("source_binding"),
        experiment_id=experiment_id,
        expected_digest=digests["source"],
    )
    preregistration = _verify_preregistration(entry, repo_root=repo_root)
    decision = _verify_decision_artifact(entry, repo_root=repo_root)
    if entry["ordinal"] >= 37 and (preregistration is None or decision is None):
        raise ProtocolViolation(
            f"{experiment_id} requires preregistration and decision bindings"
        )
    if preregistration is not None:
        _verify_config_against_preregistration(config, preregistration, experiment_id)
        bound_source = preregistration.get("source_binding")
        if type(bound_source) is not dict or bound_source not in source_files:
            raise ProtocolViolation(
                f"{experiment_id} run source differs from preregistration"
            )
    if decision is not None:
        result_binding = decision.get("result_binding")
        declared_bundle = (
            result_binding.get("bundle_root")
            if type(result_binding) is dict
            else None
        )
        if declared_bundle != digests["bundle"]:
            raise ProtocolViolation(f"{experiment_id} decision bundle mismatch")


def _verify_failed_attempt(
    entry: dict[str, Any], *, repo_root: Path, freeze_root: str
) -> None:
    experiment_id = entry["experiment_id"]
    run_id = entry["run_id"]
    if type(run_id) is not str:
        raise ProtocolViolation("failed run_id must be a string")
    match = _FAILED_RUN_RE.fullmatch(run_id)
    if match is None or match.group(1) != experiment_id:
        raise ProtocolViolation("failed run_id does not bind its experiment_id")
    run_path = _safe_artifact_path(
        repo_root,
        entry["run_path"],
        PurePosixPath("results/unified_map/failed_runs") / run_id,
        "failed run_path",
    )
    manifest_path = run_path / "manifest.json"
    failure_path = run_path / "failure.json"
    manifest = _decode_canonical(manifest_path, f"{experiment_id} failed manifest")
    failure = _decode_canonical(failure_path, f"{experiment_id} failure")
    _require_exact_keys(
        entry["digests"],
        {"bundle", "config", "failure", "manifest", "source"},
        f"{experiment_id} failed digests",
    )
    digests = entry["digests"]
    for key, value in digests.items():
        _require_digest(value, f"{experiment_id} {key} digest")
    if manifest.get("protocol") != FAILED_MANIFEST_PROTOCOL:
        raise ProtocolViolation(f"{experiment_id} failed manifest protocol mismatch")
    if (
        manifest.get("run_id") != run_id
        or failure.get("run_id") != run_id
        or manifest.get("experiment_id") != experiment_id
        or failure.get("experiment_id") != experiment_id
    ):
        raise ProtocolViolation(f"{experiment_id} failed run identity mismatch")
    if failure.get("freeze_root") != freeze_root:
        raise ProtocolViolation(f"{experiment_id} failed freeze root mismatch")
    expected_bundle = digest_json(
        {key: value for key, value in manifest.items() if key != "bundle_root"}
    )
    if manifest.get("bundle_root") != expected_bundle or digests["bundle"] != expected_bundle:
        raise ProtocolViolation(f"{experiment_id} failed bundle root mismatch")
    if digest_bytes(manifest_path.read_bytes()) != digests["manifest"]:
        raise ProtocolViolation(f"{experiment_id} failed manifest digest mismatch")
    files = manifest.get("files")
    if type(files) is not list or len(files) != 1:
        raise ProtocolViolation(f"{experiment_id} failed manifest files are invalid")
    raw = _read_bundle_member(run_path, files[0])
    if files[0]["name"] != "failure.json" or digest_bytes(raw) != digests["failure"]:
        raise ProtocolViolation(f"{experiment_id} failure digest mismatch")
    config = failure.get("config")
    if (
        type(config) is not dict
        or config.get("experiment_id") != experiment_id
        or config.get("family_code") != entry["family"]
        or digest_json(config) != digests["config"]
    ):
        raise ProtocolViolation(f"{experiment_id} failed config mismatch")
    _verify_source_binding(
        failure.get("source_binding"),
        experiment_id=experiment_id,
        expected_digest=digests["source"],
    )
    preregistration = _verify_preregistration(entry, repo_root=repo_root)
    if preregistration is None:
        raise ProtocolViolation(f"{experiment_id} failed attempt lacks preregistration")
    _verify_config_against_preregistration(config, preregistration, experiment_id)
    if str(manifest.get("decision", "")).lower() != entry["decision"].lower():
        raise ProtocolViolation(f"{experiment_id} failed decision mismatch")


def _derived_accounting(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    class_counts = Counter(row["substantive_change_class"] for row in experiments)
    role_counts = Counter(row["role"] for row in experiments)
    return {
        "count_eligible": sum(row["count_eligible"] for row in experiments),
        "count_ineligible": sum(not row["count_eligible"] for row in experiments),
        "evidence_gap_count": sum(row["evidence_status"] == "evidence_gap" for row in experiments),
        "failed_attempt_count": sum(
            row["evidence_status"] == "failed_attempt_bundle"
            for row in experiments
        ),
        "last_experiment_id": experiments[-1]["experiment_id"],
        "role_counts": dict(sorted(role_counts.items())),
        "substantive_change_class_counts": dict(sorted(class_counts.items())),
        "total_experiments": len(experiments),
    }


def verify_experiment_index(
    path: Path | str = INDEX_FILENAME, *, repo_root: Path | str | None = None
) -> dict[str, Any]:
    """Verify canonical bytes, accounting and every bound run bundle."""

    index_path = Path(path)
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    value = _decode_canonical(index_path, "experiment index")
    _require_exact_keys(
        value,
        {"accounting", "experiments", "freeze_root", "index_root", "protocol"},
        "experiment index",
    )
    if value["protocol"] != INDEX_PROTOCOL:
        raise ProtocolViolation("experiment index protocol mismatch")
    freeze_root = _require_digest(value["freeze_root"], "experiment index freeze_root")
    expected_root = digest_json(
        {key: item for key, item in value.items() if key != "index_root"}
    )
    if value["index_root"] != expected_root:
        raise ProtocolViolation("experiment index root mismatch")
    experiments = value["experiments"]
    if type(experiments) is not list or not experiments:
        raise ProtocolViolation("experiment index must contain experiments")

    seen_runs: set[str] = set()
    seen_paths: set[str] = set()
    seen_bundles: set[str] = set()
    for expected_ordinal, entry in enumerate(experiments, 1):
        required_entry_keys = {
            "count_eligible",
            "decision",
            "digests",
            "evidence_gaps",
            "evidence_status",
            "experiment_id",
            "family",
            "ordinal",
            "role",
            "run_id",
            "run_path",
            "substantive_change_class",
        }
        if type(entry) is not dict or not required_entry_keys <= set(entry):
            raise ProtocolViolation(f"experiment entry {expected_ordinal} keys mismatch")
        if set(entry) - required_entry_keys - {"decision_artifact", "preregistration"}:
            raise ProtocolViolation(f"experiment entry {expected_ordinal} keys mismatch")
        expected_id = f"EXP-{expected_ordinal:03d}"
        match = _EXPERIMENT_RE.fullmatch(entry["experiment_id"])
        if match is None or entry["experiment_id"] != expected_id or entry["ordinal"] != expected_ordinal:
            raise ProtocolViolation("experiment ids/ordinals must be contiguous and canonical")
        for key in ("family", "role", "decision", "substantive_change_class"):
            if type(entry[key]) is not str or not entry[key] or entry[key].strip() != entry[key]:
                raise ProtocolViolation(f"{expected_id} {key} is invalid")
        if type(entry["count_eligible"]) is not bool:
            raise ProtocolViolation(f"{expected_id} count_eligible is not boolean")
        change_class = entry["substantive_change_class"]
        if change_class not in _COUNTABLE_CLASSES | _NONCOUNTABLE_CLASSES:
            raise ProtocolViolation(f"{expected_id} substantive change class is unknown")
        if type(entry["evidence_gaps"]) is not list or any(
            type(item) is not str or not item for item in entry["evidence_gaps"]
        ):
            raise ProtocolViolation(f"{expected_id} evidence_gaps is invalid")

        status = entry["evidence_status"]
        if status == "bound_run_bundle":
            if entry["count_eligible"] != (change_class in _COUNTABLE_CLASSES):
                raise ProtocolViolation(
                    f"{expected_id} count eligibility contradicts change class"
                )
            if entry["evidence_gaps"]:
                raise ProtocolViolation(f"{expected_id} bound run cannot declare an evidence gap")
            _verify_bound_run(entry, repo_root=root, freeze_root=freeze_root)
            for value_, seen, label in (
                (entry["run_id"], seen_runs, "run_id"),
                (entry["run_path"], seen_paths, "run_path"),
                (entry["digests"]["bundle"], seen_bundles, "bundle"),
            ):
                if value_ in seen:
                    raise ProtocolViolation(f"duplicate {label} in experiment index")
                seen.add(value_)
        elif status == "failed_attempt_bundle":
            if entry["count_eligible"]:
                raise ProtocolViolation(f"{expected_id} failed attempt cannot count")
            if not entry["evidence_gaps"]:
                raise ProtocolViolation(
                    f"{expected_id} failed attempt must disclose missing completion evidence"
                )
            if entry.get("decision_artifact") is not None:
                raise ProtocolViolation(
                    f"{expected_id} failed attempt decision must remain in failure bundle"
                )
            _verify_failed_attempt(entry, repo_root=root, freeze_root=freeze_root)
            for value_, seen, label in (
                (entry["run_id"], seen_runs, "run_id"),
                (entry["run_path"], seen_paths, "run_path"),
                (entry["digests"]["bundle"], seen_bundles, "bundle"),
            ):
                if value_ in seen:
                    raise ProtocolViolation(f"duplicate {label} in experiment index")
                seen.add(value_)
        elif status == "evidence_gap":
            if entry["count_eligible"]:
                raise ProtocolViolation(f"{expected_id} evidence gap cannot count")
            if not entry["evidence_gaps"]:
                raise ProtocolViolation(f"{expected_id} evidence gap needs a reason")
            if entry["run_id"] is not None or entry["run_path"] is not None:
                raise ProtocolViolation(f"{expected_id} evidence gap invents a run")
            if entry["digests"] is not None:
                raise ProtocolViolation(f"{expected_id} evidence gap invents digests")
        else:
            raise ProtocolViolation(f"{expected_id} evidence_status is invalid")

    derived = _derived_accounting(experiments)
    if value["accounting"] != derived:
        raise ProtocolViolation("experiment index accounting mismatch")
    return value


def _main() -> int:
    parser = argparse.ArgumentParser(description="Verify the canonical UCM experiment index")
    parser.add_argument("--index", type=Path, default=INDEX_FILENAME)
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args()
    value = verify_experiment_index(args.index, repo_root=args.repo_root)
    print(
        json.dumps(
            {
                "index_root": value["index_root"],
                **value["accounting"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["INDEX_FILENAME", "INDEX_PROTOCOL", "verify_experiment_index"]
