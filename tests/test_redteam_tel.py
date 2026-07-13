from __future__ import annotations

import json

from prototype.candidates.temporal_ledger import TemporalEvidenceLedger, TemporalRuleModule
from prototype.contract import (
    ClockSet,
    InfoState,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
)


AT = "2026-01-01T08:00:00Z"
CUT = "2026-01-01T09:00:00Z"


def artifact(
    source_id: str,
    concept: str = "temperature",
    value: object = 39.0,
    *,
    state: InfoState = InfoState.PRESENT,
    role: SemanticRole = SemanticRole.RAW_OBSERVATION,
    raw_payload: dict[str, object] | None = None,
) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=f"artifact-{source_id}",
        source_id=source_id,
        semantic_role=role,
        concept=concept,
        scope=Scope("p1"),
        clocks=ClockSet(AT, None, AT, AT, AT),
        information_state=state,
        value=value,
        unit="Cel" if concept == "temperature" else None,
        context={},
        raw_payload={} if raw_payload is None else raw_payload,
    )


def project(
    engine: TemporalEvidenceLedger,
    target: str,
    query_id: str,
    *,
    task: str | None = None,
    model_version: str | None = None,
    guarantees: tuple[str, ...] = (),
) -> object:
    return engine.query(
        QuerySpec(
            query_id=query_id,
            kind=QueryKind.PROJECT,
            target=target,
            subject_id="p1",
            as_known_at=CUT,
            valid_at=AT,
            task=task,
            model_version=model_version,
            requested_guarantees=guarantees,
        )
    )


def fever_module() -> TemporalRuleModule:
    return TemporalRuleModule.from_data(
        {
            "module_id": "fever",
            "version": "1",
            "registered_at": "2025-12-01T00:00:00Z",
            "rules": [
                {
                    "rule_id": "temperature-to-fever",
                    "premises": [{"concept": "temperature", "min_value": 38, "unit": "Cel"}],
                    "conclusion": {"concept": "fever", "value": True},
                }
            ],
        }
    )


def test_non_exact_container_is_rejected_before_deepcopy_or_hash() -> None:
    touched = {"copy": False, "iter": False}

    class HostileDict(dict):
        def __deepcopy__(self, memo: object) -> object:
            touched["copy"] = True
            raise AssertionError("must not copy")

        def items(self):  # type: ignore[no-untyped-def]
            touched["iter"] = True
            raise AssertionError("must not iterate")

    bad = artifact("bad-context")
    object.__setattr__(bad, "context", HostileDict())
    result = TemporalEvidenceLedger().ingest(bad)
    assert result.status is ResultStatus.INVALID
    assert touched == {"copy": False, "iter": False}

    hostile_module = HostileDict()
    result = TemporalEvidenceLedger().register_module(hostile_module)
    assert result.status is ResultStatus.INVALID
    assert touched == {"copy": False, "iter": False}


def test_callable_and_oversized_payloads_fail_closed_without_mutation() -> None:
    engine = TemporalEvidenceLedger()
    callable_payload = artifact("callback", value={"nested": lambda: 1})
    assert engine.ingest(callable_payload).status is ResultStatus.INVALID
    oversized = artifact("oversized", value=[0] * 10_100)
    result = engine.ingest(oversized)
    assert result.status is ResultStatus.INVALID
    assert "预算" in result.diagnostics["error"]
    assert project(engine, "temperature", "q-empty").status is ResultStatus.INSUFFICIENT


def test_corrupted_query_and_typed_module_return_invalid_not_exception() -> None:
    engine = TemporalEvidenceLedger()
    spec = QuerySpec("q-bad", QueryKind.PROJECT, "x", "p1", CUT)
    object.__setattr__(spec, "kind", "project")
    assert engine.query(spec).status is ResultStatus.INVALID

    spec2 = QuerySpec("q-bad-2", QueryKind.PROJECT, "x", "p1", CUT)
    object.__setattr__(spec2, "requested_guarantees", ["evidence_roots"])
    assert engine.query(spec2).status is ResultStatus.INVALID

    module = fever_module()
    object.__setattr__(module.rules[0].premises[0], "information_states", ("present",))
    assert engine.register_module(module).status is ResultStatus.INVALID


def test_model_version_guarantee_and_task_are_never_silently_ignored() -> None:
    engine = TemporalEvidenceLedger()
    engine.ingest(artifact("root"))
    assert project(engine, "temperature", "q-model", model_version="model-v9").status is ResultStatus.UNSUPPORTED
    unknown = project(engine, "temperature", "q-guarantee-bad", guarantees=("magic",))
    assert unknown.status is ResultStatus.UNSUPPORTED
    assert unknown.diagnostics["unsupported_guarantees"] == ["magic"]
    supported = project(engine, "temperature", "q-guarantee-ok", guarantees=("evidence_roots",))
    assert supported.status is ResultStatus.OK
    assert supported.native_witness["requested_guarantees_consumed"] is True
    assert supported.evidence_witness["root_sources"] == ["root"]
    unregistered_task = project(engine, "temperature", "q-task", task="unregistered-task")
    assert unregistered_task.status is ResultStatus.UNSUPPORTED
    assert unregistered_task.diagnostics["task"] == "unregistered-task"


def test_masked_payload_is_redacted_in_ingest_query_explain_and_rebuild() -> None:
    secret = "TOP_SECRET_VALUE"
    engine = TemporalEvidenceLedger()
    receipt = engine.ingest(
        artifact(
            "masked-root",
            concept="genetic_result",
            value=secret,
            state=InfoState.MASKED,
            role=SemanticRole.MASKED_ARTIFACT,
            raw_payload={"secret": secret},
        )
    )
    result = project(engine, "genetic_result", "q-masked", guarantees=("masked_non_disclosure",))
    explained = engine.explain("q-masked")
    ingest_explained = engine.explain("ingest:masked-root")
    rebuilt = project(engine.clean_rebuild(), "genetic_result", "q-masked-rebuilt")
    rendered = json.dumps(
        [receipt.to_dict(), result.to_dict(), explained.to_dict(), ingest_explained.to_dict(), rebuilt.to_dict()],
        sort_keys=True,
    )
    assert secret not in rendered
    claim = result.value["claims"][0]
    assert claim["value"] is None
    assert claim["context"] == {"redacted": True}
    root = result.evidence_witness["root_artifacts"]["masked-root"]
    assert root["raw_payload"] == {"redacted": True}
    assert root["context"] == {"redacted": True}
    assert receipt.native_witness["fingerprint"] is None


def test_semantic_claim_id_stays_stable_as_proof_alternatives_change() -> None:
    engine = TemporalEvidenceLedger()
    engine.register_module(fever_module())
    engine.ingest(artifact("root-a"))
    first = project(engine, "fever", "q-first")
    first_claim = first.value["claims"][0]
    first_proofs = {p["proof_id"] for p in first_claim["proof_alternatives"]}

    engine.ingest(artifact("root-b"))
    second = project(engine, "fever", "q-second")
    second_claim = second.value["claims"][0]
    second_proofs = {p["proof_id"] for p in second_claim["proof_alternatives"]}
    assert second_claim["claim_id"] == first_claim["claim_id"]
    assert first_proofs < second_proofs
    assert all("fact_id" in p and "claim_id" not in p for p in second_claim["proof_alternatives"])

    engine.retract("root-b", "2026-01-01T10:00:00Z")
    after = engine.query(
        QuerySpec("q-after", QueryKind.PROJECT, "fever", "p1", "2026-01-01T11:00:00Z", AT)
    )
    rebuilt = engine.clean_rebuild().query(
        QuerySpec("q-after", QueryKind.PROJECT, "fever", "p1", "2026-01-01T11:00:00Z", AT)
    )
    assert after.value["claims"][0]["claim_id"] == first_claim["claim_id"]
    assert after.to_dict() == rebuilt.to_dict()


def test_masked_claim_id_does_not_encode_hidden_value() -> None:
    ids: list[str] = []
    for secret in ("secret-A", "secret-B"):
        engine = TemporalEvidenceLedger()
        engine.ingest(
            artifact(
                "same-root",
                concept="masked_concept",
                value=secret,
                state=InfoState.MASKED,
                role=SemanticRole.MASKED_ARTIFACT,
                raw_payload={"secret": secret},
            )
        )
        result = project(engine, "masked_concept", "q")
        ids.append(result.value["claims"][0]["claim_id"])
        assert secret not in json.dumps(result.to_dict(), sort_keys=True)
    assert ids[0] == ids[1]
