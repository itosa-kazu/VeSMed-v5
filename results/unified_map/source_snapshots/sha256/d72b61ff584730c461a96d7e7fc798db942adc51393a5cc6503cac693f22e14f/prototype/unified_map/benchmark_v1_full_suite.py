"""Run several frozen-v1 complete candidates against one judge-side oracle cache."""

from __future__ import annotations

import argparse
from pathlib import Path

from .benchmark_v1_runner import complete_config, run_benchmark
from .canonical import ProtocolViolation


def _experiment(value: str) -> tuple[str, str]:
    parts = value.split(":")
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError("experiment must be EXPERIMENT_ID:FAMILY_CODE")
    return parts[0], parts[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a complete UCM benchmark suite with shared judge computation"
    )
    parser.add_argument("--secret", type=Path, required=True)
    parser.add_argument(
        "--experiment",
        action="append",
        type=_experiment,
        required=True,
        help="repeatable EXPERIMENT_ID:FAMILY_CODE",
    )
    args = parser.parse_args()
    seen: set[str] = set()
    for experiment_id, family_code in args.experiment:
        if experiment_id in seen:
            raise ProtocolViolation("suite experiment ids must be unique")
        seen.add(experiment_id)
        print(f"START {experiment_id} {family_code}", flush=True)
        path = run_benchmark(
            complete_config(experiment_id, family_code), secret_path=args.secret
        )
        print(f"DONE {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

