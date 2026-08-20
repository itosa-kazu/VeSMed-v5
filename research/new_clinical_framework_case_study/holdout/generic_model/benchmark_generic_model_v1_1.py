#!/usr/bin/env python3
"""Case-blind wall/memory benchmark for the exact generic-model/1.1.0 pair."""

from __future__ import annotations

import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import tracemalloc
from typing import Callable


HERE = Path(__file__).resolve().parent
CASE_STUDY = HERE.parents[1]
PACK = HERE / "model_pack.json"
EVIDENCE = HERE.parent / "evidence" / "GENERIC_MODEL_V1_1_PERFORMANCE.json"

sys.path.insert(0, str(CASE_STUDY))
from runtime_v2 import RuntimeV2


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(function: Callable[[], object], repeats: int) -> dict[str, object]:
    samples = []
    for _ in range(repeats):
        gc.collect()
        start = time.perf_counter()
        function()
        samples.append(time.perf_counter() - start)
    return {
        "repeats": repeats,
        "samples_seconds": samples,
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
    }


def main() -> int:
    spec = json.loads(PACK.read_text(encoding="utf-8"))

    construction = measure(lambda: RuntimeV2(spec), repeats=5)
    runtime = RuntimeV2(spec)
    initialization = measure(lambda: runtime.initialize([], cut=0), repeats=3)
    state = runtime.initialize([], cut=0)
    diagnosis = measure(lambda: runtime.diagnose(state), repeats=5)
    forecast = measure(lambda: runtime.forecast(state, horizon=1), repeats=3)

    gc.collect()
    tracemalloc.start()
    memory_runtime = RuntimeV2(spec)
    memory_state = memory_runtime.initialize([], cut=0)
    memory_runtime.forecast(memory_state, horizon=1)
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    wire = state.to_dict()
    known_processes = len(spec["processes"])
    joint_hypotheses = len(
        wire["active_process_posterior"]["joint_hypotheses"]
    )
    unmodelled_process_dimension = 1
    expected_hypotheses = 2 ** (known_processes + unmodelled_process_dimension)
    result = {
        "benchmark_kind": "generic-model-1.1.0-case-blind-exact-runtime",
        "case_blind": True,
        "environment": {
            "cpu_count": os.cpu_count(),
            "implementation": platform.python_implementation(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "measurements": {
            "canonical_state_wire_bytes": len(state.to_bytes()),
            "construction": construction,
            "diagnosis": diagnosis,
            "forecast_horizon_1": forecast,
            "initialization": initialization,
            "python_current_allocated_bytes_after_traced_sequence": current_bytes,
            "python_peak_allocated_bytes_construct_initialize_forecast": peak_bytes,
        },
        "model_id": spec["model_id"],
        "model_pack_sha256": sha256(PACK),
        "model_version": spec["model_version"],
        "primary_holdout_inspected": False,
        "resource_boundary": (
            "Empirical measurement on this machine for the frozen 13-process "
            "scope; not a latency SLA and not extrapolatable to a larger atlas."
        ),
        "structural_counts": {
            "expected_exact_activation_hypotheses": expected_hypotheses,
            "joint_activation_hypotheses": joint_hypotheses,
            "known_processes": known_processes,
            "unmodelled_process_dimensions": unmodelled_process_dimension,
        },
        "status": "PASS" if joint_hypotheses == expected_hypotheses else "FAIL",
    }
    EVIDENCE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
