from __future__ import annotations

import json
from pathlib import Path
import unittest

from runtime_v2.engine import RuntimeV2
from runtime_v2.schema import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"


def model_dict() -> dict:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


class GeometryIntegrityBoundaryTests(unittest.TestCase):
    def test_unchecked_internal_distance_cache_is_byte_and_query_exact(self) -> None:
        """The optimized lookup must differ only in repeated seal checking."""

        optimized = RuntimeV2(model_dict())
        reference = RuntimeV2(model_dict())

        # Recreate the previous behavior on one instance: every internal
        # distance lookup re-enters the public integrity-checked accessor.
        raw_stratum_lookup = reference._stratum_distance_unchecked
        raw_branch_lookup = reference._branch_distance_unchecked

        def legacy_stratum_lookup(source: str, target: str) -> float:
            reference._assert_runtime_spec_integrity()
            return raw_stratum_lookup(source, target)

        def legacy_branch_lookup(source: str, target: str) -> float:
            reference._assert_runtime_spec_integrity()
            return raw_branch_lookup(source, target)

        reference._stratum_distance_unchecked = legacy_stratum_lookup  # type: ignore[method-assign]
        reference._branch_distance_unchecked = legacy_branch_lookup  # type: ignore[method-assign]

        optimized_state = optimized.initialize([], cut=0)
        reference_state = reference.initialize([], cut=0)
        self.assertEqual(optimized_state.to_bytes(), reference_state.to_bytes())

        policies = [
            {"policy_id": "NO_NEW_ACTION", "start_actions": []},
            {
                "policy_id": "START_REDUCE_A",
                "start_actions": [
                    {"action_id": "ACTION_REDUCE_A", "dose": 1.0}
                ],
            },
        ]
        queries = (
            (optimized.diagnose(optimized_state), reference.diagnose(reference_state)),
            (
                optimized.forecast(optimized_state, horizon=2),
                reference.forecast(reference_state, horizon=2),
            ),
            (
                optimized.plan(optimized_state, policies, horizon=2),
                reference.plan(reference_state, policies, horizon=2),
            ),
        )
        for optimized_result, reference_result in queries:
            self.assertEqual(
                canonical_json_bytes(optimized_result),
                canonical_json_bytes(reference_result),
            )

    def test_internal_geometry_does_not_reenter_public_distance_boundary(self) -> None:
        runtime = RuntimeV2(model_dict())

        def unexpected_public_lookup(*_args: object, **_kwargs: object) -> float:
            raise AssertionError("internal geometry re-entered public distance boundary")

        runtime.stratum_distance = unexpected_public_lookup  # type: ignore[method-assign]
        runtime.branch_distance = unexpected_public_lookup  # type: ignore[method-assign]
        state = runtime.initialize([], cut=0)
        runtime.forecast(state, horizon=1)
        runtime.rollout(
            state,
            {
                "policy_id": "START_REDUCE_A",
                "start_actions": [
                    {"action_id": "ACTION_REDUCE_A", "dose": 1.0}
                ],
            },
            horizon=1,
        )

    def test_all_public_boundaries_still_fail_closed_after_spec_mutation(self) -> None:
        runtime = RuntimeV2(model_dict())
        state = runtime.initialize([], cut=0)
        runtime.spec["scope"]["horizon"]["value"] = 999

        calls = (
            lambda: runtime.diagnose(state),
            lambda: runtime.forecast(state, horizon=1),
            lambda: runtime.plan(
                state,
                [{"policy_id": "NO_NEW_ACTION", "start_actions": []}],
                horizon=1,
            ),
            lambda: runtime.branch_distance("PROCESS_A", "PROCESS_B"),
            lambda: runtime.stratum_distance(
                "stratum:PROCESS_A", "stratum:PROCESS_B"
            ),
        )
        for call in calls:
            with self.assertRaisesRegex(ValueError, "runtime model spec mutated"):
                call()


if __name__ == "__main__":
    unittest.main()
