import argparse
import json
import re
from pathlib import Path


def normalize_value(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, list):
        return 1.0 if value else 0.0
    if isinstance(value, dict):
        if isinstance(value.get("number"), (int, float)):
            return value["number"]
        if isinstance(value.get("low"), (int, float)) and isinstance(value.get("high"), (int, float)):
            return (value["low"] + value["high"]) / 2
        dimensions = [
            value.get("length"),
            value.get("width"),
            value.get("depth"),
            value.get("height"),
            value.get("diameter"),
        ]
        dimensions = [dim for dim in dimensions if isinstance(dim, (int, float))]
        if dimensions:
            return max(dimensions)
    if isinstance(value, str):
        match = re.fullmatch(r"\s*([<>]=?)?\s*1\s*:\s*(\d+(?:\.\d+)?)\s*", value)
        if match:
            if match.group(1) and match.group(1).startswith("<"):
                return 0.0
            return float(match.group(2))
        normalized = value.strip().lower()
        if normalized in {"normal", "negative", "absent", "none", "resistant"}:
            return 0.0
        if normalized in {"positive", "present", "detected", "significant", "susceptible"}:
            return 1.0
        if normalized:
            return 1.0
    return value


def normalize_unit(item, value):
    unit = item.get("unit")
    if unit:
        return unit
    raw_value = item.get("value")
    if isinstance(raw_value, str) and re.fullmatch(r"\s*1\s*:\s*\d+(?:\.\d+)?\s*", raw_value):
        return "titer_denominator"
    if isinstance(raw_value, str):
        return "qualitative_0_1"
    if isinstance(raw_value, list):
        return "present_absent_0_1"
    if isinstance(item.get("value"), bool) or isinstance(value, float) and value in (0.0, 1.0):
        return "present_absent_0_1"
    return unit


def flatten_items(items, prefix):
    flattened = []
    for idx, item in enumerate(items or []):
        if item.get("use_in_ranking") is False:
            continue
        axis_id = item.get("axis_id")
        if not axis_id:
            continue
        value = normalize_value(item.get("value"))
        out = {
            "axis_id": axis_id,
            "value": value,
            "use_in_ranking": True,
            "_blind_extraction_path": f"{prefix}[{idx}]",
        }
        unit = normalize_unit(item, value)
        if unit:
            out["unit"] = unit
        for key in (
            "time",
            "temporality",
            "source_section",
            "parent_axis_id",
            "source_text_value",
            "conversion_note",
        ):
            if key in item:
                out[key] = item[key]
        if isinstance(item.get("value"), (str, dict, list)) and "source_text_value" not in out:
            out["source_text_value"] = (
                json.dumps(item.get("value"), ensure_ascii=False)
                if isinstance(item.get("value"), (dict, list))
                else item.get("value")
            )
        flattened.append(out)
    return flattened


def record_only_items(extraction):
    items = []
    containers = [extraction]
    if isinstance(extraction.get("case"), dict):
        containers.append(extraction["case"])
    for container in containers:
        for key in ("record_only", "record_only_exclusions"):
            value = container.get(key)
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    if not isinstance(subvalue, list):
                        continue
                    for idx, item in enumerate(subvalue):
                        if isinstance(item, dict):
                            out = dict(item)
                            out["use_in_ranking"] = False
                            out.setdefault("_blind_extraction_path", f"case.{key}.{subkey}[{idx}]")
                            items.append(out)
                        else:
                            items.append(
                                {
                                    "description": str(item),
                                    "use_in_ranking": False,
                                    "_blind_extraction_path": f"case.{key}.{subkey}[{idx}]",
                                }
                            )
                continue
            if not isinstance(value, list):
                continue
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    out = dict(item)
                    out["use_in_ranking"] = False
                    out.setdefault("_blind_extraction_path", f"case.{key}[{idx}]")
                    items.append(out)
                else:
                    items.append(
                        {
                            "description": str(item),
                            "use_in_ranking": False,
                            "_blind_extraction_path": f"case.{key}[{idx}]",
                        }
                    )
    return items


def source_value(extraction, source, key):
    if source.get(key) or extraction.get(key):
        return source.get(key) or extraction.get(key)
    source_metadata = extraction.get("source_metadata")
    if isinstance(source_metadata, dict) and source_metadata.get(key):
        return source_metadata.get(key)
    metadata = extraction.get("metadata")
    if isinstance(metadata, dict) and metadata.get(key):
        return metadata.get(key)
    article_ids = extraction.get("article_ids")
    if isinstance(article_ids, dict):
        return article_ids.get(key)
    return None


def case_payload(extraction):
    case = extraction.get("case")
    return case if isinstance(case, dict) else extraction


def pick_patient(extraction, payload):
    for key in ("patient", "patient_demographics", "demographics"):
        value = extraction.get(key)
        if isinstance(value, dict):
            return value
    for key in ("patient", "patient_demographics", "demographics"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def pick_items(extraction, payload, key):
    aliases = {
        "observations": (
            "observations",
            "rankable_observations",
            "diagnosis_neutral_observations",
            "rankable_evidence",
        ),
        "risk_context": ("risk_context", "risk_factors", "background_context"),
    }.get(key, (key,))
    for alias in aliases:
        value = extraction.get(alias)
        if isinstance(value, list):
            return value
        value = payload.get(alias)
        if isinstance(value, list):
            return value
    patient = pick_patient(extraction, payload)
    for alias in aliases:
        value = patient.get(alias)
        if isinstance(value, list):
            return value
    return []


def scalar_field(value):
    if isinstance(value, dict):
        return value.get("value")
    return value


def derive_demographics_from_observations(items, age, sex):
    for item in items or []:
        axis_id = str(item.get("axis_id") or "").strip().lower()
        value = normalize_value(item.get("value"))
        if age is None and axis_id in {"age", "age_years", "patient_age_years"}:
            age = value
        if sex is None:
            raw = item.get("value")
            raw_text = str(raw).strip().lower() if raw is not None else ""
            if axis_id in {"male_sex_presence", "male_sex"} and value == 1.0:
                sex = "M"
            elif axis_id in {"female_sex_presence", "female_sex"} and (value == 1.0 or raw_text == "female"):
                sex = "F"
            elif axis_id in {"sex", "patient_sex"}:
                if raw_text in {"m", "male"}:
                    sex = "M"
                elif raw_text in {"f", "female"}:
                    sex = "F"
    return age, sex


def build_case(extraction, extraction_path, notes_path, expected):
    payload = case_payload(extraction)
    source = extraction.get("source") or extraction.get("source_metadata") or {}
    patient = pick_patient(extraction, payload)
    observation_items = pick_items(extraction, payload, "observations")
    risk_items = pick_items(extraction, payload, "risk_context")
    pmcid = source_value(extraction, source, "pmcid")
    sex = patient.get("sex")
    if isinstance(sex, str):
        sex_map = {"male": "M", "female": "F", "m": "M", "f": "F"}
        sex = sex_map.get(sex.lower(), sex)
    if sex is None and isinstance(patient.get("demographics"), dict):
        sex = scalar_field(patient["demographics"].get("sex"))
        if isinstance(sex, str):
            sex = {"male": "M", "female": "F", "m": "M", "f": "F"}.get(sex.lower(), sex)
    age = scalar_field(patient.get("age_years")) or scalar_field(patient.get("age"))
    if age is None and isinstance(patient.get("demographics"), dict):
        age = scalar_field(patient["demographics"].get("age_years")) or scalar_field(patient["demographics"].get("age"))
    age, sex = derive_demographics_from_observations(observation_items + risk_items, age, sex)

    case = {
        "case_id": f"{pmcid}_BLIND_FULLTEXT_PILOT",
        "source_pmid": source_value(extraction, source, "pmid"),
        "source_pmcid": pmcid,
        "source_url": source_value(extraction, source, "source_url"),
        "source_doi": source_value(extraction, source, "doi"),
        "source_access_method": {
            "blind_extraction_file": str(extraction_path).replace("\\", "/"),
            "source_notes_file": str(notes_path).replace("\\", "/") if notes_path else None,
            "ranking_copy_generation": "mechanical normalization from blind extraction; expected metadata added only in this ranking copy",
        },
        "demographics": {
            "age": age,
            "age_years": age,
            "sex": sex,
        },
        "snapshot_day": 0,
        "snapshot_label": "index presentation / early objective case data before treatment response and final discussion framing",
        "risk_context": flatten_items(risk_items, "case.risk_context"),
        "observations": flatten_items(observation_items, "case.observations"),
        "record_only": record_only_items(extraction),
        "audit_notes": [
            "Blind extraction source JSON does not contain expected_manifold, expected_manifolds, or disease_label_per_paper.",
            "Rankable observations were mechanically flattened from diagnosis-neutral axis_id items with use_in_ranking not false.",
        ],
        "expected_manifold": expected,
    }
    return case


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--extraction", required=True, type=Path)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    case = build_case(extraction, args.extraction, args.notes, args.expected)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
