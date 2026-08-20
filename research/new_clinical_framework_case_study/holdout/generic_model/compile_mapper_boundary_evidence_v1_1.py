#!/usr/bin/env python3
"""Compile exact runtime-side mapper boundary evidence for generic-model/1.1.0."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
CASE_STUDY = HERE.parents[1]
EVIDENCE_DIR = HERE.parent / "evidence"
PROBES = EVIDENCE_DIR / "GENERIC_MODEL_V1_1_RUNTIME_PROBES.json"
OUTPUT = EVIDENCE_DIR / "GENERIC_MODEL_MAPPER_HARD_GATE_PROBES.json"
PACK = HERE / "model_pack.json"
MAPPER = HERE / "mapper_sanitized_registry.json"
ORACLE = HERE / "oracle_sanitized_process_registry.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    probes = load(PROBES)
    by_id = {row["probe_id"]: row for row in probes["probes"]}
    reliability = by_id["GM11-RELIABILITY-OPERATIVE"]
    masking = by_id["GM11-SUPPORT-MASKED-FAIL-CLOSED"]
    probe_pass = reliability["status"] == "PASS" and masking["status"] == "PASS"
    result = {
        "case_blind": True,
        "interpretation": {
            "mapper_execution_boundary": (
                "The runtime honors reliability and a mapper-supplied rankable=false "
                "support-masking disposition. The role-isolated mapper must still prove "
                "that it assigns those fields correctly for the selected primary case."
            ),
            "record_only_factor": (
                "The retained zero-likelihood DISPOSITION message is provenance, not an "
                "operative clinical likelihood factor."
            ),
            "status_boundary": (
                "This artifact passes the frozen generic/runtime interface only; it does "
                "not claim that a primary mapper role execution has occurred."
            ),
        },
        "model_pack_sha256": sha256(PACK),
        "primary_holdout_inspected": False,
        "probe_bindings": {
            "reliability": reliability,
            "support_masking": masking,
            "runtime_probe_artifact_sha256": sha256(PROBES),
        },
        "registry_bindings": {
            "mapper_sanitized_registry": {
                "path": "holdout/generic_model/mapper_sanitized_registry.json",
                "sha256": sha256(MAPPER),
            },
            "oracle_sanitized_process_registry": {
                "path": "holdout/generic_model/oracle_sanitized_process_registry.json",
                "sha256": sha256(ORACLE),
            },
        },
        "runtime_source_hashes": {
            path.relative_to(CASE_STUDY).as_posix(): sha256(path)
            for path in (
                CASE_STUDY / "runtime_v2" / "engine.py",
                CASE_STUDY / "runtime_v2" / "architecture_wire.py",
                CASE_STUDY / "runtime_v2" / "schema.py",
            )
        },
        "schema_version": "ncf.generic-model-mapper-boundary-probe.v1.1",
        "status": (
            "RUNTIME_BOUNDARY_PASS_MAPPER_EXECUTION_REQUIRED"
            if probe_pass
            else "RUNTIME_BOUNDARY_PROBE_FAILURE"
        ),
    }
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if probe_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
