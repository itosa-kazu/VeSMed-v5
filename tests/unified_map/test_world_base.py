from __future__ import annotations

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.schema import VisibleHistory
from prototype.unified_map.worlds import (
    ActionSpec,
    ChannelSpec,
    CheckSpec,
    PrivateEpisode,
    PublicCatalog,
    WorldSplit,
)
from prototype.unified_map.worlds.randomness import (
    bernoulli,
    categorical,
    normal01,
    uniform01,
)


def catalog() -> PublicCatalog:
    return PublicCatalog(
        observations=(ChannelSpec("obs_0", valid_range=(-5.0, 5.0)),),
        actions=(ActionSpec("A1", {"dose": "number"}, cost=0.1),),
        checks=(CheckSpec("Q1", ("obs_0",), (0, 2), cost=0.05),),
        diagnostic_labels=("C0", "C1", "unknown"),
        horizons=(1, 4, 8),
    )


def episode(hidden: int) -> PrivateEpisode:
    public = VisibleHistory(
        events=(), as_of_available_at=0, catalog_digest=catalog().digest
    )
    return PrivateEpisode(
        case_key=f"judge-{hidden}",
        environment_key="judge-world",
        split=WorldSplit.SEALED_TEST,
        generator_seed=5 + hidden,
        public_history=public,
        hidden_state_at_cut={"mode": hidden},
        invariant_parameters={"parameter": hidden + 0.25},
        diagnostic_target={f"C{hidden}": 1.0},
        factual_future=[{"value": 10 * hidden}],
        action_propensities=[{"A1": 0.5}],
        factual_utility=float(-hidden),
        oracle_anchor={"all_policies": hidden},
    )


def test_catalog_is_candidate_semantics_without_world_or_test_id() -> None:
    wire = canonical_json_bytes(catalog().to_wire())
    assert b"world_id" not in wire
    assert b"test_id" not in wire
    assert b"case_id" not in wire
    assert catalog().digest.startswith("sha256:")


def test_catalog_rejects_dangling_check_channel() -> None:
    with pytest.raises(ProtocolViolation, match="unknown channels"):
        PublicCatalog(
            observations=(ChannelSpec("obs_0"),),
            actions=(),
            checks=(CheckSpec("Q1", ("missing",), (0, 0)),),
            diagnostic_labels=("C0",),
            horizons=(1,),
        )


def test_private_truth_is_absent_from_candidate_and_trainer_history() -> None:
    first = episode(0)
    second = episode(1)
    assert first.public_history.digest == second.public_history.digest
    assert (
        first.training_example().history.digest
        == second.training_example().history.digest
    )
    assert first.judge_case().hidden_state != second.judge_case().hidden_state


def test_counter_based_randomness_is_replayable_and_order_independent() -> None:
    first = normal01(123, "future-noise", 4, 2)
    _ = normal01(123, "unrelated", 999)
    second = normal01(123, "future-noise", 4, 2)
    assert first == second
    assert first != normal01(123, "future-noise", 4, 3)
    assert 0.0 < uniform01(123, "u") < 1.0
    assert isinstance(bernoulli(0.5, 123, "b"), bool)
    assert categorical((0.0, 1.0, 0.0), 123, "c") == 1
