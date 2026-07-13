from __future__ import annotations

import json
import unittest
from copy import deepcopy
from dataclasses import asdict

from prototype.benchmark import BenchmarkRunner, _semantic, summarize_runs
from prototype.contract import (
    ArchitectureCandidate,
    CandidateManifest,
    CapabilityResult,
    QueryKind,
    ResultStatus,
    Track,
)
from prototype.workloads import (
    DEFAULT_WORKLOAD_ROOT,
    build_all_workloads,
    candidate_view,
    load_workloads,
)


class _BaseDummy(ArchitectureCandidate):
    calls: list[tuple[str, object]]

    def __init__(self) -> None:
        super().__init__(Track.NATIVE)
        self.calls = []

    @property
    def manifest(self) -> CandidateManifest:
        return CandidateManifest(
            candidate_id=self.__class__.__name__,
            version="1",
            formal_signature=("dummy",),
            execution_semantics=("dummy",),
            companion_layers=(),
            primitive_profile={},
            foreign_boundaries=(),
            declared_query_capabilities=tuple(QueryKind),
            failure_types=tuple(ResultStatus),
        )

    def clean_rebuild(self) -> "_BaseDummy":
        rebuilt = self.__class__()
        rebuilt.calls = list(self.calls)
        return rebuilt

    def explain(self, result_id: str) -> CapabilityResult:
        self.calls.append(("explain", result_id))
        return self._result()


class _CannedOK(_BaseDummy):
    """Structurally pretty but semantically empty; it must not pass."""

    def _result(self) -> CapabilityResult:
        return CapabilityResult(
            status=ResultStatus.OK,
            validation="valid",
            capability="native",
            epistemic="unknown",
            coverage_status="unknown",
            identification="not_applicable",
            computation="exact",
            value_kind="claims",
            value={"claims": [], "hypotheses": [], "trajectory": None, "probability": None},
            evidence_witness={"root_sources": []},
            native_witness={"kind": "none"},
        )

    def ingest(self, artifact):
        self.calls.append(("ingest", artifact))
        return self._result()

    def retract(self, source_id, known_at):
        self.calls.append(("retract", (source_id, known_at)))
        return self._result()

    def query(self, spec):
        self.calls.append(("query", spec))
        return self._result()

    def register_module(self, module):
        self.calls.append(("register_module", module))
        return self._result()


class _AlwaysUnsupported(_BaseDummy):
    @property
    def manifest(self) -> CandidateManifest:
        base = super().manifest
        return CandidateManifest(**{**asdict(base), "declared_query_capabilities": ()})

    def _result(self) -> CapabilityResult:
        return CapabilityResult(
            status=ResultStatus.UNSUPPORTED,
            validation="valid",
            capability="unsupported",
            epistemic="not_applicable",
            coverage_status="out_of_model",
            identification="not_applicable",
            computation="not_applicable",
            diagnostics={"reason": "dummy has no semantic capability", "unsupported_scope": "all"},
        )

    def ingest(self, artifact):
        self.calls.append(("ingest", artifact))
        return self._result()

    def retract(self, source_id, known_at):
        self.calls.append(("retract", (source_id, known_at)))
        return self._result()

    def query(self, spec):
        self.calls.append(("query", spec))
        return self._result()

    def register_module(self, module):
        self.calls.append(("register_module", module))
        return self._result()


class _UnsupportedButCorrect(_AlwaysUnsupported):
    """Adversary: refusal axes plus an oracle-looking payload."""

    def _result(self) -> CapabilityResult:
        result = super()._result()
        return CapabilityResult(**{
            **asdict(result),
            "value_kind": "claims",
            "value": {"claims": [{"concept": "truth-token", "value": True}]},
        })


class _DeclaredKindUnsupported(_AlwaysUnsupported):
    """Manifest claims every kind, then explicitly denies the kind itself."""

    @property
    def manifest(self) -> CandidateManifest:
        return _BaseDummy.manifest.fget(self)  # type: ignore[attr-defined]

    def query(self, spec):
        self.calls.append(("query", spec))
        return CapabilityResult(
            status=ResultStatus.UNSUPPORTED,
            validation="valid",
            capability="unsupported",
            epistemic="not_applicable",
            coverage_status="out_of_model",
            identification="not_applicable",
            computation="not_applicable",
            diagnostics={"unsupported_query_kind": spec.kind.value},
        )


class _DeclaredContextuallyUnsupported(_DeclaredKindUnsupported):
    """The kind exists, but a requested guarantee is outside its coverage."""

    def query(self, spec):
        self.calls.append(("query", spec))
        return CapabilityResult(
            status=ResultStatus.UNSUPPORTED,
            validation="valid",
            capability="unsupported",
            epistemic="not_applicable",
            coverage_status="out_of_model",
            identification="not_applicable",
            computation="not_applicable",
            diagnostics={"unsupported_guarantees": ["fixture-specific-guarantee"]},
        )


class _ErrorKeyBoundary(_AlwaysUnsupported):
    def query(self, spec):
        self.calls.append(("query", spec))
        return CapabilityResult(
            status=ResultStatus.UNSUPPORTED,
            validation="valid",
            capability="unsupported",
            epistemic="not_applicable",
            coverage_status="out_of_model",
            identification="not_applicable",
            computation="not_applicable",
            diagnostics={"error": "closed candidate does not implement this query algebra"},
        )


class _SparseTrajectory(_CannedOK):
    def _result(self) -> CapabilityResult:
        return CapabilityResult(
            status=ResultStatus.OK,
            validation="valid",
            capability="native",
            epistemic="supported",
            coverage_status="in_domain",
            identification="not_applicable",
            computation="exact",
            value_kind="trajectory",
            value={"trajectory": [{"hour": 7, "B": 0.19584485123492185}]},
            native_witness={"kind": "closed-test-kernel"},
            diagnostics={"seed": 1103, "error": 0.0},
        )


class _FixedNumericalGarbage(_SparseTrajectory):
    """Complete coordinates and valid diagnostics, but no model semantics."""

    def _result(self) -> CapabilityResult:
        base = super()._result()
        return CapabilityResult(**{
            **asdict(base),
            "value": {
                "trajectory": [
                    {"hour": hour, "latent_state": 0.123456}
                    for hour in range(25)
                ],
            },
        })


class _QueryEcho(_CannedOK):
    def query(self, spec):
        self.calls.append(("query", spec))
        return CapabilityResult(
            status=ResultStatus.OK,
            validation="valid",
            capability="native",
            epistemic="supported",
            coverage_status="in_domain",
            identification="not_applicable",
            computation="exact",
            value_kind="query_echo",
            value={"target": spec.target, "task": spec.task, "kind": spec.kind.value},
            evidence_witness={},
            native_witness={},
        )


class _MaskedAware(_CannedOK):
    def __init__(self) -> None:
        super().__init__()
        self.artifact = None

    def ingest(self, artifact):
        self.calls.append(("ingest", artifact))
        self.artifact = artifact
        return CapabilityResult(
            status=ResultStatus.OK, validation="valid", capability="native",
            epistemic="not_applicable", coverage_status="in_domain",
            identification="not_applicable", computation="exact",
            value_kind="receipt", value={"accepted": artifact.source_id},
            native_witness={"kind": "append"},
        )

    def query(self, spec):
        self.calls.append(("query", spec))
        assert self.artifact is not None
        masked = self.artifact.information_state.value == "masked"
        return CapabilityResult(
            status=ResultStatus.INSUFFICIENT if masked else ResultStatus.OK,
            validation="valid", capability="native",
            epistemic="masked" if masked else "supported",
            coverage_status="in_domain", identification="not_applicable", computation="exact",
            value_kind="claims",
            value={"claims": [{
                "concept": self.artifact.concept,
                "information_state": self.artifact.information_state.value,
                "value": self.artifact.value,
                "root_sources": [self.artifact.source_id],
            }]},
            evidence_witness={"root_sources": [self.artifact.source_id]},
            native_witness={"kind": "typed-projection"},
            diagnostics={"reason": "source is intentionally masked"} if masked else {},
        )


class _CleanRebuildTrap(_CannedOK):
    clean_called = False

    def clean_rebuild(self):
        type(self).clean_called = True
        raise AssertionError("runner trusted candidate.clean_rebuild")


class WorkloadContractTests(unittest.TestCase):
    def test_exactly_50_t_and_8_e_files_are_independent(self) -> None:
        loaded = load_workloads()
        self.assertEqual(len(loaded), 58)
        self.assertEqual(sum(key.startswith("T") for key in loaded), 50)
        self.assertEqual(sum(key.startswith("E") for key in loaded), 8)
        self.assertEqual({f"T{i:02d}" for i in range(1, 51)}, {key for key in loaded if key.startswith("T")})
        self.assertEqual({f"E{i:02d}" for i in range(1, 9)}, {key for key in loaded if key.startswith("E")})
        for workload_id, workload in loaded.items():
            self.assertEqual(workload_id, workload["workload_id"])
            self.assertTrue((DEFAULT_WORKLOAD_ROOT / workload["panel"] / f"{workload_id}.json").is_file())
            self.assertTrue(workload["oracle_view"]["assertions"])
            self.assertTrue(workload["candidate_view"]["branches"])

    def test_checked_in_workloads_equal_deterministic_builders(self) -> None:
        self.assertEqual(load_workloads(), build_all_workloads())

    def test_candidate_view_physically_excludes_oracles(self) -> None:
        for workload in load_workloads().values():
            view = candidate_view(workload)
            encoded = json.dumps(view, sort_keys=True)
            self.assertNotIn("oracle_view", encoded)
            self.assertNotIn("assertion_id", encoded)
            self.assertNotIn("reference_path", encoded)
            self.assertNotIn('"expected"', encoded)

    def test_manifest_claim_and_canned_ok_cannot_pass_behavior(self) -> None:
        workload = load_workloads()["T12"]
        instances: list[_CannedOK] = []

        def factory() -> _CannedOK:
            instance = _CannedOK()
            instances.append(instance)
            return instance

        run = BenchmarkRunner(factory).run(workload)
        self.assertTrue(any(instance.calls for instance in instances), "runner did not call candidate")
        self.assertEqual(run.verdict.behavior, "fail")
        self.assertEqual(run.verdict.hard, "fail")
        self.assertNotEqual(run.verdict.classification, "PASS")
        json.loads(run.to_json())

    def test_universal_refusal_is_boundary_only_not_semantic_coverage(self) -> None:
        run = BenchmarkRunner(_AlwaysUnsupported).run(load_workloads()["T12"])
        self.assertEqual(run.verdict.boundary, "pass")
        self.assertEqual(run.verdict.behavior, "fail")
        self.assertEqual(run.verdict.hard, "fail")
        self.assertEqual(run.verdict.classification, "HONEST_UNSUPPORTED")

    def test_manifest_dishonesty_requires_query_kind_contradiction(self) -> None:
        workload = load_workloads()["T16"]
        contradiction = BenchmarkRunner(_DeclaredKindUnsupported).run(workload)
        self.assertEqual(contradiction.verdict.boundary, "pass")
        self.assertEqual(contradiction.verdict.classification, "DISHONEST_CLAIM")

        contextual = BenchmarkRunner(_DeclaredContextuallyUnsupported).run(workload)
        self.assertEqual(contextual.verdict.boundary, "pass")
        self.assertEqual(contextual.verdict.classification, "PASS")

    def test_typed_boundary_accepts_candidate_error_vocabulary(self) -> None:
        run = BenchmarkRunner(_ErrorKeyBoundary).run(load_workloads()["T16"])
        self.assertEqual(run.verdict.boundary, "pass")
        self.assertEqual(run.verdict.hard, "pass")

    def test_unsupported_result_with_correct_payload_cannot_pass_semantics(self) -> None:
        workload = deepcopy(load_workloads()["T12"])
        workload["oracle_view"]["assertions"] = [{
            "assertion_id": "payload-looks-correct",
            "oracle_id": "result.contains_all@1",
            "dimension": "safety",
            "hard_gate": True,
            "args": {"result": "main:late", "expected": ["truth-token"]},
        }]
        run = BenchmarkRunner(_UnsupportedButCorrect).run(workload)
        assertion = run.assertions[0]
        self.assertFalse(assertion.passed)
        self.assertFalse(assertion.semantic_eligible)
        self.assertIn("main:late", assertion.ineligible_refs)
        self.assertNotEqual(run.verdict.classification, "PASS")

    def test_sparse_or_duplicate_trajectory_cannot_pass_reference(self) -> None:
        workload = load_workloads()["E04"]
        sparse = BenchmarkRunner(_SparseTrajectory).run(workload)
        assertion = next(item for item in sparse.assertions if item.oracle_id == "reference.trajectory@1")
        self.assertFalse(assertion.passed)
        self.assertLess(assertion.observed["coverage"], 1.0)

        class Duplicate(_SparseTrajectory):
            def _result(self) -> CapabilityResult:
                base = super()._result()
                return CapabilityResult(**{
                    **asdict(base),
                    "value": {"trajectory": [
                        {"hour": 7, "B": 0.19584485123492185},
                        {"hour": 7, "B": 0.19584485123492185},
                    ]},
                })

        duplicate = BenchmarkRunner(Duplicate).run(workload)
        assertion = next(item for item in duplicate.assertions if item.oracle_id == "reference.trajectory@1")
        self.assertFalse(assertion.passed)
        self.assertTrue(assertion.observed["duplicates"])

    def test_t35_requires_recurrence_values_target_and_full_horizon(self) -> None:
        workload = load_workloads()["T35"]

        sparse = BenchmarkRunner(_SparseTrajectory).run(workload)
        assertion = next(
            item for item in sparse.assertions
            if item.oracle_id == "reference.closed_recurrence@1"
        )
        self.assertFalse(assertion.passed)
        self.assertLess(assertion.observed["coverage"], 1.0)
        self.assertNotEqual(sparse.verdict.classification, "PASS")

        garbage = BenchmarkRunner(_FixedNumericalGarbage).run(workload)
        assertion = next(
            item for item in garbage.assertions
            if item.oracle_id == "reference.closed_recurrence@1"
        )
        self.assertFalse(assertion.passed)
        self.assertEqual(assertion.observed["coverage"], 1.0)
        self.assertIn("rmse=", assertion.diagnostic)
        self.assertNotEqual(garbage.verdict.classification, "PASS")

    def test_query_echo_and_empty_ok_do_not_pass_key_workloads(self) -> None:
        echo = BenchmarkRunner(_QueryEcho).run(load_workloads()["T37"])
        self.assertNotEqual(echo.verdict.classification, "PASS")
        self.assertTrue(any(not item.semantic_eligible for item in echo.assertions))
        self.assertTrue(all("query_kind" not in call.result.get("diagnostics", {}) for call in echo.calls))

        empty = BenchmarkRunner(_CannedOK).run(load_workloads()["T12"])
        self.assertNotEqual(empty.verdict.classification, "PASS")
        self.assertTrue(any(not item.semantic_eligible for item in empty.assertions))

    def test_masked_typed_boundary_is_legal_when_workload_explicitly_allows_it(self) -> None:
        workload = deepcopy(load_workloads()["T50"])
        for assertion in workload["oracle_view"]["assertions"]:
            assertion["args"]["allow_ineligible_statuses"] = ["insufficient"]
        run = BenchmarkRunner(_MaskedAware).run(workload)
        self.assertEqual(run.verdict.hard, "pass")
        self.assertEqual(run.verdict.boundary, "pass")
        self.assertEqual(run.verdict.classification, "PASS")

    def test_hard_axis_is_not_applicable_when_no_hard_assertions(self) -> None:
        workload = deepcopy(load_workloads()["T12"])
        for assertion in workload["oracle_view"]["assertions"]:
            assertion["hard_gate"] = False
        run = BenchmarkRunner(_CannedOK).run(workload)
        self.assertEqual(run.verdict.hard, "not_applicable")
        self.assertNotEqual(run.verdict.classification, "PASS")

    def test_clean_rebuild_is_external_replay_not_candidate_method(self) -> None:
        _CleanRebuildTrap.clean_called = False
        run = BenchmarkRunner(_CleanRebuildTrap).run(load_workloads()["T24"])
        self.assertFalse(_CleanRebuildTrap.clean_called)
        self.assertFalse(run.harness_errors)
        self.assertTrue(any(call.op.startswith("rebuild_replay_") for call in run.calls))

    def test_semantic_comparison_alpha_renames_ids_but_keeps_versions_and_graph(self) -> None:
        left = {
            "claims": [{"claim_id": "claim-random-a", "mapping_version": "map-v1"}],
            "proofs": [{"proof_id": "proof-random-a", "premise_proof_ids": [], "claim_ids": ["claim-random-a"]}],
        }
        renamed = {
            "claims": [{"claim_id": "totally-different", "mapping_version": "map-v1"}],
            "proofs": [{"proof_id": "other-proof", "premise_proof_ids": [], "claim_ids": ["totally-different"]}],
        }
        self.assertEqual(_semantic(left), _semantic(renamed))

        wrong_version = deepcopy(renamed)
        wrong_version["claims"][0]["mapping_version"] = "map-v2"
        self.assertNotEqual(_semantic(left), _semantic(wrong_version))

        wrong_graph = deepcopy(renamed)
        wrong_graph["proofs"][0]["premise_proof_ids"] = ["other-proof"]
        self.assertNotEqual(_semantic(left), _semantic(wrong_graph))

    def test_every_oracle_is_registered_and_every_workload_calls_candidate(self) -> None:
        workloads = load_workloads()
        instances: list[_AlwaysUnsupported] = []

        def factory() -> _AlwaysUnsupported:
            instance = _AlwaysUnsupported()
            instances.append(instance)
            return instance

        runs = BenchmarkRunner(factory).run_panel(workloads)
        self.assertEqual(len(runs), 58)
        self.assertTrue(all(run.calls for run in runs.values()))
        diagnostics = [assertion.diagnostic for run in runs.values() for assertion in run.assertions]
        self.assertFalse(any("unregistered oracle" in item for item in diagnostics), diagnostics)
        self.assertFalse(any(run.harness_errors for run in runs.values()), {key: run.harness_errors for key, run in runs.items() if run.harness_errors})
        summary = summarize_runs(runs)
        json.dumps({"summary": summary, "runs": {key: run.to_dict() for key, run in runs.items()}}, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
