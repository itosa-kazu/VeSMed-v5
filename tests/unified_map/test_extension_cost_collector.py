from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import prototype.unified_map.extension_cost_collector as collector
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from prototype.unified_map.extension_cost_collector import (
    BENCHMARK_EVIDENCE_SCHEMA,
    MIGRATION_RECEIPT_SCHEMA,
    MIGRATION_RECEIPT_PATH,
    OLD_BENCHMARK_TARGET_SCOPE_DIGEST,
    RETRAIN_MANIFEST_SCHEMA,
    RETRAIN_EXAMPLE_SCHEMA,
    ROOT_MANIFEST_PATH,
    ROOT_MANIFEST_SCHEMA,
    SEAL_MANIFEST_SCHEMA,
    SOURCE_MANIFEST_SCHEMA,
    TREE_MANIFEST_SCHEMA,
    CollectionStatus,
    collect_extension_cost,
)
from prototype.unified_map.metrics_m09_m11 import CoreDiffFile


D0 = "sha256:" + "0" * 64
D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
D3 = "sha256:" + "3" * 64
D4 = "sha256:" + "4" * 64


def _write(root: Path, path: str, content: bytes) -> None:
    target = root / Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def _write_json(root: Path, path: str, value: dict) -> None:
    _write(root, path, canonical_json_bytes(value))


def _tree_rows(root: Path, prefix: str) -> list[dict]:
    base = root / Path(prefix)
    rows = []
    for path in sorted(
        (item for item in base.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(base).as_posix().encode(),
    ):
        content = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(base).as_posix(),
                "size_bytes": len(content),
                "digest": digest_bytes(content),
            }
        )
    return rows


def _artifact_manifest(root: Path, stage: str) -> str:
    root_path = f"{stage}/artifacts"
    rows = _tree_rows(root, root_path)
    tree_digest = collector._tree_digest(stage, root_path, rows)
    _write_json(
        root,
        f"{stage}/artifact-tree.json",
        {
            "schema_version": TREE_MANIFEST_SCHEMA,
            "stage": stage,
            "root_path": root_path,
            "files": rows,
            "tree_digest": tree_digest,
        },
    )
    return tree_digest


def _source_manifest(
    root: Path,
    stage: str,
    *,
    git_commit: str,
    base_git_commit: str | None,
) -> str:
    root_path = f"{stage}/source"
    rows = _tree_rows(root, root_path)
    rows = [{"git_mode": "100644", **row} for row in rows]
    tree_digest = collector._tree_digest(stage, root_path, rows)
    _write_json(
        root,
        f"{stage}/source-manifest.json",
        {
            "schema_version": SOURCE_MANIFEST_SCHEMA,
            "stage": stage,
            "root_path": root_path,
            "git_commit": git_commit,
            "git_dirty": False,
            "base_git_commit": base_git_commit,
            "files": rows,
            "tree_digest": tree_digest,
        },
    )
    return tree_digest


def _legacy_receipts(root: Path) -> None:
    primary = {
        "schema_version": "ucm-extension-primary-seal-result/1",
        "status": "incomplete",
        "structural_status": "complete",
        "freeze_grade_evidence": False,
        "world_slot": "W16",
        "record_set_digest": D0,
        "binding_set_digest": D1,
        "bindings": [{"fixture": "exact-primary-state-binding"}],
        "blockers": [{"code": "UCM-E003-HARNESS_INCOMPLETE"}],
    }
    reveal = {
        "schema_version": "ucm-extension-reveal-receipt/1",
        "world_slot": "W16",
        "primary_record_set_digest": D0,
        "primary_binding_set_digest": D1,
        "extension_scope_digest": D2,
        "extension_pack_digest": D3,
        "candidate_reveal_file": "extension-reveal.json",
        "candidate_reveal_digest": D4,
        "evidence_scope": "runtime-ordering-only",
        "source_hiding_verified": False,
        "freeze_grade_evidence": False,
    }
    materialization = {
        "schema_version": "ucm-extension-materialization-result/1",
        "status": "incomplete",
        "freeze_grade_evidence": False,
        "benchmark_freeze_eligible": False,
        "corpus_status": "complete",
        "world_slot": "W16",
        "split": "sealed_test",
        "population_count": 512,
        "probe_record_count": 512,
        "primary_record_set_digest": D0,
        "primary_binding_set_digest": D1,
        "extension_scope_digest": D2,
        "extension_pack_digest": D3,
        "candidate_file": "extension-public.jsonl",
        "candidate_manifest_file": "extension-manifest.json",
        "judge_file": "extension-private.jsonl",
        "candidate_digest": D0,
        "candidate_manifest_digest": D1,
        "judge_digest": D2,
        "evidence_scope": "ordering-and-corpus-only",
        "ordering_complete": True,
        "extension_evaluation_complete": False,
        "query_contract_verified": False,
        "execution_assurance": "portable-callback",
        "blockers": [{"code": "UCM-E003-HARNESS_INCOMPLETE"}],
    }
    _write_json(root, "receipts/primary-seal.json", primary)
    _write_json(root, "receipts/reveal.json", reveal)
    _write_json(root, "receipts/materialization.json", materialization)


def _retrain_manifest(root: Path) -> str:
    rows = []
    for case_id, example_id, path in (
        ("case-001", "example-001", "001.json"),
        ("case-002", "example-002", "002.json"),
    ):
        content = (root / "retrain" / "examples" / path).read_bytes()
        rows.append(
            {
                "case_id": case_id,
                "example_id": example_id,
                "path": path,
                "size_bytes": len(content),
                "digest": digest_bytes(content),
            }
        )
    unsigned = {
        "protocol": RETRAIN_MANIFEST_SCHEMA,
        "root_path": "retrain/examples",
        "examples": rows,
    }
    set_digest = digest_json(unsigned)
    _write_json(
        root,
        "retrain/manifest.json",
        {
            "schema_version": RETRAIN_MANIFEST_SCHEMA,
            "root_path": "retrain/examples",
            "examples": rows,
            "example_set_digest": set_digest,
        },
    )
    return set_digest


def _old_benchmark(
    root: Path,
    stage: str,
    *,
    source_digest: str,
    artifact_digest: str,
    scores: tuple[int, int],
) -> None:
    _write_json(
        root,
        f"old-benchmark/{stage}.json",
        {
            "schema_version": BENCHMARK_EVIDENCE_SCHEMA,
            "stage": stage,
            "benchmark_scope_digest": OLD_BENCHMARK_TARGET_SCOPE_DIGEST,
            "metric_id": collector.OLD_BENCHMARK_METRIC_ID,
            "candidate_source_tree_digest": source_digest,
            "candidate_artifact_tree_digest": artifact_digest,
            "rows": [
                {"example_id": "old-001", "score": scores[0]},
                {"example_id": "old-002", "score": scores[1]},
            ],
        },
    )


def _root_manifest(root: Path) -> str:
    rows = []
    for path in sorted(
        (
            item
            for item in root.rglob("*")
            if item.is_file() and item.name != ROOT_MANIFEST_PATH
        ),
        key=lambda item: item.relative_to(root).as_posix().encode(),
    ):
        content = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": len(content),
                "digest": digest_bytes(content),
            }
        )
    unsigned = {
        "schema_version": ROOT_MANIFEST_SCHEMA,
        "absolute_root": root.resolve().as_posix(),
        "files": rows,
    }
    manifest = {**unsigned, "manifest_digest": digest_json(unsigned)}
    manifest_bytes = canonical_json_bytes(manifest)
    _write(root, ROOT_MANIFEST_PATH, manifest_bytes)
    return collector._root_commitment(manifest_bytes)


def _complete_fixture(
    root: Path,
    *,
    disposition: str = "completed",
    before_git_commit: str = "1" * 40,
    after_git_commit: str = "2" * 40,
) -> str:
    _legacy_receipts(root)
    _write(root, "before/artifacts/model.bin", b"abc")
    _write(root, "before/artifacts/aux.bin", b"12")
    _write(root, "after/artifacts/model.bin", b"abcdef")
    _write(root, "after/artifacts/aux.bin", b"12")
    _write(root, "after/artifacts/new.bin", b"x")
    _write(root, "before/artifacts/model-schema.json", canonical_json_bytes({"v": 1}))
    _write(root, "before/artifacts/state-schema.json", canonical_json_bytes({"v": 1}))
    _write(root, "before/artifacts/state-snapshot.bin", b"state-before")
    _write(root, "after/artifacts/model-schema.json", canonical_json_bytes({"v": 1}))
    _write(root, "after/artifacts/state-schema.json", canonical_json_bytes({"v": 2}))
    _write(root, "after/artifacts/state-snapshot.bin", b"state-after")

    _write(root, "before/source/core.py", b"a=1\nb=2\n")
    _write(root, "before/source/helper.py", b"same\n")
    _write(root, "after/source/core.py", b"a=1\nb=3\nc=4\n")
    _write(root, "after/source/helper.py", b"same\n")
    _write(root, "after/source/new.py", b"z\n")
    _write_json(
        root,
        "retrain/examples/001.json",
        {
            "schema_version": RETRAIN_EXAMPLE_SCHEMA,
            "case_id": "case-001",
            "example_id": "example-001",
            "payload": {"x": 1},
        },
    )
    _write_json(
        root,
        "retrain/examples/002.json",
        {
            "schema_version": RETRAIN_EXAMPLE_SCHEMA,
            "case_id": "case-002",
            "example_id": "example-002",
            "payload": {"x": 2},
        },
    )

    before_artifacts = _artifact_manifest(root, "before")
    after_artifacts = _artifact_manifest(root, "after")
    before_source = _source_manifest(
        root,
        "before",
        git_commit=before_git_commit,
        base_git_commit=None,
    )
    after_source = _source_manifest(
        root,
        "after",
        git_commit=after_git_commit,
        base_git_commit=before_git_commit,
    )
    _write_json(
        root,
        "before/seal.json",
        {
            "schema_version": SEAL_MANIFEST_SCHEMA,
            "stage": "before",
            "artifact_tree_digest": before_artifacts,
            "source_tree_digest": before_source,
            "model_artifact_path": "model.bin",
            "model_artifact_digest": digest_bytes(b"abc"),
            "model_schema_path": "model-schema.json",
            "model_schema_digest": digest_bytes(canonical_json_bytes({"v": 1})),
            "state_schema_path": "state-schema.json",
            "state_schema_digest": digest_bytes(canonical_json_bytes({"v": 1})),
            "state_snapshot_path": "state-snapshot.bin",
            "state_snapshot_digest": digest_bytes(b"state-before"),
        },
    )
    _write_json(
        root,
        "after/seal.json",
        {
            "schema_version": SEAL_MANIFEST_SCHEMA,
            "stage": "after",
            "artifact_tree_digest": after_artifacts,
            "source_tree_digest": after_source,
            "model_artifact_path": "model.bin",
            "model_artifact_digest": digest_bytes(b"abcdef"),
            "model_schema_path": "model-schema.json",
            "model_schema_digest": digest_bytes(canonical_json_bytes({"v": 1})),
            "state_schema_path": "state-schema.json",
            "state_schema_digest": digest_bytes(canonical_json_bytes({"v": 2})),
            "state_snapshot_path": "state-snapshot.bin",
            "state_snapshot_digest": digest_bytes(b"state-after"),
        },
    )
    retrain_digest = _retrain_manifest(root)
    _old_benchmark(
        root,
        "before",
        source_digest=before_source,
        artifact_digest=before_artifacts,
        scores=(1, 3),
    )
    _old_benchmark(
        root,
        "after",
        source_digest=after_source,
        artifact_digest=after_artifacts,
        scores=(2, 4),
    )
    _write_json(
        root,
        "receipts/migration-outcome.json",
        {
            "schema_version": MIGRATION_RECEIPT_SCHEMA,
            "extension_id": "w16-new-check-001",
            "extension_kind": "new_check",
            "world_slot": "W16",
            "primary_seal_digest": digest_bytes(
                (root / "receipts/primary-seal.json").read_bytes()
            ),
            "reveal_receipt_digest": digest_bytes(
                (root / "receipts/reveal.json").read_bytes()
            ),
            "materialization_receipt_digest": digest_bytes(
                (root / "receipts/materialization.json").read_bytes()
            ),
            "before_seal_digest": digest_bytes(
                (root / "before/seal.json").read_bytes()
            ),
            "after_seal_digest": digest_bytes((root / "after/seal.json").read_bytes()),
            "retrain_example_set_digest": retrain_digest,
            "execution_assurance": "fresh-process-exact-byte-custody-v1",
            "source_hiding_verified": True,
            "query_contract_verified": True,
            "atomic_publish_verified": True,
            "completion_disposition": disposition,
        },
    )
    return _root_manifest(root)


def _reissue_root(root: Path) -> str:
    (root / ROOT_MANIFEST_PATH).unlink()
    return _root_manifest(root)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def test_structured_fixture_derives_bytes_but_remains_typed_incomplete_without_authority(
    tmp_path: Path,
) -> None:
    expected = _complete_fixture(tmp_path)

    collected = collect_extension_cost(tmp_path, expected_root_commitment=expected)

    assert collected.status is CollectionStatus.INCOMPLETE
    assert collected.to_wire()["benchmark_status"] == "PRE-FREEZE"
    assert collected.to_wire()["benchmark_freeze_eligible"] is False
    assert collected.artifact_digest == digest_bytes(collected.canonical_bytes)
    assert collected.observation is None
    roles = {item.evidence_role for item in collected.blockers}
    assert roles >= {
        "live_git_repository",
        "migration_execution_verifier",
        "old_benchmark_evaluator_receipt",
    }

    _, files, _ = collector._verify_root(tmp_path, expected)
    before_artifacts = collector._parse_tree(files, stage="before", kind="artifact")
    after_artifacts = collector._parse_tree(files, stage="after", kind="artifact")
    before_source, _ = collector._parse_source_tree(files, stage="before")
    after_source, _ = collector._parse_source_tree(files, stage="after")
    before_seal = collector._parse_seal(
        files,
        stage="before",
        artifact_tree=before_artifacts,
        source_tree=before_source,
    )
    after_seal = collector._parse_seal(
        files,
        stage="after",
        artifact_tree=after_artifacts,
        source_tree=after_source,
    )
    migration_flags = {
        "model_migration_required": (
            before_seal["model_artifact_digest"] != after_seal["model_artifact_digest"]
        ),
        "state_migration_required": (
            before_seal["state_snapshot_digest"] != after_seal["state_snapshot_digest"]
            or before_seal["state_schema_digest"] != after_seal["state_schema_digest"]
        ),
        "schema_migration_required": (
            before_seal["model_schema_digest"] != after_seal["model_schema_digest"]
            or before_seal["state_schema_digest"] != after_seal["state_schema_digest"]
        ),
    }
    assert migration_flags == {
        "model_migration_required": True,
        "state_migration_required": True,
        "schema_migration_required": True,
    }
    retrain_count, _ = collector._parse_retrain(files)
    assert retrain_count == 2
    assert after_artifacts.size_bytes > before_artifacts.size_bytes
    assert collector._source_diff(before_source, after_source) == [
        {"path": "core.py", "added_lines": 2, "deleted_lines": 1},
        {"path": "new.py", "added_lines": 1, "deleted_lines": 0},
    ]
    _, before_ids, before_score = collector._parse_old_benchmark(
        files,
        stage="before",
        source_tree=before_source,
        artifact_tree=before_artifacts,
    )
    _, after_ids, after_score = collector._parse_old_benchmark(
        files,
        stage="after",
        source_tree=after_source,
        artifact_tree=after_artifacts,
    )
    assert before_ids == after_ids == ("old-001", "old-002")
    assert (before_score, after_score) == (2.0, 3.0)


def test_unverified_full_core_rewrite_claim_cannot_mint_hard_failure(
    tmp_path: Path,
) -> None:
    expected = _complete_fixture(tmp_path, disposition="requires_full_core_rewrite")
    result = collect_extension_cost(tmp_path, expected_root_commitment=expected)
    assert result.status is CollectionStatus.INCOMPLETE
    assert result.observation is None
    assert "migration_execution_verifier" in {
        blocker.evidence_role for blocker in result.blockers
    }


def test_public_collection_dto_cannot_mint_complete() -> None:
    evidence = collector.CanonicalMetricEvidence.from_payload(
        "m11-live/caller-forgery.json",
        {
            "schema_version": collector.M11_OBSERVATION_SCHEMA,
            "extension_id": "caller-forgery",
            "extension_kind": "new_check",
            "model_migration_required": False,
            "state_migration_required": False,
            "schema_migration_required": False,
            "retrain_examples": 0,
            "base_artifact_size_bytes": 1,
            "extended_artifact_size_bytes": 1,
            "core_diff_files": [],
            "old_benchmark_before_score": 0,
            "old_benchmark_after_score": 0,
            "old_benchmark_score_direction": "minimize",
            "old_benchmark_denominator": 1,
            "completion_disposition": "completed",
        },
    )
    observation = collector.ExtensionCostObservation(evidence)
    with pytest.raises(ProtocolViolation, match="COMPLETE issuer is disabled"):
        collector.ExtensionCostCollection(
            CollectionStatus.COMPLETE,
            "C:/caller-forgery",
            D0,
            observation,
            (),
            (),
        )

    incomplete = collector.ExtensionCostCollection(
        CollectionStatus.INCOMPLETE,
        "C:/caller-forgery",
        D0,
        None,
        (collector.CollectionBlocker("B", "role", "detail"),),
        (),
    )
    object.__setattr__(incomplete, "status", CollectionStatus.COMPLETE)
    object.__setattr__(incomplete, "observation", observation)
    object.__setattr__(incomplete, "blockers", ())
    with pytest.raises(ProtocolViolation, match="COMPLETE issuer is disabled"):
        incomplete.to_wire()


def test_live_git_verifies_exact_clean_trees_and_ancestry_but_does_not_mint_authority(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "m11@example.invalid")
    _git(repository, "config", "user.name", "M11 Test")
    _write(repository, "core.py", b"a=1\nb=2\n")
    _write(repository, "helper.py", b"same\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "before")
    before_commit = _git(repository, "rev-parse", "HEAD")
    _write(repository, "core.py", b"a=1\nb=3\nc=4\n")
    _write(repository, "new.py", b"z\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "after")
    after_commit = _git(repository, "rev-parse", "HEAD")

    evidence = tmp_path / "evidence"
    expected = _complete_fixture(
        evidence,
        before_git_commit=before_commit,
        after_git_commit=after_commit,
    )
    result = collect_extension_cost(
        evidence,
        expected_root_commitment=expected,
        live_git_repository=repository,
    )
    assert result.status is CollectionStatus.INCOMPLETE
    roles = {blocker.evidence_role for blocker in result.blockers}
    assert "live_git_repository" not in roles
    assert roles >= {
        "migration_execution_verifier",
        "old_benchmark_evaluator_receipt",
    }


def test_live_git_disables_replace_object_splices(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "m11@example.invalid")
    _git(repository, "config", "user.name", "M11 Test")
    original_branch = _git(repository, "branch", "--show-current")
    _write(repository, "core.py", b"a=1\nb=2\n")
    _write(repository, "helper.py", b"same\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "before")
    before_commit = _git(repository, "rev-parse", "HEAD")

    _write(repository, "core.py", b"ORIGINAL AFTER\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "real after")
    real_after_commit = _git(repository, "rev-parse", "HEAD")

    _git(repository, "checkout", "-b", "replacement-fixture", before_commit)
    _write(repository, "core.py", b"a=1\nb=3\nc=4\n")
    _write(repository, "new.py", b"z\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "replacement after")
    replacement_commit = _git(repository, "rev-parse", "HEAD")
    _git(repository, "checkout", original_branch)
    _git(repository, "replace", real_after_commit, replacement_commit)
    _git(repository, "reset", "--hard", real_after_commit)

    assert _git(repository, "rev-parse", "HEAD") == real_after_commit
    assert _git(repository, "show", f"{real_after_commit}:core.py") == ("a=1\nb=3\nc=4")
    assert (
        _git(
            repository,
            "--no-replace-objects",
            "show",
            f"{real_after_commit}:core.py",
        )
        == "ORIGINAL AFTER"
    )

    evidence = tmp_path / "evidence"
    expected = _complete_fixture(
        evidence,
        before_git_commit=before_commit,
        after_git_commit=real_after_commit,
    )
    with pytest.raises(ProtocolViolation, match="live Git repository is not clean"):
        collect_extension_cost(
            evidence,
            expected_root_commitment=expected,
            live_git_repository=repository,
        )


def test_code_owned_old_benchmark_target_rejects_caller_direction_and_scope(
    tmp_path: Path,
) -> None:
    _complete_fixture(tmp_path)
    for stage in ("before", "after"):
        path = tmp_path / "old-benchmark" / f"{stage}.json"
        value = json.loads(path.read_bytes())
        value["score_direction"] = "maximize"
        path.write_bytes(canonical_json_bytes(value))
    expected = _reissue_root(tmp_path)
    with pytest.raises(ProtocolViolation, match="schema mismatch"):
        collect_extension_cost(tmp_path, expected_root_commitment=expected)

    other = tmp_path.parent / "wrong-scope"
    _complete_fixture(other)
    path = other / "old-benchmark" / "after.json"
    value = json.loads(path.read_bytes())
    value["benchmark_scope_digest"] = D4
    path.write_bytes(canonical_json_bytes(value))
    expected = _reissue_root(other)
    with pytest.raises(ProtocolViolation, match="target binding"):
        collect_extension_cost(other, expected_root_commitment=expected)


def test_seal_schema_and_state_digests_must_bind_retained_blobs(tmp_path: Path) -> None:
    _complete_fixture(tmp_path)
    seal_path = tmp_path / "after" / "seal.json"
    seal = json.loads(seal_path.read_bytes())
    seal["state_schema_digest"] = D4
    seal_path.write_bytes(canonical_json_bytes(seal))
    migration_path = tmp_path / MIGRATION_RECEIPT_PATH
    migration = json.loads(migration_path.read_bytes())
    migration["after_seal_digest"] = digest_bytes(seal_path.read_bytes())
    migration_path.write_bytes(canonical_json_bytes(migration))
    expected = _reissue_root(tmp_path)
    with pytest.raises(ProtocolViolation, match="does not bind live bytes"):
        collect_extension_cost(tmp_path, expected_root_commitment=expected)


def test_retrain_cost_rejects_duplicate_case_example_identity(tmp_path: Path) -> None:
    _complete_fixture(tmp_path)
    source = tmp_path / "retrain" / "examples" / "001.json"
    duplicate = tmp_path / "retrain" / "examples" / "003.json"
    duplicate.write_bytes(source.read_bytes())
    manifest_path = tmp_path / "retrain" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    duplicate_row = dict(manifest["examples"][0])
    duplicate_row["path"] = "003.json"
    duplicate_row["size_bytes"] = len(duplicate.read_bytes())
    duplicate_row["digest"] = digest_bytes(duplicate.read_bytes())
    manifest["examples"].insert(1, duplicate_row)
    unsigned = {
        "protocol": RETRAIN_MANIFEST_SCHEMA,
        "root_path": "retrain/examples",
        "examples": manifest["examples"],
    }
    manifest["example_set_digest"] = digest_json(unsigned)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    migration_path = tmp_path / MIGRATION_RECEIPT_PATH
    migration = json.loads(migration_path.read_bytes())
    migration["retrain_example_set_digest"] = manifest["example_set_digest"]
    migration_path.write_bytes(canonical_json_bytes(migration))
    expected = _reissue_root(tmp_path)
    with pytest.raises(ProtocolViolation, match="identities must be unique"):
        collect_extension_cost(tmp_path, expected_root_commitment=expected)


def test_same_clean_git_commit_cannot_claim_different_source_trees(
    tmp_path: Path,
) -> None:
    _complete_fixture(tmp_path)
    path = tmp_path / "after" / "source-manifest.json"
    source = json.loads(path.read_bytes())
    source["git_commit"] = "1" * 40
    path.write_bytes(canonical_json_bytes(source))
    expected = _reissue_root(tmp_path)
    with pytest.raises(ProtocolViolation, match="same clean Git commit"):
        collect_extension_cost(tmp_path, expected_root_commitment=expected)


def test_source_diff_retains_empty_file_and_newline_only_changes() -> None:
    before = collector._Tree(
        "before",
        "before/source",
        (("line.py", b"x\n"),),
        D0,
    )
    after = collector._Tree(
        "after",
        "after/source",
        (("empty.py", b""), ("line.py", b"x\r\n")),
        D1,
    )
    assert collector._source_diff(before, after) == [
        {"path": "empty.py", "added_lines": 0, "deleted_lines": 0},
        {"path": "line.py", "added_lines": 1, "deleted_lines": 1},
    ]
    assert (
        CoreDiffFile.from_wire(
            {"path": "empty.py", "added_lines": 0, "deleted_lines": 0}
        ).path
        == "empty.py"
    )


def test_source_diff_retains_git_mode_only_changes() -> None:
    before = collector._Tree(
        "before",
        "before/source",
        (("tool.py", b"print('same')\n"),),
        D0,
        (("tool.py", "100644"),),
    )
    after = collector._Tree(
        "after",
        "after/source",
        (("tool.py", b"print('same')\n"),),
        D1,
        (("tool.py", "100755"),),
    )
    assert collector._source_diff(before, after) == [
        {"path": "tool.py", "added_lines": 0, "deleted_lines": 0}
    ]


def test_opaque_source_json_is_exact_bytes_not_an_evidence_envelope(
    tmp_path: Path,
) -> None:
    _legacy_receipts(tmp_path)
    pretty = b'{\n  "name": "ordinary-source-config"\n}\n'
    _write(tmp_path, "before/source/package.json", pretty)
    expected = _root_manifest(tmp_path)
    result = collect_extension_cost(tmp_path, expected_root_commitment=expected)
    assert result.status is CollectionStatus.INCOMPLETE
    assert digest_bytes(pretty) in dict(result.source_evidence_digests).values()


def test_legacy_receipts_return_typed_incomplete_instead_of_inventing_values(
    tmp_path: Path,
) -> None:
    _legacy_receipts(tmp_path)
    expected = _root_manifest(tmp_path)

    result = collect_extension_cost(tmp_path, expected_root_commitment=expected)

    assert result.status is CollectionStatus.INCOMPLETE
    assert result.observation is None
    roles = {blocker.evidence_role for blocker in result.blockers}
    assert "receipts/migration-outcome.json" in roles
    assert "before/seal.json" in roles
    assert result.to_wire()["freeze_authority_status"] == "not_claimed"


def test_tamper_extra_file_and_old_root_after_resign_are_rejected(
    tmp_path: Path,
) -> None:
    expected = _complete_fixture(tmp_path)
    model = tmp_path / "after" / "artifacts" / "model.bin"
    model.write_bytes(b"tampered")
    with pytest.raises(ProtocolViolation, match="live bytes differ"):
        collect_extension_cost(tmp_path, expected_root_commitment=expected)

    model.write_bytes(b"abcdef")
    extra = tmp_path / "after" / "artifacts" / "extra.bin"
    extra.write_bytes(b"unmanifested")
    with pytest.raises(ProtocolViolation, match="live root differs"):
        collect_extension_cost(tmp_path, expected_root_commitment=expected)

    extra.unlink()
    old_expected = expected
    primary_path = tmp_path / "receipts" / "primary-seal.json"
    primary = json.loads(primary_path.read_bytes())
    primary["blockers"][0]["detail"] = "attacker-reissued-bytes"
    primary_path.write_bytes(canonical_json_bytes(primary))
    new_expected = _reissue_root(tmp_path)
    assert new_expected != old_expected
    with pytest.raises(ProtocolViolation, match="root commitment mismatch"):
        collect_extension_cost(tmp_path, expected_root_commitment=old_expected)


def test_cross_splice_is_rejected_even_with_fresh_root_commitment(
    tmp_path: Path,
) -> None:
    _complete_fixture(tmp_path)
    path = tmp_path / "receipts" / "reveal.json"
    reveal = json.loads(path.read_bytes())
    reveal["primary_binding_set_digest"] = D4
    path.write_bytes(canonical_json_bytes(reveal))
    expected = _reissue_root(tmp_path)

    with pytest.raises(ProtocolViolation, match="primary binding roots"):
        collect_extension_cost(tmp_path, expected_root_commitment=expected)


def test_permuted_manifest_and_bool_score_are_rejected_after_resign(
    tmp_path: Path,
) -> None:
    _complete_fixture(tmp_path)
    source_path = tmp_path / "before" / "source-manifest.json"
    source = json.loads(source_path.read_bytes())
    source["files"] = list(reversed(source["files"]))
    source_path.write_bytes(canonical_json_bytes(source))
    expected = _reissue_root(tmp_path)
    with pytest.raises(ProtocolViolation, match="canonical-order"):
        collect_extension_cost(tmp_path, expected_root_commitment=expected)

    # Rebuild a clean fixture in a separate root for the exact-number guard.
    other = tmp_path.parent / "finite-guard"
    expected = _complete_fixture(other)
    score_path = other / "old-benchmark" / "after.json"
    score = json.loads(score_path.read_bytes())
    score["rows"][0]["score"] = True
    score_path.write_bytes(canonical_json_bytes(score))
    expected = _reissue_root(other)
    with pytest.raises(ProtocolViolation, match="exact finite number"):
        collect_extension_cost(other, expected_root_commitment=expected)


def test_path_traversal_and_absolute_root_staleness_are_rejected(
    tmp_path: Path,
) -> None:
    _complete_fixture(tmp_path)
    manifest_path = tmp_path / ROOT_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"][0]["path"] = "../escape"
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_digest"
    }
    manifest["manifest_digest"] = digest_json(unsigned)
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    with pytest.raises(ProtocolViolation, match="relative path"):
        collect_extension_cost(
            tmp_path,
            expected_root_commitment=collector._root_commitment(manifest_bytes),
        )

    other = tmp_path.parent / "absolute-root"
    _complete_fixture(other)
    root_manifest = json.loads((other / ROOT_MANIFEST_PATH).read_bytes())
    root_manifest["absolute_root"] = "C:/stale/root"
    unsigned = {
        key: value for key, value in root_manifest.items() if key != "manifest_digest"
    }
    root_manifest["manifest_digest"] = digest_json(unsigned)
    manifest_bytes = canonical_json_bytes(root_manifest)
    (other / ROOT_MANIFEST_PATH).write_bytes(manifest_bytes)
    with pytest.raises(ProtocolViolation, match="absolute_root"):
        collect_extension_cost(
            other,
            expected_root_commitment=collector._root_commitment(manifest_bytes),
        )


def test_hardlinked_file_is_rejected(tmp_path: Path) -> None:
    expected = _complete_fixture(tmp_path)
    external = tmp_path.parent / "hardlink-source.bin"
    external.write_bytes(b"x")
    victim = tmp_path / "after" / "artifacts" / "new.bin"
    victim.unlink()
    try:
        os.link(external, victim)
    except OSError:
        pytest.skip("hardlink creation is unavailable")
    with pytest.raises(ProtocolViolation, match="hard-linked"):
        collect_extension_cost(tmp_path, expected_root_commitment=expected)


def test_root_reparse_or_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    expected = _complete_fixture(target)
    linked = tmp_path / "linked"
    if os.name == "nt":
        result = subprocess.run(
            ("cmd", "/c", "mklink", "/J", str(linked), str(target)),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip("junction creation is unavailable")
    else:
        try:
            os.symlink(target, linked, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation is unavailable")
    with pytest.raises(ProtocolViolation, match="plain directory"):
        collect_extension_cost(linked, expected_root_commitment=expected)


def test_nested_reparse_or_symlink_entry_is_rejected(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    expected = _complete_fixture(evidence)
    external = tmp_path / "external"
    external.mkdir()
    _write(external, "hidden.bin", b"hidden")
    linked = evidence / "nested-link"
    if os.name == "nt":
        result = subprocess.run(
            ("cmd", "/c", "mklink", "/J", str(linked), str(external)),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip("junction creation is unavailable")
    else:
        try:
            os.symlink(external, linked, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation is unavailable")
    with pytest.raises(ProtocolViolation, match="link/reparse"):
        collect_extension_cost(evidence, expected_root_commitment=expected)
