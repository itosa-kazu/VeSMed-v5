"""Reference/response model loaders for V5 diagnostic scoring.

This module owns data loading only. Runtime math stays in
``v5_joint_sde_case_test.py`` so the current PoC can evolve without another
large execution entrypoint.
"""
import json
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).parent.resolve()
HEALTH_REFERENCE_DIR = ROOT / "health_reference"
RESPONSE_MODEL_DIR = ROOT / "response_models"


def _read_json_files(directory):
    if not directory.exists():
        return []
    out = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_path"] = str(path)
        out.append(data)
    return out


@lru_cache(maxsize=1)
def load_health_reference():
    """Load formal no-active-disease reference modules."""
    modules = _read_json_files(HEALTH_REFERENCE_DIR)
    axis_distributions = {}
    covariance_groups = []
    modifier_modules = []
    for module in modules:
        module_id = module.get("module_id") or Path(module.get("_path", "")).stem
        for axis in module.get("axis_distributions") or []:
            axis_id = axis.get("axis_id")
            if not axis_id:
                continue
            item = dict(axis)
            item["_source"] = f"health_reference_manifold:{module_id}"
            axis_distributions[axis_id] = item
        for group in module.get("covariance_groups") or []:
            item = dict(group)
            item["_source"] = f"health_reference_manifold:{module_id}"
            covariance_groups.append(item)
        for modifier in module.get("modifier_modules") or []:
            item = dict(modifier)
            item["_source"] = f"health_reference_manifold:{module_id}"
            modifier_modules.append(item)
    return {
        "modules": modules,
        "axis_distributions": axis_distributions,
        "covariance_groups": covariance_groups,
        "modifier_modules": modifier_modules,
    }


def health_reference_axis_overrides():
    """Return axis_id -> runtime background override."""
    out = {}
    for axis_id, axis in load_health_reference()["axis_distributions"].items():
        baseline = axis.get("baseline_range")
        if not (isinstance(baseline, list) and len(baseline) >= 2):
            continue
        out[axis_id] = {
            "unit": axis.get("unit"),
            "baseline_range": (float(baseline[0]), float(baseline[1])),
            "log_scale": bool(axis.get("log_scale", False)),
            "category": axis.get("category"),
            "axis_role": axis.get("axis_role"),
            "parent_axis_id": axis.get("parent_axis_id"),
            "_source": axis.get("_source", "health_reference_manifold"),
        }
    return out


@lru_cache(maxsize=1)
def load_response_models():
    """Load reusable expected-response / response-gap model specs."""
    models = []
    for module in _read_json_files(RESPONSE_MODEL_DIR):
        module_id = module.get("model_id") or Path(module.get("_path", "")).stem
        module["model_id"] = module_id
        models.append(module)
    return tuple(models)


@lru_cache(maxsize=1)
def response_models_by_axis():
    out = {}
    for model in load_response_models():
        for response_axis in model.get("response_axes") or []:
            axis_id = response_axis.get("axis_id")
            if not axis_id:
                continue
            out.setdefault(axis_id, []).append((model, response_axis))
    return out


def response_model_axis_ids():
    return set(response_models_by_axis())
