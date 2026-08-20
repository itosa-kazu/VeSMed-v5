#!/usr/bin/env python3
"""Compile the case-blind role registries from the frozen generic model pack.

The mapper receives only diagnosis-neutral observation/action identifiers and
their wire types.  The oracle receives only the neutral process catalogue.
Neither registry exposes model parameters, factors, priors, edges, topology,
or runtime outputs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
MODEL_PACK = HERE / "model_pack.json"
MAPPER_REGISTRY = HERE / "mapper_sanitized_registry.json"
ORACLE_REGISTRY = HERE / "oracle_sanitized_process_registry.json"

MAPPER_SCHEMA_VERSION = "NCF-MAPPER-SANITIZED-REGISTRY-1.0.0"
ORACLE_SCHEMA_VERSION = "NCF-ORACLE-SANITIZED-PROCESS-REGISTRY-1.0.0"

VALUE_TYPE_MAP = {
    "boolean": "BOOLEAN",
    "number": "NUMBER",
    "ordinal": "ORDINAL",
    "categorical": "CATEGORICAL",
}


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_model_pack(path: Path = MODEL_PACK) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), sha256_bytes(raw)


def build_mapper_registry(model: dict[str, Any], model_sha256: str) -> dict[str, Any]:
    observations = []
    for observation in sorted(model["observations"], key=lambda row: row["concept_id"]):
        observations.append(
            {
                "concept_id": observation["concept_id"],
                "unit": observation.get("unit"),
                "value_type": VALUE_TYPE_MAP[observation["value_type"]],
            }
        )

    actions = []
    for action in sorted(model["actions"], key=lambda row: row["action_id"]):
        actions.append(
            {
                "action_id": action["action_id"],
                "entity_type": "ACTION",
                "unit": None,
            }
        )

    return {
        "actions": actions,
        "observations": observations,
        "schema_version": MAPPER_SCHEMA_VERSION,
        "source_model_pack_sha256": model_sha256,
    }


def build_oracle_registry(model: dict[str, Any], model_sha256: str) -> dict[str, Any]:
    processes = []
    for process in sorted(model["processes"], key=lambda row: row["process_id"]):
        name_en = process["label_en"]
        domain = process["organ_or_domain"]
        processes.append(
            {
                "domain": domain,
                "name_en": name_en,
                "name_ja": process["label_ja"],
                "neutral_description": (
                    f"Mechanistic process in {domain}: {name_en}."
                ),
                "process_id": process["process_id"],
            }
        )

    return {
        "processes": processes,
        "schema_version": ORACLE_SCHEMA_VERSION,
        "source_model_pack_sha256": model_sha256,
    }


def compile_registries() -> tuple[dict[str, Any], dict[str, Any]]:
    model, model_sha256 = load_model_pack()
    mapper = build_mapper_registry(model, model_sha256)
    oracle = build_oracle_registry(model, model_sha256)
    MAPPER_REGISTRY.write_bytes(canonical_bytes(mapper))
    ORACLE_REGISTRY.write_bytes(canonical_bytes(oracle))
    return mapper, oracle


def main() -> int:
    mapper, oracle = compile_registries()
    summary = {
        "mapper_registry": {
            "path": str(MAPPER_REGISTRY),
            "sha256": sha256_bytes(MAPPER_REGISTRY.read_bytes()),
            "observations": len(mapper["observations"]),
            "actions": len(mapper["actions"]),
        },
        "oracle_registry": {
            "path": str(ORACLE_REGISTRY),
            "sha256": sha256_bytes(ORACLE_REGISTRY.read_bytes()),
            "processes": len(oracle["processes"]),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
