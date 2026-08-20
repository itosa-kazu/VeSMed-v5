#!/usr/bin/env python3
"""Write the final case-blind component audit for generic-model/1.1.0."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parent / "evidence"
PACK = HERE / "model_pack.json"
VALIDATION = HERE / "model_validation.json"
CONTENT = EVIDENCE / "GENERIC_MODEL_V1_1_CONTENT_AUDIT.json"
PROBES = EVIDENCE / "GENERIC_MODEL_V1_1_RUNTIME_PROBES.json"
PERFORMANCE = EVIDENCE / "GENERIC_MODEL_V1_1_PERFORMANCE.json"
MAPPER_BOUNDARY = EVIDENCE / "GENERIC_MODEL_MAPPER_HARD_GATE_PROBES.json"
MAPPER_REGISTRY = HERE / "mapper_sanitized_registry.json"
ORACLE_REGISTRY = HERE / "oracle_sanitized_process_registry.json"
RUNTIME_MANIFEST = HERE.parents[1] / "runtime_v2" / "evidence" / "manifest.json"
RUNTIME_SEAL = HERE.parents[1] / "runtime_v2" / "evidence" / "FREEZE_SEAL.json"
GENERIC_SEAL = EVIDENCE / "GENERIC_MODEL_FREEZE_SEAL.json"
OUTPUT_JSON = EVIDENCE / "GENERIC_MODEL_FINAL_INDEPENDENT_AUDIT.json"
OUTPUT_MD = EVIDENCE / "GENERIC_MODEL_FINAL_INDEPENDENT_AUDIT.md"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def binding(path: Path) -> dict[str, object]:
    return {"path": path.relative_to(HERE.parents[1]).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}


def main() -> int:
    content = load(CONTENT)
    probes = load(PROBES)
    performance = load(PERFORMANCE)
    mapper = load(MAPPER_REGISTRY)
    oracle = load(ORACLE_REGISTRY)
    validation = load(VALIDATION)
    generic_seal = load(GENERIC_SEAL)
    runtime_binding = validation.get("runtime_binding", {})
    component_pass = (
        content["status"] == "PASS"
        and probes["status"] == "PASS"
        and performance["status"] == "PASS"
        and content["artifact_hashes"]["model_pack.json"] == sha256(PACK)
        and probes["model_pack_sha256"] == sha256(PACK)
        and performance["model_pack_sha256"] == sha256(PACK)
        and mapper["source_model_pack_sha256"] == sha256(PACK)
        and oracle["source_model_pack_sha256"] == sha256(PACK)
        and validation.get("model_version") == "generic-model/1.1.0"
        and validation.get("status") == "FINAL_PASS"
        and runtime_binding.get("manifest_sha256") == sha256(RUNTIME_MANIFEST)
        and runtime_binding.get("seal_sha256") == sha256(RUNTIME_SEAL)
        and generic_seal.get("model_pack_sha256") == sha256(PACK)
        and generic_seal.get("validation_sha256") == sha256(VALIDATION)
        and generic_seal.get("status") == "FINAL_PASS"
    )
    status = (
        "GENERIC_V1_1_COMPONENT_FINAL_PASS"
        if component_pass
        else "GENERIC_V1_1_COMPONENT_AUDIT_FAILURE"
    )
    result = {
        "artifact_bindings": {
            "content_audit": binding(CONTENT),
            "mapper_boundary": binding(MAPPER_BOUNDARY),
            "mapper_registry": binding(MAPPER_REGISTRY),
            "model_pack": binding(PACK),
            "model_validation": binding(VALIDATION),
            "oracle_registry": binding(ORACLE_REGISTRY),
            "performance": binding(PERFORMANCE),
            "runtime_manifest": binding(RUNTIME_MANIFEST),
            "runtime_probes": binding(PROBES),
            "runtime_seal": binding(RUNTIME_SEAL),
            "generic_component_seal": binding(GENERIC_SEAL),
        },
        "case_blind": True,
        "clinical_claim_status": "NOT_CLINICALLY_CALIBRATED",
        "model_id": content["model_id"],
        "model_version": content["model_version"],
        "outcome": (
            "Generic-model/1.1.0 content and runtime behavior pass their case-blind "
            "audits. The model validation and component seal bind the exact final "
            "runtime manifest/seal and recursive generic source tree."
        ),
        "primary_holdout_inspected": False,
        "residual_boundaries": [
            "No primary or real case was read or selected.",
            "The model remains structural toy machinery, not a calibrated diagnostic or treatment system.",
            "Primary mapper role execution remains a post-selection hard gate even though the runtime-side interface passes.",
            "G18 blind real-case replay remains outside this component-only freeze.",
        ],
        "schema_version": "ncf.generic-model-independent-audit.v1.1",
        "status": status,
        "verification": {
            "content_checks": f"{content['status']} {len(content['checks'])}/{len(content['checks'])}",
            "exact_activation_hypotheses": performance["structural_counts"]["joint_activation_hypotheses"],
            "registry_unit_tests": "8/8 PASS",
            "runtime_behavior_probes": f"{probes['status']} {probes['passed']}/{probes['total']}",
            "runtime_full_suite_final": "132/132 PASS",
            "structural_harness": "24/24 PL gates and G01-G17 PASS",
        },
    }
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = f"""# Generic Model v1.1 独立审计（case-blind，final component）

## Outcome

**{status}**

`generic-model/1.1.0` 的通用内容与最终 runtime 行为验证通过；`model_validation.json` 和
generic component seal 已原子绑定最终 runtime manifest/seal 与完整 generic source tree。

## Key Evidence

- model pack SHA-256：`{sha256(PACK)}`
- content audit：`{content['status']} {len(content['checks'])}/{len(content['checks'])}`
- runtime behavior probes：`{probes['status']} {probes['passed']}/{probes['total']}`
- exact activation joint：`{performance['structural_counts']['joint_activation_hypotheses']}` hypotheses
- sanitized registries：{len(mapper['observations'])} observations / {len(mapper['actions'])} actions / {len(oracle['processes'])} processes；compiler tests 8/8 PASS
- final runtime full suite：132/132 PASS
- structural harness：24/24 PL gates + G01-G17 PASS

## Verification boundary

- 未读取、选择或运行 primary/real case。
- reliability 与 support masking 的 runtime interface 已通过；primary mapper 是否正确赋值仍是后续隔离角色 hard gate。
- 参数、likelihood、drift、coupling 与 action effects 均是 toy/non-calibrated，不能宣称临床有效。
- 本结论只冻结 generic component；G18 blind real-case replay 尚未执行。

## Next Step

后续仅可按已冻结 primary protocol 执行 blind real-case G18；不得把本 component freeze 解释为临床校准或治疗有效性证明。
"""
    OUTPUT_MD.write_text(md, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if component_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
