from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    domain_digest,
)
from prototype.unified_map.formal_scope_producer import (
    FORMAL_SCOPE_INCOMPLETE_STATUS,
    PREDECESSOR_ORDER,
    PREDECESSOR_ROOT_DOMAIN,
    SCOPE_BUILD_ROOT_DOMAIN,
    build_code_owned_producer_source_closure_manifest_bytes,
    parse_formal_scope_build_report_bytes,
    parse_producer_source_closure_manifest_bytes,
    produce_formal_scope_build_report,
)
from prototype.unified_map.metric_configuration import (
    benchmark_v1_metric_target_registry,
)
from prototype.unified_map.scope_transition_protocols import (
    EXTENSION_TEMPLATE_SET_BYTES,
    SPLIT_DERIVATION_PROTOCOL_BYTES,
    build_extension_template_set,
    build_split_derivation_protocol,
)
from prototype.unified_map.seed_protocol import SEED_PROTOCOL_MANIFEST_BYTES
from prototype.unified_map.task_protocol import (
    CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES,
)
from prototype.unified_map.world_scope_fragments import (
    CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES,
    ScopeGapCode,
    inspect_world_scope_fragments,
)


def _inputs() -> tuple[bytes, ...]:
    return (
        CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES,
        benchmark_v1_metric_target_registry().canonical_bytes,
        CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES,
        SEED_PROTOCOL_MANIFEST_BYTES,
        SPLIT_DERIVATION_PROTOCOL_BYTES,
        EXTENSION_TEMPLATE_SET_BYTES,
        build_code_owned_producer_source_closure_manifest_bytes(),
    )


def _report():
    return produce_formal_scope_build_report(*_inputs())


def _mutate_top_level(payload: bytes, key: str, value: object = "forbidden") -> bytes:
    wire = json.loads(payload)
    wire[key] = value
    return canonical_json_bytes(wire)


def test_live_build_is_canonical_incomplete_and_cannot_emit_scope_or_freeze() -> None:
    report = _report()

    assert report.status == FORMAL_SCOPE_INCOMPLETE_STATUS
    assert report.scope_manifest_emitted is False
    assert report.scope_manifest_bytes is None
    assert report.benchmark_freeze_eligible is False
    assert report.freeze_authority is False
    assert report.canonical_bytes == canonical_json_bytes(report.to_wire())
    assert parse_formal_scope_build_report_bytes(report.canonical_bytes) == report


def test_gap_inventory_is_exact_and_preserves_each_typed_source_wire() -> None:
    report = _report()
    counts = {
        source_id: sum(gap.source_id == source_id for gap in report.gaps)
        for source_id in PREDECESSOR_ORDER
    }

    # D metric-target gaps are present in the world report only as an exact
    # cross-reference to the metric registry.  The formal producer verifies
    # that join, then records the registry-owned typed gap once rather than
    # double-counting the same unresolved target under two predecessors.
    world_gaps = inspect_world_scope_fragments().gaps
    assert counts["world_scope_fragment"] == sum(
        gap.code is not ScopeGapCode.D_METRIC_TARGET_GAP for gap in world_gaps
    )
    assert counts["metric_semantic_registry"] == (
        benchmark_v1_metric_target_registry().target_gap_count
    )
    assert counts["split_derivation_protocol"] == (
        build_split_derivation_protocol().gap_count
    )
    assert counts["extension_template_set"] == (
        build_extension_template_set().gap_count
    )
    assert counts["task_execution_manifest"] == 0
    assert counts["seed_protocol_manifest"] == 0
    assert counts["producer_source_closure_manifest"] == 0
    assert len(report.gaps) == sum(counts.values())
    assert report.to_wire()["gap_count"] == len(report.gaps)
    assert report.to_wire()["gaps"] == [gap.to_wire() for gap in report.gaps]

    before = report.canonical_bytes
    detached = report.gaps[0].gap_wire
    detached["detail"] = "caller-side mutation"
    assert report.canonical_bytes == before


def test_every_predecessor_records_complete_canonical_preimage_and_two_digests() -> (
    None
):
    report = _report()
    wire_rows = report.to_wire()["predecessors"]

    assert tuple(row["predecessor_id"] for row in wire_rows) == PREDECESSOR_ORDER
    for row, expected_payload in zip(wire_rows, _inputs(), strict=True):
        recovered = base64.b64decode(row["canonical_bytes_base64"], validate=True)
        assert recovered == expected_payload
        assert row["canonical_byte_length"] == len(expected_payload)
        assert row["artifact_digest"] == digest_bytes(expected_payload)
        assert row["domain_semantic_digest"].startswith("sha256:")
        assert row["domain_semantic_digest"] != row["artifact_digest"]


def test_predecessor_and_build_roots_are_domain_separated_exact_preimages() -> None:
    report = _report()
    expected_predecessor_root = domain_digest(
        PREDECESSOR_ROOT_DOMAIN,
        tuple(item.record_bytes for item in report.predecessors),
    )
    expected_build_root = domain_digest(
        SCOPE_BUILD_ROOT_DOMAIN,
        (canonical_json_bytes(report._root_preimage_wire()),),
    )

    assert report.predecessor_root == expected_predecessor_root
    assert report.scope_build_root == expected_build_root
    assert report.predecessor_root != report.scope_build_root


@pytest.mark.parametrize("index", range(len(PREDECESSOR_ORDER)))
def test_each_predecessor_requires_strict_code_owned_rebuild(index: int) -> None:
    inputs = list(_inputs())
    inputs[index] = _mutate_top_level(inputs[index], "unexpected", index)

    with pytest.raises(ProtocolViolation):
        produce_formal_scope_build_report(*inputs)


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "actual_assignment",
        "partition",
        "raw_seed_value",
        "train5_precommit_actual",
        "eval_commit",
        "corpus_manifest",
        "candidate_seals",
        "extension_reveal",
        "s_prime_digest",
        "freeze_authorization",
    ],
)
def test_forbidden_actual_artifact_fields_cannot_be_resigned_into_input(
    forbidden_key: str,
) -> None:
    inputs = list(_inputs())
    inputs[4] = _mutate_top_level(inputs[4], forbidden_key)

    with pytest.raises(ProtocolViolation):
        produce_formal_scope_build_report(*inputs)


def test_fixed_input_order_rejects_cross_type_splice() -> None:
    inputs = list(_inputs())
    inputs[4], inputs[5] = inputs[5], inputs[4]

    with pytest.raises(ProtocolViolation):
        produce_formal_scope_build_report(*inputs)


def test_report_parser_rejects_resigned_root_cross_splice_and_reorder() -> None:
    wire = _report().to_wire()
    attacks: list[dict[str, object]] = []

    resigned = copy.deepcopy(wire)
    resigned["scope_build_root"] = "sha256:" + "0" * 64
    attacks.append(resigned)

    cross_spliced = copy.deepcopy(wire)
    rows = cross_spliced["predecessors"]
    rows[0]["canonical_bytes_base64"] = rows[1]["canonical_bytes_base64"]
    rows[0]["canonical_byte_length"] = rows[1]["canonical_byte_length"]
    rows[0]["artifact_digest"] = rows[1]["artifact_digest"]
    attacks.append(cross_spliced)

    reordered = copy.deepcopy(wire)
    reordered["predecessors"][0], reordered["predecessors"][1] = (
        reordered["predecessors"][1],
        reordered["predecessors"][0],
    )
    attacks.append(reordered)

    for attack in attacks:
        with pytest.raises(ProtocolViolation):
            parse_formal_scope_build_report_bytes(canonical_json_bytes(attack))


def test_report_parser_rejects_duplicate_and_noncanonical_bytes() -> None:
    payload = _report().canonical_bytes
    duplicate = payload.replace(
        b'{"benchmark_freeze_eligible":false,',
        b'{"benchmark_freeze_eligible":false,"benchmark_freeze_eligible":false,',
        1,
    )

    with pytest.raises(ProtocolViolation, match="duplicate"):
        parse_formal_scope_build_report_bytes(duplicate)
    with pytest.raises(ProtocolViolation, match="canonical"):
        parse_formal_scope_build_report_bytes(payload.rstrip(b"\n"))


def test_source_closure_parser_rejects_resigning_and_loaded_live_source_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = build_code_owned_producer_source_closure_manifest_bytes()
    parsed = parse_producer_source_closure_manifest_bytes(payload)
    assert parsed["authoritative_process_requirement"] == (
        "fresh_process_import_and_materialization_required"
    )

    resigned = _mutate_top_level(payload, "source_tree_root", "sha256:" + "0" * 64)
    with pytest.raises(ProtocolViolation):
        parse_producer_source_closure_manifest_bytes(resigned)

    original = Path.read_bytes

    def drift_one(path: Path) -> bytes:
        value = original(path)
        if path.name == "formal_scope_producer.py":
            return value + b"# drift\n"
        return value

    monkeypatch.setattr(Path, "read_bytes", drift_one)
    with pytest.raises(ProtocolViolation, match="fresh process"):
        parse_producer_source_closure_manifest_bytes(payload)


@pytest.mark.parametrize("bad", [bytearray(b"{}\n"), "{}\n", memoryview(b"{}\n")])
def test_public_parsers_require_exact_bytes(bad: object) -> None:
    with pytest.raises(ProtocolViolation, match="exact bytes"):
        parse_formal_scope_build_report_bytes(bad)  # type: ignore[arg-type]
    with pytest.raises(ProtocolViolation, match="exact bytes"):
        parse_producer_source_closure_manifest_bytes(bad)  # type: ignore[arg-type]
