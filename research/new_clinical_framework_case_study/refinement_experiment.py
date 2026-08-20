"""Deterministic shadow-world test for action-triggered local state refinement.

This module is deliberately independent of the VeSMed V5 runtime and of the
real-case replay engine.  It tests one narrow claim of the *new clinical
framework*: a state partition is relative to a declared action set, and a new
action may expose a dangerous collision that requires either a locally
observable split or an explicit ``UNIDENTIFIABLE`` result.

The world is finite and fully enumerated, so every counterfactual used below is
known by construction.  The numbers are synthetic utilities and have no
clinical interpretation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parent
RESULT_PATH = ROOT / "evidence" / "refinement_results.json"

TARGET_PARENT = "shared_branch/compensated"
UNAFFECTED_PARENT = "unrelated_branch/stable"
CHILD_A = f"{TARGET_PARENT}/response_subtype_a"
CHILD_B = f"{TARGET_PARENT}/response_subtype_b"

OLD_ACTIONS = ("wait", "support")
NEW_ACTION = "precision_treatment"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Scope:
    action_catalog: tuple[str, ...]
    check_catalog: tuple[str, ...]
    horizon: int = 1
    outcome: str = "synthetic_utility"
    tolerance: float = 0.0

    @property
    def digest(self) -> str:
        return sha256_json(asdict(self))


@dataclass(frozen=True)
class ShadowPatient:
    """A patient oracle used only for evaluating the synthetic experiment.

    ``hidden_subtype`` is never read by :func:`encode_old_state`.  It is the
    shadow world's withheld truth, analogous to an individual response type.
    """

    fixture_id: str
    parent_stratum: str
    hidden_subtype: str
    public_history: tuple[tuple[str, object], ...]
    check_result: str | None


@dataclass(frozen=True)
class CollisionWitness:
    state_signature: str
    patient_a: str
    patient_b: str
    action: str
    response_a: float
    response_b: float
    optimal_action_a: str
    optimal_action_b: str
    opposite_response: bool
    disjoint_optima: bool


@dataclass(frozen=True)
class RefinementRecord:
    from_scope_digest: str
    to_scope_digest: str
    affected_parent_strata: tuple[str, ...]
    child_strata: tuple[str, ...]
    discriminator_source: str
    migration_kernel: Mapping[str, Mapping[str, float]]
    preserved_old_queries: tuple[str, ...]
    unresolved_collision_classes: tuple[str, ...]
    status: str


def base_scope() -> Scope:
    return Scope(action_catalog=OLD_ACTIONS, check_catalog=())


def extended_scope(*, check_available: bool) -> Scope:
    checks = ("response_biomarker",) if check_available else ()
    return Scope(action_catalog=OLD_ACTIONS + (NEW_ACTION,), check_catalog=checks)


def build_target_pair(*, check_available: bool) -> tuple[ShadowPatient, ShadowPatient]:
    """Return two patients with identical public history and old state.

    If a public check exists, it is a *new* check and its result is not part of
    the old history/state.  It may be consumed only after explicit availability.
    """

    history = (
        ("branch", "shared_branch"),
        ("mode", "compensated"),
        ("disease_load", 0.4),
        ("reserve", 0.7),
        ("support_level", 0.2),
    )
    return (
        ShadowPatient("target-a", TARGET_PARENT, "A", history, "A" if check_available else None),
        ShadowPatient("target-b", TARGET_PARENT, "B", history, "B" if check_available else None),
    )


def build_unaffected_patient() -> ShadowPatient:
    return ShadowPatient(
        fixture_id="unaffected",
        parent_stratum=UNAFFECTED_PARENT,
        hidden_subtype="N",
        public_history=(("branch", "unrelated_branch"), ("mode", "stable"), ("reserve", 0.9)),
        check_result=None,
    )


def encode_old_state(patient: ShadowPatient) -> str:
    """Canonical old state signature, intentionally blind to fixture/subtype."""

    payload = {
        "parent_stratum": patient.parent_stratum,
        "public_history": list(patient.public_history),
        "scope_digest": base_scope().digest,
    }
    return sha256_json(payload)


def utility(patient: ShadowPatient, action: str) -> float:
    """Oracle utility table for the finite shadow world."""

    if patient.parent_stratum == UNAFFECTED_PARENT:
        return {"wait": 1.0, "support": 2.0, NEW_ACTION: 2.0}[action]
    if action == "wait":
        return 0.0
    if action == "support":
        return 2.0
    if action == NEW_ACTION:
        return 8.0 if patient.hidden_subtype == "A" else -8.0
    raise KeyError(action)


def optimal_action(patient: ShadowPatient, actions: Iterable[str]) -> str:
    # Stable tie breaking is part of the experiment contract.
    return max(actions, key=lambda action: (utility(patient, action), -tuple(actions).index(action)))


def old_state_is_sufficient(cohort: Iterable[ShadowPatient]) -> bool:
    """Check behavioral equivalence under the frozen old action catalogue."""

    groups: dict[str, list[ShadowPatient]] = {}
    for patient in cohort:
        groups.setdefault(encode_old_state(patient), []).append(patient)
    for patients in groups.values():
        reference = tuple(utility(patients[0], action) for action in OLD_ACTIONS)
        if any(tuple(utility(p, action) for action in OLD_ACTIONS) != reference for p in patients[1:]):
            return False
    return True


def find_new_action_collisions(cohort: Iterable[ShadowPatient]) -> list[CollisionWitness]:
    """Freeze exact same-state/opposite-response witnesses for the new action."""

    groups: dict[str, list[ShadowPatient]] = {}
    for patient in cohort:
        groups.setdefault(encode_old_state(patient), []).append(patient)
    witnesses: list[CollisionWitness] = []
    actions = OLD_ACTIONS + (NEW_ACTION,)
    for state_signature, patients in groups.items():
        for i, left in enumerate(patients):
            for right in patients[i + 1 :]:
                response_left = utility(left, NEW_ACTION) - utility(left, "support")
                response_right = utility(right, NEW_ACTION) - utility(right, "support")
                optimum_left = optimal_action(left, actions)
                optimum_right = optimal_action(right, actions)
                opposite = response_left * response_right < 0
                disjoint = optimum_left != optimum_right
                if opposite or disjoint:
                    witnesses.append(
                        CollisionWitness(
                            state_signature=state_signature,
                            patient_a=left.fixture_id,
                            patient_b=right.fixture_id,
                            action=NEW_ACTION,
                            response_a=response_left,
                            response_b=response_right,
                            optimal_action_a=optimum_left,
                            optimal_action_b=optimum_right,
                            opposite_response=opposite,
                            disjoint_optima=disjoint,
                        )
                    )
    return witnesses


def child_posterior(
    patient: ShadowPatient,
    *,
    check_catalog_contains_biomarker: bool,
    result_is_available: bool,
) -> tuple[str, dict[str, float]]:
    """Return refinement status and a child-stratum posterior.

    Before availability, even an ordered check cannot influence the posterior.
    Without any observable discriminator, the correct status is
    ``UNIDENTIFIABLE`` rather than a guessed child assignment.
    """

    if patient.parent_stratum != TARGET_PARENT:
        return "NOT_AFFECTED", {patient.parent_stratum: 1.0}
    prior = {CHILD_A: 0.5, CHILD_B: 0.5}
    if not check_catalog_contains_biomarker:
        return "UNIDENTIFIABLE", prior
    if not result_is_available:
        return "AWAITING_PUBLIC_CHECK", prior
    if patient.check_result == "A":
        return "IDENTIFIED_BY_PUBLIC_CHECK", {CHILD_A: 1.0, CHILD_B: 0.0}
    if patient.check_result == "B":
        return "IDENTIFIED_BY_PUBLIC_CHECK", {CHILD_A: 0.0, CHILD_B: 1.0}
    return "UNIDENTIFIABLE", prior


def expected_utility(posterior: Mapping[str, float], action: str) -> float:
    child_utility = {
        CHILD_A: {"wait": 0.0, "support": 2.0, NEW_ACTION: 8.0},
        CHILD_B: {"wait": 0.0, "support": 2.0, NEW_ACTION: -8.0},
        UNAFFECTED_PARENT: {"wait": 1.0, "support": 2.0, NEW_ACTION: 2.0},
    }
    return sum(probability * child_utility[child][action] for child, probability in posterior.items())


def plan_from_posterior(posterior: Mapping[str, float], actions: tuple[str, ...]) -> str:
    return max(actions, key=lambda action: (expected_utility(posterior, action), -actions.index(action)))


def cohort_regret(
    cohort: Iterable[ShadowPatient],
    *,
    check_available: bool,
    result_is_available: bool,
) -> tuple[float, list[str], list[str]]:
    actions = OLD_ACTIONS + (NEW_ACTION,)
    total_regret = 0.0
    statuses: list[str] = []
    choices: list[str] = []
    cohort_list = list(cohort)
    for patient in cohort_list:
        status, posterior = child_posterior(
            patient,
            check_catalog_contains_biomarker=check_available,
            result_is_available=result_is_available,
        )
        choice = plan_from_posterior(posterior, actions)
        oracle = max(utility(patient, action) for action in actions)
        total_regret += oracle - utility(patient, choice)
        statuses.append(status)
        choices.append(choice)
    return total_regret / len(cohort_list), statuses, choices


def old_query_fingerprint(cohort: Iterable[ShadowPatient]) -> str:
    """Digest of every frozen old-action answer, used for non-regression."""

    rows = []
    for patient in sorted(cohort, key=lambda item: item.fixture_id):
        rows.append(
            {
                "patient": patient.fixture_id,
                "state": encode_old_state(patient),
                "old_actions": {action: utility(patient, action) for action in OLD_ACTIONS},
            }
        )
    return sha256_json(rows)


def make_refinement_record(*, check_available: bool) -> RefinementRecord:
    before = base_scope()
    after = extended_scope(check_available=check_available)
    if check_available:
        status = "LOCALLY_REFINED"
        discriminator = "new_public_check"
        unresolved: tuple[str, ...] = ()
    else:
        status = "SCOPE_INSUFFICIENT_UNIDENTIFIABLE"
        discriminator = "none_available"
        unresolved = ("new_action_opposite_response_without_pretreatment_discriminator",)
    return RefinementRecord(
        from_scope_digest=before.digest,
        to_scope_digest=after.digest,
        affected_parent_strata=(TARGET_PARENT,),
        child_strata=(CHILD_A, CHILD_B),
        discriminator_source=discriminator,
        migration_kernel={TARGET_PARENT: {CHILD_A: 0.5, CHILD_B: 0.5}},
        preserved_old_queries=tuple(f"utility:{action}" for action in OLD_ACTIONS),
        unresolved_collision_classes=unresolved,
        status=status,
    )


def run_experiment() -> dict[str, object]:
    observable_pair = build_target_pair(check_available=True)
    unobservable_pair = build_target_pair(check_available=False)
    unaffected = build_unaffected_patient()

    old_cohort = observable_pair + (unaffected,)
    old_fingerprint_before = old_query_fingerprint(old_cohort)
    witnesses = find_new_action_collisions(old_cohort)

    regret_before_result, pre_statuses, pre_choices = cohort_regret(
        observable_pair, check_available=True, result_is_available=False
    )
    regret_after_result, post_statuses, post_choices = cohort_regret(
        observable_pair, check_available=True, result_is_available=True
    )
    regret_unobservable, unobservable_statuses, unobservable_choices = cohort_regret(
        unobservable_pair, check_available=False, result_is_available=False
    )

    # Refinement changes the scope metadata and local child posterior; it is not
    # allowed to mutate the old utility queries or the unrelated parent stratum.
    old_fingerprint_after = old_query_fingerprint(old_cohort)
    unaffected_before = child_posterior(
        unaffected, check_catalog_contains_biomarker=False, result_is_available=False
    )
    unaffected_after = child_posterior(
        unaffected, check_catalog_contains_biomarker=True, result_is_available=True
    )

    observable_record = make_refinement_record(check_available=True)
    unobservable_record = make_refinement_record(check_available=False)
    return {
        "experiment_id": "new-framework-shadow-local-refinement-v1",
        "independence_boundary": {
            "uses_v5": False,
            "uses_real_case_outcomes": False,
            "interpretation": "finite synthetic architecture test only",
        },
        "scope": {
            "base": {**asdict(base_scope()), "digest": base_scope().digest},
            "extended_observable": {
                **asdict(extended_scope(check_available=True)),
                "digest": extended_scope(check_available=True).digest,
            },
            "extended_unobservable": {
                **asdict(extended_scope(check_available=False)),
                "digest": extended_scope(check_available=False).digest,
            },
        },
        "base_scope": {
            "same_old_state": encode_old_state(observable_pair[0]) == encode_old_state(observable_pair[1]),
            "old_state_sufficient_for_old_actions": old_state_is_sufficient(old_cohort),
            "old_best_action_both_subtypes": [
                optimal_action(patient, OLD_ACTIONS) for patient in observable_pair
            ],
            "classification": "STRUCTURALLY_SUPPORTED",
        },
        "new_action_collision": {
            "count": len(witnesses),
            "witnesses": [asdict(witness) for witness in witnesses],
            "classification": "STRUCTURALLY_SUPPORTED" if witnesses else "FAILED",
        },
        "observable_refinement": {
            "record": asdict(observable_record),
            "before_result": {
                "statuses": pre_statuses,
                "choices": pre_choices,
                "mean_oracle_regret": regret_before_result,
            },
            "after_result": {
                "statuses": post_statuses,
                "choices": post_choices,
                "mean_oracle_regret": regret_after_result,
            },
            "regret_reduction": regret_before_result - regret_after_result,
            "old_query_non_regression": old_fingerprint_before == old_fingerprint_after,
            "unaffected_stratum_unchanged": unaffected_before == unaffected_after,
            "classification": "STRUCTURALLY_SUPPORTED",
        },
        "unobservable_refinement": {
            "record": asdict(unobservable_record),
            "statuses": unobservable_statuses,
            "choices": unobservable_choices,
            "mean_oracle_regret": regret_unobservable,
            "forced_child_assignment": False,
            "individual_treatment_direction_identified": False,
            "classification": "UNIDENTIFIABLE",
        },
        "conclusion_boundary": (
            "The experiment supports the local-refinement control flow in a finite shadow world. "
            "It does not prove a universal, finite, or clinically calibrated patient-state model."
        ),
    }


def write_results(path: Path = RESULT_PATH) -> dict[str, object]:
    # Normalize tuples to JSON arrays so the in-memory return value and the
    # persisted artifact have exactly the same canonical data model.
    results = json.loads(json.dumps(run_experiment(), ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    output = write_results()
    print(json.dumps(output, ensure_ascii=False, indent=2))
