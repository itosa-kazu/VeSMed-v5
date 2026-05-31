import json
from pathlib import Path


DISTILL_DIR = Path("distillations")


PREGNANCY_REQUIRED_CONTEXT = {
    "D-AMNIOTIC-FLUID-EMBOLISM": ("pregnancy_or_postpartum_presence", 2.0),
    "D-CHORIOAMNIONITIS": ("pregnancy_context_probability", 2.0),
    "D-ECTOPIC-PREGNANCY": ("pregnancy_context_probability", 2.0),
    "D-HELLP-SYNDROME": ("pregnancy_or_postpartum_presence", 2.0),
    "D-PERIPARTUM-CARDIOMYOPATHY": ("pregnancy_or_postpartum_presence", 2.0),
    "D-PLACENTA-PREVIA": ("pregnancy_context_probability", 2.0),
    "D-PLACENTAL-ABRUPTION": ("pregnancy_context_probability", 2.0),
    "D-POSTPARTUM-ENDOMETRITIS": ("postpartum_day_since_delivery", 2.0),
    "D-POSTPARTUM-HEMORRHAGE-UTERINE-ATONY": ("postpartum_day_since_delivery", 2.0),
    "D-PREECLAMPSIA-ECLAMPSIA": ("pregnancy_or_postpartum_presence", 2.0),
    "D-SEPTIC-ABORTION": ("gestational_age_weeks", 2.0),
    "D-THREATENED-PRETERM-LABOR": ("gestational_age_weeks", 2.0),
    "D-UTERINE-RUPTURE": ("pregnancy_context_probability", 2.0),
}


def main():
    changed = []
    for disease_id, (axis_id, penalty) in PREGNANCY_REQUIRED_CONTEXT.items():
        path = DISTILL_DIR / f"v5_{disease_id}.json"
        if not path.exists():
            print(f"missing {path}")
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        axes = data.get("axes") or []
        target = next((axis for axis in axes if axis.get("axis_id") == axis_id), None)
        if target is None:
            print(f"{disease_id}: axis not found: {axis_id}")
            continue
        before = (
            target.get("required_context_support"),
            target.get("required_context_prior_penalty"),
        )
        target["required_context_support"] = True
        target["required_context_prior_penalty"] = penalty
        target.setdefault(
            "required_context_rationale",
            "This disease manifold requires active pregnancy or postpartum/peripartum context; without that context, nonspecific abdominal pain, hypertension, hemolysis, liver injury, fever, or shock should not make it rank high.",
        )
        after = (
            target.get("required_context_support"),
            target.get("required_context_prior_penalty"),
        )
        if before != after:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changed.append((disease_id, axis_id, before, after))

    for item in changed:
        print(f"updated {item[0]} {item[1]} {item[2]} -> {item[3]}")
    print(f"changed={len(changed)}")


if __name__ == "__main__":
    main()
