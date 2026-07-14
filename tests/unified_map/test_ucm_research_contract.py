from __future__ import annotations

import re
from pathlib import Path

from prototype.unified_map.state import ALLOWED_INERT_CODECS


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research" / "unified_map"

REQUIRED_DOCUMENTS = {
    "PLAN.md",
    "FIRST_PRINCIPLES.md",
    "HYPOTHESES.md",
    "SOURCES.md",
    "MICROWORLDS.md",
    "EXPERIMENTS.md",
    "COLLISIONS.md",
    "REDTEAM.md",
    "DECISION.md",
    "ARCHITECTURE.md",
    "FORMAL_SPEC.md",
    "PLAIN_CHINESE.md",
    "BENCHMARK.md",
    "CANDIDATES.md",
    "RESEARCH_LOG.md",
    "K0_REUSE_BOUNDARY.md",
}


def text(name: str) -> str:
    return (RESEARCH / name).read_text(encoding="utf-8")


def test_all_continuously_maintained_research_documents_exist() -> None:
    missing = sorted(name for name in REQUIRED_DOCUMENTS if not (RESEARCH / name).is_file())
    assert missing == []


def test_formal_documents_do_not_depend_on_agent_drafts() -> None:
    for name in REQUIRED_DOCUMENTS:
        assert "_draft_" not in text(name), name


def test_microworld_contract_has_exactly_w01_through_w20_and_eight_sections() -> None:
    source = text("MICROWORLDS.md")
    matches = list(re.finditer(r"^## (W\d{2})：.*$", source, flags=re.MULTILINE))
    assert [match.group(1) for match in matches] == [
        f"W{index:02d}" for index in range(1, 21)
    ]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        section = source[match.end() : end]
        headings = {
            int(number)
            for number in re.findall(r"^### ([1-8])(?:\.|：)", section, re.MULTILINE)
        }
        assert headings == set(range(1, 9)), match.group(1)


def test_candidate_baseline_and_experiment_registries_are_complete_but_unrun() -> None:
    candidates = text("CANDIDATES.md")
    families = set(re.findall(r"\| (F\d{2}) \|", candidates))
    baselines = set(re.findall(r"\b(B0[1-4])\b", candidates))
    assert families == {f"F{index:02d}" for index in range(1, 13)}
    assert baselines == {f"B{index:02d}" for index in range(1, 5)}

    experiments = text("EXPERIMENTS.md")
    experiment_ids = set(re.findall(r"EXP-(\d{3})", experiments))
    assert experiment_ids == {f"{index:03d}" for index in range(1, 41)}
    assert re.search(r"候选实验完成数为\s*0\s*/\s*30", experiments)


def test_failure_and_evidence_codes_have_one_formal_registry() -> None:
    formal = text("FORMAL_SPEC.md")
    registry = set(re.findall(r"`(UCM-[FE]\d{3}-[A-Z0-9_]+)`", formal))
    assert len({code for code in registry if code.startswith("UCM-F")}) == 24
    assert len({code for code in registry if code.startswith("UCM-E")}) == 3
    for name in ["BENCHMARK.md", "CANDIDATES.md", "EXPERIMENTS.md", "REDTEAM.md"]:
        references = set(
            re.findall(r"`(UCM-[FE]\d{3}-[A-Z0-9_]+)`", text(name))
        )
        assert references <= registry, (name, sorted(references - registry))


def test_documented_state_codecs_equal_executable_inert_codecs() -> None:
    benchmark = text("BENCHMARK.md")
    expected = {"canonical-json-v1", "raw-f64le-v1"}
    assert ALLOWED_INERT_CODECS == expected
    for codec in expected:
        assert codec in benchmark
    assert "safe-msgpack" not in benchmark


def test_no_freeze_claim_exists_before_a_real_manifest() -> None:
    manifest = RESEARCH / "FREEZE_MANIFEST.json"
    if not manifest.exists():
        assert "PRE-FREEZE" in "\n".join(text("BENCHMARK.md").splitlines()[:8])
        assert "PRE-FREEZE" in "\n".join(text("MICROWORLDS.md").splitlines()[:8])
        assert "NOT EXECUTED" in "\n".join(text("REDTEAM.md").splitlines()[:8])
